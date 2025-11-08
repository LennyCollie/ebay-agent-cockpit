# eBay-Kleinanzeigen Integration

This document describes the eBay-Kleinanzeigen integration in the ebay-agent-cockpit project.

## Overview

The Kleinanzeigen integration provides a POC scraper that searches eBay-Kleinanzeigen (formerly eBay Classifieds Germany) and returns normalized results that can be merged with eBay search results.

## Features

- **Robust scraping**: Uses requests + BeautifulSoup with multiple fallback selectors
- **Normalized output**: Returns standardized item dicts with keys: `id`, `title`, `price`, `currency`, `url`, `img`, `source`
- **Politeness delays**: Built-in delays between requests to respect server resources
- **Safe integration**: Optional feature controlled via environment variable
- **De-duplication**: Automatically filters out duplicate URLs when merging with eBay results

## Legal & Robots.txt Considerations

### Important Legal Notes

⚠️ **Before using this integration in production:**

1. **Check robots.txt**: Review https://www.kleinanzeigen.de/robots.txt for current crawling policies
2. **Terms of Service**: Ensure your use complies with Kleinanzeigen's Terms of Service
3. **Rate Limiting**: Respect the site's resources - the integration includes politeness delays
4. **Data Usage**: Only use scraped data in accordance with applicable laws (GDPR, copyright, etc.)
5. **Alternative APIs**: Consider contacting Kleinanzeigen for official API access if available

### Current Implementation

The current implementation:
- Uses a 1.5-second delay between requests (configurable)
- Identifies itself with a proper User-Agent
- Only scrapes publicly available search results
- Does not bypass any access controls

**This is a Proof of Concept (POC) implementation** intended for personal, non-commercial use and testing. For production use, always verify legal compliance and consider obtaining official API access.

## Enabling the Feature

### Environment Variable

Add the following to your `.env` file to enable Kleinanzeigen integration:

```bash
# Enable eBay-Kleinanzeigen integration
ENABLE_KLEINANZEIGEN=1
```

Set to `0`, `false`, or omit entirely to disable.

### Docker / Container Setup

If using Docker, ensure your `.env` file is properly loaded:

```yaml
# docker-compose.yml
services:
  app:
    env_file:
      - .env
    # ... other config
```

The Dockerfile already uses `requirements.txt`, so the new dependencies (beautifulsoup4, lxml) will be automatically installed during build.

## Rate Limits & Caching

### Built-in Rate Limiting

The scraper includes a `POLITENESS_DELAY` of 1.5 seconds between requests. This helps prevent server overload and reduces the risk of being blocked.

### Recommended Caching Strategy

For production use, implement caching to reduce load:

```python
# Example: Cache results for 30 minutes
import time
from functools import lru_cache

@lru_cache(maxsize=128)
def cached_search(query: str, timestamp: int) -> list:
    """Cache search results, invalidated every 30 minutes"""
    from services.kleinanzeigen import search_kleinanzeigen
    return search_kleinanzeigen(query)

# Use with:
results = cached_search("laptop", int(time.time() / 1800))
```

Alternative caching solutions:
- Redis for distributed caching
- Flask-Caching for simple in-memory cache
- Database caching with expiry timestamps

### Recommended Practices

1. **Cache search results** for at least 15-30 minutes
2. **Limit concurrent requests** to 1 per session
3. **Monitor for errors** - implement circuit breaker pattern if getting blocked
4. **Use sparingly** - only fetch Kleinanzeigen results when explicitly needed
5. **Respect server resources** - don't scrape during peak hours unnecessarily

## Usage

### Basic Integration

The integration is designed to be added with a single line to your search aggregator:

```python
from services.search_integration import merge_kleinanzeigen_if_enabled

# In your search route/function:
def search_results():
    q = request.args.get("q", "")
    
    # Your existing eBay search
    results = ebay_search(q)
    
    # Add Kleinanzeigen results (one-liner)
    results = merge_kleinanzeigen_if_enabled(q, results, max_klein=20)
    
    return render_template("search_results.html", results=results)
```

### Direct Usage

You can also use the scraper directly:

```python
from services.kleinanzeigen import search_kleinanzeigen

results = search_kleinanzeigen("laptop", max_results=10)

for item in results:
    print(f"{item['title']}: {item['price']} {item['currency']}")
    print(f"URL: {item['url']}")
```

### Testing

Run the included test script:

```bash
python scripts/run_kleinanzeigen_test.py
```

Or use pytest:

```bash
pytest tests/test_kleinanzeigen_parser.py
```

## Result Format

Each item returned has the following structure:

```python
{
    "id": "kleinanzeigen:123456789",      # Unique ID prefixed with 'kleinanzeigen:'
    "title": "Example Product Title",      # Product title
    "price": "299.99",                     # Price as string (numeric value) or None
    "currency": "EUR",                     # Currency code (always EUR for Kleinanzeigen)
    "url": "https://www.kleinanzeigen.de/...",  # Full URL to listing
    "img": "https://...",                  # Image URL or None
    "source": "kleinanzeigen"              # Source identifier
}
```

## Error Handling

The integration is designed to fail gracefully:

- Network errors: Returns empty list
- Parsing errors: Skips problematic items
- Missing data: Returns None for optional fields
- Disabled feature: Returns original results unchanged

All errors are logged but don't crash the application.

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_KLEINANZEIGEN` | `0` | Enable/disable the integration (`1` to enable) |

### Code Constants

In `services/kleinanzeigen.py`:

```python
POLITENESS_DELAY = 1.5  # Seconds between requests
USER_AGENT = "..."      # User-Agent header
```

## Troubleshooting

### No results returned

1. Check if `ENABLE_KLEINANZEIGEN=1` is set in `.env`
2. Verify network connectivity
3. Check logs for error messages
4. Test with a simple query like "laptop"

### Rate limiting / Blocked

1. Increase `POLITENESS_DELAY` in `services/kleinanzeigen.py`
2. Implement caching (see above)
3. Reduce `max_klein` parameter
4. Check if IP is blocked (try from different network)

### Parsing errors

Kleinanzeigen may change their HTML structure. If parsing fails:

1. Check logs for specific error messages
2. Update selectors in `_parse_item()` function
3. Add new fallback selectors
4. Open an issue with HTML sample

## Future Enhancements

Potential improvements for future versions:

- [ ] Add support for filters (price range, location, category)
- [ ] Implement proper caching layer
- [ ] Add pagination support for more results
- [ ] Support for advanced search operators
- [ ] Monitoring and alerting for scraping issues
- [ ] Circuit breaker pattern for resilience
- [ ] Official API integration (if/when available)

## Support

For issues, questions, or contributions:

- GitHub Issues: https://github.com/LennyCollie/ebay-agent-cockpit/issues
- Repository: https://github.com/LennyCollie/ebay-agent-cockpit

---

**Last Updated**: November 2025
