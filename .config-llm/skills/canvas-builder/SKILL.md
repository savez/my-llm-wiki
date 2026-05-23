---
name: canvas-builder
description: Costruisce canvas dal contenuto del vault. Un canvas è una rappresentazione alternativa: timeline, comparison, concept-map, chart, slides, report, o post. Usa questa skill quando l'utente dice "fammi una timeline", "confronta X e Y", "butta giù delle slide", "grafica le source", "/canvas", o chiede qualunque output elaborato basato sul wiki. Scrive in wiki/canvas/ con frontmatter che include provenance (based_on). I canvas con shareable:false evolvono in place; quelli con shareable:true sono snapshot congelati.
---

# Canvas Builder

Un canvas è una rappresentazione alternativa del contenuto del vault. Può essere per la comprensione dell'utente (default) o per condivisione esterna.

## Quando usare

Trigger naturali:
- "fammi una timeline di X"
- "confronta X e Y"
- "butta giù delle slide su Z"
- "grafica le source per anno"
- "concept map di W"
- "scrivi un report/post su V"
- `/canvas [kind] [topic]`

## I sette kind

| Kind | Cos'è | Template |
|---|---|---|
| timeline | Ordinamento cronologico | `canvas-timeline.md` |
| comparison | Tabella side-by-side di 2-4 cose | `canvas-comparison.md` |
| concept-map | Diagramma Mermaid + note | `canvas-concept-map.md` |
| chart | PNG generato con matplotlib + caption | `canvas-chart.md` + `chart.py` |
| slides | Slide deck Marp | `canvas-slides.md` |
| report | Report markdown strutturato | `canvas-report.md` |
| post | Markdown a forma di blog post | `canvas-post.md` |

## Shareable o no

**Default: `shareable: false`** — il canvas è per l'utente. Evolve. L'agente lo legge durante QUERY come sintesi pre-compilata.

**Chiedi di `shareable` solo quando il kind implica audience esterna.**
- Per `timeline`, `comparison`, `concept-map`, `chart`: default a `shareable: false` e non chiedere.
- Per `slides`, `report`, `post`: chiedi "è per te o per condividere con qualcuno?"

Quando `shareable: true`, trattalo come snapshot. Non modificare silenziosamente. Se l'utente chiede di aggiornarlo dopo, conferma esplicitamente: "è marcato shareable — vuoi editare in place o creare un nuovo file datato?"

## Workflow

1. Conferma il kind se ambiguo.
2. Identifica le page che alimentano il canvas (`based_on`).
3. Per `slides`/`report`/`post` chiedi di `shareable` e dell'audience.
4. Per kind complessi (reveal deck, report multi-pagina), proponi l'outline prima di scrivere il file completo.
5. Carica il template giusto.
6. Riempilo con contenuto reale, citando `[[wiki/...]]` per ogni claim.
7. Per `chart`, esegui anche `chart.py` per produrre il PNG in `wiki/canvas/assets/`.
8. Scrivi in `wiki/canvas/<slug>.md` (o `.html` per reveal).
9. Aggiorna `wiki/index.md` (aggiungi a una sezione "Canvas").
10. Appendi a `wiki/log.md`: `## [YYYY-MM-DD] canvas | <slug>`.
11. Comunica all'utente il path esatto.

## Naming

Default: `<kind>-<topic>.md`. Esempio: `timeline-agent-skills.md`, `comparison-tofu-tempeh.md`.

Se `shareable: true`, opzionalmente prefissa con la data per chiarezza: `2026-04-20-agent-skills-team-talk.md`.

Se serve un secondo canvas dello stesso kind sullo stesso topic, disambigua: `timeline-agent-skills-enterprise.md`.

## Frontmatter

```yaml
---
type: canvas
kind: timeline | comparison | concept-map | chart | slides | report | post
created: YYYY-MM-DD
updated: YYYY-MM-DD
shareable: false           # true solo se esplicitamente per uso esterno
based_on:
  - [[wiki/pages/...]]
  - [[wiki/sources/...]]
purpose: "Una frase che descrive cosa questo canvas aiuta a vedere."
---
```

`based_on` è **obbligatorio**. Il linter lo usa. REFLECT lo usa.

## Regole

- **Cita tutto.** Ogni claim deve tracciare a un'entry di `based_on`.
- **Non inventare dati.** Per i chart, se i numeri non sono nel wiki, chiedi all'utente di fornirli o abortisci.
- **Parafrasa, non trascrivere.** I canvas sono sintesi.
- **Conferma prima di scrivere** quando il canvas è grande (slides con >8 slide, report con >5 sezioni).
- **Aggiorna in place** per `shareable: false`. Incrementa `updated`.
- **Non modificare** canvas `shareable: true` senza ok esplicito.

## Cosa questa skill non fa

- Render PDF/HTML da Marp o Reveal — l'utente lo fa separatamente.
- Auto-generare canvas — produrne uno è sempre un atto deliberato.
- Leggere canvas `shareable: true` durante QUERY future, salvo richiesta esplicita.
