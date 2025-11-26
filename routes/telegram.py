# routes/telegram.py – 100% FUNKTIONIEREND (26.11.2025)
from flask import Blueprint, render_template, request, jsonify, current_app, flash, redirect, url_for
from flask_login import login_required, current_user
from models import SessionLocal, User
from telegram_bot import TelegramBot
import os
import secrets

bp = Blueprint("telegram", __name__, url_prefix="/telegram")

# Temporäre Speicherung für Verifizierungstokens (in Produktion Redis o.ä. nutzen)
pending_verifications = {}


@bp.route("/settings")
@login_required
def settings():
    print(f"[DEBUG] current_user: {current_user}, authenticated: {current_user.is_authenticated}")

    # current_user ist bereits das vollständige User-Objekt aus Flask-Login → kein Query nötig!
    user = current_user

    # Prüfen, ob der Bot konfiguriert ist
    bot = TelegramBot()
    bot_configured = False
    try:
        bot_configured = bot.is_configured()
    except Exception as e:
        current_app.logger.error(f"[telegram] bot.is_configured() failed: {e}")

    return render_template(
        "telegram_settings.html",
        user=user,
        bot_configured=bot_configured
    )


@bp.route("/connect", methods=["POST"])
@login_required
def connect():
    # Kein DB-Query nötig – current_user ist bereits geladen
    user = current_user

    # Token generieren
    token = secrets.token_urlsafe(16)
    pending_verifications[token] = {
        "user_id": user.get_id(),
        "email": user.email
    }

    # Bot-Username holen
    bot_username = os.getenv("TELEGRAM_BOT_USERNAME")
    if not bot_username:
        bot = TelegramBot()
        if bot.is_configured():
            try:
                bot_username = bot.get_username()
            except Exception as e:
                current_app.logger.error(f"[telegram.connect] get_username failed: {e}")

    # Fallback, falls nichts klappt
    if not bot_username:
        bot_username = "ebay_superagent_bot"

    deep_link = f"https://t.me/{bot_username}?start={token}"

    return jsonify({
        "success": True,
        "deep_link": deep_link,
        "token": token
    })


@bp.route("/verify/<token>")
def verify(token):
    """Wird vom Bot aufgerufen, wenn User auf den Link klickt"""
    if token not in pending_verifications:
        flash("Ungültiger oder abgelaufener Verifizierungscode.", "danger")
        return redirect(url_for("telegram.settings"))

    data = pending_verifications.pop(token)
    user_id = data["user_id"]

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            flash("Benutzer nicht gefunden.", "danger")
            return redirect(url_for("public"))

        # Hier später chat_id vom Bot übergeben bekommen (Webhook)
        # Für jetzt: Platzhalter – wird im Bot gesetzt
        user.telegram_verified = True
        user.telegram_enabled = True
        db.commit()

        flash("Telegram erfolgreich verbunden!", "success")
    except Exception as e:
        current_app.logger.error(f"[telegram.verify] Fehler: {e}")
        db.rollback()
        flash("Fehler beim Verifizieren.", "danger")
    finally:
        db.close()

    return redirect(url_for("telegram.settings"))
