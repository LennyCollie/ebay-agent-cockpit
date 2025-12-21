# alert_checker.py
"""
Automatische Alert-Prüfung für eBay & Kleinanzeigen
====================================================
Prüft alle aktiven Search-Alerts und sendet Benachrichtigungen
(Telegram / E-Mail) bei neuen Treffern.

- Unterstützt eBay UND Kleinanzeigen (pro Alert wählbar über `source`)
- Pro Alert konfigurierbare Kanäle:
    - notify_telegram (0/1)
    - notify_email (0/1)
- Nutzt die zentrale DB-Anbindung aus database.py (PostgreSQL/SQLite)
- Nutzt Telegram-Bot (telegram_bot.py) und Mail-API (agent.py)
"""

import json
import os
import time
from datetime import datetime
from typing import Dict, List

from dotenv import load_dotenv

from telegram_bot import send_new_item_alert
from database import dict_cursor, get_placeholder, get_db
from agent import get_mail_settings, send_mail

load_dotenv()

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------
ALERT_CHECK_INTERVAL = int(os.getenv("ALERT_CHECK_INTERVAL", "3"))  # Minuten
PH = get_placeholder()
ALERT_INTERVAL_FREE = int(os.getenv("ALERT_INTERVAL_FREE", "30"))
ALERT_INTERVAL_PREMIUM = int(os.getenv("ALERT_INTERVAL_PREMIUM", "3"))


