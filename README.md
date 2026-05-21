# my-llm-wiki

Un _second brain_ personale curato da un agente LLM. Le fonti grezze le aggiungi tu — la wiki sintetizzata la mantiene l'agente.

## Da dove nasce

Implementazione dell'idea **LLM Wiki** di Andrej Karpathy ([gist originale](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)): un vault in cui l'utente fa l'ingegnere dell'informazione (cura le fonti, fa le domande, guida l'analisi) e l'LLM fa il bibliotecario (legge, sintetizza, mantiene pages e indici, tiene il pensiero in salute nel tempo).

Lo schema operativo segue da vicino l'implementazione di **Stefano Maestri** — <https://github.com/maeste/agent-mem-kb> — da cui ho preso spunto per architettura a tre piani, sette invarianti, sette operazioni, frontmatter, citazioni e workflow editoriale. Grazie mille per il lavoro fatto e condiviso!

## L'idea in tre righe

- `raw/` e `notes/` sono **ground truth**: la prima immutabile (l'agente legge ma non scrive), la seconda è territorio tuo (note destrutturate, scritte a mano).
- `wiki/` è **compilato** da raw + notes: pages concettuali, sources, views, più i file di servizio (`compass.md`, `hot.md`, `index.md`, `log.md`). Può essere ricostruito.
- Ogni claim nella wiki **cita la fonte**. Niente claim orfani, niente allucinazioni mascherate.

## Struttura

```
inbox.md              coda URL da processare
raw/                  ground truth immutabile (papers, web)
notes/                tue note grezze (meetings, books, ideas, scratch, ...)
wiki/
  pages/              concetti, persone, organizzazioni, progetti
  sources/            una pagina per file in raw/ o nota ingestita
  views/              timeline, comparison, mappe, slide, post, report
  compass.md          riflessione strategica (output di /reflect)
  hot.md              dove eravamo (5-10 righe)
  index.md            catalogo della wiki (English)
  log.md              registro append-only delle operazioni (English)
conversations/        trascrizioni salvate con /save
.lint/report.md       output ultimo lint
```

Dettagli completi su invarianti, operazioni (`FETCH`, `INGEST`, `SYNC`, `FORGET`, `QUERY`, `VIEW`, `REFLECT`, `LINT`), frontmatter, lingua, citazioni e modalità unattended in [`AGENTS.md`](AGENTS.md).

## Come si usa

1. Apri il repo con il tuo agente preferito (Claude Code, OpenCode, Codex). Tutti leggono `AGENTS.md`.
2. **Aggiungi materia prima.** Butta URL in `inbox.md`, scrivi a mano in `notes/`, lascia paper in `raw/papers/`.
3. **Chiedi all'agente di ingerire.** "ingest X" su una fonte specifica, oppure `/sync` per rielaborare le note.
4. **Interroga.** Fai domande in linguaggio naturale: l'agente legge `hot.md`, `index.md`, pages e sources rilevanti e risponde citando.
5. **Sintetizza.** `/view` per timeline, comparison, concept-map, slide, post, report.
6. **Mantieni in salute.** `/reflect` riscrive `compass.md`. Il linter trova dead link, orphan e view stantie.

## Slash command

- `/save [nome]` — salva la chat corrente in `conversations/`
- `/sync` — riprocessa `notes/` (`--dry-run` per anteprima)
- `/view [kind] [topic]` — costruisci una view
- `/reflect` — riscrivi `compass.md`
- `/forget <source>` — cascade-removal di una fonte

## Crediti

- **Andrej Karpathy** — idea originale dell'LLM Wiki.
- **Stefano Maestri** — implementazione di riferimento (<https://github.com/maeste/agent-mem-kb>) da cui questo repo prende spunto. Grazie!

