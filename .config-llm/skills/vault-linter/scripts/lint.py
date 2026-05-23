#!/usr/bin/env python3
"""
lint.py — Deterministic health check for a second brain vault (v5).

Runs deterministic checks against the wiki and writes a report.
No LLM. Standard library only.

Usage:
    python lint.py                    # uses cwd as vault
    python lint.py --vault /path      # explicit vault root
    python lint.py --unattended       # no prompts, suitable for schedulers
    python lint.py --quiet            # minimal stdout, full report in file

Exit codes:
    0 — clean (no findings)
    1 — findings present (expected; not a failure)
    2 — script error (filesystem, bug, etc.)

Output:
    .lint/report.md    human-readable findings grouped by severity
    .lint/state.yaml   bookkeeping (last run date, counters)
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path


# --- Constants --------------------------------------------------------------

WIKI_SUBDIRS = ("pages", "sources", "canvas")
STALE_SOURCE_DAYS = 180
CANVAS_STALE_DAYS = 30
DUPLICATE_SIMILARITY_THRESHOLD = 0.75
LOG_ROTATION_THRESHOLD = 500

# Files allowed to be "orphan" (no incoming wiki links)
ORPHAN_EXCEPTIONS = {
    "wiki/hot.md",
    "wiki/compass.md",
    "wiki/index.md",
    "wiki/log.md",
    "index.md",
    "log.md",
}

# Required frontmatter fields per type
REQUIRED_FRONTMATTER = {
    "source": {"type", "source_path", "content_hash", "ingested", "last_checked"},
    "page": {"type", "created", "updated"},
    "canvas": {"type", "kind", "created", "updated", "based_on"},
}

# Patterns
WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|([^\]]+))?\]\]")
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
PROPER_NOUN_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b")
HIGHLIGHT_RE = re.compile(r"==([^=].*?)==", re.DOTALL)
HIGHLIGHT_ID_LINE_RE = re.compile(r"^\s*-\s+\*\*H(\d+)\*\*:?\s*(.*)$")


# --- Data types -------------------------------------------------------------

@dataclass
class Finding:
    severity: str  # "blocking" | "important" | "advisory"
    check: str
    file: str
    detail: str
    line: int | None = None


@dataclass
class WikiPage:
    path: Path
    rel: str
    type: str | None
    frontmatter: dict = field(default_factory=dict)
    title: str | None = None
    outgoing_links: list[tuple[str, int]] = field(default_factory=list)
    body_text: str = ""


# --- Utilities --------------------------------------------------------------

def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Minimal YAML-like parser: scalars + simple lists."""
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    block = match.group(1)
    body = text[match.end():].lstrip("\n")

    fm: dict = {}
    lines = block.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue

        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            items = [x.strip().strip("\"'") for x in inner.split(",") if x.strip()]
            fm[key] = items
            i += 1
            continue

        if value == "":
            items = []
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                if not nxt.strip():
                    j += 1
                    continue
                if re.match(r"^\s+-\s+", nxt):
                    item = re.sub(r"^\s+-\s+", "", nxt).strip()
                    if (item.startswith('"') and item.endswith('"')) or \
                       (item.startswith("'") and item.endswith("'")):
                        item = item[1:-1]
                    items.append(item)
                    j += 1
                else:
                    break
            if items:
                fm[key] = items
            else:
                fm[key] = ""
            i = j
            continue

        if (value.startswith('"') and value.endswith('"')) or \
           (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        fm[key] = value
        i += 1

    return fm, body


_SLUG_INDEX_CACHE: dict[str, dict[str, Path]] = {}


def _slug_index_for(vault_root: Path) -> dict[str, Path]:
    key = str(vault_root)
    if key not in _SLUG_INDEX_CACHE:
        index: dict[str, Path] = {}
        wiki_dir = vault_root / "wiki"
        if wiki_dir.is_dir():
            for md in wiki_dir.rglob("*.md"):
                if md.stem not in index:
                    index[md.stem] = md
        _SLUG_INDEX_CACHE[key] = index
    return _SLUG_INDEX_CACHE[key]


def normalize_link_target(target: str, vault_root: Path, source_file: Path) -> Path | None:
    target = target.strip()
    if not target:
        return None

    # Strip anchor fragments like [[wiki/sources/foo#H2]]
    if "#" in target:
        target = target.split("#", 1)[0]
        if not target:
            return None

    base = Path(target)
    candidates = [base]
    if base.suffix != ".md":
        candidates.append(base.with_name(base.name + ".md"))

    for cand in candidates:
        abs_vault = vault_root / cand
        if abs_vault.exists():
            return abs_vault
        abs_local = source_file.parent / cand
        if abs_local.exists():
            return abs_local.resolve()

    if "/" not in target:
        stem = base.stem if base.suffix == ".md" else base.name
        index = _slug_index_for(vault_root)
        if stem in index:
            return index[stem]

    return vault_root / candidates[0]


def slugify(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def jaccard(a: str, b: str) -> float:
    ta = set(re.split(r"[-_\s]+", a.lower()))
    tb = set(re.split(r"[-_\s]+", b.lower()))
    ta = {t for t in ta if t}
    tb = {t for t in tb if t}
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def title_similarity(a: str, b: str) -> float:
    j = jaccard(slugify(a), slugify(b))
    sa = slugify(a).replace("-", "")
    sb = slugify(b).replace("-", "")
    if not sa or not sb:
        return j
    short, long = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
    if len(long) - len(short) <= 2 and long.startswith(short):
        return max(j, 0.85)
    return j


def parse_date(s: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date()
        except (ValueError, TypeError):
            continue
    return None


# --- Loading ----------------------------------------------------------------

def load_wiki(vault: Path) -> dict[str, WikiPage]:
    pages: dict[str, WikiPage] = {}
    wiki_root = vault / "wiki"
    if not wiki_root.is_dir():
        return pages

    for md_file in wiki_root.rglob("*.md"):
        rel = md_file.relative_to(vault).as_posix()
        text = md_file.read_text(encoding="utf-8", errors="replace")
        fm, body = parse_frontmatter(text)

        page = WikiPage(
            path=md_file,
            rel=rel,
            type=fm.get("type"),
            frontmatter=fm,
            title=extract_title(body) or md_file.stem,
            body_text=body,
        )

        def _blank_preserving(pattern, text):
            return pattern.sub(lambda m: "\n" * m.group(0).count("\n"), text)

        body_clean = _blank_preserving(HTML_COMMENT_RE, body)
        body_clean = _blank_preserving(FENCED_CODE_RE, body_clean)
        body_clean = INLINE_CODE_RE.sub("", body_clean)
        for line_no, line in enumerate(body_clean.splitlines(), start=1):
            for m in WIKILINK_RE.finditer(line):
                target = m.group(1)
                page.outgoing_links.append((target, line_no))

        pages[rel] = page

    return pages


def extract_title(body: str) -> str | None:
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return None


# --- Checks -----------------------------------------------------------------

def check_dead_links(pages: dict[str, WikiPage], vault: Path) -> list[Finding]:
    findings = []
    for page in pages.values():
        for target, line in page.outgoing_links:
            resolved = normalize_link_target(target, vault, page.path)
            if resolved is None or not resolved.exists():
                findings.append(Finding(
                    severity="blocking",
                    check="dead_links",
                    file=page.rel,
                    line=line,
                    detail=f"[[{target}]] does not resolve to an existing file",
                ))
    return findings


def check_orphans(pages: dict[str, WikiPage], vault: Path) -> list[Finding]:
    incoming: dict[str, int] = defaultdict(int)
    for page in pages.values():
        for target, _ in page.outgoing_links:
            resolved = normalize_link_target(target, vault, page.path)
            if resolved and resolved.exists():
                try:
                    rel = resolved.relative_to(vault).as_posix()
                    incoming[rel] += 1
                except ValueError:
                    continue

    findings = []
    for rel, page in pages.items():
        if rel in ORPHAN_EXCEPTIONS:
            continue
        # Canvas are leaf nodes — they cite via based_on, no incoming expected.
        if page.type == "canvas":
            continue
        if incoming.get(rel, 0) == 0:
            findings.append(Finding(
                severity="important",
                check="orphans",
                file=rel,
                detail="no incoming wiki links",
            ))
    return findings


def check_duplicates(pages: dict[str, WikiPage]) -> list[Finding]:
    findings = []
    by_subdir: dict[str, list[WikiPage]] = defaultdict(list)
    for page in pages.values():
        parts = page.rel.split("/")
        if len(parts) >= 2 and parts[0] == "wiki":
            by_subdir[parts[1]].append(page)

    seen_pairs = set()
    for subdir, group in by_subdir.items():
        for i, p1 in enumerate(group):
            for p2 in group[i + 1:]:
                t1 = p1.title or p1.path.stem
                t2 = p2.title or p2.path.stem
                sim = title_similarity(t1, t2)
                if sim >= DUPLICATE_SIMILARITY_THRESHOLD:
                    pair = tuple(sorted([p1.rel, p2.rel]))
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    findings.append(Finding(
                        severity="advisory",
                        check="duplicates",
                        file=p1.rel,
                        detail=f"similar to {p2.rel} (sim={sim:.2f})",
                    ))
    return findings


def check_missing_metadata(pages: dict[str, WikiPage]) -> list[Finding]:
    findings = []
    for page in pages.values():
        if page.rel in ORPHAN_EXCEPTIONS:
            continue
        page_type = page.type
        if not page_type:
            findings.append(Finding(
                severity="blocking",
                check="missing_metadata",
                file=page.rel,
                detail="no 'type' field in frontmatter",
            ))
            continue
        required = REQUIRED_FRONTMATTER.get(page_type, set())
        missing = required - set(page.frontmatter.keys())
        if missing:
            findings.append(Finding(
                severity="blocking",
                check="missing_metadata",
                file=page.rel,
                detail=f"missing required fields: {', '.join(sorted(missing))}",
            ))
    return findings


def check_inconsistent_naming(pages: dict[str, WikiPage]) -> list[Finding]:
    findings = []
    target_to_names: dict[str, set[str]] = defaultdict(set)

    for page in pages.values():
        body = page.body_text
        for m in WIKILINK_RE.finditer(body):
            target = m.group(1).strip()
            name = (m.group(2) or target).strip()
            if not target.endswith(".md"):
                target = target + ".md"
            target_to_names[target].add(name)

    for target, names in target_to_names.items():
        if len(names) > 2:
            findings.append(Finding(
                severity="advisory",
                check="inconsistent_naming",
                file=target,
                detail=f"referenced with {len(names)} different names: {sorted(names)}",
            ))
    return findings


def check_stale_sources(pages: dict[str, WikiPage]) -> list[Finding]:
    """Sources not re-verified (last_checked) in over STALE_SOURCE_DAYS."""
    findings = []
    threshold = date.today() - timedelta(days=STALE_SOURCE_DAYS)
    for page in pages.values():
        if not page.rel.startswith("wiki/sources/"):
            continue
        checked = parse_date(page.frontmatter.get("last_checked", ""))
        # Fallback to legacy 'updated' for back-compat
        if not checked:
            checked = parse_date(page.frontmatter.get("updated", ""))
        if checked and checked < threshold:
            days_old = (date.today() - checked).days
            findings.append(Finding(
                severity="advisory",
                check="stale_sources",
                file=page.rel,
                detail=f"last_checked {days_old} days ago ({checked})",
            ))
    return findings


def check_gaps(pages: dict[str, WikiPage]) -> list[Finding]:
    findings = []

    known: set[str] = set()
    for page in pages.values():
        if page.title:
            known.add(page.title.lower())
            known.add(slugify(page.title))
        known.add(page.path.stem.lower())

    phrase_counts: Counter = Counter()
    for page in pages.values():
        stripped = WIKILINK_RE.sub("", page.body_text)
        for m in PROPER_NOUN_RE.finditer(stripped):
            phrase = m.group(1).strip()
            if phrase.lower() in known or slugify(phrase) in known:
                continue
            phrase_counts[phrase] += 1

    for phrase, count in phrase_counts.most_common():
        if count < 3:
            break
        findings.append(Finding(
            severity="advisory",
            check="gaps",
            file="(multiple files)",
            detail=f"'{phrase}' mentioned {count} times but no wiki page exists",
        ))
        if len(findings) >= 10:
            break
    return findings


def check_canvas_staleness(pages: dict[str, WikiPage]) -> list[Finding]:
    """An evolving canvas (shareable: false) is stale when its based_on
    pages have been updated significantly after the canvas's own updated
    date. Shareable canvases are frozen by design and not checked."""
    findings = []

    for page in pages.values():
        if page.type != "canvas":
            continue
        if str(page.frontmatter.get("shareable", "")).lower() == "true":
            continue

        canvas_updated = parse_date(page.frontmatter.get("updated", ""))
        if not canvas_updated:
            continue

        based_on = page.frontmatter.get("based_on", [])
        if not isinstance(based_on, list):
            continue

        stale_deps = []
        for dep in based_on:
            dep_clean = dep.strip().lstrip("[").rstrip("]")
            if "|" in dep_clean:
                dep_clean = dep_clean.split("|", 1)[0]
            if "#" in dep_clean:
                dep_clean = dep_clean.split("#", 1)[0]
            dep_path = dep_clean if dep_clean.endswith(".md") else dep_clean + ".md"
            dep_page = pages.get(dep_path)
            if not dep_page:
                continue
            dep_updated = parse_date(dep_page.frontmatter.get("updated", ""))
            if not dep_updated:
                continue
            days_diff = (dep_updated - canvas_updated).days
            if days_diff > CANVAS_STALE_DAYS:
                stale_deps.append(f"{dep_path} (+{days_diff}d)")

        if stale_deps:
            findings.append(Finding(
                severity="advisory",
                check="canvas_staleness",
                file=page.rel,
                detail=f"based_on pages updated after canvas: {', '.join(stale_deps)}",
            ))
    return findings


def check_missing_cross_references(pages: dict[str, WikiPage]) -> list[Finding]:
    findings = []
    title_to_rel: dict[str, str] = {}
    for page in pages.values():
        if page.title and page.rel.startswith("wiki/pages/"):
            title_to_rel[page.title.lower()] = page.rel

    for page in pages.values():
        if not page.rel.startswith("wiki/sources/"):
            continue
        linked_titles = set()
        for target, _ in page.outgoing_links:
            target_norm = target if target.endswith(".md") else target + ".md"
            for p in pages.values():
                if p.rel == target_norm:
                    if p.title:
                        linked_titles.add(p.title.lower())

        stripped = WIKILINK_RE.sub("", page.body_text).lower()

        for title, target_rel in title_to_rel.items():
            if title in linked_titles:
                continue
            if len(title) < 4:
                continue
            if re.search(r"\b" + re.escape(title) + r"\b", stripped):
                findings.append(Finding(
                    severity="advisory",
                    check="missing_cross_references",
                    file=page.rel,
                    detail=f"mentions '{title}' in prose but does not link to {target_rel}",
                ))
    return findings


def check_content_hash_drift(pages: dict[str, WikiPage], vault: Path) -> list[Finding]:
    """For each source page with content_hash, recompute and flag mismatches.
    Also handles legacy 'raw_sha256' field for back-compat."""
    out: list[Finding] = []
    for rel, p in pages.items():
        if p.type != "source":
            continue
        expected = p.frontmatter.get("content_hash") or p.frontmatter.get("raw_sha256")
        source_path = p.frontmatter.get("source_path")
        if not expected or not source_path:
            continue
        if isinstance(expected, list) or isinstance(source_path, list):
            continue
        raw_file = vault / source_path
        if not raw_file.exists():
            out.append(Finding(
                severity="blocking",
                check="content_hash_drift",
                file=rel,
                detail=f"source_path '{source_path}' does not exist",
            ))
            continue
        try:
            actual = hashlib.sha256(raw_file.read_bytes()).hexdigest()
        except OSError as e:
            out.append(Finding(
                severity="important",
                check="content_hash_drift",
                file=rel,
                detail=f"cannot read {source_path}: {e}",
            ))
            continue
        if actual != expected.strip().lower():
            out.append(Finding(
                severity="important",
                check="content_hash_drift",
                file=rel,
                detail=f"source drift: expected {expected[:12]}…, got {actual[:12]}… for {source_path}",
            ))
    return out


def check_highlights_drift(pages: dict[str, WikiPage], vault: Path) -> list[Finding]:
    """For each source page with ## Highlights section, verify that the
    H<n> entries match the ==text== markers in the source_path file.

    Mismatch (count, ordering, or text) => highlights drift.
    """
    out: list[Finding] = []
    for rel, p in pages.items():
        if p.type != "source":
            continue
        source_path = p.frontmatter.get("source_path")
        if not source_path or isinstance(source_path, list):
            continue

        # Extract H<n> entries from source page body
        body = p.body_text
        in_highlights = False
        recorded: list[tuple[int, str]] = []  # (id_num, text)
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                in_highlights = (stripped.lower() == "## highlights")
                continue
            if not in_highlights:
                continue
            m = HIGHLIGHT_ID_LINE_RE.match(line)
            if m:
                id_num = int(m.group(1))
                txt = m.group(2).strip().strip('"').strip("'")
                recorded.append((id_num, txt))

        if not recorded:
            continue  # source page has no highlights section; nothing to check

        raw_file = vault / source_path
        if not raw_file.exists():
            # Already reported by content_hash_drift; skip silently
            continue

        # PDFs are binary; skip highlight extraction
        if raw_file.suffix.lower() == ".pdf":
            continue

        try:
            raw_text = raw_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        actual_highlights = [m.group(1).strip() for m in HIGHLIGHT_RE.finditer(raw_text)]

        if len(actual_highlights) != len(recorded):
            out.append(Finding(
                severity="important",
                check="highlights_drift",
                file=rel,
                detail=(
                    f"highlight count mismatch: source page has {len(recorded)} "
                    f"H-entries, raw file has {len(actual_highlights)} ==…== markers"
                ),
            ))
            continue

        # Same count: verify ordering and text
        for (id_num, recorded_text), actual_text in zip(recorded, actual_highlights):
            if recorded_text and actual_text and recorded_text != actual_text:
                # Allow trailing punctuation/whitespace differences
                if recorded_text.rstrip(".,;:") != actual_text.rstrip(".,;:"):
                    out.append(Finding(
                        severity="advisory",
                        check="highlights_drift",
                        file=rel,
                        detail=(
                            f"H{id_num} text mismatch: source page says "
                            f"'{recorded_text[:60]}…', raw has '{actual_text[:60]}…'"
                        ),
                    ))

    return out


def check_quality_signals(pages: dict[str, WikiPage]) -> list[Finding]:
    """Surface confidence:low, contested:true, mono-source no-confidence,
    and asymmetric contradictions. All optional, advisory."""
    out: list[Finding] = []

    by_slug: dict[str, WikiPage] = {}
    for rel, p in pages.items():
        slug = Path(rel).stem
        by_slug[slug] = p

    for rel, p in pages.items():
        if p.type != "page":
            continue
        fm = p.frontmatter
        conf = fm.get("confidence")
        if isinstance(conf, str) and conf.strip().lower() == "low":
            out.append(Finding(
                severity="advisory",
                check="quality_signals",
                file=rel,
                detail="confidence:low — candidate for corroboration",
            ))
        contested = fm.get("contested")
        if isinstance(contested, str) and contested.strip().lower() == "true":
            out.append(Finding(
                severity="advisory",
                check="quality_signals",
                file=rel,
                detail="contested:true — review for resolution",
            ))
        contradictions = fm.get("contradictions") or []
        if isinstance(contradictions, str):
            contradictions = [contradictions]
        for other_slug in contradictions:
            other = by_slug.get(other_slug)
            if not other:
                out.append(Finding(
                    severity="important",
                    check="quality_signals",
                    file=rel,
                    detail=f"contradictions references unknown page '{other_slug}'",
                ))
                continue
            other_contradictions = other.frontmatter.get("contradictions") or []
            if isinstance(other_contradictions, str):
                other_contradictions = [other_contradictions]
            this_slug = Path(rel).stem
            if this_slug not in other_contradictions:
                out.append(Finding(
                    severity="advisory",
                    check="quality_signals",
                    file=rel,
                    detail=f"asymmetric contradictions: '{other_slug}' does not list '{this_slug}' back",
                ))
    return out


def check_supersedes_symmetry(pages: dict[str, WikiPage]) -> list[Finding]:
    """For source pages with supersedes/superseded_by links, verify the
    reciprocal field on the linked page."""
    out: list[Finding] = []

    by_rel: dict[str, WikiPage] = {rel: p for rel, p in pages.items()}

    def _resolve_link(link: str) -> str | None:
        link = link.strip().strip("[]").strip()
        if not link:
            return None
        if "|" in link:
            link = link.split("|", 1)[0]
        link = link.split("#", 1)[0]
        if not link.endswith(".md"):
            link = link + ".md"
        if link in by_rel:
            return link
        # Try slug match
        stem = Path(link).stem
        for r in by_rel:
            if Path(r).stem == stem:
                return r
        return None

    for rel, p in pages.items():
        if p.type != "source":
            continue
        for field_name, reciprocal_field in (("supersedes", "superseded_by"),
                                             ("superseded_by", "supersedes")):
            val = p.frontmatter.get(field_name)
            if not val or (isinstance(val, str) and val.strip().lower() in ("null", "none", "")):
                continue
            targets = val if isinstance(val, list) else [val]
            for t in targets:
                resolved = _resolve_link(t)
                if not resolved:
                    out.append(Finding(
                        severity="important",
                        check="supersedes_symmetry",
                        file=rel,
                        detail=f"{field_name} references unresolvable '{t}'",
                    ))
                    continue
                other = by_rel[resolved]
                other_val = other.frontmatter.get(reciprocal_field)
                # other_val should reference back to this page's stem
                this_stem = Path(rel).stem
                if not other_val or (isinstance(other_val, str) and other_val.strip().lower() in ("null", "none", "")):
                    out.append(Finding(
                        severity="advisory",
                        check="supersedes_symmetry",
                        file=resolved,
                        detail=f"missing reciprocal {reciprocal_field} pointing to '{this_stem}'",
                    ))
    return out


def check_free_tag_variants(pages: dict[str, WikiPage]) -> list[Finding]:
    """Detect case-insensitive variants of free tags (e.g. claude-code vs Claude-Code)."""
    out: list[Finding] = []
    free_tag_to_pages: dict[str, list[str]] = defaultdict(list)

    for rel, p in pages.items():
        if not p.type:
            continue
        tags = p.frontmatter.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        for t in tags:
            t = t.strip()
            if not t or ":" in t:
                continue
            free_tag_to_pages[t].append(rel)

    by_lower: dict[str, set[str]] = defaultdict(set)
    for tag in free_tag_to_pages:
        by_lower[tag.lower()].add(tag)

    for lower, variants in by_lower.items():
        if len(variants) > 1:
            example_files = sorted({rel for v in variants for rel in free_tag_to_pages[v]})[:3]
            out.append(Finding(
                severity="advisory",
                check="free_tag_variants",
                file=example_files[0],
                detail=f"variants for '{lower}': {sorted(variants)} — pick one (also in {len(example_files)-1} other file(s))",
            ))
    return out


def check_log_rotation(pages: dict[str, WikiPage], vault: Path) -> list[Finding]:
    log_file = vault / "wiki" / "log.md"
    if not log_file.exists():
        return []
    try:
        text = log_file.read_text(encoding="utf-8")
    except OSError:
        return []
    entry_count = sum(1 for line in text.splitlines() if re.match(r"^## \[", line))
    if entry_count <= LOG_ROTATION_THRESHOLD:
        return []
    return [Finding(
        severity="advisory",
        check="log_rotation",
        file="wiki/log.md",
        detail=f"{entry_count} entries (threshold {LOG_ROTATION_THRESHOLD}) — propose rotation to log-YYYY.md",
    )]


# --- Report -----------------------------------------------------------------

def severity_rank(s: str) -> int:
    return {"blocking": 0, "important": 1, "advisory": 2}.get(s, 3)


def write_report(findings: list[Finding], vault: Path, quiet: bool = False) -> None:
    lint_dir = vault / ".lint"
    lint_dir.mkdir(exist_ok=True)

    by_severity: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        by_severity[f.severity].append(f)

    lines: list[str] = []
    lines.append("# Lint Report")
    lines.append("")
    lines.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append("")

    counts = {
        "blocking": len(by_severity.get("blocking", [])),
        "important": len(by_severity.get("important", [])),
        "advisory": len(by_severity.get("advisory", [])),
    }
    lines.append(f"**Summary:** {counts['blocking']} blocking · "
                 f"{counts['important']} important · "
                 f"{counts['advisory']} advisory")
    lines.append("")

    if not findings:
        lines.append("✅ Vault is clean. No findings.")
        lines.append("")
    else:
        for severity in ("blocking", "important", "advisory"):
            items = by_severity.get(severity, [])
            if not items:
                continue
            lines.append(f"## {severity.capitalize()} ({len(items)})")
            lines.append("")
            by_check: dict[str, list[Finding]] = defaultdict(list)
            for f in items:
                by_check[f.check].append(f)
            for check, group in sorted(by_check.items()):
                lines.append(f"### {check} — {len(group)} finding(s)")
                lines.append("")
                for f in group:
                    loc = f":{f.line}" if f.line else ""
                    lines.append(f"- `{f.file}{loc}` — {f.detail}")
                lines.append("")

    report_path = lint_dir / "report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")

    if not quiet:
        print(f"Report written to {report_path.relative_to(vault)}")


def write_state(vault: Path, findings: list[Finding], exit_code: int) -> None:
    lint_dir = vault / ".lint"
    lint_dir.mkdir(exist_ok=True)
    state_path = lint_dir / "state.yaml"

    lines = [
        f"last_lint: {date.today().isoformat()}",
        "ingests_since_last_lint: 0",
        f"last_exit_code: {exit_code}",
        f"last_findings_count: {len(findings)}",
        f"blocking: {sum(1 for f in findings if f.severity == 'blocking')}",
        f"important: {sum(1 for f in findings if f.severity == 'important')}",
        f"advisory: {sum(1 for f in findings if f.severity == 'advisory')}",
    ]
    state_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- Orchestration ----------------------------------------------------------

def run_lint(vault: Path, quiet: bool = False) -> int:
    if not (vault / "wiki").is_dir():
        print(f"ERROR: no wiki/ directory in {vault}", file=sys.stderr)
        return 2

    pages = load_wiki(vault)
    if not quiet:
        print(f"Loaded {len(pages)} wiki pages from {vault}/wiki/")

    all_checks = [
        ("dead_links", check_dead_links),
        ("orphans", check_orphans),
        ("duplicates", check_duplicates),
        ("missing_metadata", check_missing_metadata),
        ("inconsistent_naming", check_inconsistent_naming),
        ("stale_sources", check_stale_sources),
        ("gaps", check_gaps),
        ("canvas_staleness", check_canvas_staleness),
        ("missing_cross_references", check_missing_cross_references),
        ("content_hash_drift", check_content_hash_drift),
        ("highlights_drift", check_highlights_drift),
        ("quality_signals", check_quality_signals),
        ("supersedes_symmetry", check_supersedes_symmetry),
        ("free_tag_variants", check_free_tag_variants),
        ("log_rotation", check_log_rotation),
    ]

    needs_vault = {"dead_links", "orphans", "content_hash_drift",
                   "highlights_drift", "log_rotation"}

    findings: list[Finding] = []
    for name, fn in all_checks:
        try:
            if name in needs_vault:
                out = fn(pages, vault)
            else:
                out = fn(pages)
        except Exception as e:
            print(f"ERROR in check '{name}': {e}", file=sys.stderr)
            return 2
        findings.extend(out)
        if not quiet:
            print(f"  {name}: {len(out)} finding(s)")

    findings.sort(key=lambda f: (severity_rank(f.severity), f.file, f.line or 0))

    exit_code = 0 if not findings else 1
    write_report(findings, vault, quiet=quiet)
    write_state(vault, findings, exit_code)

    if not quiet:
        counts_str = (
            f"{sum(1 for f in findings if f.severity == 'blocking')} blocking, "
            f"{sum(1 for f in findings if f.severity == 'important')} important, "
            f"{sum(1 for f in findings if f.severity == 'advisory')} advisory"
        )
        print(f"\nDone. {counts_str}.")

    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Lint a second brain vault. Writes .lint/report.md."
    )
    parser.add_argument(
        "--vault", type=Path, default=Path.cwd(),
        help="Path to vault root (default: current directory).",
    )
    parser.add_argument(
        "--unattended", action="store_true",
        help="No prompts. Suitable for schedulers.",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Minimal stdout. Full report still written to .lint/report.md.",
    )
    args = parser.parse_args()

    if not args.vault.is_dir():
        print(f"ERROR: vault path is not a directory: {args.vault}", file=sys.stderr)
        return 2

    try:
        return run_lint(args.vault.resolve(), quiet=args.quiet or args.unattended)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
