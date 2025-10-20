# routes/notifications.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from sqlalchemy.orm import Session
from models import SessionLocal, User, NotificationSettings
from utils.notification_manager import get_notification_manager

bp = Blueprint("notifications", __name__, url_prefix="/notifications")


@bp.route("/settings", methods=["GET", "POST"])
def settings():
    """Benachrichtigungs-Einstellungen"""
    if "user_id" not in session:
        flash("Bitte einloggen!", "warning")
        return redirect(url_for("login"))

    db: Session = SessionLocal()
    user = db.query(User).filter_by(id=session["user_id"]).first()

    if not user:
        db.close()
        return redirect(url_for("login"))

    # Hole oder erstelle Settings
    settings_obj = db.query(NotificationSettings).filter_by(user_id=user.id).first()

    if not settings_obj:
        settings_obj = NotificationSettings(user_id=user.id)
        db.add(settings_obj)
        db.commit()

    if request.method == "POST":
        # Update Settings
        settings_obj.email_enabled = "email_enabled" in request.form
        settings_obj.telegram_enabled = "telegram_enabled" in request.form
        settings_obj.sms_enabled = "sms_enabled" in request.form

        settings_obj.quiet_hours_enabled = "quiet_hours_enabled" in request.form
        settings_obj.quiet_hours_start = request.form.get("quiet_hours_start", "22:00")
        settings_obj.quiet_hours_end = request.form.get("quiet_hours_end", "08:00")

        settings_obj.max_notifications_per_day = int(request.form.get("max_notifications_per_day", 50))
        settings_obj.max_notifications_per_hour = int(request.form.get("max_notifications_per_hour", 10))

        settings_obj.batch_notifications = "batch_notifications" in request.form
        settings_obj.batch_time = request.form.get("batch_time", "09:00")

        settings_obj.only_high_priority = "only_high_priority" in request.form
        settings_obj.min_price_drop_percent = int(request.form.get("min_price_drop_percent", 5))

        db.commit()
        db.close()

        flash("Einstellungen gespeichert!", "success")
        return redirect(url_for("notifications.settings"))

    # Hole Statistiken
    manager = get_notification_manager()
    stats = manager.get_notification_stats(user.id, days=7)

    db.close()

    return render_template(
        "notification_settings.html",
        settings=settings_obj,
        user=user,
        stats=stats
    )
