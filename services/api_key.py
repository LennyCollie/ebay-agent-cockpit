import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from models import APIKey, APIKeyLog, SessionLocal
import hmac


class APIKeyManager:
    KEY_LENGTH = 32
    SECRET_LENGTH = 64

    @staticmethod
    def generate_key_pair() -> tuple:
        key = secrets.token_urlsafe(APIKeyManager.KEY_LENGTH)
        secret = secrets.token_urlsafe(APIKeyManager.SECRET_LENGTH)
        return key, secret

    @staticmethod
    def hash_secret(secret: str) -> str:
        return hashlib.sha256(secret.encode()).hexdigest()

    @staticmethod
    def create_api_key(
        user_id: int,
        name: str,
        permissions: List[str] = None,
        rate_limit: int = 1000,
        expires_days: Optional[int] = None
    ) -> Optional[tuple]:
        db = SessionLocal()
        try:
            key, secret = APIKeyManager.generate_key_pair()
            secret_hash = APIKeyManager.hash_secret(secret)
            
            if permissions is None:
                permissions = ["read", "write"]
            
            api_key = APIKey(
                user_id=user_id,
                name=name,
                key=key,
                secret=secret_hash,
                permissions=",".join(permissions),
                rate_limit=rate_limit,
                expires_at=datetime.utcnow() + timedelta(days=expires_days) if expires_days else None
            )
            db.add(api_key)
            db.commit()
            
            return api_key, secret
        except Exception as e:
            db.rollback()
            print(f"[ERROR] Failed to create API key: {e}")
            return None
        finally:
            db.close()

    @staticmethod
    def get_api_key(key: str) -> Optional[APIKey]:
        db = SessionLocal()
        try:
            return db.query(APIKey).filter_by(key=key, is_active=True).first()
        finally:
            db.close()

    @staticmethod
    def verify_api_key(key: str, secret: str) -> Optional[APIKey]:
        api_key = APIKeyManager.get_api_key(key)
        
        if not api_key:
            return None
        
        secret_hash = APIKeyManager.hash_secret(secret)
        
        if not hmac.compare_digest(secret_hash, api_key.secret):
            return None
        
        if api_key.expires_at and datetime.utcnow() > api_key.expires_at:
            return None
        
        return api_key

    @staticmethod
    def get_user_api_keys(user_id: int) -> List[APIKey]:
        db = SessionLocal()
        try:
            return db.query(APIKey).filter_by(user_id=user_id).order_by(APIKey.created_at.desc()).all()
        finally:
            db.close()

    @staticmethod
    def get_api_key_by_id(api_key_id: int, user_id: int) -> Optional[APIKey]:
        db = SessionLocal()
        try:
            return db.query(APIKey).filter_by(id=api_key_id, user_id=user_id).first()
        finally:
            db.close()

    @staticmethod
    def update_api_key(api_key_id: int, user_id: int, **kwargs) -> Optional[APIKey]:
        db = SessionLocal()
        try:
            api_key = db.query(APIKey).filter_by(id=api_key_id, user_id=user_id).first()
            
            if not api_key:
                return None
            
            allowed_fields = ["name", "is_active", "permissions", "rate_limit"]
            for key, value in kwargs.items():
                if key in allowed_fields:
                    if key == "permissions" and isinstance(value, list):
                        setattr(api_key, key, ",".join(value))
                    else:
                        setattr(api_key, key, value)
            
            db.commit()
            return api_key
        except Exception as e:
            db.rollback()
            print(f"[ERROR] Failed to update API key: {e}")
            return None
        finally:
            db.close()

    @staticmethod
    def revoke_api_key(api_key_id: int, user_id: int) -> bool:
        db = SessionLocal()
        try:
            api_key = db.query(APIKey).filter_by(id=api_key_id, user_id=user_id).first()
            
            if not api_key:
                return False
            
            db.delete(api_key)
            db.commit()
            return True
        except Exception as e:
            db.rollback()
            print(f"[ERROR] Failed to revoke API key: {e}")
            return False
        finally:
            db.close()

    @staticmethod
    def log_api_request(
        api_key_id: int,
        method: str,
        endpoint: str,
        status_code: int,
        response_time: float,
        ip_address: str = None,
        user_agent: str = None
    ) -> bool:
        db = SessionLocal()
        try:
            log = APIKeyLog(
                api_key_id=api_key_id,
                method=method,
                endpoint=endpoint,
                status_code=status_code,
                response_time=response_time,
                ip_address=ip_address,
                user_agent=user_agent
            )
            db.add(log)
            
            api_key = db.query(APIKey).filter_by(id=api_key_id).first()
            if api_key:
                api_key.last_used = datetime.utcnow()
                api_key.last_ip = ip_address
            
            db.commit()
            return True
        except Exception as e:
            db.rollback()
            print(f"[ERROR] Failed to log API request: {e}")
            return False
        finally:
            db.close()

    @staticmethod
    def get_api_key_logs(api_key_id: int, limit: int = 100) -> List[APIKeyLog]:
        db = SessionLocal()
        try:
            return db.query(APIKeyLog).filter_by(
                api_key_id=api_key_id
            ).order_by(APIKeyLog.timestamp.desc()).limit(limit).all()
        finally:
            db.close()


class RateLimiter:
    def __init__(self, redis_client=None):
        self.redis = redis_client

    def check_rate_limit(self, api_key: APIKey) -> bool:
        if not self.redis:
            return True
        
        key = f"rate_limit:{api_key.id}:{datetime.utcnow().timestamp() // api_key.rate_limit_window}"
        
        count = self.redis.incr(key)
        
        if count == 1:
            self.redis.expire(key, api_key.rate_limit_window)
        
        return count <= api_key.rate_limit

    def get_remaining_requests(self, api_key: APIKey) -> int:
        if not self.redis:
            return api_key.rate_limit
        
        key = f"rate_limit:{api_key.id}:{datetime.utcnow().timestamp() // api_key.rate_limit_window}"
        count = int(self.redis.get(key) or 0)
        
        return max(0, api_key.rate_limit - count)
