---
name: compile
description: Orchestrator unico per rendere fruibile tutto il materiale nuovo nel vault second-brain. Quattro fasi sequenziali — fetch (con triage RSS) → scan (hash classification NEW/MODIFIED/SYNC/DRIFT) → ingest interattivo (con takeaway, tag, highlights, pages) → wrap-up (index/log/hot + auto-tick liste). Una sola azione mentale per l'utente. Usa questa skill quando l'utente dice "compila", "ingest il nuovo", "/compile", "aggiorna il wiki", "elabora tutto", oppure quando ha aggiunto materiale (URL in inbox.md, file in raw/, note in notes/) e vuole compilarlo nella wiki. Atomico per item: errore in mezzo non lascia stato inconsistente. Modalità --dry-run mostra il manifest senza scrivere. Modalità --from <path> per ingest puntuale di un singolo file.
---

# Compile

Orchestrator interattivo che porta materiale nuovo (raw + notes) dentro la wiki. È la traduzione del verbo **`/compile`** documentato in `AGENTS.md`.

## Quando usare

Trigger naturali:
- "compila", "compila il vault"
- "ingest il nuovo", "ingerisci il nuovo materiale"
- "elabora tutto", "aggiorna il wiki"
- `/compile`, `/compile --dry-run`, `/compile --from <path>`

L'utente ha appena droppato file in `raw/`, aggiunto URL/RSS a `inbox.md`, o modificato note in `notes/`. Vuole che diventi fruibile (cite-abile, query-abile, canvas-abile).

## Il flow in 4 fasi

### Fase 1 — Fetch

Esegui la skill `inbox-fetcher` in modalità triage RSS:

```bash
.venv/bin/python .config-llm/skills/inbox-fetcher/scripts/fetch_inbox.py \
    --vault . --rss-triage > /tmp/rss-triage-<timestamp>.json
```

Il file contiene `{"rss_triage": [{feed, guid, url, title, summary}, ...]}`. Se `rss_triage` è vuoto, salta direttamente alla parte URL del fetch (vedi sotto). Altrimenti:

1. Mostra all'utente la lista raggruppata per feed:
   ```
   [rss] hacker-news: 8 nuovi item
     1. LLM agents in production (Anthropic blog)
        How three patterns make agents work in prod…
     2. Why Postgres beats MongoDB again
        A long-time DBA's take on document stores…
     ...
   
   Quali fetch full? (numeri / 'all' / 'none')
   ```
2. Raccogli selezione utente. Aggiorna il JSON aggiungendo `"selected": true|false` a ogni item.
3. Salva il JSON aggiornato e invoca:
   ```bash
   .venv/bin/python .config-llm/skills/inbox-fetcher/scripts/fetch_inbox.py \
       --vault . --from-triage /tmp/rss-triage-<timestamp>.json
   ```
4. `inbox-fetcher` con `--from-triage` marca i GUID come seen (selected o no), appende gli URL selected a `## Da processare`, poi scarica full come URL normali. Internamente passa al fetch URL standard, saltando il polling feed (già fatto).

