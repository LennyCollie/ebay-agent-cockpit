# eBay‑Kleinanzeigen Integration (POC)

Kurz: dieses Modul ist ein Proof‑of‑Concept Scraper, der Ergebnisse von
https://www.ebay-kleinanzeigen.de einholt und in deiner App normalisiert.

Enablement

- Setze in deiner `.env`:

```
ENABLE_KLEINANZEIGEN=1
```

Wie die Integration funktioniert (einzeilige Einbindung)

- In deiner zentralen Such‑Aggregator‑Funktion (wo `results` gesammelt werden),
  füge nach dem Abruf der anderen Quellen diese Zeile ein:

```python
from services.search_integration import merge_kleinanzeigen_if_enabled
results = merge_kleinanzeigen_if_enabled(term, results, max_klein=20)
```

Wichtige Hinweise

- Legal: Lies `https://www.ebay-kleinanzeigen.de/robots.txt` und die Nutzungsbedingungen. Scraping kann rechtlich eingeschränkt sein.
- Rate‑Limits: Verwende geringe Frequenzen und Cache Ergebnisse. Implementiere für Produktion Proxys & Backoff.
- Maintenance: HTML‑Selektoren sind fragile; falls Ergebnisse ausbleiben, prüfe & passe die Selektoren in `services/kleinanzeigen.py`.

Testing

- Lokale Unit Test (fixture): `pytest tests/test_kleinanzeigen_parser.py -q`
- Manuelles Run‑Script: `python scripts/run_kleinanzeigen_test.py "lego technic" 5`

Deployment / Docker

- Stelle sicher, dass `requirements.txt` die folgenden Bibliotheken enthält:
  - requests
  - beautifulsoup4
  - lxml

Fazit

- PR liefert POC + helper; die finale Anbindung zur Hauptsuche ist bewusst nicht automatisiert, damit du als Maintainer die Stelle reviewen und aktivieren kannst.
