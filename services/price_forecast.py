"""
Price Forecast Service - ML-basierte Preis-Prognosen mit scikit-learn
Funktionen: Moving Average, Linear Regression, Trend-Extrapolation, Confidence Intervals
"""
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import numpy as np
from database import get_db, dict_cursor, get_placeholder
import warnings
warnings.filterwarnings('ignore')

log = logging.getLogger(__name__)

try:
    from sklearn.linear_model import LinearRegression
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    log.warning("[Price Forecast] scikit-learn not available - forecasting disabled")


def get_price_history_raw(item_hash: str, days: int = 60) -> List[Dict]:
    """
    Holt rohe Preisdaten aus der Datenbank
    
    Args:
        item_hash: Hash des Items
        days: Anzahl Tage zurück
    
    Returns:
        Liste mit Preis-Einträgen (sortiert nach Datum)
    """
    try:
        conn = get_db()
        cur = dict_cursor(conn) if hasattr(conn, 'cursor') else conn.cursor()
        ph = get_placeholder()
        
        if ph == "%s":  # PostgreSQL
            cur.execute(f"""
                SELECT 
                    DATE(last_seen) as date,
                    AVG(price_current) as price,
                    MIN(price_min) as min_price,
                    MAX(price_max) as max_price,
                    COUNT(*) as data_points
                FROM item_price_history
                WHERE item_hash = {ph}
                AND last_seen >= NOW() - INTERVAL '{days} days'
                GROUP BY DATE(last_seen)
                ORDER BY DATE(last_seen) ASC
            """, (item_hash,))
        else:  # SQLite
            cur.execute(f"""
                SELECT 
                    DATE(last_seen) as date,
                    AVG(price_current) as price,
                    MIN(price_min) as min_price,
                    MAX(price_max) as max_price,
                    COUNT(*) as data_points
                FROM item_price_history
                WHERE item_hash = {ph}
                AND last_seen >= datetime('now', '-{days} days')
                GROUP BY DATE(last_seen)
                ORDER BY DATE(last_seen) ASC
            """, (item_hash,))
        
        rows = cur.fetchall()
        conn.close()
        
        result = []
        for row in rows:
            if isinstance(row, dict):  # PostgreSQL RealDictCursor
                result.append({
                    'date': str(row['date']),
                    'price': float(row['price']) if row['price'] else 0,
                    'min_price': float(row['min_price']) if row['min_price'] else 0,
                    'max_price': float(row['max_price']) if row['max_price'] else 0,
                    'data_points': int(row['data_points']) if row['data_points'] else 1
                })
            else:  # SQLite tuple
                result.append({
                    'date': str(row[0]),
                    'price': float(row[1]) if row[1] else 0,
                    'min_price': float(row[2]) if row[2] else 0,
                    'max_price': float(row[3]) if row[3] else 0,
                    'data_points': int(row[4]) if row[4] else 1
                })
        
        return result
        
    except Exception as e:
        log.error(f"[Price Forecast] Error getting history: {e}")
        return []


def calculate_moving_averages(history: List[Dict]) -> Tuple[List[float], List[float]]:
    """
    Berechnet 7- und 14-Tage Moving Averages
    
    Returns:
        (ma7, ma14) - Listen mit Moving Averages
    """
    if not history:
        return [], []
    
    prices = [h['price'] for h in history]
    ma7 = []
    ma14 = []
    
    for i in range(len(prices)):
        if i >= 6:
            ma7.append(np.mean(prices[i-6:i+1]))
        else:
            ma7.append(np.mean(prices[:i+1]))
        
        if i >= 13:
            ma14.append(np.mean(prices[i-13:i+1]))
        else:
            ma14.append(np.mean(prices[:i+1]))
    
    return ma7, ma14


