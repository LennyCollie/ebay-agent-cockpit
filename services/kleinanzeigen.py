# services/kleinanzeigen.py
"""
eBay-Kleinanzeigen POC scraper module.

This module provides a robust web scraper for eBay-Kleinanzeigen.de
that returns normalized item dictionaries compatible with the aggregator.

Usage:
    from services.kleinanzeigen import search_kleinanzeigen
    results = search_kleinanzeigen("iphone 13", max_results=20)
"""

import logging
import random
import time
from typing import Dict, List, Optional
from urllib.parse import quote_plus

try:
    import requests
    from bs4 import BeautifulSoup
    DEPENDENCIES_AVAILABLE = True
except ImportError:
    DEPENDENCIES_AVAILABLE = False

log = logging.getLogger(__name__)

# Politeness configuration
MIN_DELAY = 1.0  # minimum delay between requests (seconds)
MAX_DELAY = 2.5  # maximum delay between requests (seconds)
REQUEST_TIMEOUT = 10  # request timeout (seconds)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

BASE_URL = "https://www.kleinanzeigen.de"


def _build_search_url(search_term: str) -> str:
    """
    Baue eine gültige Kleinanzeigen-Such-URL.

    Beispiele:
        "iphone 13" -> https://www.kleinanzeigen.de/s-iphone-13/k0
    """
    # Whitespace aufräumen
    cleaned = " ".join(search_term.strip().split())
    # Kleinanzeigen-Slug: Leerzeichen -> Bindestriche
    slug = "-".join(cleaned.split())
    encoded_slug = quote_plus(slug)

    # k0 = alle Kategorien, ganze DE-Suche
    return f"{BASE_URL}/s-{encoded_slug}/k0"



def _politeness_delay():
    """Add random delay between requests for politeness."""
    delay = random.uniform(MIN_DELAY, MAX_DELAY)
    time.sleep(delay)


def _safe_get_text(element, selector: str, default: str = "") -> str:
    """Safely extract text from BeautifulSoup element."""
    try:
        found = element.select_one(selector)
        if found:
            return found.get_text(strip=True)
        return default
    except Exception as e:
        log.debug(f"Error extracting text with selector '{selector}': {e}")
        return default


def _safe_get_attr(element, selector: str, attr: str, default: str = "") -> str:
    """Safely extract attribute from BeautifulSoup element."""
    try:
        found = element.select_one(selector)
        if found and found.has_attr(attr):
            return found[attr]
        return default
    except Exception as e:
        log.debug(f"Error extracting attr '{attr}' with selector '{selector}': {e}")
        return default


def _extract_price(price_str: str) -> Optional[str]:
    """
    Extract and normalize price from string.
    Returns numeric string like "1234.56" or None.
    """
    if not price_str:
        return None

    # Remove common text like "VB", "€", whitespace
    price_str = price_str.replace("VB", "").replace("€", "").strip()

    # Handle "zu verschenken" / free items
    if not price_str or price_str.lower() in ["zu verschenken", "kostenlos"]:
        return "0"

    try:
        # Convert German format: 1.234,56 -> 1234.56
        price_str = price_str.replace(".", "").replace(",", ".")
        price_val = float(price_str)
        return f"{price_val:.2f}"
    except ValueError:
        log.debug(f"Could not parse price: {price_str}")
        return None


