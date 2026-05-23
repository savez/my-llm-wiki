# Notes — Guida rapida

Questa cartella è la tua zona di scrittura libera. Sottocartelle indicative — aggiungi/rinomina come ti pare, l'agente scansiona ricorsivamente.

**Regole generali**:
- Nessun frontmatter richiesto. Scrivi come ti viene.
- Marca i passaggi importanti con `==testo==` (highlights). `/compile` li estrae automaticamente nelle source page.
- File `.md` preferito. Nomi file liberi (`acme-call-2026-05-20.md` o `meeting con acme.md`, indifferente).
- `/compile` tiene traccia di cosa è già ingerito via hash. Modifichi una nota → al prossimo `/compile` te la propone come MODIFIED.

---

## Le sottocartelle

### `meetings/`
Note di call, riunioni 1-1, sync, retrospective. Una nota per evento.

Suggerimento titolo: `YYYY-MM-DD-<chi>.md` (es. `2026-05-20-acme-q3-planning.md`) — facilita ricerche cronologiche.

**Contenuto tipico**: data, partecipanti, decisioni prese, action items, citazioni rilevanti (con `==…==`).

### `conferences/`
Appunti da talk, podcast, video, conferenze, workshop.

Suggerimento titolo: `<evento>-<anno>-<talk>.md` (es. `webday-2026-llm-agents.md`).

**Contenuto tipico**: speaker, claim chiave, link/risorse citate, tue reazioni. `==…==` sui passaggi che ti hanno colpito.

### `books/`
Lettura. Libri, paper letti, articoli letti, post LinkedIn letti, thread X letti. Insomma: cose lette di cui vuoi tenere traccia.

Suggerimento titolo: `<autore>-<titolo>.md` (es. `kleppmann-designing-data-intensive.md`) o per articoli `<dominio>-<topic>.md`.

**Contenuto tipico**: riassunto in parole tue, citazioni chiave (`> quote`), tue connessioni con altri libri/idee. Per articoli pubblici, considera se vale di più metterli in `raw/web/` (così sono fonti vere e proprie) o solo annotazioni qui.

### `ideas/`
Idee di progetto, brainstorm, prototipi mentali, "what if". Tue.

Suggerimento titolo: descrittivo (es. `agente-monitor-supabase.md`, `app-tracking-mese-lavoro.md`).

**Contenuto tipico**: scrivi liberamente. Si maturano nel tempo. Una nota può diventare un progetto vero (allora la sposti in `notes/projects/` o equivalente, oppure prende vita propria in un repo).

### `scratch/`
Zibaldone. Pensiero libero, draft, "non so dove metterlo". Nessuna disciplina, nessun titolo obbligatorio. Il tuo blocco appunti.

Se una nota di scratch matura, valutala per spostarla in una cartella più specifica (ideas, books, ecc.).

### `varie/`
Quello che non incastra da nessun'altra parte. Ricette, todo personali, riferimenti utili, lista contatti utili, password manager hints (non password), ecc.

### `lists/`
Wishlist: cose da leggere, vedere, provare. Le tratto come una cartella speciale perché `/compile` le legge per spuntare voci automaticamente.

File suggeriti (crea solo quelli che ti servono):
- `books-to-read.md` — libri da leggere
- `articles-to-read.md` — articoli da leggere (con URL)
- `sites-to-visit.md` — siti/risorse da vedere
- `software-to-try.md` — tool/app da provare
- `papers-to-read.md` — paper accademici

**Formato**: checkbox markdown
```markdown
# Libri da leggere

- [ ] Designing Data-Intensive Apps — Kleppmann
- [ ] Thinking in Systems — Meadows
- [x] Working in Public — Eghbal (letto 2026-04)
```

**Auto-tick**: quando `/compile` ingerisce una fonte il cui URL o titolo compare in una lista, ti propone di spuntare la riga. Conferma sempre richiesta — niente automatico.

---

## Cartelle che potresti voler aggiungere (suggerimenti, non obbligatori)

- `notes/projects/` — note progetto attivo (uno o più sub-folder per progetto)
- `notes/work/sal/` — lavoro Santagostino, contesto SAL
- `notes/work/1-1/` — note 1-to-1 col team
- `notes/health/` — appunti salute personale (allenamenti, dieta, esami)
- `notes/learning/` — appunti di studio strutturato (corsi, tutorial seguiti)

Crea solo quelle che ti servono davvero. Meglio una cartella nata "perché serve" che una creata in anticipo.

---

## Come `/compile` tratta le note

1. **Scan**: ogni nota viene hashata (sha256 del contenuto).
2. **Classifica**:
   - **NEW**: nota mai ingestita → ti propone ingest.
   - **MODIFIED incrementale** (<30% diff): aggiorno la source page in place.
   - **MODIFIED sostanziale** (≥30% o cambio heading top-level): ti propone versioning.
   - **SYNC**: hash uguale → skip.
3. **Ingest** (interattivo): mostra takeaway, propone tag, crea/aggiorna source page in `wiki/sources/<slug>-<data>.md`, eventualmente alimenta pages concettuali.

La cartella `notes/` è plastica (può cambiare) — `/compile` la traccia via hash, niente di automatico.

---

## In dubbio

- Se non sai dove mettere una nota: **`scratch/`**. Non bloccarti per la classificazione.
- Se una nota cresce e diventa importante: spostala in una cartella più appropriata, oppure proponi una cartella nuova.
- Se ti accorgi che una "nota" è in realtà una **fonte esterna** (articolo, paper, post), valuta se metterla in `raw/` (è una sorgente immutabile) invece che in `notes/` (sono note tue).
