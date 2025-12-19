"""
🛡️ ROBUST SCRAPER HELPER
Universal Helper-Funktionen die mit JEDEM Portal funktionieren
"""
import re
from typing import Optional, Dict, List
from bs4 import BeautifulSoup, Tag
import logging

log = logging.getLogger(__name__)


def find_items_universal(soup: BeautifulSoup, portal_name: str) -> List[Tag]:
    """
    [*] Findet Items auf JEDER Website - Universal!

    Probiert verschiedene Strategien:
    1. Bekannte Selektoren für das Portal
    2. Generische Artikel-Container
    3. Links zu Produktseiten
    4. Strukturelle Patterns

    Args:
        soup: BeautifulSoup object
        portal_name: Name des Portals (für spezifische Patterns)

    Returns:
        Liste von Tags (Artikel-Container)
    """
    items = []

    # Strategie 1: Portal-spezifische Selektoren
    portal_selectors = {
        'quoka': [
            ('div', {'class': 'q-card'}),
            ('div', {'class': 'q-adlist__item'}),
            ('article', {'class': 'marketplace-item'}),
        ],
        'shpock': [
            ('article', {}),
            ('div', {'class': re.compile(r'item|listing|card')}),
        ],
        'marktde': [
            ('article', {}),
            ('div', {'class': re.compile(r'ad[-_]item')}),
        ]
    }

    if portal_name in portal_selectors:
        for tag_name, attrs in portal_selectors[portal_name]:
            items = soup.find_all(tag_name, attrs)
            if items:
                log.debug(f"Found {len(items)} items with {tag_name} {attrs}")
                return items

    # Strategie 2: Generische Artikel-Container
    generic_selectors = [
        ('article', {}),
        ('div', {'class': re.compile(r'(item|listing|ad|card|result)', re.I)}),
        ('li', {'class': re.compile(r'(item|listing|ad|card|result)', re.I)}),
    ]

    for tag_name, attrs in generic_selectors:
        items = soup.find_all(tag_name, attrs)
        if len(items) > 3:  # Mindestens ein paar Items
            log.debug(f"Found {len(items)} items with generic {tag_name}")
            return items

    # Strategie 3: Links zu Produktseiten (sehr robust!)
    link_patterns = {
        'quoka': r'/anzeigen?/\d+',
        'shpock': r'/items/\d+',
        'marktde': r'/\d+-[\w-]+',
    }

    pattern = link_patterns.get(portal_name, r'/(item|ad|listing|anzeige)/\d+')
    items = soup.find_all('a', href=re.compile(pattern))

    if items:
        log.debug(f"Found {len(items)} items via link pattern")
        return items

    # Strategie 4: Alle Links mit Preisen in der Nähe (last resort)
    all_links = soup.find_all('a', href=True)
    items_with_price = []

    for link in all_links:
        # Check ob in der Nähe ein Preis ist
        parent = link.parent
        if parent and ('€' in parent.get_text() or 'EUR' in parent.get_text()):
            items_with_price.append(link)

    if items_with_price:
        log.debug(f"Found {len(items_with_price)} items via price proximity")
        return items_with_price

    log.warning(f"No items found for {portal_name}")
    return []


def extract_title_universal(element: Tag) -> Optional[str]:
    """
    📝 Extrahiert Titel aus JEDEM Element - Universal!

    Probiert mehrere Quellen:
    - HTML-Attribute (title, aria-label)
    - Text-Content
    - Child-Elemente (h1-h6, span, etc.)
    """
    if not element:
        return None

    # 1. Attribute
    for attr in ['title', 'aria-label', 'data-title', 'alt']:
        value = element.get(attr)
        if value and len(value) > 5:
            return value.strip()

    # 2. Heading-Tags
    for tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
        heading = element.find(tag)
        if heading:
            text = heading.get_text(strip=True)
            if len(text) > 5:
                return text

    # 3. Spans/Divs mit class*="title"
    title_elem = element.find(['span', 'div'], class_=re.compile(r'title', re.I))
    if title_elem:
        text = title_elem.get_text(strip=True)
        if len(text) > 5:
            return text

    # 4. Direct text (aber nicht zu viel)
    text = element.get_text(strip=True)
    if 5 < len(text) < 200:
        return text

    return None


def extract_url_universal(element: Tag, base_url: str = '') -> Optional[str]:
    """
    🔗 Extrahiert URL aus JEDEM Element - Universal!
    """
    if not element:
        return None

    # 1. Falls element selbst ein Link
    if element.name == 'a':
        url = element.get('href', '')
    else:
        # 2. Suche Link im Element
        link = element.find('a', href=True)
        url = link.get('href', '') if link else ''

    if not url:
        return None

    # 3. URL vervollständigen
    if url.startswith('//'):
        url = 'https:' + url
    elif url.startswith('/'):
        url = base_url + url
    elif not url.startswith('http'):
        return None

    return url


