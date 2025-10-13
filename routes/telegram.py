# routes/telegram.py
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
    #   flash("Bitte einloggen!", "warning")
    #   return redirect(url_for("login"))

    db: Session = SessionLocal()
    user = db.query(User).filter_by(id=session["user_id"]).first()

    if not user:
        db.close()
        return redirect(url_for("login"))

    # Bot Info
    bot = TelegramBot()
    bot_configured = bot.is_configured()

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

    # Bot Username für Deep Link
    bot = TelegramBot()
    bot_username = "ebay_superagent_bot"

    # Deep Link zum Bot
    deep_link = f"https://t.me/{bot_username}?start={token}"

    db.close()

    return jsonify({"success": True, "deep_link": deep_link, "token": token})


@bp.route("/verify/<token>")
def verify(token: str):
    """
    Webhook-Endpoint: Telegram Bot ruft dies auf wenn User /start sendet
    Alternative: User gibt Token manuell im Bot ein
    """
    chat_id = request.args.get("chat_id")

    if not chat_id:
        return jsonify({"error": "chat_id fehlt"}), 400

    # Token validieren
    verification = pending_verifications.get(token)

    if not verification:
        return jsonify({"error": "Ungültiger oder abgelaufener Token"}), 404

    user_id = verification["user_id"]

    # Telegram Verbindung verifizieren
    telegram_info = verify_telegram_connection(chat_id)

    if not telegram_info:
        return jsonify({"error": "Telegram Chat nicht gefunden"}), 404

    # User in DB updaten
    db: Session = SessionLocal()
    user = db.query(User).filter_by(id=user_id).first()

    if user:
        user.telegram_chat_id = chat_id
        user.telegram_username = telegram_info.get("username", "")
        user.telegram_verified = True
        user.telegram_enabled = True

        db.commit()

        # Willkommensnachricht senden
        send_welcome_notification(
            chat_id=chat_id, user_name=telegram_info.get("first_name", "User")
        )

        # Token löschen
        del pending_verifications[token]

        db.close()

        return jsonify({"success": True, "message": "Telegram erfolgreich verknüpft!"})

    db.close()
    return jsonify({"error": "User nicht gefunden"}), 404


@bp.route("/disconnect", methods=["POST"])
def disconnect():
    """Trennt Telegram-Verknüpfung"""
    if "user_id" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401

    db: Session = SessionLocal()
    user = db.query(User).filter_by(id=session["user_id"]).first()

    if user:
        user.telegram_chat_id = None
        user.telegram_username = None
        user.telegram_verified = False
        user.telegram_enabled = False

        db.commit()
        db.close()

        flash("Telegram-Verknüpfung getrennt", "success")
        return jsonify({"success": True})

    db.close()
    return jsonify({"error": "User nicht gefunden"}), 404


@bp.route("/toggle", methods=["POST"])
def toggle():
    """Aktiviert/Deaktiviert Telegram Notifications"""
    if "user_id" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401

    enabled = request.json.get("enabled", False)

    db: Session = SessionLocal()
    user = db.query(User).filter_by(id=session["user_id"]).first()

    if user and user.telegram_verified:
        user.telegram_enabled = enabled
        db.commit()
        db.close()

        status = "aktiviert" if enabled else "deaktiviert"
        return jsonify({"success": True, "message": f"Telegram-Alerts {status}"})

    db.close()
    return jsonify({"error": "Telegram nicht verknüpft"}), 400


@bp.route("/test", methods=["POST"])
def test_notification():
    """Sendet Test-Nachricht"""
    if "user_id" not in session:
        return jsonify({"error": "Nicht eingeloggt"}), 401

    db: Session = SessionLocal()
    user = db.query(User).filter_by(id=session["user_id"]).first()

    if not user or not user.telegram_chat_id:
        db.close()
        return jsonify({"error": "Telegram nicht verknüpft"}), 400

    # Test-Item
    test_item = {
        "title": "🧪 Test-Benachrichtigung - iPhone 15 Pro",
        "price": "999",
        "currency": "EUR",
        "url": "https://ebay.de",
        "condition": "Neu",
        "location": "Berlin",
    }

    from telegram_bot import send_new_item_alert

    success = send_new_item_alert(
        chat_id=user.telegram_chat_id,
        item=test_item,
        agent_name="Test-Agent",
        with_image=False,
    )

    db.close()

    if success:
        return jsonify({"success": True, "message": "Test-Nachricht gesendet!"})
    else:
        return jsonify({"success": False, "message": "Fehler beim Senden"}), 500


# Webhook Endpoint (optional, für fortgeschrittene Nutzung)
@bp.route("/webhook", methods=["POST"])
def webhook():
    """
    Telegram Webhook Handler
    Muss bei Telegram registriert werden:
    https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://deine-domain.com/telegram/webhook
    """
    update = request.json

    # Verarbeite /start Command mit Token
    if "message" in update:
        message = update["message"]
        text = message.get("text", "")
        chat_id = str(message["chat"]["id"])

        if text.startswith("/start "):
            token = text.split(" ", 1)[1]

            # Verifiziere User
            verification = pending_verifications.get(token)

            if verification:
                user_id = verification["user_id"]

                db: Session = SessionLocal()
                user = db.query(User).filter_by(id=user_id).first()

                if user:
                    user.telegram_chat_id = chat_id
                    user.telegram_username = message.get("from", {}).get("username", "")
                    user.telegram_verified = True
                    user.telegram_enabled = True

                    db.commit()
                    db.close()

                    # Willkommensnachricht
                    send_welcome_notification(
                        chat_id=chat_id,
                        user_name=message.get("from", {}).get("first_name", "User"),
                    )

                    del pending_verifications[token]

                    return jsonify({"ok": True})

                db.close()

    return jsonify({"ok": True})
