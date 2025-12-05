"""
Kleinanzeigen HTML Scraper
Da RSS nicht mehr verfügbar ist, scrapen wir direkt die HTML-Seite
"""
import requests
from bs4 import BeautifulSoup
import re
import hashlib
from datetime import datetime
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


def check_dependencies() -> bool:
    """Prüft ob alle benötigten Dependencies installiert sind"""
    try:
        import requests
        from bs4 import BeautifulSoup
        return True
    except ImportError as e:
        logger.error(f"Dependencies fehlen! Bitte installieren: pip install beautifulsoup4 requests")
        return False


def search_kleinanzeigen(
    query: str,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    location: Optional[str] = None,
    radius_km: Optional[int] = None,
    limit: int = 50
) -> List[Dict]:
    """
    Sucht auf eBay Kleinanzeigen via HTML Scraping

    Args:
        query: Suchbegriff
        price_min: Minimaler Preis
        price_max: Maximaler Preis
        location: PLZ oder Stadt
        radius_km: Umkreis (wird ignoriert, da nicht in URL umsetzbar)
        limit: Maximale Anzahl

    Returns:
        Liste von Dictionaries mit Artikel-Daten
    """
    try:
        url = _build_search_url(query, price_min, price_max, location)

        print(f"\n{'='*60}")
        print(f"🔍 KLEINANZEIGEN HTML SCRAPING")
        print(f"{'='*60}")
        print(f"URL: {url}")
        print(f"Query: {query}")
        print(f"{'='*60}\n")

        # Seite abrufen
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
        }

        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        print(f"✅ Status: {response.status_code}")

        # Parse HTML
        soup = BeautifulSoup(response.text, 'html.parser')

        # Finde Artikel-Container
        # Kleinanzeigen nutzt verschiedene Selektoren
        articles = soup.find_all('article', class_='aditem')

        # Fallback: Andere Selektoren probieren
        if not articles:
            articles = soup.select('div.ad-listitem')

        print(f"📦 Gefundene Artikel: {len(articles)}\n")

        results = []

        for i, article in enumerate(articles[:limit], 1):
            try:
                item = _parse_html_article(article, query)
                if item:
                    # Debug: Erste 3 Items anzeigen
                    if i <= 3:
                        print(f"✓ Item {i}:")
                        print(f"  Title: {item['title'][:60]}")
                        print(f"  Price: {item.get('price', 'N/A')}")
                        print(f"  URL: {item['url'][:80]}...")

                    # Preis-Filter anwenden
                    if price_min and item.get('price') and item['price'] < price_min:
                        continue
                    if price_max and item.get('price') and item['price'] > price_max:
                        continue

                    results.append(item)

            except Exception as e:
                logger.debug(f"Fehler bei Item {i}: {e}")
                continue

        print(f"\n✅ Gefunden: {len(results)} Kleinanzeigen\n")
        return results

    except Exception as e:
        logger.error(f"HTML Scraping Error: {e}")
        import traceback
        traceback.print_exc()
        return []


def _build_search_url(
    query: str,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    location: Optional[str] = None
) -> str:
    """Erstellt die Such-URL"""
    # Query URL-encodieren
    query_encoded = query.replace(' ', '+')

    # Basis-URL
    url = f"https://www.kleinanzeigen.de/s-suchanfrage.html?keywords={query_encoded}"

    # Preis-Filter
    if price_min or price_max:
        url += "&priceType=FIXED"
        if price_min:
            url += f"&minPrice={int(price_min)}"
        if price_max:
            url += f"&maxPrice={int(price_max)}"

    # Sortierung nach neuesten
    url += "&sortingField=SORTING_DATE"

    # Location (PLZ)
    if location:
        plz_match = re.search(r'\b(\d{5})\b', location)
        if plz_match:
            url += f"&locationStr={plz_match.group(1)}"

    return url


def _parse_html_article(article, query: str) -> Optional[Dict]:
    """Parst einen einzelnen Artikel aus dem HTML"""
    try:
        # Titel und URL
        title_elem = article.find('a', class_='ellipsis')
        if not title_elem:
            # Fallback: Andere Selektoren
            title_elem = article.find('a', attrs={'data-href': True})

        if not title_elem:
            return None

        title = title_elem.get_text(strip=True)
        url = title_elem.get('href', '')

        # URL vervollständigen
        if url and not url.startswith('http'):
            url = f"https://www.kleinanzeigen.de{url}"

        # Preis
        price = None
        price_elem = article.find('p', class_='aditem-main--middle--price-shipping--price')
        if not price_elem:
            # Fallback
            price_elem = article.select_one('.aditem-main--middle--price')

        if price_elem:
            price_text = price_elem.get_text(strip=True)
            price = _extract_price(price_text)

        # Bild
        image_url = None
        img_elem = article.find('img', class_='imagebox')
        if not img_elem:
            img_elem = article.find('img')

        if img_elem:
            # Probiere verschiedene Attribute
            image_url = (
                img_elem.get('src') or
                img_elem.get('data-src') or
                img_elem.get('data-imgsrc')
            )

        # Standort
        location = None
        location_elem = article.find('div', class_='aditem-main--top--left')
        if not location_elem:
            location_elem = article.select_one('.aditem-details')

        if location_elem:
            location_text = location_elem.get_text(strip=True)
            # Nur die ersten 100 Zeichen (enthält oft mehr Info)
            location = location_text[:100]

        # PLZ extrahieren
        postal_code = None
        if location:
            plz_match = re.search(r'\b(\d{5})\b', location)
            postal_code = plz_match.group(1) if plz_match else None

        # Item-ID generieren
        item_id = _generate_item_id(url)

        # Zustand
        condition = 'Gebraucht'
        if any(word in title.upper() for word in ['NEU', 'OVP', 'UNBENUTZT']):
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
            'description': title,
            'published_date': datetime.now(),
            'source': 'kleinanzeigen'
        }

    except Exception as e:
        logger.debug(f"Parse error: {e}")
        return None


def _extract_price(text: str) -> Optional[float]:
    """Extrahiert Preis aus Text"""
    if not text:
        return None

    # VB, Tausch, etc.
    if any(word in text.upper() for word in ['VB', 'TAUSCH', 'GESCHENK']):
        # Versuche trotzdem Preis zu finden
        pass

    # Preis-Pattern: "123 €", "1.234 €", "123,50 €"
    match = re.search(r'(\d+(?:\.\d{3})*(?:,\d{2})?)\s*€', text)
    if match:
        price_str = match.group(1).replace('.', '').replace(',', '.')
        try:
            return float(price_str)
        except ValueError:
            return None

    return None


def _generate_item_id(url: str) -> str:
    """Generiert eindeutige Item-ID"""
    match = re.search(r'/(\d+)-', url)
    if match:
        return f"ka_{match.group(1)}"
    return f"ka_{hashlib.md5(url.encode()).hexdigest()[:12]}"


# ========================================
# TEST-FUNKTION
# ========================================

def test_search():
    """Test-Funktion"""
    print("=" * 60)
    print("KLEINANZEIGEN HTML SCRAPER TEST")
    print("=" * 60)

    if not check_dependencies():
        print("❌ Dependencies fehlen!")
        return

    print("✅ Dependencies OK\n")

    results = search_kleinanzeigen(
        query="iPhone 12",
        price_min=200,
        price_max=500,
        limit=10
    )

    print(f"\n📦 Gefunden: {len(results)} Artikel\n")

    for i, item in enumerate(results[:5], 1):
        print(f"{i}. {item['title'][:60]}")
        print(f"   💰 {item['price']:.2f} EUR" if item['price'] else "   💰 Preis auf Anfrage")
        print(f"   📍 {item['location']}")
        print(f"   🔗 {item['url'][:80]}...")
        print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_search()
