# routes/telegram.py – FINAL FIX 2025
from flask import Blueprint, render_template, request, jsonify, current_app, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy.orm import Session
from models import SessionLocal, User
from telegram_bot import TelegramBot
import os
import secrets

bp = Blueprint("telegram", __name__, url_prefix="/telegram")
pending_verifications = {}

@bp.route("/settings")
@login_required
def settings():
    print(f"[DEBUG] current_user: {current_user}, authenticated: {current_user.is_authenticated}")
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(id=current_user.id).first()
        if not user:
            flash("Benutzer nicht gefunden.", "danger")
            return redirect(url_for("login"))

        bot = TelegramBot()
        bot_configured = False
        try:
            bot_configured = bot.is_configured()
        except Exception as e:
            current_app.logger.error(f"[telegram] bot.is_configured() failed: {e}")

        return render_template(
            "telegram_settings.html",
            user=current_user,           # ← current_user!
            bot_configured=bot_configured
        )
    finally:
        db.close()


@bp.route("/connect", methods=["POST"])
@login_required
def connect():
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(id=current_user.id).first()
        if not user:
            return jsonify({"error": "User nicht gefunden"}), 404

        token = secrets.token_urlsafe(16)
        pending_verifications[token] = {"user_id": user.id, "email": user.email}

        bot_username = os.getenv("TELEGRAM_BOT_USERNAME")
        if not bot_username:
            bot = TelegramBot()
            if bot.is_configured():
                try:
                    bot_username = bot.get_username()
                except Exception as e:
                    current_app.logger.error(f"[telegram.connect] get_username failed: {e}")

        if not bot_username:
            bot_username = "ebay_superagent_bot"

        deep_link = f"https://t.me/{bot_username}?start={token}"
        return jsonify({"success": True, "deep_link": deep_link, "token": token})
    finally:
        db.close()
