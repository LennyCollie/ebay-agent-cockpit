"""
Facebook Marketplace Integration
HINWEIS: Facebook ist komplexer als andere Portale wegen Login-Anforderungen
Diese Version nutzt Public-Search ohne Login für beste Ergebnisse
"""
import requests
from bs4 import BeautifulSoup
import re
import hashlib
import json
from datetime import datetime
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


def check_dependencies() -> bool:
    """Prüft Dependencies"""
    try:
        import requests
        from bs4 import BeautifulSoup
        return True
    except ImportError:
        logger.error("Dependencies fehlen!")
        return False


def search_facebook_marketplace(
    query: str,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    location: Optional[str] = None,
    radius_km: Optional[int] = 50,
    limit: int = 50
) -> List[Dict]:
    """
    Sucht auf Facebook Marketplace

    WICHTIG:
    - Facebook hat Bot-Protection
    - Beste Methode: Mobile-Website mit realistischen Headers
    - Alternative: Facebook Graph API (benötigt App-Registration)

    Args:
        query: Suchbegriff
        price_min: Min-Preis
        price_max: Max-Preis
        location: Stadt oder PLZ
        radius_km: Umkreis
        limit: Max Anzahl

    Returns:
        Liste von Artikeln
    """
    try:
        url = _build_search_url(query, price_min, price_max, location, radius_km)

        print(f"\n{'='*60}")
        print(f"[*] FACEBOOK MARKETPLACE SCRAPING")
        print(f"{'='*60}")
        print(f"URL: {url}")
        print(f"Query: {query}")
        print(f"[!]  HINWEIS: Facebook hat Bot-Protection!")
        print(f"{'='*60}\n")

        # Sehr realistische Mobile Headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0',
        }

        # Session verwenden (realistischer)
        session = requests.Session()

        # Erst Hauptseite laden (Cookie setzen)
        session.get('https://www.facebook.com/marketplace', headers=headers)

        # Dann Suche
        response = session.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        print(f"[OK] Status: {response.status_code}")

        # Parse
        soup = BeautifulSoup(response.text, 'html.parser')

        # Facebook verwendet dynamisches Rendering - wir suchen nach Daten im Script-Tag
        results = _parse_facebook_data(soup, query)

        if not results:
            # Fallback: Klassisches HTML-Parsing
            results = _parse_facebook_html(soup, query)

        print(f"[+] Gefundene Artikel: {len(results)}\n")

        # Preis-Filter anwenden
        filtered = []
        for item in results[:limit]:
            if price_min and item.get('price') and item['price'] < price_min:
                continue
            if price_max and item.get('price') and item['price'] > price_max:
                continue
            filtered.append(item)

        print(f"[OK] Nach Filter: {len(filtered)} Artikel\n")
        return filtered

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 403:
            logger.warning("[!]  Facebook blockiert Bot-Zugriff. Empfehlung:")
            logger.warning("   1. Graph API nutzen (siehe Docs)")
            logger.warning("   2. Proxy verwenden")
            logger.warning("   3. Rate-Limiting implementieren")
        else:
            logger.error(f"HTTP Error: {e}")
        return []

    except Exception as e:
        logger.error(f"Facebook Scraping Error: {e}")
        import traceback
        traceback.print_exc()
        return []


def _build_search_url(
    query: str,
    price_min: Optional[float],
    price_max: Optional[float],
    location: Optional[str],
    radius_km: Optional[int]
) -> str:
    """Erstellt Facebook Marketplace URL"""
    query_encoded = query.replace(' ', '%20')

    # Facebook Marketplace Search
    url = f"https://www.facebook.com/marketplace/search/?query={query_encoded}"

    # Preis-Range
    if price_min:
        url += f"&minPrice={int(price_min)}"
    if price_max:
        url += f"&maxPrice={int(price_max)}"

    # Location (Facebook nutzt Location-IDs, aber wir können Text versuchen)
    if location:
        url += f"&location={location}"

    # Radius (in Miles! Facebook nutzt Miles)
    if radius_km:
        miles = int(radius_km * 0.621371)  # km zu miles
        url += f"&radius={miles}"

    # Sortierung
    url += "&sortBy=creation_time_descend"  # Neueste zuerst

    return url


