from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from services.sms import SMSManager
from models import SessionLocal

sms_bp = Blueprint("sms", __name__, url_prefix="/api/sms")
sms_manager = SMSManager()


@sms_bp.route("/settings", methods=["GET"])
@login_required
def get_sms_settings():
    """Get current SMS settings"""
    settings = sms_manager.get_sms_settings(current_user.id)
    
    if not settings:
        return jsonify({
            "success": True,
            "data": {
                "phone_number": None,
                "phone_verified": False,
                "is_enabled": False,
                "alert_types": "price_drop,new_item",
                "max_sms_per_day": 5,
                "quiet_hours_start": "22:00",
                "quiet_hours_end": "08:00",
                "total_sms_sent": 0,
                "total_sms_cost": 0.0
            }
        })

    return jsonify({
        "success": True,
        "data": {
            "phone_number": settings.phone_number[:3] + "***" + settings.phone_number[-3:] if settings.phone_number else None,
            "phone_verified": settings.phone_verified,
            "is_enabled": settings.is_enabled,
            "alert_types": settings.alert_types.split(",") if settings.alert_types else [],
            "max_sms_per_day": settings.max_sms_per_day,
            "quiet_hours_start": settings.quiet_hours_start,
            "quiet_hours_end": settings.quiet_hours_end,
            "total_sms_sent": settings.total_sms_sent,
            "total_sms_cost": round(settings.total_sms_cost, 2)
        }
    })


@sms_bp.route("/settings/initiate-verification", methods=["POST"])
@login_required
def initiate_phone_verification():
    """Start phone number verification"""
    data = request.get_json()
    
    if not data or not data.get("phone_number"):
        return jsonify({"success": False, "error": "Phone number required"}), 400

    phone_number = data.get("phone_number").strip()
    country_code = data.get("country_code", "DE")

    success, message = sms_manager.initiate_phone_verification(
        current_user.id, 
        phone_number
    )

    status_code = 200 if success else 400
    return jsonify({
        "success": success,
        "message": message
    }), status_code


@sms_bp.route("/settings/verify", methods=["POST"])
@login_required
def verify_phone():
    """Verify phone number with code"""
    data = request.get_json()
    
    if not data or not data.get("code"):
        return jsonify({"success": False, "error": "Verification code required"}), 400

    code = data.get("code").strip()

    success, message = sms_manager.verify_phone_number(current_user.id, code)
    
    status_code = 200 if success else 400
    return jsonify({
        "success": success,
        "message": message
    }), status_code


@sms_bp.route("/settings", methods=["PUT"])
@login_required
def update_sms_settings():
    """Update SMS notification settings"""
    data = request.get_json()
    
    if not data:
        return jsonify({"success": False, "error": "No data provided"}), 400

    update_data = {}
    
    if "is_enabled" in data:
        update_data["is_enabled"] = bool(data.get("is_enabled"))
    
    if "alert_types" in data:
        alert_types = data.get("alert_types")
        if isinstance(alert_types, list):
            update_data["alert_types"] = alert_types
        elif isinstance(alert_types, str):
            update_data["alert_types"] = alert_types.split(",")
    
    if "max_sms_per_day" in data:
        max_sms = int(data.get("max_sms_per_day", 5))
        if 1 <= max_sms <= 50:
            update_data["max_sms_per_day"] = max_sms
    
    if "quiet_hours_start" in data:
        update_data["quiet_hours_start"] = data.get("quiet_hours_start")
    
    if "quiet_hours_end" in data:
        update_data["quiet_hours_end"] = data.get("quiet_hours_end")

    settings = sms_manager.update_sms_settings(current_user.id, **update_data)
    
    if not settings:
        return jsonify({"success": False, "error": "Failed to update settings"}), 500

    return jsonify({
        "success": True,
        "message": "Settings updated",
        "data": {
            "is_enabled": settings.is_enabled,
            "alert_types": settings.alert_types.split(",") if settings.alert_types else [],
            "max_sms_per_day": settings.max_sms_per_day,
            "quiet_hours_start": settings.quiet_hours_start,
            "quiet_hours_end": settings.quiet_hours_end
        }
    })


@sms_bp.route("/test", methods=["POST"])
@login_required
def send_test_sms():
    """Send test SMS to verify setup"""
    message = f"Test SMS von eBay-Agent Cockpit"
    
    success, message_response = sms_manager.send_alert_sms(
        current_user.id,
        alert_type="test",
        message=message,
        test=True
    )
    
    status_code = 200 if success else 400
    return jsonify({
        "success": success,
        "message": message_response
    }), status_code


@sms_bp.route("/logs", methods=["GET"])
@login_required
def get_sms_logs():
    """Get SMS send logs"""
    limit = request.args.get("limit", 50, type=int)
    
    logs = sms_manager.get_sms_logs(current_user.id, limit=limit)
    
    data = []
    for log in logs:
        data.append({
            "id": log.id,
            "phone_number": log.phone_number[-3:] if log.phone_number else "***",
            "message": log.message_content[:100] + "..." if len(log.message_content) > 100 else log.message_content,
            "alert_type": log.alert_type,
            "status": log.status,
            "cost": f"€{log.cost_cents/100:.2f}" if log.cost_cents else "N/A",
            "sent_at": log.sent_at.isoformat() if log.sent_at else None,
            "created_at": log.created_at.isoformat()
        })
    
    return jsonify({
        "success": True,
        "data": data,
        "count": len(data)
    })


@sms_bp.route("/statistics", methods=["GET"])
@login_required
def get_sms_statistics():
    """Get SMS usage statistics"""
    stats = sms_manager.get_sms_statistics(current_user.id)
    
    return jsonify({
        "success": True,
        "data": stats
    })


@sms_bp.route("/disable", methods=["POST"])
@login_required
def disable_sms():
    """Disable SMS notifications"""
    success = sms_manager.disable_sms(current_user.id)
    
    if not success:
        return jsonify({"success": False, "error": "Failed to disable SMS"}), 500
    
    return jsonify({
        "success": True,
        "message": "SMS notifications disabled"
    })


@sms_bp.route("/alert-types", methods=["GET"])
@login_required
def get_alert_types():
    """Get available SMS alert types"""
    return jsonify({
        "success": True,
        "data": sms_manager.ALERT_TYPES
    })
