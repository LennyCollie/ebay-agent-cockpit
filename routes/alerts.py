from __future__ import annotations

import json
import time
from datetime import datetime
from typing import List, Dict, Any

from flask import (
    Blueprint,
    request,
    redirect,
    url_for,
    flash,
    current_app,
    jsonify,
    render_template,
)
from flask_login import login_required, current_user

from alert_checker import (
    ALERT_INTERVAL_FREE,
    ALERT_INTERVAL_PREMIUM,
    search_ebay_for_alert,
    search_kleinanzeigen_for_alert,
)
from database import get_db, get_placeholder

bp = Blueprint("alerts", __name__)

def _compute_plan_info(plan_type_raw, is_premium, last_run_ts: int):
    plan_type = (plan_type_raw or "").strip().lower()
    is_premium_flag = bool(is_premium)

    if plan_type in ("pro", "premium") or is_premium_flag:
        interval_min = ALERT_INTERVAL_PREMIUM
    else:
        interval_min = ALERT_INTERVAL_FREE

    now_ts = int(time.time())
    next_run_in_min = None
    if last_run_ts:
        next_due_ts = int(last_run_ts) + interval_min * 60
        if next_due_ts > now_ts:
            next_run_in_min = int((next_due_ts - now_ts) / 60)
        else:
            next_run_in_min = 0

    # Label für Anzeige
    if plan_type in ("pro", "premium"):
        plan_label = plan_type.upper()
    elif is_premium_flag:
        plan_label = "PREMIUM"
    else:
        plan_label = "FREE"

    return {
        "plan_type": plan_type or "free",
        "is_premium": is_premium_flag,
        "interval_min": interval_min,
        "next_run_in_min": next_run_in_min,
        "plan_label": plan_label,
    }


PH = get_placeholder()




def _bool_from_form(val: str | None) -> bool:
    if not val:
        return False
    return val.strip().lower() in {"1", "true", "on", "yes"}


@bp.route("/delete/<int:alert_id>", methods=["POST", "GET"])
@login_required
def delete_alert(alert_id):
    """Löscht einen Search-Alert"""
    try:
        conn = get_db()
        cur = conn.cursor()

        # Prüfe ob Alert dem User gehört
        cur.execute(
            f"""
            SELECT id FROM search_alerts
            WHERE id = {PH} AND user_email = {PH}
            """,
            (alert_id, current_user.email),
        )

        alert = cur.fetchone()

        if not alert:
            conn.close()
            return jsonify({
                'success': False,
                'error': 'Alert nicht gefunden oder gehört dir nicht'
            }), 404

        # Alert deaktivieren
        cur.execute(
            f"""
            UPDATE search_alerts
            SET is_active = 0
            WHERE id = {PH}
            """,
            (alert_id,),
        )

        conn.commit()
        conn.close()

        flash("Alert erfolgreich gelöscht!", "success")

        # JSON oder Redirect
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': 'Alert gelöscht'})
        else:
            return redirect(request.referrer or url_for('alerts.manage_alerts'))

    except Exception as e:
        current_app.logger.error(f"Alert-Löschen Fehler: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route("/manage", methods=["GET"])
@login_required
def manage_alerts():
    """
    Zeigt alle Alerts des aktuellen Users inkl. Plan/Intervall-Infos.
    """
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        f"""
        SELECT
            a.id,
            a.terms_json,
            a.filters_json,
            a.source,
            a.last_run_ts,
            a.is_active,
            COALESCE(a.notify_email, 0)   AS notify_email,
            COALESCE(a.notify_telegram, 0) AS notify_telegram,
            u.plan_type,
            u.is_premium
        FROM search_alerts a
        JOIN users u ON a.user_email = u.email
        WHERE a.user_email = {PH}
        ORDER BY a.id DESC
        """,
        (current_user.email,),
    )
    rows = cur.fetchall()
    conn.close()

    alerts = []
    now_ts = int(time.time())

    for row in rows:
        (
            alert_id,
            terms_json,
            filters_json,
            source,
            last_run_ts,
            is_active,
            notify_email,
            notify_telegram,
            plan_type,
            is_premium,
        ) = row

        try:
            terms = json.loads(terms_json or "[]")
        except Exception:
            terms = []

        try:
            filters = json.loads(filters_json or "{}")
        except Exception:
            filters = {}

        last_run_ts = int(last_run_ts or 0)
        last_run_dt = None
        if last_run_ts:
            try:
                last_run_dt = datetime.fromtimestamp(last_run_ts)
            except Exception:
                last_run_dt = None

        plan_type = (plan_type or "").strip().lower()
        is_premium_flag = bool(is_premium)

        # Intervall nach Plan-Logik (wie in alert_checker)
        if plan_type in ("pro", "premium") or is_premium_flag:
            interval_min = ALERT_INTERVAL_PREMIUM
        else:
            interval_min = ALERT_INTERVAL_FREE

        # Nächster geplanter Check (ungefähr)
        next_run_in_min = None
        if last_run_ts:
            next_due_ts = last_run_ts + interval_min * 60
            if next_due_ts > now_ts:
                next_run_in_min = int((next_due_ts - now_ts) / 60)
            else:
                next_run_in_min = 0

        alerts.append(
            {
                "id": alert_id,
                "terms": terms,
                "filters": filters,
                "source": (source or "ebay"),
                "is_active": bool(is_active),
                "notify_email": bool(notify_email),
                "notify_telegram": bool(notify_telegram),
                "plan_type": plan_type or "free",
                "is_premium": is_premium_flag,
                "interval_min": interval_min,
                "last_run_dt": last_run_dt,
                "next_run_in_min": next_run_in_min,
            }
        )

    return render_template("alerts/manage.html", alerts=alerts)

