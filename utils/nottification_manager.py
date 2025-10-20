# utils/notification_manager.py
from datetime import datetime, timedelta
from typing import Dict, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from models import SessionLocal, User, NotificationSettings, NotificationLog, WatchedItem, SearchAgent


class NotificationManager:
    """Intelligente Benachrichtigungs-Steuerung"""

    def __init__(self):
        self.db: Optional[Session] = None

    def _get_db(self):
        if not self.db:
            self.db = SessionLocal()
        return self.db

    def _close_db(self):
        if self.db:
            self.db.close()
            self.db = None

    def can_send_notification(self, user_id: int, channel: str = "email") -> Dict:
        """
        Prüft ob Notification gesendet werden kann

        Returns:
            {
                "allowed": bool,
                "reason": str
            }
        """
        db = self._get_db()

        # Hole Settings
        settings = db.query(NotificationSettings).filter_by(user_id=user_id).first()

        if not settings:
            # Erstelle Default Settings
            settings = NotificationSettings(user_id=user_id)
            db.add(settings)
            db.commit()

        # 1. Prüfe ob Kanal aktiviert
        if channel == "email" and not settings.email_enabled:
            return {"allowed": False, "reason": "E-Mail deaktiviert"}
        if channel == "telegram" and not settings.telegram_enabled:
            return {"allowed": False, "reason": "Telegram deaktiviert"}

        # 2. Prüfe Ruhezeiten
        if settings.quiet_hours_enabled:
            now = datetime.now().time()
            start = datetime.strptime(settings.quiet_hours_start, "%H:%M").time()
            end = datetime.strptime(settings.quiet_hours_end, "%H:%M").time()

            # Behandle Übernacht-Ruhezeiten (z.B. 22:00 - 08:00)
            if start > end:
                in_quiet = now >= start or now <= end
            else:
                in_quiet = start <= now <= end

            if in_quiet:
                return {"allowed": False, "reason": "Ruhezeit aktiv"}

        # 3. Prüfe Tages-Limit
        today_start = datetime.now().replace(hour=0, minute=0, second=0)
        today_count = db.query(func.count(NotificationLog.id)).filter(
            NotificationLog.user_id == user_id,
            NotificationLog.created_at >= today_start,
            NotificationLog.status == "sent"
        ).scalar()

        if today_count >= settings.max_notifications_per_day:
            return {"allowed": False, "reason": f"Tages-Limit erreicht ({settings.max_notifications_per_day})"}

        # 4. Prüfe Stunden-Limit
        hour_ago = datetime.now() - timedelta(hours=1)
        hour_count = db.query(func.count(NotificationLog.id)).filter(
            NotificationLog.user_id == user_id,
            NotificationLog.created_at >= hour_ago,
            NotificationLog.status == "sent"
        ).scalar()

        if hour_count >= settings.max_notifications_per_hour:
            return {"allowed": False, "reason": f"Stunden-Limit erreicht ({settings.max_notifications_per_hour})"}

        return {"allowed": True, "reason": None}

    def send_notification(
        self,
        user_id: int,
        notification_type: str,
        channel: str,
        subject: str,
        content: str,
        watched_item_id: Optional[int] = None,
        agent_id: Optional[int] = None,
        priority: str = "normal"
    ) -> Dict:
        """
        Sendet eine Benachrichtigung (oder queued sie)

        Args:
            user_id: User ID
            notification_type: "price_drop", "new_item", "auction_ending", etc.
            channel: "email", "telegram", "sms"
            subject: Betreff
            content: Inhalt
            watched_item_id: Optional - ID des beobachteten Items
            agent_id: Optional - ID des Such-Agenten
            priority: "low", "normal", "high"

        Returns:
            {
                "sent": bool,
                "reason": str,
                "log_id": int
            }
        """
        db = self._get_db()

        # Prüfe ob senden erlaubt
        check = self.can_send_notification(user_id, channel)

        # Erstelle Log-Eintrag
        log = NotificationLog(
            user_id=user_id,
            notification_type=notification_type,
            channel=channel,
            subject=subject,
            content=content,
            watched_item_id=watched_item_id,
            agent_id=agent_id,
            status="pending"
        )

        db.add(log)
        db.commit()

        if not check["allowed"]:
            # Nicht erlaubt → markiere als skipped
            log.status = "skipped"
            log.error_message = check["reason"]
            db.commit()

            return {
                "sent": False,
                "reason": check["reason"],
                "log_id": log.id
            }

        # Sende tatsächlich
        try:
            if channel == "email":
                success = self._send_email(user_id, subject, content)
            elif channel == "telegram":
                success = self._send_telegram(user_id, content)
            else:
                success = False

            if success:
                log.status = "sent"
                log.sent_at = datetime.utcnow()
            else:
                log.status = "failed"
                log.error_message = "Versand fehlgeschlagen"

            db.commit()

            return {
                "sent": success,
                "reason": None if success else "Versand fehlgeschlagen",
                "log_id": log.id
            }

        except Exception as e:
            log.status = "failed"
            log.error_message = str(e)
            db.commit()

            return {
                "sent": False,
                "reason": str(e),
                "log_id": log.id
            }

    def _send_email(self, user_id: int, subject: str, content: str) -> bool:
        """Sendet E-Mail (nutzt bestehende mailer.py)"""
        try:
            from mailer import send_mail

            db = self._get_db()
            user = db.query(User).filter_by(id=user_id).first()

            if not user:
                return False

            return send_mail(
                to_email=user.email,
                subject=subject,
                text_body=content,
                html_body=f"<p>{content}</p>"
            )
        except Exception as e:
            print(f"[NOTIFICATION] E-Mail Fehler: {e}")
            return False

    def _send_telegram(self, user_id: int, content: str) -> bool:
        """Sendet Telegram (nutzt bestehende telegram_bot.py)"""
        try:
            from telegram_bot import TelegramBot

            db = self._get_db()
            user = db.query(User).filter_by(id=user_id).first()

            if not user or not user.telegram_chat_id:
                return False

            bot = TelegramBot()
            return bot.send_message(user.telegram_chat_id, content)

        except Exception as e:
            print(f"[NOTIFICATION] Telegram Fehler: {e}")
            return False

    def send_price_drop_alert(self, watched_item_id: int, old_price: float, new_price: float) -> Dict:
        """Spezialisierte Funktion für Preis-Senkung"""
        db = self._get_db()

        watched = db.query(WatchedItem).filter_by(id=watched_item_id).first()

        if not watched:
            return {"sent": False, "reason": "Item nicht gefunden"}

        # Prüfe ob User Preis-Drops will
        settings = db.query(NotificationSettings).filter_by(user_id=watched.user_id).first()

        if settings and settings.only_high_priority:
            drop_percent = ((old_price - new_price) / old_price) * 100
            if drop_percent < settings.min_price_drop_percent:
                return {"sent": False, "reason": f"Preissenkung zu gering ({drop_percent:.1f}% < {settings.min_price_drop_percent}%)"}

        drop_amount = old_price - new_price
        drop_percent = ((old_price - new_price) / old_price) * 100

        subject = f"💰 Preis gesenkt: {watched.item_title[:50]}"
        content = f"""
Gute Nachrichten! Der Preis für ein beobachtetes Item ist gesunken:

"{watched.item_title}"

Alter Preis: {old_price:.2f} {watched.currency}
Neuer Preis: {new_price:.2f} {watched.currency}

Ersparnis: {drop_amount:.2f} {watched.currency} ({drop_percent:.1f}%)

Link: {watched.item_url}
        """.strip()

        # Sende via beide Kanäle
        results = {}

        # E-Mail
        email_result = self.send_notification(
            user_id=watched.user_id,
            notification_type="price_drop",
            channel="email",
            subject=subject,
            content=content,
            watched_item_id=watched_item_id,
            priority="high"
        )
        results["email"] = email_result

        # Telegram
        telegram_result = self.send_notification(
            user_id=watched.user_id,
            notification_type="price_drop",
            channel="telegram",
            subject=subject,
            content=content,
            watched_item_id=watched_item_id,
            priority="high"
        )
        results["telegram"] = telegram_result

        return {
            "sent": email_result["sent"] or telegram_result["sent"],
            "channels": results
        }

    def get_notification_stats(self, user_id: int, days: int = 7) -> Dict:
        """Holt Benachrichtigungs-Statistiken"""
        db = self._get_db()

        since = datetime.utcnow() - timedelta(days=days)

        total = db.query(func.count(NotificationLog.id)).filter(
            NotificationLog.user_id == user_id,
            NotificationLog.created_at >= since
        ).scalar()

        sent = db.query(func.count(NotificationLog.id)).filter(
            NotificationLog.user_id == user_id,
            NotificationLog.created_at >= since,
            NotificationLog.status == "sent"
        ).scalar()

        skipped = db.query(func.count(NotificationLog.id)).filter(
            NotificationLog.user_id == user_id,
            NotificationLog.created_at >= since,
            NotificationLog.status == "skipped"
        ).scalar()

        failed = db.query(func.count(NotificationLog.id)).filter(
            NotificationLog.user_id == user_id,
            NotificationLog.created_at >= since,
            NotificationLog.status == "failed"
        ).scalar()

        return {
            "days": days,
            "total": total,
            "sent": sent,
            "skipped": skipped,
            "failed": failed
        }

    def __del__(self):
        self._close_db()


# Singleton
_manager = None

def get_notification_manager() -> NotificationManager:
    global _manager
    if _manager is None:
        _manager = NotificationManager()
    return _manager


# Test
if __name__ == "__main__":
    manager = get_notification_manager()

    # Test: Kann Notification senden?
    result = manager.can_send_notification(user_id=1, channel="email")
    print(result)