def extract_price_universal(element: Tag, text: str = None) -> Optional[float]:
    """
    💰 Extrahiert Preis aus JEDEM Element - Universal!

    Findet Preise in verschiedenen Formaten:
    - 123 €
    - € 123
    - 123,50 EUR
    - 1.234,50 €
    """
    search_text = text or element.get_text() if element else ''

    if not search_text:
        return None

    # Pattern für deutsche Preise
    patterns = [
        r'(\d+(?:\.\d{3})*(?:,\d{2})?)\s*€',        # 1.234,50 €
        r'€\s*(\d+(?:\.\d{3})*(?:,\d{2})?)',        # € 1.234,50
        r'(\d+(?:\.\d{3})*(?:,\d{2})?)\s*EUR',      # 1.234,50 EUR
        r'EUR\s*(\d+(?:\.\d{3})*(?:,\d{2})?)',      # EUR 1.234,50
        r'(\d+(?:,\d{2})?)\s*€',                     # 123,50 €
        r'€\s*(\d+(?:,\d{2})?)',                     # € 123,50
    ]

    for pattern in patterns:
        match = re.search(pattern, search_text)
        if match:
            price_str = match.group(1)
            # Konvertiere: 1.234,50 -> 1234.50
            price_str = price_str.replace('.', '').replace(',', '.')
            try:
                price = float(price_str)
                # Plausibilitätscheck
                if 0 < price < 999999:
                    return price
            except ValueError:
                continue

    return None


def extract_image_universal(element: Tag) -> Optional[str]:
    """
    🖼️ Extrahiert Bild-URL aus JEDEM Element - Universal!
    """
    if not element:
        return None

    img = element.find('img')
    if not img:
        return None

    # Probiere verschiedene Attribute
    for attr in ['src', 'data-src', 'data-lazy-src', 'data-original', 'srcset']:
        url = img.get(attr)
        if url:
            # Bei srcset: nehme erste URL
            if ',' in str(url):
                url = url.split(',')[0].split(' ')[0]

            # Vollständige URL
            if url.startswith('//'):
                return 'https:' + url
            elif url.startswith('/'):
                return None  # Braucht base_url
            elif url.startswith('http'):
                return url

    return None


def extract_location_universal(element: Tag) -> Optional[str]:
    """
    📍 Extrahiert Standort aus JEDEM Element - Universal!
    """
    if not element:
        return None

    # 1. Suche nach location/ort/standort-Klassen
    location_elem = element.find(['span', 'div', 'p'], class_=re.compile(r'(location|ort|standort|address)', re.I))
    if location_elem:
        return location_elem.get_text(strip=True)

    # 2. Suche nach PLZ-Pattern im Text
    text = element.get_text()
    plz_match = re.search(r'\b(\d{5})\s+([A-ZÄÖÜ][a-zäöüß]+)', text)
    if plz_match:
        return f"{plz_match.group(1)} {plz_match.group(2)}"

    return None


def parse_item_universal(element: Tag, source: str, base_url: str = '') -> Optional[Dict]:
    """
    🎯 Parst ein Item komplett - Universal für ALLE Portale!

    Args:
        element: BeautifulSoup Tag (Artikel-Container)
        source: Portal-Name (quoka, shpock, marktde, etc.)
        base_url: Basis-URL des Portals

    Returns:
        Dict mit Item-Daten oder None
    """
    try:
        # Extrahiere alle Felder
        title = extract_title_universal(element)
        url = extract_url_universal(element, base_url)
        price = extract_price_universal(element)
        image_url = extract_image_universal(element)
        location = extract_location_universal(element)

        # Validierung
        if not title or not url:
            return None

        # PLZ extrahieren
        postal_code = None
        if location:
            plz_match = re.search(r'\b(\d{5})\b', location)
            if plz_match:
                postal_code = plz_match.group(1)

        # Zustand
        condition = 'Gebraucht'
        if any(word in title.upper() for word in ['NEU', 'OVP', 'NEW', 'UNBENUTZT']):
            condition = 'Neu'

        # Item-ID
        from datetime import datetime
        import hashlib
        item_id = f"{source}_{hashlib.md5(url.encode()).hexdigest()[:12]}"

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
            'source': source
        }

    except Exception as e:
        log.debug(f"Parse error: {e}")
        return None


# ===================================================================
# USAGE EXAMPLE
# ===================================================================

def scrape_portal_robust(url: str, portal_name: str, base_url: str) -> List[Dict]:
    """
    Beispiel: Robustes Scraping für JEDES Portal
    """
    import requests

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')

        # 1. Finde Items (universal!)
        elements = find_items_universal(soup, portal_name)

        # 2. Parse Items (universal!)
        items = []
        for elem in elements:
            item = parse_item_universal(elem, portal_name, base_url)
            if item:
                items.append(item)

        return items

    except Exception as e:
        log.error(f"Scraping error: {e}")
        return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    # Test
    print("🛡️ Testing Universal Scraper Helper...")

    # Test mit Quoka
    results = scrape_portal_robust(
        url="https://www.quoka.de/suche/?q=iPhone",
        portal_name="quoka",
        base_url="https://www.quoka.de"
    )

    print(f"Found: {len(results)} items")
    for item in results[:3]:
        print(f"  - {item['title'][:50]}")