def forecast_with_linear_regression(
    history: List[Dict], 
    forecast_days: int = 7
) -> Dict:
    """
    Erstellt Prognose mit Linearer Regression
    
    Args:
        history: Historische Preis-Daten
        forecast_days: Anzahl Tage in die Zukunft
    
    Returns:
        Dict mit forecast_dates, forecast_prices, confidence_upper, confidence_lower
    """
    if not SKLEARN_AVAILABLE or len(history) < 3:
        return {'forecast': [], 'upper': [], 'lower': []}
    
    try:
        prices = np.array([h['price'] for h in history]).reshape(-1, 1)
        X = np.arange(len(prices)).reshape(-1, 1)
        
        model = LinearRegression()
        model.fit(X, prices)
        
        future_X = np.arange(len(prices), len(prices) + forecast_days).reshape(-1, 1)
        forecast = model.predict(future_X)
        
        residuals = prices.flatten() - model.predict(X)
        std_error = np.std(residuals)
        
        confidence_upper = forecast.flatten() + (1.96 * std_error)
        confidence_lower = forecast.flatten() - (1.96 * std_error)
        confidence_lower = np.maximum(confidence_lower, np.min(prices) * 0.8)
        
        forecast_dates = []
        last_date = datetime.strptime(history[-1]['date'], '%Y-%m-%d')
        for i in range(forecast_days):
            forecast_dates.append((last_date + timedelta(days=i+1)).strftime('%Y-%m-%d'))
        
        return {
            'forecast': forecast.flatten().tolist(),
            'upper': confidence_upper.tolist(),
            'lower': confidence_lower.tolist(),
            'dates': forecast_dates,
            'slope': float(model.coef_[0][0]),
            'intercept': float(model.intercept_[0])
        }
        
    except Exception as e:
        log.error(f"[Price Forecast] Regression error: {e}")
        return {'forecast': [], 'upper': [], 'lower': []}


def get_price_forecast(item_hash: str, forecast_days: int = 7) -> Dict:
    """
    Hauptfunktion: Gibt komplette Prognose mit allen Metriken zurück
    
    Args:
        item_hash: Hash des Items
        forecast_days: Tage in die Zukunft prognostizieren
    
    Returns:
        Dict mit historischen Daten, Moving Averages, Prognose und Statistiken
    """
    history = get_price_history_raw(item_hash, days=60)
    
    if len(history) < 3:
        return {
            'success': False,
            'message': 'Nicht genug historische Daten für Prognose',
            'data_points': len(history)
        }
    
    try:
        ma7, ma14 = calculate_moving_averages(history)
        regression_forecast = forecast_with_linear_regression(history, forecast_days)
        
        prices = [h['price'] for h in history]
        current_price = prices[-1] if prices else 0
        min_price = min(prices)
        max_price = max(prices)
        avg_price = np.mean(prices)
        
        trend = 'stable'
        if len(prices) >= 7:
            recent_avg = np.mean(prices[-7:])
            older_avg = np.mean(prices[:7])
            trend_pct = ((recent_avg - older_avg) / older_avg) * 100 if older_avg > 0 else 0
            if trend_pct > 2:
                trend = 'rising'
            elif trend_pct < -2:
                trend = 'falling'
        
        return {
            'success': True,
            'history': history,
            'moving_averages': {
                'ma7': ma7,
                'ma14': ma14
            },
            'forecast': {
                'dates': regression_forecast.get('dates', []),
                'prices': regression_forecast.get('forecast', []),
                'upper_bound': regression_forecast.get('upper', []),
                'lower_bound': regression_forecast.get('lower', []),
                'slope': regression_forecast.get('slope', 0),
                'intercept': regression_forecast.get('intercept', 0)
            },
            'statistics': {
                'current_price': float(current_price),
                'min_price': float(min_price),
                'max_price': float(max_price),
                'avg_price': float(avg_price),
                'trend': trend,
                'data_points': len(history),
                'volatility': float(np.std(prices)) if len(prices) > 1 else 0
            }
        }
        
    except Exception as e:
        log.error(f"[Price Forecast] Error in get_price_forecast: {e}")
        return {
            'success': False,
            'message': str(e),
            'history': history
        }


