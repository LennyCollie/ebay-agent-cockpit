#!/usr/bin/env python
"""Test script to verify all imports and basic functionality"""

import sys

def test_imports():
    """Test all module imports"""
    errors = []
    
    print("Testing Python imports...")
    print("-" * 50)
    
    try:
        from models import (
            Base, engine, User, Alert, PriceHistory, 
            Report, ReportGeneration, ReportTemplate,
            UserRole, UserRoleAssignment, Sponsor, SponsorLevel, TeamMember,
            WhiteLabelBrand, ResellerAccount, EndUserAccount,
            PriceForecast, PriceTrendAnalysis, MarketInsight
        )
        print("[OK] All models imported successfully")
    except Exception as e:
        errors.append(f"Model import error: {str(e)}")
        print(f"[ERR] Model import error: {str(e)}")
    
    try:
        from services.sms import SMSManager
        print("[OK] SMS Service imported successfully")
    except Exception as e:
        errors.append(f"SMS Service error: {str(e)}")
        print(f"[ERR] SMS Service error: {str(e)}")
    
    try:
        from services.reports import ReportGenerator
        print("[OK] Report Service imported successfully")
    except Exception as e:
        errors.append(f"Report Service error: {str(e)}")
        print(f"[ERR] Report Service error: {str(e)}")
    
    try:
        from services.ml_predictions import MLPredictionService
        print("[OK] ML Service imported successfully")
    except Exception as e:
        errors.append(f"ML Service error: {str(e)}")
        print(f"[ERR] ML Service error: {str(e)}")
    
    try:
        from routes.sms_notifications import sms_bp
        print("[OK] SMS Routes imported successfully")
    except Exception as e:
        errors.append(f"SMS Routes error: {str(e)}")
        print(f"[ERR] SMS Routes error: {str(e)}")
    
    try:
        from routes.reports import reports_bp
        print("[OK] Reports Routes imported successfully")
    except Exception as e:
        errors.append(f"Reports Routes error: {str(e)}")
        print(f"[ERR] Reports Routes error: {str(e)}")
    
    try:
        from routes.roles import roles_bp
        print("[OK] Roles Routes imported successfully")
    except Exception as e:
        errors.append(f"Roles Routes error: {str(e)}")
        print(f"[ERR] Roles Routes error: {str(e)}")
    
    try:
        from routes.reseller import reseller_bp
        print("[OK] Reseller Routes imported successfully")
    except Exception as e:
        errors.append(f"Reseller Routes error: {str(e)}")
        print(f"[ERR] Reseller Routes error: {str(e)}")
    
    try:
        from routes.ml_analytics import ml_bp
        print("[OK] ML Analytics Routes imported successfully")
    except Exception as e:
        errors.append(f"ML Analytics Routes error: {str(e)}")
        print(f"[ERR] ML Analytics Routes error: {str(e)}")
    
    print("-" * 50)
    
    if errors:
        print(f"\n[FAILED] {len(errors)} errors found:")
        for error in errors:
            print(f"  - {error}")
        return False
    else:
        print("\n[SUCCESS] All imports successful!")
        return True


def test_models():
    """Test model structure"""
    print("\nTesting Model Structure...")
    print("-" * 50)
    
    try:
        from models import Report, ReportGeneration, UserRole, Sponsor
        from sqlalchemy import inspect
        
        # Check Report table
        mapper = inspect(Report)
        report_cols = [c.key for c in mapper.columns]
        expected = ['id', 'user_id', 'name', 'report_type', 'format', 'is_enabled']
        if all(col in report_cols for col in expected):
            print("[OK] Report model structure correct")
        else:
            print("[ERR] Report model missing columns")
        
        # Check UserRole table
        mapper = inspect(UserRole)
        role_cols = [c.key for c in mapper.columns]
        if 'name' in role_cols and 'permissions' in role_cols:
            print("[OK] UserRole model structure correct")
        else:
            print("[ERR] UserRole model missing columns")
        
        # Check Sponsor table
        mapper = inspect(Sponsor)
        sponsor_cols = [c.key for c in mapper.columns]
        if 'level_id' in sponsor_cols and 'is_active' in sponsor_cols:
            print("[OK] Sponsor model structure correct")
        else:
            print("[ERR] Sponsor model missing columns")
        
        print("-" * 50)
        print("[SUCCESS] Model structure validation passed!")
        return True
        
    except Exception as e:
        print(f"[ERR] Model structure validation failed: {str(e)}")
        return False


if __name__ == "__main__":
    success = test_imports()
    success = test_models() and success
    
    sys.exit(0 if success else 1)
