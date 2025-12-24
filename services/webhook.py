import json
import hmac
import hashlib
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import threading
from models import WebhookEndpoint, WebhookEvent, WebhookLog, SessionLocal


class WebhookManager:
    SUPPORTED_EVENTS = {
        "webhook.test": "Test-Webhook",
        "alert.triggered": "Alert wurde ausgelöst",
        "alert.matched": "Treffer für Alert gefunden",
        "search.completed": "Suche abgeschlossen",
        "affiliate.converted": "Affiliate Konvertierung",
        "coupon.applied": "Coupon angewendet",
        "payment.success": "Zahlung erfolgreich",
        "payment.failed": "Zahlung fehlgeschlagen",
        "subscription.created": "Abo erstellt",
        "subscription.canceled": "Abo gekündigt",
        "achievement.earned": "Achievement verdient",
        "leaderboard.updated": "Leaderboard aktualisiert",
    }

    @staticmethod
    def create_webhook(user_id: int, name: str, url: str, events: List[str]) -> Optional[WebhookEndpoint]:
        db = SessionLocal()
        try:
            secret = WebhookManager.generate_secret()
            
            endpoint = WebhookEndpoint(
                user_id=user_id,
                name=name,
                url=url,
                secret=secret,
                events=",".join(events),
                is_active=True
            )
            db.add(endpoint)
            db.commit()
            return endpoint
        except Exception as e:
            db.rollback()
            print(f"[ERROR] Failed to create webhook: {e}")
            return None
        finally:
            db.close()

    @staticmethod
    def get_user_webhooks(user_id: int) -> List[WebhookEndpoint]:
        db = SessionLocal()
        try:
            return db.query(WebhookEndpoint).filter_by(user_id=user_id).all()
        finally:
            db.close()

    @staticmethod
    def get_webhook(endpoint_id: int, user_id: int) -> Optional[WebhookEndpoint]:
        db = SessionLocal()
        try:
            return db.query(WebhookEndpoint).filter_by(
                id=endpoint_id,
                user_id=user_id
            ).first()
        finally:
            db.close()

    @staticmethod
    def update_webhook(endpoint_id: int, user_id: int, **kwargs) -> Optional[WebhookEndpoint]:
        db = SessionLocal()
        try:
            endpoint = db.query(WebhookEndpoint).filter_by(
                id=endpoint_id,
                user_id=user_id
            ).first()
            
            if not endpoint:
                return None
            
            allowed_fields = ["name", "url", "events", "is_active", "retry_count", "timeout"]
            for key, value in kwargs.items():
                if key in allowed_fields:
                    if key == "events" and isinstance(value, list):
                        setattr(endpoint, key, ",".join(value))
                    else:
                        setattr(endpoint, key, value)
            
            db.commit()
            return endpoint
        except Exception as e:
            db.rollback()
            print(f"[ERROR] Failed to update webhook: {e}")
            return None
        finally:
            db.close()

    @staticmethod
    def delete_webhook(endpoint_id: int, user_id: int) -> bool:
        db = SessionLocal()
        try:
            endpoint = db.query(WebhookEndpoint).filter_by(
                id=endpoint_id,
                user_id=user_id
            ).first()
            
            if not endpoint:
                return False
            
            db.delete(endpoint)
            db.commit()
            return True
        except Exception as e:
            db.rollback()
            print(f"[ERROR] Failed to delete webhook: {e}")
            return False
        finally:
            db.close()

    @staticmethod
    def generate_secret() -> str:
        import secrets
        return secrets.token_urlsafe(32)

    @staticmethod
    def verify_signature(secret: str, payload: str, signature: str) -> bool:
        expected_signature = hmac.new(
            secret.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected_signature, signature)

    @staticmethod
    def create_signature(secret: str, payload: str) -> str:
        return hmac.new(
            secret.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()


class EventDispatcher:
    @staticmethod
    def dispatch_event(user_id: int, event_type: str, event_data: Dict, source: str = "system"):
        if event_type not in WebhookManager.SUPPORTED_EVENTS:
            print(f"[WARNING] Unknown event type: {event_type}")
            return
        
        db = SessionLocal()
        try:
            event = WebhookEvent(
                user_id=user_id,
                event_type=event_type,
                event_data=json.dumps(event_data),
                source=source
            )
            db.add(event)
            db.commit()
            
            threading.Thread(
                target=EventDispatcher._deliver_event,
                args=(event.id,),
                daemon=True
            ).start()
            
        except Exception as e:
            db.rollback()
            print(f"[ERROR] Failed to dispatch event: {e}")
        finally:
            db.close()

    @staticmethod
    def _format_payload(endpoint: WebhookEndpoint, event: WebhookEvent, payload: dict) -> dict:
        if "discord" in endpoint.url.lower() or "discord" in endpoint.name.lower():
            return EventDispatcher._format_discord(event, payload)
        elif "slack" in endpoint.url.lower() or "hooks.slack" in endpoint.url:
            return EventDispatcher._format_slack(event, payload)
        else:
            return payload

    @staticmethod
    def _format_discord(event: WebhookEvent, payload: dict) -> dict:
        event_type = event.event_type
        data = payload["data"]
        
        colors = {
            "alert.triggered": 3447003,
            "alert.matched": 3066993,
            "search.completed": 9807270,
            "affiliate.converted": 15418782,
            "coupon.applied": 2067276,
            "payment.success": 3066993,
            "payment.failed": 15158332,
            "subscription.created": 9807270,
            "subscription.canceled": 15158332,
            "achievement.earned": 15418782,
            "leaderboard.updated": 2067276,
        }
        
        color = colors.get(event_type, 9807270)
        
        titles = {
            "alert.triggered": "🔔 Alert ausgelöst",
            "alert.matched": "✅ Treffer gefunden",
            "search.completed": "🔍 Suche fertig",
            "affiliate.converted": "💰 Affiliate Konvertierung",
            "coupon.applied": "🎟️ Coupon genutzt",
            "payment.success": "💳 Zahlung erfolgreich",
            "payment.failed": "❌ Zahlung fehlgeschlagen",
            "subscription.created": "📅 Abo erstellt",
            "subscription.canceled": "🚫 Abo gekündigt",
            "achievement.earned": "🏆 Achievement verdient",
            "leaderboard.updated": "🥇 Leaderboard aktualisiert",
        }
        
        return {
            "embeds": [{
                "title": titles.get(event_type, event_type),
                "description": json.dumps(data, indent=2, ensure_ascii=False)[:2000],
                "color": color,
                "timestamp": payload["timestamp"],
                "footer": {
                    "text": "eBay Agent Cockpit"
                }
            }]
        }

    @staticmethod
    def _format_slack(event: WebhookEvent, payload: dict) -> dict:
        event_type = event.event_type
        data = payload["data"]
        
        colors = {
            "alert.triggered": "#3b82f6",
            "alert.matched": "#10b981",
            "search.completed": "#f59e0b",
            "affiliate.converted": "#ec4899",
            "coupon.applied": "#8b5cf6",
            "payment.success": "#10b981",
            "payment.failed": "#ef4444",
            "subscription.created": "#f59e0b",
            "subscription.canceled": "#ef4444",
            "achievement.earned": "#ec4899",
            "leaderboard.updated": "#8b5cf6",
        }
        
        color = colors.get(event_type, "#667eea")
        
        titles = {
            "alert.triggered": "🔔 Alert ausgelöst",
            "alert.matched": "✅ Treffer gefunden",
            "search.completed": "🔍 Suche fertig",
            "affiliate.converted": "💰 Affiliate Konvertierung",
            "coupon.applied": "🎟️ Coupon genutzt",
            "payment.success": "💳 Zahlung erfolgreich",
            "payment.failed": "❌ Zahlung fehlgeschlagen",
            "subscription.created": "📅 Abo erstellt",
            "subscription.canceled": "🚫 Abo gekündigt",
            "achievement.earned": "🏆 Achievement verdient",
            "leaderboard.updated": "🥇 Leaderboard aktualisiert",
        }
        
        return {
            "attachments": [{
                "color": color,
                "title": titles.get(event_type, event_type),
                "text": json.dumps(data, indent=2, ensure_ascii=False)[:2000],
                "ts": int(payload.get("timestamp", datetime.utcnow()).timestamp() if isinstance(payload.get("timestamp"), str) else datetime.utcnow().timestamp())
            }]
        }

    @staticmethod
    def _deliver_event(event_id: int):
        db = SessionLocal()
        try:
            event = db.query(WebhookEvent).filter_by(id=event_id).first()
            if not event:
                return
            
            endpoints = db.query(WebhookEndpoint).filter_by(
                user_id=event.user_id,
                is_active=True
            ).all()
            
            for endpoint in endpoints:
                events_list = endpoint.events.split(",")
                if event.event_type not in events_list:
                    continue
                
                EventDispatcher._send_to_endpoint(endpoint, event, db)
                
        finally:
            db.close()

    @staticmethod
    def _send_to_endpoint(endpoint: WebhookEndpoint, event: WebhookEvent, db):
        try:
            payload = {
                "id": event.id,
                "type": event.event_type,
                "timestamp": event.created_at.isoformat(),
                "data": json.loads(event.event_data)
            }
            
            formatted_payload = EventDispatcher._format_payload(endpoint, event, payload)
            payload_json = json.dumps(formatted_payload)
            signature = WebhookManager.create_signature(endpoint.secret, payload_json)
            
            headers = {
                "Content-Type": "application/json",
                "X-Webhook-Signature": signature,
                "X-Webhook-Event": event.event_type,
                "User-Agent": "EbayAgentCockpit/1.0"
            }
            
            response = requests.post(
                endpoint.url,
                json=formatted_payload,
                headers=headers,
                timeout=endpoint.timeout
            )
            
            log = WebhookLog(
                endpoint_id=endpoint.id,
                event_id=event.id,
                status="success" if response.status_code < 400 else "failed",
                response_code=response.status_code,
                response_body=response.text[:500] if response.text else None,
                completed_at=datetime.utcnow()
            )
            
            db.add(log)
            endpoint.last_triggered = datetime.utcnow()
            db.commit()
            
        except requests.Timeout:
            EventDispatcher._handle_retry(endpoint, event, "Timeout", db)
        except requests.RequestException as e:
            EventDispatcher._handle_retry(endpoint, event, str(e), db)
        except Exception as e:
            print(f"[ERROR] Failed to send webhook: {e}")

    @staticmethod
    def _handle_retry(endpoint: WebhookEndpoint, event: WebhookEvent, error: str, db):
        log = db.query(WebhookLog).filter_by(
            endpoint_id=endpoint.id,
            event_id=event.id
        ).order_by(WebhookLog.created_at.desc()).first()
        
        if not log:
            log = WebhookLog(
                endpoint_id=endpoint.id,
                event_id=event.id,
                status="pending",
                error_message=error,
                attempt_number=1
            )
            db.add(log)
        else:
            log.attempt_number += 1
        
        if log.attempt_number <= endpoint.retry_count:
            delay_seconds = (2 ** (log.attempt_number - 1)) * 5
            log.next_retry_at = datetime.utcnow() + timedelta(seconds=delay_seconds)
            log.status = "pending_retry"
        else:
            log.status = "failed"
            log.completed_at = datetime.utcnow()
        
        log.error_message = error
        db.commit()

    @staticmethod
    def get_event_logs(endpoint_id: int, limit: int = 50) -> List[WebhookLog]:
        db = SessionLocal()
        try:
            return db.query(WebhookLog).filter_by(
                endpoint_id=endpoint_id
            ).order_by(WebhookLog.created_at.desc()).limit(limit).all()
        finally:
            db.close()

    @staticmethod
    def retry_failed_events():
        db = SessionLocal()
        try:
            pending_logs = db.query(WebhookLog).filter(
                WebhookLog.status.in_(["pending_retry"]),
                WebhookLog.next_retry_at <= datetime.utcnow()
            ).all()
            
            for log in pending_logs:
                endpoint = log.endpoint
                event = log.event
                
                if endpoint.is_active:
                    EventDispatcher._send_to_endpoint(endpoint, event, db)
                    
        except Exception as e:
            print(f"[ERROR] Retry failed events: {e}")
        finally:
            db.close()
