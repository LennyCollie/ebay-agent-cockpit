import json
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import StandardScaler
from models import SessionLocal, PriceForecast, PriceTrendAnalysis, PriceHistory, Alert, MLModel


class MLPredictionService:
    
    def __init__(self):
        self.min_samples = 10
        self.max_history_days = 365
    
    def generate_price_forecast(self, alert_id: int, user_id: int) -> Tuple[bool, str]:
        db = SessionLocal()
        try:
            alert = db.query(Alert).filter_by(id=alert_id, user_id=user_id).first()
            if not alert:
                return False, "Alert not found"
            
            history = db.query(PriceHistory).filter_by(
                alert_id=alert_id
            ).order_by(PriceHistory.checked_at.desc()).limit(self.max_history_days).all()
            
            if len(history) < self.min_samples:
                return False, "Insufficient data for prediction"
            
            history = list(reversed(history))
            
            prices = np.array([h.price for h in history]).reshape(-1, 1)
            days = np.arange(len(history)).reshape(-1, 1)
            
            scaler = StandardScaler()
            prices_scaled = scaler.fit_transform(prices)
            
            model = LinearRegression()
            model.fit(days, prices_scaled.flatten())
            
            future_days_7 = np.array([[len(history) + 7]])
            future_days_14 = np.array([[len(history) + 14]])
            future_days_30 = np.array([[len(history) + 30]])
            
            pred_7 = scaler.inverse_transform([[model.predict(future_days_7)[0]]])[0][0]
            pred_14 = scaler.inverse_transform([[model.predict(future_days_14)[0]]])[0][0]
            pred_30 = scaler.inverse_transform([[model.predict(future_days_30)[0]]])[0][0]
            
            current_price = float(alert.current_price) if alert.current_price else prices[-1][0]
            
            trend_direction = "upward" if model.coef_[0] > 0 else "downward"
            trend_strength = abs(float(model.coef_[0]))
            
            accuracy = self._calculate_model_accuracy(model, days, prices_scaled)
            
            forecast = db.query(PriceForecast).filter_by(alert_id=alert_id).first()
            
            if forecast:
                forecast.current_price = current_price
                forecast.predicted_price_7d = pred_7
                forecast.predicted_price_14d = pred_14
                forecast.predicted_price_30d = pred_30
                forecast.confidence_score_7d = 0.85
                forecast.confidence_score_14d = 0.75
                forecast.confidence_score_30d = 0.65
                forecast.trend_direction = trend_direction
                forecast.trend_strength = trend_strength
                forecast.recommendation = self._generate_recommendation(current_price, pred_7, pred_14, pred_30)
                forecast.last_trained = datetime.utcnow()
                forecast.training_samples = len(history)
                forecast.model_accuracy = accuracy
                forecast.updated_at = datetime.utcnow()
            else:
                forecast = PriceForecast(
                    alert_id=alert_id,
                    user_id=user_id,
                    forecast_type="linear_regression",
                    current_price=current_price,
                    predicted_price_7d=pred_7,
                    predicted_price_14d=pred_14,
                    predicted_price_30d=pred_30,
                    confidence_score_7d=0.85,
                    confidence_score_14d=0.75,
                    confidence_score_30d=0.65,
                    trend_direction=trend_direction,
                    trend_strength=trend_strength,
                    recommendation=self._generate_recommendation(current_price, pred_7, pred_14, pred_30),
                    last_trained=datetime.utcnow(),
                    training_samples=len(history),
                    model_accuracy=accuracy
                )
                db.add(forecast)
            
            db.commit()
            return True, f"Forecast generated with {accuracy:.2%} accuracy"
            
        except Exception as e:
            return False, f"Forecast generation error: {str(e)}"
        finally:
            db.close()
    
    def generate_trend_analysis(self, alert_id: int, user_id: int, period_days: int = 30) -> Tuple[bool, str]:
        db = SessionLocal()
        try:
            alert = db.query(Alert).filter_by(id=alert_id, user_id=user_id).first()
            if not alert:
                return False, "Alert not found"
            
            cutoff_date = datetime.utcnow() - timedelta(days=period_days)
            history = db.query(PriceHistory).filter(
                PriceHistory.alert_id == alert_id,
                PriceHistory.checked_at >= cutoff_date
            ).order_by(PriceHistory.checked_at).all()
            
            if len(history) < self.min_samples:
                return False, "Insufficient data for analysis"
            
            prices = np.array([h.price for h in history])
            
            min_price = float(np.min(prices))
            max_price = float(np.max(prices))
            avg_price = float(np.mean(prices))
            
            volatility = float(np.std(prices))
            
            days_array = np.arange(len(prices)).reshape(-1, 1)
            model = LinearRegression()
            model.fit(days_array, prices)
            trend_slope = float(model.coef_[0])
            
            price_drops = sum(1 for i in range(1, len(prices)) if prices[i] < prices[i-1])
            avg_drop_pct = sum((prices[i-1] - prices[i]) / prices[i-1] * 100 for i in range(1, len(prices)) if prices[i] < prices[i-1]) / max(price_drops, 1)
            
            best_buy_price = min_price
            good_deal_threshold = avg_price * 0.95
            fair_price_range_min = avg_price * 0.9
            fair_price_range_max = avg_price * 1.1
            
            analysis = db.query(PriceTrendAnalysis).filter_by(alert_id=alert_id, period_days=period_days).first()
            
            if analysis:
                analysis.min_price = min_price
                analysis.max_price = max_price
                analysis.avg_price = avg_price
                analysis.price_volatility = volatility
                analysis.trend_slope = trend_slope
                analysis.price_drops_count = price_drops
                analysis.avg_drop_percentage = avg_drop_pct
                analysis.best_buy_price = best_buy_price
                analysis.good_deal_threshold = good_deal_threshold
                analysis.fair_price_range_min = fair_price_range_min
                analysis.fair_price_range_max = fair_price_range_max
                analysis.updated_at = datetime.utcnow()
            else:
                analysis = PriceTrendAnalysis(
                    alert_id=alert_id,
                    user_id=user_id,
                    period_days=period_days,
                    min_price=min_price,
                    max_price=max_price,
                    avg_price=avg_price,
                    price_volatility=volatility,
                    trend_slope=trend_slope,
                    price_drops_count=price_drops,
                    avg_drop_percentage=avg_drop_pct,
                    best_buy_price=best_buy_price,
                    good_deal_threshold=good_deal_threshold,
                    fair_price_range_min=fair_price_range_min,
                    fair_price_range_max=fair_price_range_max
                )
                db.add(analysis)
            
            db.commit()
            return True, "Trend analysis completed"
            
        except Exception as e:
            return False, f"Analysis error: {str(e)}"
        finally:
            db.close()
    
    def _calculate_model_accuracy(self, model, X, y) -> float:
        y_pred = model.predict(X)
        mse = np.mean((y - y_pred) ** 2)
        rmse = np.sqrt(mse)
        return max(0, 1 - (rmse / (np.max(y) - np.min(y)))) if (np.max(y) - np.min(y)) > 0 else 0.5
    
    def _generate_recommendation(self, current: float, pred_7: float, pred_14: float, pred_30: float) -> str:
        if pred_7 < current * 0.95:
            return "Wait for lower prices"
        elif pred_7 > current * 1.05:
            return "Buy now before price increase"
        else:
            return "Current price is fair"


class TrendAnalysisService:
    
    def __init__(self):
        self.db = SessionLocal()
    
    def analyze_category_trends(self, category: str) -> Dict:
        try:
            alerts = self.db.query(Alert).filter_by(category=category).all()
            
            if not alerts:
                return {"error": "No data for category"}
            
            prices = []
            for alert in alerts[:100]:
                history = self.db.query(PriceHistory).filter_by(alert_id=alert.id).limit(30).all()
                prices.extend([h.price for h in history])
            
            if not prices:
                return {"error": "No price history"}
            
            prices = np.array(prices)
            
            return {
                "category": category,
                "average_price": float(np.mean(prices)),
                "price_range_min": float(np.min(prices)),
                "price_range_max": float(np.max(prices)),
                "volatility": float(np.std(prices)),
                "market_trend": "upward" if np.mean(prices[-10:]) > np.mean(prices[:10]) else "downward",
                "sample_count": len(prices)
            }
        finally:
            self.db.close()
