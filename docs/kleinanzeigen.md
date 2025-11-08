# eBay-Kleinanzeigen Integration

This document describes the eBay-Kleinanzeigen POC integration.

## Overview

The Kleinanzeigen integration provides web scraping functionality to fetch search results from eBay-Kleinanzeigen.de and merge them with your existing aggregator results.

## Features

- 🔍 Robust web scraping with multiple fallback selectors
- 🤝 Politeness delays (1-2.5s) between requests
- 🛡️ Fail-safe integration - never breaks existing functionality
- 🔧 Environment flag controlled (opt-in)
- 📋 Normalized data format compatible with aggregator
- 🔄 De-duplication by URL

## Legal & Ethical Considerations

### robots.txt Compliance

Before deploying to production, **always check** https://www.kleinanzeigen.de/robots.txt to ensure your scraping activity is permitted.

### Rate Limits

- The scraper includes random delays (1-2.5 seconds) between requests
- Default max results per search: 20 items
- **Do not** increase scraping frequency beyond what's reasonable
- Consider implementing exponential backoff on errors

### Recommendations

1. **Caching**: Cache results for at least 5-10 minutes to reduce load
2. **Monitoring**: Log all requests and monitor for 429/503 errors
3. **User-Agent**: Uses standard browser UA - consider customizing with contact info
4. **Error Handling**: All errors are caught and logged, never breaking aggregator

## How to Enable

### 1. Install Dependencies

The required dependencies are listed in `requirements.txt`:

```bash
pip install -r requirements.txt
```

This installs:
- `requests>=2.31` (already present)
- `beautifulsoup4>=4.11` (new)
- `lxml>=4.9` (new)

### 2. Set Environment Variable

Add to your `.env` file:

```bash
ENABLE_KLEINANZEIGEN=1
```

To disable, either:
- Set `ENABLE_KLEINANZEIGEN=0`
- Remove the variable entirely

## Integration into Aggregator

### One-Line Integration

The integration is designed to be a single function call that wraps your existing search:

```python
from services.search_integration import merge_kleinanzeigen_if_enabled

# Your existing search code
def search_items(term):
    results = your_ebay_search_function(term)
    
    # Add this ONE line to enable Kleinanzeigen integration
    results = merge_kleinanzeigen_if_enabled(term, results, max_klein=20)
    
    return results
```

### Where to Add It

Look for your main search/aggregator function, typically in:
- `app.py` - in route handlers like `/search`
- `services/ebay_api.py` - in search functions
- Custom aggregator modules

**Example locations:**

```python
# Example 1: In Flask route
@app.route('/search')
def search():
    term = request.args.get('q')
    results = fetch_ebay_results(term)
    
    # Add Kleinanzeigen results
    results = merge_kleinanzeigen_if_enabled(term, results)
    
    return jsonify(results)

# Example 2: In service layer
def aggregate_results(search_term):
    all_results = []
    all_results.extend(search_ebay(search_term))
    all_results.extend(search_other_source(search_term))
    
    # Add Kleinanzeigen if enabled
    all_results = merge_kleinanzeigen_if_enabled(search_term, all_results)
    
    return all_results
```

## Data Format

Items returned from Kleinanzeigen have this structure:

```python
{
    "id": "kleinanzeigen:123456789",  # Always prefixed
    "title": "iPhone 13 Pro wie neu",
    "price": "599.00",  # Normalized to decimal string or None
    "currency": "EUR",  # Always EUR
    "url": "https://www.kleinanzeigen.de/s-anzeige/...",
    "img": "https://img.kleinanzeigen.de/...",  # or None
    "source": "kleinanzeigen"  # Always "kleinanzeigen"
}
```

## Testing

### Unit Tests

Run the included unit test:

```bash
pytest tests/test_kleinanzeigen_parser.py -v
```

This test uses a fixture HTML file and doesn't require internet.

### Manual Testing

Use the provided test script:

```bash
python scripts/run_kleinanzeigen_test.py <search_term>
```

Example:
```bash
python scripts/run_kleinanzeigen_test.py "iphone 13"
```

This will:
1. Search Kleinanzeigen for the term
2. Print results as formatted JSON
3. Show count and sample data

### Integration Testing

Test the full integration:

```python
# In Python REPL or test script
import os
os.environ['ENABLE_KLEINANZEIGEN'] = '1'

from services.search_integration import merge_kleinanzeigen_if_enabled

existing = [{"title": "Test", "url": "http://example.com", "source": "test"}]
merged = merge_kleinanzeigen_if_enabled("iphone", existing, max_klein=5)

print(f"Original: {len(existing)} items")
print(f"Merged: {len(merged)} items")
```

## Troubleshooting

### No Results Returned

1. Check internet connectivity
2. Verify URL format hasn't changed on Kleinanzeigen.de
3. Check logs for errors: `log.error` messages
4. Test with known working search term (e.g., "iphone")

### Import Errors

```python
# Test dependencies
from services.kleinanzeigen import check_dependencies
print(check_dependencies())  # Should print True
```

If False, reinstall:
```bash
pip install requests beautifulsoup4 lxml
```

### Rate Limiting / 429 Errors

If you see HTTP 429 errors:
1. Increase delays in `services/kleinanzeigen.py` (MIN_DELAY, MAX_DELAY)
2. Reduce max_results
3. Implement caching
4. Add exponential backoff

### Parsing Errors

The scraper uses multiple fallback selectors. If parsing fails:
1. Check if Kleinanzeigen changed their HTML structure
2. Update selectors in `_parse_article()` function
3. Test with `scripts/run_kleinanzeigen_test.py` to debug

## Architecture

```
services/
├── kleinanzeigen.py           # Core scraper (requests + BeautifulSoup)
└── search_integration.py      # Fail-safe integration helper

tests/
├── test_kleinanzeigen_parser.py  # Unit tests
└── fixtures/
    └── kleinanzeigen_sample.html  # Test HTML fixture

scripts/
└── run_kleinanzeigen_test.py     # Manual testing script
```

## Future Enhancements

Potential improvements (not in this POC):

- [ ] Caching layer (Redis/file-based)
- [ ] Pagination support (multiple pages)
- [ ] Advanced filtering (price range, location)
- [ ] Image proxy/CDN integration
- [ ] Async/parallel requests
- [ ] Metrics/monitoring integration
- [ ] Admin UI toggle for enable/disable
- [ ] Per-user enable/disable settings

## Support

For issues or questions:
1. Check logs for error messages
2. Review this documentation
3. Test components individually (scraper, integration, dependencies)
4. Check Kleinanzeigen.de for structural changes

## License & Attribution

This is a proof-of-concept integration. Ensure compliance with:
- eBay-Kleinanzeigen Terms of Service
- robots.txt directives
- Local data protection laws (GDPR if in EU)

Always respect rate limits and use responsibly.
