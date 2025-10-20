# routes/watchlist.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from sqlalchemy.orm import Session
from models import SessionLocal, User, WatchedItem
from datetime import datetime

bp = Blueprint("watchlist", __name__, url_prefix="/watchlist")


@bp.route("/")
def index():
    """Watchlist-Übersicht"""
    if "user_id" not in session:
        flash("Bitte einloggen!", "warning")
        return redirect(url_for("login"))

    db: Session = SessionLocal()
    user = db.query(User).filter_by(id=session["user_id"]).first()

    if not user:
        db.close()
        return redirect(url_for("login"))

    # Hole alle beobachteten Items
    watched = db.query(WatchedItem).filter_by(
        user_id=user.id,
        is_active=True
    ).order_by(WatchedItem.created_at.desc()).all()

    db.close()

    return render_template("watchlist.html", items=watched, user=user)


@bp.route("/add", methods=["POST"])
def add():
    """Fügt Item zur Watchlist hinzu"""
    if "user_id" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401

    # Daten aus Request
    ebay_item_id = request.json.get("item_id")
    title = request.json.get("title")
    url = request.json.get("url")
    price = request.json.get("price")
    image = request.json.get("image")
    currency = request.json.get("currency", "EUR")

    if not ebay_item_id or not title:
        return jsonify({"error": "Fehlende Daten"}), 400

    db: Session = SessionLocal()
    user = db.query(User).filter_by(id=session["user_id"]).first()

    if not user:
        db.close()
        return jsonify({"error": "User nicht gefunden"}), 404

    # Prüfe ob bereits beobachtet
    existing = db.query(WatchedItem).filter_by(
        user_id=user.id,
        ebay_item_id=ebay_item_id
    ).first()

    if existing:
        db.close()
        return jsonify({"error": "Bereits auf Watchlist"}), 409

    # Erstelle neues WatchedItem
    watched = WatchedItem(
        user_id=user.id,
        ebay_item_id=ebay_item_id,
        item_title=title,
        item_url=url,
        image_url=image,
        initial_price=price,
        current_price=price,
        lowest_price=price,
        currency=currency
    )

    db.add(watched)
    db.commit()
    db.close()

    return jsonify({
        "success": True,
        "message": "Zur Watchlist hinzugefügt"
    })


@bp.route("/remove/<int:item_id>", methods=["POST"])
def remove(item_id):
    """Entfernt Item von Watchlist"""
    if "user_id" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401

    db: Session = SessionLocal()

    item = db.query(WatchedItem).filter_by(
        id=item_id,
        user_id=session["user_id"]
    ).first()

    if not item:
        db.close()
        return jsonify({"error": "Item nicht gefunden"}), 404

    # Soft-Delete (oder hard delete mit db.delete(item))
    item.is_active = False
    db.commit()
    db.close()

    return jsonify({"success": True})


@bp.route("/settings/<int:item_id>", methods=["GET", "POST"])
def settings(item_id):
    """Einstellungen für beobachtetes Item"""
    if "user_id" not in session:
        flash("Bitte einloggen!", "warning")
        return redirect(url_for("login"))

    db: Session = SessionLocal()

    item = db.query(WatchedItem).filter_by(
        id=item_id,
        user_id=session["user_id"]
    ).first()

    if not item:
        db.close()
        flash("Item nicht gefunden", "error")
        return redirect(url_for("watchlist.index"))

    if request.method == "POST":
        # Update Settings
        item.notify_price_drop = "notify_price_drop" in request.form
        item.notify_auction_ending = "notify_auction_ending" in request.form
        item.price_drop_threshold = int(request.form.get("threshold", 5))

        db.commit()
        db.close()

        flash("Einstellungen gespeichert", "success")
        return redirect(url_for("watchlist.index"))

    db.close()

    return render_template("watchlist_settings.html", item=item)


@bp.route("/check-updates")
def check_updates():
    """Prüft alle Watchlist-Items auf Updates (wird von Cron aufgerufen)"""
    # TODO: Token-basierte Authentifizierung
    token = request.args.get("token")

    if token != os.getenv("CRON_TOKEN", ""):
        return jsonify({"error": "Unauthorized"}), 401

    db: Session = SessionLocal()

    # Hole alle aktiven Watchlist-Items
    items = db.query(WatchedItem).filter_by(is_active=True).all()

    updated_count = 0

    for item in items:
        # TODO: eBay API aufrufen um aktuellen Preis zu holen
        # Für jetzt: Placeholder
        # new_price = fetch_current_price(item.ebay_item_id)

        # Wenn Preis gesunken: Benachrichtigung senden
        # if new_price < item.current_price:
        #     send_price_drop_notification(item.user, item, new_price)

        item.last_checked = datetime.utcnow()
        updated_count += 1

    db.commit()
    db.close()

    return jsonify({
        "success": True,
        "items_checked": updated_count
    })