def _parse_facebook_data(soup: BeautifulSoup, query: str) -> List[Dict]:
    """
    Parst Facebook-Daten aus Script-Tags
    Facebook rendert Daten oft in JSON innerhalb von Script-Tags
    """
    results = []

    try:
        # Suche nach Script-Tags mit JSON-Daten
        scripts = soup.find_all('script', type='application/json')

        for script in scripts:
            try:
                data = json.loads(script.string)

                # Facebook hat verschiedene JSON-Strukturen
                # Wir suchen nach Marketplace-Listings
                items = _extract_items_from_json(data)
                results.extend(items)

            except (json.JSONDecodeError, AttributeError):
                continue

        return results

    except Exception as e:
        logger.debug(f"JSON parsing failed: {e}")
        return []


def _extract_items_from_json(data: dict, results: list = None) -> list:
    """Rekursiv durch JSON-Struktur und extrahiere Listings"""
    if results is None:
        results = []

    if isinstance(data, dict):
        # Check ob das ein Marketplace-Item ist
        if 'marketplace_listing_title' in data or 'listing_price' in data:
            item = _parse_facebook_item(data)
            if item:
                results.append(item)

        # Rekursiv durch alle Keys
        for value in data.values():
            _extract_items_from_json(value, results)

    elif isinstance(data, list):
        for item in data:
            _extract_items_from_json(item, results)

    return results


def _parse_facebook_item(data: dict) -> Optional[Dict]:
    """Parst ein einzelnes Facebook Marketplace Item aus JSON"""
    try:
        # Titel
        title = data.get('marketplace_listing_title') or data.get('title') or ''

        # Preis
        price = None
        price_data = data.get('listing_price') or data.get('price')
        if price_data:
            if isinstance(price_data, dict):
                price = float(price_data.get('amount', 0))
            else:
                price = _extract_price(str(price_data))

        # URL
        url = data.get('url') or data.get('uri') or ''
        if url and not url.startswith('http'):
            url = f"https://www.facebook.com{url}"

        # Bild
        image_url = None
        if 'image' in data:
            img = data['image']
            if isinstance(img, dict):
                image_url = img.get('uri') or img.get('url')
            else:
                image_url = str(img)

        # Location
        location = data.get('location', {})
        if isinstance(location, dict):
            location = location.get('name') or location.get('city') or ''
        else:
            location = str(location)

        # ID
        item_id = data.get('id') or data.get('listing_id') or ''

        if not title or not url:
            return None

        return {
            'item_id': f"fb_{item_id}" if item_id else _generate_item_id(url),
            'title': title[:500],
            'price': price,
            'url': url,
            'image_url': image_url,
            'location': location,
            'postal_code': None,
            'condition': 'Gebraucht',
            'description': title,
            'published_date': datetime.now(),
            'source': 'facebook'
        }

    except Exception as e:
        logger.debug(f"Parse item error: {e}")
        return None


def _parse_facebook_html(soup: BeautifulSoup, query: str) -> List[Dict]:
    """
    Fallback: Klassisches HTML-Parsing
    Facebook-HTML ist sehr komplex und ändert sich häufig!
    """
    results = []

    # Facebook nutzt generische div-Klassen (ändern sich oft!)
    # Wir versuchen mehrere Selektoren

    selectors = [
        'div[data-testid*="marketplace"]',
        'a[href*="/marketplace/item/"]',
        'div.x9f619',  # Facebook Generic Class
    ]

    for selector in selectors:
        items = soup.select(selector)
        if items:
            logger.info(f"Found {len(items)} items with selector: {selector}")
            break

    # Wenn keine Items gefunden, warnen
    if not items:
        logger.warning("[!]  Keine Items gefunden - Facebook struktur hat sich geändert!")
        logger.warning("   Empfehlung: Graph API nutzen oder Proxy verwenden")
        return []

    for item in items[:50]:
        try:
            parsed = _parse_html_item(item)
            if parsed:
                results.append(parsed)
        except Exception as e:
            logger.debug(f"Parse error: {e}")
            continue

    return results


