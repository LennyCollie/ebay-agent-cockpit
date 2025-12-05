#!/usr/bin/env python3
"""
eBay Agent - Haupt-Service
Kombiniert Scraper und Telegram-Benachrichtigungen
"""

import threading
import time
import logging
import signal
import sys
from datetime import datetime
import os

# Import der eigenen Module
# Diese sollten in separaten Dateien liegen:
# - kleinanzeigen_scraper.py
# - telegram_notifier.py
try:
    from kleinanzeigen_scraper import KleinanzeigenScraper
    from telegram_notifier import TelegramNotifier
except ImportError:
    logging.error("Fehler: Kann Module nicht importieren!")
    logging.error("Stelle sicher, dass kleinanzeigen_scraper.py und telegram_notifier.py im selben Ordner sind")
    sys.exit(1)

# Logging konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('ebay_agent.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ========================================
# KONFIGURATION
# ========================================

# Aus Umgebungsvariablen laden (empfohlen) oder direkt hier eintragen
DATABASE_URL = os.environ.get(
    'DATABASE_URL',
    "postgresql://agent_db_final_user:7FfbPfBywc3Xd0qCDWSwCT3cxl7NSMvt@dpg-d1ua2849c44c73cp4cag-a.oregon-postgres.render.com/agent_db_final"
)

TELEGRAM_BOT_TOKEN = os.environ.get(
    'TELEGRAM_BOT_TOKEN',
    '8367205938:AAFE59s0DGWy3x-XFpt2_60g4hZJ7X4nQb8'  # WICHTIG: Ersetzen!
)

# Intervalle in Sekunden
SCRAPER_INTERVAL = int(os.environ.get('SCRAPER_INTERVAL', 300))  # 5 Minuten
NOTIFIER_INTERVAL = int(os.environ.get('NOTIFIER_INTERVAL', 60))  # 1 Minute

# ========================================
# SERVICE KLASSE
# ========================================

class EbayAgentService:
    def __init__(self):
        self.running = False
        self.scraper = None
        self.notifier = None
        self.scraper_thread = None
        self.notifier_thread = None

        # Signal-Handler für sauberes Beenden
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def signal_handler(self, signum, frame):
        """Behandelt SIGINT (Ctrl+C) und SIGTERM"""
        logger.info("\n🛑 Shutdown-Signal empfangen...")
        self.stop()
        sys.exit(0)

    def validate_config(self) -> bool:
        """Validiert die Konfiguration"""
        if not DATABASE_URL or 'DEIN' in DATABASE_URL.upper():
            logger.error("❌ DATABASE_URL nicht konfiguriert!")
            return False

        if not TELEGRAM_BOT_TOKEN or 'DEIN' in TELEGRAM_BOT_TOKEN.upper():
            logger.error("❌ TELEGRAM_BOT_TOKEN nicht konfiguriert!")
            logger.info("ℹ️  Erstelle einen Bot mit @BotFather in Telegram")
            return False

        return True

    def run_scraper_loop(self):
        """Thread-Funktion für den Scraper"""
        logger.info("🔍 Scraper-Thread gestartet")

        self.scraper = KleinanzeigenScraper(DATABASE_URL)

        while self.running:
            try:
                self.scraper.run_scrape_cycle()
            except Exception as e:
                logger.error(f"❌ Fehler im Scraper: {e}", exc_info=True)

            # Warte das Interval, aber prüfe alle Sekunde ob wir stoppen sollen
            for _ in range(SCRAPER_INTERVAL):
                if not self.running:
                    break
                time.sleep(1)

        logger.info("🔍 Scraper-Thread beendet")

    def run_notifier_loop(self):
        """Thread-Funktion für den Notifier"""
        logger.info("📤 Notifier-Thread gestartet")

        self.notifier = TelegramNotifier(DATABASE_URL, TELEGRAM_BOT_TOKEN)

        # Bot-Info abrufen
        bot_info = self.notifier.get_bot_info()
        if bot_info:
            logger.info(f"🤖 Bot verbunden: @{bot_info.get('username')}")
        else:
            logger.error("❌ Kann Bot-Info nicht abrufen - Token ungültig?")
            return

        while self.running:
            try:
                self.notifier.send_pending_notifications()
            except Exception as e:
                logger.error(f"❌ Fehler im Notifier: {e}", exc_info=True)

            # Warte das Interval, aber prüfe alle Sekunde ob wir stoppen sollen
            for _ in range(NOTIFIER_INTERVAL):
                if not self.running:
                    break
                time.sleep(1)

        logger.info("📤 Notifier-Thread beendet")

    def start(self):
        """Startet den Service"""
        logger.info("=" * 60)
        logger.info("🚀 eBay Agent Service wird gestartet...")
        logger.info("=" * 60)

        # Konfiguration validieren
        if not self.validate_config():
            logger.error("❌ Konfiguration ungültig - Service wird nicht gestartet")
            return False

        logger.info(f"📊 Konfiguration:")
        logger.info(f"   - Scraper-Interval: {SCRAPER_INTERVAL}s ({SCRAPER_INTERVAL/60:.1f} Minuten)")
        logger.info(f"   - Notifier-Interval: {NOTIFIER_INTERVAL}s ({NOTIFIER_INTERVAL/60:.1f} Minuten)")
        logger.info(f"   - Datenbank: {DATABASE_URL.split('@')[1].split('/')[0]}")

        self.running = True

        # Threads starten
        self.scraper_thread = threading.Thread(
            target=self.run_scraper_loop,
            name="ScraperThread",
            daemon=True
        )

        self.notifier_thread = threading.Thread(
            target=self.run_notifier_loop,
            name="NotifierThread",
            daemon=True
        )

        self.scraper_thread.start()
        self.notifier_thread.start()

        logger.info("✅ Service gestartet!")
        logger.info("   Drücke Ctrl+C zum Beenden")
        logger.info("=" * 60 + "\n")

        return True

    def stop(self):
        """Stoppt den Service"""
        if not self.running:
            return

        logger.info("🛑 Service wird beendet...")
        self.running = False

        # Warte auf Threads (max 10 Sekunden)
        if self.scraper_thread:
            self.scraper_thread.join(timeout=10)
        if self.notifier_thread:
            self.notifier_thread.join(timeout=10)

        logger.info("✅ Service beendet")

    def status(self):
        """Zeigt den Status des Service an"""
        print("\n" + "=" * 60)
        print("📊 SERVICE STATUS")
        print("=" * 60)
        print(f"Running: {'✅ Ja' if self.running else '❌ Nein'}")
        print(f"Scraper-Thread: {'✅ Aktiv' if self.scraper_thread and self.scraper_thread.is_alive() else '❌ Inaktiv'}")
        print(f"Notifier-Thread: {'✅ Aktiv' if self.notifier_thread and self.notifier_thread.is_alive() else '❌ Inaktiv'}")
        print(f"Zeit: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
        print("=" * 60 + "\n")


# ========================================
# HAUPTPROGRAMM
# ========================================

def main():
    """Hauptfunktion"""
    service = EbayAgentService()

    # Service starten
    if not service.start():
        sys.exit(1)

    # Hauptloop - zeigt alle 5 Minuten den Status
    try:
        while True:
            time.sleep(300)  # 5 Minuten
            service.status()
    except KeyboardInterrupt:
        logger.info("\n👋 Beende Service...")
        service.stop()


if __name__ == "__main__":
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║              eBay Agent - Notification Service            ║
    ║                                                           ║
    ║  Überwacht automatisch eBay Kleinanzeigen und sendet     ║
    ║  Benachrichtigungen über Telegram                         ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """)

    main()
