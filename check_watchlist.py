# check_watchlist.py - Prüft Watchlist-Items auf Änderungen
from models import SessionLocal, WatchedItem
from utils.price_analyzer import track_watched_item_price
from utils.notification_manager import get_notification_manager
from datetime import datetime, timedelta

def check_all_watched_items():
    """Prüft alle Watchlist-Items"""
    print("[WATCHLIST] Starte Check...")

    db = SessionLocal()

    # Hole alle aktiven Items die länger als 1h nicht geprüft wurden
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)

    items = db.query(WatchedItem).filter(
        WatchedItem.is_active == True,
        WatchedItem.last_checked < one_hour_ago
    ).all()

    print(f"[WATCHLIST] {len(items)} Items zu prüfen")

    manager = get_notification_manager()
    updates = 0

    for item in items:
        try:
            # TODO: eBay API aufrufen um aktuellen Preis zu holen
            # Für jetzt: Mock
            # new_price = fetch_ebay_item_price(item.ebay_item_id)

            # Simuliere Preisänderung (nur für Test)
            old_price = float(item.current_price)
            new_price = old_price * 0.95  # 5% günstiger

            # Speichere Snapshot
            track_watched_item_price(
                watched_item_id=item.id,
                current_price=new_price,
                available=True
            )

            # Wenn Preis gesunken: Alert senden
            if new_price < old_price and item.notify_price_drop:
                result = manager.send_price_drop_alert(
                    watched_item_id=item.id,
                    old_price=old_price,
                    new_price=new_price
                )

                if result["sent"]:
                    print(f"[WATCHLIST] Preis-Alert gesendet für: {item.item_title[:50]}")
                    updates += 1

            item.last_checked = datetime.utcnow()

        except Exception as e:
            print(f"[WATCHLIST] Fehler bei Item {item.id}: {e}")
            continue

    db.commit()
    db.close()

    print(f"[WATCHLIST] Fertig. {updates} Alerts gesendet")

if __name__ == "__main__":
    check_all_watched_items()
