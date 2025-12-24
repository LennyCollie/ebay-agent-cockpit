from functools import wraps
from flask import request, jsonify, g
from services.api_key import APIKeyManager, RateLimiter
import time


def require_api_key(permissions=None):
    """Decorator to require API key authentication"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            auth_header = request.headers.get("Authorization", "")
            
            if not auth_header.startswith("Bearer "):
                return jsonify({
                    "success": False,
                    "error": "Missing or invalid Authorization header"
                }), 401
            
            token = auth_header[7:]
            parts = token.split(":")
            
            if len(parts) != 2:
                return jsonify({
                    "success": False,
                    "error": "Invalid API key format. Use: key:secret"
                }), 401
            
            key, secret = parts
            
            api_key = APIKeyManager.verify_api_key(key, secret)
            
            if not api_key:
                return jsonify({
                    "success": False,
                    "error": "Invalid API key or secret"
                }), 401
            
            if permissions:
                api_permissions = set(api_key.permissions.split(","))
                if not any(p in api_permissions for p in permissions):
                    return jsonify({
                        "success": False,
                        "error": f"Insufficient permissions. Required: {permissions}"
                    }), 403
            
            g.api_key = api_key
            g.user_id = api_key.user_id
            
            start_time = time.time()
            try:
                response = f(*args, **kwargs)
            finally:
                response_time = time.time() - start_time
                status_code = 200
                if isinstance(response, tuple):
                    status_code = response[1] if len(response) > 1 else 200
                
                APIKeyManager.log_api_request(
                    api_key_id=api_key.id,
                    method=request.method,
                    endpoint=request.path,
                    status_code=status_code,
                    response_time=response_time,
                    ip_address=request.remote_addr,
                    user_agent=request.headers.get("User-Agent")
                )
            
            return response
        
        return decorated_function
    return decorator


def api_auth_optional():
    """Decorator to optionally use API key authentication"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            auth_header = request.headers.get("Authorization", "")
            
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
                parts = token.split(":")
                
                if len(parts) == 2:
                    key, secret = parts
                    api_key = APIKeyManager.verify_api_key(key, secret)
                    
                    if api_key:
                        g.api_key = api_key
                        g.user_id = api_key.user_id
            
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator
