# routes/watchlist.py - Watchlist Routes für eBay Items (2025 FIX – Flask-Login)
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    current_app,
)

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

# WICHTIG: aus models importieren – nicht aus routes
from models import SessionLocal, WatchedItem
from database import get_db, get_placeholder


bp = Blueprint("watchlist", __name__, url_prefix="/watchlist")



@bp.route('/')
@login_required
def index():
    """Zeigt die Watchlist des Users"""
    db = SessionLocal()
    try:
        user_id = current_user.id  # ← Kein session["user_id"] mehr!

        items = (
            db.query(WatchedItem)
            .filter_by(user_id=user_id, is_active=True)
            .order_by(WatchedItem.created_at.desc())
            .all()
        )

        # Preisänderungen berechnen
        for item in items:
            if item.initial_price and item.current_price:
                try:
                    initial = float(str(item.initial_price).replace('EUR', '').replace(',', '.').strip())
                    current = float(str(item.current_price).replace('EUR', '').replace(',', '.').strip())
                    item.price_change = current - initial
                    item.price_change_percent = ((current - initial) / initial * 100) if initial > 0 else 0
                except Exception as e:
                    current_app.logger.error(f"[watchlist] Price calc error: {e}")
                    item.price_change = 0
                    item.price_change_percent = 0
            else:
                item.price_change = 0
                item.price_change_percent = 0

        return render_template(
            'watchlist/index.html',
            items=items,
            user=current_user,  # ← current_user statt DB-Abfrage
            item_count=len(items)
        )
    finally:
        db.close()


@bp.route('/add', methods=['POST'])
@login_required
def add():
    """Fügt ein Item zur Watchlist hinzu"""
    db = SessionLocal()
    try:
        user_id = current_user.id

        item_id = request.form.get('item_id', '').strip()
        title = request.form.get('title', '').strip()
        price = request.form.get('price', '').strip()
        url = request.form.get('url', '').strip()
        image_url = request.form.get('image_url', '').strip()

        if not item_id or not title:
            flash("Fehlende Artikeldaten.", "danger")
            return redirect(request.referrer or url_for('search.index'))

        # Prüfe auf Duplikat
        existing = db.query(WatchedItem).filter_by(
            user_id=user_id, ebay_item_id=item_id
        ).first()

        if existing:
            if not existing.is_active:
                existing.is_active = True
                existing.last_checked = datetime.utcnow()
                db.commit()
                flash(f"Reaktiviert: {title[:40]}...", "success")
            else:
                flash(f"Bereits in Watchlist: {title[:40]}...", "info")
        else:
            watched_item = WatchedItem(
                user_id=user_id,
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

            # Erster Preis-Tracking-Eintrag
            try:
                price_val = float(price.replace('EUR', '').replace(',', '.').strip()) if price else 0.0
                db.add(ItemPriceTracking(
                    watched_item_id=watched_item.id,
                    price=price_val,
                    currency='EUR',
                    item_available=True,
                    recorded_at=datetime.utcnow()
                ))
                db.commit()
            except Exception as e:
                current_app.logger.warning(f"[watchlist] Price tracking failed: {e}")

            flash(f"Hinzugefügt: {title[:40]}...", "success")

        return redirect(request.referrer or url_for('watchlist.index'))
    except Exception as e:
        db.rollback()
        current_app.logger.error(f"[watchlist.add] Error: {e}", exc_info=True)
        flash("Fehler beim Hinzufügen.", "danger")
        return redirect(request.referrer or url_for('search.index'))
    finally:
        db.close()


@bp.route('/remove/<int:item_id>', methods=['POST'])
@login_required
def remove(item_id):
    db = SessionLocal()
    try:
        # 1. Watchlist-Eintrag per ORM suchen
        item = db.query(WatchedItem).filter_by(id=item_id, user_id=current_user.id).first()

        if item:
            item.is_active = False
            db.commit()
            return jsonify({'success': True, 'message': f"'{item.item_title[:40]}...' entfernt"})

        # 2. Fallback: Alert aus search_alerts (DB-Layer mit get_db)
        conn = get_db()
        cur = conn.cursor()
        ph = get_placeholder()   # ? für SQLite, %s für Postgres

        cur.execute(
            f"DELETE FROM search_alerts WHERE id = {ph} AND user_email = {ph}",
            (item_id, current_user.email)
        )
        conn.commit()
        conn.close()

        return jsonify({'success': True, 'message': 'Alert gelöscht'})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        db.close()




@bp.route('/update-price/<int:item_id>', methods=['POST'])
@login_required
def update_price(item_id):
    db = SessionLocal()
    try:
        item = db.query(WatchedItem).filter_by(id=item_id, user_id=current_user.id).first()
        if not item:
            return jsonify({'error': 'Item nicht gefunden'}), 404

        new_price = request.json.get('price') if request.is_json else request.form.get('price')
        if not new_price:
            return jsonify({'error': 'Kein Preis übergeben'}), 400

        old_price = item.current_price
        item.current_price = new_price
        item.last_checked = datetime.utcnow()

        # Niedrigsten Preis aktualisieren
        try:
            new_val = float(new_price.replace('EUR', '').replace(',', '.').strip())
            if not item.lowest_price or new_val < float(item.lowest_price.replace('EUR', '').replace(',', '.').strip()):
                item.lowest_price = new_price
        except:
            pass

        # Preis-Tracking
        try:
            db.add(ItemPriceTracking(
                watched_item_id=item.id,
                price=new_val,
                currency='EUR',
                item_available=True,
                recorded_at=datetime.utcnow()
            ))
        except:
            pass

        db.commit()

        # Preissenkung prüfen
        if old_price and item.notify_price_drop:
            try:
                old_val = float(old_price.replace('EUR', '').replace(',', '.').strip())
                drop_percent = ((old_val - new_val) / old_val * 100)
                if drop_percent >= item.price_drop_threshold:
                    flash(f"Preissenkung! {item.item_title[:30]}... jetzt {drop_percent:.1f}% günstiger!", "success")
            except:
                pass

        return jsonify({'success': True, 'new_price': new_price})
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()


@bp.route('/settings/<int:item_id>', methods=['GET', 'POST'])
@login_required
def settings(item_id):
    db = SessionLocal()
    try:
        item = db.query(WatchedItem).filter_by(id=item_id, user_id=current_user.id).first()
        if not item:
            flash("Item nicht gefunden", "warning")
            return redirect(url_for('watchlist.index'))

        if request.method == 'POST':
            item.notify_price_drop = request.form.get('notify_price_drop') == 'on'
            item.notify_auction_ending = request.form.get('notify_auction_ending') == 'on'
            item.price_drop_threshold = int(request.form.get('price_drop_threshold', 5))
            db.commit()
            flash("Einstellungen gespeichert", "success")
            return redirect(url_for('watchlist.index'))

        return render_template('watchlist/settings.html', item=item)
    finally:
        db.close()


@bp.route('/stats')
@login_required
def stats():
    db = SessionLocal()
    try:
        items = db.query(WatchedItem).filter_by(user_id=current_user.id, is_active=True).all()
        total_items = len(items)
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

        return render_template('watchlist/stats.html',
            total_items=total_items,
            active_items=total_items,
            total_savings=round(total_savings, 2),
            items_with_savings=items_with_savings,
            user=current_user
        )
    finally:
        db.close()
