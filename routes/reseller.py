from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from models import SessionLocal, ResellerAccount, WhiteLabelBrand, EndUserAccount, ResellerCommission
import json
import secrets
from datetime import datetime

reseller_bp = Blueprint("reseller", __name__, url_prefix="/api/reseller")


@reseller_bp.route("/account", methods=["GET"])
@login_required
def get_reseller_account():
    db = SessionLocal()
    try:
        account = db.query(ResellerAccount).filter_by(reseller_id=current_user.id).first()
        
        if not account:
            return jsonify({
                "success": True,
                "data": None
            })
        
        return jsonify({
            "success": True,
            "data": {
                "id": account.id,
                "company_name": account.company_name,
                "company_address": account.company_address,
                "company_tax_id": account.company_tax_id,
                "reseller_discount_percentage": account.reseller_discount_percentage,
                "max_end_users": account.max_end_users,
                "current_end_users": account.current_end_users,
                "commission_percentage": account.commission_percentage,
                "total_revenue": account.total_revenue,
                "total_commission": account.total_commission,
                "is_approved": account.is_approved,
                "is_active": account.is_active,
                "created_at": account.created_at.isoformat()
            }
        })
    finally:
        db.close()


@reseller_bp.route("/account", methods=["POST"])
@login_required
def create_reseller_account():
    db = SessionLocal()
    try:
        existing = db.query(ResellerAccount).filter_by(reseller_id=current_user.id).first()
        if existing:
            return jsonify({"success": False, "error": "Reseller account already exists"}), 400
        
        data = request.get_json()
        
        if not data or not data.get("company_name"):
            return jsonify({"success": False, "error": "Company name required"}), 400
        
        api_key = f"rsl_{secrets.token_hex(32)}"
        
        account = ResellerAccount(
            reseller_id=current_user.id,
            company_name=data["company_name"],
            company_address=data.get("company_address"),
            company_tax_id=data.get("company_tax_id"),
            api_key=api_key
        )
        
        db.add(account)
        db.commit()
        
        return jsonify({
            "success": True,
            "data": {
                "id": account.id,
                "company_name": account.company_name,
                "api_key": api_key
            }
        }), 201
    finally:
        db.close()


@reseller_bp.route("/brand", methods=["GET"])
@login_required
def get_white_label_brand():
    db = SessionLocal()
    try:
        brand = db.query(WhiteLabelBrand).filter_by(reseller_id=current_user.id).first()
        
        if not brand:
            return jsonify({
                "success": True,
                "data": None
            })
        
        return jsonify({
            "success": True,
            "data": {
                "id": brand.id,
                "brand_name": brand.brand_name,
                "brand_domain": brand.brand_domain,
                "brand_logo_url": brand.brand_logo_url,
                "brand_favicon_url": brand.brand_favicon_url,
                "primary_color": brand.primary_color,
                "secondary_color": brand.secondary_color,
                "accent_color": brand.accent_color,
                "support_email": brand.support_email,
                "support_phone": brand.support_phone,
                "support_url": brand.support_url,
                "footer_text": brand.footer_text,
                "is_active": brand.is_active
            }
        })
    finally:
        db.close()


@reseller_bp.route("/brand", methods=["POST", "PUT"])
@login_required
def configure_white_label_brand():
    db = SessionLocal()
    try:
        brand = db.query(WhiteLabelBrand).filter_by(reseller_id=current_user.id).first()
        
        data = request.get_json()
        
        if not data or not data.get("brand_name"):
            return jsonify({"success": False, "error": "Brand name required"}), 400
        
        if brand:
            brand.brand_name = data["brand_name"]
            brand.brand_domain = data.get("brand_domain")
            brand.brand_logo_url = data.get("brand_logo_url")
            brand.brand_favicon_url = data.get("brand_favicon_url")
            brand.primary_color = data.get("primary_color", brand.primary_color)
            brand.secondary_color = data.get("secondary_color", brand.secondary_color)
            brand.accent_color = data.get("accent_color", brand.accent_color)
            brand.support_email = data.get("support_email")
            brand.support_phone = data.get("support_phone")
            brand.support_url = data.get("support_url")
            brand.footer_text = data.get("footer_text")
            brand.updated_at = datetime.utcnow()
        else:
            brand = WhiteLabelBrand(
                reseller_id=current_user.id,
                brand_name=data["brand_name"],
                brand_domain=data.get("brand_domain"),
                brand_logo_url=data.get("brand_logo_url"),
                brand_favicon_url=data.get("brand_favicon_url"),
                primary_color=data.get("primary_color", "#3b82f6"),
                secondary_color=data.get("secondary_color", "#2563eb"),
                accent_color=data.get("accent_color", "#10b981"),
                support_email=data.get("support_email"),
                support_phone=data.get("support_phone"),
                support_url=data.get("support_url"),
                footer_text=data.get("footer_text")
            )
            db.add(brand)
        
        db.commit()
        return jsonify({"success": True, "message": "Brand configured"})
    finally:
        db.close()


