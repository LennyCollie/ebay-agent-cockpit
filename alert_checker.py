# alert_checker.py
"""
Automatische Alert-Prüfung für eBay & Kleinanzeigen
====================================================
Prüft alle aktiven Search-Alerts und sendet Telegram-Benachrichtigungen
bei neuen Treffern.

ERWEITERT: Unterstützt jetzt auch eBay Kleinanzeigen!
"""

import json
import os
import time
from datetime import datetime
from typing import Dict, List, Optional

from telegram_bot import send_new_item_alert
from database import dict_cursor, get_placeholder
from dotenv import load_dotenv
load_dotenv()

# Konfiguration
ALERT_CHECK_INTERVAL = int(os.getenv("ALERT_CHECK_INTERVAL", "3"))  # Minuten
PH = get_placeholder()


def check_all_alerts(db_connection) -> Dict[str, int]:
    """
    Hauptfunktion: Prüft alle aktiven Alerts und sendet Benachrichtigungen.
    ERWEITERT: Unterstützt eBay UND Kleinanzeigen!
    """
    print(f"\n{'='*70}")
    print(f"🔔 ALERT-CHECK GESTARTET: {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*70}\n")

    stats = {
        "alerts_checked": 0,
        "new_items_found": 0,
        "notifications_sent": 0,
        "errors": 0,
        "ebay_alerts": 0,
        "kleinanzeigen_alerts": 0,
    }

    cur = dict_cursor(db_connection)

    # Hole alle aktiven Alerts (MIT source-Spalte!)
    cur.execute(
        """
        SELECT id, user_email, terms_json, filters_json, last_run_ts, source
        FROM search_alerts
        WHERE is_active = 1
        """
    )
    alerts = cur.fetchall()

    if not alerts:
        print("ℹ️  Keine aktiven Alerts gefunden.")
        return stats

    print(f"📋 Gefunden: {len(alerts)} aktive Alert(s)\n")

    for alert_row in alerts:
        try:
            process_single_alert(alert_row, cur, db_connection, stats)
        except Exception as e:
            try:
                aid = alert_row.get("id")
            except Exception:
                aid = "?"
            print(f"❌ Fehler bei Alert {aid}: {e}")
            stats["errors"] += 1
            import traceback
            traceback.print_exc()

    db_connection.commit()

    print(f"\n{'='*70}")
    print(f"✅ ALERT-CHECK ABGESCHLOSSEN")
    print(f"{'='*70}")
    print(f"📊 Statistik:")
    print(f"   - Alerts geprüft: {stats['alerts_checked']}")
    print(f"   - eBay Alerts: {stats['ebay_alerts']}")
    print(f"   - Kleinanzeigen Alerts: {stats['kleinanzeigen_alerts']}")
    print(f"   - Neue Items: {stats['new_items_found']}")
    print(f"   - Benachrichtigungen: {stats['notifications_sent']}")
    print(f"   - Fehler: {stats['errors']}")
    print(f"{'='*70}\n")

    return stats


