from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from models import SessionLocal, PriceForecast, PriceTrendAnalysis, MarketInsight
from services.ml_predictions import MLPredictionService, TrendAnalysisService
from datetime import datetime
import json

ml_bp = Blueprint("ml", __name__, url_prefix="/api/ml")
pred_service = MLPredictionService()
trend_service = TrendAnalysisService()


@ml_bp.route("/forecast/<int:alert_id>", methods=["GET"])
@login_required
def get_price_forecast(alert_id):
    db = SessionLocal()
    try:
        forecast = db.query(PriceForecast).filter_by(
            alert_id=alert_id,
            user_id=current_user.id
        ).first()
        
        if not forecast:
            return jsonify({
                "success": False,
                "message": "No forecast available. Training model..."
            }), 404
        
        return jsonify({
            "success": True,
            "data": {
                "id": forecast.id,
                "current_price": forecast.current_price,
                "predictions": {
                    "7_days": {
                        "price": forecast.predicted_price_7d,
                        "confidence": forecast.confidence_score_7d
                    },
                    "14_days": {
                        "price": forecast.predicted_price_14d,
                        "confidence": forecast.confidence_score_14d
                    },
                    "30_days": {
                        "price": forecast.predicted_price_30d,
                        "confidence": forecast.confidence_score_30d
                    }
                },
                "trend": {
                    "direction": forecast.trend_direction,
                    "strength": forecast.trend_strength
                },
                "recommendation": forecast.recommendation,
                "model_accuracy": forecast.model_accuracy,
                "training_samples": forecast.training_samples,
                "last_trained": forecast.last_trained.isoformat() if forecast.last_trained else None
            }
        })
    finally:
        db.close()


@ml_bp.route("/forecast/<int:alert_id>/generate", methods=["POST"])
@login_required
def generate_forecast(alert_id):
    success, message = pred_service.generate_price_forecast(alert_id, current_user.id)
    
    return jsonify({
        "success": success,
        "message": message
    }), 200 if success else 400


@ml_bp.route("/trends/<int:alert_id>", methods=["GET"])
@login_required
def get_trend_analysis(alert_id):
    db = SessionLocal()
    try:
        analysis = db.query(PriceTrendAnalysis).filter_by(
            alert_id=alert_id,
            user_id=current_user.id
        ).order_by(PriceTrendAnalysis.period_days.desc()).first()
        
        if not analysis:
            return jsonify({
                "success": False,
                "message": "No trend analysis available"
            }), 404
        
        return jsonify({
            "success": True,
            "data": {
                "id": analysis.id,
                "period_days": analysis.period_days,
                "price_stats": {
                    "min": analysis.min_price,
                    "max": analysis.max_price,
                    "avg": analysis.avg_price,
                    "volatility": analysis.price_volatility
                },
                "trend": {
                    "slope": analysis.trend_slope,
                    "price_drops": analysis.price_drops_count,
                    "avg_drop_percentage": analysis.avg_drop_percentage
                },
                "recommendations": {
                    "best_buy_price": analysis.best_buy_price,
                    "good_deal_threshold": analysis.good_deal_threshold,
                    "fair_price_range": {
                        "min": analysis.fair_price_range_min,
                        "max": analysis.fair_price_range_max
                    }
                },
                "updated_at": analysis.updated_at.isoformat()
            }
        })
    finally:
        db.close()


@ml_bp.route("/trends/<int:alert_id>/generate", methods=["POST"])
@login_required
def generate_trend_analysis(alert_id):
    data = request.get_json() or {}
    period_days = data.get("period_days", 30)
    
    success, message = pred_service.generate_trend_analysis(
        alert_id,
        current_user.id,
        period_days
    )
    
    return jsonify({
        "success": success,
        "message": message
    }), 200 if success else 400


@ml_bp.route("/market-insights/<category>", methods=["GET"])
@login_required
def get_market_insights(category):
    db = SessionLocal()
    try:
        insight = db.query(MarketInsight).filter_by(
            user_id=current_user.id,
            category=category
        ).first()
        
        if not insight:
            return jsonify({
                "success": False,
                "message": "No insights available"
            }), 404
        
        return jsonify({
            "success": True,
            "data": {
                "id": insight.id,
                "category": insight.category,
                "market_trend": insight.market_trend,
                "prices": {
                    "average": insight.average_price,
                    "range": {
                        "min": insight.price_range_min,
                        "max": insight.price_range_max
                    }
                },
                "supply_demand": {
                    "demand": insight.demand_level,
                    "supply": insight.supply_level,
                    "competitive_intensity": insight.competitive_intensity
                },
                "opportunities": json.loads(insight.opportunities) if insight.opportunities else [],
                "risks": json.loads(insight.risks) if insight.risks else [],
                "generated_at": insight.generated_at.isoformat()
            }
        })
    finally:
        db.close()


@ml_bp.route("/market-insights/<category>/generate", methods=["POST"])
@login_required
def generate_market_insights(category):
    db = SessionLocal()
    try:
        insights_data = trend_service.analyze_category_trends(category)
        
        if "error" in insights_data:
            return jsonify({
                "success": False,
                "message": insights_data["error"]
            }), 400
        
        insight = db.query(MarketInsight).filter_by(
            user_id=current_user.id,
            category=category
        ).first()
        
        opportunities = [
            "High price volatility - good trading opportunities",
            "Stable demand - reliable market",
            "Price trend analysis available"
        ]
        
        risks = [
            "Market saturation increasing",
            "Competition rising"
        ]
        
        if insight:
            insight.market_trend = insights_data["market_trend"]
            insight.average_price = insights_data["average_price"]
            insight.price_range_min = insights_data["price_range_min"]
            insight.price_range_max = insights_data["price_range_max"]
            insight.opportunities = json.dumps(opportunities)
            insight.risks = json.dumps(risks)
            insight.generated_at = datetime.utcnow()
        else:
            insight = MarketInsight(
                user_id=current_user.id,
                category=category,
                market_trend=insights_data["market_trend"],
                average_price=insights_data["average_price"],
                price_range_min=insights_data["price_range_min"],
                price_range_max=insights_data["price_range_max"],
                demand_level="medium",
                supply_level="medium",
                competitive_intensity="medium",
                opportunities=json.dumps(opportunities),
                risks=json.dumps(risks)
            )
            db.add(insight)
        
        db.commit()
        
        return jsonify({
            "success": True,
            "message": "Market insights generated",
            "data": insights_data
        }), 201
    finally:
        db.close()


@ml_bp.route("/batch-forecast", methods=["POST"])
@login_required
def batch_generate_forecasts():
    data = request.get_json() or {}
    alert_ids = data.get("alert_ids", [])
    
    results = []
    for alert_id in alert_ids[:20]:
        success, message = pred_service.generate_price_forecast(alert_id, current_user.id)
        results.append({
            "alert_id": alert_id,
            "success": success,
            "message": message
        })
    
    return jsonify({
        "success": True,
        "data": results
    })


@ml_bp.route("/stats", methods=["GET"])
@login_required
def get_ml_stats():
    db = SessionLocal()
    try:
        forecast_count = db.query(PriceForecast).filter_by(user_id=current_user.id).count()
        analysis_count = db.query(PriceTrendAnalysis).filter_by(user_id=current_user.id).count()
        insights_count = db.query(MarketInsight).filter_by(user_id=current_user.id).count()
        
        return jsonify({
            "success": True,
            "data": {
                "forecasts": forecast_count,
                "trend_analyses": analysis_count,
                "market_insights": insights_count,
                "total_predictions": forecast_count + analysis_count + insights_count
            }
        })
    finally:
        db.close()