# ---------------------------------------------------------------------------
# HAUPTSCHLEIFE: Alle Alerts prüfen
# ---------------------------------------------------------------------------
def check_all_alerts(db_connection) -> Dict[str, int]:
    """
    Hauptfunktion: Prüft alle aktiven Alerts und sendet Benachrichtigungen.

    - Quelle pro Alert über Spalte `source`:
        - "ebay"
        - "kleinanzeigen"
    - Kanäle pro Alert:
        - notify_telegram (0/1)
        - notify_email (0/1)
    """
    print(f"\n{'=' * 70}")
    print(f"🔔 ALERT-CHECK GESTARTET: {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'=' * 70}\n")

    stats = {
        "alerts_checked": 0,
        "new_items_found": 0,
        "notifications_sent": 0,   # Telegram + E-Mail zusammen
        "errors": 0,
        "ebay_alerts": 0,
        "kleinanzeigen_alerts": 0,
    }

    cur = dict_cursor(db_connection)

    # Neue Spalten: source, notify_telegram, notify_email
    cur.execute(
        """
        SELECT
            id,
            user_email,
            terms_json,
            filters_json,
            last_run_ts,
            source,
            notify_telegram,
            notify_email
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
                aid = alert_row["id"] if isinstance(alert_row, dict) else alert_row[0]
            except Exception:
                aid = "?"
            print(f"[!] Fehler bei Alert {aid}: {e}")
            stats["errors"] += 1
            import traceback

            traceback.print_exc()

    try:
        db_connection.commit()
    except Exception:
        # bei Postgres kann die Connection ggf. schon weg sein
        pass

    print(f"\n{'=' * 70}")
    print(f"[OK] ALERT-CHECK ABGESCHLOSSEN")
    print(f"{'=' * 70}")
    print(f"[*] Statistik:")
    print(f"   - Alerts geprüft: {stats['alerts_checked']}")
    print(f"   - eBay Alerts: {stats['ebay_alerts']}")
    print(f"   - Kleinanzeigen Alerts: {stats['kleinanzeigen_alerts']}")
    print(f"   - Neue Items: {stats['new_items_found']}")
    print(f"   - Benachrichtigungen gesamt: {stats['notifications_sent']}")
    print(f"   - Fehler: {stats['errors']}")
    print(f"{'=' * 70}\n")

    return stats


# ---------------------------------------------------------------------------
# EINZELNER ALERT
# ---------------------------------------------------------------------------
def process_single_alert(alert_row, cursor, connection, stats: Dict) -> None:
    """Verarbeitet einen einzelnen Alert (eBay ODER Kleinanzeigen)"""

    alert = dict(alert_row)
    alert_id = alert["id"]
    user_email = alert["user_email"]

    try:
        terms = json.loads(alert.get("terms_json") or "[]")
    except Exception:
        terms = []

    try:
        filters = json.loads(alert.get("filters_json") or "{}")
    except Exception:
        filters = {}

    last_run = int(alert.get("last_run_ts") or 0)

    # Quelle: ebay / kleinanzeigen
    source = (alert.get("source") or "ebay").strip().lower()
    if source not in ("ebay", "kleinanzeigen"):
        source = "ebay"

    # Benachrichtigungs-Kanäle aus der DB (0/1 -> bool)
    notify_telegram = bool(alert.get("notify_telegram", 1))
    notify_email = bool(alert.get("notify_email", 0))

    agent_name = f"Alert #{alert_id} ({source.upper()})"
    now = int(time.time())

    # ------------------------------------------------------------
    # User-Daten laden (inkl. Plan & Premium-Flag)
    # ------------------------------------------------------------
    cursor.execute(
        f"""
        SELECT
            telegram_chat_id,
            telegram_enabled,
            telegram_verified,
            plan_type,
            is_premium
        FROM users
        WHERE email = {PH}
        """,
        (user_email,),
    )
    user_row = cursor.fetchone()

    if not user_row:
        print("   [!]  User nicht in DB gefunden")
        update_alert_timestamp(alert_id, now, cursor)
        return

    user_row = dict(user_row)

    telegram_chat_id = user_row.get("telegram_chat_id")
    telegram_enabled = bool(user_row.get("telegram_enabled"))
    telegram_verified = bool(user_row.get("telegram_verified"))

    # Plan & Premium sauber initialisieren
    plan_type = (user_row.get("plan_type") or "").strip().lower()
    is_premium = bool(user_row.get("is_premium"))

    # ------------------------------------------------------------
    # Plan-Logik: welche Kanäle sind erlaubt?
    # ------------------------------------------------------------
    if not (plan_type in ("pro", "premium") or is_premium):
        # FREE-Plan: Telegram abschalten
        if notify_telegram:
            print("   ℹ️  Telegram ist im FREE-Plan nicht erlaubt – deaktiviere für diesen Alert.")
        notify_telegram = False
        # notify_email lassen wir an – das ist dein „Freemium“-Channel

    # ------------------------------------------------------------
    # Intervall je nach Plan bestimmen
    # ------------------------------------------------------------
    if plan_type in ("pro", "premium") or is_premium:
        alert_interval_min = ALERT_INTERVAL_PREMIUM
    else:
        alert_interval_min = ALERT_INTERVAL_FREE

    check_interval_seconds = alert_interval_min * 60

    # Debug-Ausgabe
    print(f"[*] Alert {alert_id} ({agent_name})")
    print(f"   User: {user_email}")
    print(f"   Suchbegriffe: {terms}")
    print(f"   Quelle: {source.upper()}")
    print(
        f"   Plan: '{plan_type or 'free'}', PremiumFlag={is_premium}, "
        f"Intervall={alert_interval_min} Min"
    )
    print(f"   Kanäle: Telegram={notify_telegram}, E-Mail={notify_email}")
    stats["alerts_checked"] += 1

    # ------------------------------------------------------------
    # Rate-Limiting basierend auf Plan (Free vs. Premium/Pro)
    # ------------------------------------------------------------
    if now - last_run < check_interval_seconds:
        time_left = check_interval_seconds - (now - last_run)
        print(
            f"⏭️  Alert {alert_id} ({agent_name}): Übersprungen "
            f"(noch {time_left}s, Intervall={alert_interval_min} Min, Plan='{plan_type or 'free'}')"
        )
        return

    # ------------------------------------------------------------
    # Telegram-Status hart prüfen, falls der Alert Telegram nutzen will
    # ------------------------------------------------------------
    if notify_telegram and not (telegram_chat_id and telegram_enabled and telegram_verified):
        print("   ℹ️  Telegram nicht aktiviert/verifiziert – Telegram wird für diesen Alert deaktiviert")
        notify_telegram = False

    # Wenn weder Telegram noch Mail aktiv sind, trotzdem suchen (damit Items ggf. als gesehen markiert werden),
    # aber nichts verschicken.
    if not notify_telegram and not notify_email:
        print("   ℹ️  Keine Benachrichtigungskanäle aktiv – es wird nichts gesendet.")

    # -----------------------------------------------------------------------
    # SUCHE AUSFÜHREN (abhängig von Source)
    # -----------------------------------------------------------------------
    print(f"   🔎 Führe {source.upper()}-Suche durch...")

    try:
        if source == "kleinanzeigen":
            items = search_kleinanzeigen_for_alert(terms, filters)
            stats["kleinanzeigen_alerts"] += 1
        else:
            items = search_ebay_for_alert(terms, filters)
            stats["ebay_alerts"] += 1

        print(f"   [+] Gefunden: {len(items)} Items")

    except Exception as e:
        print(f"   [!] Suche fehlgeschlagen: {e}")
        stats["errors"] += 1
        update_alert_timestamp(alert_id, now, cursor)
        return

    # -----------------------------------------------------------------------
    # NEUE ITEMS FINDEN
    # -----------------------------------------------------------------------
    new_items = find_new_items(items, alert_id, user_email, source, cursor, connection)

    if not new_items:
        print("   [+] Keine neuen Items")
        update_alert_timestamp(alert_id, now, cursor)
        print()
        return

    print(f"   🎯 {len(new_items)} NEUE Item(s)!")
    stats["new_items_found"] += len(new_items)

    # -----------------------------------------------------------------------
    # TELEGRAM-BENACHRICHTIGUNGEN
    # -----------------------------------------------------------------------
    if notify_telegram:
        for item in new_items[:5]:
            success = send_telegram_alert(
                str(telegram_chat_id),
                item,
                agent_name,
                source,
                alert_id,
            )
            if success:
                stats["notifications_sent"] += 1
            time.sleep(1)

        if len(new_items) > 5:
            print(f"   ℹ️  {len(new_items) - 5} weitere Items nicht per Telegram gesendet (Spam-Schutz)")

    # -----------------------------------------------------------------------
    # E-MAIL-BENACHRICHTIGUNG (einmal pro Alert-Lauf)
    # -----------------------------------------------------------------------
    if notify_email:
        email_ok = send_email_alert(user_email, alert, new_items, source)
        if email_ok:
            stats["notifications_sent"] += 1
        else:
            print("   [!]  E-Mail-Versand für diesen Alert fehlgeschlagen")

    update_alert_timestamp(alert_id, now, cursor)
    print()


# ---------------------------------------------------------------------------
# E-MAIL-BENACHRICHTIGUNG
# ---------------------------------------------------------------------------
def send_email_alert(user_email: str, alert: Dict, new_items: List[Dict], source: str) -> bool:
    """
    Baut eine HTML-Mail mit den neuen Items und verschickt sie über Postmark/SMTP,
    basierend auf agent.get_mail_settings / agent.send_mail.
    """
    if not user_email or "@" not in user_email:
        print("   [!]  Ungültige E-Mail-Adresse, überspringe E-Mail-Versand.")
        return False

    try:
        terms = json.loads(alert.get("terms_json") or "[]")
    except Exception:
        terms = []

    subject_terms = ", ".join(terms) if terms else "deinen Alert"
    src_label = "eBay Kleinanzeigen" if source == "kleinanzeigen" else "eBay"
    subject = f"🔔 Neue Treffer bei {src_label} für „{subject_terms}“"

    lines = [
        f"<h3>Neue Treffer für deinen {src_label}-Agent</h3>",
        "<p>Hier sind die neuesten Angebote, die zu deinem Alert passen:</p>",
        "<ul>",
    ]

    for item in new_items[:30]:  # Sicherheitslimit
        title = item.get("title") or "Ohne Titel"
        price = str(item.get("price") or item.get("price_text") or "")
        url = item.get("url") or item.get("item_url") or "#"
        src = (item.get("src") or src_label).title()

        lines.append(
            f'<li>[{src}] <a href="{url}">{title}</a>'
            f"{(' – ' + price) if price else ''}</li>"
        )

    lines.append("</ul>")
    lines.append(
        "<p style='margin-top:12px;font-size:12px;color:#666'>"
        "Du erhältst diese Mail, weil du für diese Suche einen Alarm aktiviert hast."
        "</p>"
    )
    body_html = "\n".join(lines)

    try:
        settings = get_mail_settings()
        ok = send_mail(settings, [user_email], subject, body_html)
        if ok:
            print(f"   [OK] E-Mail an {user_email} gesendet")
        else:
            print(f"   [!] send_mail(...) meldet Fehler für {user_email}")
        return ok
    except Exception as e:
        print(f"   [!] Exception beim E-Mail-Versand: {e}")
        import traceback

        traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# Kleinanzeigen-SUCHE für Alerts (Wrapper um services.kleinanzeigen)
# ---------------------------------------------------------------------------
def search_kleinanzeigen_for_alert(terms: List[str], filters: Dict) -> List[Dict]:
    """
    Führt Kleinanzeigen-Suche für einen Alert aus.
    Nutzt die HTML-Scraping-Funktion aus services/kleinanzeigen.py
    und wandelt das Ergebnis in das Standard-Item-Format um.
    """
    try:
        from services.kleinanzeigen import search_kleinanzeigen
    except Exception as e:
        print(f"      [!] Kleinanzeigen-Modul nicht importierbar: {e}")
        return []

    # Suchbegriff & Preisgrenzen vorbereiten
    query = " ".join(terms)

    def _parse_price(val):
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip()
        if not s:
            return None
        s = s.replace("€", "").replace(".", "").replace(",", ".")
        try:
            return float(s)
        except Exception:
            return None

    price_min = _parse_price(filters.get("price_min"))
    price_max = _parse_price(filters.get("price_max"))

    try:
        results = search_kleinanzeigen(
            query=query,
            price_min=price_min,
            price_max=price_max,
            limit=20,
        )
    except Exception as e:
        print(f"      [!] Kleinanzeigen-Suche Fehler: {e}")
        import traceback

        traceback.print_exc()
        return []

    items: List[Dict] = []

    for raw in results:
        # Robuste ID
        item_id = (
            raw.get("item_id")
            or raw.get("id")
            or raw.get("url")
        )
        if not item_id:
            continue

        # Preis hübsch formatieren
        raw_price = raw.get("price")
        if isinstance(raw_price, (int, float)):
            price_text = f"{float(raw_price):.2f} EUR"
        elif isinstance(raw_price, str) and raw_price.strip():
            price_text = raw_price.strip()
        else:
            price_text = "VB"

        items.append(
            {
                "id": str(item_id),
                "title": raw.get("title") or "Ohne Titel",
                "price": price_text,
                "url": raw.get("url"),
                "img": raw.get("image_url"),
                "image_url": raw.get("image_url"),
                "location": raw.get("location"),
                "condition": raw.get("condition"),
                "src": "kleinanzeigen",
            }
        )

    print(f"      [OK] Kleinanzeigen-Wrapper: {len(items)} Items zurückgegeben")
    return items


# ---------------------------------------------------------------------------
# eBay-SUCHE für Alerts (ruft dein Backend auf)
# ---------------------------------------------------------------------------
def search_ebay_for_alert(terms: List[str], filters: Dict) -> List[Dict]:
    """
    Führt eBay-Suche für einen Alert aus.
    Nutzt die bestehende _backend_search_ebay Funktion aus app.py.
    """
    try:
        from app import _backend_search_ebay

        items, total = _backend_search_ebay(terms, filters, page=1, per_page=10)
        return items
    except Exception as e:
        print(f"      [!] eBay-Suche Fehler: {e}")
        import traceback

        traceback.print_exc()
        return []


# ---------------------------------------------------------------------------
# NEUE ITEMS DETEKTIEREN (mit Source-Unterstützung)
# ---------------------------------------------------------------------------
def find_new_items(
    items: List[Dict],
    alert_id: int,
    user_email: str,
    source: str,
    cursor,
    connection,
) -> List[Dict]:
    """
    Filtert neue Items heraus (eBay ODER Kleinanzeigen).
    Markiert gesehene Items in alert_seen mit richtigem `src`.
    """
    new_items: List[Dict] = []
    now = int(time.time())

    for item in items:
        item_id = str(item.get("id") or item.get("url", "") or item.get("title", ""))[:200]
        if not item_id:
            continue

        # Prüfen, ob schon gesehen (für diesen Alert & Source)
        cursor.execute(
            f"""
            SELECT item_id
            FROM alert_seen
            WHERE user_email = {PH}
              AND search_hash = {PH}
              AND src = {PH}
              AND item_id = {PH}
            """,
            (user_email, str(alert_id), source, item_id),
        )

        if cursor.fetchone():
            continue

        # Neues Item -> merken & in DB eintragen
        new_items.append(item)

        cursor.execute(
            f"""
            INSERT INTO alert_seen
                (user_email, search_hash, src, item_id, first_seen, last_sent)
            VALUES
                ({PH}, {PH}, {PH}, {PH}, {PH}, {PH})
            """,
            (user_email, str(alert_id), source, item_id, now, now),
        )

    try:
        connection.commit()
    except Exception:
        pass

    return new_items


# ---------------------------------------------------------------------------
# TELEGRAM-NACHRICHT (mit Source-Badge)
# ---------------------------------------------------------------------------
def send_telegram_alert(
    chat_id: str,
    item: Dict,
    agent_name: str,
    source: str = "ebay",
    alert_id: int = None,
) -> bool:
    """
    Sendet Telegram-Benachrichtigung.
    Zeigt Badge für Source (eBay = 🔵, Kleinanzeigen = 🟢).
    Inline-Buttons ermöglichen Pause/Delete direkt im Chat.
    """
    try:
        badge = "🟢" if source == "kleinanzeigen" else "🔵"
        source_name = "Kleinanzeigen" if source == "kleinanzeigen" else "eBay"

        formatted_item = {
            "title": f"{badge} {item.get('title', 'Unbekannt')}",
            "price": str(item.get("price", "N/A")),
            "currency": item.get("currency", "EUR"),
            "url": item.get("url", ""),
            "image_url": item.get("image_url") or item.get("img") or "",
            "condition": item.get("condition", ""),
            "location": item.get("location", ""),
            "source": source_name,
        }

        if formatted_item["image_url"]:
            print(f"      🖼️  Bild-URL: {formatted_item['image_url'][:60]}...")
        else:
            print("      ℹ️  Kein Bild verfügbar")

        success = send_new_item_alert(
            chat_id=chat_id,
            item=formatted_item,
            agent_name=agent_name,
            alert_id=alert_id,
            with_image=bool(formatted_item["image_url"]),
        )

        if success:
            print("      [OK] Telegram-Nachricht gesendet")
        else:
            print("      [!]  Telegram-Nachricht fehlgeschlagen")

        return success

    except Exception as e:
        print(f"      [!] Fehler beim Senden: {e}")
        import traceback

        traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# last_run_ts aktualisieren
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Cron-Lauf in alert_runs protokollieren
# ---------------------------------------------------------------------------
def _log_alert_run(start_ts: int, end_ts: int, success: bool, stats: Dict | None) -> None:
    """
    Schreibt einen Eintrag in die Tabelle alert_runs.
    Läuft bewusst 'best effort' – Fehler beim Loggen sollen den Cron nicht killen.
    """
    stats = stats or {}
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            f"""
            INSERT INTO alert_runs (
                started_at,
                finished_at,
                success,
                alerts_checked,
                new_items_found,
                notifications_sent,
                errors,
                ebay_alerts,
                kleinanzeigen_alerts
            )
            VALUES (
                {PH}, {PH}, {PH},
                {PH}, {PH}, {PH},
                {PH}, {PH}, {PH}
            )
            """,
            (
                int(start_ts),
                int(end_ts),
                1 if success else 0,
                int(stats.get("alerts_checked", 0)),
                int(stats.get("new_items_found", 0)),
                int(stats.get("notifications_sent", 0)),
                int(stats.get("errors", 0)),
                int(stats.get("ebay_alerts", 0)),
                int(stats.get("kleinanzeigen_alerts", 0)),
            ),
        )
        conn.commit()
        print("   📝 Cron-Lauf in alert_runs protokolliert.")
    except Exception as e:
        print(f"   [!]  Konnte alert_runs nicht loggen: {e}")
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Entry-Point für Cron / HTTP-Trigger
# ---------------------------------------------------------------------------
def run_alert_check():
    """
    Entry-Point für Cron-Job.
    Prüft ALLE Alerts (eBay + Kleinanzeigen) und loggt den Lauf in alert_runs.
    """
    start_ts = int(time.time())

    try:
        conn = get_db()
        stats = check_all_alerts(conn)
        conn.close()

        end_ts = int(time.time())
        _log_alert_run(start_ts, end_ts, True, stats)

        return {
            "success": True,
            "stats": stats,
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        end_ts = int(time.time())
        # Beim Fehler haben wir evtl. keine Stats – dann alles 0, aber success=0
        _log_alert_run(start_ts, end_ts, False, None)

        print(f"\n[!] KRITISCHER FEHLER im Alert-Check: {e}")
        import traceback
        traceback.print_exc()

        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
        }


# ---------------------------------------------------------------------------
# DIREKTSTART (lokaler Test)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("🔔 Alert-Checker Direktstart (eBay + Kleinanzeigen)\n")
    print(f"⏰ Check-Interval: {ALERT_CHECK_INTERVAL} Minuten")

    if os.getenv("TELEGRAM_BOT_TOKEN"):
        print("[OK] Telegram Bot ist konfiguriert")
    else:
        print("[!] TELEGRAM_BOT_TOKEN nicht gesetzt")

    result = run_alert_check()

    print("\n[*] Ergebnis:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
