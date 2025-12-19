"""
Quoka Scraper - ROBUSTE VERSION (Dez 2024)
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

# Importiere Universal Helper (falls vorhanden)
try:
    from services.robust_scraper_helper import (
        find_items_universal,
        parse_item_universal
    )
    USE_UNIVERSAL = True
except ImportError:
    logger.warning("robust_scraper_helper nicht gefunden - nutze Fallback")
    USE_UNIVERSAL = False


def search_quoka(
    query: str,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    location: Optional[str] = None,
    radius_km: Optional[int] = None,
    limit: int = 50
) -> List[Dict]:
    """
    Sucht auf Quoka - ROBUSTE VERSION
    """
    try:
        url = _build_search_url(query, price_min, price_max, location, radius_km)

        print(f"\n{'='*60}")
        print(f"[*] QUOKA HTML SCRAPING (ROBUST)")
        print(f"{'='*60}")
        print(f"URL: {url}")
        print(f"Query: {query}")
        print(f"{'='*60}\n")

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8',
            'Referer': 'https://www.quoka.de/',
        }

        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        print(f"[OK] Status: {response.status_code}")

        soup = BeautifulSoup(response.text, 'html.parser')

        # ROBUSTE METHODE: Universal Helper
        if USE_UNIVERSAL:
            articles = find_items_universal(soup, 'quoka')
        else:
            # FALLBACK: Mehrere Strategien
            articles = _find_items_fallback(soup)

        print(f"[+] Gefundene Artikel: {len(articles)}\n")

        results = []
        for i, article in enumerate(articles[:limit], 1):
            try:
                # ROBUSTES PARSING
                if USE_UNIVERSAL:
                    item = parse_item_universal(article, 'quoka', 'https://www.quoka.de')
                else:
                    item = _parse_html_article_fallback(article, query)

                if item:
                    # [WICHTIG] Filter Navigation/Dummy-Items HIER direkt in Quoka
                    if _is_invalid_quoka_listing(item):
                        continue

                    # Debug
                    if i <= 3:
                        print(f"[+] Item {i}:")
                        print(f"  Title: {item['title'][:60]}")
                        print(f"  Price: {item.get('price', 'N/A')}")
                        print(f"  URL: {item['url'][:80]}...")

                    # Preis-Filter
                    if price_min and item.get('price') and item['price'] < price_min:
                        continue
                    if price_max and item.get('price') and item['price'] > price_max:
                        continue

                    results.append(item)

            except Exception as e:
                logger.debug(f"Fehler bei Item {i}: {e}")
                continue

        print(f"\n[OK] Gefunden: {len(results)} Quoka-Anzeigen\n")
        return results

    except Exception as e:
        logger.error(f"Quoka Scraping Error: {e}")
        import traceback
        traceback.print_exc()
        return []


def _is_invalid_quoka_listing(item: Dict) -> bool:
    """
    Filtert Navigation/Dummy-Items und Job-Listings in Quoka
    Returns True wenn Item ungueltig ist (gefiltert werden soll)
    """
    title = (item.get('title') or '').lower().strip()
    
    # Navigation-Strings die Quoka oft returned
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
    
    if len(title) < 40:
        job_phrases = ['job gesucht', 'stelle gesucht', 'arbeit gesucht', 'minijob', 'nebenjob', 'ich suche', 'suche stelle', 'suche arbeit', 'stellengesuche', 'hilfe bei', 'komplettservice']
        for phrase in job_phrases:
            if phrase in title:
                return True
    
    return False


def _build_search_url(
    query: str,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    location: Optional[str] = None,
    radius_km: Optional[int] = None
) -> str:
    """Erstellt Quoka Such-URL"""
    query_encoded = query.replace(' ', '+')
    url = f"https://www.quoka.de/suche/?q={query_encoded}"

    if price_min:
        url += f"&price_from={int(price_min)}"
    if price_max:
        url += f"&price_to={int(price_max)}"

    if location:
        plz_match = re.search(r'\b(\d{5})\b', location)
        if plz_match:
            url += f"&plz={plz_match.group(1)}"
        else:
            location_encoded = location.replace(' ', '+')
            url += f"&ort={location_encoded}"

    if radius_km:
        url += f"&radius={radius_km}"

    url += "&sort=date_desc"

    return url


def _find_items_fallback(soup: BeautifulSoup) -> List:
    """
    FALLBACK: Findet Items ohne Universal Helper
    Probiert ALLE bekannten Strategien für Quoka
    """
    # Strategie 1: Neue Struktur (Dez 2024)
    articles = soup.find_all('div', class_='q-card')
    if articles:
        logger.info(f"Found via q-card: {len(articles)}")
        return articles

    # Strategie 2: Alte Struktur
    articles = soup.find_all('div', class_='q-adlist__item')
    if articles:
        logger.info(f"Found via q-adlist__item: {len(articles)}")
        return articles

    # Strategie 3: Article Tags
    articles = soup.find_all('article')
    if len(articles) > 2:
        logger.info(f"Found via article: {len(articles)}")
        return articles

    # Strategie 4: Links zu Anzeigen
    articles = soup.find_all('a', href=re.compile(r'/anzeigen?/\d+'))
    if articles:
        logger.info(f"Found via link pattern: {len(articles)}")
        return articles

    # Strategie 5: Divs mit "item" oder "ad" in class
    articles = soup.find_all('div', class_=re.compile(r'(item|ad|listing|card)', re.I))
    if len(articles) > 2:
        logger.info(f"Found via generic class: {len(articles)}")
        return articles

    logger.warning("No items found with any strategy!")
    return []


def _parse_html_article_fallback(article, query: str) -> Optional[Dict]:
    """
    FALLBACK: Parst Item ohne Universal Helper
    SEHR ROBUST - probiert ALLE Möglichkeiten
    """
    try:
        # === TITEL FINDEN ===
        title = None

        # Strategie 1: Link-Attribute
        if article.name == 'a':
            title = article.get('title') or article.get('aria-label')

        # Strategie 2: Suche Link
        if not title:
            link = article.find('a', href=True)
            if link:
                title = link.get('title') or link.get('aria-label') or link.get_text(strip=True)

        # Strategie 3: Heading-Tags
        if not title:
            for tag in ['h1', 'h2', 'h3', 'h4']:
                heading = article.find(tag)
                if heading:
                    title = heading.get_text(strip=True)
                    break

        # Strategie 4: Direct text
        if not title:
            title = article.get_text(strip=True)

        if not title or len(title) < 5:
            return None

        # === URL FINDEN ===
        url = ''
        if article.name == 'a':
            url = article.get('href', '')
        else:
            link = article.find('a', href=True)
            if link:
                url = link.get('href', '')

        if not url:
            return None

        # URL vervollständigen
        if url.startswith('//'):
            url = 'https:' + url
        elif url.startswith('/'):
            url = f"https://www.quoka.de{url}"
        elif not url.startswith('http'):
            url = f"https://www.quoka.de/{url}"

        # === PREIS FINDEN ===
        price = None
        price_text = article.get_text()

        patterns = [
            r'(\d+(?:\.\d{3})*(?:,\d{2})?)\s*€',
            r'€\s*(\d+(?:\.\d{3})*(?:,\d{2})?)',
            r'(\d+(?:,\d{2})?)\s*EUR',
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

        # === BILD FINDEN ===
        image_url = None
        img = article.find('img')
        if img:
            image_url = (
                img.get('src') or
                img.get('data-src') or
                img.get('data-lazy-src')
            )
            if image_url and image_url.startswith('//'):
                image_url = 'https:' + image_url

        # === LOCATION FINDEN ===
        location = None
        location_elem = article.find(['span', 'div'], class_=re.compile(r'(location|ort|city)', re.I))
        if location_elem:
            location = location_elem.get_text(strip=True)

        # Oder PLZ im Text suchen
        if not location:
            plz_match = re.search(r'\b(\d{5})\s+([A-ZÄÖÜ][a-zäöüß]+)', price_text)
            if plz_match:
                location = f"{plz_match.group(1)} {plz_match.group(2)}"

        postal_code = None
        if location:
            plz_match = re.search(r'\b(\d{5})\b', location)
            if plz_match:
                postal_code = plz_match.group(1)

        # === ITEM ERSTELLEN ===
        item_id = f"qk_{hashlib.md5(url.encode()).hexdigest()[:12]}"

        condition = 'Gebraucht'
        if any(word in title.upper() for word in ['NEU', 'OVP', 'NEW', 'UNBENUTZT']):
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
            'source': 'quoka'
        }

    except Exception as e:
        logger.debug(f"Parse error: {e}")
        return None


# ========================================
# TEST
# ========================================

def test_search():
    """Test Quoka"""
    print("=" * 60)
    print("QUOKA ROBUST SCRAPER TEST")
    print("=" * 60)

    results = search_quoka(
        query="iPhone 13",
        price_max=600,
        limit=10
    )

    print(f"\n[+] Gefunden: {len(results)} Artikel\n")

    for i, item in enumerate(results[:5], 1):
        print(f"{i}. {item['title'][:60]}")
        if item['price']:
            print(f"   Preis: {item['price']:.2f} EUR")
        print(f"   Link: {item['url'][:80]}...")
        print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_search()