def _parse_html_item(item) -> Optional[Dict]:
    """Parst HTML-Element zu Item-Dict"""
    try:
        # URL
        link = item.find('a', href=re.compile(r'/marketplace/item/'))
        if not link:
            link = item if item.name == 'a' else None

        if not link:
            return None

        url = link.get('href', '')
        if url and not url.startswith('http'):
            url = f"https://www.facebook.com{url}"

        # Titel - Facebook versteckt oft in aria-label
        title = (
            link.get('aria-label') or
            link.get('title') or
            link.get_text(strip=True)
        )

        # Preis
        price = None
        price_elem = item.find(text=re.compile(r'€|\$'))
        if price_elem:
            price = _extract_price(price_elem)

        # Bild
        img = item.find('img')
        image_url = img.get('src') if img else None

        if not title or not url:
            return None

        return {
            'item_id': _generate_item_id(url),
            'title': title[:500],
            'price': price,
            'url': url,
            'image_url': image_url,
            'location': None,
            'postal_code': None,
            'condition': 'Gebraucht',
            'description': title,
            'published_date': datetime.now(),
            'source': 'facebook'
        }

    except Exception as e:
        logger.debug(f"HTML parse error: {e}")
        return None


def _extract_price(text: str) -> Optional[float]:
    """Extrahiert Preis"""
    if not text:
        return None

    patterns = [
        r'(\d+(?:\.\d{3})*(?:,\d{2})?)\s*€',
        r'€\s*(\d+(?:\.\d{3})*(?:,\d{2})?)',
        r'\$\s*(\d+(?:\.\d{3})*(?:\.\d{2})?)',
    ]

    for pattern in patterns:
        match = re.search(pattern, str(text))
        if match:
            price_str = match.group(1).replace('.', '').replace(',', '.')
            try:
                return float(price_str)
            except ValueError:
                continue

    return None


def _generate_item_id(url: str) -> str:
    """Generiert Item-ID"""
    match = re.search(r'/item/(\d+)', url)
    if match:
        return f"fb_{match.group(1)}"
    return f"fb_{hashlib.md5(url.encode()).hexdigest()[:12]}"


# ========================================
# ALTERNATIVE: FACEBOOK GRAPH API
# ========================================

def search_facebook_marketplace_api(
    query: str,
    access_token: str,
    limit: int = 50
) -> List[Dict]:
    """
    Facebook Graph API Methode (empfohlen für Production!)

    Setup:
    1. Gehe zu: https://developers.facebook.com/
    2. Erstelle eine App
    3. Aktiviere "Marketplace API"
    4. Generiere Access Token

    Args:
        query: Suchbegriff
        access_token: Facebook Access Token
        limit: Max Anzahl

    Returns:
        Liste von Items
    """
    try:
        url = "https://graph.facebook.com/v18.0/marketplace_search"

        params = {
            'access_token': access_token,
            'q': query,
            'limit': limit,
            'fields': 'id,name,price,description,location,image'
        }

        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()

        data = response.json()

        results = []
        for item in data.get('data', []):
            results.append({
                'item_id': f"fb_{item['id']}",
                'title': item.get('name', ''),
                'price': float(item.get('price', {}).get('amount', 0)),
                'url': f"https://www.facebook.com/marketplace/item/{item['id']}",
                'image_url': item.get('image', {}).get('url'),
                'location': item.get('location', {}).get('name'),
                'postal_code': None,
                'condition': 'Gebraucht',
                'description': item.get('description', '')[:500],
                'published_date': datetime.now(),
                'source': 'facebook'
            })

        return results

    except Exception as e:
        logger.error(f"Facebook API Error: {e}")
        return []


# ========================================
# TEST
# ========================================

def test_search():
    """Test-Funktion"""
    print("=" * 60)
    print("FACEBOOK MARKETPLACE SCRAPER TEST")
    print("=" * 60)
    print("\n[!]  WICHTIG:")
    print("Facebook hat starke Bot-Protection!")
    print("Diese Methode funktioniert nur begrenzt.")
    print("Für Production: Graph API verwenden!\n")

    results = search_facebook_marketplace(
        query="iPhone 13",
        price_max=600,
        location="Köln",
        limit=10
    )

    print(f"\n[+] Gefunden: {len(results)} Artikel\n")

    for i, item in enumerate(results[:5], 1):
        print(f"{i}. {item['title'][:60]}")
        if item['price']:
            print(f"   💰 {item['price']:.2f} EUR")
        print(f"   🔗 {item['url'][:80]}...")
        print()

    if len(results) == 0:
        print("\n[!]  Keine Ergebnisse - möglicherweise geblockt!")
        print("\nLÖSUNGEN:")
        print("1. Facebook Graph API nutzen (empfohlen)")
        print("2. Proxy-Service verwenden")
        print("3. Rate-Limiting implementieren")
        print("4. Facebook-Button im Frontend (User öffnet selbst)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_search()
