from models import (
    User, AffiliateAccount, Coupon, CouponUsage, AffiliateConversion,
    AnalyticsSnapshot, AnalyticsEvent
)

print("[OK] All models imported successfully")
print(f"[OK] User: {User.__tablename__}")
print(f"[OK] AffiliateAccount: {AffiliateAccount.__tablename__}")
print(f"[OK] Coupon: {Coupon.__tablename__}")
print(f"[OK] AnalyticsSnapshot: {AnalyticsSnapshot.__tablename__}")
print(f"[OK] AnalyticsEvent: {AnalyticsEvent.__tablename__}")
