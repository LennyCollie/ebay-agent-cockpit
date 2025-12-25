from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from models import SessionLocal, UserRole, UserRoleAssignment, Sponsor, SponsorLevel, TeamMember
import json
from datetime import datetime, timedelta
from functools import wraps

roles_bp = Blueprint("roles", __name__, url_prefix="/api/roles")


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        db = SessionLocal()
        try:
            admin_role = db.query(UserRole).filter_by(name="admin").first()
            if not admin_role:
                return jsonify({"success": False, "error": "Admin access required"}), 403
            
            has_admin = db.query(UserRoleAssignment).filter_by(
                user_id=current_user.id,
                role_id=admin_role.id,
                is_active=True
            ).first()
            
            if not has_admin:
                return jsonify({"success": False, "error": "Admin access required"}), 403
        finally:
            db.close()
        
        return f(*args, **kwargs)
    return decorated_function


@roles_bp.route("/list", methods=["GET"])
@login_required
@admin_required
def list_roles():
    db = SessionLocal()
    try:
        roles = db.query(UserRole).all()
        return jsonify({
            "success": True,
            "data": [
                {
                    "id": r.id,
                    "name": r.name,
                    "description": r.description,
                    "permissions": json.loads(r.permissions) if r.permissions else [],
                    "is_system_role": r.is_system_role
                }
                for r in roles
            ]
        })
    finally:
        db.close()


@roles_bp.route("", methods=["POST"])
@login_required
@admin_required
def create_role():
    db = SessionLocal()
    try:
        data = request.get_json()
        
        if not data or not data.get("name"):
            return jsonify({"success": False, "error": "Name required"}), 400
        
        existing = db.query(UserRole).filter_by(name=data["name"]).first()
        if existing:
            return jsonify({"success": False, "error": "Role already exists"}), 400
        
        role = UserRole(
            name=data["name"],
            description=data.get("description"),
            permissions=json.dumps(data.get("permissions", [])),
            is_system_role=False
        )
        
        db.add(role)
        db.commit()
        
        return jsonify({
            "success": True,
            "data": {"id": role.id, "name": role.name}
        }), 201
    finally:
        db.close()


@roles_bp.route("/<int:role_id>/assign", methods=["POST"])
@login_required
@admin_required
def assign_role(role_id):
    db = SessionLocal()
    try:
        data = request.get_json()
        
        if not data or not data.get("user_id"):
            return jsonify({"success": False, "error": "User ID required"}), 400
        
        role = db.query(UserRole).filter_by(id=role_id).first()
        if not role:
            return jsonify({"success": False, "error": "Role not found"}), 404
        
        existing = db.query(UserRoleAssignment).filter_by(
            user_id=data["user_id"],
            role_id=role_id
        ).first()
        
        if existing:
            existing.is_active = True
            existing.updated_at = datetime.utcnow()
        else:
            assignment = UserRoleAssignment(
                user_id=data["user_id"],
                role_id=role_id,
                assigned_by=current_user.id,
                expires_at=data.get("expires_at")
            )
            db.add(assignment)
        
        db.commit()
        return jsonify({"success": True, "message": "Role assigned"})
    finally:
        db.close()


@roles_bp.route("/<int:role_id>/revoke", methods=["POST"])
@login_required
@admin_required
def revoke_role(role_id):
    db = SessionLocal()
    try:
        data = request.get_json()
        user_id = data.get("user_id") if data else None
        
        if not user_id:
            return jsonify({"success": False, "error": "User ID required"}), 400
        
        assignment = db.query(UserRoleAssignment).filter_by(
            user_id=user_id,
            role_id=role_id
        ).first()
        
        if assignment:
            assignment.is_active = False
            db.commit()
        
        return jsonify({"success": True, "message": "Role revoked"})
    finally:
        db.close()


@roles_bp.route("/sponsors/levels", methods=["GET"])
@login_required
def list_sponsor_levels():
    db = SessionLocal()
    try:
        levels = db.query(SponsorLevel).filter_by(is_active=True).all()
        return jsonify({
            "success": True,
            "data": [
                {
                    "id": l.id,
                    "name": l.name,
                    "description": l.description,
                    "monthly_price": l.monthly_price,
                    "benefits": json.loads(l.benefits) if l.benefits else [],
                    "max_team_members": l.max_team_members,
                    "badge_color": l.badge_color,
                    "badge_icon": l.badge_icon
                }
                for l in levels
            ]
        })
    finally:
        db.close()


@roles_bp.route("/sponsors/profile", methods=["GET"])
@login_required
def get_sponsor_profile():
    db = SessionLocal()
    try:
        sponsor = db.query(Sponsor).filter_by(user_id=current_user.id).first()
        
        if not sponsor:
            return jsonify({
                "success": True,
                "data": None
            })
        
        return jsonify({
            "success": True,
            "data": {
                "id": sponsor.id,
                "level": sponsor.level.name if sponsor.level else None,
                "monthly_donation": sponsor.monthly_donation,
                "total_donated": sponsor.total_donated,
                "started_at": sponsor.started_at.isoformat(),
                "is_active": sponsor.is_active,
                "custom_badge_name": sponsor.custom_badge_name,
                "custom_badge_color": sponsor.custom_badge_color
            }
        })
    finally:
        db.close()


