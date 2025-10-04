# config.py
import os

# --- ENV direkt lesen (außerhalb der Klasse!) ---
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PRICE_BASIC = os.getenv("STRIPE_PRICE_BASIC", "")
STRIPE_PRICE_PRO = os.getenv("STRIPE_PRICE_PRO", "")
STRIPE_PRICE_TEAM = os.getenv("STRIPE_PRICE_TEAM", "")

# --- Abgeleitete Helfer / Mappings ---
STRIPE_PRICE = {
    "basic": STRIPE_PRICE_BASIC,
    "pro": STRIPE_PRICE_PRO,
    "team": STRIPE_PRICE_TEAM,
}
PRICE_TO_PLAN = {v: k for k, v in STRIPE_PRICE.items() if v}
PLAN_LIMITS = {"basic": 5, "pro": 20, "team": 50}  # gern anpassen


# --- App-Config (reicht die oben definierten Werte nur durch) ---
class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-me")

    STRIPE_SECRET_KEY = STRIPE_SECRET_KEY
    STRIPE_PRICE_BASIC = STRIPE_PRICE_BASIC
    STRIPE_PRICE_PRO = STRIPE_PRICE_PRO
    STRIPE_PRICE_TEAM = STRIPE_PRICE_TEAM
