"""
Smart Notifications Service - Preis-Drop-Alerts und Verfügbarkeitswarnungen
"""
import logging
import sqlite3
from typing import Dict, List, Optional
from datetime import datetime

log = logging.getLogger(__name__)


def get_db():
    """Verbindung zur SQLite-Datenbank"""
    conn = sqlite3.connect("instance/db.sqlite3")
    conn.row_factory = sqlite3.Row
    return conn


def create_price_alert(user_id: int, item_title: str, target_price: float, 
                      search_term: str, threshold_percent: Optional[float] = None) -> bool:
    """
    Erstellt einen Preis-Drop-Alert für einen Benutzer
    
    Args:
        user_id: Benutzer-ID
        item_title: Titel des Items
        target_price: Zielpreis für Alert
        search_term: Suchbegriff
        threshold_percent: Prozentuale Schwelle (z.B. 10 = 10% unter aktuellem Preis)
    
    Returns:
        True wenn erfolgreich, False sonst
    """
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO price_alerts 
            (user_id, item_title, target_price, threshold_percent, search_term, created_at, is_active)
            VALUES (?, ?, ?, ?, ?, datetime('now'), 1)
        """, (user_id, item_title[:255], target_price, threshold_percent, search_term[:255]))
        
        conn.commit()
        conn.close()
        
        log.info(f"[Notification] Price alert created for user {user_id}: {item_title}")
        return True
        
    except Exception as e:
        log.error(f"[Notification] Error creating price alert: {e}")
        return False


def get_active_alerts(user_id: int) -> List[Dict]:
    """Holt alle aktiven Alerts für einen Benutzer"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT id, item_title, target_price, threshold_percent, search_term, created_at
            FROM price_alerts
            WHERE user_id = ? AND is_active = 1
            ORDER BY created_at DESC
        """, (user_id,))
        
        rows = cur.fetchall()
        conn.close()
        
        result = []
        for row in rows:
            result.append({
                'id': row[0],
                'item_title': row[1],
                'target_price': float(row[2]) if row[2] else None,
                'threshold_percent': float(row[3]) if row[3] else None,
                'search_term': row[4],
                'created_at': row[5]
            })
        
        return result
        
    except Exception as e:
        log.error(f"[Notification] Error fetching alerts: {e}")
        return []


def delete_alert(alert_id: int, user_id: int) -> bool:
    """Löscht einen Alert (nur vom Owner)"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("""
            DELETE FROM price_alerts
            WHERE id = ? AND user_id = ?
        """, (alert_id, user_id))
        
        conn.commit()
        affected = cur.rowcount
        conn.close()
        
        if affected > 0:
            log.info(f"[Notification] Alert {alert_id} deleted for user {user_id}")
            return True
        return False
        
    except Exception as e:
        log.error(f"[Notification] Error deleting alert: {e}")
        return False


def toggle_alert(alert_id: int, user_id: int, active: bool) -> bool:
    """Aktiviert/Deaktiviert einen Alert"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("""
            UPDATE price_alerts
            SET is_active = ?
            WHERE id = ? AND user_id = ?
        """, (1 if active else 0, alert_id, user_id))
        
        conn.commit()
        conn.close()
        
        log.info(f"[Notification] Alert {alert_id} toggled to {active}")
        return True
        
    except Exception as e:
        log.error(f"[Notification] Error toggling alert: {e}")
        return False


def check_price_drops(current_price: float, item_title: str, search_term: str) -> List[Dict]:
    """
    Prüft ob Preis unter irgendeinem Alert-Threshold fällt
    
    Args:
        current_price: Aktueller Preis
        item_title: Item-Titel
        search_term: Suchbegriff
    
    Returns:
        Liste der ausgelösten Alerts
    """
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT id, user_id, target_price, threshold_percent
            FROM price_alerts
            WHERE (item_title LIKE ? OR search_term LIKE ?)
            AND is_active = 1
        """, (f"%{item_title}%", f"%{search_term}%"))
        
        rows = cur.fetchall()
        conn.close()
        
        triggered = []
        for row in rows:
            alert_id, user_id, target_price, threshold_percent = row
            
            if target_price and current_price <= target_price:
                triggered.append({
                    'alert_id': alert_id,
                    'user_id': user_id,
                    'type': 'target_price',
                    'current_price': current_price,
                    'target_price': target_price
                })
            elif threshold_percent:
                price_threshold = target_price * (1 - threshold_percent / 100) if target_price else None
                if price_threshold and current_price <= price_threshold:
                    triggered.append({
                        'alert_id': alert_id,
                        'user_id': user_id,
                        'type': 'threshold',
                        'current_price': current_price,
                        'threshold_price': price_threshold,
                        'percent': threshold_percent
                    })
        
        return triggered
        
    except Exception as e:
        log.error(f"[Notification] Error checking price drops: {e}")
        return []


