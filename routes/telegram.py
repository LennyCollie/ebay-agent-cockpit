# routes/telegram.py
import os
import secrets
from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
    current_app,
)
from flask_login import login_required, current_user   # ← NEU!
from sqlalchemy.orm import Session
from models import SessionLocal, User
from telegram_bot import (
    TelegramBot,
    send_welcome_notification,
    verify_telegram_connection,
)

bp = Blueprint("telegram", __name__, url_prefix="/telegram")

# Temporärer Speicher für Verknüpfungs-Tokens (in Production: Redis!)
pending_verifications = {}

@bp.route("/settings")
@login_required                                 # ← Jetzt richtig mit Flask-Login!
def settings():
    """Telegram Settings Seite"""
    # Kein session["user_id"] mehr nötig – current_user ist da!
    db: Session = SessionLocal()
    try:
        user = db.query(User).filter_by(id=current_user.id).first()
        if not user:
            flash("Benutzer nicht gefunden.", "danger")
            return redirect(url_for("login"))

        # Bot Info
        bot = TelegramBot()
        bot_configured = False
        try:
            bot_configured = bot.is_configured()
        except Exception:
            current_app.logger.exception("[telegram.settings] bot.is_configured() failed")

        return render_template(
            "telegram_settings.html",
            user=user,
            bot_configured=bot_configured
        )
    finally:
        db.close()


@bp.route("/connect", methods=["POST"])
@login_required                                 # ← Auch hier!
def connect():
    """Startet Telegram-Verknüpfung"""
    db: Session = SessionLocal()
    try:
        user = db.query(User).filter_by(id=current_user.id).first()
        if not user:
            return jsonify({"error": "User nicht gefunden"}), 404

        # Generiere Token
        token = secrets.token_urlsafe(16)
        pending_verifications[token] = {
            "user_id": user.id,
            "email": user.email
        }

        # Bot Username
        bot_username = os.getenv("TELEGRAM_BOT_USERNAME")
        if not bot_username:
            bot = TelegramBot()
            if bot.is_configured():
                try:
                    bot_username = bot.get_username()
                except Exception:
                    current_app.logger.exception("[telegram.connect] get_username failed")

        if not bot_username:
            bot_username = "ebay_superagent_bot"

        deep_link = f"https://t.me/{bot_username}?start={token}"

        return jsonify({"success": True, "deep_link": deep_link, "token": token})
    finally:
        db.close()