@bp.route("/results/<int:alert_id>", methods=["GET"])
@login_required
def alert_results(alert_id: int):
    """
    Detailseite für einen Alert:
    - zeigt aktuelle Angebote (eBay oder Kleinanzeigen)
    - markiert Items als 'neu' oder 'bereits gesehen' anhand alert_seen
    """
    conn = get_db()
    cur = conn.cursor()

    # Alert + User-Plan laden (und Ownership prüfen)
    cur.execute(
        f"""
        SELECT
            a.id,
            a.terms_json,
            a.filters_json,
            a.source,
            a.last_run_ts,
            a.is_active,
            COALESCE(a.notify_email, 0)   AS notify_email,
            COALESCE(a.notify_telegram, 0) AS notify_telegram,
            u.plan_type,
            u.is_premium
        FROM search_alerts a
        JOIN users u ON a.user_email = u.email
        WHERE a.id = {PH} AND a.user_email = {PH}
        """,
        (alert_id, current_user.email),
    )
    row = cur.fetchone()

    if not row:
        conn.close()
        flash("Alert nicht gefunden oder gehört dir nicht.", "danger")
        return redirect(url_for("alerts.manage_alerts"))

    (
        aid,
        terms_json,
        filters_json,
        source,
        last_run_ts,
        is_active,
        notify_email,
        notify_telegram,
        plan_type,
        is_premium,
    ) = row

    try:
        terms = json.loads(terms_json or "[]")
    except Exception:
        terms = []

    try:
        filters = json.loads(filters_json or "{}")
    except Exception:
        filters = {}

    last_run_ts = int(last_run_ts or 0)
    last_run_dt = datetime.fromtimestamp(last_run_ts) if last_run_ts else None

    plan_info = _compute_plan_info(plan_type, is_premium, last_run_ts)

    # ------------------------------------------------------------
    # Suche ausführen (aktuelle Angebote)
    # ------------------------------------------------------------
    source_norm = (source or "ebay").strip().lower()
    if source_norm == "kleinanzeigen":
        items = search_kleinanzeigen_for_alert(terms, filters)
    else:
        items = search_ebay_for_alert(terms, filters)

    # ------------------------------------------------------------
    # Items mit "gesehen"/"neu" anreichern
    # ------------------------------------------------------------
    enriched_items = []

    for item in items:
        # gleiche ID-Logik wie im alert_checker
        item_id = str(
            item.get("id")
            or item.get("url", "")
            or item.get("title", "")
        )[:200]

        if not item_id:
            continue

        cur.execute(
            f"""
            SELECT first_seen, last_sent
            FROM alert_seen
            WHERE user_email = {PH}
              AND search_hash = {PH}
              AND src = {PH}
              AND item_id = {PH}
            """,
            (current_user.email, str(alert_id), source_norm, item_id),
        )
        seen_row = cur.fetchone()

        seen = False
        first_seen_dt = None
        last_sent_dt = None

        if seen_row:
            seen = True
            first_seen_ts, last_sent_ts = seen_row
            if first_seen_ts:
                first_seen_dt = datetime.fromtimestamp(int(first_seen_ts))
            if last_sent_ts:
                last_sent_dt = datetime.fromtimestamp(int(last_sent_ts))

        # generische Anzeige-Felder aufbereiten
        title = item.get("title") or "Ohne Titel"
        price = item.get("price") or item.get("price_text") or ""
        url = item.get("url") or item.get("item_url") or "#"
        img = item.get("image_url") or item.get("img") or ""
        src_label = (item.get("src") or source_norm).lower()

        item["display_title"] = title
        item["display_price"] = price
        item["display_url"] = url
        item["display_img"] = img
        item["display_src"] = src_label
        item["seen"] = seen
        item["first_seen_dt"] = first_seen_dt
        item["last_sent_dt"] = last_sent_dt

        enriched_items.append(item)

    conn.close()

    alert_ctx = {
        "id": aid,
        "terms": terms,
        "filters": filters,
        "source": source_norm,
        "is_active": bool(is_active),
        "notify_email": bool(notify_email),
        "notify_telegram": bool(notify_telegram),
        "last_run_dt": last_run_dt,
        **plan_info,
    }

    return render_template(
        "alerts/results.html",
        alert=alert_ctx,
        items=enriched_items,
    )




@bp.post("/toggle/<int:alert_id>")
@login_required
def toggle_alert(alert_id):
    """
    Aktiviert/deaktiviert einen Alert des aktuellen Users.
    """
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            f"""
            SELECT is_active
            FROM search_alerts
            WHERE id = {PH} AND user_email = {PH}
            """,
            (alert_id, current_user.email),
        )
        row = cur.fetchone()

        if not row:
            conn.close()
            flash("Alert nicht gefunden oder gehört dir nicht.", "danger")
            return redirect(request.referrer or url_for("alerts.manage_alerts"))

        current_state = row[0]
        new_state = 0 if current_state else 1

        cur.execute(
            f"UPDATE search_alerts SET is_active = {PH} WHERE id = {PH}",
            (new_state, alert_id),
        )
        conn.commit()
        conn.close()

        msg = "Alert aktiviert." if new_state else "Alert pausiert."
        flash(msg, "success")

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": True, "is_active": bool(new_state)})

        return redirect(request.referrer or url_for("alerts.manage_alerts"))

    except Exception as e:
        current_app.logger.error(f"Alert-Toggle Fehler: {e}")
        flash("Fehler beim Aktualisieren des Alerts.", "danger")
        return redirect(request.referrer or url_for("alerts.manage_alerts"))




@bp.post("/subscribe", endpoint="alerts_subscribe")
@login_required
def alerts_subscribe():
    """
    Legt einen neuen Such-Alert an.
    ⭐ ERWEITERT: Unterstützt eBay, Kleinanzeigen oder beide (source=both).
    """
    src = request.form

    # Suchbegriffe
    q1 = (src.get("q1") or src.get("q") or "").strip()
    q2 = (src.get("q2") or "").strip()
    q3 = (src.get("q3") or "").strip()

    terms: List[str] = [q for q in (q1, q2, q3) if q]

    if not terms:
        flash("Bitte mindestens einen Suchbegriff für den Alarm angeben.", "warning")
        return redirect(request.referrer or url_for("search.search_page"))

    # Source-Parameter (ebay / kleinanzeigen / both)
    source_raw = (src.get("source") or "ebay").strip().lower()
    if source_raw == "both":
        sources = ["ebay", "kleinanzeigen"]
    else:
        sources = [source_raw]

    # Filter
    price_min = (src.get("price_min") or "").strip()
    price_max = (src.get("price_max") or "").strip()
    sort = (src.get("sort") or "best").strip()

    conds: List[str] = []
    cond_vals = src.getlist("condition")
    for c in cond_vals:
        c = (c or "").strip().upper()
        if c:
            conds.append(c)

    location_country = (src.get("location_country") or "DE").strip().upper()
    listing_type = (src.get("listing_type") or "all").strip()

    filters: Dict[str, Any] = {
        "price_min": price_min or None,
        "price_max": price_max or None,
        "conditions": conds,
        "listing_type": listing_type,
        "location_country": location_country,
        "free_shipping": _bool_from_form(src.get("free_shipping")),
        "top_rated_only": _bool_from_form(src.get("top_rated_only")),
        "returns_accepted": _bool_from_form(src.get("returns_accepted")),
        "sort": sort,
    }

    notify_email = 1 if src.get("notify_email") else 0
    notify_telegram = 1 if src.get("notify_telegram") else 0

    try:
        conn = get_db()
        cur = conn.cursor()

        for source in sources:
            cur.execute(
                f"""
                INSERT INTO search_alerts
                    (user_email, terms_json, filters_json, source, last_run_ts, is_active, notify_email, notify_telegram)
                VALUES
                    ({PH}, {PH}, {PH}, {PH}, {PH}, 1, {PH}, {PH})
                """,
                (
                    current_user.email,
                    json.dumps(terms),
                    json.dumps(filters),
                    source,
                    0,
                    notify_email,
                    notify_telegram,
                ),
            )

        conn.commit()
        conn.close()

        source_label = {
            "ebay": "eBay",
            "kleinanzeigen": "Kleinanzeigen",
        }

        if len(sources) == 2:
            source_name = "eBay & Kleinanzeigen"
        else:
            source_name = source_label.get(sources[0], "eBay")

        flash(f"[OK] {source_name}-Alarm gespeichert! Du wirst bei neuen Treffern benachrichtigt.", "success")

    except Exception as e:
        current_app.logger.error(f"[alerts_subscribe] Fehler: {e}", exc_info=True)
        flash("Fehler beim Anlegen des Alerts.", "danger")

    return redirect(request.referrer or url_for("search.search_page", q1=q1))

