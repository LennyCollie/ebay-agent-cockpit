# services/kleinanzeigen.py
"""
eBay-Kleinanzeigen POC scraper with requests + BeautifulSoup.
Returns normalized item dicts with keys: id, title, price, currency, url, img, source.
Includes politeness delays and fallback selectors.
"""
import logging
import time
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# Base URL for eBay-Kleinanzeigen
BASE_URL = "https://www.kleinanzeigen.de"
SEARCH_URL = f"{BASE_URL}/s-suchanfrage.html"

# User-Agent to identify ourselves
USER_AGENT = "Mozilla/5.0 (compatible; EbayAgentCockpit/1.0; +https://github.com/LennyCollie/ebay-agent-cockpit)"

# Politeness delay between requests (in seconds)
POLITENESS_DELAY = 1.5


def search_kleinanzeigen(
    query: str,
    max_results: int = 20,
    timeout: int = 10
) -> List[Dict[str, Optional[str]]]:
    """
    Search eBay-Kleinanzeigen for the given query and return normalized results.
    
    Args:
        query: Search term
        max_results: Maximum number of results to return (default: 20)
        timeout: Request timeout in seconds (default: 10)
    
    Returns:
        List of dicts with keys: id, title, price, currency, url, img, source
    """
    if not query or not query.strip():
        log.warning("Empty query provided to search_kleinanzeigen")
        return []
    
    try:
        # Build search URL with query parameter
        params = {
            "keywords": query.strip(),
            "sortingField": "SORTING_DATE"  # Sort by date (newest first)
        }
        
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
        
        log.info(f"Searching Kleinanzeigen for: {query}")
        
        # Make request with politeness delay
        time.sleep(POLITENESS_DELAY)
        response = requests.get(
            SEARCH_URL,
            params=params,
            headers=headers,
            timeout=timeout,
            allow_redirects=True
        )
        response.raise_for_status()
        
        # Parse HTML
        soup = BeautifulSoup(response.content, "lxml")
        
        # Extract items using multiple fallback selectors
        items = _extract_items(soup, max_results)
        
        log.info(f"Found {len(items)} items for query: {query}")
        return items
        
    except requests.exceptions.Timeout:
        log.error(f"Timeout while searching Kleinanzeigen for: {query}")
        return []
    except requests.exceptions.RequestException as e:
        log.error(f"Request error while searching Kleinanzeigen: {e}")
        return []
    except Exception as e:
        log.error(f"Unexpected error in search_kleinanzeigen: {e}")
        return []


def _extract_items(soup: BeautifulSoup, max_results: int) -> List[Dict[str, Optional[str]]]:
    """
    Extract items from parsed HTML using fallback selectors.
    
    Args:
        soup: BeautifulSoup parsed HTML
        max_results: Maximum number of items to extract
    
    Returns:
        List of normalized item dicts
    """
    items = []
    
    # Try multiple selectors (Kleinanzeigen layout changes frequently)
    # Primary selector: article tags with ad-listitem class
    articles = soup.find_all("article", class_="aditem", limit=max_results * 2)
    
    # Fallback 1: li tags with ad-listitem class
    if not articles:
        articles = soup.find_all("li", class_="ad-listitem", limit=max_results * 2)
    
    # Fallback 2: div tags with specific class patterns
    if not articles:
        articles = soup.find_all("div", class_=lambda x: x and "aditem" in x, limit=max_results * 2)
    
    for article in articles:
        if len(items) >= max_results:
            break
        
        try:
            item = _parse_item(article)
            if item and item.get("id") and item.get("title"):
                items.append(item)
        except Exception as e:
            log.debug(f"Failed to parse item: {e}")
            continue
    
    return items


def _parse_item(article) -> Optional[Dict[str, Optional[str]]]:
    """
    Parse a single item from HTML element.
    
    Args:
        article: BeautifulSoup element (article/li/div)
    
    Returns:
        Dict with keys: id, title, price, currency, url, img, source or None if parsing fails
    """
    # Extract ID from data attribute or href
    item_id = None
    item_id = article.get("data-adid") or article.get("data-ad-id")
    
    # Extract title and URL
    title = None
    url = None
    
    # Try to find title link (multiple selectors)
    title_link = article.find("a", class_="ellipsis")
    if not title_link:
        title_link = article.find("a", {"data-test": "listing-title"})
    if not title_link:
        title_link = article.find("a", class_="aditem-main--title")
    if not title_link:
        h2 = article.find("h2", class_="text-module-begin")
        if h2:
            title_link = h2.find("a")
    
    if title_link:
        title = title_link.get_text(strip=True)
        href = title_link.get("href")
        if href:
            url = urljoin(BASE_URL, href)
            # Extract ID from URL if not found in data attributes
            if not item_id and "/s-anzeige/" in href:
                # URL format: /s-anzeige/title-slug/ID-extra-data
                parts = href.split("/")
                if len(parts) >= 4:
                    # Get the last part which contains the ID
                    id_part = parts[-1]
                    # ID is before the first dash
                    if "-" in id_part:
                        item_id = id_part.split("-")[0]
                    else:
                        item_id = id_part
    
    # Extract price
    price = None
    currency = "EUR"  # Default currency for Kleinanzeigen
    
    price_elem = (
        article.find("p", class_="aditem-main--middle--price-shipping--price") or
        article.find("p", {"data-test": "listing-price"}) or
        article.find("span", class_="price") or
        article.find("p", class_="aditem-main--middle--price")
    )
    
    if price_elem:
        price_text = price_elem.get_text(strip=True)
        # Parse price: "1.234 €", "VB", "Zu verschenken", etc.
        if price_text and price_text.lower() not in ["vb", "zu verschenken", "tausch"]:
            # Extract numeric value
            price_cleaned = price_text.replace(".", "").replace(",", ".").replace("€", "").replace("EUR", "").strip()
            try:
                price = str(float(price_cleaned))
            except (ValueError, AttributeError):
                price = None
    
    # Extract image
    img = None
    img_elem = article.find("img")
    if img_elem:
        # Try src first, then data-src (lazy loading)
        img = img_elem.get("src") or img_elem.get("data-src")
        if img and img.startswith("//"):
            img = "https:" + img
        elif img and not img.startswith("http"):
            img = urljoin(BASE_URL, img)
    
    # Only return if we have minimum required fields
    if not item_id or not title:
        return None
    
    return {
        "id": f"kleinanzeigen:{item_id}",
        "title": title,
        "price": price,
        "currency": currency,
        "url": url,
        "img": img,
        "source": "kleinanzeigen"
    }


def test_search():
    """
    Test function for manual verification.
    """
    print("Testing Kleinanzeigen search...")
    results = search_kleinanzeigen("laptop", max_results=5)
    
    if results:
        print(f"\nFound {len(results)} results:")
        for i, item in enumerate(results, 1):
            print(f"\n{i}. {item['title']}")
            print(f"   ID: {item['id']}")
            print(f"   Price: {item['price']} {item['currency']}" if item['price'] else "   Price: N/A")
            print(f"   URL: {item['url']}")
            print(f"   Image: {item['img']}" if item['img'] else "   Image: N/A")
    else:
        print("No results found")


if __name__ == "__main__":
    test_search()
