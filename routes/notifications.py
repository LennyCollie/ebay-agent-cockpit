"""
Routes für Smart Notifications (Price Alerts)
"""
from flask import Blueprint, request, jsonify, render_template
from flask_login import current_user, login_required
from services.notifications import (
    create_price_alert,
    get_active_alerts,
    delete_alert,
    toggle_alert,
    get_alert_triggers,
    get_alert_statistics
)


bp = Blueprint("notifications", __name__, url_prefix="/notifications")


@bp.route("/alerts", methods=["GET"])
@login_required
def list_alerts():
    """Zeigt alle aktiven Alerts des Benutzers"""
    alerts = get_active_alerts(current_user.id)
    return render_template("alerts_list.html", alerts=alerts)


@bp.route("/api/alerts", methods=["GET"])
@login_required
def api_list_alerts():
    """API: Alle aktiven Alerts abrufen"""
    alerts = get_active_alerts(current_user.id)
    return jsonify(alerts)


@bp.route("/api/alerts", methods=["POST"])
@login_required
def api_create_alert():
    """API: Neuen Price Alert erstellen"""
    data = request.json or {}

    item_title = (data.get("item_title") or "").strip()
    target_price = data.get("target_price")
    search_term = (data.get("search_term") or "").strip()
    threshold_percent = data.get("threshold_percent")

    if not item_title or target_price is None:
        return jsonify({"error": "item_title und target_price erforderlich"}), 400

    success = create_price_alert(
        user_id=current_user.id,
        item_title=item_title,
        target_price=float(target_price),
        search_term=search_term,
        threshold_percent=float(threshold_percent) if threshold_percent else None
    )

    if success:
        return jsonify({"success": True, "message": "Alert erstellt"}), 201
    else:
        return jsonify({"error": "Fehler beim Erstellen des Alerts"}), 500


@bp.route("/api/alerts/<int:alert_id>", methods=["DELETE"])
@login_required
def api_delete_alert(alert_id):
    """API: Alert löschen"""
    success = delete_alert(alert_id, current_user.id)

    if success:
        return jsonify({"success": True, "message": "Alert gelöscht"}), 200
    else:
        return jsonify({"error": "Alert nicht gefunden oder nicht berechtigt"}), 404

@bp.route("/dashboard", methods=["GET"])
@login_required
def dashboard():
    alerts = get_active_alerts(current_user.id)
    alert_data = []
    for alert in alerts:
        stats = get_alert_statistics(alert['id'])
        alert_data.append({**alert, 'stats': stats})
    return render_template("alerts_dashboard.html", alerts=alert_data)


@bp.route("/api/alerts/<int:alert_id>/triggers", methods=["GET"])
@login_required
def api_alert_triggers(alert_id):
    alert = get_active_alerts(current_user.id)
    alert_ids = [a['id'] for a in alert]
    if alert_id not in alert_ids:
        return jsonify({"error": "nicht berechtigt"}), 404
    triggers = get_alert_triggers(alert_id, limit=request.args.get("limit", 100, type=int))
    return jsonify(triggers)


@bp.route("/api/alerts/<int:alert_id>/stats", methods=["GET"])
@login_required
def api_alert_stats(alert_id):
    alert = get_active_alerts(current_user.id)
    alert_ids = [a['id'] for a in alert]
    if alert_id not in alert_ids:
        return jsonify({"error": "nicht berechtigt"}), 404
    return jsonify(get_alert_statistics(alert_id))



@bp.route("/api/alerts/<int:alert_id>/toggle", methods=["PATCH"])
@login_required
def api_toggle_alert(alert_id):
    """API: Alert aktivieren/deaktivieren"""
    data = request.json or {}
    active = data.get("active", True)

    success = toggle_alert(alert_id, current_user.id, bool(active))

    if success:
        return jsonify({"success": True, "message": f"Alert {'aktiviert' if active else 'deaktiviert'}"}), 200
    else:
        return jsonify({"error": "Fehler beim Aktualisieren des Alerts"}), 500
