from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from services.api_key import APIKeyManager
from models import APIKey, APIKeyLog, User, SessionLocal
import re

api_keys_bp = Blueprint("api_keys", __name__, url_prefix="/api/api-keys")


def admin_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, "is_admin", False):
            return jsonify({"success": False, "error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return wrapper


@api_keys_bp.route("/", methods=["GET"])
@login_required
def list_api_keys():
    """List all API keys for current user"""
    api_keys = APIKeyManager.get_user_api_keys(current_user.id)
    
    data = []
    for key in api_keys:
        permissions = key.permissions.split(",") if key.permissions else []
        data.append({
            "id": key.id,
            "name": key.name,
            "key": key.key[:8] + "..." + key.key[-4:],
            "permissions": permissions,
            "is_active": key.is_active,
            "rate_limit": key.rate_limit,
            "last_used": key.last_used.isoformat() if key.last_used else None,
            "last_ip": key.last_ip,
            "created_at": key.created_at.isoformat(),
            "expires_at": key.expires_at.isoformat() if key.expires_at else None
        })
    
    return jsonify({
        "success": True,
        "data": data
    })


@api_keys_bp.route("/", methods=["POST"])
@login_required
def create_api_key():
    """Create new API key"""
    data = request.get_json()
    
    if not data or not data.get("name"):
        return jsonify({"success": False, "error": "Name required"}), 400
    
    permissions = data.get("permissions", ["read", "write"])
    rate_limit = data.get("rate_limit", 1000)
    expires_days = data.get("expires_days")
    
    result = APIKeyManager.create_api_key(
        user_id=current_user.id,
        name=data["name"],
        permissions=permissions,
        rate_limit=rate_limit,
        expires_days=expires_days
    )
    
    if not result:
        return jsonify({"success": False, "error": "Failed to create API key"}), 500
    
    api_key, secret = result
    
    return jsonify({
        "success": True,
        "data": {
            "id": api_key.id,
            "name": api_key.name,
            "key": api_key.key,
            "secret": secret,
            "permissions": permissions,
            "rate_limit": rate_limit
        },
        "warning": "Store the secret securely. It won't be shown again!"
    }), 201


@api_keys_bp.route("/<int:key_id>", methods=["GET"])
@login_required
def get_api_key(key_id):
    """Get API key details"""
    api_key = APIKeyManager.get_api_key_by_id(key_id, current_user.id)
    
    if not api_key:
        return jsonify({"success": False, "error": "API key not found"}), 404
    
    permissions = api_key.permissions.split(",") if api_key.permissions else []
    
    return jsonify({
        "success": True,
        "data": {
            "id": api_key.id,
            "name": api_key.name,
            "key": api_key.key[:8] + "..." + api_key.key[-4:],
            "permissions": permissions,
            "is_active": api_key.is_active,
            "rate_limit": api_key.rate_limit,
            "last_used": api_key.last_used.isoformat() if api_key.last_used else None,
            "last_ip": api_key.last_ip,
            "created_at": api_key.created_at.isoformat(),
            "expires_at": api_key.expires_at.isoformat() if api_key.expires_at else None
        }
    })


@api_keys_bp.route("/<int:key_id>", methods=["PUT"])
@login_required
def update_api_key(key_id):
    """Update API key"""
    api_key = APIKeyManager.get_api_key_by_id(key_id, current_user.id)
    
    if not api_key:
        return jsonify({"success": False, "error": "API key not found"}), 404
    
    data = request.get_json()
    
    updated = APIKeyManager.update_api_key(key_id, current_user.id, **data)
    
    if not updated:
        return jsonify({"success": False, "error": "Failed to update API key"}), 500
    
    permissions = updated.permissions.split(",") if updated.permissions else []
    
    return jsonify({
        "success": True,
        "data": {
            "id": updated.id,
            "name": updated.name,
            "permissions": permissions,
            "is_active": updated.is_active,
            "rate_limit": updated.rate_limit
        }
    })


@api_keys_bp.route("/<int:key_id>", methods=["DELETE"])
@login_required
def delete_api_key(key_id):
    """Delete API key"""
    success = APIKeyManager.revoke_api_key(key_id, current_user.id)
    
    if not success:
        return jsonify({"success": False, "error": "API key not found"}), 404
    
    return jsonify({"success": True, "message": "API key deleted"})


@api_keys_bp.route("/<int:key_id>/logs", methods=["GET"])
@login_required
def get_api_key_logs(key_id):
    """Get API key usage logs"""
    api_key = APIKeyManager.get_api_key_by_id(key_id, current_user.id)
    
    if not api_key:
        return jsonify({"success": False, "error": "API key not found"}), 404
    
    limit = request.args.get("limit", 100, type=int)
    logs = APIKeyManager.get_api_key_logs(key_id, limit)
    
    data = []
    for log in logs:
        data.append({
            "id": log.id,
            "method": log.method,
            "endpoint": log.endpoint,
            "status_code": log.status_code,
            "response_time": log.response_time,
            "ip_address": log.ip_address,
            "timestamp": log.timestamp.isoformat()
        })
    
    return jsonify({
        "success": True,
        "data": data
    })


@api_keys_bp.route("/admin/stats", methods=["GET"])
@login_required
@admin_required
def admin_api_stats():
    """Get admin statistics for all API keys"""
    db = SessionLocal()
    try:
        from datetime import datetime, timedelta
        
        total_keys = db.query(APIKey).count()
        active_keys = db.query(APIKey).filter_by(is_active=True).count()
        
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_requests = db.query(APIKeyLog).filter(APIKeyLog.timestamp >= today).count()
        
        avg_response = db.query(APIKeyLog).filter(APIKeyLog.timestamp >= today).all()
        avg_response_time = sum(log.response_time for log in avg_response) / len(avg_response) if avg_response else 0
        
        all_keys = db.query(APIKey).all()
        keys_data = []
        for key in all_keys:
            user = db.query(User).filter_by(id=key.user_id).first()
            log_count = db.query(APIKeyLog).filter_by(api_key_id=key.id).count()
            keys_data.append({
                "user_email": user.email if user else "Unknown",
                "name": key.name,
                "is_active": key.is_active,
                "rate_limit": key.rate_limit,
                "created_at": key.created_at.isoformat(),
                "last_used": key.last_used.isoformat() if key.last_used else None,
                "request_count": log_count
            })
        
        return jsonify({
            "success": True,
            "stats": {
                "total_keys": total_keys,
                "active_keys": active_keys,
                "total_requests": today_requests,
                "avg_response_time": avg_response_time
            },
            "keys": keys_data
        })
    finally:
        db.close()
