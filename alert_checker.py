"""
Automatische Alert-Prüfung für eBay & Kleinanzeigen
===================================================
Prüft alle aktiven Search-Alerts und sendet Benachrichtigungen
(Telegram / E-Mail) bei neuen Treffern.

- Unterstützt eBay UND Kleinanzeigen (pro Alert wählbar über `source`)
- Pro Alert konfigurierbare Kanäle:
    - notify_telegram (0/1)
    - notify_email (0/1)
- Nutzt die zentrale DB-Anbindung aus database.py
- Nutzt Telegram-Bot (telegram_bot.py) und Mail-API (agent.py)
- Kleinanzeigen liefert einen Status (services/kleinanzeigen.py), damit im
  Log sichtbar ist, WARUM nichts gefunden wurde (Blockade, geänderte
  Seitenstruktur, wirklich leer ...)
"""

from __future__ import annotations

import html
import json
import os
import time
import traceback
from datetime import datetime
from typing import Dict, List

from dotenv import load_dotenv

from agent import get_mail_settings, send_mail
from database import dict_cursor, get_db, get_placeholder
from smart_filters import SmartFilter
from services.kleinanzeigen import (
    KleinanzeigenSearchResult,
    KleinanzeigenSearchStatus,
    is_kleinanzeigen_enabled,
)
from telegram_bot import send_new_item_alert

load_dotenv()

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------
ALERT_CHECK_INTERVAL = int(os.getenv("ALERT_CHECK_INTERVAL", "3"))  # Minuten
ALERT_INTERVAL_FREE = int(os.getenv("ALERT_INTERVAL_FREE", "30"))
ALERT_INTERVAL_PREMIUM = int(os.getenv("ALERT_INTERVAL_PREMIUM", "3"))

# Toleranz, damit ein Cron-Lauf, der ein paar Sekunden "zu früh" kommt,
# den Alert nicht um einen ganzen Zyklus verschiebt.
GRACE_SECONDS = int(os.getenv("ALERT_GRACE_SECONDS", "20"))

# Maximale Anzahl Telegram-Nachrichten pro Alert und Lauf (Spam-Schutz)
TELEGRAM_MAX_PER_ALERT = int(os.getenv("TELEGRAM_MAX_PER_ALERT", "5"))

PH = get_placeholder()

KA_OK_STATUS = {
    KleinanzeigenSearchStatus.SUCCESS_WITH_RESULTS,
    KleinanzeigenSearchStatus.SUCCESS_EMPTY,
}


# ---------------------------------------------------------------------------
# HAUPTSCHLEIFE: Alle Alerts prüfen
# ---------------------------------------------------------------------------
def check_all_alerts(db_connection) -> Dict[str, int]:
    """Prüft alle aktiven Alerts und sendet Benachrichtigungen."""
    print(f"\n{'=' * 70}")
    print(f"🔔 ALERT-CHECK GESTARTET: {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'=' * 70}\n")

    stats = {
        "alerts_checked": 0,
        "new_items_found": 0,
        "notifications_sent": 0,
        "errors": 0,
        "ebay_alerts": 0,
        "kleinanzeigen_alerts": 0,
    }

    cur = dict_cursor(db_connection)
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
            _safe_commit(db_connection)
        except Exception as e:
            aid = "?"
            try:
                aid = dict(alert_row).get("id", "?")
            except Exception:
                pass
            print(f"[!] Fehler bei Alert {aid}: {type(e).__name__}: {e}")
            stats["errors"] += 1
            traceback.print_exc()
            # Wichtig bei PostgreSQL: nach einem DB-Fehler ist die Transaktion
            # "abgebrochen". Ohne Rollback würden alle folgenden Alerts scheitern.
            _safe_rollback(db_connection)

    _safe_commit(db_connection)

    print(f"\n{'=' * 70}")
    print("[OK] ALERT-CHECK ABGESCHLOSSEN")
    print(f"{'=' * 70}")
    print("[*] Statistik:")
    print(f"   - Alerts geprüft: {stats['alerts_checked']}")
    print(f"   - eBay Alerts: {stats['ebay_alerts']}")
    print(f"   - Kleinanzeigen Alerts: {stats['kleinanzeigen_alerts']}")
    print(f"   - Neue Items: {stats['new_items_found']}")
    print(f"   - Benachrichtigungen gesamt: {stats['notifications_sent']}")
    print(f"   - Fehler: {stats['errors']}")
    print(f"{'=' * 70}\n")

    return stats


