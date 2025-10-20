# routes/stats.py
from flask import Blueprint, render_template, request, jsonify
from utils.price_analyzer import get_price_trend, get_popular_searches

bp = Blueprint("stats", __name__, url_prefix="/stats")


@bp.route("/price-trend")
def price_trend():
    """Zeigt Preis-Trend für Suchbegriff"""
    search_term = request.args.get("q", "").strip()
    days = int(request.args.get("days", 30))

    trend = None
    popular = get_popular_searches(limit=10)

    if search_term:
        trend = get_price_trend(search_term, days=days)

    return render_template(
        "price_history.html",
        trend=trend,
        popular_searches=popular
    )


@bp.route("/api/item-history/<int:watched_item_id>")
def api_item_history(watched_item_id):
    """API: Preis-Historie für beobachtetes Item"""
    from utils.price_analyzer import get_item_price_history

    days = int(request.args.get("days", 30))
    history = get_item_price_history(watched_item_id, days=days)

    return jsonify(history)
