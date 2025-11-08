# alert_checker.py
"""
Automatische Alert-Prüfung für eBay Items
==========================================
Prüft alle aktiven Search-Alerts und sendet Telegram-Benachrichtigungen
bei neuen Treffern.

Wird vom Cron-Job alle X Minuten aufgerufen.
"""

import json
import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from telegram_bot import send_new_item_alert

# Konfiguration aus .env
ALERT_CHECK_INTERVAL = int(os.getenv("ALERT_CHECK_INTERVAL", "3"))  # Minuten


def check_all_alerts(db_connection) -> Dict[str, int]:
    """
    Hauptfunktion: Prüft alle aktiven Alerts und sendet Benachrichtigungen.

    Args:
        db_connection: SQLite/PostgreSQL Connection

    Returns:
        Dict mit Statistiken {"alerts_checked": X, "new_items_found": Y, "notifications_sent": Z}
    """
    print(f"\n{'='*70}")
    print(f"🔔 ALERT-CHECK GESTARTET: {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*70}\n")

    stats = {
        "alerts_checked": 0,
        "new_items_found": 0,
        "notifications_sent": 0,
        "errors": 0
    }

    cur = db_connection.cursor()

    # Hole alle aktiven Alerts
    cur.execute("""
        SELECT id, user_email, terms_json, filters_json, last_run_ts
        FROM search_alerts
        WHERE is_active = 1
    """)

    alerts = cur.fetchall()

    if not alerts:
        print("ℹ️  Keine aktiven Alerts gefunden.")
        return stats

    print(f"📋 Gefunden: {len(alerts)} aktive Alert(s)\n")

    for alert in alerts:
        try:
            process_single_alert(alert, cur, db_connection, stats)
        except Exception as e:
            print(f"❌ Fehler bei Alert {alert['id']}: {e}")
            stats["errors"] += 1
            import traceback
            traceback.print_exc()

    db_connection.commit()

    print(f"\n{'='*70}")
    print(f"✅ ALERT-CHECK ABGESCHLOSSEN")
    print(f"{'='*70}")
    print(f"📊 Statistik:")
    print(f"   - Alerts geprüft: {stats['alerts_checked']}")
    print(f"   - Neue Items: {stats['new_items_found']}")
    print(f"   - Benachrichtigungen: {stats['notifications_sent']}")
    print(f"   - Fehler: {stats['errors']}")
    print(f"{'='*70}\n")

    return stats


def process_single_alert(alert, cursor, connection, stats: Dict) -> None:
    """Verarbeitet einen einzelnen Alert"""
    # Konvertiere Row zu Dict
    alert = dict(alert)  # ← NEU! Diese Zeile MUSS als ERSTES rein!

    alert_id = alert["id"]  # ← Jetzt OK!

    user_email = alert["user_email"]
    terms = json.loads(alert["terms_json"])
    filters = json.loads(alert["filters_json"])
    last_run = int(alert.get("last_run_ts") or 0)
    agent_name = f"Alert #{alert_id}"

    now = int(time.time())

    # Prüfe ob genug Zeit vergangen ist (Rate-Limiting)
    check_interval_seconds = ALERT_CHECK_INTERVAL * 60
    if now - last_run < check_interval_seconds:
        time_left = check_interval_seconds - (now - last_run)
        print(f"⏭️  Alert {alert_id} ({agent_name}): Übersprungen (noch {time_left}s)")
        return

    print(f"🔍 Alert {alert_id} ({agent_name})")
    print(f"   User: {user_email}")
    print(f"   Suchbegriffe: {terms}")
    stats["alerts_checked"] += 1

    # Hole Telegram Chat-ID des Users
    cursor.execute("""
        SELECT telegram_chat_id, telegram_enabled, telegram_verified
        FROM users
        WHERE email = ?
    """, (user_email,))

    user_row = cursor.fetchone()

    if not user_row:
        print(f"   ⚠️  User nicht in DB gefunden")
        update_alert_timestamp(alert_id, now, cursor)
        return

    # Konvertiere Row zu Dict
    user_row = dict(user_row)  # ← DAS HAST DU SCHON!

    telegram_chat_id = user_row.get("telegram_chat_id")

    telegram_enabled = user_row.get("telegram_enabled", False)
    telegram_verified = user_row.get("telegram_verified", False)

    if not (telegram_chat_id and telegram_enabled and telegram_verified):
        print(f"   ℹ️  Telegram nicht aktiviert/verifiziert")
        update_alert_timestamp(alert_id, now, cursor)
        return

    # Suche durchführen
    print(f"   🔎 Führe Suche durch...")

    try:
        # WICHTIG: Diese Funktion muss aus app.py importiert werden!
        # Workaround: Nutze direkte Funktion wenn verfügbar
        from app import _backend_search_ebay

        items, total = _backend_search_ebay(terms, filters, page=1, per_page=10)

        print(f"   📦 Gefunden: {len(items)} Items")

    except Exception as e:
        print(f"   ❌ Suche fehlgeschlagen: {e}")
        stats["errors"] += 1
        update_alert_timestamp(alert_id, now, cursor)
        return

    # Finde neue Items (die noch nicht gesehen wurden)
    new_items = find_new_items(items, alert_id, user_email, cursor, connection)

    if new_items:
        print(f"   🎯 {len(new_items)} NEUE Item(s)!")
        stats["new_items_found"] += len(new_items)

        # Sende Benachrichtigungen (max 5 um Spam zu vermeiden)
        for item in new_items[:5]:
            success = send_telegram_alert(telegram_chat_id, item, agent_name)
            if success:
                stats["notifications_sent"] += 1
            time.sleep(1)  # 1 Sekunde Pause zwischen Nachrichten

        if len(new_items) > 5:
            print(f"   ℹ️  {len(new_items) - 5} weitere Items nicht gesendet (Spam-Schutz)")
    else:
        print(f"   ✓ Keine neuen Items")

    # Timestamp aktualisieren
    update_alert_timestamp(alert_id, now, cursor)
    print()


