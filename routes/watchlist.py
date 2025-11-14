# routes/watchlist.py - Watchlist Routes für eBay Items
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from datetime import datetime
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import SessionLocal, User, WatchedItem, ItemPriceTracking

bp = Blueprint('watchlist', __name__, url_prefix='/watchlist')


def get_current_user(db):
    """Holt User basierend auf Session (robust: user_id oder user_email)."""
    # 1) user_id bevorzugt (numeric)
    uid = session.get("user_id")
    if uid:
        try:
            uid = int(uid)
            user = db.query(User).filter_by(id=uid).first()
            if user:
                return user
        except Exception:
            pass

    # 2) fallback auf user_email
    user_email = (session.get("user_email") or "").strip().lower()
    if not user_email or user_email == "guest" or "@" not in user_email:
        return None

    user = db.query(User).filter_by(email=user_email).first()
    return user



@bp.route('/')
def index():
    """Zeigt die Watchlist des Users"""
    db = SessionLocal()
    try:
        user = get_current_user(db)
        if not user:
            flash("Bitte einloggen um die Watchlist zu nutzen", "warning")
            return redirect(url_for('login'))

        # Hole alle watched items
        items = db.query(WatchedItem).filter_by(
            user_id=user.id,
            is_active=True
        ).order_by(WatchedItem.created_at.desc()).all()

        # Berechne Preisänderungen
        for item in items:
            if item.initial_price and item.current_price:
                try:
                    # Entferne EUR und parse als Float
                    initial_str = str(item.initial_price).replace('EUR', '').replace(',', '.').strip()
                    current_str = str(item.current_price).replace('EUR', '').replace(',', '.').strip()

                    initial = float(initial_str) if initial_str else 0
                    current = float(current_str) if current_str else 0

                    item.price_change = current - initial
                    item.price_change_percent = ((current - initial) / initial * 100) if initial > 0 else 0
                except Exception as e:
                    print(f"[watchlist] Price calculation error: {e}")
                    item.price_change = 0
                    item.price_change_percent = 0
            else:
                item.price_change = 0
                item.price_change_percent = 0

        return render_template('watchlist/index.html',
                             items=items,
                             user=user,
                             item_count=len(items))
    finally:
        db.close()


@bp.route('/add', methods=['POST'])
def add():
    """Fügt ein Item zur Watchlist hinzu - FIXED VERSION"""
    db = SessionLocal()
    try:
        # User aus Session holen
        user = get_current_user(db)
        if not user:
            flash("Bitte einloggen um Artikel zur Watchlist hinzuzufügen.", "warning")
            return redirect(url_for('login'))

        # Daten aus Formular holen
        item_id = request.form.get('item_id', '').strip()
        title = request.form.get('title', '').strip()
        price = request.form.get('price', '').strip()
        url = request.form.get('url', '').strip()
        image_url = request.form.get('image_url', '').strip()

        print(f"[watchlist] Adding item: id={item_id}, title={title[:30]}, price={price}")

        # Validierung
        if not item_id or not title:
            flash("Fehlende Artikeldaten (ID oder Titel).", "danger")
            return redirect(request.referrer or url_for('search'))

        # Prüfe ob Item bereits in Watchlist
        existing = db.query(WatchedItem).filter_by(
            user_id=user.id,
            ebay_item_id=item_id
        ).first()

        if existing:
            if not existing.is_active:
                # Reaktiviere inaktives Item
                existing.is_active = True
                existing.last_checked = datetime.utcnow()
                db.commit()
                flash(f"✅ '{title[:40]}...' wurde reaktiviert!", "success")
            else:
                flash(f"ℹ️ '{title[:40]}...' ist bereits in deiner Watchlist.", "info")
        else:
            # Erstelle neues WatchedItem
            watched_item = WatchedItem(
                user_id=user.id,
                ebay_item_id=item_id,
                item_title=title,
                item_url=url,
                image_url=image_url,
                initial_price=price or "0",
                current_price=price or "0",
                currency='EUR',
                notify_price_drop=True,
                notify_auction_ending=True,
                is_active=True,
                created_at=datetime.utcnow(),
                last_checked=datetime.utcnow()
            )
            db.add(watched_item)
            db.commit()

            # Erstelle ersten Price Tracking Eintrag
            try:
                price_value = float(price.replace('EUR', '').replace(',', '.').strip()) if price else 0.0
                price_tracking = ItemPriceTracking(
                    watched_item_id=watched_item.id,
                    price=price_value,
                    currency='EUR',
                    item_available=True,
                    recorded_at=datetime.utcnow()
                )
                db.add(price_tracking)
                db.commit()
            except Exception as e:
                print(f"[watchlist] Price tracking creation failed: {e}")
                # Nicht kritisch, weitermachen

            flash(f"✅ '{title[:40]}...' wurde zur Watchlist hinzugefügt!", "success")
            print(f"[watchlist] Successfully added item {item_id}")

        # Redirect basierend auf Quelle
        if request.form.get('source') == 'search':
            return redirect(request.referrer or url_for('search'))
        return redirect(url_for('watchlist.index'))

    except Exception as e:
        db.rollback()
        print(f"[WATCHLIST] Error adding item: {e}")
        import traceback
        traceback.print_exc()
        flash("❌ Fehler beim Hinzufügen zur Watchlist (siehe Log).", "danger")
        return redirect(request.referrer or url_for('search'))
    finally:
        db.close()


