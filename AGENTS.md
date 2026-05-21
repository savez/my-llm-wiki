# LLM Wiki — Second Brain Vault

Questo file definisce lo schema di un vault personale di conoscenza mantenuto da un agente LLM, basato sul pattern _LLM Wiki_ di Karpathy (https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

Viene letto da qualsiasi agente che opera sul vault (Claude Code, OpenCode, Codex). Symlink `OPENCODE.md` e altri agent file a questo così tutti seguono le stesse convenzioni.

**Principio guida:** `raw/` e `notes/` sono ground truth. `wiki/` è compilato a partire da loro e può essere ricostruito. L'utente cura le fonti, fa domande, guida l'analisi. L'agente legge, sintetizza, mantiene la wiki, e tiene il pensiero in salute nel tempo.

---

## Architettura

Tre piani, separati per regime di mutabilità e ownership:

**Raw immutabile** — `raw/`. Popolato da meccanismi automatici (fetcher da `inbox.md`, futuri RSS). L'agente legge ma non scrive, salvo via skill di ingestione automatica. Una volta dentro, immutabile.

**Raw modificabile** — `notes/`. Le tue note grezze, scritte a mano. Sottocartelle libere, contenuto destrutturato, nessun frontmatter richiesto. Scrivi come ti viene. È il tuo lato del vault.

**Wiki sintetizzata** — `wiki/`. L'unico posto che l'agente costruisce attivamente, attingendo da `raw/` e `notes/`. Pages, sources, views, più i file riassuntivi `compass.md`, `hot.md`, `index.md`, `log.md`.

Per claim ad alto rischio (numeri, citazioni esatte, fatti legali/medici), risali sempre alla fonte. La wiki sintetizza ma non sostituisce.

**Il vault tratta `raw/` e `notes/` come due ingressi dello stesso pattern.** Stesso meccanismo di sintesi (source page + page concettuale), stesse regole di citazione, stesso strato wiki. L'unica differenza è la mutabilità: `raw/` è immutabile (l'agente sa cosa contiene una volta per tutte), `notes/` è plastica (l'agente tiene traccia dei cambiamenti via hash). Le operazioni INGEST e SYNC sono varianti dello stesso processo, ottimizzate per i due regimi. In futuro, nuove fonti di input (RSS, trascrizioni vocali, email, highlight di ebook) possono plug-in nello stesso pattern senza modifiche architetturali: si aggiunge una cartella in `raw/` o `notes/` e una skill di import, il resto del vault non se ne accorge.

---

## Struttura

```
inbox.md              coda di URL — tu aggiungi, fetcher elabora
raw/                  ground truth immutabile
  papers/             PDF
  web/<slug>/         articoli web convertiti in markdown
notes/                tue note grezze, sottocartelle libere
  meetings/           call, riunioni
  conferences/        appunti da talk, podcast, video
  books/              appunti di lettura
  ideas/              idee di progetto, brainstorm
  scratch/            zibaldone, pensiero libero
wiki/
  pages/              concetti, persone, organizzazioni, progetti
  sources/            una pagina per file in raw/ o note ingestita
  views/              timeline, comparison, mappe, slide, post, report
  compass.md          riflessione strategica (output di /reflect)
  hot.md              dove eravamo (5-10 righe, riscritte)
  index.md            catalogo della wiki (English)
  log.md              registro append-only delle operazioni (English)
conversations/        trascrizioni salvate con /save
.lint/report.md       output ultimo lint
.claude/              skill, slash command, hook (meccanismi)
```

Le sottocartelle di `notes/` sono indicative. Aggiungine, rinominale, riorganizzale come ti pare. L'agente scansiona ricorsivamente.

---

## Le sette invarianti

Mai violarle.

1. **Mai scrivere in `raw/`.** Solo le skill di fetching automatico possono aggiungere file lì. L'unica eccezione è FORGET, che cancella.
    
2. **`notes/` è tuo dominio.** L'agente le legge, le ingerisce, ma non le riscrive né impone struttura. Sono destrutturate per design.
    
3. **Ogni claim nella wiki cita una fonte.** Citazione a `raw/...`, `notes/...` o `[[wiki/sources/...]]`. Nessun claim orfano. Le inferenze si marcano `(sintesi — da verificare)`.
    
4. **Paraphrase, non copiare.** Riassunti nelle proprie parole. Mai trascrivere blocchi verbatim da fonti, salvo citazione breve esplicita.
    
5. **L'utente cura, l'agente mantiene.** Niente ingestione automatica di nuove fonti, niente cambiamenti strutturali senza conferma, niente view create spontaneamente.
    
6. **≤15 file toccati per operazione.** Se ne servono di più, fermati e chiedi all'utente cosa contia.
    
7. **Aggiorna `index.md` e `log.md` dopo ogni scrittura in `wiki/`.**
    

---

## Lingua

Il vault è bilingue per design.

- **`raw/`** mantiene la lingua originale. Mai tradurre.
- **`notes/`** segue la tua testa al momento. Nessun vincolo.
- **`wiki/pages/`, `wiki/sources/`, `wiki/views/`** in **italiano**, indipendentemente dalla lingua delle fonti. Una pagina per concetto/source/view — niente traduzioni parallele. Citazioni verbatim possono restare in lingua originale dentro la prosa italiana, quando le parole esatte contano.
- **`compass.md`, `hot.md`** in **italiano**.
- **`index.md`, `log.md`** in **inglese**. Sono metadati operativi, non contenuto. L'inglese li tiene parseable e consistenti.
- **Risposte in chat** seguono te.

---

## Frontmatter

Ogni file in `wiki/` ha frontmatter YAML.

**Pages** (`wiki/pages/`):

```yaml
---
type: page
created: 2026-05-20
updated: 2026-05-20
tags: [...]
---
```

**Sources** (`wiki/sources/`):

```yaml
---
type: source
source_path: raw/papers/attention-is-all-you-need.pdf  # oppure notes/...
created: 2026-05-20
updated: 2026-05-20
tags: [...]
# Solo per source da notes/ versionate:
supersedes: [[wiki/sources/<slug>-<data-precedente>]]
superseded_by: null
last_synced_hash: <hash del contenuto della nota all'ultimo sync>
---
```

**Views** (`wiki/views/`):

```yaml
---
type: view
kind: timeline | comparison | concept-map | chart | slides | report | post
shareable: false                # true solo se prodotta per condividere fuori
created: 2026-05-20
updated: 2026-05-20
based_on:
  - [[wiki/pages/...]]
  - [[wiki/sources/...]]
tags: [...]
---
```

Quando `shareable: true`, la view è **congelata**: l'agente non la modifica più, neanche se le pagine sottostanti cambiano. Quando `shareable: false` (default), la view è viva e può essere rigenerata.

Le note in `notes/` **non** hanno frontmatter richiesto. SYNC mantiene il tracking della freschezza calcolando l'hash del contenuto e salvandolo nel frontmatter della source page corrispondente (`last_synced_hash`).

---

## Le sette operazioni

### FETCH

Trigger: "process inbox", "fetcha inbox".

Esegue la skill `inbox-fetcher`: legge URL da `inbox.md`, scarica le pagine, converte in markdown, salva in `raw/web/<slug>/`. Marca URL come fatti in `inbox.md`. Non ingerisce — solo porta dentro.

### INGEST

Trigger: "ingest X", riferito a un file specifico in `raw/`.

Una fonte alla volta, salvo richiesta esplicita di batch.

1. Leggi la fonte nella sua lingua originale.
2. Discuti i takeaway con l'utente (in italiano) prima di scrivere.
3. Crea `wiki/sources/<slug>.md` in italiano. Per default ogni fonte ne ha una; puoi proporre di saltare la source page per fonti marginali (note brevi, post casuali, frammenti) — ma richiede conferma esplicita, e la fonte deve essere citata da almeno una page.
4. Crea o aggiorna le `wiki/pages/...` rilevanti, in italiano.
5. Aggiungi `[[wiki-link]]` per connettere il nuovo materiale a ciò che già esiste.
6. Prima di chiudere, verifica che ogni nuova page abbia almeno un inbound link. Se non ne ha, aggiungilo o segnalala come orphan intenzionale in `log.md`.
7. Quando una nuova fonte rinforza, indebolisce o contraddice claim esistenti, **non** sovrascrivere silenziosamente: marca la contraddizione esplicitamente, con entrambe le citazioni.
8. Aggiorna `index.md` e `log.md`.
9. Ogni claim nella wiki deve essere citato (invariante #3).

Se l'ingest richiederebbe di creare >3 page nuove, fermati e chiedi.

### SYNC

Trigger: "sync notes", "rielabora le note", `/sync`, `/sync --dry-run`.

Operazione gemella di INGEST per `notes/`. Mentre INGEST è mirato su una singola fonte in `raw/`, SYNC è batch su `notes/` con tracking della freschezza.

1. **Scan ricorsivo** di `notes/`, raccogliendo tutti i file `.md`.
2. Per ogni nota, **calcola l'hash** del contenuto.
3. **Confronta** con `last_synced_hash` nella source page corrispondente (`wiki/sources/<slug>.md`):
    - Source page assente → nota mai ingestita → da ingestire.
    - Hash diverso → nota modificata dopo l'ultimo sync → da reingestire.
    - Hash uguale → in pari, ignora.
4. **Riporta sommario all'utente** prima di agire: "Trovate N nuove, M modificate, K in pari. Procedo?"
5. **Modalità `--dry-run`**: mostra solo il sommario dello step 4 con l'elenco dei file impattati (nuove, modificate con classificazione incrementale/sostanziale prevista, pages potenzialmente impattate). Termina senza scrivere nulla. Utile per vedere "quanto è disallineato il wiki dalle mie note" senza impegno.
6. Su conferma (in modalità normale), per ogni nota da ingestire:
    - **Nuova**: crea `wiki/sources/<slug>-<YYYY-MM-DD>.md`, propone aggiornamenti alle pages rilevanti. Aggiorna `last_synced_hash`.
    - **Modificata**: confronta diff col contenuto precedente.
        - **Incrementale** (cambiamento minore): aggiorna la source page corrente, aggiorna `last_synced_hash`.
        - **Sostanziale** (>30% del contenuto, o cambio strutturale): propone versioning. Su conferma, crea nuova source page `<slug>-<YYYY-MM-DD>.md`, marca la vecchia come `superseded_by`, mette la nuova come `supersedes` della vecchia. Identifica le pages che citano la vecchia source e ti segnala "queste pages citano la versione precedente, vuoi rivederle?" — **non riscrivere automaticamente prosa di pages**.
7. Aggiorna `index.md` (con eventuali entry di versionamento) e `log.md`.

Naming delle source da notes: sempre con data (`progetto-x-2026-05-20.md`), fin dalla prima versione. Naming delle source da `raw/papers/` e `raw/web/`: senza data (`attention-is-all-you-need.md`), perché lì la fonte è davvero immutabile.

### FORGET

Trigger: "forget X", "rimuovi la fonte X", `/forget <source>`.

Cascade-removal di una fonte e tutto ciò che dipendeva solo da lei.

1. Risolvi target: trova `wiki/sources/<slug>.md` e il file in `raw/` o `notes/` puntato da `source_path`.
2. Grep del vault per ogni riferimento: `[[wiki/sources/<slug>]]`, citazioni del path. Elenca all'utente.
3. Per ogni `wiki/pages/...` che cita la fonte, decide per claim:
    - Claim supportato da altre fonti → rimuovi solo questa citazione.
    - Claim dipendeva solo da questa fonte → proponi di rimuoverlo (o degradarlo a "non verificato"). **Chiedi prima di cancellare prosa.**
4. Per ogni `wiki/views/...` con la fonte in `based_on`:
    - `shareable: false` → rigenera o sfoltisci la view.
    - `shareable: true` → **non toccare**, avverti l'utente che la view ora ha citazioni dangling.
5. Per source versionate: gestire la catena `supersedes` / `superseded_by`. Se cancelli una versione intermedia, riaggancia i link nelle versioni adiacenti.
6. Cancella `wiki/sources/<slug>.md` e il file in `raw/` (o `notes/`). Questa è l'unica eccezione all'invariante #1 — l'invariante copre la creazione, non la rimozione user-directed.
7. Aggiorna `index.md` e `log.md`.
8. Esegui LINT per confermare zero dead link.

Se la fonte è citata da >15 file, la cascade supera l'invariante #6: fermati, riporta il fanout, lascia che l'utente scelga (cascade su più passi, o lasciare citazioni dangling per il linter).

### QUERY

Trigger: l'utente fa una domanda.

1. **Leggi `wiki/hot.md`** per prima cosa — contesto cheap su dove eravamo rimasti.
2. Leggi `wiki/index.md` per identificare le pages rilevanti.
3. **Se esiste una view pertinente in `wiki/views/`, leggila prima** — è una sintesi pre-compilata, spesso più veloce che ricostruire dalle pages.
4. Leggi le pages e sources rilevanti.
5. Rispondi usando solo claim tracciabili nel vault. Cita tutto: pages nella risposta in chat, raw nelle pages.
6. Se il vault non basta, dillo. Non riempire i buchi con training data. Suggerisci quale fonte o search web potrebbe colmare il gap.
7. Se la risposta è valore durevole, **proponi di salvarla** come nuova page o folded in una esistente (vedi save-back).

### VIEW

Trigger: "fammi una timeline di X", "confronta Y e Z", "butta giù slide su W", `/view`.

Crea un artefatto strutturato in `wiki/views/`. Sette `kind` supportati: `timeline`, `comparison`, `concept-map`, `chart`, `slides`, `report`, `post`.

**Mermaid è il formato preferito per `concept-map`, `timeline` e diagrammi di flusso.** È testo, vive nel markdown, renderizza ovunque, è rigenerabile. Per grafici dati-dense o grafi molto grandi (>30 nodi), valutare alternative (tabella + SVG, o tool esterno).

**Pattern editoriale consigliato.** Per output destinati a condivisione esterna (`post`, `report`, `slides`), il flusso a due stadi rende meglio:

1. Prima costruisci una view di **sintesi interna** (`comparison`, `concept-map`, `timeline`...) con `shareable: false`. Questa è "ho capito il tema".
2. Poi, da quella, derivi una view di **condivisione** (`post`, `report`). Questa è "ecco come lo racconto fuori".

Per i `kind` orientati alla condivisione (`post`, `report`, `slides`), l'agente chiede esplicitamente se la view nasce già `shareable: true`.

**Citazioni nelle views.** Stesse regole delle pages: ogni claim cita una fonte o una page. Le views non sono prosa libera, sono sintesi derivata. Le citazioni stanno nelle note di accompagnamento, non dentro i diagrammi.

**Struttura tipica di una view:** frontmatter, riassunto in 1-2 righe, artefatto principale (diagramma/tabella/testo), note di lettura con citazioni, sezione "Pagine collegate".

### REFLECT

Trigger: "rifletti sul vault", `/reflect`.

Riscrivi `wiki/compass.md` da zero (non append). Tre sezioni in prosa, in italiano:

1. **Dove sta andando il mio pensiero** (3-5 righe)
2. **Cosa non sto guardando** (3-5 bullet con link a pages)
3. **Una domanda su cui vale la pena fermarsi** (una sola, incorporata nella prosa)

Includi nella sezione 2 eventuali problemi strutturali (page duplicate, orphan, view stantie). Se ci sono conversazioni in `conversations/` con insight non ancora filati nel wiki, o note in `notes/ideas/` o `notes/scratch/` con materiale maturo, o views che potrebbero espandere pages, segnalali qui.

### LINT

Trigger: "lint", o auto-trigger dopo 5 ingest / 7 giorni.

Esegui la skill `vault-linter`. Solo check deterministici:

- dead link (`[[...]]` che non risolve)
- frontmatter mancante o malformato in `wiki/`
- naming inconsistente
- views stantie (`based_on` punta a pages aggiornate dopo la view)
- pages orphan (zero inbound link)
- concetti citati in pages ma senza page propria
- claim potenzialmente outdated alla luce di fonti più recenti
- cross-reference mancanti

Output in `.lint/report.md`. **Mai auto-fix.** Riporta come lista numerata con fix suggeriti. Append `## [data] lint | wiki-health` a `log.md`.

---

## Hot cache

A fine sessione, se abbiamo toccato contenuto significativo, aggiorna `wiki/hot.md` con 5-10 righe: cosa abbiamo coperto, cosa è rimasto aperto, da dove riprendere. **Riscrivi, non aggiungere.** A inizio sessione, l'agente legge `wiki/hot.md` per primo.

---

## Save-back workflow

Quando una risposta in chat vale la pena di essere salvata:

1. L'agente propone target — nuova page o page esistente in cui integrarla.
2. Su conferma, scrivi/aggiorna la page seguendo il page format.
3. Cita le pages e le raw/notes da cui la risposta ha attinto.
4. Aggiorna `index.md` se è nata una nuova page.
5. Append entry `query` a `log.md`.

Questo è ciò che fa compoundare l'esplorazione insieme all'ingest.

---

## Page format

Le pages in `wiki/pages/` seguono questo schema (in italiano):

```markdown
---
type: page
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags: [...]
---

# Titolo della pagina

**Riassunto**: una o due frasi che descrivono questa pagina.

**Fonti**: elenco dei file in `raw/` o `notes/` da cui questa pagina
trae informazioni, o link a `[[wiki/sources/...]]`.

**Ultimo aggiornamento**: YYYY-MM-DD.

---

Contenuto principale. Titoli chiari, paragrafi brevi.

Collegare i concetti con [[wiki-link]] all'interno del testo.

## Pagine collegate

- [[concetto-collegato-1]]
- [[concetto-collegato-2]]
```

Source page (`wiki/sources/`) e view (`wiki/views/`) seguono lo stesso schema, con frontmatter specifico per il loro `type`. Synthesis, comparison, decision pages possono divergere dove la struttura non si adatta — ma mantengono `Riassunto`, `Fonti`, `Ultimo aggiornamento`, `Pagine collegate`.

---

## Citazioni

- Ogni claim fattuale in una page cita la sua fonte.
- Formato per fonti raw: `(fonte: raw/papers/nome.pdf)` o `(fonte: raw/web/<slug>/index.md)`.
- Formato per note: `(fonte: notes/meetings/2026-05-20-acme.md)`.
- Formato per source page: `[[wiki/sources/<slug>]]`.
- Per inferenze senza fonte diretta: `(sintesi — da verificare)`.
- Se due fonti disagree, marca la contraddizione con entrambe le citazioni.
- In chat (in italiano), cita pages. Nelle pages, cita raw o notes.

---

## Indexing e logging

**`wiki/index.md`** — content-oriented. Lista le pages per categoria con descrizione one-line, in inglese. Aggiornato a ogni ingest e save-back. Esempio:

```markdown
# Wiki Index

## Concepts
- [[transformer]] — Self-attention architecture
- [[mixture-of-experts]] — Sparse expert routing in large models

## Models
- [[claude-opus-4-7]] — Anthropic's flagship as of 2026

## Sources (notes)
- [[progetto-x-2026-05-20]] — Project X idea, v2 (supersedes 2026-03-15)
- [[progetto-x-2026-03-15]] — Project X idea, v1
```

**`wiki/log.md`** — chronological, append-only, in inglese. Cattura ingest, save-back da query, sync, forget, lint. Formato heading consistente:

```markdown
## [2026-05-20] ingest | attention-is-all-you-need
## [2026-05-20] sync   | progetto-x v2 (supersedes v1)
## [2026-05-20] query  | rag-vs-long-context-tradeoffs
## [2026-05-20] view   | agent-architectures-map
## [2026-05-20] forget | obsolete-paper-xyz
## [2026-05-20] lint   | wiki-health-check
```

Una riga di dettaglio sotto ogni heading. Parseable con `grep "^## \[" wiki/log.md | tail -10`.

---

## Modalità unattended

Quando l'agente è invocato con `--unattended`, `VAULT_UNATTENDED=1`, o la parola "unattended" nel prompt:

**Permesso:** leggere qualunque cosa, eseguire LINT, eseguire REFLECT, aggiornare `wiki/compass.md`, `hot.md`, `log.md`, `.lint/report.md`.

**Non permesso:** ingest, sync, forget, creare views, modificare `wiki/pages/`, cancellare nulla da `raw/` `notes/` o `wiki/sources/`, applicare qualsiasi cambiamento strutturale. Le proposte restano proposte finché l'utente non conferma interattivamente.

---

## Slash command

- `/save [nome]` — salva la conversazione corrente in `conversations/`
- `/sync` — esegui SYNC su `notes/`
- `/sync --dry-run` — mostra cosa farebbe SYNC senza scrivere nulla
- `/view [kind] [topic]` — costruisci una view (vedi VIEW)
- `/reflect` — produci `compass.md` (vedi REFLECT)
- `/forget <source>` — cascade-removal (vedi FORGET)

Per il resto, linguaggio naturale. Niente comando per "trovami altri URL su X" — basta chiedere.

---

## Regole operative

- **Mai modificare nulla in `raw/`.**
- **Mai imporre struttura a `notes/`.** Le note sono tue, destrutturate.
- **Sempre aggiornare `wiki/index.md` e `wiki/log.md`** dopo scritture in `wiki/`.
- **Sempre leggere `wiki/hot.md` e `wiki/index.md` prima** di una query o un'operazione di mantenimento.
- Nomi delle page lowercase con trattini: `mixture-of-experts.md`.
- Preferire aggiornare una page esistente piuttosto che crearne una quasi-duplicata.
- Lingua chiara, plain. Non inventare fatti per far sentire la wiki completa.
- Quando incerto su come categorizzare qualcosa, chiedi.
- Mantenere questo schema pratico. Aggiornarlo quando il workflow matura.

---

## Quando in dubbio

- Se una regola crea frizione, **proponi una modifica all'utente**. Non emendare silenziosamente questo file.
- Se non riesci a tracciare un claim a una fonte, non farlo.
- Se stai per creare >3 pages o toccare >15 file, fermati e chiedi.
- Se l'utente sta andando controcorrente rispetto al vault, segnalalo con tatto.

Tieni il vault onesto. Tienilo piccolo. Tienilo utile.
