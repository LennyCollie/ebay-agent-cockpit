# config.py
import os

# --- ENV direkt lesen (außerhalb der Klasse!) ---
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PRICE_BASIC = os.getenv("STRIPE_PRICE_BASIC", "")
STRIPE_PRICE_PRO = os.getenv("STRIPE_PRICE_PRO", "")
STRIPE_PRICE_TEAM = os.getenv("STRIPE_PRICE_TEAM", "")
PLAUSIBLE_DOMAIN = os.getenv("PLAUSIBLE_DOMAIN", "")

# --- Abgeleitete Helfer / Mappings ---
STRIPE_PRICE = {
    "basic": STRIPE_PRICE_BASIC,
    "pro": STRIPE_PRICE_PRO,
    "team": STRIPE_PRICE_TEAM,
}
PRICE_TO_PLAN = {v: k for k, v in STRIPE_PRICE.items() if v}
PLAN_LIMITS = {"basic": 5, "pro": 20, "team": 50}


# --- App-Config (reicht die oben definierten Werte durch) ---
class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-me")

    STRIPE_SECRET_KEY = STRIPE_SECRET_KEY
    STRIPE_PRICE_BASIC = STRIPE_PRICE_BASIC
    STRIPE_PRICE_PRO = STRIPE_PRICE_PRO
    STRIPE_PRICE_TEAM = STRIPE_PRICE_TEAM

    STRIPE_PRICE = STRIPE_PRICE
    PRICE_TO_PLAN = PRICE_TO_PLAN
    PLAN_LIMITS = PLAN_LIMITS

    PLAUSIBLE_DOMAIN = PLAUSIBLE_DOMAIN
