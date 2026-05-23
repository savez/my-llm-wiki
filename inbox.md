# Inbox

Coda di URL e feed RSS/Atom da fetchare. Tu aggiungi, la skill `inbox-fetcher` elabora con il trigger "elabora inbox" / "fetcha inbox" / "polla i feed".

Formato:

- URL singoli: `- [ ] <url>` sotto `## Da processare`. Una volta processato, il fetcher lo marca `- [x]` e salva il risultato in `raw/web/<slug>/` o `raw/papers/<slug>.pdf`.
- Feed: `- feed: <url-feed>` sotto `## Feeds`. La skill polla periodicamente, segue i redirect del link di ogni nuovo item, e appende l'URL canonico sotto `## Da processare`. Per disiscriverti, cancella la riga del feed.

## Feeds

<!-- Sottoscrizioni a feed RSS/Atom. Esempi:
- feed: https://www.anthropic.com/news/rss.xml
- feed: https://simonwillison.net/atom/everything/
-->

## Da processare

<!-- esempi:
- [ ] https://arxiv.org/abs/1706.03762
- [ ] https://karpathy.github.io/2025/...
-->

## Elaborati

<!-- popolato automaticamente dal fetcher -->