Per gli URL `## Da processare` non legati a feed (URL che l'utente ha incollato a mano), `inbox-fetcher` li elabora come parte dello stesso run.

In modalità `--dry-run`: salta il triage interattivo e mostra solo cosa verrebbe pollato.

### Fase 2 — Scan

Esegui `scripts/compile.py --vault . --scan-only` (oppure inline in Python). Lo scan:

1. Lista ricorsivamente `raw/**/*` e `notes/**/*.md`.
2. Per ogni file calcola sha256 del contenuto.
3. Per ogni `wiki/sources/*.md` legge `source_path` e `content_hash`.
4. Classifica ogni file:
   - **NEW** — nessuna source page con quel `source_path`.
   - **SYNC** — hash uguale a `content_hash` registrato → skip, bump `last_checked`.
   - **MODIFIED** — hash diverso da `content_hash`. Sub-classifica:
     - **incrementale** (<30% diff, no cambio heading top-level)
     - **sostanziale** (≥30% o cambio heading top-level)
   - **DRIFT** — source page esiste ma `source_path` non risolve.
5. **Mostra manifest** all'utente:
   ```
   [scan]
     NEW       6 file
               ├─ raw/web/articolo-debian/index.md
               └─ ...
     MODIFIED  2 file
               ├─ notes/ideas/canvas-builder.md (incrementale ~8%)
               └─ notes/projects/sal-q3.md       (sostanziale ~45%)
     SYNC      143 file (skip)
     DRIFT     0
   
   Procedo? [y/n]
   ```
6. **Gate >15 file**: se `NEW + MODIFIED > 15`, fermati. Chiedi all'utente come segmentare (per cartella, per data, per tag). Invariante #3 di `AGENTS.md`.
7. Se `--dry-run`, esci qui.
8. Se `NEW + MODIFIED == 0`, salta direttamente a Fase 4.

### Fase 3 — Ingest interattivo

Loop per ogni item NEW + MODIFIED. **Uno alla volta**. Atomico per item.

Per ogni item:

1. Mostra metadati: titolo, autore, data, lingua, length, conteggio highlights `==text==`.
2. **Genera takeaway**: una sintesi di 2-4 righe in italiano di cosa hai capito dalla fonte (tema, punto centrale, claim notevoli). **Questo step non è opzionale** — è la differenza tra ingest meccanico e dialogico. Per il fallback Python standalone (se la skill è invocata via subprocess senza LLM), usa un riassunto estrattivo (prime 3 frasi non vuote + bullet sui primi 3 highlight).
3. **Proponi tag**: estrai keyword dal contenuto, intersecali con tag già presenti in altre source/page del vault per consistency. Default a tag liberi, suggerisci `kind:*` opzionale se il tipo è ovvio (es. PDF di paper → `reading`; software trovato → `tool`).
4. **Proponi pages**: identifica pages esistenti citate o concetti nuovi che meritano una page propria. Soft-limit: max 3 page nuove per item.
5. **Per MODIFIED sostanziali**: aggiungi opzioni `version` / `overwrite` / `show-diff` ai comandi.
6. Attendi azione utente:
   - `ingest` — procedi.
   - `skip` — salta, file resta dove sta, riproposto al prossimo `/compile`.
   - `edit-tags` — apri editor inline o accetta tag rivisti dall'utente.
   - `show-content` — mostra il contenuto del file.
   - `forget` — cancella il file (solo per RSS finiti in raw per errore).
   - `version` / `overwrite` / `show-diff` — solo MODIFIED sostanziale.
7. Su `ingest`:
   - Se raw/web/ con frontmatter incompleto, normalizzalo (unica scrittura ammessa in raw, una sola volta).
   - Estrai highlights `==(.+?)==`, assegna `H1`, `H2`, ... in ordine.
   - Scrivi/aggiorna `wiki/sources/<slug>.md` con frontmatter completo (`source_path`, `content_hash`, `ingested`, `last_checked`, `tags`, eventuali `supersedes`/`superseded_by`) + sezione `## Highlights` + `## Sintesi` in italiano con citazioni inline per claim specifici.
   - Scrivi/aggiorna `wiki/pages/<slug>.md` per ogni page identificata.
   - Naming source: senza data per `raw/`, con data `<slug>-<YYYY-MM-DD>.md` per `notes/`.
   - Verifica inbound link su page nuove (orphan check); se zero, aggiungi un link da una page esistente o flagga in `log.md` come orphan intenzionale.
8. Su `version` (MODIFIED sostanziale): crea `<slug>-<oggi>.md`, marca old `superseded_by: [[new]]`, new `supersedes: [[old]]`. **Mai riscrittura automatica** della prosa di pages citanti — solo flag.
9. Append entry a `wiki/log.md`:
   ```
   ## [YYYY-MM-DD] ingest | <slug>
   source: <source_path>
   content_hash: <hash[:12]>…
   highlights: <N>
   pages: [[a]] (created), [[b]] (updated)
   ```
10. Se errore di parsing/scrittura: salta l'item, raccogli per il wrap-up, **non corrompere** lo stato.

### Fase 4 — Wrap-up

1. Aggiorna `wiki/index.md` con entry per pages nuove, source nuove, eventuali versionamenti.
2. Append entry chiusura a `wiki/log.md` con totali.
3. Riscrivi `wiki/hot.md` (5-10 righe: cosa coperto, cosa aperto, da dove riprendere).
4. **Auto-tick liste**: per ogni fonte ingerita questo run, cerca match in `notes/lists/*.md`:
   - Match URL esatto: preferito.
   - Match fuzzy title (threshold 0.85): fallback.
   - Su match: proponi `- [ ]` → `- [x]` con conferma utente. Mai automatico.
5. Stampa summary:
   ```
   [done]
     Ingerite: N nuove, M modificate (X versioned)
     Pages: A create, B aggiornate
     Highlights: H estratti
     Liste: <file> (Y item spuntati)
   ```
6. Se ultimo LINT > 7 giorni fa (legge `.lint/state.yaml`), suggerisci `/lint`.

## Come eseguirla

Da agente LLM-driven (Claude, OpenCode, Hermes):

1. Riconosci trigger naturale.
2. Leggi questo `SKILL.md`.
3. Esegui le 4 fasi in dialogo con l'utente, usando i sotto-script:
   - `inbox-fetcher` per la Fase 1.
   - `scripts/compile.py --scan-only` per la Fase 2 (deterministico, no LLM).
   - Tu (LLM) per la Fase 3 (takeaway, tag, prosa di sintesi).
   - `scripts/compile.py --wrap-up <changes.json>` per la Fase 4 (index/log/hot/auto-tick, deterministico).

Da CLI puro (no agente):

```bash
# Tutto in cascata, interattivo via stdin/stdout
python .config-llm/skills/compile/scripts/compile.py --vault .

# Solo scan (manifest, no scritture)
python .config-llm/skills/compile/scripts/compile.py --vault . --dry-run

# Ingest puntuale di un file
python .config-llm/skills/compile/scripts/compile.py --vault . --from raw/web/articolo/index.md
```

Lo script Python standalone usa il fallback estrattivo per takeaway/tag — utile per smoke test, ma per l'uso reale è meglio invocare via agente LLM.

## Dipendenze

Solo libreria standard Python per scan e wrap-up. Per la Fase 1, dipende da `inbox-fetcher` (che ha le sue: `trafilatura`, `requests`, `feedparser`, `python-slugify`).

## Non in scope

- Generare canvas (delegato a `canvas-builder`).
- Rispondere a domande (delegato a /query, che è LLM-driven, non scriptato).
- Health check (delegato a `vault-linter`).
- Riscrivere prosa di pages esistenti senza conferma esplicita utente (mai).
- Bypassare il gate >15 file (mai).
