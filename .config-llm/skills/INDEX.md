# Skills — Catalogo

Catalogo machine-readable di tutte le skill installate in questo vault. Ogni skill è una cartella sotto `.config-llm/skills/` con un `SKILL.md` (istruzioni) e — quando serve — uno `scripts/`. Vedi `AGENTS.md` § "Invocazione skill" per il protocollo a 3 step (riconosci trigger → leggi SKILL.md → esegui script).

| name | trigger naturale | script | docs |
|------|------------------|--------|------|
| compile | "compila il vault", "ingest il nuovo", "/compile" | `scripts/compile.py` | [SKILL.md](compile/SKILL.md) |
| inbox-fetcher | sotto-step di /compile; "elabora inbox", "fetcha inbox", "polla i feed" | `scripts/fetch_inbox.py` | [SKILL.md](inbox-fetcher/SKILL.md) |
| canvas-builder | "fammi una timeline / comparison / slide / chart / report / post di X", "/canvas" | (template-driven, `templates/chart.py` per chart) | [SKILL.md](canvas-builder/SKILL.md) |
| vault-linter | "lint", "controlla il vault", "trova link rotti", "vault health" | `scripts/lint.py` | [SKILL.md](vault-linter/SKILL.md) |

## Note

- Tutti gli script accettano `--vault <path>` (default: cwd) e — quando rilevante — `--dry-run`.
- Lo stato persistente delle skill vive in `.config-llm/state/` (es. `feeds.json` per inbox-fetcher).
- Per aggiungere una skill nuova: crea `.config-llm/skills/<name>/SKILL.md` con frontmatter `name` + `description`, lo script in `scripts/`, e aggiungi una riga a questa tabella.
