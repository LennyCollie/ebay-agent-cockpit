# config.py
import os


class Config:
    # 1) Direkt aus ENV
    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    STRIPE_PRICE_BASIC = os.getenv("STRIPE_PRICE_BASIC", "")
    STRIPE_PRICE_PRO = os.getenv("STRIPE_PRICE_PRO", "")
    STRIPE_PRICE_TEAM = os.getenv("STRIPE_PRICE_TEAM", "")

    # 2) Abgeleitete Helfer (eine Quelle der Wahrheit)
    STRIPE_PRICE = {
        "basic": STRIPE_PRICE_BASIC,
        "pro": STRIPE_PRICE_PRO,
        "team": STRIPE_PRICE_TEAM,
    }
    PRICE_TO_PLAN = {v: k for k, v in STRIPE_PRICE.items() if v}
    PLAN_LIMITS = {"basic": 5, "pro": 20, "team": 50}  # frei anpassen