def _safe_commit(connection) -> None:
    try:
        connection.commit()
    except Exception as e:
        print(f"   [!] Commit fehlgeschlagen: {type(e).__name__}: {e}")


def _safe_rollback(connection) -> None:
    try:
        connection.rollback()
    except Exception as e:
        print(f"   [!] Rollback fehlgeschlagen: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# EINZELNER ALERT
# ---------------------------------------------------------------------------
def process_single_alert(alert_row, cursor, connection, stats: Dict[str, int]) -> None:
    """Verarbeitet einen einzelnen Alert."""

    alert = dict(alert_row)
    alert_id = alert["id"]
    user_email = alert["user_email"]

    source = (alert.get("source") or "ebay").strip().lower()
    if source not in ("ebay", "kleinanzeigen"):
        source = "ebay"

    # A source pause must not touch user settings, seen items or first-run state.
    if source == "kleinanzeigen" and not is_kleinanzeigen_enabled():
        print(f"   [Kleinanzeigen] Alert {alert_id} übersprungen: source_disabled")
        return

    try:
        terms = json.loads(alert.get("terms_json") or "[]")
    except Exception:
        terms = []

    try:
        filters = json.loads(alert.get("filters_json") or "{}")
    except Exception:
        filters = {}

    last_run = int(alert.get("last_run_ts") or 0)

    notify_telegram = bool(alert.get("notify_telegram", 1))
    notify_email = bool(alert.get("notify_email", 0))

    agent_name = f"Alert #{alert_id} ({source.upper()})"
    now = int(time.time())

    # --- Nutzer laden --------------------------------------------------------
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
        print(f"   [!] Alert {alert_id}: User nicht in DB gefunden")
        update_alert_timestamp(alert_id, now, cursor)
        return

    user_row = dict(user_row)

    telegram_chat_id = user_row.get("telegram_chat_id")
    telegram_enabled = bool(user_row.get("telegram_enabled"))
    telegram_verified = bool(user_row.get("telegram_verified"))
    plan_type = (user_row.get("plan_type") or "").strip().lower()
    is_premium = bool(user_row.get("is_premium"))
    has_paid_plan = plan_type in ("pro", "premium") or is_premium

    if not has_paid_plan and notify_telegram:
        print("   ℹ️ Telegram ist im FREE-Plan nicht erlaubt – deaktiviere für diesen Alert.")
        notify_telegram = False

    alert_interval_min = ALERT_INTERVAL_PREMIUM if has_paid_plan else ALERT_INTERVAL_FREE
    check_interval_seconds = alert_interval_min * 60

    print(f"[*] Alert {alert_id} ({agent_name})")
    print(f"   User: {user_email}")
    print(f"   Suchbegriffe: {len(terms)} konfiguriert")
    print(f"   Quelle: {source.upper()}")
    print(
        f"   Plan: '{plan_type or 'free'}', PremiumFlag={is_premium}, "
        f"Intervall={alert_interval_min} Min"
    )
    print(f"   Kanäle: Telegram={notify_telegram}, E-Mail={notify_email}")

    # --- Ist der Alert fällig? ----------------------------------------------
    if last_run > 0:
        elapsed_seconds = now - last_run
        due_after = check_interval_seconds - GRACE_SECONDS
        if elapsed_seconds < due_after:
            print(
                f"   ⏭️  Alert {alert_id} noch nicht fällig "
                f"(noch {due_after - elapsed_seconds}s, Intervall={alert_interval_min} Min)\n"
            )
            return

    stats["alerts_checked"] += 1

    # --- Kanäle prüfen -------------------------------------------------------
    if notify_telegram and not (telegram_chat_id and telegram_enabled and telegram_verified):
        print("   ℹ️ Telegram nicht aktiviert/verifiziert – Telegram wird für diesen Alert deaktiviert")
        notify_telegram = False

    if not notify_telegram and not notify_email:
        print("   ℹ️ Keine Benachrichtigungskanäle aktiv – es wird nichts gesendet.")

    # --- Suche ---------------------------------------------------------------
    print(f"   🔎 Führe {source.upper()}-Suche durch...")

    try:
        if source == "kleinanzeigen":
            stats["kleinanzeigen_alerts"] += 1
            ka_result = search_kleinanzeigen_for_alert(terms, filters)

            if ka_result.status == KleinanzeigenSearchStatus.SOURCE_DISABLED:
                # Also handle a pause detected by the shared search layer.
                stats["alerts_checked"] -= 1
                stats["kleinanzeigen_alerts"] -= 1
                print(f"   [Kleinanzeigen] Alert {alert_id} übersprungen: source_disabled")
                return

            if ka_result.status not in KA_OK_STATUS:
                print(
                    "   [!] Kleinanzeigen ist derzeit nicht verfügbar "
                    f"(classification={ka_result.status.value}, "
                    f"reason={ka_result.reason}, http={ka_result.http_status})."
                )
                stats["errors"] += 1
                _touch_after_error(alert_id, last_run, now, cursor)
                print()
                return

            items = ka_result.results
        else:
            stats["ebay_alerts"] += 1
            items = search_ebay_for_alert(terms, filters)

        if filters.get("only_main_product") or filters.get("smart_filter"):
            before = len(items)
            sf = SmartFilter()
            res = sf.filter_items(items, search_terms=terms)
            items = res["filtered_items"]
            print(f"      🧠 Smart-Filter: {before} -> {len(items)} Items")

        print(f"   [+] Gefunden: {len(items)} Items")

    except Exception as e:
        print(f"   [!] Suche fehlgeschlagen: classification=search_error ({type(e).__name__}: {e})")
        traceback.print_exc()
        stats["errors"] += 1
        _touch_after_error(alert_id, last_run, now, cursor)
        print()
        return

    # --- Neue Items erkennen -------------------------------------------------
    new_items = find_new_items(items, alert_id, user_email, source, cursor, connection)

    # Erstlauf: vorhandene Treffer nur vormerken, nicht melden
    if last_run == 0:
        print("   ℹ️ Erstlauf: vorhandene Treffer wurden nur vorgemerkt, keine Benachrichtigung.")
        update_alert_timestamp(alert_id, now, cursor)
        print()
        return

    if not new_items:
        print("   [+] Keine neuen Items")
        update_alert_timestamp(alert_id, now, cursor)
        print()
        return

    print(f"   🎯 {len(new_items)} NEUE Item(s)!")
    stats["new_items_found"] += len(new_items)

    # --- Benachrichtigungen --------------------------------------------------
    if notify_telegram:
        for item in new_items[:TELEGRAM_MAX_PER_ALERT]:
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

        if len(new_items) > TELEGRAM_MAX_PER_ALERT:
            print(
                f"   ℹ️ {len(new_items) - TELEGRAM_MAX_PER_ALERT} weitere Items "
                "nicht per Telegram gesendet (Spam-Schutz)"
            )

    if notify_email:
        email_ok = send_email_alert(user_email, alert, new_items, source)
        if email_ok:
            stats["notifications_sent"] += 1
        else:
            print("   [!] E-Mail-Versand für diesen Alert fehlgeschlagen")

    update_alert_timestamp(alert_id, now, cursor)
    print()


def _touch_after_error(alert_id: int, last_run: int, now: int, cursor) -> None:
    """
    Setzt nach einem Suchfehler den Zeitstempel, damit die Quelle nicht bei
    jedem Cron-Lauf bedrängt wird.
    Ausnahme: Beim Erstlauf (last_run == 0) bleibt der Zeitstempel bei 0,
    damit der Erstlauf später nachgeholt wird und die ersten Treffer nicht
    fälschlich als "neu" gemeldet werden.
    """
    if last_run > 0:
        update_alert_timestamp(alert_id, now, cursor)


# ---------------------------------------------------------------------------
# SUCHE
# ---------------------------------------------------------------------------
def search_kleinanzeigen_for_alert(
    terms: List[str],
    filters: Dict,
) -> KleinanzeigenSearchResult:
    """
    Führt die Kleinanzeigen-Suche für einen Alert aus.
    Nutzt services/kleinanzeigen_backend.py (liefert ein KleinanzeigenSearchResult).
    """
    try:
        from services.kleinanzeigen_backend import backend_search_kleinanzeigen

        result = backend_search_kleinanzeigen(terms, filters, per_page=20)
        print(
            "      [Kleinanzeigen] Suchstatus: "
            f"classification={result.status.value} items={len(result.results)}"
        )
        return result
    except Exception as e:
        print(
            "      [!] Kleinanzeigen-Suche Fehler: "
            f"classification=source_unavailable ({type(e).__name__}: {e})"
        )
        traceback.print_exc()
        return KleinanzeigenSearchResult(
            results=[],
            status=KleinanzeigenSearchStatus.SOURCE_UNAVAILABLE,
            reason="alert_wrapper_error",
            retryable=True,
        )


def search_ebay_for_alert(terms: List[str], filters: Dict) -> List[Dict]:
    """
    Führt die eBay-Suche für einen Alert aus.
    Nutzt services/ebay_backend.py.

    Fehler werden NICHT verschluckt, sondern weitergereicht. So zählt der
    Lauf als Fehler und der Zeitstempel wird korrekt behandelt, statt eine
    leere Trefferliste als "keine neuen Items" zu melden.
    """
    from services.ebay_backend import backend_search_ebay

    items, _total = backend_search_ebay(terms, filters, page=1, per_page=10)
    print(f"      [OK] eBay-Wrapper: {len(items)} Items zurückgegeben")
    return items


# ---------------------------------------------------------------------------
# NEUE ITEMS DETEKTIEREN
# ---------------------------------------------------------------------------
def find_new_items(
    items: List[Dict],
    alert_id: int,
    user_email: str,
    source: str,
    cursor,
    connection,
) -> List[Dict]:
    """Filtert neue Items heraus und markiert sie in alert_seen."""
    new_items: List[Dict] = []
    now = int(time.time())
    seen_in_this_run: set = set()

    print(f"      [DEBUG] Prüfe {len(items)} Items auf Neuheit für Alert {alert_id} ({source})")

    for item in items:
        item_id = str(item.get("id") or item.get("url") or item.get("title") or "")[:200]
        title = str(item.get("title") or "Ohne Titel")[:80]

        if not item_id:
            print(f"      [DEBUG] Überspringe Item ohne ID: {title}")
            continue

        # Doppelte innerhalb desselben Laufs ignorieren
        if item_id in seen_in_this_run:
            continue
        seen_in_this_run.add(item_id)

        cursor.execute(
            f"""
            SELECT item_id, first_seen, last_sent
            FROM alert_seen
            WHERE user_email = {PH}
              AND search_hash = {PH}
              AND src = {PH}
              AND item_id = {PH}
            """,
            (user_email, str(alert_id), source, item_id),
        )

        row = cursor.fetchone()

        if row:
            print(f"      [DEBUG] Bereits bekannt: {title} | item_id={item_id}")
            continue

        print(f"      [DEBUG] NEU erkannt: {title} | item_id={item_id}")
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

    _safe_commit(connection)

    print(f"      [DEBUG] Neu erkannt insgesamt: {len(new_items)}")
    return new_items


# ---------------------------------------------------------------------------
# E-MAIL
# ---------------------------------------------------------------------------
def send_email_alert(user_email: str, alert: Dict, new_items: List[Dict], source: str) -> bool:
    """Baut eine HTML-Mail mit den neuen Items und verschickt sie."""
    if not user_email or "@" not in user_email:
        print("   [!] Ungültige E-Mail-Adresse, überspringe E-Mail-Versand.")
        return False

    try:
        terms = json.loads(alert.get("terms_json") or "[]")
    except Exception:
        terms = []

    subject_terms = ", ".join(terms) if terms else "deinen Alert"
    src_label = "eBay Kleinanzeigen" if source == "kleinanzeigen" else "eBay"
    subject = f"🔔 Neue Treffer bei {src_label} für „{subject_terms}“"

    lines = [
        f"<h3>Neue Treffer für deinen {html.escape(src_label)}-Agent</h3>",
        "<p>Hier sind die neuesten Angebote, die zu deinem Alert passen:</p>",
        "<ul>",
    ]

    for item in new_items[:30]:
        title = html.escape(str(item.get("title") or "Ohne Titel"))
        price = html.escape(str(item.get("price") or item.get("price_text") or ""))
        url = html.escape(str(item.get("url") or item.get("item_url") or "#"), quote=True)
        src = html.escape(str(item.get("src") or src_label).title())

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
        return bool(ok)
    except Exception as e:
        print(f"   [!] Exception beim E-Mail-Versand: {type(e).__name__}: {e}")
        traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# TELEGRAM
# ---------------------------------------------------------------------------
def send_telegram_alert(
    chat_id: str,
    item: Dict,
    agent_name: str,
    source: str = "ebay",
    alert_id: int | None = None,
) -> bool:
    """Sendet eine Telegram-Benachrichtigung."""
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
            print("      ℹ️ Kein Bild verfügbar")

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
            print("      [!] Telegram-Nachricht fehlgeschlagen")

        return bool(success)

    except Exception as e:
        print(f"      [!] Fehler beim Senden: {type(e).__name__}: {e}")
        traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# TIMESTAMP / LOGGING
# ---------------------------------------------------------------------------
def update_alert_timestamp(alert_id: int, timestamp: int, cursor) -> None:
    """Aktualisiert last_run_ts eines Alerts."""
    cursor.execute(
        f"""
        UPDATE search_alerts
        SET last_run_ts = {PH}
        WHERE id = {PH}
        """,
        (timestamp, alert_id),
    )


def _log_alert_run(start_ts: int, end_ts: int, success: bool, stats: Dict | None) -> None:
    """Schreibt einen Eintrag in die Tabelle alert_runs."""
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
        print(f"   [!] Konnte alert_runs nicht loggen: {type(e).__name__}: {e}")
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# ENTRYPOINT
# ---------------------------------------------------------------------------
def run_alert_check():
    """Entry-Point für den Cron-Job."""
    start_ts = int(time.time())

    try:
        from services.email_alert_importer import check_and_import_email_alerts

        print("🔎 Prüfe auf neue E-Mail-Alerts (mobile.de / autoscout24)...")
        check_and_import_email_alerts()
    except Exception as e:
        print(f"[!] Fehler beim E-Mail-Import: {type(e).__name__}: {e}")

    conn = None
    try:
        conn = get_db()
        stats = check_all_alerts(conn)

        end_ts = int(time.time())
        _log_alert_run(start_ts, end_ts, True, stats)

        return {
            "success": True,
            "stats": stats,
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        end_ts = int(time.time())
        _log_alert_run(start_ts, end_ts, False, None)

        print(f"\n[!] KRITISCHER FEHLER im Alert-Check: {type(e).__name__}: {e}")
        traceback.print_exc()

        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
        }

    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# DIREKTSTART
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
