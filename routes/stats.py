# routes/stats.py
from flask import Blueprint, request, jsonify

bp = Blueprint("stats", __name__, url_prefix="/stats")


@bp.route("/api/price-history/<item_hash>")
def api_price_history_by_hash(item_hash):
    """API: Preis-Verlauf für Item via Hash (für Suchresultate)"""
    from services.price_tracker import get_price_history, get_item_stats

    days = int(request.args.get("days", 30))
    
    history = get_price_history(item_hash, days=days)
    stats = get_item_stats(item_hash)
    
    return jsonify({
        "history": history,
        "stats": stats
    })


@bp.route("/api/price-forecast/<item_hash>")
def api_price_forecast(item_hash):
    """API: ML-basierte Preis-Prognose mit Confidence Intervals"""
    from services.price_forecast import get_price_forecast
    
    forecast_days = int(request.args.get("days", 7))
    forecast_days = min(max(forecast_days, 3), 30)
    
    result = get_price_forecast(item_hash, forecast_days=forecast_days)
    
    return jsonify(result)


@bp.route("/api/recommendation/<item_hash>")
def api_recommendation(item_hash):
    """API: Detaillierte Kaufempfehlung mit Badge & Aktion"""
    from services.price_forecast import get_detailed_recommendation
    
    result = get_detailed_recommendation(item_hash)
    
    return jsonify(result)
