# routes/admin.py
from __future__ import annotations

import time
from datetime import datetime

from flask import Blueprint, render_template, abort
from flask_login import login_required, current_user

from database import get_db, get_placeholder

bp = Blueprint("admin", __name__, url_prefix="/admin")
PH = get_placeholder()


def admin_required(f):
    from functools import wraps

    @wraps(f)
    def wrapper(*args, **kwargs):
        # falls du kein is_admin-Feld hast, das hier entsprechend anpassen
        if not current_user.is_authenticated or not getattr(current_user, "is_admin", False):
            abort(403)
        return f(*args, **kwargs)

    return wrapper


@bp.route("/dashboard")
@login_required
@admin_required
def dashboard():
    conn = get_db()
    cur = conn.cursor()

    # Basis-Stats
    cur.execute("SELECT COUNT(*) FROM users")
    user_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM users WHERE is_premium = 1")
    premium_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM search_alerts")
    alert_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM search_alerts WHERE is_active = 1")
    active_alerts = cur.fetchone()[0]

    # letzte Cron-Läufe (z.B. 20)
    try:
        cur.execute(
            """
            SELECT
                id,
                started_at,
                finished_at,
                success,
                alerts_checked,
                new_items_found,
                notifications_sent,
                errors,
                ebay_alerts,
                kleinanzeigen_alerts
            FROM alert_runs
            ORDER BY id DESC
            LIMIT 20
            """
        )
        run_rows = cur.fetchall()
    except Exception:
        run_rows = []

    conn.close()

    cron_runs = []
    for r in run_rows:
        (
            rid,
            started_at,
            finished_at,
            success,
            alerts_checked,
            new_items_found,
            notifications_sent,
            errors,
            ebay_alerts,
            kleinanzeigen_alerts,
        ) = r

        started_dt = datetime.fromtimestamp(int(started_at))
        finished_dt = datetime.fromtimestamp(int(finished_at))
        duration_s = max(0, int(finished_at) - int(started_at))

        cron_runs.append(
            {
                "id": rid,
                "started_dt": started_dt,
                "finished_dt": finished_dt,
                "duration_s": duration_s,
                "success": bool(success),
                "alerts_checked": alerts_checked,
                "new_items_found": new_items_found,
                "notifications_sent": notifications_sent,
                "errors": errors,
                "ebay_alerts": ebay_alerts,
                "kleinanzeigen_alerts": kleinanzeigen_alerts,
            }
        )

    return render_template(
        "admin/dashboard.html",
        user_count=user_count,
        premium_count=premium_count,
        alert_count=alert_count,
        active_alerts=active_alerts,
        cron_runs=cron_runs,
    )


@bp.route("/community-links")
@login_required
@admin_required
def community_links():
    return render_template("admin/community_links.html")


@bp.route("/coupons")
@login_required
def coupons():
    return render_template("admin/coupons.html")


@bp.route("/analytics")
@login_required
def analytics():
    return render_template("admin/analytics.html")


@bp.route("/achievements")
@login_required
@admin_required
def achievements():
    return render_template("admin/achievements.html")


@bp.route("/webhooks")
@login_required
@admin_required
def webhooks():
    return render_template("admin/webhooks.html")


@bp.route("/api-management")
@login_required
@admin_required
def api_management():
    return render_template("admin/api_management.html")