def find_new_items(
    items: List[Dict],
    alert_id: int,
    user_email: str,
    cursor,
    connection
) -> List[Dict]:
    """
    Filtert neue Items heraus (die noch nicht gesehen wurden).
    Markiert gesehene Items in der DB.
    """
    new_items = []
    now = int(time.time())

    for item in items:
        # Item-ID aus URL oder direkt
        item_id = str(item.get("id") or item.get("url", ""))[:200]

        if not item_id:
            continue

        # Prüfe ob schon gesehen
        cursor.execute("""
            SELECT item_id FROM alert_seen
            WHERE user_email = ? AND search_hash = ? AND item_id = ?
        """, (user_email, str(alert_id), item_id))

        if cursor.fetchone():
            # Schon gesehen
            continue

        # Neues Item!
        new_items.append(item)

        # In DB markieren
        cursor.execute("""
            INSERT INTO alert_seen
            (user_email, search_hash, src, item_id, first_seen, last_sent)
            VALUES (?, ?, 'ebay', ?, ?, ?)
        """, (user_email, str(alert_id), item_id, now, now))

    connection.commit()
    return new_items


def send_telegram_alert(chat_id: str, item: Dict, agent_name: str) -> bool:
    """
    Sendet eine Telegram-Benachrichtigung für ein Item.
    Nutzt die vorhandene send_new_item_alert() Funktion.
    """
    try:
        # Formatiere Item für telegram_bot.py
        formatted_item = {
            "title": item.get("title", "Unbekannt"),
            "price": str(item.get("price", "N/A")),
            "currency": item.get("currency", "EUR"),
            "url": item.get("url", ""),
            "image_url": item.get("image_url") or item.get("image") or "",  # FIX: Mehrere Felder prüfen
            "condition": item.get("condition", ""),
            "location": item.get("location", ""),
        }

        # Debug: Zeige welches Bild verwendet wird
        if formatted_item["image_url"]:
            print(f"      🖼️  Bild-URL: {formatted_item['image_url'][:60]}...")
        else:
            print(f"      ℹ️  Kein Bild verfügbar")

        success = send_new_item_alert(
            chat_id=chat_id,
            item=formatted_item,
            agent_name=agent_name,
            with_image=bool(formatted_item["image_url"])  # Nur mit Bild wenn vorhanden
        )

        if success:
            print(f"      ✅ Telegram-Nachricht gesendet")
        else:
            print(f"      ⚠️  Telegram-Nachricht fehlgeschlagen")

        return success

    except Exception as e:
        print(f"      ❌ Fehler beim Senden: {e}")
        return False


def update_alert_timestamp(alert_id: int, timestamp: int, cursor) -> None:
    """Aktualisiert den last_run_ts eines Alerts"""
    cursor.execute("""
        UPDATE search_alerts
        SET last_run_ts = ?
        WHERE id = ?
    """, (timestamp, alert_id))


# ============================================================================
# HAUPTFUNKTION für Cron-Job
# ============================================================================

def run_alert_check():
    """
    Haupt-Entry-Point für den Cron-Job.
    Wird von der /cron/check-alerts Route aufgerufen.
    """
    try:
        # DB-Connection holen (muss aus app.py importiert werden)
        from app import get_db

        conn = get_db()
        stats = check_all_alerts(conn)
        conn.close()

        return {
            "success": True,
            "stats": stats,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        print(f"\n❌ KRITISCHER FEHLER im Alert-Check: {e}")
        import traceback
        traceback.print_exc()

        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


# ============================================================================
# TEST / DEBUG
# ============================================================================

if __name__ == "__main__":
    print("🧪 Alert-Checker Test-Modus\n")

    # Prüfe Konfiguration
    from telegram_bot import TelegramBot

    bot = TelegramBot()
    if bot.is_configured():
        print("✅ Telegram Bot ist konfiguriert")
    else:
        print("❌ TELEGRAM_BOT_TOKEN fehlt!")

    print(f"⏰ Check-Interval: {ALERT_CHECK_INTERVAL} Minuten")
    print("\nZum Ausführen: Starte den Cron-Job oder rufe /cron/check-alerts auf")
