---
type: canvas
kind: chart
created: {{DATE}}
updated: {{DATE}}
shareable: false
based_on:
  - [[wiki/pages/{{TOPIC}}]]
purpose: "Quantitative view of {{TOPIC}} along {{DIMENSION}}."
chart_script: chart.py
chart_output: assets/{{SLUG}}.png
---

# {{TITLE}}

![{{TITLE}}](assets/{{SLUG}}.png)

## What this shows

One paragraph describing what the chart reveals. Be concrete.

## Data source

- Numbers from: [[wiki/sources/...]], [[wiki/sources/...]]
- Aggregation method: counted by tag / summed by month / ...

## Regeneration

```bash
cd wiki/canvas
python chart.py
```

## Caveats

What the chart cannot show.
