---
name: inbox-fetcher
description: Elabora una coda di URL e feed RSS/Atom elencati in inbox.md per un vault second-brain, scaricando ogni pagina come markdown pulito in raw/web/<slug>/index.md, con immagini in assets/. Usa questa skill quando l'utente menziona "inbox", "elabora", "fetcha", "scarica articoli", "feed RSS", o aggiunge URL/feed a inbox.md. Eseguila PRIMA di qualunque operazione di ingest, così l'agente lavora su file raw puliti. Gestisce articoli HTML via trafilatura, download diretti di PDF, polling RSS/Atom con risoluzione redirect e dedup canonical, e fallimenti per singolo URL (paywall, pagine JS, timeout) senza bloccare il resto della coda. I domini walled (X/Twitter, LinkedIn, Threads, Facebook, Instagram) sono segnati per fallback Playwright MCP guidato dall'agente. Gli URL arxiv abstract/html sono riscritti sull'endpoint PDF così a essere archiviato è il paper, non la landing page.
---

# Inbox Fetcher

Elabora una coda mista di URL singoli e feed RSS/Atom da `inbox.md` in file markdown puliti sotto `raw/web/` e `raw/papers/`, pronti per l'ingest nel wiki.

## Quando usare questa skill

Da attivare quando l'utente:

- Dice "elabora l'inbox", "fetcha l'inbox", "scarica questi URL", "polla i feed"
- Aggiunge URL a `inbox.md` (sotto `## Da processare`) o feed (sotto `## Feeds`) e chiede di prepararli
- Chiede di ingerire contenuto web e il vault ha un `inbox.md`
- Vuole rinfrescare o ri-fetchare un URL già nell'inbox

Questa skill è uno **step pre-ingest**. Dopo che è girata, l'utente (o l'agente che segue l'`AGENTS.md` del vault) esegue l'ingest vero e proprio — legge i nuovi file in `raw/` e li compila nel wiki.

## Assunzioni sul vault

La skill si aspetta questo layout:

```
<vault>/
├── inbox.md              coda di URL + feed (formato checkbox + feed:)
├── raw/
│   ├── web/              output articoli HTML
│   └── papers/           download diretti di PDF
└── .config-llm/
    ├── skills/
    │   └── inbox-fetcher/
    │       ├── SKILL.md
    │       └── scripts/
    │           └── fetch_inbox.py
    └── state/
        └── feeds.json    stato persistente dei feed (dedup GUID)
```

La skill crea `raw/web/`, `raw/papers/` e `.config-llm/state/` se non esistono.

## Formato inbox

`inbox.md` ha tre sezioni:

```markdown
# Inbox

## Feeds

- feed: https://www.anthropic.com/news/rss.xml
- feed: https://simonwillison.net/atom/everything/

## Da processare

- [ ] https://www.anthropic.com/engineering/agent-skills
- [ ] https://example.com/paper-x.pdf
  - tags: agent-skills, spec
  - note: focus sulla composizione

## Elaborati

- [x] https://old-url.com → `raw/web/old-url-slug/` (2026-04-15)
```

Regole:

- **`## Feeds`**: una riga per sottoscrizione, formato `- feed: <url>`. Niente checkbox (i feed sono permanenti). Per disiscriverti, cancella la riga.
- **`## Da processare`**: solo le righe `- [ ] <URL>` (non spuntate) vengono elaborate. Sotto-bullet indentati (tags, note) sono preservati ma non parsati — sono hint per lo step di ingest.
- **`## Elaborati`**: popolato in automatico. Dopo un fetch riuscito, la riga si sposta qui e viene marcata `- [x]` con path di output e data.
- I fetch falliti ricevono un suffisso inline `⚠ <ragione>` e restano non spuntati così l'utente decide.
- Gli URL appesi dal polling RSS finiscono in `## Da processare` (canonical URL post-redirect, vedi sotto).

## Come eseguirla

Dalla root del vault:

```bash
python .config-llm/skills/inbox-fetcher/scripts/fetch_inbox.py
```

Oppure da qualunque path:

```bash
python .config-llm/skills/inbox-fetcher/scripts/fetch_inbox.py --vault /path/to/vault
```

**Con venv condiviso del repo `my-llm-wiki`** (raccomandato — evita di installare le deps nel Python di sistema):

```bash
/path/to/my-llm-wiki/.venv/bin/python .config-llm/skills/inbox-fetcher/scripts/fetch_inbox.py
```

Setup una tantum:
```bash
cd /path/to/my-llm-wiki
python3 -m venv .venv
.venv/bin/pip install trafilatura requests python-slugify feedparser
```

Flag disponibili:

