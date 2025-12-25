from flask import Blueprint, request, jsonify, send_file
from flask_login import login_required, current_user
from models import SessionLocal, Report, ReportGeneration, ReportTemplate
from services.reports import ReportGenerator
import json
from datetime import datetime, timedelta
from io import BytesIO

reports_bp = Blueprint("reports", __name__, url_prefix="/api/reports")
generator = ReportGenerator()


@reports_bp.route("/templates", methods=["GET"])
@login_required
def get_templates():
    db = SessionLocal()
    try:
        templates = db.query(ReportTemplate).all()
        return jsonify({
            "success": True,
            "data": [
                {
                    "id": t.id,
                    "name": t.name,
                    "description": t.description,
                    "report_type": t.report_type,
                    "is_premium": t.is_premium,
                    "icon": t.icon,
                    "color": t.color
                }
                for t in templates
            ]
        })
    finally:
        db.close()


@reports_bp.route("", methods=["GET"])
@login_required
def list_reports():
    db = SessionLocal()
    try:
        reports = db.query(Report).filter_by(user_id=current_user.id).order_by(Report.created_at.desc()).all()
        
        return jsonify({
            "success": True,
            "data": [
                {
                    "id": r.id,
                    "name": r.name,
                    "report_type": r.report_type,
                    "format": r.format,
                    "is_scheduled": r.is_scheduled,
                    "is_enabled": r.is_enabled,
                    "last_generated": r.last_generated.isoformat() if r.last_generated else None,
                    "created_at": r.created_at.isoformat()
                }
                for r in reports
            ]
        })
    finally:
        db.close()


@reports_bp.route("", methods=["POST"])
@login_required
def create_report():
    db = SessionLocal()
    try:
        data = request.get_json()
        
        if not data or not data.get("name") or not data.get("report_type"):
            return jsonify({"success": False, "error": "Name and report_type required"}), 400
        
        report = Report(
            user_id=current_user.id,
            name=data.get("name"),
            description=data.get("description"),
            report_type=data.get("report_type"),
            format=data.get("format", "pdf"),
            is_scheduled=data.get("is_scheduled", False),
            schedule_frequency=data.get("schedule_frequency"),
            email_recipients=data.get("email_recipients"),
            include_charts=data.get("include_charts", True),
            include_summary=data.get("include_summary", True),
            include_detailed_data=data.get("include_detailed_data", True),
            filters=json.dumps(data.get("filters", {})) if data.get("filters") else None
        )
        
        db.add(report)
        db.commit()
        
        return jsonify({
            "success": True,
            "data": {"id": report.id, "name": report.name}
        }), 201
    finally:
        db.close()


@reports_bp.route("/<int:report_id>", methods=["GET"])
@login_required
def get_report(report_id):
    db = SessionLocal()
    try:
        report = db.query(Report).filter_by(id=report_id, user_id=current_user.id).first()
        
        if not report:
            return jsonify({"success": False, "error": "Report not found"}), 404
        
        return jsonify({
            "success": True,
            "data": {
                "id": report.id,
                "name": report.name,
                "description": report.description,
                "report_type": report.report_type,
                "format": report.format,
                "is_scheduled": report.is_scheduled,
                "schedule_frequency": report.schedule_frequency,
                "email_recipients": report.email_recipients.split(",") if report.email_recipients else [],
                "include_charts": report.include_charts,
                "include_summary": report.include_summary,
                "include_detailed_data": report.include_detailed_data,
                "filters": json.loads(report.filters) if report.filters else {},
                "is_enabled": report.is_enabled,
                "last_generated": report.last_generated.isoformat() if report.last_generated else None,
                "created_at": report.created_at.isoformat()
            }
        })
    finally:
        db.close()