def process_single_alert(alert_row, cursor, connection, stats: Dict) -> None:
    """Verarbeitet einen einzelnen Alert (eBay ODER Kleinanzeigen)"""

    alert = dict(alert_row)
    alert_id = alert["id"]
    user_email = alert["user_email"]
    terms = json.loads(alert["terms_json"])
    filters = json.loads(alert["filters_json"])
    last_run = int(alert.get("last_run_ts") or 0)

    # ⭐ NEU: Source-Feld auslesen
    source = alert.get("source", "ebay").lower()

    agent_name = f"Alert #{alert_id} ({source.upper()})"

    now = int(time.time())

    # Rate-Limiting prüfen
    check_interval_seconds = ALERT_CHECK_INTERVAL * 60
    if now - last_run < check_interval_seconds:
        time_left = check_interval_seconds - (now - last_run)
        print(f"⏭️  Alert {alert_id} ({agent_name}): Übersprungen (noch {time_left}s)")
        return

    print(f"🔍 Alert {alert_id} ({agent_name})")
    print(f"   User: {user_email}")
    print(f"   Suchbegriffe: {terms}")
    print(f"   Quelle: {source.upper()}")
    stats["alerts_checked"] += 1

    # Telegram-Daten des Users holen
    cursor.execute(
        f"""
        SELECT telegram_chat_id, telegram_enabled, telegram_verified
        FROM users
        WHERE email = {PH}
        """,
        (user_email,),
    )
    user_row = cursor.fetchone()

    if not user_row:
        print(f"   ⚠️  User nicht in DB gefunden")
        update_alert_timestamp(alert_id, now, cursor)
        return

    user_row = dict(user_row)
    telegram_chat_id = user_row.get("telegram_chat_id")
    telegram_enabled = bool(user_row.get("telegram_enabled"))
    telegram_verified = bool(user_row.get("telegram_verified"))

    if not (telegram_chat_id and telegram_enabled and telegram_verified):
        print(f"   ℹ️  Telegram nicht aktiviert/verifiziert")
        update_alert_timestamp(alert_id, now, cursor)
        return

    # ⭐ SUCHE DURCHFÜHREN - abhängig von Source
    print(f"   🔎 Führe {source.upper()}-Suche durch...")

    try:
        if source == "kleinanzeigen":
            items = search_kleinanzeigen_for_alert(terms, filters)
            stats["kleinanzeigen_alerts"] += 1
        else:
            items = search_ebay_for_alert(terms, filters)
            stats["ebay_alerts"] += 1

        print(f"   📦 Gefunden: {len(items)} Items")

    except Exception as e:
        print(f"   ❌ Suche fehlgeschlagen: {e}")
        stats["errors"] += 1
        update_alert_timestamp(alert_id, now, cursor)
        return

    # Neue Items finden
    new_items = find_new_items(items, alert_id, user_email, source, cursor, connection)

    if new_items:
        print(f"   🎯 {len(new_items)} NEUE Item(s)!")
        stats["new_items_found"] += len(new_items)

        # Benachrichtigungen senden (max 5)
        for item in new_items[:5]:
            success = send_telegram_alert(
                str(telegram_chat_id),
                item,
                agent_name,
                source
            )
            if success:
                stats["notifications_sent"] += 1
            time.sleep(1)

        if len(new_items) > 5:
            print(f"   ℹ️  {len(new_items) - 5} weitere Items nicht gesendet (Spam-Schutz)")
    else:
        print(f"   ✓ Keine neuen Items")

    update_alert_timestamp(alert_id, now, cursor)
    print()


# ============================================================================
# ⭐ NEU: Kleinanzeigen-Suche für Alerts
# ============================================================================

def search_kleinanzeigen_for_alert(terms: List[str], filters: Dict) -> List[Dict]:
    """
    Führt Kleinanzeigen-Suche für einen Alert aus.
    Nutzt die HTML-Scraping-Funktion aus services/kleinanzeigen.py
    """
    try:
        from services.kleinanzeigen import search_kleinanzeigen

        query = " ".join(terms)
        price_min = filters.get("price_min")
        price_max = filters.get("price_max")

        # Konvertiere zu Float falls String
        if price_min and isinstance(price_min, str):
            try:
                price_min = float(price_min)
            except:
                price_min = None

        if price_max and isinstance(price_max, str):
            try:
                price_max = float(price_max)
            except:
                price_max = None

        results = search_kleinanzeigen(
            query=query,
            price_min=price_min,
            price_max=price_max,
            limit=20
        )

        # Konvertiere zu einheitlichem Format
        items = []
        for item in results:
            items.append({
                "id": item.get("item_id"),
                "title": item.get("title"),
                "price": f"{item.get('price'):.2f} EUR" if item.get('price') else "VB",
                "url": item.get("url"),
                "img": item.get("image_url"),
                "image_url": item.get("image_url"),
                "location": item.get("location"),
                "condition": item.get("condition"),
                "src": "kleinanzeigen",
            })

        return items

    except Exception as e:
        print(f"      ❌ Kleinanzeigen-Suche Fehler: {e}")
        import traceback
        traceback.print_exc()
        return []


def search_ebay_for_alert(terms: List[str], filters: Dict) -> List[Dict]:
    """
    Führt eBay-Suche für einen Alert aus.
    Nutzt die bestehende _backend_search_ebay Funktion.
    """
    try:
        from app import _backend_search_ebay
        items, total = _backend_search_ebay(terms, filters, page=1, per_page=10)
        return items
    except Exception as e:
        print(f"      ❌ eBay-Suche Fehler: {e}")
        return []


