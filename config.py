# config.py
import os

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PRICE_STARTER = os.getenv("STRIPE_PRICE_STARTER", "")
STRIPE_PRICE_BASIC = os.getenv("STRIPE_PRICE_BASIC", "")
STRIPE_PRICE_PRO = os.getenv("STRIPE_PRICE_PRO", "")
STRIPE_PRICE_ENTERPRISE = os.getenv("STRIPE_PRICE_ENTERPRISE", "")
STRIPE_PRICE_CUSTOM = os.getenv("STRIPE_PRICE_CUSTOM", "")
PLAUSIBLE_DOMAIN = os.getenv("PLAUSIBLE_DOMAIN", "")

STRIPE_PRICE = {
    "starter": STRIPE_PRICE_STARTER,
    "basic": STRIPE_PRICE_BASIC,
    "pro": STRIPE_PRICE_PRO,
    "enterprise": STRIPE_PRICE_ENTERPRISE,
    "custom": STRIPE_PRICE_CUSTOM,
}
PRICE_TO_PLAN = {v: k for k, v in STRIPE_PRICE.items() if v}

PLAN_FEATURES = {
    "free": {
        "price": 0.0,
        "currency": "EUR",
        "max_alerts": 5,
        "max_products": 10,
        "sms_alerts": False,
        "pdf_reports": False,
        "api_access": False,
        "priority_support": False,
        "white_label": False,
        "description": "Kostenlos - Perfekt zum Starten"
    },
    "starter": {
        "price": 4.99,
        "currency": "EUR",
        "max_alerts": 25,
        "max_products": 50,
        "sms_alerts": True,
        "pdf_reports": False,
        "api_access": False,
        "priority_support": False,
        "white_label": False,
        "description": "€4.99/Monat - Für Hobby-Nutzer"
    },
    "basic": {
        "price": 9.99,
        "currency": "EUR",
        "max_alerts": 100,
        "max_products": 200,
        "sms_alerts": True,
        "pdf_reports": True,
        "api_access": False,
        "priority_support": False,
        "white_label": False,
        "description": "€9.99/Monat - Für regelmäßige Nutzer"
    },
    "pro": {
        "price": 19.99,
        "currency": "EUR",
        "max_alerts": 500,
        "max_products": 1000,
        "sms_alerts": True,
        "pdf_reports": True,
        "api_access": True,
        "priority_support": True,
        "white_label": False,
        "description": "€19.99/Monat - Für Power-User"
    },
    "enterprise": {
        "price": 49.99,
        "currency": "EUR",
        "max_alerts": 5000,
        "max_products": 10000,
        "sms_alerts": True,
        "pdf_reports": True,
        "api_access": True,
        "priority_support": True,
        "white_label": False,
        "description": "€49.99/Monat - Für Profis"
    },
    "custom": {
        "price": 99.0,
        "currency": "EUR",
        "max_alerts": -1,
        "max_products": -1,
        "sms_alerts": True,
        "pdf_reports": True,
        "api_access": True,
        "priority_support": True,
        "white_label": True,
        "description": "Ab €99/Monat - White-Label & Custom"
    }
}

PLAN_LIMITS = {
    "free": 5,
    "starter": 25,
    "basic": 100,
    "pro": 500,
    "enterprise": 5000,
    "custom": -1
}


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-me")

    STRIPE_SECRET_KEY = STRIPE_SECRET_KEY
    STRIPE_PRICE_STARTER = STRIPE_PRICE_STARTER
    STRIPE_PRICE_BASIC = STRIPE_PRICE_BASIC
    STRIPE_PRICE_PRO = STRIPE_PRICE_PRO
    STRIPE_PRICE_ENTERPRISE = STRIPE_PRICE_ENTERPRISE
    STRIPE_PRICE_CUSTOM = STRIPE_PRICE_CUSTOM

    STRIPE_PRICE = STRIPE_PRICE
    PRICE_TO_PLAN = PRICE_TO_PLAN
    PLAN_LIMITS = PLAN_LIMITS
    PLAN_FEATURES = PLAN_FEATURES

    PLAUSIBLE_DOMAIN = PLAUSIBLE_DOMAIN
