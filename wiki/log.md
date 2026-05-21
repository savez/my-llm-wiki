# Wiki Log

Append-only chronological log of operations on `wiki/`. English by design.

Operations: `ingest`, `sync`, `query`, `view`, `forget`, `lint`, `reflect`.

Format:

```
## [YYYY-MM-DD] <op> | <subject>
One-line detail.
```

Parse last 10 with: `grep "^## \[" wiki/log.md | tail -10`.

---

<!-- example entries:
## [2026-05-20] ingest | attention-is-all-you-need
Created source page and updated `transformer` concept page.

## [2026-05-20] sync   | progetto-x v2 (supersedes v1)
Substantive change: new source page created, v1 marked superseded.

## [2026-05-20] view   | agent-architectures-map
Concept-map, shareable: false. Based on 4 pages + 2 sources.

## [2026-05-20] lint   | wiki-health-check
3 dead links, 1 orphan page. See .lint/report.md.
-->
