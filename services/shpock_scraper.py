"""
Shpock Scraper - ROBUSTE VERSION (Dez 2024)
Nutzt Universal Helper für maximale Stabilität
"""
import requests
from bs4 import BeautifulSoup
import re
import hashlib
from datetime import datetime
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

try:
    from services.robust_scraper_helper import (
        find_items_universal,
        parse_item_universal
    )
    USE_UNIVERSAL = True
except ImportError:
    logger.warning("robust_scraper_helper nicht gefunden - nutze Fallback")
    USE_UNIVERSAL = False


def search_shpock(
    query: str,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    location: Optional[str] = None,
    radius_km: Optional[int] = None,
    limit: int = 50
) -> List[Dict]:
    """Sucht auf Shpock - ROBUSTE VERSION"""
    try:
        url = _build_search_url(query, price_min, price_max, location)

        print(f"\n{'='*60}")
        print(f"[*] SHPOCK HTML SCRAPING (ROBUST)")
        print(f"{'='*60}")
        print(f"URL: {url}")
        print(f"Query: {query}")
        print(f"{'='*60}\n")

        # Mobile User-Agent (Shpock ist mobile-first)
        headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8',
            'Referer': 'https://www.shpock.com/',
        }

        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        print(f"[OK] Status: {response.status_code}")

        soup = BeautifulSoup(response.text, 'html.parser')

        # ROBUST: Universal Helper
        if USE_UNIVERSAL:
            articles = find_items_universal(soup, 'shpock')
        else:
            articles = _find_items_fallback(soup)

        print(f"[+] Gefundene Artikel: {len(articles)}\n")

        results = []
        for i, article in enumerate(articles[:limit], 1):
            try:
                if USE_UNIVERSAL:
                    item = parse_item_universal(article, 'shpock', 'https://www.shpock.com')
                else:
                    item = _parse_html_article_fallback(article, query)

                if item:
                    # [WICHTIG] Filter Navigation/Dummy-Items HIER direkt in Shpock
                    if _is_invalid_shpock_listing(item):
                        continue

                    if i <= 3:
                        print(f"[+] Item {i}:")
                        print(f"  Title: {item['title'][:60]}")
                        print(f"  Price: {item.get('price', 'N/A')}")

                    # Preis-Filter
                    if price_min and item.get('price') and item['price'] < price_min:
                        continue
                    if price_max and item.get('price') and item['price'] > price_max:
                        continue

                    results.append(item)

            except Exception as e:
                logger.debug(f"Fehler bei Item {i}: {e}")
                continue

        print(f"\n[OK] Gefunden: {len(results)} Shpock-Anzeigen\n")
        return results

    except Exception as e:
        logger.error(f"Shpock Scraping Error: {e}")
        import traceback
        traceback.print_exc()
        return []


def _is_invalid_shpock_listing(item: Dict) -> bool:
    """
    Filtert Navigation/Dummy-Items in Shpock
    Returns True wenn Item ungueltig ist (gefiltert werden soll)
    """
    title = (item.get('title') or '').lower().strip()
    
    # Navigation-Strings die Shpock oft returned
    invalid_exact = [
        'zuhause',
        'startseite',
        'home',
        'finde alles',
        'was du suchst',
        'durchsuchen',
        'entdecken',
        'kategorien',
        'favoriten',
        'merkliste',
        'nachrichten',
        'mein konto',
        'einstellungen',
        'verkaufen',
        'jetzt verkaufen',
        'anzeige aufgeben',
        'meine anzeigen',
        'hilfe',
        'about',
        'kontakt',
    ]
    
    # Titel zu kurz oder leer
    if not title or len(title) < 5:
        return True
    
    # Exakte Matches
    if title in invalid_exact:
        return True
    
    # Substring-Matches (nur fuer kurze Titel)
    if len(title) < 40:
        for pattern in invalid_exact:
            if pattern in title:
                return True
    
    return False


def _build_search_url(
    query: str,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    location: Optional[str] = None
) -> str:
    """Erstellt Shpock URL"""
    query_encoded = query.replace(' ', '%20')
    url = f"https://www.shpock.com/de-de/search?q={query_encoded}"

    if price_min:
        url += f"&minPrice={int(price_min)}"
    if price_max:
        url += f"&maxPrice={int(price_max)}"

    if location:
        location_encoded = location.replace(' ', '%20')
        url += f"&location={location_encoded}"

    url += "&sort=date"

    return url