def log_alert_trigger(alert_id: int, triggered_price: float, item_found_price: Optional[float] = None, 
                     savings_amount: Optional[float] = None) -> bool:
    """
    Speichert einen Alert-Trigger in die Datenbank
    
    Args:
        alert_id: Alert-ID
        triggered_price: Der Preis der den Alert ausgelöst hat
        item_found_price: Der ursprüngliche Preis des Items
        savings_amount: Wie viel Ersparnis
    
    Returns:
        True wenn erfolgreich, False sonst
    """
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO price_alert_triggers 
            (alert_id, triggered_price, triggered_at, item_found_price, savings_amount)
            VALUES (?, ?, datetime('now'), ?, ?)
        """, (alert_id, triggered_price, item_found_price, savings_amount))
        
        conn.commit()
        conn.close()
        
        log.info(f"[Notification] Alert {alert_id} triggered at price {triggered_price}")
        return True
        
    except Exception as e:
        log.error(f"[Notification] Error logging alert trigger: {e}")
        return False


def get_alert_triggers(alert_id: int, limit: int = 100) -> List[Dict]:
    """
    Holt alle Trigger für einen bestimmten Alert
    
    Args:
        alert_id: Alert-ID
        limit: Maximale Anzahl der Einträge
    
    Returns:
        Liste der Trigger
    """
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT id, triggered_price, triggered_at, item_found_price, savings_amount
            FROM price_alert_triggers
            WHERE alert_id = ?
            ORDER BY triggered_at DESC
            LIMIT ?
        """, (alert_id, limit))
        
        rows = cur.fetchall()
        conn.close()
        
        result = []
        for row in rows:
            result.append({
                'id': row[0],
                'triggered_price': float(row[1]) if row[1] else None,
                'triggered_at': row[2],
                'item_found_price': float(row[3]) if row[3] else None,
                'savings_amount': float(row[4]) if row[4] else None
            })
        
        return result
        
    except Exception as e:
        log.error(f"[Notification] Error fetching alert triggers: {e}")
        return []


def get_alert_statistics(alert_id: int) -> Dict:
    """
    Berechnet Statistiken für einen Alert
    
    Args:
        alert_id: Alert-ID
    
    Returns:
        Dict mit Statistiken (trigger_count, last_trigger, total_savings, avg_savings)
    """
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT 
                COUNT(*) as trigger_count,
                MAX(triggered_at) as last_trigger,
                SUM(savings_amount) as total_savings,
                AVG(savings_amount) as avg_savings
            FROM price_alert_triggers
            WHERE alert_id = ?
        """, (alert_id,))
        
        row = cur.fetchone()
        conn.close()
        
        if row:
            return {
                'trigger_count': row[0] or 0,
                'last_trigger': row[1],
                'total_savings': float(row[2]) if row[2] else 0.0,
                'avg_savings': float(row[3]) if row[3] else 0.0
            }
        
        return {
            'trigger_count': 0,
            'last_trigger': None,
            'total_savings': 0.0,
            'avg_savings': 0.0
        }
        
    except Exception as e:
        log.error(f"[Notification] Error calculating statistics: {e}")
        return {
            'trigger_count': 0,
            'last_trigger': None,
            'total_savings': 0.0,
            'avg_savings': 0.0
        }