@reseller_bp.route("/end-users", methods=["GET"])
@login_required
def list_end_users():
    db = SessionLocal()
    try:
        account = db.query(ResellerAccount).filter_by(reseller_id=current_user.id).first()
        if not account:
            return jsonify({"success": False, "error": "No reseller account"}), 404
        
        end_users = db.query(EndUserAccount).filter_by(reseller_id=account.id).all()
        
        return jsonify({
            "success": True,
            "data": [
                {
                    "id": eu.id,
                    "end_user_id": eu.end_user_id,
                    "custom_domain": eu.custom_domain,
                    "plan": eu.plan,
                    "monthly_fee": eu.monthly_fee,
                    "created_at": eu.created_at.isoformat()
                }
                for eu in end_users
            ]
        })
    finally:
        db.close()


@reseller_bp.route("/end-users", methods=["POST"])
@login_required
def add_end_user():
    db = SessionLocal()
    try:
        account = db.query(ResellerAccount).filter_by(reseller_id=current_user.id).first()
        if not account:
            return jsonify({"success": False, "error": "No reseller account"}), 404
        
        if account.current_end_users >= account.max_end_users:
            return jsonify({"success": False, "error": "Max end users reached"}), 400
        
        data = request.get_json()
        
        if not data or not data.get("end_user_id"):
            return jsonify({"success": False, "error": "End user ID required"}), 400
        
        end_user = EndUserAccount(
            reseller_id=account.id,
            end_user_id=data["end_user_id"],
            custom_domain=data.get("custom_domain"),
            plan=data.get("plan", "basic"),
            monthly_fee=data.get("monthly_fee")
        )
        
        account.current_end_users += 1
        db.add(end_user)
        db.commit()
        
        return jsonify({
            "success": True,
            "data": {"id": end_user.id}
        }), 201
    finally:
        db.close()


@reseller_bp.route("/commissions", methods=["GET"])
@login_required
def list_commissions():
    db = SessionLocal()
    try:
        account = db.query(ResellerAccount).filter_by(reseller_id=current_user.id).first()
        if not account:
            return jsonify({"success": False, "error": "No reseller account"}), 404
        
        commissions = db.query(ResellerCommission).filter_by(reseller_id=account.id).all()
        
        return jsonify({
            "success": True,
            "data": [
                {
                    "id": c.id,
                    "period": c.period,
                    "total_revenue": c.total_revenue,
                    "commission_amount": c.commission_amount,
                    "commission_percentage": c.commission_percentage,
                    "status": c.status,
                    "paid_at": c.paid_at.isoformat() if c.paid_at else None,
                    "created_at": c.created_at.isoformat()
                }
                for c in commissions
            ]
        })
    finally:
        db.close()


@reseller_bp.route("/stats", methods=["GET"])
@login_required
def get_reseller_stats():
    db = SessionLocal()
    try:
        account = db.query(ResellerAccount).filter_by(reseller_id=current_user.id).first()
        if not account:
            return jsonify({"success": False, "error": "No reseller account"}), 404
        
        total_revenue = db.query(ResellerCommission).filter_by(reseller_id=account.id).with_entities(
            db.func.sum(ResellerCommission.total_revenue)
        ).scalar() or 0.0
        
        total_commission = db.query(ResellerCommission).filter_by(reseller_id=account.id).with_entities(
            db.func.sum(ResellerCommission.commission_amount)
        ).scalar() or 0.0
        
        return jsonify({
            "success": True,
            "data": {
                "company_name": account.company_name,
                "end_users": account.current_end_users,
                "max_end_users": account.max_end_users,
                "total_revenue": total_revenue,
                "total_commission": total_commission,
                "commission_percentage": account.commission_percentage,
                "is_approved": account.is_approved
            }
        })
    finally:
        db.close()
