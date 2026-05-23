#!/usr/bin/env python3
"""
fetch_inbox.py — Process inbox.md and populate raw/web/ (and raw/papers/ for PDFs).

Usage:
    python fetch_inbox.py                    # uses current dir as vault
    python fetch_inbox.py --vault /path      # explicit vault path
    python fetch_inbox.py --dry-run          # shows what would be done
    python fetch_inbox.py --feeds-only       # only poll RSS feeds, no URL fetching
    python fetch_inbox.py --skip-feeds       # skip RSS polling, only URLs

Reads `inbox.md` from the vault root, polls RSS/Atom feeds listed under
`## Feeds`, finds unchecked URL entries under `## Da processare`, fetches
each, and writes clean markdown + images to raw/web/<slug>/. PDFs go to
raw/papers/<slug>.pdf.

Idempotent: already-processed URLs are skipped. Feed items are deduped by
canonical URL (post-redirect) against the entire inbox.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urljoin

# --- Dependency check with friendly error -----------------------------------

MISSING_DEPS = []
try:
    import requests
except ImportError:
    MISSING_DEPS.append("requests")
try:
    import trafilatura
except ImportError:
    MISSING_DEPS.append("trafilatura")
try:
    from slugify import slugify
except ImportError:
    MISSING_DEPS.append("python-slugify")
try:
    import feedparser
except ImportError:
    MISSING_DEPS.append("feedparser")

if MISSING_DEPS:
    print("Missing dependencies. Install with:", file=sys.stderr)
    print(f"  pip install {' '.join(MISSING_DEPS)}", file=sys.stderr)
    sys.exit(1)


# --- Data types -------------------------------------------------------------

@dataclass
class InboxEntry:
    url: str
    line_index: int
    raw_line: str


@dataclass
class FetchResult:
    url: str
    ok: bool
    kind: str  # "html" | "pdf" | "failed"
    out_path: Path | None = None
    reason: str | None = None


@dataclass
class FeedReport:
    feed_url: str
    new_items: list[str] = field(default_factory=list)  # canonical URLs appended
    skipped_dedup: int = 0
    error: str | None = None


# --- Constants --------------------------------------------------------------

HTML_TIMEOUT = 20
PDF_TIMEOUT = 60
MAX_PDF_SIZE_MB = 50

REDIRECT_TIMEOUT = 10
MAX_REDIRECT_HOPS = 5
MAX_NEW_PER_POLL = 20
MAX_SEEN_GUIDS = 500

USER_AGENT = (
    "Mozilla/5.0 (compatible; InboxFetcher/1.0; "
    "+https://github.com/anthropic/skills)"
)

UNCHECKED_PATTERN = re.compile(r"^- \[ \] (https?://\S+)\s*$")
CHECKED_PATTERN = re.compile(r"^- \[x\] (https?://\S+)")
FEED_PATTERN = re.compile(r"^-\s*feed:\s*(\S+)")
IMG_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")

# Domains known to block plain HTTP fetchers (auth walls, aggressive
# anti-bot, or JS-only rendering). Skip trafilatura entirely and mark
# the URL for agent-driven Playwright MCP fallback.
WALLED_DOMAINS = frozenset({
    "x.com",
    "twitter.com",
    "mobile.twitter.com",
    "threads.net",
    "linkedin.com",
    "www.linkedin.com",
    "facebook.com",
    "www.facebook.com",
    "m.facebook.com",
    "instagram.com",
    "www.instagram.com",
})

PLAYWRIGHT_HINT = "try playwright"


# --- Core operations --------------------------------------------------------

def strip_comments(text: str) -> str:
    """Strip HTML comments before parsing (so example URLs in comments
    are not picked up)."""
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def find_unchecked_entries(inbox_text: str) -> list[InboxEntry]:
    """Parse inbox.md and return list of unchecked URL entries."""
    stripped = strip_comments(inbox_text)
    entries = []
    for i, line in enumerate(stripped.splitlines()):
        match = UNCHECKED_PATTERN.match(line)
        if match:
            entries.append(InboxEntry(
                url=match.group(1).strip(),
                line_index=i,
                raw_line=line,
            ))
    return entries


def existing_inbox_urls(inbox_text: str) -> set[str]:
    """Set of all URLs already in inbox (checked + unchecked).

    Used to dedup feed items before appending. Comments stripped so
    example URLs inside <!-- ... --> don't count.
    """
    stripped = strip_comments(inbox_text)
    urls: set[str] = set()
    for line in stripped.splitlines():
        m = UNCHECKED_PATTERN.match(line) or CHECKED_PATTERN.match(line)
        if m:
            urls.add(m.group(1).strip())
    return urls


def is_pdf_url(url: str) -> bool:
    """Heuristic: URL path ends in .pdf."""
    return Path(urlparse(url).path).suffix.lower() == ".pdf"


def is_walled(url: str) -> bool:
    """Preflight check: URL host is in the walled-domain list."""
    host = urlparse(url).netloc.lower()
    return host in WALLED_DOMAINS


def rewrite_url_for_fetch(url: str) -> tuple[str, str | None]:
    """Rewrite a user-supplied URL into a better fetch target.

    Returns (fetch_url, slug_override). When slug_override is non-None
    it is used as the raw-file slug verbatim (bypassing slugify) so
    canonical identifiers like arxiv paper IDs survive intact.

    Arxiv abstract and HTML URLs are rewritten to the PDF endpoint so
    we archive the paper itself instead of the landing page.
    """
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    if host in ("arxiv.org", "export.arxiv.org"):
        m = re.match(r"^/(?:abs|html|pdf)/(.+?)(?:\.pdf)?$", parsed.path)
        if m:
            paper_id = m.group(1)
            slug = f"arxiv-{paper_id.replace('/', '-')}"
            return f"https://arxiv.org/pdf/{paper_id}.pdf", slug
    return url, None


def slug_from(url: str, title: str | None) -> str:
    """Generate a filesystem-safe slug, preferring the title."""
    if title and title.strip():
        s = slugify(title)[:80]
        if s:
            return s
    host = urlparse(url).netloc.replace("www.", "")
    h = hashlib.sha1(url.encode()).hexdigest()[:8]
    return f"{slugify(host)}-{h}"


def fetch_pdf(url: str, papers_dir: Path,
              slug_override: str | None = None) -> FetchResult:
    """Download a PDF directly to raw/papers/."""
    try:
        r = requests.get(
            url,
            timeout=PDF_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            stream=True,
        )
        r.raise_for_status()
    except Exception as e:
        return FetchResult(url=url, ok=False, kind="failed",
                           reason=f"pdf download failed: {e}")

    size = int(r.headers.get("Content-Length", 0))
    if size > MAX_PDF_SIZE_MB * 1024 * 1024:
        print(f"  ⚠ large PDF ({size // 1024 // 1024} MB): {url}")

    slug = slug_override or slug_from(url, None)
    out_path = papers_dir / f"{slug}.pdf"
    papers_dir.mkdir(parents=True, exist_ok=True)

    with open(out_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)

    return FetchResult(url=url, ok=True, kind="pdf", out_path=out_path)


def fetch_html(url: str, web_dir: Path) -> FetchResult:
    """Fetch an HTML article, extract clean markdown, download images."""
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        return FetchResult(url=url, ok=False, kind="failed",
                           reason=f"fetch returned empty (network / 403 / paywall) — {PLAYWRIGHT_HINT}")

    result = trafilatura.extract(
        downloaded,
        output_format="markdown",
        with_metadata=True,
        include_images=True,
        include_links=True,
        include_tables=True,
    )
    if not result or not result.strip():
        return FetchResult(url=url, ok=False, kind="failed",
                           reason=f"extraction empty (likely paywall or JS-rendered) — {PLAYWRIGHT_HINT}")

    meta = trafilatura.extract_metadata(downloaded)
    title = getattr(meta, "title", None) if meta else None
    author = getattr(meta, "author", None) if meta else None
    pub_date = getattr(meta, "date", None) if meta else None
    language = getattr(meta, "language", None) if meta else None

    slug = slug_from(url, title)
    out_dir = web_dir / slug
    assets_dir = out_dir / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(exist_ok=True)

    md_with_local_images = download_images(result, assets_dir, base_url=url)

    frontmatter_lines = [
        "---",
        f"source_url: {url}",
        f"title: {yaml_escape(title) if title else 'Untitled'}",
    ]
    if author:
        frontmatter_lines.append(f"author: {yaml_escape(author)}")
    if pub_date:
        frontmatter_lines.append(f"published: {pub_date}")
    if language:
        frontmatter_lines.append(f"language: {language}")
    frontmatter_lines.append(f"fetched: {date.today().isoformat()}")
    frontmatter_lines.append("fetched_via: trafilatura")
    frontmatter_lines.append("---")
    frontmatter = "\n".join(frontmatter_lines) + "\n\n"

    body = f"# {title or 'Untitled'}\n\n{md_with_local_images}\n"
    (out_dir / "index.md").write_text(frontmatter + body, encoding="utf-8")

    return FetchResult(url=url, ok=True, kind="html", out_path=out_dir)


def download_images(md: str, assets_dir: Path, base_url: str) -> str:
    """Download all images referenced in md, rewrite paths to local assets/."""

    def replace(match: re.Match) -> str:
        alt, src = match.group(1), match.group(2)
        if not src.startswith(("http://", "https://")):
            src_abs = urljoin(base_url, src)
        else:
            src_abs = src
        try:
            r = requests.get(
                src_abs,
                timeout=HTML_TIMEOUT,
                headers={"User-Agent": USER_AGENT},
            )
            r.raise_for_status()
        except Exception:
            return match.group(0)  # keep original link on failure

        ext = Path(urlparse(src_abs).path).suffix or ".png"
        if len(ext) > 6:
            ext = ".png"
        name = hashlib.sha1(src_abs.encode()).hexdigest()[:12] + ext
        (assets_dir / name).write_bytes(r.content)
        return f"![{alt}](assets/{name})"

    return IMG_PATTERN.sub(replace, md)


def yaml_escape(s: str) -> str:
    """Minimal YAML string escape: quote if it contains special chars."""
    if any(c in s for c in ":#\"'\n"):
        return '"' + s.replace('"', '\\"').replace("\n", " ") + '"'
    return s


# --- RSS / Atom feed polling ------------------------------------------------

def parse_feeds(inbox_text: str) -> list[str]:
    """Extract feed URLs from the `## Feeds` section. Stops at next `##`."""
    stripped = strip_comments(inbox_text)
    feeds: list[str] = []
    in_feeds = False
    for line in stripped.splitlines():
        if line.strip().lower() == "## feeds":
            in_feeds = True
            continue
        if in_feeds and line.startswith("## "):
            break
        if in_feeds:
            m = FEED_PATTERN.match(line)
            if m:
                feeds.append(m.group(1).strip())
    return feeds


def load_feed_state(vault: Path) -> dict:
    state_path = vault / ".config-llm" / "state" / "feeds.json"
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ⚠ feeds.json unreadable ({e}); starting from empty state",
              file=sys.stderr)
        return {}


def save_feed_state(vault: Path, state: dict) -> None:
    state_dir = vault / ".config-llm" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "feeds.json"
    tmp = state_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    os.replace(tmp, state_path)


def resolve_canonical_url(url: str) -> str:
    """Follow HTTP redirects to the final canonical URL.

    Tries HEAD first; falls back to GET on 405/403 (some servers reject HEAD).
    Capped at MAX_REDIRECT_HOPS. On any error, returns the input url.
    """
    if not url.startswith(("http://", "https://")):
        return url
    session = requests.Session()
    session.max_redirects = MAX_REDIRECT_HOPS
    headers = {"User-Agent": USER_AGENT}
    for method in ("HEAD", "GET"):
        try:
            req = session.request(
                method,
                url,
                allow_redirects=True,
                timeout=REDIRECT_TIMEOUT,
                headers=headers,
                stream=(method == "GET"),
            )
            # Don't drain GET body — we only need the final URL
            final = req.url
            req.close()
            return final
        except requests.TooManyRedirects:
            # session retains history; return last successful hop if any,
            # else original
            return url
        except Exception:
            continue
    return url


def poll_feed(feed_url: str, feed_state: dict) -> tuple[list[dict], dict, str | None]:
    """Poll one feed. Returns (new_items, updated_state, error).

    new_items is a list of dicts {guid, canonical, title, summary} for
    items never seen before. Caps at MAX_NEW_PER_POLL. Uses etag/last-
    modified for conditional GET when feedparser supports it.
    """
    etag = feed_state.get("etag")
    modified = feed_state.get("last_modified")
    seen_guids = list(feed_state.get("seen_guids", []))
    seen_set = set(seen_guids)

    try:
        parsed = feedparser.parse(
            feed_url,
            etag=etag,
            modified=modified,
            agent=USER_AGENT,
        )
    except Exception as e:
        return [], feed_state, f"feedparser error: {e}"

    status = getattr(parsed, "status", None)
    if status == 304:
        # Not modified since last poll; still bump last_polled
        feed_state["last_polled"] = datetime.now(timezone.utc).isoformat()
        return [], feed_state, None

    if status and status >= 400:
        return [], feed_state, f"HTTP {status}"

    if getattr(parsed, "bozo", False) and not parsed.entries:
        err = getattr(parsed, "bozo_exception", "malformed feed")
        return [], feed_state, f"malformed feed: {err}"

    new_items: list[dict] = []
    for entry in parsed.entries:
        guid = (
            getattr(entry, "id", None)
            or getattr(entry, "guid", None)
            or getattr(entry, "link", None)
        )
        link = getattr(entry, "link", None)
        if not guid or not link:
            continue
        if guid in seen_set:
            continue
        canonical = resolve_canonical_url(link)
        title = getattr(entry, "title", "") or ""
        summary = (
            getattr(entry, "summary", "")
            or getattr(entry, "description", "")
            or ""
        )
        # Strip HTML from summary (feed summaries often contain markup)
        summary = re.sub(r"<[^>]+>", " ", summary)
        summary = re.sub(r"\s+", " ", summary).strip()
        if len(summary) > 280:
            summary = summary[:277].rstrip() + "…"
        new_items.append({
            "guid": guid,
            "canonical": canonical,
            "title": title.strip(),
            "summary": summary,
        })
        if len(new_items) >= MAX_NEW_PER_POLL:
            break

    # Update seen_guids (FIFO cap MAX_SEEN_GUIDS)
    for item in new_items:
        seen_guids.append(item["guid"])
    if len(seen_guids) > MAX_SEEN_GUIDS:
        seen_guids = seen_guids[-MAX_SEEN_GUIDS:]

    feed_state["seen_guids"] = seen_guids
    feed_state["last_polled"] = datetime.now(timezone.utc).isoformat()
    new_etag = getattr(parsed, "etag", None)
    if new_etag:
        feed_state["etag"] = new_etag
    new_modified = getattr(parsed, "modified", None) or getattr(parsed, "updated", None)
    if new_modified:
        feed_state["last_modified"] = new_modified

    return new_items, feed_state, None


def append_feed_items_to_inbox(inbox_text: str, new_urls: list[str]) -> str:
    """Append URLs as `- [ ] <url>` lines under `## Da processare`.

    If the section doesn't exist, create it before any `## Elaborati`
    (or at end of file). Preserves existing content.
    """
    if not new_urls:
        return inbox_text

    lines = inbox_text.splitlines()
    has_trailing_newline = inbox_text.endswith("\n")

    # Find `## Da processare`
    process_idx = None
    next_section_idx = None
    for i, line in enumerate(lines):
        if line.strip().lower() == "## da processare":
            process_idx = i
        elif process_idx is not None and line.startswith("## "):
            next_section_idx = i
            break

    new_lines = [f"- [ ] {url}" for url in new_urls]

    if process_idx is None:
        # Create section before `## Elaborati` if present, else at end
        elab_idx = None
        for i, line in enumerate(lines):
            if line.strip().lower() == "## elaborati":
                elab_idx = i
                break
        insertion = ["", "## Da processare", ""] + new_lines + [""]
        if elab_idx is not None:
            lines = lines[:elab_idx] + insertion + lines[elab_idx:]
        else:
            if lines and lines[-1].strip():
                lines.append("")
            lines.extend(["## Da processare", ""] + new_lines)
    else:
        # Insert at the end of the section (before next `## ...`)
        insert_at = next_section_idx if next_section_idx is not None else len(lines)
        # Walk backwards to skip trailing blank lines inside the section
        while insert_at > process_idx + 1 and lines[insert_at - 1].strip() == "":
            insert_at -= 1
        lines = lines[:insert_at] + new_lines + lines[insert_at:]

    out = "\n".join(lines)
    return out + ("\n" if has_trailing_newline else "")


def mark_feed_unreachable(inbox_text: str, feed_url: str, reason: str) -> str:
    """Append `<!-- ⚠ unreachable YYYY-MM-DD: reason -->` to the feed line.

    If a previous unreachable marker exists on that line, replace it
    rather than stacking.
    """
    today = date.today().isoformat()
    marker = f"<!-- ⚠ unreachable {today}: {reason} -->"
    new_lines = []
    changed = False
    for line in inbox_text.splitlines():
        m = FEED_PATTERN.match(line)
        if m and m.group(1).strip() == feed_url:
            base = re.sub(r"\s*<!--\s*⚠ unreachable.*?-->\s*$", "", line).rstrip()
            new_lines.append(f"{base}  {marker}")
            changed = True
        else:
            new_lines.append(line)
    if not changed:
        return inbox_text
    out = "\n".join(new_lines)
    return out + ("\n" if inbox_text.endswith("\n") else "")


def feed_phase(
    vault: Path,
    inbox_text: str,
    dry_run: bool,
) -> tuple[str, list[FeedReport]]:
    """Poll all subscribed feeds and append new items to inbox_text.

    Returns (updated_inbox_text, reports). State is persisted to disk
    unless dry_run is True.
    """
    feeds = parse_feeds(inbox_text)
    if not feeds:
        return inbox_text, []

    state = load_feed_state(vault)
    existing = existing_inbox_urls(inbox_text)
    reports: list[FeedReport] = []
    all_new_urls: list[str] = []
    seen_in_this_run: set[str] = set()
    new_inbox = inbox_text

    print(f"\nFeeds: {len(feeds)} sottoscritti")
    for feed_url in feeds:
        feed_state = state.get(feed_url, {})
        report = FeedReport(feed_url=feed_url)
        print(f"  polling {feed_url} …")
        new_items, updated_state, error = poll_feed(feed_url, feed_state)
        if error:
            report.error = error
            print(f"    ⚠ {error}")
            new_inbox = mark_feed_unreachable(new_inbox, feed_url, error)
            reports.append(report)
            continue

        state[feed_url] = updated_state

        for item in new_items:
            canonical = item["canonical"]
            if canonical in existing or canonical in seen_in_this_run:
                report.skipped_dedup += 1
                continue
            report.new_items.append(canonical)
            all_new_urls.append(canonical)
            seen_in_this_run.add(canonical)

        n_new = len(report.new_items)
        n_dup = report.skipped_dedup
        if n_new == 0 and n_dup == 0:
            print(f"    — nessun nuovo item")
        else:
            print(f"    + {n_new} nuovo/i (dedup: {n_dup})")
        reports.append(report)

    if dry_run:
        return new_inbox, reports

    new_inbox = append_feed_items_to_inbox(new_inbox, all_new_urls)
    save_feed_state(vault, state)
    return new_inbox, reports


# --- RSS triage (compile orchestrator integration) -------------------------

def triage_feeds(vault: Path) -> dict:
    """Poll feeds and return a structured triage list WITHOUT updating
    state or modifying inbox.md.

    The compile orchestrator uses this to ask the user which items to
    fetch full. Then it calls apply_triage() with the user's selection
    to commit the decision.

    Returns: {"rss_triage": [{feed, guid, url, title, summary}, ...]}
    """
    inbox_path = vault / "inbox.md"
    if not inbox_path.exists():
        return {"rss_triage": [], "error": "inbox.md not found"}

    inbox_text = inbox_path.read_text(encoding="utf-8")
    feeds = parse_feeds(inbox_text)
    if not feeds:
        return {"rss_triage": []}

    state = load_feed_state(vault)
    existing = existing_inbox_urls(inbox_text)
    seen_in_run: set[str] = set()
    triage: list[dict] = []

    for feed_url in feeds:
        feed_state = state.get(feed_url, {})
        new_items, _updated_state, error = poll_feed(feed_url, feed_state)
        if error:
            continue
        for item in new_items:
            canonical = item["canonical"]
            if canonical in existing or canonical in seen_in_run:
                continue
            seen_in_run.add(canonical)
            triage.append({
                "feed": feed_url,
                "guid": item["guid"],
                "url": canonical,
                "title": item["title"],
                "summary": item["summary"],
            })

    return {"rss_triage": triage}


def apply_triage(vault: Path, triage_data: dict) -> tuple[int, int]:
    """Apply a triage decision file.

    Expected format:
        {
          "rss_triage": [
            {feed, guid, url, title, summary, selected: bool},
            ...
          ]
        }

    For every item (selected or not), mark the GUID as seen in feed_state
    (so it won't reappear in future polls). For selected items, append
    canonical URL to inbox.md `## Da processare`.

    Returns: (n_selected_appended, n_dropped).
    """
    inbox_path = vault / "inbox.md"
    if not inbox_path.exists():
        raise FileNotFoundError(f"inbox.md not found in {vault}")

    items = triage_data.get("rss_triage", [])
    if not items:
        return (0, 0)

    state = load_feed_state(vault)
    inbox_text = inbox_path.read_text(encoding="utf-8")
    existing = existing_inbox_urls(inbox_text)

    n_selected = 0
    n_dropped = 0
    selected_urls: list[str] = []

    # Group GUIDs by feed for state update
    guids_per_feed: dict[str, list[str]] = {}
    for item in items:
        feed_url = item.get("feed")
        guid = item.get("guid")
        if not feed_url or not guid:
            continue
        guids_per_feed.setdefault(feed_url, []).append(guid)

        if item.get("selected"):
            url = item.get("url")
            if url and url not in existing:
                selected_urls.append(url)
                n_selected += 1
        else:
            n_dropped += 1

    # Mark every triaged GUID as seen (selected or dropped) so it won't
    # reappear on next poll. This is the contract: the user has made
    # a decision on this item.
    for feed_url, guids in guids_per_feed.items():
        feed_state = state.get(feed_url, {})
        seen = list(feed_state.get("seen_guids", []))
        seen_set = set(seen)
        for g in guids:
            if g not in seen_set:
                seen.append(g)
                seen_set.add(g)
        if len(seen) > MAX_SEEN_GUIDS:
            seen = seen[-MAX_SEEN_GUIDS:]
        feed_state["seen_guids"] = seen
        feed_state["last_polled"] = datetime.now(timezone.utc).isoformat()
        state[feed_url] = feed_state

    save_feed_state(vault, state)

    if selected_urls:
        new_inbox = append_feed_items_to_inbox(inbox_text, selected_urls)
        inbox_path.write_text(new_inbox, encoding="utf-8")

    return (n_selected, n_dropped)


# --- Inbox rewriting --------------------------------------------------------

def update_inbox(
    inbox_text: str,
    results: list[FetchResult],
) -> str:
    """Rewrite inbox.md after URL fetching:
    - successful URLs are moved under '## Elaborati'
    - failed URLs stay unchecked with a ⚠ reason appended inline
    """
    lines = inbox_text.splitlines()
    today = date.today().isoformat()

    result_by_url = {r.url: r for r in results}

    new_processed_lines: list[str] = []
    out_lines: list[str] = []

    for line in lines:
        match = UNCHECKED_PATTERN.match(line)
        if not match:
            out_lines.append(line)
            continue

        url = match.group(1).strip()
        if url not in result_by_url:
            out_lines.append(line)
            continue

        result = result_by_url[url]
        if result.ok:
            rel = result.out_path
            new_processed_lines.append(
                f"- [x] {url} → `{rel}` ({today})"
            )
        else:
            out_lines.append(f"- [ ] {url} ⚠ {result.reason}")

    final_lines = list(out_lines)
    if new_processed_lines:
        if not any(l.strip().lower() == "## elaborati" for l in final_lines):
            if final_lines and final_lines[-1].strip():
                final_lines.append("")
            final_lines.append("## Elaborati")
            final_lines.append("")
        final_lines.extend(new_processed_lines)

    return "\n".join(final_lines) + ("\n" if inbox_text.endswith("\n") else "")


# --- Orchestration ----------------------------------------------------------

def process_vault(
    vault: Path,
    dry_run: bool = False,
    feeds_only: bool = False,
    skip_feeds: bool = False,
) -> int:
    inbox_path = vault / "inbox.md"
    if not inbox_path.exists():
        print(f"ERROR: inbox.md not found at {inbox_path}", file=sys.stderr)
        return 1

    web_dir = vault / "raw" / "web"
    papers_dir = vault / "raw" / "papers"

    inbox_text = inbox_path.read_text(encoding="utf-8")

    # Phase 1 — Feeds
    feed_reports: list[FeedReport] = []
    if not skip_feeds:
        inbox_text, feed_reports = feed_phase(vault, inbox_text, dry_run)
        if not dry_run and feed_reports:
            inbox_path.write_text(inbox_text, encoding="utf-8")

    if feeds_only:
        _print_feed_summary(feed_reports, dry_run)
        return 0

    # Phase 2 — URLs
    entries = find_unchecked_entries(inbox_text)

    if not entries and not feed_reports:
        print("Inbox empty. Nothing to do.")
        return 0
    if not entries:
        _print_feed_summary(feed_reports, dry_run)
        print("\nNo URLs to fetch.")
        return 0

    print(f"\nFound {len(entries)} URL(s) to process.")
    if dry_run:
        for e in entries:
            print(f"  would fetch: {e.url}")
        _print_feed_summary(feed_reports, dry_run)
        return 0

    results: list[FetchResult] = []
    for e in entries:
        fetch_url, slug_override = rewrite_url_for_fetch(e.url)
        if fetch_url != e.url:
            print(f"\n→ {e.url}\n  (fetching as → {fetch_url})")
        else:
            print(f"\n→ {e.url}")

        if is_pdf_url(fetch_url):
            r = fetch_pdf(fetch_url, papers_dir, slug_override=slug_override)
        elif is_walled(fetch_url):
            host = urlparse(fetch_url).netloc.lower()
            r = FetchResult(
                url=fetch_url, ok=False, kind="failed",
                reason=f"walled domain ({host}) — {PLAYWRIGHT_HINT}",
            )
        else:
            r = fetch_html(fetch_url, web_dir)

        r.url = e.url  # keep original inbox URL for line matching
        results.append(r)
        if r.ok:
            print(f"  ✓ {r.kind} → {r.out_path}")
        else:
            print(f"  ⚠ {r.reason}")

    new_text = update_inbox(inbox_text, results)
    inbox_path.write_text(new_text, encoding="utf-8")

    # Summary
    n_html = sum(1 for r in results if r.ok and r.kind == "html")
    n_pdf = sum(1 for r in results if r.ok and r.kind == "pdf")
    n_fail = sum(1 for r in results if not r.ok)
    print()
    _print_feed_summary(feed_reports, dry_run)
    print(f"Processed {len(results)} URLs:")
    print(f"  ✓ {n_html} HTML article(s) → raw/web/")
    print(f"  ✓ {n_pdf} PDF(s) → raw/papers/")
    if n_fail:
        print(f"  ⚠ {n_fail} failed (see inbox.md for reasons)")

    return 0 if n_fail == 0 else 2


def _print_feed_summary(reports: list[FeedReport], dry_run: bool) -> None:
    if not reports:
        return
    n_feeds = len(reports)
    n_new = sum(len(r.new_items) for r in reports)
    n_dup = sum(r.skipped_dedup for r in reports)
    n_err = sum(1 for r in reports if r.error)
    tag = "[dry-run] " if dry_run else ""
    print(f"\n{tag}Feeds: {n_feeds} sottoscritti, "
          f"{n_new} nuovi item appesi, {n_dup} dedup, {n_err} errori")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch URLs and poll RSS feeds from inbox.md into raw/."
    )
    parser.add_argument(
        "--vault",
        type=Path,
        default=Path.cwd(),
        help="Path to vault root (default: current directory).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be fetched/appended, don't write.",
    )
    parser.add_argument(
        "--feeds-only",
        action="store_true",
        help="Only poll RSS feeds and append items; don't fetch URLs.",
    )
    parser.add_argument(
        "--skip-feeds",
        action="store_true",
        help="Skip RSS polling, only fetch URLs.",
    )
    parser.add_argument(
        "--rss-triage",
        action="store_true",
        help=(
            "Poll feeds without updating state or inbox. Output triage JSON "
            "to stdout: {rss_triage: [{feed, guid, url, title, summary}]}. "
            "Used by /compile to ask the user which items to fetch full."
        ),
    )
    parser.add_argument(
        "--from-triage",
        type=Path,
        default=None,
        help=(
            "Read a triage JSON file (rss_triage list with 'selected: bool' "
            "per item), mark all GUIDs as seen, append selected URLs to "
            "inbox.md ## Da processare, then proceed with URL fetch as normal."
        ),
    )
    args = parser.parse_args()

    if args.feeds_only and args.skip_feeds:
        print("ERROR: --feeds-only and --skip-feeds are mutually exclusive",
              file=sys.stderr)
        return 1

    if not args.vault.is_dir():
        print(f"ERROR: vault path is not a directory: {args.vault}",
              file=sys.stderr)
        return 1

    if args.rss_triage:
        triage = triage_feeds(args.vault)
        json.dump(triage, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0

    if args.from_triage:
        if not args.from_triage.exists():
            print(f"ERROR: triage file not found: {args.from_triage}",
                  file=sys.stderr)
            return 1
        try:
            triage_data = json.loads(args.from_triage.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"ERROR: invalid JSON in triage file: {e}", file=sys.stderr)
            return 1
        n_sel, n_drop = apply_triage(args.vault, triage_data)
        print(f"Triage applied: {n_sel} URL(s) queued, {n_drop} dropped (marked seen).")
        # Fall through to URL fetch (skip feeds — we just consumed the triage)
        return process_vault(
            args.vault,
            dry_run=args.dry_run,
            feeds_only=False,
            skip_feeds=True,
        )

    return process_vault(
        args.vault,
        dry_run=args.dry_run,
        feeds_only=args.feeds_only,
        skip_feeds=args.skip_feeds,
    )


if __name__ == "__main__":
    sys.exit(main())
