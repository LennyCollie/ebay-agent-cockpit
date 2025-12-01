# routes/alerts.py
from __future__ import annotations

import json
import time
from typing import List, Dict, Any

from flask import Blueprint, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user

from database import get_db  # gleiche DB wie alert_checker.py nutzt

bp = Blueprint("alerts", __name__)


def _bool_from_form(val: str | None) -> bool:
    if not val:
        return False
    return val.strip().lower() in {"1", "true", "on", "yes"}


@bp.post("/subscribe", endpoint="alerts_subscribe")
@login_required
def alerts_subscribe():
    """
    Legt einen neuen Such-Alert an.
    Erwartet dieselben Felder wie das Suchformular / search.html.
    """
    src = request.form

    # Bis zu 3 Suchbegriffe (wie im Template: q1, q2, q3)
    q1 = (src.get("q1") or src.get("q") or "").strip()
    q2 = (src.get("q2") or "").strip()
    q3 = (src.get("q3") or "").strip()

    terms: List[str] = [q for q in (q1, q2, q3) if q]

    if not terms:
        flash("Bitte mindestens einen Suchbegriff für den Alarm angeben.", "warning")
        return redirect(request.referrer or url_for("search.search_page"))

    # Basis-Filter
    price_min = (src.get("price_min") or "").strip()
    price_max = (src.get("price_max") or "").strip()
    sort = (src.get("sort") or "best").strip()

    # Bedingungen: aus hidden inputs "condition" (kann mehrfach vorkommen)
    conds: List[str] = []
    cond_vals = src.getlist("condition")
    for c in cond_vals:
        c = (c or "").strip().upper()
        if c:
            conds.append(c)

    # Location / weitere Filter könntest du später ergänzen
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

        now_ts = int(time.time())

        # alert_checker.py erwartet:
        #   id, user_email, terms_json, filters_json, last_run_ts, is_active
        cur.execute(
            """
            INSERT INTO search_alerts (user_email, terms_json, filters_json, last_run_ts, is_active)
            VALUES (?, ?, ?, ?, 1)
            """,
            (
                current_user.email,        # User wird über E-Mail identifiziert
                json.dumps(terms),         # z.B. ["iphone 13","macbook"]
                json.dumps(filters),       # Dict mit Filtern
                0,                         # last_run_ts = 0 -> beim nächsten Check sofort dran
            ),
        )
        conn.commit()
        conn.close()

        flash("Such-Alarm gespeichert. Du wirst bei neuen Treffern benachrichtigt.", "success")
    except Exception as e:
        current_app.logger.error(f"[alerts_subscribe] Fehler: {e}", exc_info=True)
        flash("Fehler beim Anlegen des Alerts.", "danger")

    # Zurück zur Suche / Ergebnisse
    return redirect(request.referrer or url_for("search.search_page", q1=q1))
