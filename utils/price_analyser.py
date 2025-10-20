# utils/price_analyzer.py
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from models import SessionLocal, PriceHistory, ItemPriceTracking, WatchedItem
import statistics


def record_search_prices(search_term: str, items: List[Dict], condition: str = None):
    """
    Speichert Preis-Statistik für eine Suche

    Args:
        search_term: Suchbegriff
        items: Liste von eBay-Items mit 'price' Feld
        condition: Optional - Zustand (NEW, USED, etc.)
    """
    if not items:
        return

    # Extrahiere Preise
    prices = []
    for item in items:
        try:
            price = float(item.get("price", 0))
            if price > 0:
                prices.append(price)
        except (ValueError, TypeError):
            continue

    if not prices:
        return

    # Berechne Statistiken
    avg_price = statistics.mean(prices)
    min_price = min(prices)
    max_price = max(prices)

    try:
        median_price = statistics.median(prices)
    except statistics.StatisticsError:
        median_price = avg_price

    # Speichere in DB
    db = SessionLocal()

    history = PriceHistory(
        search_term=search_term.lower().strip(),
        avg_price=avg_price,
        min_price=min_price,
        max_price=max_price,
        median_price=median_price,
        item_count=len(prices),
        condition=condition
    )

    db.add(history)
    db.commit()
    db.close()

    print(f"[PRICE] Recorded: {search_term} → Ø {avg_price:.2f}€ ({len(prices)} items)")


def get_price_trend(search_term: str, days: int = 30) -> Dict:
    """
    Holt Preis-Trend für einen Suchbegriff

    Returns:
        {
            "search_term": str,
            "current_avg": float,
            "trend": "rising" | "falling" | "stable",
            "change_percent": float,
            "history": [...]
        }
    """
    db = SessionLocal()

    since = datetime.utcnow() - timedelta(days=days)

    records = db.query(PriceHistory).filter(
        PriceHistory.search_term == search_term.lower().strip(),
        PriceHistory.recorded_at >= since
    ).order_by(PriceHistory.recorded_at.asc()).all()

    db.close()

    if not records:
        return {
            "search_term": search_term,
            "found": False,
            "message": "Keine Daten vorhanden"
        }

    # Aktuelle und älteste Preise
    current_avg = records[-1].avg_price
    oldest_avg = records[0].avg_price

    # Trend berechnen
    change_percent = ((current_avg - oldest_avg) / oldest_avg * 100) if oldest_avg > 0 else 0

    if change_percent > 5:
        trend = "rising"
    elif change_percent < -5:
        trend = "falling"
    else:
        trend = "stable"

    # History für Chart
    history = [
        {
            "date": r.recorded_at.strftime("%Y-%m-%d"),
            "avg_price": round(r.avg_price, 2),
            "min_price": round(r.min_price, 2),
            "max_price": round(r.max_price, 2),
            "item_count": r.item_count
        }
        for r in records
    ]

    return {
        "search_term": search_term,
        "found": True,
        "current_avg": round(current_avg, 2),
        "oldest_avg": round(oldest_avg, 2),
        "trend": trend,
        "change_percent": round(change_percent, 1),
        "history": history,
        "days": days
    }


def track_watched_item_price(watched_item_id: int, current_price: float, available: bool = True, bid_count: int = 0):
    """
    Speichert Preis-Snapshot für beobachtetes Item

    Args:
        watched_item_id: ID des WatchedItem
        current_price: Aktueller Preis
        available: Ob Item noch verfügbar ist
        bid_count: Anzahl Gebote (bei Auktionen)
    """
    db = SessionLocal()

    snapshot = ItemPriceTracking(
        watched_item_id=watched_item_id,
        price=current_price,
        item_available=available,
        bid_count=bid_count
    )

    db.add(snapshot)

    # Update WatchedItem current_price
    watched = db.query(WatchedItem).filter_by(id=watched_item_id).first()
    if watched:
        watched.current_price = str(current_price)
        watched.last_checked = datetime.utcnow()

        # Update lowest_price
        if not watched.lowest_price or float(watched.lowest_price) > current_price:
            watched.lowest_price = str(current_price)

    db.commit()
    db.close()


def get_item_price_history(watched_item_id: int, days: int = 30) -> Dict:
    """
    Holt Preis-Verlauf für ein beobachtetes Item

    Returns:
        {
            "item_id": int,
            "price_history": [...],
            "lowest": float,
            "highest": float,
            "current": float
        }
    """
    db = SessionLocal()

    since = datetime.utcnow() - timedelta(days=days)

    snapshots = db.query(ItemPriceTracking).filter(
        ItemPriceTracking.watched_item_id == watched_item_id,
        ItemPriceTracking.recorded_at >= since
    ).order_by(ItemPriceTracking.recorded_at.asc()).all()

    watched = db.query(WatchedItem).filter_by(id=watched_item_id).first()

    db.close()

    if not snapshots:
        return {
            "item_id": watched_item_id,
            "found": False,
            "message": "Noch keine Preis-Historie"
        }

    prices = [s.price for s in snapshots]

    history = [
        {
            "timestamp": s.recorded_at.strftime("%Y-%m-%d %H:%M"),
            "price": round(s.price, 2),
            "available": s.item_available,
            "bids": s.bid_count
        }
        for s in snapshots
    ]

    return {
        "item_id": watched_item_id,
        "item_title": watched.item_title if watched else "Unbekannt",
        "found": True,
        "lowest": round(min(prices), 2),
        "highest": round(max(prices), 2),
        "current": round(prices[-1], 2),
        "price_history": history
    }


def get_popular_searches(limit: int = 10) -> List[Dict]:
    """
    Gibt die beliebtesten Suchbegriffe zurück (nach Anzahl Einträge)
    """
    db = SessionLocal()

    results = db.query(
        PriceHistory.search_term,
        func.count(PriceHistory.id).label("count"),
        func.avg(PriceHistory.avg_price).label("avg_price")
    ).group_by(
        PriceHistory.search_term
    ).order_by(
        func.count(PriceHistory.id).desc()
    ).limit(limit).all()

    db.close()

    return [
        {
            "search_term": r.search_term,
            "searches": r.count,
            "avg_price": round(r.avg_price, 2)
        }
        for r in results
    ]


# Test-Funktion
if __name__ == "__main__":
    # Test
    test_items = [
        {"price": "999"},
        {"price": "1099"},
        {"price": "950"},
        {"price": "1050"},
    ]

    record_search_prices("iPhone 15 Pro", test_items)

    trend = get_price_trend("iPhone 15 Pro", days=7)
    print(trend)