@roles_bp.route("/sponsors/levels/<int:level_id>/become", methods=["POST"])
@login_required
def become_sponsor(level_id):
    db = SessionLocal()
    try:
        level = db.query(SponsorLevel).filter_by(id=level_id).first()
        if not level:
            return jsonify({"success": False, "error": "Level not found"}), 404
        
        existing = db.query(Sponsor).filter_by(user_id=current_user.id).first()
        
        if existing:
            existing.level_id = level_id
            existing.is_active = True
            existing.updated_at = datetime.utcnow()
        else:
            sponsor = Sponsor(
                user_id=current_user.id,
                level_id=level_id,
                monthly_donation=level.monthly_price
            )
            db.add(sponsor)
        
        db.commit()
        
        return jsonify({
            "success": True,
            "message": f"Welcome to {level.name} sponsor tier!"
        })
    finally:
        db.close()


@roles_bp.route("/sponsors/cancel", methods=["POST"])
@login_required
def cancel_sponsorship():
    db = SessionLocal()
    try:
        sponsor = db.query(Sponsor).filter_by(user_id=current_user.id).first()
        
        if sponsor:
            sponsor.is_active = False
            sponsor.canceled_at = datetime.utcnow()
            db.commit()
        
        return jsonify({"success": True, "message": "Sponsorship canceled"})
    finally:
        db.close()


@roles_bp.route("/team/members", methods=["GET"])
@login_required
def list_team_members():
    db = SessionLocal()
    try:
        members = db.query(TeamMember).filter_by(owner_id=current_user.id, is_active=True).all()
        
        return jsonify({
            "success": True,
            "data": [
                {
                    "id": m.id,
                    "member_id": m.member_id,
                    "member_email": m.member.email if m.member else None,
                    "role": m.role,
                    "invited_at": m.invited_at.isoformat(),
                    "joined_at": m.joined_at.isoformat() if m.joined_at else None,
                    "can_manage_alerts": m.can_manage_alerts,
                    "can_manage_team": m.can_manage_team
                }
                for m in members
            ]
        })
    finally:
        db.close()


@roles_bp.route("/team/members", methods=["POST"])
@login_required
def invite_team_member():
    db = SessionLocal()
    try:
        data = request.get_json()
        
        if not data or not data.get("member_id"):
            return jsonify({"success": False, "error": "Member ID required"}), 400
        
        member = TeamMember(
            owner_id=current_user.id,
            member_id=data["member_id"],
            role=data.get("role", "member"),
            can_manage_alerts=data.get("can_manage_alerts", True),
            can_manage_team=data.get("can_manage_team", False)
        )
        
        db.add(member)
        db.commit()
        
        return jsonify({
            "success": True,
            "message": "Team member invited"
        }), 201
    finally:
        db.close()


@roles_bp.route("/team/members/<int:member_id>", methods=["PUT"])
@login_required
def update_team_member(member_id):
    db = SessionLocal()
    try:
        member = db.query(TeamMember).filter_by(
            id=member_id,
            owner_id=current_user.id
        ).first()
        
        if not member:
            return jsonify({"success": False, "error": "Team member not found"}), 404
        
        data = request.get_json()
        
        if "role" in data:
            member.role = data["role"]
        if "can_manage_alerts" in data:
            member.can_manage_alerts = data["can_manage_alerts"]
        if "can_manage_team" in data:
            member.can_manage_team = data["can_manage_team"]
        
        db.commit()
        return jsonify({"success": True, "message": "Team member updated"})
    finally:
        db.close()


@roles_bp.route("/team/members/<int:member_id>", methods=["DELETE"])
@login_required
def remove_team_member(member_id):
    db = SessionLocal()
    try:
        member = db.query(TeamMember).filter_by(
            id=member_id,
            owner_id=current_user.id
        ).first()
        
        if member:
            member.is_active = False
            db.commit()
        
        return jsonify({"success": True, "message": "Team member removed"})
    finally:
        db.close()


@roles_bp.route("/my-roles", methods=["GET"])
@login_required
def get_my_roles():
    db = SessionLocal()
    try:
        assignments = db.query(UserRoleAssignment).filter_by(
            user_id=current_user.id,
            is_active=True
        ).all()
        
        return jsonify({
            "success": True,
            "data": [
                {
                    "role_id": a.role_id,
                    "role_name": a.role.name if a.role else None,
                    "permissions": json.loads(a.role.permissions) if a.role and a.role.permissions else [],
                    "assigned_at": a.assigned_at.isoformat(),
                    "expires_at": a.expires_at.isoformat() if a.expires_at else None
                }
                for a in assignments
            ]
        })
    finally:
        db.close()
