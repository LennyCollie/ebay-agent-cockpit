"""
Price History Tracker - speichert und verfolgt Preisveränderungen
Optimiert für PostgreSQL und SQLite
"""
import hashlib
import logging
from typing import Dict, List, Optional
from database import get_db, get_placeholder

log = logging.getLogger(__name__)


def hash_item(title: str, portal: str) -> str:
    """
    Erstellt eindeutige Hash für Item (für Deduplication)
    Format: title + portal => SHA256
    """
    try:
        key = f"{title.lower()[:100]}_{portal}".encode('utf-8')
        return hashlib.sha256(key).hexdigest()[:16]
    except Exception as e:
        log.error(f"[Price Tracker] Hash error: {e}")
        return ""


def track_item_price(item: Dict) -> bool:
    """
    Speichert/Updated Item-Preis in History mit Min/Max Tracking
    
    Args:
        item: Dict mit title, price, source, url
    
    Returns:
        True wenn erfolgreich, False sonst
    """
    try:
        item_hash = hash_item(item.get('title', ''), item.get('source', 'unknown'))
        if not item_hash:
            return False
        
        price_str = str(item.get('price', '0')).replace('€', '').replace(',', '.').strip()
        try:
            price = float(price_str.split()[0])
        except (ValueError, IndexError):
            price = 0.0
        
        conn = get_db()
        cur = conn.cursor()
        ph = get_placeholder()
        
        if get_placeholder() == "%s":
            cur.execute(f"""
                INSERT INTO item_price_history 
                (item_hash, item_title, price_current, price_min, price_max, portal, last_seen)
                VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, NOW())
                ON CONFLICT (item_hash) DO UPDATE SET
                    item_title = {ph},
                    price_current = {ph},
                    price_min = LEAST(item_price_history.price_min, {ph}),
                    price_max = GREATEST(item_price_history.price_max, {ph}),
                    last_seen = NOW()
            """, (
                item_hash, 
                item.get('title', '')[:255],
                price, price, price,
                item.get('source', 'unknown'),
                item.get('title', '')[:255],
                price,
                price,
                price
            ))
        else:
            cur.execute(f"""
                SELECT price_min, price_max FROM item_price_history 
                WHERE item_hash = {ph}
            """, (item_hash,))
            existing = cur.fetchone()
            
            if existing:
                min_price = min(existing[0] if existing[0] else price, price)
                max_price = max(existing[1] if existing[1] else price, price)
            else:
                min_price = price
                max_price = price
            
            cur.execute(f"""
                INSERT OR REPLACE INTO item_price_history 
                (item_hash, item_title, price_current, price_min, price_max, portal, last_seen)
                VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, CURRENT_TIMESTAMP)
            """, (
                item_hash,
                item.get('title', '')[:255],
                price,
                min_price,
                max_price,
                item.get('source', 'unknown')
            ))
        
        conn.commit()
        conn.close()
        
        log.info(f"[Price Tracker] Tracked: {item.get('title', 'Unknown')} @ {price}€")
        return True
        
    except Exception as e:
        log.error(f"[Price Tracker] Error tracking price: {e}")
        return False


def get_price_history(item_hash: str, days: int = 30) -> List[Dict]:
    """
    Holt Preis-Verlauf für Item
    
    Args:
        item_hash: Hash des Items
        days: Anzahl Tage zurück
    
    Returns:
        Liste mit Preis-Einträgen
    """
    try:
        conn = get_db()
        cur = conn.cursor()
        ph = get_placeholder()
        
        if get_placeholder() == "%s":
            cur.execute(f"""
                SELECT 
                    DATE(last_seen) as date, 
                    price_current, 
                    price_min, 
                    price_max,
                    item_title,
                    portal
                FROM item_price_history
                WHERE item_hash = {ph}
                AND last_seen >= NOW() - INTERVAL '{days} days'
                ORDER BY last_seen DESC
            """, (item_hash,))
        else:
            cur.execute(f"""
                SELECT 
                    DATE(last_seen) as date, 
                    price_current, 
                    price_min, 
                    price_max,
                    item_title,
                    portal
                FROM item_price_history
                WHERE item_hash = {ph}
                AND last_seen >= datetime('now', '-{days} days')
                ORDER BY last_seen DESC
            """, (item_hash,))
        
        rows = cur.fetchall()
        conn.close()
        
        if not rows:
            return []
        
        result = []
        for row in rows:
            result.append({
                'date': str(row[0]),
                'price_current': float(row[1]) if row[1] else 0,
                'price_min': float(row[2]) if row[2] else 0,
                'price_max': float(row[3]) if row[3] else 0,
                'title': row[4],
                'portal': row[5]
            })
        
        return result
        
    except Exception as e:
        log.error(f"[Price History] Error fetching history: {e}")
        return []


def get_item_stats(item_hash: str) -> Optional[Dict]:
    """
    Holt Statistiken für ein Item
    """
    try:
        conn = get_db()
        cur = conn.cursor()
        ph = get_placeholder()
        
        cur.execute(f"""
            SELECT 
                item_title,
                price_current,
                price_min,
                price_max,
                portal,
                COUNT(*) as changes,
                MIN(last_seen) as first_tracked,
                MAX(last_seen) as last_tracked
            FROM item_price_history
            WHERE item_hash = {ph}
            GROUP BY item_hash, item_title, price_current, price_min, price_max, portal
        """, (item_hash,))
        
        row = cur.fetchone()
        conn.close()
        
        if not row:
            return None
        
        return {
            'title': row[0],
            'price_current': float(row[1]) if row[1] else 0,
            'price_min': float(row[2]) if row[2] else 0,
            'price_max': float(row[3]) if row[3] else 0,
            'portal': row[4],
            'changes': row[5],
            'first_tracked': row[6],
            'last_tracked': row[7],
            'savings': (float(row[3]) - float(row[1])) if row[1] and row[3] else 0
        }
        
    except Exception as e:
        log.error(f"[Price Stats] Error: {e}")
        return None