# ============================================================================
# ⭐ ERWEITERT: find_new_items mit Source-Unterstützung
# ============================================================================

def find_new_items(
    items: List[Dict],
    alert_id: int,
    user_email: str,
    source: str,  # ⭐ NEU: Source-Parameter
    cursor,
    connection,
) -> List[Dict]:
    """
    Filtert neue Items heraus (eBay ODER Kleinanzeigen).
    Markiert gesehene Items mit der richtigen Source.
    """
    new_items: List[Dict] = []
    now = int(time.time())

    for item in items:
        item_id = str(item.get("id") or item.get("url", ""))[:200]

        if not item_id:
            continue

        # Prüfe ob schon gesehen (mit Source!)
        cursor.execute(
            f"""
            SELECT item_id FROM alert_seen
            WHERE user_email = {PH}
            AND search_hash = {PH}
            AND src = {PH}
            AND item_id = {PH}
            """,
            (user_email, str(alert_id), source, item_id),
        )

        if cursor.fetchone():
            continue

        # Neues Item!
        new_items.append(item)

        # In DB markieren (mit Source!)
        cursor.execute(
            f"""
            INSERT INTO alert_seen
                (user_email, search_hash, src, item_id, first_seen, last_sent)
            VALUES
                ({PH}, {PH}, {PH}, {PH}, {PH}, {PH})
            """,
            (user_email, str(alert_id), source, item_id, now, now),
        )

    connection.commit()
    return new_items


# ============================================================================
# ⭐ ERWEITERT: Telegram-Nachricht mit Source-Badge
# ============================================================================

def send_telegram_alert(
    chat_id: str,
    item: Dict,
    agent_name: str,
    source: str = "ebay"  # ⭐ NEU
) -> bool:
    """
    Sendet Telegram-Benachrichtigung.
    Zeigt Badge für Source (eBay = 🔵, Kleinanzeigen = 🟢)
    """
    try:
        # Source-Badge
        badge = "🟢" if source == "kleinanzeigen" else "🔵"
        source_name = "Kleinanzeigen" if source == "kleinanzeigen" else "eBay"

        # Formatiere Item
        formatted_item = {
            "title": f"{badge} {item.get('title', 'Unbekannt')}",
            "price": str(item.get("price", "N/A")),
            "currency": item.get("currency", "EUR"),
            "url": item.get("url", ""),
            "image_url": item.get("image_url") or item.get("img") or "",
            "condition": item.get("condition", ""),
            "location": item.get("location", ""),
            "source": source_name,  # ⭐ Für Template
        }

        if formatted_item["image_url"]:
            print(f"      🖼️  Bild-URL: {formatted_item['image_url'][:60]}...")
        else:
            print(f"      ℹ️  Kein Bild verfügbar")

        success = send_new_item_alert(
            chat_id=chat_id,
            item=formatted_item,
            agent_name=agent_name,
            with_image=bool(formatted_item["image_url"]),
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
    cursor.execute(
        f"""
        UPDATE search_alerts
        SET last_run_ts = {PH}
        WHERE id = {PH}
        """,
        (timestamp, alert_id),
    )


# ============================================================================
# HAUPTFUNKTION
# ============================================================================

def run_alert_check():
    """
    Entry-Point für Cron-Job.
    Prüft ALLE Alerts (eBay + Kleinanzeigen)
    """
    try:
        from app import get_db

        conn = get_db()
        stats = check_all_alerts(conn)
        conn.close()

        return {
            "success": True,
            "stats": stats,
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        print(f"\n❌ KRITISCHER FEHLER im Alert-Check: {e}")
        import traceback
        traceback.print_exc()

        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
        }


# ============================================================================
# DIREKTSTART (Test)
# ============================================================================

if __name__ == "__main__":
    print("🔔 Alert-Checker Direktstart (eBay + Kleinanzeigen)\n")
    print(f"⏰ Check-Interval: {ALERT_CHECK_INTERVAL} Minuten")

    if os.getenv("TELEGRAM_BOT_TOKEN"):
        print("✅ Telegram Bot ist konfiguriert")
    else:
        print("⚠️ TELEGRAM_BOT_TOKEN nicht gesetzt")

    result = run_alert_check()

    print("\n📊 Ergebnis:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