def _parse_article(article) -> Optional[Dict]:
    """
    Parse a single article element from Kleinanzeigen search results.

    Returns normalized dict with keys:
        id: str (prefixed with 'kleinanzeigen:')
        title: str
        price: str (numeric or None)
        currency: str (always 'EUR')
        url: str (full URL)
        img: str (image URL or None)
        source: str (always 'kleinanzeigen')
    """
    try:
        # Multiple selector strategies for robustness

        # Title selectors (try multiple patterns)
        title = (
            _safe_get_text(article, "a.ellipsis") or
            _safe_get_text(article, "h2.text-module-begin") or
            _safe_get_text(article, "[class*='title']") or
            _safe_get_text(article, "a[title]")
        )

        if not title:
            log.debug("Article has no title, skipping")
            return None

        # URL selectors
        url = (
            _safe_get_attr(article, "a.ellipsis", "href") or
            _safe_get_attr(article, "a[href*='/s-anzeige/']", "href")
        )

        if url and not url.startswith("http"):
            url = f"https://www.kleinanzeigen.de{url}"

        if not url:
            log.debug(f"Article '{title}' has no URL, skipping")
            return None

        # Extract ID from URL
        # URL format: /s-anzeige/title/123456789-123-4567
        article_id = None
        if "/s-anzeige/" in url:
            parts = url.split("/")
            if len(parts) > 0:
                # ID is typically in last segment before query params
                last_part = parts[-1].split("?")[0]
                # Extract numeric part
                if "-" in last_part:
                    article_id = last_part.split("-")[0]

        if not article_id:
            article_id = str(abs(hash(url)))[:12]  # fallback: hash of URL

        # Price selectors
        price_text = (
            _safe_get_text(article, "p[class*='price']") or
            _safe_get_text(article, "[class*='price']") or
            _safe_get_text(article, "p.text-module-begin")
        )
        price = _extract_price(price_text)

        # Image selectors
        img = (
            _safe_get_attr(article, "img", "src") or
            _safe_get_attr(article, "img", "data-src") or
            _safe_get_attr(article, "img[class*='image']", "src")
        )

        # Ensure image URL is absolute
        if img and not img.startswith("http"):
            if img.startswith("//"):
                img = f"https:{img}"
            elif img.startswith("/"):
                img = f"https://www.kleinanzeigen.de{img}"

        return {
            "id": f"kleinanzeigen:{article_id}",
            "title": title,
            "price": price,
            "currency": "EUR",
            "url": url,
            "img": img,
            "source": "kleinanzeigen"
        }

    except Exception as e:
        log.warning(f"Error parsing article: {e}")
        return None


def search_kleinanzeigen(
    search_term: str,
    max_results: int = 20
) -> List[Dict]:
    """
    Search eBay-Kleinanzeigen for items matching the search term.

    Args:
        search_term: Search query string
        max_results: Maximum number of results to return (default 20)

    Returns:
        List of normalized item dictionaries. Empty list on error.

    Example:
        >>> results = search_kleinanzeigen("iphone 13", max_results=10)
        >>> print(f"Found {len(results)} items")
        >>> for item in results:
        ...     print(f"{item['title']}: {item['price']} {item['currency']}")
    """
    if not DEPENDENCIES_AVAILABLE:
        log.error(
            "Required dependencies not available. "
            "Install: pip install requests beautifulsoup4 lxml"
        )
        return []

    if not search_term or not search_term.strip():
        log.warning("Empty search term provided")
        return []

    results = []

    try:
        # Build search URL (neues Format)
        search_url = _build_search_url(search_term)

        log.info(f"Searching Kleinanzeigen for: {search_term}")
        log.debug(f"Kleinanzeigen URL: {search_url}")

        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }

        response = requests.get(
            search_url,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True
        )
        response.raise_for_status()

        # Parse HTML
        soup = BeautifulSoup(response.text, "lxml")

        # Find article containers - try multiple selectors for robustness
        articles = (
            soup.select("article[class*='aditem']") or
            soup.select("li[class*='ad-listitem']") or
            soup.select("article") or
            []
        )

        log.info(f"Found {len(articles)} article elements")

        for article in articles[:max_results]:
            item = _parse_article(article)
            if item:
                results.append(item)
                log.debug(f"Parsed: {item['title']}")

        log.info(f"Successfully parsed {len(results)} items from Kleinanzeigen")

    except requests.RequestException as e:
        log.error(f"Request error searching Kleinanzeigen: {e}")
    except Exception as e:
        log.error(f"Unexpected error searching Kleinanzeigen: {e}")

    return results


def check_dependencies() -> bool:
    """Check if required dependencies are available."""
    return DEPENDENCIES_AVAILABLE


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO)
    print("Testing Kleinanzeigen scraper...")

    if not check_dependencies():
        print("ERROR: Missing dependencies!")
        print("Install with: pip install requests beautifulsoup4 lxml")
        exit(1)

    test_term = "iphone"
    print(f"\nSearching for: {test_term}")

    items = search_kleinanzeigen(test_term, max_results=5)

    print(f"\nFound {len(items)} items:\n")
    for item in items:
        print(f"- {item['title']}")
        print(f"  Price: {item['price']} {item['currency']}")
        print(f"  URL: {item['url']}")
        print(f"  ID: {item['id']}")
        print()
