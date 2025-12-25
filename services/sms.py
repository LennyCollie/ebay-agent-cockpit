import os
import secrets
import string
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import phonenumbers
from models import SMSNotificationSetting, SMSSendLog, SessionLocal

try:
    from twilio.rest import Client
    TWILIO_ENABLED = True
except ImportError:
    TWILIO_ENABLED = False


class SMSManager:
    ALERT_TYPES = {
        "price_drop": "Preis-Drop",
        "new_item": "Neuer Artikel",
        "auction_ending": "Auktion endet bald",
        "bid_outbid": "Du wurdest überboten",
        "item_sold": "Artikel verkauft",
        "daily_summary": "Tägliche Zusammenfassung",
    }

    def __init__(self):
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
        self.from_number = os.getenv("TWILIO_PHONE_NUMBER", "")
        self.client = None
        
        if TWILIO_ENABLED and self.account_sid and self.auth_token:
            self.client = Client(self.account_sid, self.auth_token)

    def validate_phone_number(self, phone: str, country_code: str = "DE") -> tuple[bool, str]:
        """Validate and normalize phone number"""
        try:
            parsed = phonenumbers.parse(phone, country_code)
            if not phonenumbers.is_valid_number(parsed):
                return False, "Ungültige Telefonnummer"
            
            formatted = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
            return True, formatted
        except phonenumbers.NumberParseException as e:
            return False, f"Fehler beim Parsen: {str(e)}"

    def generate_verification_code(self) -> str:
        """Generate 6-digit verification code"""
        return ''.join(secrets.choice(string.digits) for _ in range(6))

    def initiate_phone_verification(self, user_id: int, phone_number: str) -> tuple[bool, str]:
        """Start phone number verification process"""
        db = SessionLocal()
        try:
            is_valid, normalized = self.validate_phone_number(phone_number)
            if not is_valid:
                return False, normalized

            settings = db.query(SMSNotificationSetting).filter_by(user_id=user_id).first()
            if not settings:
                settings = SMSNotificationSetting(user_id=user_id)
                db.add(settings)

            verification_code = self.generate_verification_code()
            settings.phone_number = normalized
            settings.verification_code = verification_code
            settings.verification_attempts = 0
            settings.phone_verified = False

            message = f"Dein Verificationscode für eBay-Agent: {verification_code}"
            
            if self.client and self.from_number:
                try:
                    self.client.messages.create(
                        body=message,
                        from_=self.from_number,
                        to=normalized
                    )
                except Exception as e:
                    return False, f"SMS konnte nicht gesendet werden: {str(e)}"
            else:
                print(f"[SMS-DEV] Verification code for {normalized}: {verification_code}")

            db.commit()
            return True, "Verificationscode wurde gesendet"

        except Exception as e:
            db.rollback()
            return False, f"Fehler: {str(e)}"
        finally:
            db.close()

    def verify_phone_number(self, user_id: int, code: str) -> tuple[bool, str]:
        """Verify phone number with code"""
        db = SessionLocal()
        try:
            settings = db.query(SMSNotificationSetting).filter_by(user_id=user_id).first()
            
            if not settings:
                return False, "Keine Einstellung gefunden"

            if settings.phone_verified:
                return False, "Telefonnummer ist bereits verifiziert"

            settings.verification_attempts += 1
            if settings.verification_attempts > 3:
                return False, "Zu viele Versuche. Bitte neuen Code anfordern"

            if settings.verification_code != code:
                db.commit()
                return False, f"Ungültiger Code ({3 - settings.verification_attempts} Versuche verbleibend)"

            settings.phone_verified = True
            settings.verification_code = None
            settings.verification_attempts = 0

            db.commit()
            return True, "Telefonnummer erfolgreich verifiziert!"

        except Exception as e:
            db.rollback()
            return False, f"Fehler: {str(e)}"
        finally:
            db.close()

    def update_sms_settings(self, user_id: int, **kwargs) -> Optional[SMSNotificationSetting]:
        """Update SMS notification settings"""
        db = SessionLocal()
        try:
            settings = db.query(SMSNotificationSetting).filter_by(user_id=user_id).first()
            
            if not settings:
                settings = SMSNotificationSetting(user_id=user_id)
                db.add(settings)

            allowed_fields = [
                "is_enabled", "alert_types", "max_sms_per_day",
                "quiet_hours_start", "quiet_hours_end"
            ]
            
            for key, value in kwargs.items():
                if key in allowed_fields:
                    if key == "alert_types" and isinstance(value, list):
                        setattr(settings, key, ",".join(value))
                    else:
                        setattr(settings, key, value)

            db.commit()
            return settings

        except Exception as e:
            db.rollback()
            print(f"[ERROR] Failed to update SMS settings: {e}")
            return None
        finally:
            db.close()

    def get_sms_settings(self, user_id: int) -> Optional[SMSNotificationSetting]:
        """Get SMS settings for user"""
        db = SessionLocal()
        try:
            return db.query(SMSNotificationSetting).filter_by(user_id=user_id).first()
        finally:
            db.close()

    def is_within_quiet_hours(self, settings: SMSNotificationSetting) -> bool:
        """Check if current time is within quiet hours"""
        now = datetime.now().time()
        start = datetime.strptime(settings.quiet_hours_start, "%H:%M").time()
        end = datetime.strptime(settings.quiet_hours_end, "%H:%M").time()

        if start <= end:
            return start <= now <= end
        else:
            return now >= start or now <= end

    def check_daily_limit(self, user_id: int, settings: SMSNotificationSetting) -> bool:
        """Check if user has exceeded daily SMS limit"""
        db = SessionLocal()
        try:
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            
            today_count = db.query(SMSSendLog).filter(
                SMSSendLog.user_id == user_id,
                SMSSendLog.status == "sent",
                SMSSendLog.sent_at >= today_start
            ).count()

            return today_count < settings.max_sms_per_day

        finally:
            db.close()

    def send_alert_sms(
        self,
        user_id: int,
        alert_type: str,
        message: str,
        test: bool = False
    ) -> tuple[bool, str]:
        """Send SMS alert to user"""
        db = SessionLocal()
        try:
            settings = self.get_sms_settings(user_id)
            
            if not settings or not settings.is_enabled or not settings.phone_verified:
                return False, "SMS-Benachrichtigungen nicht aktiviert"

            if not test and self.is_within_quiet_hours(settings):
                return False, "SMS während Ruhezeit nicht gesendet"

            if not test and not self.check_daily_limit(user_id, settings):
                return False, f"Tägliches Limit ({settings.max_sms_per_day} SMS) erreicht"

            log = SMSSendLog(
                user_id=user_id,
                settings_id=settings.id,
                phone_number=settings.phone_number,
                message_content=message,
                alert_type=alert_type,
                status="pending"
            )
            db.add(log)
            db.flush()

            if self.client and self.from_number:
                try:
                    response = self.client.messages.create(
                        body=message,
                        from_=self.from_number,
                        to=settings.phone_number
                    )
                    
                    log.status = "sent"
                    log.provider_message_id = response.sid
                    log.sent_at = datetime.utcnow()
                    log.cost_cents = int(response.price * 100) if response.price else 5
                    
                    settings.total_sms_sent += 1
                    settings.total_sms_cost += log.cost_cents / 100.0

                    db.commit()
                    return True, f"SMS gesendet (ID: {response.sid})"

                except Exception as e:
                    log.status = "failed"
                    log.error_message = str(e)
                    log.retry_count += 1
                    db.commit()
                    return False, f"SMS-Fehler: {str(e)}"
            else:
                log.status = "sent"
                log.sent_at = datetime.utcnow()
                log.cost_cents = 3
                settings.total_sms_sent += 1
                settings.total_sms_cost += 0.03
                print(f"[SMS-DEV] Message to {settings.phone_number}: {message}")
                db.commit()
                return True, "SMS im Dev-Modus gesendet"

        except Exception as e:
            db.rollback()
            return False, f"Fehler: {str(e)}"
        finally:
            db.close()

    def get_sms_logs(self, user_id: int, limit: int = 50) -> List[SMSSendLog]:
        """Get SMS send logs for user"""
        db = SessionLocal()
        try:
            return db.query(SMSSendLog).filter_by(user_id=user_id).order_by(
                SMSSendLog.created_at.desc()
            ).limit(limit).all()
        finally:
            db.close()

    def get_sms_statistics(self, user_id: int) -> Dict:
        """Get SMS statistics for user"""
        db = SessionLocal()
        try:
            settings = db.query(SMSNotificationSetting).filter_by(user_id=user_id).first()
            
            if not settings:
                return {
                    "phone_verified": False,
                    "total_sms_sent": 0,
                    "total_cost": 0.0,
                    "today_sent": 0,
                    "month_sent": 0
                }

            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

            today_logs = db.query(SMSSendLog).filter(
                SMSSendLog.user_id == user_id,
                SMSSendLog.status == "sent",
                SMSSendLog.sent_at >= today_start
            ).all()

            month_logs = db.query(SMSSendLog).filter(
                SMSSendLog.user_id == user_id,
                SMSSendLog.status == "sent",
                SMSSendLog.sent_at >= month_start
            ).all()

            return {
                "phone_number": settings.phone_number[:3] + "***" + settings.phone_number[-3:] if settings.phone_number else None,
                "phone_verified": settings.phone_verified,
                "is_enabled": settings.is_enabled,
                "total_sms_sent": settings.total_sms_sent,
                "total_cost": round(settings.total_sms_cost, 2),
                "today_sent": len(today_logs),
                "month_sent": len(month_logs),
                "daily_limit": settings.max_sms_per_day,
                "quiet_hours": f"{settings.quiet_hours_start} - {settings.quiet_hours_end}"
            }

        finally:
            db.close()

    def disable_sms(self, user_id: int) -> bool:
        """Disable SMS notifications for user"""
        db = SessionLocal()
        try:
            settings = db.query(SMSNotificationSetting).filter_by(user_id=user_id).first()
            if settings:
                settings.is_enabled = False
                settings.phone_verified = False
                settings.phone_number = None
                db.commit()
                return True
            return False
        except Exception as e:
            db.rollback()
            print(f"[ERROR] Failed to disable SMS: {e}")
            return False
        finally:
            db.close()