- `--dry-run` — mostra cosa verrebbe elaborato senza fetchare davvero
- `--feeds-only` — solo polling feed, non elabora URL singoli
- `--skip-feeds` — solo URL singoli, salta il polling (utile in offline)
- `--rss-triage` — polla i feed e stampa JSON con titolo+summary degli item nuovi, **senza aggiornare stato né `inbox.md`**. Usato dall'orchestrator `/compile` per fare triage interattivo.
- `--from-triage <file.json>` — legge un file di triage (formato sotto), marca tutti i GUID come `seen` (selected o no), appende solo gli URL `selected: true` a `## Da processare`, poi procede al fetch URL.

Lo script è idempotente: gli URL già elaborati (marcati `[x]`) sono saltati. Per ri-fetchare un URL, togli la spunta manualmente in `inbox.md`. I feed deduplicano via GUID/canonical URL — nessuna azione manuale richiesta.

### Formato JSON per triage

Output di `--rss-triage`:

```json
{
  "rss_triage": [
    {
      "feed": "https://example.com/feed.xml",
      "guid": "tag:example.com,2026:post-123",
      "url": "https://example.com/post-canonical",
      "title": "Titolo articolo",
      "summary": "Riassunto dal feed (max 280 char)"
    }
  ]
}
```

Input atteso da `--from-triage`: lo stesso schema, con un campo aggiuntivo `selected: true|false` per item. L'orchestrator (o lo script LLM) chiede all'utente, riempie `selected`, e ripassa il file.

## Cosa fa lo script

### Fase 1 — Polling feed (se ci sono feed sottoscritti)

1. **Parse** della sezione `## Feeds` con regex `^-\s*feed:\s*(\S+)`.
2. **Polling** di ogni feed con `feedparser`, usando header `If-None-Match` / `If-Modified-Since` (etag/last-modified) salvati in `.config-llm/state/feeds.json` per evitare downloading inutili.
3. Per ogni nuovo item (GUID non in `seen_guids`):
   - **Risoluzione canonical URL**: il link del feed è spesso un tracking URL (feedproxy, feedburner, t.co, ?utm_*). La skill segue i redirect con `HEAD` (fallback `GET`, max 5 hop) per ottenere l'URL finale. Su errore, usa il link originale.
   - **Dedup canonical**: skip se l'URL canonico è già in `## Elaborati` o già in `## Da processare` (gestisce il caso di due feed che linkano lo stesso articolo).
   - **Append**: aggiunge `- [ ] <canonical_url>` sotto `## Da processare`.
4. **Salva stato**: aggiorna `seen_guids` (cap 500 per feed, FIFO), `last_polled`, `etag`, `last_modified`.
5. Cap di sicurezza al primo polling: `MAX_NEW_PER_POLL=20` item, per non flood-are l'inbox con anni di archivio.

### Fase 2 — Elaborazione URL singoli

Per ogni `- [ ] <url>` non spuntato in `## Da processare`:

1. **Riscrittura URL (pre-fetch).** Alcuni URL sono riscritti per raggiungere il contenuto reale invece di una landing page. Oggi: arxiv — qualunque `arxiv.org/abs/<id>`, `arxiv.org/html/<id>` o `arxiv.org/pdf/<id>` (con o senza `.pdf`, con o senza suffisso versione `vN`) viene riscritto a `arxiv.org/pdf/<id>.pdf` così archiviamo il paper. Lo slug diventa `arxiv-<id>` verbatim (niente slugify — preserva l'ID canonico). La riga inbox continua a tracciare l'URL che hai scritto.
2. **Rilevamento PDF.** Se l'URL (riscritto) finisce in `.pdf` o il server risponde con `Content-Type: application/pdf`, scarica così com'è in `raw/papers/<slug>.pdf`.
3. **Estrazione HTML.** Altrimenti, usa `trafilatura` per fetchare ed estrarre markdown pulito con metadata (titolo, autore, data pubblicazione, lingua).
4. **Generazione slug.** Per URL riscritti, usa lo slug override (es. `arxiv-2405.12345`). Altrimenti preferisce il titolo dell'articolo, fallback a `<hostname>-<hash8>`.
5. **Download immagini.** Parsa pattern `![alt](url)`, scarica ogni immagine in `raw/web/<slug>/assets/` con nome file basato su hash, riscrive i path a locali.
6. **Frontmatter.** Antepone YAML con `source_url`, `title`, `author`, `fetched`, `fetched_via: trafilatura`, `language`. Il campo `fetched_via` discrimina origine vs gli altri due valori: `playwright` (fallback walled domain) e `manual` (utente ha incollato il contenuto, vedi `AGENTS.md > ## Capture manuale`).
7. **Aggiornamento inbox.** Se riuscito, sposta in `## Elaborati`. Se fallito, appende `⚠` con la ragione.

### Flusso feed → riassunto

Il flusso completo è: feed → poll → canonical URL → append a `## Da processare` → estrazione trafilatura → `raw/web/<slug>/index.md` con l'articolo intero. L'agente poi farà INGEST per produrre una `wiki/sources/<slug>.md` col **riassunto vero dell'articolo** — non il summary spesso troncato del feed. Il feed garantisce la scoperta; il pipeline esistente garantisce la qualità del riassunto.

## Dipendenze

Python 3.10+ e:

```bash
pip install trafilatura requests python-slugify feedparser
```

Se una dipendenza manca, lo script stampa il comando di install ed esce con codice 1.

## Edge case

- **Dominio walled (preflight).** Host in `WALLED_DOMAINS` (X/Twitter, LinkedIn, Threads, Facebook, Instagram) sono saltati a monte — trafilatura fallirebbe comunque. Marcato `⚠ walled domain (<host>) — try playwright`. L'agente fa il follow-up con il fallback Playwright MCP (vedi sotto).
- **Paywall / 403 / login wall (host non walled).** L'estrazione torna vuota. Marcato `⚠ extraction empty (likely paywall or JS-rendered) — try playwright`. Stesso fallback Playwright.
- **SPA renderizzata in JS.** Idem — hint `try playwright`.
- **PDF molto grandi (>50 MB).** Scaricati comunque, stampa un warning.
- **URL duplicato.** Se già in `## Elaborati`, saltato con un messaggio. Togli la spunta manualmente per forzare il ri-fetch.
- **Timeout di rete.** Timeout per request: 20s per HTML, 60s per PDF. I fallimenti non bloccano la coda.
- **Feed 404 / unreachable.** Annotato accanto al feed in `inbox.md` come commento HTML `<!-- ⚠ unreachable 2026-05-21 -->`, **non rimuove la sottoscrizione** (potrebbe essere un blip temporaneo).
- **Redirect chain >5 hop.** Fermati, usa l'ultimo URL raggiunto, logga warning.
- **Canonical URL identico per due feed diversi** (stesso articolo segnalato da due fonti). Appendi una volta sola; logga `<!-- da: feed-A, feed-B -->` come commento per traccia.
- **Item del feed che linka a un altro feed** (raro). Trattalo come URL normale, lascia che il pipeline lo fetcha; nessuna recursive subscription.

## Fallback Playwright

Ogni URL marcato `⚠ ... — try playwright` in inbox.md è un hand-off dallo script all'agente. Lo script non chiama mai un browser; l'agente usa Playwright MCP (`mcp__plugin_playwright_playwright__browser_*` su Claude Code, o tool equivalente su altri agenti) interattivamente, un URL alla volta.

**Protocollo per URL:**

1. **Conferma con l'utente** prima di fetchare. Mai elaborare in batch URL walled non presidiati.
2. Naviga con `browser_navigate` all'URL.
3. Se serve auth e l'utente è loggato (profilo persistente), procedi. Altrimenti fermati e riporta — non tentare di bypassare l'auth.
4. Usa `browser_snapshot` per l'accessibility tree, o `browser_evaluate` per estrarre il testo dell'articolo/tweet dal DOM. Per i thread X/Twitter, raccogli il thread intero, non solo il post root.
5. Genera uno slug (titolo per articoli; `<handle>-<tweet-id>` per X/Twitter).
6. Scrivi `raw/web/<slug>/index.md` con frontmatter:
   ```yaml
   ---
   source_url: <url>
   title: <inferito o prima riga del post>
   author: <handle o autore>
   published: <YYYY-MM-DD se visibile>
   fetched: <oggi>
   fetched_via: playwright
   ---
   ```
7. Salva screenshot in `raw/web/<slug>/assets/` solo se l'utente lo chiede — sono grossi e raramente servono.
8. In `inbox.md`, sposta la riga in `## Elaborati` con `- [x] <url> → \`raw/web/<slug>/\` (<oggi>)`. Rimuovi il marker `⚠`.
9. Riporta all'utente cosa è stato catturato e chiedi se procedere all'INGEST.

**Fuori scope per il fallback:** bypassare login wall, risolvere CAPTCHA, scraping a volume. Se emerge una di queste, fermati e dillo all'utente.

## Output contract

Dopo un run completo, lo script stampa:

```
Feeds: 2 sottoscritti, 4 nuovi item appesi (1 dedup con elaborati)

Processed 7 URLs:
  ✓ 5 HTML articles → raw/web/
  ✓ 1 PDF → raw/papers/
  ⚠ 1 failed (extraction empty): https://paywall-site.com/article
```

L'agente riporta questo sommario verbatim e chiede all'utente se procedere con l'ingest sui nuovi file.

## Non in scope

- Ri-estrazione quando il sorgente HTML cambia (nessun versionamento; l'utente ri-fetcha manualmente).
- Scraping autenticato dentro lo script Python (cookie, API key) — l'utente scarica manualmente, o usa il fallback Playwright MCP interattivamente.
- OCR immagini o estrazione figure da PDF.
- Scheduling / cron — l'utente o lo scheduler dell'agente decidono quando girare.
- Batch non presidiato via Playwright — il fallback richiede sessione interattiva con l'agente (una conferma per URL).
- OPML import / export per i feed — l'utente edita la sezione `## Feeds` a mano.
- Recursive subscription (item del feed che è esso stesso un feed).
