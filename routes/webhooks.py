from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from services.webhook import WebhookManager, EventDispatcher
from models import SessionLocal, WebhookLog
import json

webhooks_bp = Blueprint("webhooks", __name__, url_prefix="/api/webhooks")


@webhooks_bp.route("/", methods=["GET"])
@login_required
def list_webhooks():
    endpoints = WebhookManager.get_user_webhooks(current_user.id)
    
    data = []
    for endpoint in endpoints:
        events_list = endpoint.events.split(",")
        data.append({
            "id": endpoint.id,
            "name": endpoint.name,
            "url": endpoint.url,
            "events": events_list,
            "is_active": endpoint.is_active,
            "is_verified": endpoint.is_verified,
            "retry_count": endpoint.retry_count,
            "timeout": endpoint.timeout,
            "last_triggered": endpoint.last_triggered.isoformat() if endpoint.last_triggered else None,
            "created_at": endpoint.created_at.isoformat()
        })
    
    return jsonify({
        "success": True,
        "data": data,
        "supported_events": WebhookManager.SUPPORTED_EVENTS
    })


@webhooks_bp.route("/", methods=["POST"])
@login_required
def create_webhook():
    data = request.get_json()
    
    if not data or not all(key in data for key in ["name", "url", "events"]):
        return jsonify({"success": False, "error": "Missing required fields"}), 400
    
    if not isinstance(data.get("events"), list) or len(data["events"]) == 0:
        return jsonify({"success": False, "error": "Events must be non-empty list"}), 400
    
    for event in data["events"]:
        if event not in WebhookManager.SUPPORTED_EVENTS:
            return jsonify({
                "success": False,
                "error": f"Unknown event: {event}"
            }), 400
    
    endpoint = WebhookManager.create_webhook(
        user_id=current_user.id,
        name=data["name"],
        url=data["url"],
        events=data["events"]
    )
    
    if not endpoint:
        return jsonify({"success": False, "error": "Failed to create webhook"}), 500
    
    return jsonify({
        "success": True,
        "data": {
            "id": endpoint.id,
            "secret": endpoint.secret,
            "name": endpoint.name,
            "url": endpoint.url
        }
    }), 201


@webhooks_bp.route("/<int:endpoint_id>", methods=["GET"])
@login_required
def get_webhook(endpoint_id):
    endpoint = WebhookManager.get_webhook(endpoint_id, current_user.id)
    
    if not endpoint:
        return jsonify({"success": False, "error": "Webhook not found"}), 404
    
    events_list = endpoint.events.split(",")
    
    return jsonify({
        "success": True,
        "data": {
            "id": endpoint.id,
            "name": endpoint.name,
            "url": endpoint.url,
            "events": events_list,
            "is_active": endpoint.is_active,
            "is_verified": endpoint.is_verified,
            "retry_count": endpoint.retry_count,
            "timeout": endpoint.timeout,
            "last_triggered": endpoint.last_triggered.isoformat() if endpoint.last_triggered else None,
            "created_at": endpoint.created_at.isoformat()
        }
    })


@webhooks_bp.route("/<int:endpoint_id>", methods=["PUT"])
@login_required
def update_webhook(endpoint_id):
    endpoint = WebhookManager.get_webhook(endpoint_id, current_user.id)
    
    if not endpoint:
        return jsonify({"success": False, "error": "Webhook not found"}), 404
    
    data = request.get_json()
    
    if "events" in data:
        if not isinstance(data["events"], list):
            return jsonify({"success": False, "error": "Events must be a list"}), 400
        for event in data["events"]:
            if event not in WebhookManager.SUPPORTED_EVENTS:
                return jsonify({"success": False, "error": f"Unknown event: {event}"}), 400
    
    updated = WebhookManager.update_webhook(endpoint_id, current_user.id, **data)
    
    if not updated:
        return jsonify({"success": False, "error": "Failed to update webhook"}), 500
    
    events_list = updated.events.split(",")
    
    return jsonify({
        "success": True,
        "data": {
            "id": updated.id,
            "name": updated.name,
            "url": updated.url,
            "events": events_list,
            "is_active": updated.is_active,
            "retry_count": updated.retry_count,
            "timeout": updated.timeout
        }
    })


@webhooks_bp.route("/<int:endpoint_id>", methods=["DELETE"])
@login_required
def delete_webhook(endpoint_id):
    success = WebhookManager.delete_webhook(endpoint_id, current_user.id)
    
    if not success:
        return jsonify({"success": False, "error": "Webhook not found"}), 404
    
    return jsonify({"success": True, "message": "Webhook deleted"})


@webhooks_bp.route("/<int:endpoint_id>/logs", methods=["GET"])
@login_required
def get_webhook_logs(endpoint_id):
    endpoint = WebhookManager.get_webhook(endpoint_id, current_user.id)
    
    if not endpoint:
        return jsonify({"success": False, "error": "Webhook not found"}), 404
    
    limit = request.args.get("limit", 50, type=int)
    logs = EventDispatcher.get_event_logs(endpoint_id, limit)
    
    data = []
    for log in logs:
        data.append({
            "id": log.id,
            "event_type": log.event.event_type,
            "status": log.status,
            "response_code": log.response_code,
            "attempt_number": log.attempt_number,
            "error_message": log.error_message,
            "created_at": log.created_at.isoformat(),
            "completed_at": log.completed_at.isoformat() if log.completed_at else None
        })
    
    return jsonify({
        "success": True,
        "data": data
    })


@webhooks_bp.route("/<int:endpoint_id>/test", methods=["POST"])
@login_required
def test_webhook(endpoint_id):
    endpoint = WebhookManager.get_webhook(endpoint_id, current_user.id)
    
    if not endpoint:
        return jsonify({"success": False, "error": "Webhook not found"}), 404
    
    test_event_data = {
        "test": True,
        "message": "This is a test webhook delivery",
        "timestamp": __import__("datetime").datetime.utcnow().isoformat()
    }
    
    db = SessionLocal()
    try:
        from models import WebhookEvent
        
        event = WebhookEvent(
            user_id=current_user.id,
            event_type="webhook.test",
            event_data=json.dumps(test_event_data),
            source="test"
        )
        db.add(event)
        db.flush()
        
        EventDispatcher._send_to_endpoint(endpoint, event, db)
        
        return jsonify({
            "success": True,
            "message": "Test webhook sent"
        })
    except Exception as e:
        db.rollback()
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
    finally:
        db.close()
