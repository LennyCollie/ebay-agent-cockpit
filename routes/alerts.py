# routes/alerts.py
from __future__ import annotations

import json
import time
from typing import List, Dict, Any

from flask import (
    Blueprint,
    request,
    redirect,
    url_for,
    flash,
    current_app,
    jsonify  # ⭐ FEHLTE!
)
from flask_login import login_required, current_user

from database import get_db

bp = Blueprint("alerts", __name__)


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
        cur.execute("""
            SELECT id FROM search_alerts
            WHERE id = ? AND user_email = ?
        """, (alert_id, current_user.email))

        alert = cur.fetchone()

        if not alert:
            conn.close()
            return jsonify({
                'success': False,
                'error': 'Alert nicht gefunden oder gehört dir nicht'
            }), 404

        # Alert deaktivieren
        cur.execute("""
            UPDATE search_alerts
            SET is_active = 0
            WHERE id = ?
        """, (alert_id,))

        conn.commit()
        conn.close()

        flash("Alert erfolgreich gelöscht!", "success")

        # JSON oder Redirect
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': 'Alert gelöscht'})
        else:
            return redirect(url_for('dashboard'))

    except Exception as e:
        current_app.logger.error(f"Alert-Löschen Fehler: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.post("/subscribe", endpoint="alerts_subscribe")
@login_required
def alerts_subscribe():
    """
    Legt einen neuen Such-Alert an.
    ⭐ ERWEITERT: Unterstützt jetzt auch Kleinanzeigen via 'source' Parameter!
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

    # ⭐ NEU: Source-Parameter (ebay oder kleinanzeigen)
    source = (src.get("source") or "ebay").strip().lower()

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

    try:
        conn = get_db()
        cur = conn.cursor()

        # ⭐ ERWEITERT: Mit source-Spalte!
        cur.execute(
            """
            INSERT INTO search_alerts
            (user_email, terms_json, filters_json, source, last_run_ts, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (
                current_user.email,
                json.dumps(terms),
                json.dumps(filters),
                source,  # ⭐ NEU!
                0,
            ),
        )
        conn.commit()
        conn.close()

        source_name = "Kleinanzeigen" if source == "kleinanzeigen" else "eBay"
        flash(f"✅ {source_name}-Alarm gespeichert! Du wirst bei neuen Treffern benachrichtigt.", "success")

    except Exception as e:
        current_app.logger.error(f"[alerts_subscribe] Fehler: {e}", exc_info=True)
        flash("Fehler beim Anlegen des Alerts.", "danger")

    return redirect(request.referrer or url_for("search.search_page", q1=q1))