def _find_items_fallback(soup: BeautifulSoup) -> List:
    """FALLBACK für Shpock"""
    # Strategie 1: Article Tags
    articles = soup.find_all('article')
    if len(articles) > 2:
        logger.info(f"Found via article: {len(articles)}")
        return articles

    # Strategie 2: Item Links
    articles = soup.find_all('a', href=re.compile(r'/items/\d+'))
    if articles:
        logger.info(f"Found via item links: {len(articles)}")
        return articles

    # Strategie 3: Divs mit data-testid
    articles = soup.find_all('div', attrs={'data-testid': re.compile(r'(item|listing|card)')})
    if articles:
        logger.info(f"Found via testid: {len(articles)}")
        return articles

    # Strategie 4: Generic
    articles = soup.find_all('div', class_=re.compile(r'(item|listing|card)', re.I))
    if len(articles) > 2:
        logger.info(f"Found via generic: {len(articles)}")
        return articles

    logger.warning("No Shpock items found!")
    return []


def _parse_html_article_fallback(article, query: str) -> Optional[Dict]:
    """FALLBACK Parser für Shpock"""
    try:
        # TITEL
        title = None
        url = ''

        if article.name == 'a':
            url = article.get('href', '')
            title = article.get('title') or article.get('aria-label') or article.get_text(strip=True)
        else:
            link = article.find('a', href=True)
            if link:
                url = link.get('href', '')
                title = link.get('title') or link.get('aria-label') or link.get_text(strip=True)

            if not title:
                for tag in ['h2', 'h3', 'h4']:
                    heading = article.find(tag)
                    if heading:
                        title = heading.get_text(strip=True)
                        break

        if not title or not url:
            return None

        # URL vervollständigen
        if url.startswith('/'):
            url = f"https://www.shpock.com{url}"
        elif not url.startswith('http'):
            return None

        # PREIS
        price = None
        price_text = article.get_text()

        patterns = [
            r'(\d+(?:\.\d{3})*(?:,\d{2})?)\s*€',
            r'€\s*(\d+(?:\.\d{3})*(?:,\d{2})?)',
        ]

        for pattern in patterns:
            match = re.search(pattern, price_text)
            if match:
                try:
                    price_str = match.group(1).replace('.', '').replace(',', '.')
                    price = float(price_str)
                    if 0 < price < 999999:
                        break
                except ValueError:
                    continue

        # Kostenlos Check
        if any(word in price_text.upper() for word in ['KOSTENLOS', 'GRATIS', 'FREE']):
            price = 0.0

        # BILD
        image_url = None
        img = article.find('img')
        if img:
            image_url = (
                img.get('src') or
                img.get('data-src') or
                img.get('srcset', '').split(',')[0].split(' ')[0]
            )
            if image_url and image_url.startswith('//'):
                image_url = 'https:' + image_url

        # LOCATION
        location = None
        location_elem = article.find(['span', 'div'], class_=re.compile(r'location', re.I))
        if location_elem:
            location = location_elem.get_text(strip=True)

        postal_code = None
        if location:
            plz_match = re.search(r'\b(\d{5})\b', location)
            if plz_match:
                postal_code = plz_match.group(1)

        # ITEM
        item_id = f"sh_{hashlib.md5(url.encode()).hexdigest()[:12]}"

        condition = 'Gebraucht'
        if any(word in title.upper() for word in ['NEU', 'OVP', 'NEW']):
            condition = 'Neu'

        return {
            'item_id': item_id,
            'title': title[:500],
            'price': price,
            'url': url,
            'image_url': image_url,
            'location': location,
            'postal_code': postal_code,
            'condition': condition,
            'description': title[:500],
            'published_date': datetime.now(),
            'source': 'shpock'
        }

    except Exception as e:
        logger.debug(f"Parse error: {e}")
        return None


def test_search():
    """Test Shpock"""
    print("=" * 60)
    print("SHPOCK ROBUST SCRAPER TEST")
    print("=" * 60)

    results = search_shpock(
        query="iPhone 13",
        price_max=600,
        limit=10
    )

    print(f"\n[+] Gefunden: {len(results)} Artikel\n")

    for i, item in enumerate(results[:5], 1):
        print(f"{i}. {item['title'][:60]}")
        if item['price'] is not None:
            print(f"   💰 {item['price']:.2f} EUR")
        print(f"   🔗 {item['url'][:80]}...")
        print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_search()
