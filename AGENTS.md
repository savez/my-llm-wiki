# LLM Wiki — Second Brain Vault

Vault personale di conoscenza mantenuto da un agente LLM, basato sul pattern _LLM Wiki_ di Karpathy (https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

Letto da qualsiasi agente che opera sul vault (Claude Code, OpenCode, Codex, Hermes). `CLAUDE.md` e altri agent file sono symlink a questo.

**Principio guida**: `raw/` e `notes/` sono ground truth. `wiki/` è compilato a partire da loro e può essere ricostruito. Tu curi le fonti, fai domande, guidi l'analisi. L'agente legge, sintetizza, mantiene la wiki, e tiene il pensiero in salute nel tempo.

---

## Architettura

Tre piani, separati per regime di mutabilità:

- **`raw/`** — ground truth immutabile. Popolato da `inbox-fetcher` (URL+RSS da `inbox.md`) o capture manuale (incolla-paste, drop PDF). Dopo l'ingresso non si tocca più.
- **`notes/`** — tue note grezze, struttura libera. Sottocartelle indicative (`books`, `conferences`, `ideas`, `meetings`, `scratch`, `varie`, `lists`). Scrivi come ti viene.
- **`wiki/`** — l'unico posto che l'agente costruisce attivamente, attingendo da `raw/` e `notes/`. Contiene `pages/` (concetti), `sources/` (una pagina per file ingerito), `canvas/` (artefatti strutturati: slide, post, timeline...), più `compass.md`, `hot.md`, `index.md`, `log.md`.

Per claim ad alto rischio (numeri, citazioni esatte, fatti legali/medici), risali sempre alla fonte. La wiki sintetizza ma non sostituisce.

---

## I 4 verbi

Quello che hai in testa nell'uso quotidiano:

| Verbo | Cosa fai | Cosa fa l'agente |
|---|---|---|
| **Aggiungo** | Droppi materiale in `raw/`, scrivi in `notes/`, aggiungi URL/RSS a `inbox.md`. Marchi con `==testo==` ciò che ti colpisce. | Nulla — sono cartelle/file tuoi. |
| **`/compile`** | Lanci quando vuoi rendere fruibile il nuovo. | Fetch + triage RSS, scan raw+notes, ingest interattivo con takeaway/tag/highlights, aggiorna index+log+hot. |
| **`/query`** (o domanda naturale) | Chiedi informazioni alla wiki. | Risponde con citazioni; se vale, propone save-back in una page. |
| **`/canvas`** | Chiedi artefatto strutturato: post LinkedIn, articolo, slide, timeline, comparison, concept-map, chart, report. | Costruisce in `wiki/canvas/<slug>.md` attingendo da pages+sources. |

**Operazioni secondarie** (on-demand, non quotidiane):
- `/forget <source>` — cascade-removal
- `/reflect` — riscrive `wiki/compass.md`
- `/lint` — health check del vault

---

## Aggiungo: dove va cosa

### `raw/papers/<slug>.pdf`
Droppi il PDF. `/compile` lo rileva via sha256, ti chiede di ingerirlo.

### `raw/web/<slug>/index.md`
Articoli web. Due strade:
- **Via inbox-fetcher**: metti URL in `inbox.md`, `/compile` lo scarica.
- **Capture manuale**: incolli a mano (per contenuti login-walled, thread X, post LinkedIn, email forwardate, highlight ebook). Frontmatter consigliato:

```yaml
---
source_url: <url o omesso per snippet senza fonte web>
title: <titolo>
author: <se noto>
published: <YYYY-MM-DD se noto>
fetched: <data cattura>
fetched_via: trafilatura | playwright | manual
---
```

Convenzioni per tipologia: vedi **Appendice C**.

### `notes/`
Note libere. Sottocartelle indicative:
- `notes/meetings/` — call, riunioni
- `notes/conferences/` — talk, podcast
- `notes/books/` — lettura
- `notes/ideas/` — brainstorm, prototipi
- `notes/scratch/` — zibaldone
- `notes/varie/` — il resto
- `notes/lists/` — wishlist (`books-to-read.md`, `articles-to-read.md`, `sites-to-visit.md`, `software-to-try.md`...). `/compile` può auto-spuntare item quando li ingerisci.

Aggiungi, rinomina, riorganizza come ti pare. L'agente scansiona ricorsivamente.

### `inbox.md`
Coda di URL e feed RSS. Sezioni `## Da processare`, `## Feeds`, `## Elaborati` (storico con timestamp). Aggiungi tu, `/compile` elabora.

### Highlights `==testo==`

Sintassi unica per marcare passaggi importanti, valida ovunque (raw/web/, notes/):

```markdown
Il punto centrale è che ==l'attenzione è tutto ciò di cui hai bisogno==
e questo cambia il paradigma. Poi nota che ==i transformer scalano meglio==.
```

Durante `/compile`, l'agente estrae tutti i match `==(.+?)==`, assegna ID stabili (`H1`, `H2`...), e li promuove nella **source page** sotto sezione `## Highlights`. Le page concettuali possono citarli puntualmente: `[[wiki/sources/articolo#H2]]`.

Il `raw/` non viene mai modificato dall'estrazione (invariante #1).

---

## `/compile`

Comando unico per rendere fruibile tutto il materiale nuovo. Quattro fasi sequenziali, interattive.

### Fase 1 — Fetch (auto)

```
$ /compile

[fetch] inbox.md: 2 nuovi URL → raw/web/
[fetch] RSS: 8 nuovi item, triage:

  1. [hacker-news] LLM agents in production (Anthropic)
     Summary: How three patterns make agents work in prod…
  2. [hacker-news] Why Postgres beats MongoDB again
     Summary: A long-time DBA's take on document stores…
  3. [paul-graham] Working on hard problems
     Summary: Essay on choosing what to work on…
  ...

Quali fetch full? (numeri / 'all' / 'none')
> 1, 3
```

Triage RSS = scelta su title + feed-summary, senza scraping aggressivo. Solo i selezionati vengono scaricati full in `raw/web/`. Gli scartati restano dedupati in `.config-llm/state/feeds.json` come "seen" e non riappaiono.

### Fase 2 — Scan

Computa sha256 di tutto `raw/` + `notes/`, classifica:

- **NEW** — nessuna source page esistente
- **MODIFIED** — hash diverso da `content_hash` registrato
- **SYNC** — hash uguale (skip, bump `last_checked`)
- **DRIFT** — source page esiste ma `source_path` non risolve

Mostra manifest **prima di toccare nulla**:

```
[scan]
  NEW       6 file
            ├─ raw/web/articolo-debian/index.md
            ├─ raw/web/llm-agents/index.md
            └─ ...
  MODIFIED  2 file
            ├─ notes/ideas/canvas-builder.md   (incrementale ~8%)
            └─ notes/projects/sal-q3.md         (sostanziale ~45%)
  SYNC      143 file (skip)
  DRIFT     0

Procedo con ingest interattivo? [y/n]
```

Se NEW + MODIFIED > 15 si ferma e chiede come segmentare (invariante #3).

### Fase 3 — Ingest interattivo

Loop per ogni item NEW + MODIFIED. **Uno alla volta**. Lo step è dialogico: l'agente mostra cosa ha capito, tu correggi se serve.

```
─────────────────────────────────────────────
[1/8] NEW · raw/web/articolo-debian/index.md
  Titolo: Il progetto Debian non accetterà più pacchetti non riproducibili
  Autore: miamammausalinux | Published: 2026-05-20
  Lingua: it | Length: ~1200 parole
  Highlights trovati: 3
    H1: "la riproducibilità è la base della supply-chain trust"
    H2: "ogni pacchetto deve essere bit-per-bit identico se ricompilato"
    H3: "i maintainer hanno tempo fino a fine 2026"

  Takeaway (mia lettura):
  • Debian attiva un policy gate: pacchetti non bit-per-bit
    riproducibili vengono bloccati da testing.
  • Motivazione esplicita: hardening della supply-chain.
  • I maintainer hanno deadline fine 2026.

  Tag proposti: debian, supply-chain, reproducible-builds, security
  kind: reading

  Pages candidate:
    [[debian]]         (esistente, aggiungo riferimento)
    [[supply-chain]]   (nuova, creo se confermi)

  Azione? [ingest / skip / edit-tags / show-content / forget]
> ingest
```

Il **takeaway** è uno step esplicito e non opzionale: l'agente dichiara cosa ha capito prima di proporre tag e pages. Tu correggi a voce o con `edit-tags` / `show-content`. È la differenza tra ingest meccanico e ingest dialogico.

**Comandi disponibili a ogni item**:
- `ingest` — procedi con takeaway/tag/pages proposti.
- `skip` — non ingerire ora; il file resta dove sta, riproposto al prossimo `/compile`.
- `edit-tags` — modifichi tag/kind/pages prima di confermare.
- `show-content` — mostra il contenuto del file.
- `forget` — cancella il file in raw (solo per RSS finiti per errore).

**Per MODIFIED sostanziali** (≥30% diff o cambio di heading top-level), step extra:

```
[3/8] MODIFIED · notes/projects/sal-q3.md (substantial, ~45%)
  Diff: 12 heading nuovi, 3 rimossi
  Source page corrente: sal-q3-2026-04-10.md

  Azione? [version / overwrite / skip / show-diff]
> version
  → Creo sal-q3-2026-05-23.md, marco supersedes/superseded_by.
  → Le pages [[lavoro-sal]] e [[okr-q3]] citavano la versione precedente.
    Le flaggo per review? [y/n]
> y
```

**Mai riscrittura automatica della prosa di pages**. L'agente flagga, tu rivedi.

Atomico per item: errore in mezzo non lascia stato inconsistente, l'item fallito viene riportato al wrap-up.

### Fase 4 — Wrap-up

```
[done]
  Ingerite: 5 nuove fonti, 2 modificate (1 versioned)
  Pages: 3 create, 7 aggiornate
  Highlights estratti: 14
  Liste: articles-to-read.md aggiornata (1 item spuntato)

  index.md, log.md, hot.md aggiornati.

  Ultimo LINT 6 giorni fa, suggerisco /lint. [y/n]
```

**Auto-tick liste**: per ogni fonte ingerita, l'agente cerca match in `notes/lists/*.md` per URL (preferito) o titolo (fuzzy, threshold 0.85). Su match propone `[ ]` → `[x]`. Mai automatico, sempre conferma.

### Opzioni

- `/compile --dry-run` — esegue Fase 1+2, mostra manifest, esce senza scrivere.
- `/compile --from <path>` — ingest puntuale su una singola fonte, salta scan generale.

---

## `/query`

Domanda naturale o slash:

1. Legge `wiki/hot.md` (dove eravamo).
2. Legge `wiki/index.md` per identificare le pages rilevanti.
3. Se esiste un canvas pertinente in `wiki/canvas/`, lo legge — è sintesi pre-compilata, spesso più veloce.
4. Risponde usando solo claim tracciabili nel vault. Cita pages nella chat, raw/notes nelle pages.
5. Se il vault non basta, lo dice. Non riempie i buchi con training data.
6. Se la risposta vale, propone save-back come page nuova o folded in una esistente.

---

## `/canvas`

Crea un artefatto strutturato in `wiki/canvas/`. Sette `kind`: `timeline`, `comparison`, `concept-map`, `chart`, `slides`, `report`, `post`.

**Mermaid** è il formato preferito per `concept-map`, `timeline`, diagrammi di flusso. È testo, vive nel markdown, renderizza ovunque, è rigenerabile.

**Pattern editoriale a due stadi** (consigliato per output destinati a condivisione esterna):
1. Sintesi interna (`comparison`, `concept-map`, `timeline`) con `shareable: false`. È "ho capito il tema".
2. Output di condivisione (`post`, `report`, `slides`) derivata dalla prima. È "ecco come lo racconto fuori".

Per i kind orientati alla condivisione, l'agente chiede se la canvas nasce già `shareable: true`. Quando `shareable: true`, la canvas è **congelata**: non viene rigenerata anche se le pages sottostanti cambiano.

**Citazioni nelle canvas**: stesse regole delle pages. Ogni claim cita una fonte o una page. Le citazioni stanno nelle note di accompagnamento, non dentro i diagrammi.

---

## Wiki structure

Tre tipi di file in `wiki/`. Ognuno ha frontmatter YAML.

### Page (`wiki/pages/`)

```yaml
---
type: page
created: 2026-05-23
updated: 2026-05-23
tags: [free, tags, here]    # tag liberi, vedi Appendice A per taxonomy opzionale
kind: concept                # opzionale: concept|tool|person|org|project|method|event|decision|reading
---

# Titolo

**Riassunto**: 1-2 frasi.

**Fonti**: elenco dei file in `raw/` o `notes/` o link `[[wiki/sources/...]]`.

**Ultimo aggiornamento**: YYYY-MM-DD.

---

Contenuto principale. Collega concetti con [[wiki-link]].

## Pagine collegate

- [[concetto-collegato-1]]
```

### Source (`wiki/sources/`)

```yaml
---
type: source
source_path: raw/web/articolo-debian/index.md
content_hash: a3f5...
ingested: 2026-05-23
last_checked: 2026-05-23
tags: [debian, supply-chain]
supersedes: null              # opzionale, default null
superseded_by: null           # opzionale, default null
---

# Titolo (in italiano)

**Riassunto**: 1-2 frasi sulla fonte.

**Fonti**: path raw o note originale.

## Highlights

- **H1**: "passaggio importante 1"
- **H2**: "passaggio importante 2"
- **H3**: "passaggio importante 3"

## Sintesi

Prosa in italiano. Citazioni inline per claim specifici.
```

Naming source:
- Da `raw/papers/` o `raw/web/`: senza data (`attention-is-all-you-need.md`) — la fonte è davvero immutabile.
- Da `notes/`: con data (`progetto-x-2026-05-20.md`) fin dalla prima versione — la nota può evolvere.

### Canvas (`wiki/canvas/`)

```yaml
---
type: canvas
kind: post | slides | report | timeline | comparison | concept-map | chart
shareable: false                # true = congelata
created: 2026-05-23
updated: 2026-05-23
based_on:
  - [[wiki/pages/debian]]
  - [[wiki/sources/articolo-debian]]
tags: [debian, supply-chain]
---
```

### Lingua

- `raw/` lingua originale. **Mai tradurre**.
- `notes/` segue te.
- `wiki/pages/`, `wiki/sources/`, `wiki/canvas/` in **italiano**. Citazioni verbatim possono restare in lingua originale dentro prosa italiana.
- `compass.md`, `hot.md` in **italiano**.
- `index.md`, `log.md` in **inglese** (metadati operativi).
- Risposte in chat seguono te.

### Citazioni

Ogni **claim fattuale, numerico, citazione testuale, o conclusione specifica** cita inline. Frasi di sintesi che riassumono materiale citato altrove nella stessa page **non richiedono citazione duplicata** se la sezione `Fonti` in alto è completa.

- Per fonti raw: `(fonte: raw/papers/nome.pdf)` o `(fonte: raw/web/<slug>/index.md)`.
- Per note: `(fonte: notes/meetings/2026-05-20-acme.md)`.
- Per source page: `[[wiki/sources/<slug>]]` o `[[wiki/sources/<slug>#H2]]` per highlight specifico.
- Per inferenze senza fonte diretta: `(sintesi — da verificare)`.
- Se due fonti disagree, marca la contraddizione con entrambe le citazioni.

---

## Tracciamento freschezza

Principio: **la source page è il registro**. Niente file di stato extra. Se esiste `wiki/sources/<slug>.md` con `source_path: raw/web/articolo/index.md`, allora quella fonte è ingerita.

### Stati durante `/compile` scan

- **NEW**: nessuna source page → da ingerire.
- **SYNC**: hash uguale a `content_hash` → ignora (bump `last_checked`).
- **MODIFIED incrementale** (<30% diff, no cambio heading top): update in place, bump `content_hash`, aggiorna page citanti se highlights cambiati.
- **MODIFIED sostanziale** (≥30% o cambio heading top): propone versioning. Crea `<slug>-<YYYY-MM-DD>.md`, marca `supersedes`/`superseded_by`. Pages citanti vengono flaggate per review, **mai riscritte automaticamente**.
- **DRIFT**: source page esiste ma `source_path` non risolve. Segnala, propone `/forget` o re-link.

### LINT come safety net

`/lint` ricomputa `content_hash` su tutti i source files, segnala drift silenzioso (raw modificato a mano fuori da `/compile`), source page con `source_path` mancante, `supersedes`/`superseded_by` asimmetrici, highlights drift. Sempre report → tu decidi. **Mai auto-fix**.

---

## Le 4 invarianti

Mai violarle.

1. **`raw/` è immutabile dopo l'ingresso.** Eccezioni: normalizzazione frontmatter alla prima ingestione, `/forget` user-directed.
2. **Claim fattuali, numerici, e citazioni testuali tracciano la fonte inline.** Sintesi possono fare riferimento alla sezione `Fonti` della page.
3. **≤15 file toccati per operazione.** Oltre → ferma e chiedi.
4. **Aggiorna `index.md` e `log.md` dopo ogni scrittura in `wiki/`.**

---

## Operazioni secondarie

### `/forget <source>`

Cascade-removal di una fonte e tutto ciò che dipendeva solo da lei.

1. Risolve target: `wiki/sources/<slug>.md` e il file in `raw/` o `notes/`.
2. Grep per ogni riferimento. Elenca all'utente.
3. Per ogni `wiki/pages/` che cita: claim supportato da altre fonti → rimuove solo la citazione; claim mono-fonte → propone rimozione o degrade a "non verificato". **Chiede prima di cancellare prosa.**
4. Per ogni canvas con la fonte in `based_on`: `shareable: false` → rigenera; `shareable: true` → non tocca, avverte di citazioni dangling.
5. Per source versionate: gestisce catena `supersedes`/`superseded_by`.
6. Cancella `wiki/sources/<slug>.md` e il file in raw/notes. Unica eccezione all'invariante #1.
7. Aggiorna `index.md` e `log.md`.

Se la fonte è citata da >15 file, supera l'invariante #3: ferma, riporta fanout, tu scegli.

### `/reflect`

Riscrive `wiki/compass.md` da zero. Tre sezioni in italiano:
1. **Dove sta andando il mio pensiero** (3-5 righe)
2. **Cosa non sto guardando** (3-5 bullet con link a pages)
3. **Una domanda su cui vale la pena fermarsi** (una sola)

Include problemi strutturali (page duplicate, orphan, canvas stantie), insight in `conversations/` non ancora filati, note mature in `notes/ideas/` o `notes/scratch/`.

### `/lint`

Skill `vault-linter`. Solo check deterministici, **mai auto-fix**.

- Dead link, frontmatter malformato, naming inconsistente.
- Canvas stantie (`based_on` punta a pages aggiornate dopo la canvas).
- Pages orphan (zero inbound link).
- Concetti citati ma senza page propria.
- Claim potenzialmente outdated alla luce di fonti più recenti.
- Drift `content_hash` (raw modificato fuori da `/compile`).
- `supersedes`/`superseded_by` asimmetrici.
- Highlights drift (`==X==` nel raw non corrisponde a `H<n>` nella source page).
- Tag drift su varianti (claude-code vs claudecode vs Claude-Code → warning).
- Log rotation soglia (>500 entry → propone rotation).

Output in `.lint/report.md`. Append `## [data] lint | wiki-health` a `log.md`.

**Trigger**: on-demand, oppure suggerito da `/compile` se ultimo LINT > 7 giorni.

---

## Hot cache, compass, log, index

### `wiki/hot.md`
5-10 righe: cosa abbiamo coperto, cosa è rimasto aperto, da dove riprendere. **Riscritto, non aggiunto**. Aggiornato a fine `/compile` o fine sessione significativa. A inizio sessione, l'agente lo legge per primo.

### `wiki/compass.md`
Output di `/reflect`. Riflessione strategica. Riscritto da zero ogni volta.

### `wiki/index.md`
Content-oriented, inglese. Lista pages/sources/canvas per categoria con descrizione one-line. Aggiornato a ogni scrittura in `wiki/`.

```markdown
# Wiki Index

## Concepts
- [[transformer]] — Self-attention architecture
- [[mixture-of-experts]] — Sparse expert routing

## Models
- [[claude-opus-4-7]] — Anthropic's flagship as of 2026

## Sources (notes)
- [[progetto-x-2026-05-20]] — Project X idea, v2 (supersedes 2026-03-15)
```

### `wiki/log.md`
Chronological, append-only, inglese. Una entry per operazione.

```markdown
## [2026-05-23] ingest | articolo-debian
source: raw/web/articolo-debian/index.md
content_hash: a3f5...
highlights: 3
pages: [[debian]] (created), [[supply-chain]] (updated)

## [2026-05-23] sync   | canvas-builder (incremental, 8%)
## [2026-05-23] query  | rag-vs-long-context-tradeoffs
## [2026-05-23] canvas | agent-architectures-map
## [2026-05-23] forget | obsolete-paper-xyz
## [2026-05-23] lint   | wiki-health-check
```

Parseable: `grep "^## \[" wiki/log.md | tail -10`.

**Rotation**: quando supera 500 entry (`grep -c "^## \[" wiki/log.md`), `/lint` segnala. Con conferma utente: rinomina `log.md` → `log-YYYY.md`, crea nuovo `log.md`, prima entry `## [data] rotate | logs archived to log-YYYY.md`. Logs ruotati restano per sempre. **Nessun auto-rotate**.

---

## Modalità unattended

Quando l'agente è invocato con `--unattended`, `VAULT_UNATTENDED=1`, o "unattended" nel prompt:

**Permesso**: leggere qualunque cosa, eseguire `/lint`, eseguire `/reflect`, aggiornare `compass.md`, `hot.md`, `log.md`, `.lint/report.md`.

**Non permesso**: ingest, sync, forget, creare canvas, modificare `wiki/pages/`, cancellare nulla da `raw/`/`notes/`/`wiki/sources/`, applicare cambiamenti strutturali. Le proposte restano proposte finché tu non confermi.

---

## Slash command

- `/compile` — fetch + scan + ingest interattivo
- `/compile --dry-run` — solo manifest, niente scritture
- `/compile --from <path>` — ingest puntuale
- `/query` (o domanda naturale) — domanda alla wiki
- `/canvas [kind] [topic]` — costruisce artefatto
- `/forget <source>` — cascade-removal
- `/reflect` — produce `compass.md`
- `/lint` — health check
- `/save [nome]` — salva conversazione corrente in `conversations/`

Per il resto, linguaggio naturale.

---

## Invocazione skill

Le skill vivono in `.config-llm/skills/<name>/`. Ogni skill ha:

- `SKILL.md` — frontmatter (`name`, `description`) + istruzioni
- `scripts/` — script Python eseguibili dalla root del vault
- eventuali `templates/`, `assets/`

Catalogo in `.config-llm/skills/INDEX.md`. Skill correnti:

| name | trigger | docs |
|---|---|---|
| compile | `/compile`, "compila", "ingest il nuovo" | [SKILL.md](.config-llm/skills/compile/SKILL.md) |
| inbox-fetcher | (sotto-step di /compile) | [SKILL.md](.config-llm/skills/inbox-fetcher/SKILL.md) |
| canvas-builder | `/canvas`, "fammi una timeline/post/slide di X" | [SKILL.md](.config-llm/skills/canvas-builder/SKILL.md) |
| vault-linter | `/lint`, "controlla il vault" | [SKILL.md](.config-llm/skills/vault-linter/SKILL.md) |

Il vault è **agent-agnostic per design**. Protocollo a 3 step per ogni agente:
1. Riconosce il trigger naturale.
2. Legge `.config-llm/skills/<name>/SKILL.md`.
3. Esegue lo script associato via shell, dalla root del vault.

Tutti gli script accettano `--vault <path>` (default: cwd) e dove ha senso `--dry-run`.

---

## Quando in dubbio

- Se una regola crea frizione, **proponi una modifica** all'utente. Non emendare silenziosamente questo file.
- Se non riesci a tracciare un claim a una fonte, non farlo.
- Se stai per creare >3 pages o toccare >15 file, fermati e chiedi.
- Se l'utente sta andando controcorrente rispetto al vault, segnalalo con tatto.

Tieni il vault onesto. Tienilo piccolo. Tienilo utile.

---

## Appendice A — Tag taxonomy estesa (opzionale)

Default: **tag liberi**. Nessun namespace obbligatorio.

Se vuoi disciplina maggiore per ricerche affidabili, due namespace opzionali:

**topic:** — di cosa tratta
- `topic:ai`, `topic:dev`, `topic:devtools`, `topic:cloud`, `topic:security`, `topic:health`, `topic:business`, `topic:productivity`, `topic:learning`, `topic:personal`

**kind:** — che tipo di pagina è (può anche essere un campo top-level del frontmatter, non solo un tag)
- `concept`, `tool`, `person`, `org`, `project`, `method`, `event`, `decision`, `reading`

Aggiungere namespace nuovi: edita questa appendice prima di usarli. LINT segnala namespace fuori taxonomy solo se l'utente ha attivato il check (off di default).

---

## Appendice B — Frontmatter avanzato (opzionale)

Campi opzionali per pages che vuoi marcare con quality signals:

```yaml
---
type: page
# ...
confidence: high | medium | low    # quanto sono supportati i claim
contested: true                    # ci sono contraddizioni irrisolte
contradictions: [other-page-slug]  # pages in conflitto con questa (reciproco)
---
```

Settali quando: topic veloci, opinion-heavy, claim mono-fonte. Non marcare `confidence: high` salvo claim supportati da ≥2 fonti indipendenti. LINT lista pages con `confidence: low` o `contested: true` per review periodica.

Versioning note (in source page da `notes/`):

```yaml
supersedes: [[wiki/sources/<slug>-<data-precedente>]]
superseded_by: null
```

`/compile` gestisce la catena automaticamente quando una nota cambia in modo sostanziale.

---

## Appendice C — Capture manuale per tipologia

Per contenuto non fetchabile da `inbox-fetcher` (post privati, thread X copiati, articoli paywall, email forwardate, snippet da chat, highlight ebook):

1. Crea `raw/web/<slug>/` con slug lowercase-hyphens.
2. Crea `raw/web/<slug>/index.md` col contenuto. Frontmatter base (vedi § Aggiungo → raw/web).
3. (Opzionale) Immagini in `raw/web/<slug>/assets/`.
4. Esegui `/compile` o `/compile --from raw/web/<slug>/index.md`.

**Convenzioni per tipologia**:

- **Thread X/Twitter**: paste con `> @handle:` come prefisso per ogni tweet, ordine cronologico. `source_url` = URL del root tweet.
- **Post LinkedIn / Facebook / Instagram / Threads**: paste integrale, `source_url` se accessibile.
- **Articolo paywall**: preferire `Riassunto + key quotes` rispetto a copia integrale (fair-use). `source_url` originale.
- **Email forwardata**: paste corpo, `source_url` omesso, `author` = mittente.
- **Highlight ebook (Kindle, Apple Books)**: paste come quote-blocks, `author` = autore libro, `source_url` omesso o link store.

**PDF scaricati a mano**: drop in `raw/papers/<slug>.pdf`. Niente frontmatter (è binario); `/compile` calcola comunque `content_hash` e crea la source page.

Dopo il primo `/compile`, il file in `raw/` è immutabile come il resto.
