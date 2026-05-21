# Lint Report

Output dell'ultima esecuzione della skill `vault-linter`. Solo check deterministici, **mai auto-fix**.

Check eseguiti:

- dead link (`[[...]]` che non risolve)
- frontmatter mancante o malformato in `wiki/`
- naming inconsistente
- views stantie (`based_on` punta a pages aggiornate dopo la view)
- pages orphan (zero inbound link)
- concetti citati in pages senza page propria
- claim potenzialmente outdated alla luce di fonti più recenti
- cross-reference mancanti

---

_Nessun lint ancora eseguito. Trigger con "lint", o auto-trigger dopo 5 ingest / 7 giorni._