@bp.route('/remove/<int:item_id>', methods=['POST'])
def remove(item_id):
    """Entfernt ein Item aus der Watchlist (JSON Response für AJAX)"""
    db = SessionLocal()
    try:
        user = get_current_user(db)
        if not user:
            return jsonify({'success': False, 'error': 'Nicht eingeloggt'}), 401

        item = db.query(WatchedItem).filter_by(
            id=item_id,
            user_id=user.id
        ).first()

        if not item:
            return jsonify({'success': False, 'error': 'Item nicht gefunden'}), 404

        # Soft delete - nur deaktivieren
        item.is_active = False
        db.commit()

        return jsonify({'success': True, 'message': f"'{item.item_title[:40]}' wurde entfernt"})

    except Exception as e:
        db.rollback()
        print(f"[watchlist] Remove error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        db.close()


@bp.route('/update-price/<int:item_id>', methods=['POST'])
def update_price(item_id):
    """Aktualisiert den Preis eines Items (manuell oder via AJAX)"""
    db = SessionLocal()
    try:
        user = get_current_user(db)
        if not user:
            return jsonify({'error': 'Nicht eingeloggt'}), 401

        item = db.query(WatchedItem).filter_by(
            id=item_id,
            user_id=user.id
        ).first()

        if not item:
            return jsonify({'error': 'Item nicht gefunden'}), 404

        new_price = request.json.get('price') if request.is_json else request.form.get('price')

        if new_price:
            # Speichere alten Preis
            old_price = item.current_price

            # Update current price
            item.current_price = new_price
            item.last_checked = datetime.utcnow()

            # Prüfe auf niedrigsten Preis
            try:
                new_val = float(new_price.replace('EUR', '').replace(',', '.').strip())
                if not item.lowest_price:
                    item.lowest_price = new_price
                else:
                    lowest_val = float(item.lowest_price.replace('EUR', '').replace(',', '.').strip())
                    if new_val < lowest_val:
                        item.lowest_price = new_price
            except:
                pass

            # Füge Price Tracking Eintrag hinzu
            try:
                price_value = float(new_price.replace('EUR', '').replace(',', '.').strip())
                price_tracking = ItemPriceTracking(
                    watched_item_id=item.id,
                    price=price_value,
                    currency='EUR',
                    item_available=True,
                    recorded_at=datetime.utcnow()
                )
                db.add(price_tracking)
            except Exception as e:
                print(f"[watchlist] Price tracking error: {e}")

            db.commit()

            # Prüfe auf Preissenkung für Benachrichtigung
            if old_price and item.notify_price_drop:
                try:
                    old_val = float(old_price.replace('EUR', '').replace(',', '.').strip())
                    new_val = float(new_price.replace('EUR', '').replace(',', '.').strip())
                    drop_percent = ((old_val - new_val) / old_val * 100)

                    if drop_percent >= item.price_drop_threshold:
                        flash(f"💰 Preissenkung! {item.item_title[:30]}... ist jetzt {drop_percent:.1f}% günstiger!", "success")
                except:
                    pass

            if request.is_json:
                return jsonify({'success': True, 'new_price': new_price})

        return redirect(url_for('watchlist.index'))

    except Exception as e:
        db.rollback()
        print(f"[watchlist] Update price error: {e}")
        if request.is_json:
            return jsonify({'error': str(e)}), 500
        flash("Fehler beim Preis-Update", "danger")
        return redirect(url_for('watchlist.index'))
    finally:
        db.close()


@bp.route('/settings/<int:item_id>', methods=['GET', 'POST'])
def settings(item_id):
    """Einstellungen für ein Watchlist Item"""
    db = SessionLocal()
    try:
        user = get_current_user(db)
        if not user:
            flash("Bitte einloggen", "warning")
            return redirect(url_for('login'))

        item = db.query(WatchedItem).filter_by(
            id=item_id,
            user_id=user.id
        ).first()

        if not item:
            flash("Item nicht gefunden", "warning")
            return redirect(url_for('watchlist.index'))

        if request.method == 'POST':
            # Update Einstellungen
            item.notify_price_drop = request.form.get('notify_price_drop') == 'on'
            item.notify_auction_ending = request.form.get('notify_auction_ending') == 'on'
            item.price_drop_threshold = int(request.form.get('price_drop_threshold', 5))
            db.commit()
            flash("✅ Einstellungen gespeichert", "success")
            return redirect(url_for('watchlist.index'))

        return render_template('watchlist/settings.html', item=item)

    finally:
        db.close()


@bp.route('/stats')
def stats():
    """Zeigt Statistiken zur Watchlist"""
    db = SessionLocal()
    try:
        user = get_current_user(db)
        if not user:
            flash("Bitte einloggen", "warning")
            return redirect(url_for('login'))

        # Sammle Statistiken
        total_items = db.query(WatchedItem).filter_by(user_id=user.id).count()
        active_items = db.query(WatchedItem).filter_by(user_id=user.id, is_active=True).count()

        # Durchschnittliche Ersparnis berechnen
        items = db.query(WatchedItem).filter_by(user_id=user.id, is_active=True).all()
        total_savings = 0
        items_with_savings = 0

        for item in items:
            if item.initial_price and item.current_price:
                try:
                    initial = float(str(item.initial_price).replace('EUR', '').replace(',', '.').strip())
                    current = float(str(item.current_price).replace('EUR', '').replace(',', '.').strip())
                    if current < initial:
                        total_savings += (initial - current)
                        items_with_savings += 1
                except:
                    pass

        stats_data = {
            'total_items': total_items,
            'active_items': active_items,
            'total_savings': round(total_savings, 2),
            'items_with_savings': items_with_savings,
            'user': user
        }

        return render_template('watchlist/stats.html', **stats_data)

    finally:
        db.close()