def get_forecast_summary(item_hash: str) -> Dict:
    """
    Schnelle Zusammenfassung der Prognose für Dashboard
    """
    forecast = get_price_forecast(item_hash)
    
    if not forecast.get('success'):
        return {'success': False, 'message': forecast.get('message', 'Unknown error')}
    
    stats = forecast['statistics']
    forecast_data = forecast['forecast']
    
    recommendation = 'hold'
    if forecast_data['prices']:
        last_forecast = forecast_data['prices'][-1]
        current = stats['current_price']
        
        if last_forecast < current * 0.95:
            recommendation = 'wait'
        elif last_forecast > current * 1.05:
            recommendation = 'buy'
    
    return {
        'success': True,
        'current_price': stats['current_price'],
        'forecast_7d': forecast_data['prices'][-1] if forecast_data['prices'] else stats['current_price'],
        'trend': stats['trend'],
        'volatility': stats['volatility'],
        'recommendation': recommendation,
        'confidence': min(100, (stats['data_points'] / 30) * 100)
    }


def get_detailed_recommendation(item_hash: str) -> Dict:
    """
    Detaillierte Kaufempfehlung mit Begründung, Badges und Action Items
    
    Returns:
        Dict mit recommendation, badge, message, action, price_change_percent
    """
    forecast = get_price_forecast(item_hash)
    
    if not forecast.get('success'):
        return {
            'success': False,
            'recommendation': 'neutral',
            'badge': '❓',
            'message': 'Nicht genug Daten für Empfehlung',
            'action': 'Komm später vorbei'
        }
    
    try:
        stats = forecast['statistics']
        forecast_data = forecast['forecast']
        
        current_price = stats['current_price']
        forecast_price = forecast_data['prices'][-1] if forecast_data['prices'] else current_price
        price_change = forecast_price - current_price
        price_change_percent = (price_change / current_price * 100) if current_price > 0 else 0
        
        confidence = min(100, (stats['data_points'] / 30) * 100)
        volatility = stats['volatility']
        trend = stats['trend']
        
        recommendation = 'neutral'
        badge = '🟡'
        message = ''
        action = ''
        
        if forecast_price < current_price * 0.95:
            recommendation = 'wait'
            badge = '🔴'
            price_drop = abs(price_change_percent)
            message = f'Preis wird in 7 Tagen ca. {price_drop:.1f}% fallen'
            action = '⏳ Warte noch - bessere Deals kommen!'
            
        elif forecast_price > current_price * 1.05:
            recommendation = 'buy'
            badge = '🟢'
            price_rise = price_change_percent
            message = f'Preis wird in 7 Tagen ca. {price_rise:.1f}% steigen'
            action = '⚡ Jetzt kaufen - der Preis wird teurer!'
            
        else:
            recommendation = 'hold'
            badge = '🟡'
            message = 'Preis bleibt stabil'
            action = '➡️ Weder besonders günstig noch teuer'
        
        return {
            'success': True,
            'recommendation': recommendation,
            'badge': badge,
            'message': message,
            'action': action,
            'current_price': round(current_price, 2),
            'forecast_price': round(forecast_price, 2),
            'price_change': round(price_change, 2),
            'price_change_percent': round(price_change_percent, 1),
            'trend': trend,
            'volatility': round(volatility, 2),
            'confidence': round(confidence, 0),
            'data_points': stats['data_points'],
            'min_price': round(stats['min_price'], 2),
            'max_price': round(stats['max_price'], 2),
            'avg_price': round(stats['avg_price'], 2),
            'upper_bound': round(forecast_data['upper_bound'][-1] if forecast_data['upper_bound'] else forecast_price, 2),
            'lower_bound': round(forecast_data['lower_bound'][-1] if forecast_data['lower_bound'] else forecast_price, 2)
        }
        
    except Exception as e:
        log.error(f"[Price Forecast] Error in detailed recommendation: {e}")
        return {
            'success': False,
            'recommendation': 'neutral',
            'badge': '❓',
            'message': 'Fehler bei der Analyse',
            'action': 'Versuche es später noch mal'
        }
