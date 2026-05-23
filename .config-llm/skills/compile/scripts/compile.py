#!/usr/bin/env python3
"""
compile.py — Orchestrator deterministic core for /compile.

The interactive ingest loop is owned by the LLM agent reading SKILL.md.
This script provides the deterministic pieces the agent needs:

    --scan-only       Walk raw/ + notes/, classify each file as
                      NEW/MODIFIED/SYNC/DRIFT against wiki/sources/,
                      and emit a manifest JSON to stdout.

    --from <path>     Same classification but for a single file path.
                      Includes extracted highlights and a fallback
                      extractive takeaway (for non-LLM use).

    --wrap-up <file>  Read a changes JSON (produced by the agent during
                      Phase 3) and apply Phase 4: update wiki/index.md,
                      wiki/log.md, wiki/hot.md, and auto-tick liste in
                      notes/lists/.

    --dry-run         Alias for --scan-only.

No LLM. Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path


# --- Constants --------------------------------------------------------------

SCAN_RAW_DIR = "raw"
SCAN_NOTES_DIR = "notes"
SOURCES_DIR = "wiki/sources"
INDEX_FILE = "wiki/index.md"
LOG_FILE = "wiki/log.md"
HOT_FILE = "wiki/hot.md"
LISTS_DIR = "notes/lists"

SUBSTANTIAL_DIFF_THRESHOLD = 0.30
SCAN_GATE = 15

HIGHLIGHT_RE = re.compile(r"==([^=].*?)==", re.DOTALL)
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
HEADING_TOP_RE = re.compile(r"^# ", re.MULTILINE)


# --- Data types -------------------------------------------------------------

@dataclass
class SourceFile:
    rel: str                 # vault-relative path
    abs_path: str
    content_hash: str        # current sha256 of content
    is_binary: bool = False
    size_bytes: int = 0


@dataclass
class SourcePage:
    rel: str                 # wiki/sources/<slug>.md
    source_path: str | None  # what raw/notes file it tracks
    content_hash: str | None # expected hash from frontmatter
    is_versioned: bool = False


@dataclass
class ManifestItem:
    state: str               # NEW | MODIFIED_INCREMENTAL | MODIFIED_SUBSTANTIAL | SYNC | DRIFT
    source_path: str
    source_page: str | None  # rel path if applicable
    diff_ratio: float | None = None
    structural_change: bool = False
    highlights: list[dict] = field(default_factory=list)


# --- Utilities --------------------------------------------------------------

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_probably_binary(path: Path) -> bool:
    """Quick heuristic: read first 4KB, check for null bytes."""
    try:
        with path.open("rb") as f:
            chunk = f.read(4096)
        return b"\x00" in chunk
    except OSError:
        return True


def parse_frontmatter(text: str) -> dict:
    """Minimal YAML scalar parser. Reuses logic compatible with vault-linter."""
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    block = match.group(1)
    fm: dict = {}
    for line in block.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            fm[key] = [x.strip().strip("\"'") for x in inner.split(",") if x.strip()]
            continue
        if (value.startswith('"') and value.endswith('"')) or \
           (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        fm[key] = value
    return fm


def extract_highlights(text: str) -> list[dict]:
    """Find ==text== markers; return list of {id, text} with stable IDs."""
    out: list[dict] = []
    for i, m in enumerate(HIGHLIGHT_RE.finditer(text), start=1):
        out.append({"id": f"H{i}", "text": m.group(1).strip()})
    return out


def fallback_takeaway(text: str, highlights: list[dict], max_sentences: int = 3) -> str:
    """Extractive takeaway: first N non-trivial sentences + bullet on highlights.
    Used when LLM is not driving (smoke tests, direct CLI runs)."""
    # Strip frontmatter
    body = FRONTMATTER_RE.sub("", text, count=1)
    # Strip markdown noise minimally
    body = re.sub(r"^#+\s+.*$", "", body, flags=re.MULTILINE)
    body = re.sub(r"==(.+?)==", r"\1", body)
    body = re.sub(r"\[\[(.+?)\]\]", r"\1", body)
    # Sentence split (very rough)
    sentences = re.split(r"(?<=[.!?])\s+", body)
    picked = []
    for s in sentences:
        s = s.strip()
        if len(s) < 30:
            continue
        picked.append(s)
        if len(picked) >= max_sentences:
            break

    lines = []
    if picked:
        lines.append("Takeaway (estrazione automatica — sostituire con sintesi reale):")
        for s in picked:
            lines.append(f"• {s}")
    else:
        lines.append("Takeaway: (testo troppo corto per sintesi estrattiva)")
    if highlights:
        lines.append("")
        lines.append("Highlights:")
        for h in highlights[:3]:
            lines.append(f"  {h['id']}: \"{h['text'][:80]}\"")
    return "\n".join(lines)


def load_source_pages(vault: Path) -> dict[str, SourcePage]:
    """Index every wiki/sources/*.md by their source_path."""
    out: dict[str, SourcePage] = {}
    sources_dir = vault / SOURCES_DIR
    if not sources_dir.is_dir():
        return out
    for md in sources_dir.rglob("*.md"):
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm = parse_frontmatter(text)
        if fm.get("type") != "source":
            continue
        sp = fm.get("source_path")
        if isinstance(sp, list):
            continue
        if not isinstance(sp, str) or not sp:
            continue
        # back-compat: prefer content_hash, fallback to raw_sha256
        ch = fm.get("content_hash") or fm.get("raw_sha256")
        if isinstance(ch, list):
            ch = ch[0] if ch else None
        page = SourcePage(
            rel=md.relative_to(vault).as_posix(),
            source_path=sp,
            content_hash=ch.strip() if isinstance(ch, str) else None,
            is_versioned=bool(fm.get("supersedes") and str(fm.get("supersedes")).lower() not in ("null", "none", "")),
        )
        # Index by source_path; if multiple source pages point at same file
        # (versioning), keep the most-recently-modified one for state lookup.
        if sp in out:
            existing = vault / out[sp].rel
            try:
                if md.stat().st_mtime > existing.stat().st_mtime:
                    out[sp] = page
            except OSError:
                pass
        else:
            out[sp] = page
    return out


def walk_inputs(vault: Path) -> list[SourceFile]:
    """Walk raw/ and notes/, compute hash for each file."""
    out: list[SourceFile] = []
    for root_name in (SCAN_RAW_DIR, SCAN_NOTES_DIR):
        root = vault / root_name
        if not root.is_dir():
            continue
        for f in root.rglob("*"):
            if not f.is_file():
                continue
            # Skip hidden files / .gitkeep
            if f.name.startswith("."):
                continue
            try:
                data = f.read_bytes()
            except OSError:
                continue
            out.append(SourceFile(
                rel=f.relative_to(vault).as_posix(),
                abs_path=str(f.resolve()),
                content_hash=sha256_bytes(data),
                is_binary=is_probably_binary(f),
                size_bytes=len(data),
            ))
    return out


def classify_modification(old_text: str, new_text: str) -> tuple[float, bool]:
    """Return (diff_ratio, structural_change).

    diff_ratio: 1.0 - SequenceMatcher.ratio() on character sequences,
                bounded [0, 1]. ≥ SUBSTANTIAL_DIFF_THRESHOLD = substantial.
    structural_change: top-level heading count differs.
    """
    ratio = SequenceMatcher(a=old_text, b=new_text, autojunk=False).ratio()
    diff = max(0.0, min(1.0, 1.0 - ratio))
    old_h = len(HEADING_TOP_RE.findall(old_text))
    new_h = len(HEADING_TOP_RE.findall(new_text))
    structural = (old_h != new_h)
    return diff, structural


def build_manifest(vault: Path) -> dict:
    """Compute the scan manifest. Returns JSON-serializable dict."""
    sources = load_source_pages(vault)
    files = walk_inputs(vault)

    # Build inverse: source_path → SourceFile (for DRIFT detection)
    seen_paths: set[str] = {sf.rel for sf in files}

    items: list[ManifestItem] = []

    for sf in files:
        src_page = sources.get(sf.rel)
        if src_page is None:
            # NEW
            text = ""
            if not sf.is_binary:
                try:
                    text = Path(sf.abs_path).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    pass
            items.append(ManifestItem(
                state="NEW",
                source_path=sf.rel,
                source_page=None,
                highlights=extract_highlights(text),
            ))
            continue

        if src_page.content_hash and src_page.content_hash == sf.content_hash:
            items.append(ManifestItem(
                state="SYNC",
                source_path=sf.rel,
                source_page=src_page.rel,
            ))
            continue

        # MODIFIED
        diff_ratio = None
        structural = False
        highlights: list[dict] = []
        if not sf.is_binary:
            try:
                new_text = Path(sf.abs_path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                new_text = ""
            highlights = extract_highlights(new_text)
            # We don't have the old text; approximate with source page body
            try:
                old_text = (vault / src_page.rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                old_text = ""
            diff_ratio, structural = classify_modification(old_text, new_text)

        if diff_ratio is not None and (diff_ratio >= SUBSTANTIAL_DIFF_THRESHOLD or structural):
            state = "MODIFIED_SUBSTANTIAL"
        else:
            state = "MODIFIED_INCREMENTAL"
        items.append(ManifestItem(
            state=state,
            source_path=sf.rel,
            source_page=src_page.rel,
            diff_ratio=diff_ratio,
            structural_change=structural,
            highlights=highlights,
        ))

    # DRIFT: source pages whose source_path no longer exists
    for src_path, src_page in sources.items():
        if src_path not in seen_paths:
            items.append(ManifestItem(
                state="DRIFT",
                source_path=src_path,
                source_page=src_page.rel,
            ))

    # Tallies
    counts: dict[str, int] = defaultdict(int)
    for it in items:
        counts[it.state] += 1

    gate_count = counts.get("NEW", 0) + counts.get("MODIFIED_INCREMENTAL", 0) + counts.get("MODIFIED_SUBSTANTIAL", 0)
    gate_exceeded = gate_count > SCAN_GATE

    return {
        "vault": str(vault),
        "scanned_at": datetime.now().isoformat(timespec="seconds"),
        "counts": dict(counts),
        "gate_exceeded": gate_exceeded,
        "gate_threshold": SCAN_GATE,
        "items": [asdict(it) for it in items],
    }


# --- Wrap-up: index, log, hot, auto-tick liste -----------------------------

def update_log(vault: Path, log_entries: list[dict]) -> None:
    """Append entries to wiki/log.md. Each entry is a dict with at minimum
    `op` (ingest|sync|forget|canvas|query|lint), `slug`, and optional
    `detail` lines."""
    log_path = vault / LOG_FILE
    today = date.today().isoformat()
    lines: list[str] = []
    for entry in log_entries:
        op = entry.get("op", "ingest")
        slug = entry.get("slug", "")
        # Pad op to 6 chars to align column
        op_padded = (op + "      ")[:6]
        lines.append(f"## [{today}] {op_padded} | {slug}")
        for k, v in entry.items():
            if k in ("op", "slug"):
                continue
            if v is None or v == "":
                continue
            lines.append(f"{k}: {v}")
        lines.append("")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    existing = log_path.read_text(encoding="utf-8") if log_path.exists() else "# Wiki Log\n\nAppend-only operations log.\n\n"
    log_path.write_text(existing.rstrip() + "\n\n" + "\n".join(lines).rstrip() + "\n",
                        encoding="utf-8")


def update_index(vault: Path, index_updates: list[dict]) -> None:
    """Apply a list of index updates. Each update has:
        {section: 'Concepts'|'Sources'|'Canvas'|...,
         entry: '- [[slug]] — description'}

    Naive append: ensure the section heading exists, then append the entry
    if it's not already there.
    """
    index_path = vault / INDEX_FILE
    if not index_path.exists():
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text("# Wiki Index\n\n", encoding="utf-8")
    text = index_path.read_text(encoding="utf-8")

    for upd in index_updates:
        section = upd.get("section")
        entry = upd.get("entry")
        if not section or not entry:
            continue
        section_header = f"## {section}"
        if section_header not in text:
            text = text.rstrip() + f"\n\n{section_header}\n\n{entry}\n"
            continue
        if entry in text:
            continue
        # Insert under the section header
        lines = text.splitlines()
        out_lines: list[str] = []
        inserted = False
        for i, line in enumerate(lines):
            out_lines.append(line)
            if line.strip() == section_header and not inserted:
                # Find end of section (blank line then next ## or EOF)
                # Insert immediately after blank line following header
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    out_lines.append(lines[j])
                    j += 1
                # Skip to end of this section's entries
                while j < len(lines) and not lines[j].startswith("## "):
                    out_lines.append(lines[j])
                    j += 1
                # Insert entry before next section
                if out_lines and out_lines[-1].strip():
                    out_lines.append("")
                out_lines.append(entry)
                # Continue from where we stopped
                lines = lines[j:]
                inserted = True
                break
        if not inserted:
            text = text.rstrip() + f"\n{entry}\n"
        else:
            text = "\n".join(out_lines + lines) + "\n"

    index_path.write_text(text, encoding="utf-8")


def rewrite_hot(vault: Path, hot_text: str) -> None:
    """Rewrite wiki/hot.md from scratch (5-10 line resume cache)."""
    hot_path = vault / HOT_FILE
    hot_path.parent.mkdir(parents=True, exist_ok=True)
    hot_path.write_text(hot_text.rstrip() + "\n", encoding="utf-8")


def auto_tick_lists(vault: Path, ingested_items: list[dict]) -> list[dict]:
    """For each ingested item, search notes/lists/*.md for matching
    `- [ ] <url>` or `- [ ] <title>` lines. Return list of proposed
    changes [{file, line, before, after}] — does NOT apply them. The
    agent shows the proposals and asks for confirmation.

    Each ingested_item has: {url, title, slug}.
    """
    lists_dir = vault / LISTS_DIR
    if not lists_dir.is_dir():
        return []
    proposals: list[dict] = []
    for md in lists_dir.rglob("*.md"):
        try:
            lines = md.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for idx, line in enumerate(lines):
            if not re.match(r"^\s*-\s*\[\s\]", line):
                continue
            for item in ingested_items:
                url = item.get("url") or ""
                title = item.get("title") or ""
                if url and url in line:
                    new_line = re.sub(r"\[\s\]", "[x]", line, count=1)
                    proposals.append({
                        "file": md.relative_to(vault).as_posix(),
                        "line": idx + 1,
                        "before": line,
                        "after": new_line,
                        "match": "url",
                        "ingested_slug": item.get("slug"),
                    })
                    continue
                if title and len(title) > 5:
                    # Fuzzy title match
                    ratio = SequenceMatcher(a=title.lower(), b=line.lower(), autojunk=False).ratio()
                    if ratio >= 0.85:
                        new_line = re.sub(r"\[\s\]", "[x]", line, count=1)
                        proposals.append({
                            "file": md.relative_to(vault).as_posix(),
                            "line": idx + 1,
                            "before": line,
                            "after": new_line,
                            "match": f"title (fuzzy={ratio:.2f})",
                            "ingested_slug": item.get("slug"),
                        })
    return proposals


def apply_list_ticks(vault: Path, approved: list[dict]) -> int:
    """Apply approved list-tick changes. Returns count applied."""
    by_file: dict[str, list[dict]] = defaultdict(list)
    for p in approved:
        by_file[p["file"]].append(p)
    count = 0
    for file_rel, changes in by_file.items():
        path = vault / file_rel
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for ch in changes:
            idx = ch["line"] - 1
            if 0 <= idx < len(lines) and lines[idx] == ch["before"]:
                lines[idx] = ch["after"]
                count += 1
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return count


def apply_wrap_up(vault: Path, changes: dict) -> dict:
    """Apply Phase 4 changes.

    Expected `changes` structure:
        {
          "log_entries": [{op, slug, source, content_hash, ...}, ...],
          "index_updates": [{section, entry}, ...],
          "hot_text": "string with the new hot.md content",
          "list_tick_approved": [proposal-dicts, ...],
        }
    Returns: {"log_entries": N, "index_updates": M, "hot_updated": bool,
              "list_ticks": K}
    """
    log_entries = changes.get("log_entries", [])
    index_updates = changes.get("index_updates", [])
    hot_text = changes.get("hot_text")
    approved_ticks = changes.get("list_tick_approved", [])

    if log_entries:
        update_log(vault, log_entries)
    if index_updates:
        update_index(vault, index_updates)
    if hot_text is not None:
        rewrite_hot(vault, hot_text)
    n_ticks = apply_list_ticks(vault, approved_ticks) if approved_ticks else 0

    return {
        "log_entries": len(log_entries),
        "index_updates": len(index_updates),
        "hot_updated": hot_text is not None,
        "list_ticks": n_ticks,
    }


# --- CLI orchestration ------------------------------------------------------

def cmd_scan_only(vault: Path) -> int:
    manifest = build_manifest(vault)
    json.dump(manifest, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


def cmd_from(vault: Path, target: Path) -> int:
    """Show classification for a single file. Useful for /compile --from."""
    if not target.exists():
        print(f"ERROR: {target} does not exist", file=sys.stderr)
        return 1
    try:
        rel = target.resolve().relative_to(vault.resolve()).as_posix()
    except ValueError:
        print(f"ERROR: {target} is not inside vault {vault}", file=sys.stderr)
        return 1

    full_manifest = build_manifest(vault)
    matching = [it for it in full_manifest["items"] if it["source_path"] == rel]
    out = {
        "vault": str(vault),
        "target": rel,
        "items": matching,
    }
    # Add takeaway fallback if not binary
    for it in matching:
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
            it["fallback_takeaway"] = fallback_takeaway(text, it.get("highlights", []))
        except OSError:
            pass
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


def cmd_wrap_up(vault: Path, changes_file: Path) -> int:
    if not changes_file.exists():
        print(f"ERROR: {changes_file} does not exist", file=sys.stderr)
        return 1
    try:
        changes = json.loads(changes_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON: {e}", file=sys.stderr)
        return 1
    result = apply_wrap_up(vault, changes)
    json.dump({"applied": result}, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic core for /compile. Interactive ingest is LLM-driven.",
    )
    parser.add_argument(
        "--vault", type=Path, default=Path.cwd(),
        help="Path to vault root (default: cwd).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--scan-only", action="store_true",
        help="Walk raw/+notes/, emit manifest JSON, exit.",
    )
    mode.add_argument(
        "--dry-run", action="store_true",
        help="Alias for --scan-only.",
    )
    mode.add_argument(
        "--from", dest="from_path", type=Path, default=None,
        help="Classify a single file. Emit JSON with state + highlights + fallback takeaway.",
    )
    mode.add_argument(
        "--wrap-up", dest="wrap_up_file", type=Path, default=None,
        help="Apply Phase 4 from a changes JSON file. Updates index/log/hot, optional list ticks.",
    )
    args = parser.parse_args()

    if not args.vault.is_dir():
        print(f"ERROR: vault path is not a directory: {args.vault}", file=sys.stderr)
        return 1

    vault = args.vault.resolve()

    if args.from_path:
        return cmd_from(vault, args.from_path)
    if args.wrap_up_file:
        return cmd_wrap_up(vault, args.wrap_up_file)
    # default + --scan-only + --dry-run all output the manifest
    return cmd_scan_only(vault)


if __name__ == "__main__":
    sys.exit(main())
