import feedparser
import psycopg2
from psycopg2.extras import RealDictCursor
import time
import hashlib
from datetime import datetime
import urllib.parse
import logging
import re
import requests
from typing import Optional, List, Dict

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class KleinanzeigenScraper:
    def __init__(self, database_url):
        self.database_url = database_url
        self.base_url = "https://www.kleinanzeigen.de"

    def get_db_connection(self):
        """Erstellt eine Datenbankverbindung"""
        return psycopg2.connect(self.database_url)

    def get_active_searches(self) -> List[Dict]:
        """Holt alle aktiven Kleinanzeigen-Suchanfragen aus der Datenbank"""
        conn = self.get_db_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        sa.id,
                        sa.query,
                        sa.price_min,
                        sa.price_max,
                        sa.location,
                        sa.radius_km,
                        sa.condition,
                        sa.user_id,
                        u.telegram_chat_id,
                        u.telegram_enabled
                    FROM search_agents sa
                    JOIN users u ON sa.user_id = u.id
                    WHERE sa.source = 'kleinanzeigen'
                    AND sa.active = true
                """)
                return cur.fetchall()
        finally:
            conn.close()

    def update_last_checked(self, search_agent_id: int):
        """Aktualisiert den Zeitpunkt der letzten Prüfung"""
        conn = self.get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE search_agents
                    SET last_checked = %s
                    WHERE id = %s
                """, (datetime.now(), search_agent_id))
                conn.commit()
        finally:
            conn.close()

    def generate_item_id(self, url: str) -> str:
        """Generiert eine eindeutige ID aus der URL"""
        # Extrahiere die Kleinanzeigen-ID aus der URL
        match = re.search(r'/(\d+)-', url)
        if match:
            return f"ka_{match.group(1)}"
        return hashlib.md5(url.encode()).hexdigest()

    def parse_price(self, text: str) -> Optional[float]:
        """Extrahiert Preis aus Text"""
        if not text:
            return None

        # Sucht nach Preisangaben wie "123 €", "1.234,56 €", "VB"
        if "VB" in text.upper() or "VERHANDLUNGSBASIS" in text.upper():
            # Bei VB den Preis trotzdem versuchen zu extrahieren
            pass

        match = re.search(r'(\d+(?:\.\d{3})*(?:,\d{2})?)\s*€', text)
        if match:
            price_str = match.group(1).replace('.', '').replace(',', '.')
            try:
                return float(price_str)
            except ValueError:
                return None
        return None

    def extract_postal_code(self, location: str) -> Optional[str]:
        """Extrahiert PLZ aus Standort-Text"""
        if not location:
            return None
        match = re.search(r'\b(\d{5})\b', location)
        return match.group(1) if match else None

    def build_rss_url(self, search: Dict) -> str:
        """Erstellt RSS-URL mit Filtern"""
        query = search['query'].replace(' ', '-')
        encoded_query = urllib.parse.quote(query)

        # Basis-URL
        url = f"{self.base_url}/s-{encoded_query}/k0"

        params = {'format': 'rss'}

        # Preis-Filter
        if search.get('price_min'):
            params['price_min'] = int(search['price_min'])
        if search.get('price_max'):
            params['price_max'] = int(search['price_max'])

        # Sortierung nach neuesten zuerst
        params['sort'] = 'CREATION_DATE_DESC'

        return f"{url}?{urllib.parse.urlencode(params)}"

    def fetch_rss_feed(self, search: Dict) -> List:
        """Ruft RSS-Feed ab"""
        rss_url = self.build_rss_url(search)
        logger.info(f"Fetching RSS: {rss_url}")

        try:
            # User-Agent setzen um nicht blockiert zu werden
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }

            feed = feedparser.parse(rss_url, request_headers=headers)

            if feed.bozo:
                logger.warning(f"Feed-Parsing-Warnung: {feed.bozo_exception}")

            return feed.entries
        except Exception as e:
            logger.error(f"Fehler beim Abrufen des RSS-Feeds: {e}")
            return []

    def item_exists(self, item_id: str) -> bool:
        """Prüft ob ein Item bereits in der Datenbank existiert"""
        conn = self.get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 1 FROM found_items
                    WHERE item_id = %s AND source = 'kleinanzeigen'
                    LIMIT 1
                """, (item_id,))
                return cur.fetchone() is not None
        finally:
            conn.close()

    def matches_filters(self, item_data: Dict, search: Dict) -> bool:
        """Prüft ob Item den Such-Filtern entspricht"""
        # Preis-Filter
        if search.get('price_min') and item_data.get('price'):
            if item_data['price'] < search['price_min']:
                return False

        if search.get('price_max') and item_data.get('price'):
            if item_data['price'] > search['price_max']:
                return False

        # Weitere Filter können hier ergänzt werden
        # z.B. PLZ-Radius-Berechnung

        return True

    def save_item(self, item_data: Dict, search_agent_id: int) -> bool:
        """Speichert ein Item in der Datenbank"""
        conn = self.get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO found_items (
                        item_id, search_agent_id, title, price, currency,
                        url, image_url, location, postal_code, condition,
                        source, description, published_date, is_new
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (item_id, source) DO NOTHING
                    RETURNING id
                """, (
                    item_data['item_id'],
                    search_agent_id,
                    item_data['title'],
                    item_data['price'],
                    'EUR',
                    item_data['url'],
                    item_data['image_url'],
                    item_data['location'],
                    item_data['postal_code'],
                    item_data['condition'],
                    'kleinanzeigen',
                    item_data['description'],
                    item_data['published_date'],
                    True  # is_new
                ))

                result = cur.fetchone()
                conn.commit()

                if result:
                    logger.info(f"✓ Neues Item gespeichert: {item_data['title'][:50]}")
                    return True
                return False

        except Exception as e:
            logger.error(f"Fehler beim Speichern: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def process_feed_entry(self, entry: Dict, search: Dict) -> bool:
        """Verarbeitet einen RSS-Feed-Eintrag"""
        try:
            url = entry.get('link', '')
            if not url:
                return False

            item_id = self.generate_item_id(url)

            # Prüfe ob bereits vorhanden
            if self.item_exists(item_id):
                return False

            # Extrahiere Daten
            title = entry.get('title', '').strip()
            description = entry.get('summary', '').strip()

            # Preis extrahieren
            price = None
            price_text = title + ' ' + description
            price = self.parse_price(price_text)

            # Standort extrahieren
            location = None
            location_match = re.search(r'(\d{5}\s+[^<\n|]+)', description)
            if location_match:
                location = location_match.group(1).strip()[:255]

            postal_code = self.extract_postal_code(location) if location else None

            # Bild-URL
            image_url = None
            if hasattr(entry, 'enclosures') and entry.enclosures:
                image_url = entry.enclosures[0].get('href')
            elif hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
                image_url = entry.media_thumbnail[0].get('url')

            # Datum
            published_date = None
            if 'published_parsed' in entry and entry.published_parsed:
                published_date = datetime(*entry.published_parsed[:6])

            # Zustand (meist gebraucht bei Kleinanzeigen)
            condition = 'Gebraucht'
            if any(word in title.upper() for word in ['NEU', 'UNBENUTZT', 'OVP']):
                condition = 'Neu'

            item_data = {
                'item_id': item_id,
                'title': title[:500],
                'price': price,
                'url': url,
                'image_url': image_url,
                'location': location,
                'postal_code': postal_code,
                'condition': condition,
                'published_date': published_date,
                'description': description[:2000]
            }

            # Filter anwenden
            if not self.matches_filters(item_data, search):
                logger.debug(f"Item gefiltert (außerhalb der Kriterien): {title[:50]}")
                return False

            return self.save_item(item_data, search['id'])

        except Exception as e:
            logger.error(f"Fehler beim Verarbeiten des Eintrags: {e}")
            return False

    def run_scrape_cycle(self):
        """Führt einen kompletten Scraping-Durchlauf aus"""
        logger.info("=" * 60)
        logger.info("STARTE KLEINANZEIGEN SCRAPING-DURCHLAUF")
        logger.info("=" * 60)

        searches = self.get_active_searches()
        logger.info(f"📋 Aktive Suchanfragen: {len(searches)}")

        if not searches:
            logger.warning("⚠️  Keine aktiven Kleinanzeigen-Suchen gefunden!")
            return 0

        total_new_items = 0

        for idx, search in enumerate(searches, 1):
            query = search['query']
            logger.info(f"\n[{idx}/{len(searches)}] 🔍 Suche: '{query}'")

            try:
                entries = self.fetch_rss_feed(search)
                logger.info(f"   📦 Feed-Einträge gefunden: {len(entries)}")

                if not entries:
                    logger.warning(f"   ⚠️  Keine Einträge im RSS-Feed")
                    continue

                new_items = 0
                for entry in entries:
                    if self.process_feed_entry(entry, search):
                        new_items += 1

                logger.info(f"   ✨ Neue Items: {new_items}")
                total_new_items += new_items

                # Last checked aktualisieren
                self.update_last_checked(search['id'])

                # Pause zwischen Anfragen (Rate-Limiting)
                time.sleep(3)

            except Exception as e:
                logger.error(f"   ❌ Fehler bei Suche '{query}': {e}")
                continue

        logger.info("\n" + "=" * 60)
        logger.info(f"✅ DURCHLAUF ABGESCHLOSSEN - Neue Items gesamt: {total_new_items}")
        logger.info("=" * 60 + "\n")

        return total_new_items

    def run_continuous(self, interval_seconds: int = 300):
        """Führt kontinuierlich Scraping-Durchläufe aus"""
        logger.info(f"🚀 Starte kontinuierliches Scraping (Interval: {interval_seconds}s = {interval_seconds/60:.1f} Minuten)")

        cycle_count = 0

        while True:
            cycle_count += 1
            logger.info(f"\n🔄 Durchlauf #{cycle_count} - {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")

            try:
                self.run_scrape_cycle()
            except Exception as e:
                logger.error(f"❌ Kritischer Fehler im Scraping-Durchlauf: {e}")

            next_run = datetime.now().timestamp() + interval_seconds
            next_run_time = datetime.fromtimestamp(next_run).strftime('%H:%M:%S')
            logger.info(f"💤 Nächster Durchlauf um {next_run_time}")

            time.sleep(interval_seconds)


# ========================================
# HAUPTPROGRAMM
# ========================================

if __name__ == "__main__":
    DATABASE_URL = "postgresql://agent_db_final_user:7FfbPfBywc3Xd0qCDWSwCT3cxl7NSMvt@dpg-d1ua2849c44c73cp4cag-a.oregon-postgres.render.com/agent_db_final"

    scraper = KleinanzeigenScraper(DATABASE_URL)

    # Wähle Modus:

    # Option 1: Einmaliger Test-Durchlauf
    # scraper.run_scrape_cycle()

    # Option 2: Kontinuierlich alle 5 Minuten
    scraper.run_continuous(interval_seconds=300)

    # Option 3: Kontinuierlich alle 3 Minuten (schneller)
    # scraper.run_continuous(interval_seconds=180)