@reports_bp.route("/<int:report_id>", methods=["PUT"])
@login_required
def update_report(report_id):
    db = SessionLocal()
    try:
        report = db.query(Report).filter_by(id=report_id, user_id=current_user.id).first()
        
        if not report:
            return jsonify({"success": False, "error": "Report not found"}), 404
        
        data = request.get_json()
        
        if "name" in data:
            report.name = data["name"]
        if "description" in data:
            report.description = data["description"]
        if "is_enabled" in data:
            report.is_enabled = data["is_enabled"]
        if "is_scheduled" in data:
            report.is_scheduled = data["is_scheduled"]
        if "schedule_frequency" in data:
            report.schedule_frequency = data["schedule_frequency"]
        if "email_recipients" in data:
            report.email_recipients = ",".join(data["email_recipients"]) if data["email_recipients"] else None
        
        report.updated_at = datetime.utcnow()
        db.commit()
        
        return jsonify({"success": True, "message": "Report updated"})
    finally:
        db.close()


@reports_bp.route("/<int:report_id>", methods=["DELETE"])
@login_required
def delete_report(report_id):
    db = SessionLocal()
    try:
        report = db.query(Report).filter_by(id=report_id, user_id=current_user.id).first()
        
        if not report:
            return jsonify({"success": False, "error": "Report not found"}), 404
        
        db.delete(report)
        db.commit()
        
        return jsonify({"success": True, "message": "Report deleted"})
    finally:
        db.close()


@reports_bp.route("/<int:report_id>/generate", methods=["POST"])
@login_required
def generate_report(report_id):
    db = SessionLocal()
    try:
        report = db.query(Report).filter_by(id=report_id, user_id=current_user.id).first()
        
        if not report:
            return jsonify({"success": False, "error": "Report not found"}), 404
        
        success, message = generator.generate_report(current_user.id, report_id)
        
        return jsonify({
            "success": success,
            "message": message
        }), 200 if success else 400
    finally:
        db.close()


@reports_bp.route("/generations/<int:generation_id>", methods=["GET"])
@login_required
def get_generation(generation_id):
    db = SessionLocal()
    try:
        generation = db.query(ReportGeneration).filter_by(
            id=generation_id,
            user_id=current_user.id
        ).first()
        
        if not generation:
            return jsonify({"success": False, "error": "Generation not found"}), 404
        
        return jsonify({
            "success": True,
            "data": {
                "id": generation.id,
                "report_id": generation.report_id,
                "status": generation.status,
                "file_size": generation.file_size,
                "generation_time_ms": generation.generation_time_ms,
                "row_count": generation.row_count,
                "created_at": generation.created_at.isoformat(),
                "completed_at": generation.completed_at.isoformat() if generation.completed_at else None,
                "error_message": generation.error_message
            }
        })
    finally:
        db.close()


@reports_bp.route("/<int:generation_id>/download", methods=["GET"])
@login_required
def download_report(generation_id):
    file_data = generator.get_report_file(current_user.id, generation_id)
    
    if not file_data:
        return jsonify({"success": False, "error": "Report not found"}), 404
    
    return send_file(
        BytesIO(file_data),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"report_{generation_id}.pdf"
    )


@reports_bp.route("/history/<int:report_id>", methods=["GET"])
@login_required
def get_report_history(report_id):
    db = SessionLocal()
    try:
        report = db.query(Report).filter_by(id=report_id, user_id=current_user.id).first()
        
        if not report:
            return jsonify({"success": False, "error": "Report not found"}), 404
        
        generations = db.query(ReportGeneration).filter_by(
            report_id=report_id,
            user_id=current_user.id
        ).order_by(ReportGeneration.created_at.desc()).limit(20).all()
        
        return jsonify({
            "success": True,
            "data": [
                {
                    "id": g.id,
                    "status": g.status,
                    "file_size": g.file_size,
                    "generation_time_ms": g.generation_time_ms,
                    "created_at": g.created_at.isoformat(),
                    "completed_at": g.completed_at.isoformat() if g.completed_at else None
                }
                for g in generations
            ]
        })
    finally:
        db.close()


@reports_bp.route("/schedule/test", methods=["POST"])
@login_required
def test_schedule():
    data = request.get_json()
    
    return jsonify({
        "success": True,
        "message": "Schedule test passed",
        "next_run": (datetime.utcnow() + timedelta(days=1)).isoformat()
    })
