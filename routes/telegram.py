# routes/telegram.py
import os
import time
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
from sqlalchemy.orm import Session

from models import SessionLocal, User
from telegram_bot import (
    TelegramBot,
    send_welcome_notification,
    verify_telegram_connection,
)

bp = Blueprint("telegram", __name__, url_prefix="/telegram")

# Temporärer Speicher für Verknüpfungs-Tokens (in Production: Redis nutzen!)
pending_verifications = {}


@bp.route("/settings")
def settings():
    """Telegram Settings Seite"""
    if "user_id" not in session:
        session["user_id"] = 1  # TEMPORÄR - deine Test-User-ID

    db: Session = SessionLocal()
    user = db.query(User).filter_by(id=session["user_id"]).first()

    if not user:
        db.close()
        return redirect(url_for("login"))

    # Bot Info
    bot = TelegramBot()
    bot_configured = False
    try:
        bot_configured = bot.is_configured()
    except Exception:
        current_app.logger.exception("[telegram.settings] bot.is_configured() failed")

    db.close()

    return render_template(
        "telegram_settings.html", user=user, bot_configured=bot_configured
    )


@bp.route("/connect", methods=["POST"])
def connect():
    """Startet Telegram-Verknüpfung"""
    if "user_id" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401

    db: Session = SessionLocal()
    user = db.query(User).filter_by(id=session["user_id"]).first()

    if not user:
        db.close()
        return jsonify({"error": "User nicht gefunden"}), 404

    # Generiere eindeutigen Token
    token = secrets.token_urlsafe(16)

    # Speichere Token (in Production: Redis mit TTL!)
    pending_verifications[token] = {"user_id": user.id, "email": user.email}

    # Bot Username für Deep Link:
    # 1) zuerst aus ENV lesen (TELEGRAM_BOT_USERNAME)
    # 2) falls nicht gesetzt → bot.get_username() (ruft Telegram getMe)
    bot = TelegramBot()
    bot_username = os.getenv("TELEGRAM_BOT_USERNAME")  # user-set in .env (ohne @)

    if not bot_username and bot.is_configured():
        try:
            bot_username = bot.get_username()
        except Exception:
            current_app.logger.exception("[telegram.connect] bot.get_username() failed")

    # Fallback falls weiterhin nichts gefunden wurde
    if not bot_username:
        bot_username = "ebay_superagent_bot"  # nur als letzte Absicherung

    # Deep Link zum Bot (username ohne @)
    deep_link = f"https://t.me/{bot_username}?start={token}"

    db.close()

    return jsonify({"success": True, "deep_link": deep_link, "token": token})
