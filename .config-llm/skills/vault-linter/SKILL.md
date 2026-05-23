---
name: vault-linter
description: Esegue check deterministici di salute su un vault wiki second-brain (link morti, pagine orfane, duplicati, metadata mancante, naming inconsistente, source stantie, gap, canvas stantie, cross-reference mancanti, content_hash drift, highlights drift, quality signals, supersedes simmetria, free-tag variants, log rotation) e scrive un report in .lint/report.md. Usa questa skill quando l'utente dice "lint", "controlla il vault", "vault health", "trova link rotti". Da eseguire anche periodicamente — triggera quando si sono accumulati 5+ ingest dall'ultimo lint OPPURE sono passati 7+ giorni. Supporta modalità unattended via flag --unattended. Veloce, zero token LLM consumati.
---

# Vault Linter

Health check deterministico per il vault. Gira in millisecondi, consuma zero token LLM.

## Quando usare

- L'utente dice "lint", "controlla il vault", "trova link rotti".
- Prima di `/reflect`, se `.lint/state.yaml` mostra stantiezza (≥5 ingest o ≥7 giorni dall'ultimo lint).
- Dopo un batch di ingest, per verificare l'integrità.
- Modalità unattended, schedulata.

## Cosa controlla

Quindici check deterministici. Ognuno produce finding con path concreti.

| # | Check | Cosa intercetta |
|---|---|---|
| 1 | **dead_links** | `[[path]]` che punta a file inesistenti (anchor `#H<n>` ignorati per la risoluzione) |
| 2 | **orphans** | Pagine con zero inbound link (esclusi hot.md/compass.md/index.md/log.md; canvas esenti perché leaf) |
| 3 | **duplicates** | Pagine con titoli simili nella stessa sottocartella |
| 4 | **missing_metadata** | Frontmatter senza campi richiesti per il `type` (source: type/source_path/content_hash/ingested/last_checked; page: type/created/updated; canvas: type/kind/created/updated/based_on) |
| 5 | **inconsistent_naming** | Stesso target linkato con >2 nomi diversi |
| 6 | **stale_sources** | Source pages con `last_checked` (o legacy `updated`) > 180 giorni |
| 7 | **gaps** | Nomi di concetti ricorrenti (≥3 menzioni) senza page corrispondente |
| 8 | **canvas_staleness** | Canvas evolutivi (`shareable: false`) il cui `based_on` punta a pagine modificate più di 30 giorni dopo |
| 9 | **missing_cross_references** | Source pages che citano una page nella prosa senza link |
| 10 | **content_hash_drift** | `content_hash` (o legacy `raw_sha256`) non corrisponde all'hash del file in `raw/`/`notes/` |
| 11 | **highlights_drift** | `==text==` nel raw non corrisponde agli `H<n>` nella sezione `## Highlights` della source page (count, ordering, o testo) |
| 12 | **quality_signals** | Pages con `confidence: low`, `contested: true`, mono-fonte senza confidence, asimmetrie in `contradictions:` |
| 13 | **supersedes_symmetry** | Source pages con `supersedes`/`superseded_by` senza puntamento reciproco |
| 14 | **free_tag_variants** | Varianti case-insensitive di tag liberi (es. `claude-code` vs `Claude-Code`) |
| 15 | **log_rotation** | `wiki/log.md` supera 500 entry → propone rotazione |

I check 3, 5, 7, 9, 14 sono euristici — possono produrre falsi positivi, marcati come advisory.

## Cosa NON controlla più (rispetto a v4)

- `topic:*` o `kind:*` obbligatori nei tag. La taxonomy nuova ha tag liberi + `kind:*` opzionale come campo top-level del frontmatter (non più un tag).
- Namespace enforcement contro lista chiusa.

## Come si esegue

```bash
# Dalla root del vault
python .config-llm/skills/vault-linter/scripts/lint.py

# Unattended (no prompt)
python .config-llm/skills/vault-linter/scripts/lint.py --unattended

# Da fuori il vault
python .config-llm/skills/vault-linter/scripts/lint.py --vault /path/to/vault
```

## Exit code

- `0` — pulito (zero finding)
- `1` — finding presenti (atteso; non è un failure)
- `2` — errore dello script

## Output

### `.lint/report.md`

Finding raggruppati per severità:

- **Blocking** — link morti, metadata richiesto mancante, content_hash su file mancante.
- **Important** — orfane, gap, content_hash drift, highlights drift count mismatch, contradictions a pages sconosciute.
- **Advisory** — duplicati, stantie, naming, canvas stantie, free-tag variants, quality signals, supersedes asimmetria, highlights drift textuale.

### `.lint/state.yaml`

```yaml
last_lint: 2026-05-23
ingests_since_last_lint: 0
last_exit_code: 1
last_findings_count: 12
```

## Dipendenze

Solo libreria standard Python. Nessun `pip install` necessario.

## Cosa il linter NON fa

- **Non aggiusta nulla.** Solo report.
- **Non usa un LLM.** Python puro su testo e filesystem.
- **Non valida il contenuto semantico.** Quello è compito di `/reflect`.

## Come l'agente usa l'output

**Interattivo:** legge il report, riassume ("X blocking, Y important, Z advisory"), propone di fixare i blocking adesso.

**Unattended:** gira; se catastrofico (>50 link morti) aborta qualunque `/reflect` successivo. Altrimenti annota il sommario lint in `compass.md` come breve footer.
