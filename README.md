
# Frontend Bootstrap Pack – ebay-agent-cockpit

Sofort nutzbare Bootstrap-Variante (v5) für schnelles, schönes UI auf Render.

## Struktur
.
├── templates/
│   ├── base.html
│   ├── _flash.html
│   ├── dashboard.html
│   ├── 404.html
│   └── 500.html
└── static/
    ├── css/
    │   └── custom.css
    └── js/
        └── main.js

## Einbindung (Flask/Jinja)
- `Flask(__name__, template_folder="templates", static_folder="static")`
- In deinen Views: `return render_template("dashboard.html")`
- Optional Error-Handler registrieren (404/500).

## Hinweise
- Bootstrap via CDN (CSS + JS bundle) wird in `base.html` eingebunden.
- Flash-Messages nutzen Bootstrap Alerts (dismissible).

## eBay-Kleinanzeigen Integration

### Overview

This project now includes an optional integration for eBay-Kleinanzeigen search results. The integration provides a POC scraper that can merge Kleinanzeigen results with your existing eBay search results.

### Features

- 🔍 **Search integration**: Seamlessly merge Kleinanzeigen results with eBay results
- 🛡️ **Safe & optional**: Controlled via environment variable, fails gracefully
- 🔄 **De-duplication**: Automatically filters out duplicate URLs
- ⏱️ **Politeness**: Built-in delays to respect server resources
- 📝 **Normalized format**: Returns standardized item dicts compatible with eBay results

### Quick Start

1. **Enable the feature** in your `.env` file:

```bash
ENABLE_KLEINANZEIGEN=1
```

2. **Integrate into your search** (one-liner):

```python
from services.search_integration import merge_kleinanzeigen_if_enabled

# In your search route/function:
results = ebay_search(query)
results = merge_kleinanzeigen_if_enabled(query, results, max_klein=20)
```

That's it! The integration will automatically fetch and merge Kleinanzeigen results when enabled.

### Documentation

For detailed information, see:

- 📖 [Full documentation](docs/kleinanzeigen.md) - Complete guide including legal considerations, caching, and troubleshooting
- 🧪 [Tests](tests/test_kleinanzeigen_parser.py) - Unit tests with fixtures
- 🎯 [Test script](scripts/run_kleinanzeigen_test.py) - Manual QA script

### Testing

Run the integration test:

```bash
python scripts/run_kleinanzeigen_test.py "laptop" 5
```

Run unit tests:

```bash
pytest tests/test_kleinanzeigen_parser.py
```

### Integration Example

Here's how to integrate it into your existing search route:

```python
# routes/search.py
from services.search_integration import merge_kleinanzeigen_if_enabled

@bp_search.get("/search/results")
def search_results():
    q = request.args.get("q", "")
    
    # Your existing eBay search (Finding or Browse API)
    results = normalize_finding(finding_search(q))
    
    # Add Kleinanzeigen results - single line!
    results = merge_kleinanzeigen_if_enabled(q, results, max_klein=20)
    
    return render_template("search_results.html", results=results)
```

### Result Format

Each Kleinanzeigen result has the same structure as eBay results:

```python
{
    "id": "kleinanzeigen:123456789",
    "title": "Product Title",
    "price": "299.99",        # or None
    "currency": "EUR",
    "url": "https://www.kleinanzeigen.de/...",
    "img": "https://...",     # or None
    "source": "kleinanzeigen"
}
```

### Important Notes

⚠️ **Legal Considerations**: This is a POC implementation for personal use. Before production use:
- Review Kleinanzeigen's robots.txt and Terms of Service
- Consider implementing caching to reduce server load
- Ensure compliance with applicable laws (GDPR, etc.)

For more details, see the [full documentation](docs/kleinanzeigen.md).
