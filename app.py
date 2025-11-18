import base64
import csv
import hashlib
import io
import json
import math
import os
import sqlite3
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode

import requests
import stripe
from flask import (
    Blueprint,
    Flask,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix

# -------------------------------------------------------------------
# .env laden (lokal)
# -------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv(".env.local", override=True)
    load_dotenv()
except Exception:
    pass

# -------------------------------------------------------------------
# Flask App erstellen
# -------------------------------------------------------------------
app = Flask(__name__, template_folder="templates", static_folder="static")

# ProxyFix für Render (hinter Cloudflare/LoadBalancer)

from werkzeug.middleware.proxy_fix import ProxyFix
import os

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# -------------------------------------------------------------------
# SECRET_KEY Setup (KRITISCH für Sessions!)
# -------------------------------------------------------------------
SECRET_KEY = (
    os.getenv("SECRET_KEY")
    or os.getenv("FLASK_SECRET_KEY")
    or os.getenv("APP_SECRET")
    or "dev-key-CHANGE-IN-PRODUCTION-!!!"  # Fallback nur für lokale Entwicklung
)

app.secret_key = SECRET_KEY
app.config["SECRET_KEY"] = SECRET_KEY

# Debug-Ausgabe
secret_from_env = bool(os.getenv("SECRET_KEY"))
print("\n" + "="*50)
print("🔐 SECRET_KEY CONFIG:")
print(f"  Loaded from ENV: {secret_from_env}")
print(f"  Length: {len(SECRET_KEY)}")
print(f"  First 8 chars: {SECRET_KEY[:8]}...")
print("="*50)

# -------------------------------------------------------------------
# Session / Cookie Config
# -------------------------------------------------------------------
IS_RENDER = bool(os.getenv("RENDER"))
IS_PRODUCTION = os.getenv("ENV", "").lower() == "production" or IS_RENDER

app.config["SESSION_PERMANENT"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = 86400  # 24 Stunden

if IS_PRODUCTION:
    print("🔒 Production Mode: Secure Cookies ENABLED")
    app.config["SESSION_COOKIE_SECURE"] = True
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["PREFERRED_URL_SCHEME"] = "https"
else:
    print("🔓 Development Mode: Secure Cookies DISABLED")
    app.config["SESSION_COOKIE_SECURE"] = False
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# -------------------------------------------------------------------
# Config & Imports
# -------------------------------------------------------------------
from config import PLAUSIBLE_DOMAIN, PRICE_TO_PLAN, STRIPE_PRICE, Config

# NUR EINMAL Config laden!
app.config.from_object(Config)

# Stripe Config
app.config["STRIPE_PRICE"] = STRIPE_PRICE
app.config["PRICE_TO_PLAN"] = PRICE_TO_PLAN
app.config["PLAUSIBLE_DOMAIN"] = os.getenv("PLAUSIBLE_DOMAIN", "")

stripe.api_key = (Config.STRIPE_SECRET_KEY or os.getenv("STRIPE_SECRET_KEY", "")).strip()
STRIPE_OK = bool(stripe.api_key and len(stripe.api_key) > 10)

# -------------------------------------------------------------------
# Blueprints registrieren
# -------------------------------------------------------------------
from routes.inbound import bp as inbound_bp
from routes.telegram import bp as telegram_bp
from routes.vision_test import bp as vision_test_bp
from routes.watchlist import bp as watchlist_bp
from routes.search import bp_search as search_bp

app.register_blueprint(inbound_bp)
app.register_blueprint(telegram_bp)
app.register_blueprint(vision_test_bp)
app.register_blueprint(search_bp)
app.register_blueprint(watchlist_bp)

print("[Telegram] ✅ Routes registriert")

# -------------------------------------------------------------------
# Imports für Mail & Agent
# -------------------------------------------------------------------
from agent import get_mail_settings, send_mail

# -------------------------------------------------------------------
# Helper Functions
# -------------------------------------------------------------------
def as_bool(val: Optional[str]) -> bool:
    return str(val).strip().lower() in {"1", "true", "yes", "on"}

def getenv_any(*names: str, default: str = "") -> str:
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    return default

# -------------------------------------------------------------------
# Security Headers
# -------------------------------------------------------------------
@app.after_request
def add_security_headers(resp):
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    return resp

# -------------------------------------------------------------------
# Debug-Ausgabe ENV
# -------------------------------------------------------------------
print("\n" + "="*50)
print("🌍 ENVIRONMENT DEBUG:")
print(f"  LIVE_SEARCH = {os.getenv('LIVE_SEARCH', 'NOT SET')}")
print(f"  EBAY_CLIENT_ID = {os.getenv('EBAY_CLIENT_ID', 'MISSING')[:20]}...")
print(f"  EBAY_CLIENT_SECRET = {os.getenv('EBAY_CLIENT_SECRET', 'MISSING')[:20]}...")
print(f"  DATABASE_URL = {bool(os.getenv('DATABASE_URL'))}")
print(f"  RENDER = {IS_RENDER}")
print("="*50 + "\n")


# --- Security Headers (basic hardening) ---
@app.after_request
def add_security_headers(resp):
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # optional, aber sinnvoll:
    resp.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    return resp


# Limits / Defaults
FREE_SEARCH_LIMIT = int(os.getenv("FREE_SEARCH_LIMIT", "3"))
PREMIUM_SEARCH_LIMIT = int(os.getenv("PREMIUM_SEARCH_LIMIT", "10"))
PER_PAGE_DEFAULT = int(os.getenv("PER_PAGE_DEFAULT", "20"))
SEARCH_CACHE_TTL = int(os.getenv("SEARCH_CACHE_TTL", "60"))  # Sekunden


NOTIFY_COOLDOWN_MIN = int(os.getenv("NOTIFY_COOLDOWN_MINUTES", "120"))
NOTIFY_MAX_ITEMS_PER_MAIL = int(os.getenv("NOTIFY_MAX_ITEMS_PER_MAIL", "10"))

# NEU: Token für den privaten HTTP-Cron-Trigger
AGENT_TRIGGER_TOKEN = os.getenv("AGENT_TRIGGER_TOKEN", "")

# ALT (deprecated): Query-Token für /cron/run-alerts
CRON_TOKEN = os.getenv("CRON_TOKEN", "")

# DB (SQLite Pfad auch für Render kompatibel)
DB_URL = os.getenv("DB_PATH", "sqlite:///instance/db.sqlite3")


def _sqlite_file_from_url(url: str) -> Path:
    if url.startswith("sqlite:///"):
        rel = url.replace("sqlite:///", "", 1)
        return Path(rel)
    return Path(url)


DB_FILE = _sqlite_file_from_url(DB_URL)
if DB_URL.startswith("sqlite:"):
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)

# -------------------------------------------------------------------
# eBay – OAuth Client Credentials + Suche
# -------------------------------------------------------------------
EBAY_CLIENT_ID = getenv_any("EBAY_CLIENT_ID", "EBAY_APP_ID")
EBAY_CLIENT_SECRET = getenv_any("EBAY_CLIENT_SECRET", "EBAY_CERT_ID")
EBAY_SCOPES = os.getenv("EBAY_SCOPES", "https://api.ebay.com/oauth/api_scope")
EBAY_GLOBAL_ID = os.getenv("EBAY_GLOBAL_ID", "EBAY-DE")
LIVE_SEARCH = as_bool(os.getenv("LIVE_SEARCH", "0"))


def _marketplace_from_global(gid: str) -> str:
    gid = (gid or "").upper()
    if gid in {"EBAY-DE", "EBAY_DE"}:
        return "EBAY_DE"
    if gid in {"EBAY-US", "EBAY_US"}:
        return "EBAY_US"
    if gid in {"EBAY-GB", "EBAY_GB"}:
        return "EBAY_GB"
    if gid in {"EBAY-FR", "EBAY_FR"}:
        return "EBAY_FR"
    return "EBAY_DE"


def _currency_for_marketplace(mkt: str) -> str:
    mkt = (mkt or "").upper()
    if mkt == "EBAY_US":
        return "USD"
    if mkt == "EBAY_GB":
        return "GBP"
    if mkt == "EBAY_FR":
        return "EUR"
    return "EUR"


EBAY_MARKETPLACE_ID = _marketplace_from_global(EBAY_GLOBAL_ID)
EBAY_CURRENCY = _currency_for_marketplace(EBAY_MARKETPLACE_ID)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_DEFAULT_CHAT_ID = os.getenv("TELEGRAM_DEFAULT_CHAT_ID", "")
ALERT_CHECK_INTERVAL = int(os.getenv("ALERT_CHECK_INTERVAL", "3"))
NOTIFICATION_METHOD = os.getenv("NOTIFICATION_METHOD", "email")

def send_telegram_notification(chat_id: str, message: str) -> bool:
    """
    Sendet eine Telegram-Nachricht.
    Returns: True wenn erfolgreich
    """
    if not TELEGRAM_BOT_TOKEN:
        print("[Telegram] ❌ Bot Token fehlt!")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        print(f"[Telegram] ✅ Nachricht gesendet an {chat_id}")
        return True
    except Exception as e:
        print(f"[Telegram] ❌ Fehler: {e}")
        return False

# Optional: Affiliate-Parameter (an itemWebUrl anhängen)
AFFILIATE_PARAMS = os.getenv("AFFILIATE_PARAMS", "")  # "campid=XXXX;customid=YOURTAG"


def _append_affiliate(url: Optional[str]) -> Optional[str]:
    if not url or not AFFILIATE_PARAMS:
        return url
    parts = [p.strip() for p in AFFILIATE_PARAMS.split(";") if p.strip()]
    q = "&".join(parts)
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{q}" if q else url


# HTTP Session + Token Cache
_http = requests.Session()
_EBAY_TOKEN: Dict[str, object] = {"access_token": None, "expires_at": 0.0}


def ebay_get_token() -> Optional[str]:
    tok = _EBAY_TOKEN.get("access_token")
    if tok and time.time() < float(_EBAY_TOKEN.get("expires_at") or 0):
        return str(tok)

    if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
        print("[ebay_get_token] missing client id/secret")
        return None

    token_url = "https://api.ebay.com/identity/v1/oauth2/token"
    basic = base64.b64encode(f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}".encode()).decode()
    headers = {
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {"grant_type": "client_credentials", "scope": EBAY_SCOPES}
    try:
        r = _http.post(token_url, headers=headers, data=data, timeout=15)
        r.raise_for_status()
        j = r.json() or {}
        _EBAY_TOKEN["access_token"] = j.get("access_token")
        _EBAY_TOKEN["expires_at"] = time.time() + int(j.get("expires_in", 7200)) - 60
        return str(_EBAY_TOKEN["access_token"])
    except Exception as e:
        print(f"[ebay_get_token] {e}")
        return None


def _build_ebay_filters(filters: dict) -> Optional[str]:
    """
    Baut den 'filter' Query-Parameter für die eBay Browse API aus dem filters dict.
    Erwartete keys in filters: price_min, price_max, conditions (list), sort, free_shipping (str '1'),
    listing_type (e.g. 'buy_it_now'|'auction'|'all'), location_country (z.B. 'DE'), ...
    Gibt None zurück wenn kein Filter gesetzt ist.
    """
    parts: List[str] = []
    if not isinstance(filters, dict):
        return None
    # Preisbereich
    pmn = str(filters.get("price_min") or "").strip()
    pmx = str(filters.get("price_max") or "").strip()
    if pmn or pmx:
        parts.append(f"price:[{pmn}..{pmx}]")
        if EBAY_CURRENCY:  # Annahme: Deine Config-Variable
            parts.append(f"priceCurrency:{EBAY_CURRENCY}")
    # Zustand(e)
    conds = [str(c).strip().upper() for c in (filters.get("conditions") or []) if c and str(c).strip()]
    if conds:
        parts.append("conditions:{" + ",".join(conds) + "}")
    # Listing / Angebotsformat
    lt = str(filters.get("listing_type") or "").strip().lower()
    if lt:
        if lt in ("buy_it_now", "bin", "fixed_price", "fixedprice", "fixed"):
            parts.append("buyingOptions:{FIXED_PRICE}")
        elif lt in ("auction", "auktion"):
            parts.append("buyingOptions:{AUCTION}")
        # 'all' -> nothing
    # Kostenloser Versand
    fs = str(filters.get("free_shipping") or "").strip().lower()
    if fs in ("1", "true", "yes", "on"):
        parts.append("deliveryOptions:{FREE}")
    # Land / Lieferland
    lc = str(filters.get("location_country") or "").strip().upper()
    if lc:
        parts.append(f"deliveryCountry:{lc}")
    # Top-rated seller
    tr = str(filters.get("top_rated_only") or "").strip().lower()
    if tr in ("1", "true", "yes", "on"):
        parts.append("sellerTopRated:true")
    # Returns accepted (erweitert)
    ra = str(filters.get("returns_accepted") or "").strip().lower()
    if ra in ("1", "true", "yes", "on"):
        parts.append("returnsAccepted:true")
    if parts:
        return ",".join(parts)
    return None

def _map_sort(ui_sort: str) -> Optional[str]:
    s = (ui_sort or "").strip()
    if not s or s == "best":  # Best Match
        return None
    if s == "price_asc":
        return "price"
    if s == "price_desc":
        return "-price"
    if s == "newly":
        return "newlyListed"
    return None

def ebay_search_one(
    term: str,
    limit: int,
    offset: int,
    filter_str: Optional[str],
    sort: Optional[str],
    marketplace_id: Optional[str] = None,
) -> Tuple[List[Dict], Optional[int]]:
    """
    Sucht ein Term via eBay Browse API. marketplace_id kann übergeben werden (z.B. 'EBAY_DE').
    Debug-Log gibt die finalen params aus.
    """
    token = ebay_get_token()  # Deine Funktion
    if not token or not term:
        return [], None
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    params = {"q": term, "limit": max(1, min(limit, 50)), "offset": max(0, offset)}
    if filter_str:
        params["filter"] = filter_str
    if sort:
        params["sort"] = sort
    used_marketplace = marketplace_id or EBAY_MARKETPLACE_ID  # Deine Config
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": used_marketplace,
    }
    # Debug: Log the final params we send to eBay (ohne Authorization)
    msg = f"[ebay_search_one] url={url} marketplace={used_marketplace} params={params}"
    try:
        current_app.logger.debug(msg)
    except Exception:
        print(msg)  # Fallback

    try:
        r = _http.get(url, headers=headers, params=params, timeout=15)
        r.raise_for_status()
        j = r.json() or {}
        items_raw = j.get("itemSummaries", []) or []
        total = j.get("total")
        items: List[Dict] = []
        for it in items_raw:
            title = it.get("title") or "—"
            web = _append_affiliate(it.get("itemWebUrl"))
            img = (it.get("image") or {}).get("imageUrl")
            price = (it.get("price") or {}).get("value")
            cur = (it.get("price") or {}).get("currency")
            price_str = f"{price} {cur}" if price and cur else "–"
            iid = (
                it.get("itemId")
                or it.get("legacyItemId")
                or it.get("epid")
                or (web or "")[:200]
            )
            items.append(
                {
                    "id": iid,
                    "title": title,
                    "price": price_str,
                    "url": web,
                    "img": img,
                    "term": term,
                    "src": "ebay",
                }
            )
        return items, (int(total) if isinstance(total, int) else None)
    except Exception as e:
        try:
            current_app.logger.exception("[ebay_search_one] request failed")
        except Exception:
            print(f"[ebay_search_one] request failed: {e}")
        return [], None

def _backend_search_demo(
    terms: List[str], filters: dict, page: int, per_page: int
) -> Tuple[List[Dict], int]:
    """
    Simuliertes Demo-Backend, das einfache Filter (price range, condition, country, free_shipping)
    berücksichtigt, damit die UI lokal getestet werden kann.
    - Erzeugt deterministische Preise und Zustände (NEW/USED) pro Item.
    - Filter werden angewendet bevor Paging berechnet wird.
    """
    # Parse filter values (sicher)
    try:
        pmin = float(filters.get("price_min") or 0) if (filters.get("price_min") or "") != "" else None
    except Exception:
        pmin = None
    try:
        pmax = float(filters.get("price_max") or 0) if (filters.get("price_max") or "") != "" else None
    except Exception:
        pmax = None

    conds = [(c or "").strip().upper() for c in (filters.get("conditions") or []) if (c or "").strip()]
    location_country = (filters.get("location_country") or "").upper()
    free_shipping = bool(filters.get("free_shipping"))
    # top_rated_only ignored in demo or simulated below

    # Generate a larger pool of candidate items (deterministic)
    pool: List[Dict] = []
    pool_size = max(60, len(terms) * 40)
    for i in range(pool_size):
        # choose a term to include in title/url for deterministic matching
        t = terms[i % max(1, len(terms))] if terms else f"Artikel {i+1}"
        # deterministic price (e.g. 20 + (i % 50) * 5)
        price_val = 20 + (i % 50) * 5
        # deterministic condition
        condition = "USED" if (i % 2 == 0) else "NEW"
        # deterministic free shipping for some items
        item_free_shipping = (i % 3 == 0)
        # deterministic country distribution
        country = ["DE", "AT", "CH", "GB", "US"][i % 5]

        item = {
            "id": f"demo-{i+1}",
            "title": f"Demo-Ergebnis für „{t}“ #{i+1} [{condition}]",
            "price": f"{price_val:.2f} EUR",
            "price_val": price_val,
            "condition": condition,
            "url": f"https://www.ebay.de/sch/i.html?_nkw={t}",
            "img": "https://via.placeholder.com/64x48?text=%20",
            "term": t,
            "src": "demo",
            "country": country,
            "free_shipping": item_free_shipping,
            "seller_top_rated": (i % 10 == 0),
        }
        pool.append(item)

    # Apply filters to pool
    def keep(it):
        # term match (must contain first search term in title/url)
        if terms:
            # require at least one search term substring in title (case-insensitive)
            t0 = (terms[0] or "").strip().lower()
            if t0 and t0 not in (it["title"] or "").lower() and t0 not in (it["term"] or "").lower():
                return False
        # price range
        if pmin is not None and it["price_val"] < pmin:
            return False
        if pmax is not None and it["price_val"] > pmax:
            return False
        # conditions (if provided)
        if conds:
            if it.get("condition", "").upper() not in conds:
                return False
        # country (if provided)
        if location_country:
            if it.get("country", "").upper() != location_country:
                return False
        # free shipping
        if filters.get("free_shipping"):
            if not it.get("free_shipping", False):
                return False
        # top rated
        if filters.get("top_rated_only"):
            if not it.get("seller_top_rated", False):
                return False
        return True

    filtered = [it for it in pool if keep(it)]

    total = len(filtered)
    # pagination
    start = (page - 1) * per_page
    stop = start + per_page
    page_items = filtered[start:stop]

    # Map back to expected item shape (drop internal keys)
    items: List[Dict] = []
    for it in page_items:
        items.append(
            {
                "id": it["id"],
                "title": it["title"],
                "price": f"{it['price_val']:.2f} EUR",
                "url": it["url"],
                "img": it["img"],
                "term": it["term"],
                "src": "demo",
            }
        )

    return items, total


# Mini-Cache
_search_cache: dict = {}  # key -> (ts, (items, total_estimated))

# -------------------------
# 1) Saubere _build_ebay_filters
# -------------------------
def _build_ebay_filters(filters: dict) -> Optional[str]:
    """
    Baut den 'filter' Query-Parameter für die eBay Browse API.

    KORRIGIERT: Alle Filter werden nun korrekt verarbeitet.
    """
    parts: List[str] = []

    if not isinstance(filters, dict):
        print("[DEBUG] _build_ebay_filters: filters ist kein dict!")
        return None

    # ========== PREIS ==========
    pmn = str(filters.get("price_min") or "").strip()
    pmx = str(filters.get("price_max") or "").strip()
    if pmn or pmx:
        parts.append(f"price:[{pmn}..{pmx}]")
        if EBAY_CURRENCY:
            parts.append(f"priceCurrency:{EBAY_CURRENCY}")
        print(f"[DEBUG] Filter: Preis [{pmn}..{pmx}] {EBAY_CURRENCY}")

    # ========== ZUSTAND ==========
    conds = [str(c).strip().upper() for c in (filters.get("conditions") or []) if c and str(c).strip()]
    if conds:
        parts.append("conditions:{" + ",".join(conds) + "}")
        print(f"[DEBUG] Filter: Zustand {conds}")

    # ========== ANGEBOTSFORMAT (buyingOptions) ==========
    lt = str(filters.get("listing_type") or "").strip().lower()
    if lt:
        if lt in ("buy_it_now", "bin", "fixed_price", "fixedprice", "fixed"):
            parts.append("buyingOptions:{FIXED_PRICE}")
            print(f"[DEBUG] Filter: Nur Sofortkauf")
        elif lt in ("auction", "auktion"):
            parts.append("buyingOptions:{AUCTION}")
            print(f"[DEBUG] Filter: Nur Auktion")

    # ========== KOSTENLOSER VERSAND ==========
    # WICHTIG: Prüfe explizit auf Boolean True oder String "1"
    fs = filters.get("free_shipping")
    if fs is True or str(fs).strip().lower() in ("1", "true", "yes", "on"):
        parts.append("deliveryOptions:{FREE}")
        print(f"[DEBUG] Filter: Kostenloser Versand aktiviert")

    # ========== LIEFERLAND ==========
    lc = str(filters.get("location_country") or "").strip().upper()
    if lc and lc != "ALL":
        parts.append(f"deliveryCountry:{lc}")
        print(f"[DEBUG] Filter: Lieferland {lc}")

    # ========== TOP-RATED SELLER ==========
    tr = filters.get("top_rated_only")
    if tr is True or str(tr).strip().lower() in ("1", "true", "yes", "on"):
        parts.append("sellerTopRated:true")
        print(f"[DEBUG] Filter: Nur Top-bewertete Verkäufer")

    # ========== RÜCKGABERECHT ==========
    ra = filters.get("returns_accepted")
    if ra is True or str(ra).strip().lower() in ("1", "true", "yes", "on"):
        parts.append("returnsAccepted:true")
        print(f"[DEBUG] Filter: Nur mit Rückgaberecht")

    if parts:
        result = ",".join(parts)
        print(f"[DEBUG] FINALER FILTER-STRING: {result}")
        return result

    print("[DEBUG] Keine Filter gesetzt")
    return None


def _map_sort(ui_sort: str) -> Optional[str]:
    """Mappt UI-Sortierung auf eBay API sort-Parameter."""
    s = (ui_sort or "").strip()
    if not s or s == "best":
        return None  # Best Match (default)
    if s == "price_asc":
        return "price"
    if s == "price_desc":
        return "-price"
    if s == "newly":
        return "newlyListed"
    return None


def ebay_search_one(
    term: str,
    limit: int,
    offset: int,
    filter_str: Optional[str],
    sort: Optional[str],
    marketplace_id: Optional[str] = None,
) -> Tuple[List[Dict], Optional[int]]:
    """
    Sucht einen Begriff via eBay Browse API.

    KORRIGIERT: Debug-Logging zeigt alle Parameter.
    """
    # Annahme: Diese Funktion existiert bereits
    from app import ebay_get_token, _append_affiliate
    import requests as _http
    from flask import current_app

    token = ebay_get_token()
    if not token or not term:
        print(f"[DEBUG] ebay_search_one: Kein Token oder Term! token={bool(token)}, term={term}")
        return [], None

    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    params = {
        "q": term,
        "limit": max(1, min(limit, 50)),
        "offset": max(0, offset)
    }

    if filter_str:
        params["filter"] = filter_str

    if sort:
        params["sort"] = sort

    used_marketplace = marketplace_id or EBAY_MARKETPLACE_ID

    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": used_marketplace,
    }

    # ========== DEBUG: ZEIGE ALLE PARAMETER ==========
    print("=" * 60)
    print(f"[eBay API Call] Term: {term}")
    print(f"[eBay API Call] URL: {url}")
    print(f"[eBay API Call] Marketplace: {used_marketplace}")
    print(f"[eBay API Call] Params: {params}")
    print(f"[eBay API Call] Headers: Authorization=Bearer *****, X-EBAY-C-MARKETPLACE-ID={used_marketplace}")
    print("=" * 60)

    try:
        current_app.logger.debug(f"[ebay_search_one] Calling eBay API with params={params}")
    except:
        pass

    try:
        r = _http.get(url, headers=headers, params=params, timeout=15)
        r.raise_for_status()
        j = r.json() or {}

        items_raw = j.get("itemSummaries", []) or []
        total = j.get("total")

        print(f"[eBay API Response] Total: {total}, Items returned: {len(items_raw)}")

        items: List[Dict] = []
        for it in items_raw:
            title = it.get("title") or "—"
            web = _append_affiliate(it.get("itemWebUrl"))
            img = (it.get("image") or {}).get("imageUrl")
            price = (it.get("price") or {}).get("value")
            cur = (it.get("price") or {}).get("currency")
            price_str = f"{price} {cur}" if price and cur else "–"

            iid = (
                it.get("itemId")
                or it.get("legacyItemId")
                or it.get("epid")
                or (web or "")[:200]
            )

            items.append({
                "id": iid,
                "title": title,
                "price": price_str,
                "url": web,
                "img": img,
                "term": term,
                "src": "ebay",
            })

        return items, (int(total) if isinstance(total, int) else None)

    except Exception as e:
        print(f"[eBay API ERROR] {e}")
        try:
            current_app.logger.exception("[ebay_search_one] request failed")
        except:
            pass
        return [], None


def _backend_search_ebay(
    terms: List[str],
    filters: dict,
    page: int,
    per_page: int
) -> Tuple[List[Dict], Optional[int]]:
    """
    Hauptfunktion für eBay-Suche mit korrekter Filter-Anwendung.

    KORRIGIERT:
    - Filter werden korrekt gebaut und übergeben
    - Marketplace wird basierend auf location_country gesetzt
    - Debug-Ausgaben zeigen den kompletten Ablauf
    """
    print("\n" + "=" * 70)
    print("=== _backend_search_ebay AUFGERUFEN ===")
    print(f"Terms: {terms}")
    print(f"Filters: {filters}")
    print(f"Page: {page}, Per Page: {per_page}")
    print("=" * 70)

    # ========== LIVE-SEARCH PRÜFUNG ==========
    LIVE_SEARCH_BOOL = str(os.getenv("LIVE_SEARCH", "false")).strip().lower() in ("true", "1", "yes", "on")
    EBAY_CLIENT_ID = os.getenv("EBAY_CLIENT_ID")
    EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET")

    print(f"[DEBUG] LIVE_SEARCH={LIVE_SEARCH_BOOL}")
    print(f"[DEBUG] EBAY_CLIENT_ID={'vorhanden' if EBAY_CLIENT_ID else 'FEHLT!'}")
    print(f"[DEBUG] EBAY_CLIENT_SECRET={'vorhanden' if EBAY_CLIENT_SECRET else 'FEHLT!'}")

    if not LIVE_SEARCH_BOOL or not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
        print("[WARNUNG] Live-Suche nicht möglich → Fallback zu Demo-Modus")
        # Annahme: Diese Funktion existiert
        from app import _backend_search_demo
        return _backend_search_demo(terms, filters, page, per_page)

    # ========== FILTER BAUEN ==========
    print("\n--- Filter werden gebaut ---")
    filter_str = _build_ebay_filters(filters)
    sort = _map_sort(filters.get("sort", "best"))

    print(f"[DEBUG] Filter-String: {filter_str or 'KEINE FILTER'}")
    print(f"[DEBUG] Sort-Parameter: {sort or 'BEST_MATCH (default)'}")

    # ========== MARKETPLACE BASIEREND AUF LAND ==========
    marketplace_map = {
        "DE": "EBAY_DE",
        "CH": "EBAY_CH",
        "AT": "EBAY_AT",
        "GB": "EBAY_GB",
        "US": "EBAY_US",
    }
    location_country = (filters.get("location_country") or "DE").upper()
    marketplace_id = marketplace_map.get(location_country, EBAY_MARKETPLACE_ID)

    print(f"[DEBUG] Location Country: {location_country}")
    print(f"[DEBUG] Marketplace ID: {marketplace_id}")

    # ========== SUCHE PRO BEGRIFF ==========
    n = max(1, len(terms))
    per_term = max(1, per_page // n)
    offset = (page - 1) * per_term

    print(f"\n--- Suche {n} Begriff(e), {per_term} Ergebnisse pro Begriff, Offset {offset} ---")

    items_all: List[Dict] = []
    totals: List[int] = []

    for i, t in enumerate(terms, 1):
        print(f"\n[{i}/{n}] Suche Begriff: '{t}'")
        items, total = ebay_search_one(t, per_term, offset, filter_str, sort, marketplace_id=marketplace_id)
        items_all.extend(items)
        if isinstance(total, int):
            totals.append(total)
        print(f"[{i}/{n}] Gefunden: {len(items)} Items, Total: {total}")

    # ========== AUFFÜLLEN MIT ERSTEM BEGRIFF ==========
    if len(items_all) < per_page and terms:
        rest = per_page - len(items_all)
        base = offset + per_term
        print(f"\n--- Fülle auf mit {rest} weiteren Ergebnissen von '{terms[0]}', Offset {base} ---")
        extra, _ = ebay_search_one(terms[0], rest, base, filter_str, sort, marketplace_id=marketplace_id)
        items_all.extend(extra)
        print(f"--- {len(extra)} zusätzliche Items geladen ---")

    total_estimated = sum(totals) if totals else None

    print(f"\n=== ENDERGEBNIS: {len(items_all)} Items, Geschätzt insgesamt: {total_estimated} ===")
    print("=" * 70 + "\n")

    return items_all[:per_page], total_estimated


# ========== DEMO-BACKEND FÜR TESTS ==========
def _backend_search_demo(
    terms: List[str],
    filters: dict,
    page: int,
    per_page: int
) -> Tuple[List[Dict], int]:
    """
    Demo-Backend mit Filter-Simulation für lokale Tests.
    """
    print("[DEMO MODE] Verwende simulierte eBay-Daten")

    # Parse Filter
    try:
        pmin = float(filters.get("price_min") or 0) if (filters.get("price_min") or "") != "" else None
    except:
        pmin = None

    try:
        pmax = float(filters.get("price_max") or 0) if (filters.get("price_max") or "") != "" else None
    except:
        pmax = None

    conds = [(c or "").strip().upper() for c in (filters.get("conditions") or []) if (c or "").strip()]
    location_country = (filters.get("location_country") or "").upper()
    free_shipping = filters.get("free_shipping") is True or str(filters.get("free_shipping", "")).strip() == "1"

    print(f"[DEMO] Filter: Preis {pmin}-{pmax}, Zustand {conds}, Land {location_country}, Versand frei: {free_shipping}")

    # Generiere Pool
    pool: List[Dict] = []
    pool_size = max(60, len(terms) * 40)

    for i in range(pool_size):
        t = terms[i % max(1, len(terms))] if terms else f"Artikel {i+1}"
        price_val = 20 + (i % 50) * 5
        condition = "USED" if (i % 2 == 0) else "NEW"
        item_free_shipping = (i % 3 == 0)
        country = ["DE", "AT", "CH", "GB", "US"][i % 5]

        item = {
            "id": f"demo-{i+1}",
            "title": f"Demo: {t} #{i+1} [{condition}]",
            "price": f"{price_val:.2f} EUR",
            "price_val": price_val,
            "condition": condition,
            "url": f"https://www.ebay.de/sch/i.html?_nkw={t}",
            "img": "https://via.placeholder.com/64x48?text=%20",
            "term": t,
            "src": "demo",
            "country": country,
            "free_shipping": item_free_shipping,
        }
        pool.append(item)

    # Filter anwenden
    def keep(it):
        # Term Match
        if terms:
            t0 = (terms[0] or "").strip().lower()
            if t0 and t0 not in (it["title"] or "").lower():
                return False

        # Preis
        if pmin is not None and it["price_val"] < pmin:
            return False
        if pmax is not None and it["price_val"] > pmax:
            return False

        # Zustand
        if conds and it.get("condition", "").upper() not in conds:
            return False

        # Land
        if location_country and it.get("country", "").upper() != location_country:
            return False

        # Kostenloser Versand
        if free_shipping and not it.get("free_shipping", False):
            return False

        return True

    filtered = [it for it in pool if keep(it)]
    total = len(filtered)

    # Pagination
    start = (page - 1) * per_page
    stop = start + per_page
    page_items = filtered[start:stop]

    print(f"[DEMO] {total} gefilterte Items, zeige {len(page_items)} auf Seite {page}")

    # Zurück zur erwarteten Struktur
    items: List[Dict] = []
    for it in page_items:
        items.append({
            "id": it["id"],
            "title": it["title"],
            "price": f"{it['price_val']:.2f} EUR",
            "url": it["url"],
            "img": it["img"],
            "term": it["term"],
            "src": "demo",
        })

    return items, total


# -------------------------------------------------------------------
# Amazon PA-API (optional + fail-safe)
# -------------------------------------------------------------------
AMZ_ENABLED = os.getenv("AMZ_ENABLED", "0") in {"1", "true", "True", "yes", "on"}
AMZ_ACCESS = getenv_any("AMZ_ACCESS_KEY_ID", "AMZ_ACCESS_KEY")
AMZ_SECRET = getenv_any("AMZ_SECRET_ACCESS_KEY", "AMZ_SECRET")
AMZ_TAG = getenv_any("AMZ_PARTNER_TAG", "AMZ_ASSOC_TAG", "AMZ_TRACKING_ID")
AMZ_COUNTRY = os.getenv("AMZ_COUNTRY", "DE")

AMZ_OK = False
amazon_client = None
try:
    if AMZ_ENABLED:
        from amazon_paapi import AmazonApi

        if AMZ_ACCESS and AMZ_SECRET and AMZ_TAG:
            amazon_client = AmazonApi(AMZ_ACCESS, AMZ_SECRET, AMZ_TAG, AMZ_COUNTRY)
            AMZ_OK = True
except Exception as _e:
    print("[amazon] init failed:", _e)
    AMZ_OK = False
    amazon_client = None


def amazon_search_one(
    term: str, limit: int, page: int, price_min: str = "", price_max: str = ""
) -> Tuple[List[Dict], Optional[int]]:
    if not (AMZ_OK and term and amazon_client):
        return [], None
    try:
        item_count = max(1, min(limit, 10))
        page = max(1, min(page, 10))
        kwargs = {
            "keywords": term,
            "item_count": item_count,
            "item_page": page,
            "search_index": "All",
            "resources": [
                "ItemInfo.Title",
                "Images.Primary.Small",
                "Offers.Listings.Price",
                "DetailPageURL",
            ],
        }
        if price_min:
            kwargs["min_price"] = int(float(price_min) * 100)
        if price_max:
            kwargs["max_price"] = int(float(price_max) * 100)

        res = amazon_client.search_items(**kwargs)

        items: List[Dict] = []
        for p in getattr(res, "items", []) or []:
            try:
                title = p.item_info.title.display_value
            except Exception:
                title = "—"
            url = getattr(p, "detail_page_url", None)
            img = None
            try:
                img = p.images.primary.small.url
            except Exception:
                pass
            price_val, currency = None, None
            try:
                pr = p.offers.listings[0].price
                price_val = getattr(pr, "amount", None)
                currency = getattr(pr, "currency", None)
            except Exception:
                pass
            price_str = f"{price_val} {currency}" if price_val and currency else "–"
            asin = getattr(p, "asin", url or title) or f"{term}-{page}-{len(items)+1}"
            items.append(
                {
                    "id": asin,
                    "title": title,
                    "price": price_str,
                    "img": img,
                    "url": url,
                    "term": term,
                    "src": "amazon",
                }
            )
        return items, None
    except Exception as e:
        print("[amazon] search error:", e)
        return [], None


def _backend_search_amazon(terms: List[str], filters: dict, page: int, per_page: int):
    if not AMZ_OK:
        return [], None
    per_term = max(1, per_page // max(1, len(terms)))
    all_items: List[Dict] = []
    for t in terms:
        part, _ = amazon_search_one(
            t,
            per_term,
            page,
            filters.get("price_min") or "",
            filters.get("price_max") or "",
        )
        all_items.extend(part)
    return all_items[:per_page], None


def _backend_search_combined(terms: List[str], filters: dict, page: int, per_page: int):
    """eBay ist Leitquelle (liefert total), Amazon wird interleaved."""
    ebay_items, ebay_total = _backend_search_ebay(terms, filters, page, per_page)
    amz_items, _ = _backend_search_amazon(terms, filters, page, per_page)
    out: List[Dict] = []
    i = j = 0
    while len(out) < per_page and (i < len(ebay_items) or j < len(amz_items)):
        if i < len(ebay_items):
            ebay_items[i]["src"] = "ebay"
            out.append(ebay_items[i])
            i += 1
        if len(out) >= per_page:
            break
        if j < len(amz_items):
            out.append(amz_items[j])
            j += 1
    return out, ebay_total


# -------------------------------------------------------------------
# Suche + Cache Wrapper
# -------------------------------------------------------------------
def _search_with_cache(terms: List[str], filters: dict, page: int, per_page: int):
    use_amazon = AMZ_OK
    key = (
        tuple(terms),
        filters.get("price_min") or "",
        filters.get("price_max") or "",
        filters.get("sort") or "best",
        tuple(filters.get("conditions") or []),
        page,
        per_page,
        "amz" if use_amazon else "ebay",
    )
    cached = _cache_get(key)
    if cached:
        return cached
    if use_amazon:
        items, total = _backend_search_combined(terms, filters, page, per_page)
    else:
        items, total = _backend_search_ebay(terms, filters, page, per_page)
    _cache_set(key, (items, total))
    return items, total


# -------------------------------------------------------------------
# E-Mail: Versand + De-Duping
# -------------------------------------------------------------------
def _send_email(to_email: str, subject: str, html_body: str) -> bool:
    """Send email using agent.py mail settings (Postmark or SMTP)"""
    try:
        mail_settings = get_mail_settings()
        success = send_mail(mail_settings, [to_email], subject, html_body)
        return success
    except Exception as e:
        print(f"[_send_email] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def _make_search_hash(terms: List[str], filters: dict) -> str:
    payload = {
        "terms": [t.strip() for t in terms if t.strip()],
        "filters": {
            "price_min": filters.get("price_min") or "",

            "price_max": filters.get("price_max") or "",
            "sort": filters.get("sort") or "best",
            "conditions": sorted(filters.get("conditions") or []),
        },
    }
    s = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _render_items_html(title: str, items: List[Dict]) -> str:
    rows = []
    for it in items[:NOTIFY_MAX_ITEMS_PER_MAIL]:
        img = it.get("img") or "https://via.placeholder.com/96x72?text=%20"
        url = it.get("url") or "#"
        price = it.get("price") or "–"
        src = it.get("src") or ""
        badge = (
            f'<span style="background:#eef;padding:2px 6px;border-radius:4px;font-size:12px;margin-left:8px">{src}</span>'
            if src
            else ""
        )
        rows.append(
            f"""
        <tr>
            <td style="padding:8px 12px"><img src="{img}" alt="" width="96" style="border:1px solid #ddd;border-radius:4px"></td>
            <td style="padding:8px 12px">
              <div style="font-weight:600;margin-bottom:4px"><a href="{url}" target="_blank" style="text-decoration:none;color:#0d6efd">{it.get('title') or '—'}</a>{badge}</div>
              <div style="color:#333">{price}</div>
            </td>
        </tr>
        """
        )
    more = ""
    if len(items) > NOTIFY_MAX_ITEMS_PER_MAIL:
        more = f"<p style='margin-top:8px'>+ {len(items) - NOTIFY_MAX_ITEMS_PER_MAIL} weitere Treffer …</p>"
    return f"""
    <div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
      <h2 style="margin:0 0 12px">{title}</h2>
      <table cellspacing="0" cellpadding="0" border="0">{''.join(rows)}</table>
      {more}
      <p style="margin-top:16px;color:#666;font-size:12px">Du erhältst diese Mail, weil du für diese Suche einen Alarm aktiviert hast.</p>
    </div>
    """


def _mark_and_filter_new(
    user_email: str, search_hash: str, src: str, items: List[Dict]
) -> List[Dict]:
    """Nur Items zurückgeben, die für diese Suche/Person/Src noch nicht (oder nach Cooldown) gemailt wurden."""
    if not items:
        return []
    now = int(time.time())
    conn = get_db()
    cur = conn.cursor()
    new_items: List[Dict] = []
    for it in items:
        iid = str(it.get("id") or it.get("url") or it.get("title"))[:255]
        cur.execute(
            """
            SELECT last_sent FROM alert_seen
            WHERE user_email=? AND search_hash=? AND src=? AND item_id=?
        """,
            (user_email, search_hash, src, iid),
        )
        row = cur.fetchone()
        if not row:
            new_items.append(it)
            cur.execute(
                """
                INSERT INTO alert_seen (user_email, search_hash, src, item_id, first_seen, last_sent)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (user_email, search_hash, src, iid, now, 0),
            )
        else:
            last_sent = int(row["last_sent"])
            if last_sent == 0:
                new_items.append(it)
            else:
                if now - last_sent >= NOTIFY_COOLDOWN_MIN * 60:
                    new_items.append(it)
    conn.commit()
    conn.close()
    return new_items


def _group_by_src(items: List[Dict]) -> Dict[str, List[Dict]]:
    groups: Dict[str, List[Dict]] = {}
    for it in items:
        src = (it.get("src") or "ebay").lower()
        groups.setdefault(src, []).append(it)
    return groups


def _mark_sent(user_email: str, search_hash: str, src: str, items: List[Dict]) -> None:
    now = int(time.time())
    if not items:
        return
    conn = get_db()
    cur = conn.cursor()
    for it in items:
        iid = str(it.get("id") or it.get("url") or it.get("title"))[:255]
        cur.execute(
            """
            UPDATE alert_seen
               SET last_sent=?
             WHERE user_email=? AND search_hash=? AND src=? AND item_id=?
        """,
            (now, user_email, search_hash, src, iid),
        )
    conn.commit()
    conn.close()


# -------------------------------------------------------------------
# DB (Users + Alerts/Seen)
# -------------------------------------------------------------------
def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_FILE), detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_db()
    cur = conn.cursor()
    # users
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            is_premium INTEGER NOT NULL DEFAULT 0
        )
    """
    )
    # items gesehen/versendet
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_seen (
            user_email   TEXT    NOT NULL,
            search_hash  TEXT    NOT NULL,
            src          TEXT    NOT NULL,
            item_id      TEXT    NOT NULL,
            first_seen   INTEGER NOT NULL,
            last_sent    INTEGER NOT NULL,
            PRIMARY KEY (user_email, search_hash, src, item_id)
        )
    """
    )
    # gespeicherte Alerts (für Cron)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS search_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email   TEXT NOT NULL,
            terms_json   TEXT NOT NULL,
            filters_json TEXT NOT NULL,
            per_page     INTEGER NOT NULL DEFAULT 20,
            is_active    INTEGER NOT NULL DEFAULT 1,
            last_run_ts  INTEGER NOT NULL DEFAULT 0
        )
    """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_alerts_active ON search_alerts(is_active)"
    )
    conn.commit()
    conn.close()


init_db()


# -------------------------------------------------------------------
# Template-Fallback
# -------------------------------------------------------------------
def safe_render(template_name: str, **ctx):
    try:
        return render_template(template_name, **ctx)
    except Exception:
        title = ctx.get("title", "ebay-agent-cockpit")
        body = ctx.get("body", "")
        try:
            home = url_for("public_home")
        except Exception:
            home = "/"
        return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet"></head>
<body class="container py-4">
<div class="alert alert-warning">Template <code>{template_name}</code> nicht gefunden – Fallback aktiv.</div>
<h1 class="h4">{title}</h1>
<div class="mb-3">{body}</div>
<p><a class="btn btn-primary" href="{home}">Zur Startseite</a></p>
</body></html>"""


# -------------------------------------------------------------------
# Context-Processor
# -------------------------------------------------------------------
def _build_query(existing: dict, **extra) -> str:
    merged = {**existing, **{k: v for k, v in extra.items() if v is not None}}
    pairs = []
    for k, v in merged.items():
        if v in (None, ""):
            continue
        if isinstance(v, (list, tuple)):
            for item in v:
                if item not in (None, ""):
                    pairs.append((k, str(item)))
        else:
            pairs.append((k, str(v)))
    return urlencode(pairs)


@app.context_processor
def inject_globals():
    return {
        "FREE_SEARCH_LIMIT": FREE_SEARCH_LIMIT,
        "PREMIUM_SEARCH_LIMIT": PREMIUM_SEARCH_LIMIT,
        "STRIPE_PRICE_BASIC": STRIPE_PRICE_BASIC,  # NEU
        "STRIPE_PRICE_PRO": STRIPE_PRICE_PRO,  # NEU
        "STRIPE_PRICE_TEAM": STRIPE_PRICE_TEAM,  # NEU
        "qs": _build_query,
        "plausible_domain": PLAUSIBLE_DOMAIN,
        "AMZ_TAG": os.getenv("AMZ_ASSOC_TAG", ""),
        "AMZ_COUNTRY": os.getenv("AMZ_COUNTRY", "DE"),
    }


# -------------------------------------------------------------------
# Session-Defaults + UTM
# -------------------------------------------------------------------
@app.before_request
def _ensure_session_defaults():
    session.setdefault("free_search_count", 0)
    session.setdefault("is_premium", False)
    session.setdefault("user_email", "guest")
    # UTM nur einmalig erfassen
    if not session.get("utm"):
        utm_keys = [
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_term",
            "utm_content",
        ]
        utm = {k: request.args.get(k) for k in utm_keys if request.args.get(k)}
        if utm:
            session["utm"] = utm


def _user_search_limit() -> int:
    return PREMIUM_SEARCH_LIMIT if session.get("is_premium") else FREE_SEARCH_LIMIT


# -------------------------------------------------------------------
# Auth (Demo)
# -------------------------------------------------------------------


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return safe_render("register.html", title="Registrieren")

    email = (request.form.get("email") or "").strip().lower()
    password = (request.form.get("password") or "").strip()
    
    if not email or not password:
        flash("Bitte E-Mail und Passwort angeben.", "warning")
        return redirect(url_for("register"))

    # Passwort hashen!
    from werkzeug.security import generate_password_hash
    password_hash = generate_password_hash(password)

    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import IntegrityError
    
    db_url = os.getenv("DATABASE_URL", f"sqlite:///{DB_FILE}")
    engine = create_engine(db_url)
    
    try:
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO users (email, password, is_premium) VALUES (:email, :password, 0)"),
                {"email": email, "password": password_hash}
            )
        flash("✅ Registrierung erfolgreich. Bitte einloggen.", "success")
        return redirect(url_for("login"))
        
    except IntegrityError:
        flash("Diese E-Mail ist bereits registriert.", "warning")
        return redirect(url_for("register"))
    except Exception as e:
        print(f"[REGISTER] Error: {e}")
        flash("Fehler bei der Registrierung.", "danger")
        return redirect(url_for("register"))





@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return safe_render("login.html", title="Login")
    
    print(f"[DEBUG] DATABASE_URL: {os.getenv('DATABASE_URL', 'NOT SET')}")
    print(f"[DEBUG] DB_FILE: {DB_FILE}")
    
    email = (request.form.get("email") or "").strip().lower()
    password = (request.form.get("password") or "").strip()
    
    # SQLAlchemy statt get_db()
    from sqlalchemy import create_engine, text
    from werkzeug.security import check_password_hash
    
    db_url = os.getenv("DATABASE_URL", f"sqlite:///{DB_FILE}")
    engine = create_engine(db_url)
    
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT id, password, is_premium FROM users WHERE email = :email"),
            {"email": email}
        )
        row = result.fetchone()
    
    # Passwort-Check mit Hash-Vergleich
    if not row or not check_password_hash(row[1], password):
        flash("E-Mail oder Passwort ist falsch.", "warning")
        return redirect(url_for("login"))
    
    session["user_id"] = int(row[0])
    session["user_email"] = email
    session["is_premium"] = bool(row[2])
    flash("Login erfolgreich.", "success")
    return redirect(url_for("dashboard"))

@app.route("/logout")
def logout():
    session.clear()
    flash("Logout erfolgreich.", "info")
    return redirect(url_for("public_home"))


# -------------------------------------------------------------------
# Public / Dashboard / Free-Start
# -------------------------------------------------------------------
@app.route("/")
def root_redirect():
    return redirect(url_for("public_home"))


@app.route("/public")
def public_home():
    return safe_render("public_home.html", title="Start – ebay-agent-cockpit")


@app.route("/pricing")
def public_pricing():
    ev_free_limit_hit = bool(session.pop("ev_free_limit_hit", False))
    return safe_render(
        "public_pricing.html",
        title="Preise – ebay-agent-cockpit",
        ev_free_limit_hit=ev_free_limit_hit,
    )


@app.route("/dashboard")
def dashboard():
    """Dashboard mit Telegram-Status, Alerts, Statistiken"""
    if not session.get("user_id"):
        flash("Bitte einloggen.", "info")
        return redirect(url_for("login"))

    user_email = session.get("user_email")

    try:
        conn = get_db()
        cur = conn.cursor()

        # User-Daten holen
        cur.execute("""
            SELECT email, telegram_chat_id, telegram_enabled, telegram_verified,
                   telegram_username, plan_type, is_premium
            FROM users WHERE email = ?
        """, (user_email,))

        user_row = cur.fetchone()
        user = dict(user_row) if user_row else {
            "email": user_email,
            "telegram_chat_id": None,
            "telegram_enabled": False,
            "telegram_verified": False,
            "telegram_username": None,
            "plan_type": "free",
            "is_premium": False
        }

        # Stats holen
        stats = get_watchlist_stats(user_email, conn)

        # Recent Alerts holen
        cur.execute("""
            SELECT id, terms_json, filters_json, last_run_ts
            FROM search_alerts
            WHERE user_email = ? AND is_active = 1
            ORDER BY id DESC LIMIT 10
        """, (user_email,))

        recent_alerts = []
        for row in cur.fetchall():
            row = dict(row)
            try:
                terms = json.loads(row["terms_json"])
                filters = json.loads(row["filters_json"])
                recent_alerts.append({
                    "id": row["id"],
                    "search_term": terms[0] if terms else "Unbekannt",
                    "price_min": filters.get("price_min", ""),
                    "price_max": filters.get("price_max", ""),
                    "location": filters.get("location_country", "DE"),
                    "free_shipping": filters.get("free_shipping", False)
                })
            except:
                continue

        conn.close()

        context = {
            "title": "Dashboard",
            "user": user,
            "stats": stats,
            "recent_alerts": recent_alerts,
            "watchlist_count": stats.get("active_alerts", 0),
            "notifications_today": stats.get("notifications_today", 0),
            "last_notification_time": "5"
        }

        return safe_render("dashboard.html", **context)

    except Exception as e:
        print(f"[Dashboard] Fehler: {e}")
        return safe_render("dashboard.html",
            title="Dashboard",
            user={"email": user_email, "telegram_verified": False},
            stats={"active_alerts": 0, "max_alerts": 3, "notifications_today": 0,
                   "plan": "free", "check_interval": 5},
            recent_alerts=[],
            watchlist_count=0,
            notifications_today=0
        )

# Watchlist Stats Funktion (ersetzt Import von watchlist_integration)
# -------------------------
# Watchlist-Statistiken
# -------------------------
def get_watchlist_stats(user_email, conn):
    """Holt Watchlist-Statistiken"""
    cur = conn.cursor()

    # Aktive Alerts
    cur.execute(
        """
        SELECT COUNT(*) as count
        FROM search_alerts
        WHERE user_email = ? AND is_active = 1
        """,
        (user_email,),
    )
    row = cur.fetchone()
    active_alerts = row["count"] if row and "count" in row else 0

    # Benachrichtigungen heute
    import time
    today_start = int(time.time()) - (24 * 3600)
    cur.execute(
        """
        SELECT COUNT(*) as count
        FROM alert_seen
        WHERE user_email = ? AND first_seen > ?
        """,
        (user_email, today_start),
    )
    row = cur.fetchone()
    notifications_today = row["count"] if row and "count" in row else 0

    # Plan-Limits
    cur.execute("SELECT plan_type FROM users WHERE email = ?", (user_email,))
    user = cur.fetchone()
    plan = user["plan_type"] if user and "plan_type" in user else "free"

    plan_limits = {
        "free": {"max_alerts": 3, "check_interval": 5},
        "basic": {"max_alerts": 10, "check_interval": 3},
        "pro": {"max_alerts": 50, "check_interval": 1},
        "team": {"max_alerts": 150, "check_interval": 1},
    }

    limits = plan_limits.get(plan, plan_limits["free"])

    return {
        "active_alerts": active_alerts,
        "max_alerts": limits["max_alerts"],
        "notifications_today": notifications_today,
        "plan": plan,
        "check_interval": limits["check_interval"],
    }


# -------------------------
# Dashboard-Route
# -------------------------
@app.route("/dashboard2")
def dashboard2():
    """Dashboard mit Telegram-Status, Alerts, Statistiken"""
    if not session.get("user_id"):
        flash("Bitte einloggen.", "info")
        return redirect(url_for("login"))

    user_email = session.get("user_email")

    try:
        conn = get_db()
        cur = conn.cursor()

        # User-Daten holen
        cur.execute(
            """
            SELECT email, telegram_chat_id, telegram_enabled, telegram_verified,
                   telegram_username, plan_type, is_premium
            FROM users WHERE email = ?
            """,
            (user_email,),
        )
        user_row = cur.fetchone()
        user = (
            dict(user_row)
            if user_row
            else {
                "email": user_email,
                "telegram_chat_id": None,
                "telegram_enabled": False,
                "telegram_verified": False,
                "telegram_username": None,
                "plan_type": "free",
                "is_premium": False,
            }
        )

        # Stats holen
        stats = get_watchlist_stats(user_email, conn)

        # ============================================================
        # RECENT ALERTS (Letzte 10)
        # ============================================================
        cur.execute(
            """
            SELECT id, terms_json, filters_json, last_run_ts
            FROM search_alerts
            WHERE user_email = ? AND is_active = 1
            ORDER BY id DESC
            LIMIT 10
            """,
            (user_email,),
        )

        alerts_raw = cur.fetchall()
        recent_alerts = []
        for row in alerts_raw:
            row = dict(row)
            try:
                terms = json.loads(row.get("terms_json") or "[]")
                filters = json.loads(row.get("filters_json") or "{}")
                recent_alerts.append(
                    {
                        "id": row.get("id"),
                        "search_term": terms[0] if terms else "Unbekannt",
                        "price_min": filters.get("price_min", ""),
                        "price_max": filters.get("price_max", ""),
                        "location": filters.get("location_country", "DE"),
                        "free_shipping": filters.get("free_shipping", False),
                        "last_check": row.get("last_run_ts", 0),
                    }
                )
            except Exception as e:
                app.logger.debug("[Dashboard] Alert-Parse-Fehler: %s", e)
                continue

        # ============================================================
        # WATCHLIST COUNT (für alte Kompatibilität)
        # ============================================================
        watchlist_count = stats.get("active_alerts", 0)
        try:
            cur.execute(
                """
                SELECT COUNT(*) as count
                FROM watchlist
                WHERE user_email = ?
                """,
                (user_email,),
            )
            old_watchlist_count = cur.fetchone()
            if old_watchlist_count and "count" in old_watchlist_count:
                watchlist_count = old_watchlist_count["count"]
        except Exception:
            # watchlist Tabelle existiert ggf. nicht — safe fallback
            pass

        # ============================================================
        # LETZTE BENACHRICHTIGUNG (optional)
        # ============================================================
        last_notification_time = "–"
        try:
            import time

            cur.execute(
                """
                SELECT MAX(first_seen) as last_seen
                FROM alert_seen
                WHERE user_email = ?
                """,
                (user_email,),
            )
            last_row = cur.fetchone()
            if last_row and last_row.get("last_seen"):
                last_seen = last_row["last_seen"]
                now = int(time.time())
                minutes_ago = (now - last_seen) // 60

                if minutes_ago < 60:
                    last_notification_time = f"{minutes_ago}"
                elif minutes_ago < 1440:  # < 24 Stunden
                    last_notification_time = f"{minutes_ago // 60}h"
                else:
                    last_notification_time = f"{minutes_ago // 1440}d"
        except Exception as e:
            app.logger.debug("[Dashboard] Last-Notification-Fehler: %s", e)

        conn.close()

        # ============================================================
        # CONTEXT ZUSAMMENSTELLEN
        # ============================================================
        context = {
            "title": "Dashboard",
            "user": user,
            "stats": stats,
            "recent_alerts": recent_alerts,
            "watchlist_count": watchlist_count,
            "notifications_today": stats.get("notifications_today", 0),
            "last_notification_time": last_notification_time,
            "avg_price_saved": 0,  # Optional: Später berechnen
        }

        return safe_render("dashboard.html", **context)

    except Exception as e:
        # Fehler-Fallback
        app.logger.exception("[Dashboard] Kritischer Fehler")
        context = {
            "title": "Dashboard",
            "user": {"email": user_email, "telegram_verified": False},
            "stats": {
                "active_alerts": 0,
                "max_alerts": 3,
                "notifications_today": 0,
                "plan": "free",
                "check_interval": 5,
            },
            "recent_alerts": [],
            "watchlist_count": 0,
            "notifications_today": 0,
            "last_notification_time": "–",
        }
        return safe_render("dashboard.html", **context)



@app.route("/start-free")
@app.route("/free")
def start_free():
    session["is_premium"] = False
    session["free_search_count"] = 0
    session["user_email"] = "guest"
    return redirect(url_for("search"))


# -------------------------------------------------------------------
# Suche – PRG + Pagination + Filter
# -------------------------------------------------------------------
from urllib.parse import urlencode

@app.route("/search", methods=["GET", "POST"])
def search():
    # DEBUG: Log eingehender Request-Daten
    current_app.logger.debug("=== /search called, method=%s ===", request.method)
    current_app.logger.debug("request.args: %s", request.args.to_dict(flat=False))
    current_app.logger.debug("request.form: %s", request.form.to_dict(flat=False))
    try:
        current_app.logger.debug("request.json: %s", request.get_json(silent=True))
    except Exception:
        current_app.logger.debug("request.json: <error>")

    # --------------------
    # POST -> Redirect mit Querystring (PRG)
    # --------------------
    if request.method == "POST":
        # DEBUG: show form content
        current_app.logger.debug("[DEBUG] POST received! Form data: %s", dict(request.form))

        # Parameter sammeln (condition als Liste) – FIX: Checkboxen nur wenn gesendet!
        params = {
            "q1": (request.form.get("q1") or "").strip(),
            "q2": (request.form.get("q2") or "").strip(),
            "q3": (request.form.get("q3") or "").strip(),
            "price_min": (request.form.get("price_min") or "").strip(),
            "price_max": (request.form.get("price_max") or "").strip(),
            "sort": (request.form.get("sort") or "best").strip(),
            "per_page": (request.form.get("per_page") or "").strip(),
            "condition": request.form.getlist("condition"),
            # Erweiterte Filter – FIX: Nur senden, wenn vorhanden (kein "0"!)
            "location_country": (request.form.get("location_country") or "DE").strip(),
            "free_shipping": request.form.get("free_shipping"),  # None oder "1" → urlencode ignoriert None
            "returns_accepted": request.form.get("returns_accepted"),
            "top_rated_only": request.form.get("top_rated_only"),
            "listing_type": request.form.get("listing_type", "").strip(),  # NEU: Auktion/Sofortkauf
        }

        # Free-Limit zählen (vor Redirect)
        if not session.get("is_premium", False):
            count = int(session.get("free_search_count", 0))
            if count >= FREE_SEARCH_LIMIT:  # Deine Config
                session["ev_free_limit_hit"] = True
                flash(
                    f"Kostenloses Limit ({FREE_SEARCH_LIMIT}) erreicht – bitte Upgrade buchen.",
                    "info",
                )
                return redirect(url_for("public_pricing"))
            session["free_search_count"] = count + 1

        # Seite auf 1 setzen
        params["page"] = 1

        # DEBUG: raw params zeigen
        current_app.logger.debug("POST -> redirect params (raw): %s", params)

        # Querystring bauen (doseq=True sorgt für condition=a&condition=b; None-Werte werden ignoriert)
        query = urlencode(params, doseq=True)
        redirect_url = url_for("search") + "?" + query
        current_app.logger.debug("Redirecting to: %s", redirect_url)
        return redirect(redirect_url)

    # --------------------
    # GET -> tatsächliche Suche
    # --------------------
    terms = [
        t
        for t in [
            (request.args.get("q1") or "").strip(),
            (request.args.get("q2") or "").strip(),
            (request.args.get("q3") or "").strip(),
        ]
        if t
    ]

    if not terms:
        return safe_render("search.html", title="Suche")  # Deine safe_render-Funktion

    # Filter aus request.args extrahieren
    filters = {
        "price_min": request.args.get("price_min", "").strip(),
        "price_max": request.args.get("price_max", "").strip(),
        "sort": request.args.get("sort", "best").strip(),
        "conditions": request.args.getlist("condition") or [],
        # Erweiterte Filter – FIX: Bool nur wenn "1" vorhanden
        "location_country": request.args.get("location_country", "DE").strip(),
        "free_shipping": request.args.get("free_shipping") == "1",
        "returns_accepted": request.args.get("returns_accepted") == "1",
        "top_rated_only": request.args.get("top_rated_only") == "1",
        "listing_type": request.args.get("listing_type", "").strip(),  # NEU
    }

    # ✅ DEBUG: Jetzt NACH der filters-Definition!
    print("\n" + "="*70)
    print("🔍 SEARCH ROUTE - GET REQUEST")
    print("="*70)
    print(f"Terms: {terms}")
    print(f"\nFilters:")
    for key, value in filters.items():
        print(f"  {key}: {value!r}")
    print("="*70 + "\n")

    try:
        page = max(1, int(request.args.get("page", 1)))
    except Exception:
        page = 1

    try:
        per_page = min(100, max(5, int(request.args.get("per_page", PER_PAGE_DEFAULT))))  # Deine Config
    except Exception:
        per_page = PER_PAGE_DEFAULT

    # DEBUG: Backend-Aufruf
    current_app.logger.debug("Calling _backend_search_ebay with terms=%s filters=%s page=%s per_page=%s",
                             terms, filters, page, per_page)
    print(f"📞 Calling _backend_search_ebay(")
    print(f"     terms={terms},")
    print(f"     filters={filters},")
    print(f"     page={page},")
    print(f"     per_page={per_page}")
    print(f"   )\n")

    # Backend aufrufen
    items, total_estimated = _backend_search_ebay(terms, filters, page, per_page)

    # DEBUG: Backend-Resultat
    print(f"✅ Backend returned: {len(items)} items, total_estimated={total_estimated}\n")

    # Pagination berechnen
    total_pages = (
        math.ceil(total_estimated / per_page) if total_estimated is not None else None
    )
    has_prev = page > 1
    has_next = (total_pages and page < total_pages) or (
        not total_pages and len(items) == per_page
    )

    # Base Query-String für Pagination
    base_qs = {
        "q1": request.args.get("q1", ""),
        "q2": request.args.get("q2", ""),
        "q3": request.args.get("q3", ""),
        "price_min": filters["price_min"],
        "price_max": filters["price_max"],
        "sort": filters["sort"],
        "condition": filters["conditions"],
        "per_page": per_page,
        # Erweiterte Filter in base_qs – FIX: Nur "1" wenn True
        "location_country": filters["location_country"],
        "free_shipping": "1" if filters["free_shipping"] else None,  # None → ignoriert in urlencode
        "returns_accepted": "1" if filters["returns_accepted"] else None,
        "top_rated_only": "1" if filters["top_rated_only"] else None,
        "listing_type": filters.get("listing_type", ""),  # NEU
    }

    # Template rendern
    return safe_render(
        "search_results.html",
        title="Suchergebnisse",
        terms=terms,
        results=items,
        filters=filters,
        pagination={
            "page": page,
            "per_page": per_page,
            "total_estimated": total_estimated,
            "total_pages": total_pages,
            "has_prev": has_prev,
            "has_next": has_next,
        },
        base_qs=base_qs,
    )

@app.route("/cron/check-alerts", methods=["POST", "GET"])
def cron_check_alerts():
    """
    Cron-Job Route: Prüft alle Alerts und sendet Benachrichtigungen.
    """
    # Token aus Header oder Query-Parameter
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        token = request.args.get("token", "")

    # Token prüfen
    if not token or token != AGENT_TRIGGER_TOKEN:
        print("[Cron] ❌ Ungültiger Token")
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    print(f"[Cron] ✅ Alert-Check gestartet")

    try:
        result = run_alert_check()
        return jsonify(result), 200 if result["success"] else 500
    except Exception as e:
        print(f"[Cron] ❌ Fehler: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/", methods=["GET"])
def index():
    try:
        return "<br>".join(map(str, app.url_map.iter_rules()))
    except Exception:
        current_app.logger.exception("index failed")
        return "OK", 200


@app.route("/pilot/info")
def pilot_info():
    waitlist_url = request.url_root.rstrip("/") + "/pilot/waitlist"
    # Deinen internen Widget-Link NICHT direkt anzeigen (nur als Hinweis für das Team-Handout)
    return render_template("pilot_info.html", waitlist_url=waitlist_url)


@app.route("/favicon.ico")
def legacy_favicon():
    return redirect(url_for("static", filename="icons/favicon.ico"), code=302)

@app.route("/email/test", methods=["GET", "POST"])
def email_test():
    """
    Test-Route:
      - GET  /email/test?to=someone@example.com
      - POST form field 'email' (guest input)
      - Fallback: session.user_email or TEST_EMAIL / FROM_EMAIL env
    Optional: Admin-check or PILOT_EMAILS whitelist (siehe weiter unten).
    """
    # lokale Imports hier, damit app import-agent zyklische Abhängigkeiten vermeidet
    from agent import get_mail_settings, send_mail

    # optionaler Admin-Schutz (deaktiviere wenn nicht benötigt)
    if os.getenv("EMAIL_TEST_ADMIN_ONLY", "0") == "1":
        if not session.get("is_admin"):
            abort(403)

    # 1) Prioritäten: query param -> form -> session -> ENV
    recipient = (
        request.args.get("to")
        or request.form.get("email")
        or (session.get("user_email") if session is not None else None)
        or os.getenv("TEST_EMAIL")
        or os.getenv("FROM_EMAIL")
    )

    # einfache Validierung
    if not recipient or "@" not in recipient:
        flash("Keine gültige E-Mail-Adresse gefunden (query/form/session/ENV).", "danger")
        return redirect(url_for("search"))

    # optional: PILOT whitelist (nur zulässige Test-Adressen erlauben)
    pilot_raw = os.getenv("PILOT_EMAILS", "")
    if pilot_raw:
        pilot_set = {e.strip().lower() for p in pilot_raw.split(",") for e in p.split(";") if e.strip()}
        if pilot_set and recipient.lower() not in pilot_set:
            flash("Diese E-Mail ist nicht für Testversand freigeschaltet.", "warning")
            return redirect(url_for("search"))

    settings = get_mail_settings()
    subject = "✉️ Test-E-Mail vom eBay-Agent"
    body_html = "<p>✅ Test-Mail erfolgreich gesendet!</p><p>Grüße vom eBay-Agent.</p>"

    try:
        ok = send_mail(settings, [recipient], subject, body_html)
        if ok:
            flash(f"Test-Mail an {recipient} gesendet ✅", "success")
        else:
            flash("Fehler beim Versand (siehe Server-Log).", "warning")
    except Exception as e:
        # Ausnahme anzeigen, aber nicht sensiblen Inhalt ins UI schreiben
        flash(f"Fehler beim Versand: {str(e)}", "danger")

    return redirect(url_for("search"))





# -------------------------------------------------------------------
# Alerts: Subscribe / Send-now / Cron (HTTP-Trigger-Variante siehe unten)
# -------------------------------------------------------------------
@app.post("/alerts/subscribe")
def alerts_subscribe():
    """Speichert die aktuelle Suche als Alert (für Cron)."""
    user_email = session.get("user_email") or ""
    if not user_email or user_email.lower() == "guest" or "@" not in user_email:
        flash("Bitte einloggen, um Alarme zu speichern.", "warning")
        return redirect(url_for("login"))

    terms = [
        t
        for t in [
            (request.form.get("q1") or "").strip(),
            (request.form.get("q2") or "").strip(),
            (request.form.get("q3") or "").strip(),
        ]
        if t
    ]
    if not terms:
        flash("Keine Suchbegriffe übergeben.", "warning")
        return redirect(url_for("search"))

    filters = {
        "price_min": (request.form.get("price_min") or "").strip(),
        "price_max": (request.form.get("price_max") or "").strip(),
        "sort": (request.form.get("sort") or "best").strip(),
        "conditions": request.form.getlist("condition"),
    }
    per_page = 30
    try:
        per_page = min(100, max(5, int(request.form.get("per_page", "30"))))
    except Exception:
        pass

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO search_alerts (user_email, terms_json, filters_json, per_page, is_active, last_run_ts)
        VALUES (?, ?, ?, ?, 1, 0)
    """,
        (
            user_email,
            json.dumps(terms, ensure_ascii=False),
            json.dumps(filters, ensure_ascii=False),
            per_page,
        ),
    )
    conn.commit()
    conn.close()

    flash(
        "Alarm gespeichert. Du erhältst eine E-Mail, wenn neue Treffer gefunden werden.",
        "success",
    )
    return redirect(url_for("search", **{**request.form}))


@app.post("/alerts/send-now")
def alerts_send_now():
    """Manuell: Suche aus Formular ausführen und E-Mail an (eingeloggt) senden – mit De-Duping."""
    user_email = session.get("user_email") or request.form.get("email") or ""
    if not user_email or user_email.lower() == "guest" or "@" not in user_email:
        flash("Gültige E-Mail erforderlich (einloggen oder E-Mail angeben).", "warning")
        return redirect(url_for("search"))

    terms = [
        t
        for t in [
            (request.form.get("q1") or "").strip(),
            (request.form.get("q2") or "").strip(),
            (request.form.get("q3") or "").strip(),
        ]
        if t
    ]
    if not terms:
        flash("Keine Suchbegriffe übergeben.", "warning")
        return redirect(url_for("search"))

    filters = {
        "price_min": (request.form.get("price_min") or "").strip(),
        "price_max": (request.form.get("price_max") or "").strip(),
        "sort": (request.form.get("sort") or "best").strip(),
        "conditions": request.form.getlist("condition"),
    }

    per_page = 30
    try:
        per_page = min(100, max(5, int(request.form.get("per_page", "30"))))
    except Exception:
        pass

    items, _ = _search_with_cache(terms, filters, page=1, per_page=per_page)
    search_hash = _make_search_hash(terms, filters)

    # De-Duping gruppenweise pro src
    groups = _group_by_src(items)
    new_all: List[Dict] = []
    for src, group in groups.items():
        new_items = _mark_and_filter_new(user_email, search_hash, src, group)
        new_all.extend(new_items)

    if not new_all:
        flash(
            "Keine neuen Treffer (alles schon gemailt oder noch im Cooldown).", "info"
        )
        return redirect(url_for("search", **{**request.form}))

    subject = f"Neue Treffer für „{', '.join(terms)}“ – {len(new_all)} neu"
    html = _render_items_html(subject, new_all)
    ok = _send_email(user_email, subject, html)
    if ok:
        for src, group in groups.items():
            # markiere nur die, die wir tatsächlich geschickt haben
            sent_subset = [
                it for it in new_all if (it.get("src") or "ebay").lower() == src
            ]
            _mark_sent(user_email, search_hash, src, sent_subset)
        flash(
            f"E-Mail versendet an {user_email} mit {len(new_all)} neuen Treffern.",
            "success",
        )
    else:
        flash("E-Mail-Versand fehlgeschlagen (SMTP prüfen).", "danger")

    return redirect(url_for("search", **{**request.form}))


# Fügen Sie das NACH Zeile 1038 ein (nach den anderen alert-Routen):


@app.route("/agents/create", methods=["POST"])
def create_agent():
    """Neue Suche/Agent erstellen mit Limit-Check"""

    # Ihre Session-basierte Auth nutzen
    user_id = session.get("user_id")
    if not user_id:
        flash("Bitte einloggen.", "warning")
        return redirect(url_for("login"))

    # User aus DB holen für Limit-Check
    conn = get_db()
    cur = conn.cursor()
    user = cur.execute(
        "SELECT email, is_premium FROM users WHERE id = ?", (user_id,)
    ).fetchone()

    if not user:
        flash("User nicht gefunden.", "danger")
        return redirect(url_for("login"))

    # Aktive Agents zählen
    active_count = cur.execute(
        "SELECT COUNT(*) FROM search_alerts WHERE user_email = ? AND is_active = 1",
        (user["email"],),
    ).fetchone()[0]

    # Limit bestimmen (basierend auf is_premium)
    if user["is_premium"]:
        limit = PREMIUM_SEARCH_LIMIT  # Sie haben das schon definiert (10)
    else:
        limit = FREE_SEARCH_LIMIT  # Sie haben das schon definiert (3)

    # Limit Check
    if active_count >= limit:
        conn.close()
        flash(
            f"Limit erreicht! Sie haben bereits {active_count} aktive Suchagenten. "
            f"{'Ihr Premium-Limit ist ' + str(limit) if user['is_premium'] else 'Bitte upgraden Sie auf Premium für mehr Suchagenten.'}",
            "warning",
        )
        return redirect(url_for("public_pricing"))

    # Agent erstellen (wie in Ihrer alerts_subscribe Funktion)
    terms = [
        t
        for t in [
            request.form.get("q1", "").strip(),
            request.form.get("q2", "").strip(),
            request.form.get("q3", "").strip(),
        ]
        if t
    ]

    if not terms:
        conn.close()
        flash("Keine Suchbegriffe angegeben.", "warning")
        return redirect(url_for("search"))

    filters = {
        "price_min": request.form.get("price_min", "").strip(),
        "price_max": request.form.get("price_max", "").strip(),
        "sort": request.form.get("sort", "best").strip(),
        "conditions": request.form.getlist("condition"),
    }

    # In DB speichern
    cur.execute(
        """
        INSERT INTO search_alerts (user_email, terms_json, filters_json, per_page, is_active, last_run_ts)
        VALUES (?, ?, ?, ?, 1, 0)
        """,
        (
            user["email"],
            json.dumps(terms, ensure_ascii=False),
            json.dumps(filters, ensure_ascii=False),
            30,
        ),
    )
    conn.commit()
    conn.close()

    flash(
        f"Suchagent erfolgreich erstellt! ({active_count + 1}/{limit} verwendet)",
        "success",
    )
    return redirect(url_for("dashboard"))


# ALT/Kompatibilität (deprecated): Query-basiertes Cron-Endpoint
@app.get("/cron/run-alerts")
def cron_run_alerts():
    """ALT (deprecated). Bitte künftig den HTTP-Trigger /internal/run-agent (POST + Bearer) verwenden."""
    token = request.args.get("token", "")
    if not CRON_TOKEN or token != CRON_TOKEN:
        return abort(403)

    now = int(time.time())
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, user_email, terms_json, filters_json, per_page FROM search_alerts WHERE is_active=1"
    )
    alerts = cur.fetchall()
    conn.close()

    total_checked = 0
    total_sent = 0
    for a in alerts:
        total_checked += 1
        user_email = a["user_email"]
        try:
            terms = json.loads(a["terms_json"] or "[]")
            filters = json.loads(a["filters_json"] or "{}")
            per_page = int(a["per_page"] or 30)
        except Exception:
            continue

        items, _ = _search_with_cache(terms, filters, page=1, per_page=per_page)
        search_hash = _make_search_hash(terms, filters)

        groups = _group_by_src(items)
        new_all: List[Dict] = []
        for src, group in groups.items():
            new_items = _mark_and_filter_new(user_email, search_hash, src, group)
            new_all.extend(new_items)

        if new_all and user_email and "@" in user_email:
            subject = f"Neue Treffer für „{', '.join(terms)}“ – {len(new_all)} neu"
            html = _render_items_html(subject, new_all)
            if _send_email(user_email, subject, html):
                for src, _group in groups.items():
                    sent_subset = [
                        it for it in new_all if (it.get("src") or "ebay").lower() == src
                    ]
                    _mark_sent(user_email, search_hash, src, sent_subset)
                total_sent += 1

        # last_run_ts aktualisieren
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE search_alerts SET last_run_ts=? WHERE id=?", (now, int(a["id"]))
        )
        conn.commit()
        conn.close()

    return jsonify(
        {"ok": True, "alerts_checked": total_checked, "alerts_emailed": total_sent}
    )


@app.get("/pilot/info")
def pilot_info_page():
    base = request.url_root.rstrip("/")
    waitlist_url = base + "/pilot/waitlist"

    # Praxis-ID dynamisch aus der URL, fallback für Demo
    practice = request.args.get("practice", "DEMO-PRAXIS")

    # Interner Key aus ENV
    token = os.getenv("PRACTICE_DEMO_SECRET", "")

    # Widget-Link nur zeigen, wenn der aufrufende Link den korrekten key mitliefert
    show_widget = bool(token) and (request.args.get("key") == token)
    widget_url = None
    if show_widget:
        widget_url = f"{base}/pilot/widget?practice={practice}&key={token}"

    return render_template(
        "pilot_info.html",
        waitlist_url=waitlist_url,
        widget_url=widget_url,  # None ⇒ Button wird versteckt
        practice=practice,
        year=datetime.now().year,
    )


# -------------------------------------------------------------------
# Stripe (optional – fällt zurück, wenn nicht konfiguriert)
# -------------------------------------------------------------------
# 1) ENV laden
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_BASIC = os.getenv("STRIPE_PRICE_BASIC", "")
STRIPE_PRICE_PRO = os.getenv("STRIPE_PRICE_PRO", "")
STRIPE_PRICE_TEAM = os.getenv("STRIPE_PRICE_TEAM", "")

# 2) Stripe aktivieren (falls Key vorhanden)
STRIPE_ENABLED = bool(STRIPE_SECRET_KEY)
if STRIPE_ENABLED:
    stripe.api_key = STRIPE_SECRET_KEY

# 3) In app.config spiegeln (falls du app.config nutzt)
app.config.update(
    STRIPE_SECRET_KEY=STRIPE_SECRET_KEY,
    STRIPE_WEBHOOK_SECRET=STRIPE_WEBHOOK_SECRET,
    STRIPE_PRICE_BASIC=STRIPE_PRICE_BASIC,
    STRIPE_PRICE_PRO=STRIPE_PRICE_PRO,
    STRIPE_PRICE_TEAM=STRIPE_PRICE_TEAM,
)

# 4) Mapping Price-ID → Plan (basic|pro|team)
PRICE_TO_PLAN = {
    STRIPE_PRICE_BASIC: "basic",
    STRIPE_PRICE_PRO: "pro",
    STRIPE_PRICE_TEAM: "team",
}
# Leere Einträge entfernen
PRICE_TO_PLAN = {pid: plan for pid, plan in PRICE_TO_PLAN.items() if pid}


# 5) Webhook-Route
@app.post("/billing/stripe/webhook")
def stripe_webhook():
    # Wenn kein Secret konfiguriert ist: still ACK (kein Stripe aktiv)
    if not app.config.get("STRIPE_WEBHOOK_SECRET"):
        return "", 200

    payload = request.get_data(as_text=True)
    sig = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig,
            secret=app.config["STRIPE_WEBHOOK_SECRET"],
        )
    except stripe.error.SignatureVerificationError:
        return "Bad signature", 400
    except Exception:
        return "Invalid payload", 400

    etype = event.get("type", "")
    obj = event.get("data", {}).get("object", {}) or {}

    # --- price_id robust extrahieren (für verschiedene Event-Typen)
    def _extract_price_id(o: dict) -> str | None:
        if not isinstance(o, dict):
            return None

        # 1) checkout.session.completed (expand lines) => o["lines"]["data"][0]["price"]["id"]
        lines = o.get("lines", {}).get("data", [])
        if lines:
            price = lines[0].get("price") or {}
            if isinstance(price, dict):
                return price.get("id")

        # 2) subscription object => o["items"]["data"][0]["price"]["id"]
        items = o.get("items", {}).get("data", [])
        if items:
            price = items[0].get("price") or {}
            if isinstance(price, dict):
                return price.get("id")

        # 3) invoice.line_item (selten) => o["price"]["id"]
        price = o.get("price")
        if isinstance(price, dict):
            return price.get("id")

        return None

    price_id = _extract_price_id(obj)
    plan = PRICE_TO_PLAN.get(price_id)

    # --- User identifizieren
    from models import User, db  # db = SQLAlchemy Session

    user_id = obj.get("client_reference_id") or obj.get("metadata", {}).get("user_id")
    customer_email = (obj.get("customer_details", {}) or {}).get("email") or obj.get(
        "customer_email"
    )

    user = None
    if user_id:
        try:
            user = User.query.get(int(user_id))
        except Exception:
            user = None
    if not user and customer_email:
        user = User.query.filter_by(email=customer_email).first()

    if not user:
        # unbekannter Kunde – still ACK, damit Stripe nicht retried
        return "", 200

    # --- Statuswechsel
    if etype in (
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
    ):
        if plan and getattr(user, "plan", None) != plan:
            user.plan = plan
            db.session.commit()

    elif etype in ("customer.subscription.deleted", "customer.subscription.canceled"):
        if getattr(user, "plan", None) != "free":
            user.plan = "free"
            db.session.commit()

    return "", 200


@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    # 1) Stripe verfügbar?
    if not STRIPE_OK or not STRIPE_SECRET_KEY:
        flash("Stripe ist nicht konfiguriert.", "warning")
        return redirect(url_for("public_pricing"))

    # 2) Plan/Preis aus Form oder Query lesen (basic|pro|team ODER direkte price_... ID)
    plan = (
        request.form.get("price")
        or request.args.get("price")
        or request.values.get("price_id")
        or "pro"
    ).strip()  # Default: pro

    stripe_prices = app.config.get(
        "STRIPE_PRICE", {}
    )  # {"basic": "...", "pro": "...", "team": "..."}
    price_id = stripe_prices.get(
        plan, plan
    )  # wenn 'plan' schon eine price_... ID ist, bleibt sie so

    if not price_id:
        flash("Ungültiger Plan/Preis.", "warning")
        return redirect(url_for("public_pricing"))

    # 3) URLs & Kundendaten
    success_url = url_for("checkout_success", _external=True)
    cancel_url = url_for("checkout_cancel", _external=True)

    client_ref = str(
        session.get("user_id") or ""
    )  # <— hier war bei dir ein extra Anführungszeichen am Ende
    user_email = (session.get("user_email") or "").strip()
    if user_email.lower() == "guest" or "@" not in user_email:
        user_email = None

    # 4) Checkout-Session anlegen
    try:
        session_stripe = stripe.checkout.Session.create(  # type: ignore
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            allow_promotion_codes=True,
            client_reference_id=client_ref or None,
            customer_email=user_email or None,
            metadata={
                "user_id": session.get("user_id"),
                "plan": plan,
            },  # nützlich für Webhook
        )
        return redirect(session_stripe.url, code=303)

    except Exception as e:
        flash(f"Stripe-Fehler: {e}", "danger")
        return redirect(url_for("public_pricing"))


@app.route("/billing/portal")
def billing_portal():
    flash("Abo-Verwaltung ist demnächst verfügbar.", "info")
    return redirect(url_for("public_pricing"))


@app.route("/checkout/success")
def checkout_success():
    session["is_premium"] = True
    flash("Dein Premium-Zugang ist jetzt freigeschaltet.", "success")
    return safe_render("success.html", title="Erfolg")


@app.route("/checkout/cancel")
def checkout_cancel():
    flash("Vorgang abgebrochen.", "info")
    return redirect(url_for("public_pricing"))


# -------------------------------------------------------------------
# Debug / Health
# -------------------------------------------------------------------
@app.route("/_debug/ebay")
def debug_ebay():
    return jsonify(
        {
            "configured": bool(EBAY_CLIENT_ID and EBAY_CLIENT_SECRET),
            "marketplace": EBAY_MARKETPLACE_ID,
            "currency": EBAY_CURRENCY,
            "token_cached": bool(_EBAY_TOKEN["access_token"]),
            "token_valid_for_s": max(
                0, int(float(_EBAY_TOKEN.get("expires_at", 0)) - time.time())
            ),
            "live_search": LIVE_SEARCH,
        }
    )


@app.route("/_debug/amazon")
def debug_amazon():
    return jsonify(
        {
            "amz_enabled": AMZ_ENABLED,
            "amz_ok": AMZ_OK,
            "country": AMZ_COUNTRY,
            "has_keys": bool(AMZ_ACCESS and AMZ_SECRET and AMZ_TAG),
        }
    )


@app.route("/debug")
def debug_env():
    user_email = session.get("user_email") or ""
    if not user_email and session.get("user_id"):
        conn = get_db()
        row = conn.execute(
            "SELECT email FROM users WHERE id=?", (session["user_id"],)
        ).fetchone()
        conn.close()
        if row and row["email"]:
            user_email = row["email"]

    data = {
        "env": {
            "DB_PATH": DB_URL,
            "FREE_SEARCH_LIMIT": FREE_SEARCH_LIMIT,
            "PREMIUM_SEARCH_LIMIT": PREMIUM_SEARCH_LIMIT,
            "LIVE_SEARCH": "1" if LIVE_SEARCH else "0",
            "EBAY_CLIENT_ID_set": bool(EBAY_CLIENT_ID),
            "EBAY_CLIENT_SECRET_set": bool(EBAY_CLIENT_SECRET),
            "EBAY_SCOPES": EBAY_SCOPES,
            "EBAY_GLOBAL_ID": EBAY_GLOBAL_ID,
            "STRIPE_PRICE_PRO_set": bool(STRIPE_PRICE_PRO),
            "STRIPE_SECRET_KEY_set": bool(STRIPE_SECRET_KEY),
            "STRIPE_WEBHOOK_SECRET_set": bool(STRIPE_WEBHOOK_SECRET),
            "AMZ_ENABLED": AMZ_ENABLED,
            "AMZ_ACCESS_KEY_set": bool(AMZ_ACCESS),
            "AMZ_SECRET_set": bool(AMZ_SECRET),
            "AMZ_TAG_set": bool(AMZ_TAG),
            "AMZ_COUNTRY": AMZ_COUNTRY,
            "PLAUSIBLE_DOMAIN": PLAUSIBLE_DOMAIN,
        },
        "session": {
            "free_search_count": int(session.get("free_search_count", 0)),
            "is_premium": bool(session.get("is_premium", False)),
            "user_email": user_email,
            "utm": session.get("utm") or {},
        },
    }
    return jsonify(data)


@app.route("/healthz")
def healthz():
    return "ok", 200


# (Optional) Amazon Direkt-Suche
@app.route("/amazon/search")
def amazon_search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return safe_render(
            "search.html", title="Amazon-Suche", body="Bitte Suchbegriff angeben."
        )
    if not AMZ_OK:
        flash("Amazon ist nicht konfiguriert.", "info")
        return redirect(url_for("public_home"))

    page = 1
    try:
        page = max(1, int(request.args.get("page", 1)))
    except Exception:
        pass

    items, _ = amazon_search_one(q, limit=20, page=page)

    return safe_render(
        "search_results.html",
        title=f"Amazon-Ergebnisse für „{q}“",
        terms=[q],
        results=items,
        filters={"price_min": "", "price_max": "", "sort": "best", "conditions": []},
        pagination={
            "page": 1,
            "per_page": len(items),
            "total_estimated": len(items),
            "total_pages": 1,
            "has_prev": False,
            "has_next": False,
        },
        base_qs={"q1": q, "per_page": len(items)},
    )


@app.route("/robots.txt")
def robots_txt():
    body = f"User-agent: *\nAllow: /\nSitemap: {request.url_root.rstrip('/')}/sitemap.xml\n"
    return app.response_class(body, mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    from datetime import date

    # Liste deiner öffentlichen Seiten (nur vorhandene Endpoints eintragen)
    endpoints = [
        "public_home",
        "public_pricing",
        "public_imprint",
        "public_privacy",
    ]
    urls = []
    for ep in endpoints:
        try:
            urls.append(url_for(ep, _external=True))
        except Exception:
            pass  # Endpoint existiert (noch) nicht – einfach überspringen

    today = date.today().isoformat()
    xml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    xml += [f"<url><loc>{u}</loc><lastmod>{today}</lastmod></url>" for u in urls]
    xml.append("</urlset>")

    return app.response_class("\n".join(xml), mimetype="application/xml")


@app.after_request
def add_security_and_cache_headers(resp):
    # Security
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    resp.headers["X-Frame-Options"] = "DENY"

    # Einfaches Caching für statische Assets
    mt = resp.mimetype or ""
    if any(x in mt for x in ["image/", "font/", "javascript", "css"]):
        resp.headers["Cache-Control"] = "public, max-age=2592000"  # 30 Tage
    return resp


# -------------------------------------------------------------------
# PRIVATER Cron-Trigger (neu, empfohlen): /internal/run-agent  (POST + Bearer)
# -------------------------------------------------------------------
# Lock laden (mit sicherem Fallback, falls lock.py fehlt)
try:
    from lock import agent_lock  # Datei-Lock über Prozesse/Worker
except Exception:
    from contextlib import contextmanager
    from threading import Lock as _TLock

    _fallback_lock = _TLock()

    @contextmanager
    def agent_lock(timeout: int = 110):
        ok = _fallback_lock.acquire(timeout=timeout if timeout else None)
        try:
            yield
        finally:
            if ok:
                _fallback_lock.release()


internal_bp = Blueprint("internal", __name__)


def require_agent_token():
    token = request.headers.get("Authorization", "")
    if token.startswith("Bearer "):
        token = token[7:]
    env_tok = os.getenv("AGENT_TRIGGER_TOKEN", "")
    if token != os.getenv("AGENT_TRIGGER_TOKEN", ""):
        abort(401)


@internal_bp.route("/mail-test", methods=["GET"])
def internal_mail_test():
    # oben in der Datei muss stehen: from mailer import send_mail

    to = request.args.get("to", "").strip()
    if not to:
        return jsonify({"ok": False, "error": "missing 'to'"}), 400

    try:
        send_mail(
            to=to,
            subject="Test vom ebay-agent-cockpit",
            text="? Mail-Setup ok. (Staging)",
        )
        return jsonify({"ok": True, "to": to}), 200
    except Exception as e:
        current_app.logger.exception("mail test failed")
        return jsonify({"ok": False, "error": str(e)}), 500


@internal_bp.route("/run-agent", methods=["POST"])
def internal_run_agent():
    # Token prüfen (kleiner Helper – siehe unten)
    require_agent_token()

    with agent_lock():  # <- das hast du schon
        try:
            from agent import run_agent_once
        except Exception as e:
            current_app.logger.exception("agent import failed")
            return jsonify({"status": "error", "error": "agent_import_failed"}), 500

        try:
            run_agent_once()
        except Exception as e:
            current_app.logger.exception("agent run failed")
            return jsonify({"status": "error", "error": "agent_run_failed"}), 500

    return jsonify({"ok": True}), 200


# ========= INTERN: Helfer für Alerts / DB-Inspektion =========


def _detect_alerts_table(conn):
    """
    Sucht eine Tabelle mit einer 'email'-Spalte und einer Aktiv-Spalte ('active' oder 'is_active').
    Gibt (table_name, email_col, active_col, id_col) zurück oder (None, ...), falls nicht gefunden.
    """
    cur = conn.cursor()
    # alle Tabellen
    rows = cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    tables = [r[0] for r in rows]
    for t in tables:
        cols = cur.execute(
            f"PRAGMA table_info({t})"
        ).fetchall()  # cid, name, type, notnull, dflt, pk
        names = {c[1].lower(): c for c in cols}
        # Pflicht: email + irgendeine Aktiv-Spalte
        if "email" in names and ("active" in names or "is_active" in names):
            email_col = "email"
            active_col = "active" if "active" in names else "is_active"
            # ID-Spalte heuristisch
            id_col = (
                "id"
                if "id" in names
                else ("alert_id" if "alert_id" in names else list(names.keys())[0])
            )
            return t, email_col, active_col, id_col
    return None, None, None, None


@internal_bp.route("/db-info", methods=["GET"])
def internal_db_info():
    """Zeigt Tabellen + vermutete Alerts-Tabelle/Spalten – zum Nachsehen im Browser."""
    require_agent_token()  # denselben Token-Check nutzen wie bei deinen anderen /internal-Routen
    conn = get_db()
    cur = conn.cursor()
    tables = cur.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    found = _detect_alerts_table(conn)
    data = {
        "tables": [{"name": n, "create_sql": s} for (n, s) in tables],
        "alerts_detection": {
            "table": found[0],
            "email_col": found[1],
            "active_col": found[2],
            "id_col": found[3],
        },
    }
    from flask import jsonify

    return jsonify(data), 200


@internal_bp.route("/alerts/disable-all", methods=["POST"])
def internal_alerts_disable_all():
    """Setzt alle Alarme für eine E-Mail auf inaktiv."""
    require_agent_token()
    email = request.form.get("email", "").strip().lower()
    if not email:
        return ("missing email", 400)

    conn = get_db()
    table, email_col, active_col, _ = _detect_alerts_table(conn)
    if not table:
        return ("could not detect alerts table", 500)

    cur = conn.cursor()
    cur.execute(
        f"UPDATE {table} SET {active_col}=0 WHERE lower({email_col})=?", (email,)
    )
    conn.commit()
    return {"ok": True, "email": email, "updated": cur.rowcount}, 200


@internal_bp.route("/my-alerts", methods=["GET"])
def internal_my_alerts():
    """
    Mini-Übersicht + Toggle. Aufruf: /internal/my-alerts?email=dein@postfach.de
    """
    require_agent_token()
    email = request.args.get("email", "").strip().lower()
    if not email:
        return ("missing ?email=...", 400)

    conn = get_db()
    table, email_col, active_col, id_col = _detect_alerts_table(conn)
    if not table:
        return ("could not detect alerts table", 500)

    cur = conn.cursor()
    rows = cur.execute(
        f"SELECT {id_col} AS id, {email_col} AS email, {active_col} AS active, * FROM {table} WHERE lower({email_col})=? ORDER BY {id_col} DESC",
        (email,),
    ).fetchall()

    # ganz einfacher HTML-Renderer, kein extra Template nötig
    html = ["<h1>Meine Alarme</h1>"]
    html.append(f"<p>Email: <b>{email}</b></p>")
    if not rows:
        html.append("<p>Keine Alarme gefunden.</p>")
    else:
        html.append(
            "<table border=1 cellpadding=6><tr><th>ID</th><th>Aktiv</th><th>Aktion</th></tr>"
        )
        for r in rows:
            rid = r["id"] if isinstance(r, dict) else r[0]
            is_active = r["active"] if isinstance(r, dict) else r[2]
            label = "deaktivieren" if is_active else "aktivieren"
            new_val = 0 if is_active else 1
            html.append(
                f"<tr><td>{rid}</td>"
                f"<td>{'✅ aktiv' if is_active else '⛔ inaktiv'}</td>"
                f"<td>"
                f"<form method='post' action='/internal/alerts/toggle' style='margin:0;'>"
                f"<input type='hidden' name='id' value='{rid}'/>"
                f"<input type='hidden' name='active' value='{new_val}'/>"
                f"<input type='hidden' name='email' value='{email}'/>"
                f"<button type='submit'>{label}</button>"
                f"</form>"
                f"</td></tr>"
            )
        html.append("</table>")
        html.append(
            "<p style='margin-top:12px'>Tipp: <form method='post' action='/internal/alerts/disable-all' style='display:inline;'>"
            f"<input type='hidden' name='email' value='{email}'/>"
            "<button>Alle für diese E-Mail deaktivieren</button></form></p>"
        )
    return "\n".join(html), 200


@internal_bp.route("/alerts/toggle", methods=["POST"])
def internal_alerts_toggle():
    """Aktiv-Flag eines Alerts umschalten (von der Tabelle oben aus)."""
    require_agent_token()
    rid = request.form.get("id", "").strip()
    target = request.form.get("active", "").strip()
    email = request.form.get("email", "").strip().lower()

    if not rid or target not in ("0", "1"):
        return ("bad request", 400)

    conn = get_db()
    table, email_col, active_col, id_col = _detect_alerts_table(conn)
    if not table:
        return ("could not detect alerts table", 500)

    cur = conn.cursor()
    cur.execute(
        f"UPDATE {table} SET {active_col}=? WHERE {id_col}=?", (int(target), rid)
    )
    conn.commit()
    # wieder zurück zur Liste für diese E-Mail
    return redirect(f"/internal/my-alerts?email={email}")


@app.route("/_routes")
def _routes():
    return {"routes": [str(r) for r in app.url_map.iter_rules()]}


def require_agent_token():
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        auth = auth[7:]
    if auth != os.getenv("AGENT_TRIGGER_TOKEN", ""):
        abort(401)


# Registrierung des internen Blueprints (jetzt, wo er existiert)

app.register_blueprint(internal_bp, url_prefix="/internal")


@app.route("/public/vision-test")
def vision_test_quick():
    from utils.vision_openai import scan_openai

    urls = request.args.getlist("img")
    if not urls:
        return jsonify(error="usage: /public/vision-test?img=<url>"), 400

    try:
        result = scan_openai(urls, max_images=2)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e), "verdict": "error"}), 500


# -------------------------------------------------------------------
# Run (nur lokal)
# -------------------------------------------------------------------

# ======= DEMO BLOCK: Storno-Radar (Begin) =======
import os
from datetime import datetime

from flask import abort, jsonify, render_template_string, request

# nutzt deine existierende send_mail-Funktion:
from mailer import send_mail

# Schalter (kannst du per ENV steuern)
DEMO_ENABLED = os.getenv("DEMO_ENABLED", "1") == "1"
PRACTICE_DEMO_SECRET = os.getenv("PRACTICE_DEMO_SECRET", "")  # optionaler Key

# In-Memory Speicher (nur für Demo)
DEMO_WAITLIST = []  # [{email, fach, plz, fenster, created}]
DEMO_SLOTS = []  # [{fach, until, link, created}]


def _demo_guard():
    if not DEMO_ENABLED:
        abort(404)


# --- Warteliste (Patient) ---
@app.get("/pilot/waitlist")
def pilot_waitlist_form():
    _demo_guard()
    html = """
    <div style="font-family:sans-serif;max-width:520px;margin:24px auto">
      <h2>Warteliste – Schnelltest</h2>
      <form method="post" action="/pilot/waitlist">
        <label>E-Mail:</label><br><input name="email" required style="width:100%"><br>
        <label>Fachgebiet:</label><br>
          <select name="fach" style="width:100%">
            <option>Orthopädie</option><option>Dermatologie</option><option>HNO</option>
          </select><br>
        <label>PLZ (optional):</label><br><input name="plz" style="width:100%"><br>
        <label>Zeitfenster (z. B. Mo–Fr 8–12):</label><br><input name="fenster" style="width:100%"><br><br>
        <button type="submit">Auf Warteliste</button>
      </form>
      <p style="margin-top:1rem"><a href="/pilot/widget">→ Praxis-Widget öffnen</a></p>
    </div>
    """
    return render_template_string(html)


@app.post("/pilot/waitlist")
def pilot_waitlist_save():
    _demo_guard()
    DEMO_WAITLIST.append(
        {
            "email": request.form.get("email", "").strip(),
            "fach": request.form.get("fach", "").strip(),
            "plz": request.form.get("plz", "").strip(),
            "fenster": request.form.get("fenster", "").strip(),
            "created": datetime.utcnow().isoformat(),
        }
    )
    return "<p>✅ Eingetragen! <a href='/pilot/waitlist'>Zurück</a> • <a href='/pilot/widget'>Praxis-Widget</a></p>"


# --- Praxis-Widget (Slot freigeben) ---
@app.get("/pilot/widget")
def pilot_widget_form():
    _demo_guard()
    if PRACTICE_DEMO_SECRET and request.args.get("key") != PRACTICE_DEMO_SECRET:
        return "401 demo key missing/invalid", 401
    html = """
    <div style="font-family:sans-serif;max-width:520px;margin:24px auto">
      <h2>Praxis-Widget – Slot freigeben</h2>
      <form method="post" action="/pilot/widget{qs}">
        <label>Fachgebiet:</label><br>
          <select name="fach" style="width:100%">
            <option>Orthopädie</option><option>Dermatologie</option><option>HNO</option>
          </select><br>
        <label>Slot frei bis (HH:MM):</label><br><input name="until" placeholder="15:30" required style="width:100%"><br>
        <label>Buchungslink (116117 / Praxis-Web / Tel-Hinweis):</label><br>
          <input name="link" placeholder="https://www.116117.de/..." style="width:100%"><br><br>
        <button type="submit">Slot freigeben & Benachrichtigen</button>
      </form>
      <p style="margin-top:1rem"><a href="/pilot/waitlist">→ Warteliste</a></p>
    </div>
    """.format(
        qs=("?key=" + PRACTICE_DEMO_SECRET) if PRACTICE_DEMO_SECRET else ""
    )
    return render_template_string(html)


@app.post("/pilot/widget")
def pilot_widget_free():
    _demo_guard()
    if PRACTICE_DEMO_SECRET and request.args.get("key") != PRACTICE_DEMO_SECRET:
        return "401 demo key missing/invalid", 401

    fach = request.form.get("fach", "").strip()
    until = request.form.get("until", "").strip()
    link = request.form.get("link", "").strip() or "(Telefon: 01234/56789)"

    DEMO_SLOTS.append(
        {
            "fach": fach,
            "until": until,
            "link": link,
            "created": datetime.utcnow().isoformat(),
        }
    )

    # einfache Filterlogik: nur Fachgebiet matchen
    matches = [w for w in DEMO_WAITLIST if w["fach"] == fach]
    sent = 0
    for w in matches[:20]:  # Sicherheitslimit
        try:
            addr = w["email"]
            send_mail_pilot(
                to=addr,
                subject=f"Freier Termin ({fach}) bis {until}",
                text=(
                    f"Hallo,\n\n"
                    f"in {fach} ist kurzfristig ein Termin frei – gültig bis {until}.\n\n"
                    f"Buchen/Info: {link}\n"
                ),
                # optional: separater Message-Stream für Pilot
                stream=os.getenv("PILOT_MESSAGE_STREAM"),
                # optional: Reply-To
                reply_to=os.getenv("PILOT_SENDER_EMAIL"),
            )
            sent += 1
        except Exception:
            current_app.logger.exception("pilot mail failed")

    qs = f"?key={PRACTICE_DEMO_SECRET}" if PRACTICE_DEMO_SECRET else ""
    return (
        f"<p>✅ Slot freigegeben ({fach}) bis {until}. "
        f"Benachrichtigungen verschickt: {sent}. "
        f"<a href='/pilot/widget{qs}'>Zurück</a></p>"
    )


# ======= DEMO BLOCK: Storno-Radar (End) =======

# ========== ADMIN PANEL ==========


@app.route("/admin")
def admin_login_form():
    """Admin Login Seite"""
    if session.get("is_admin"):
        return redirect("/admin/dashboard")

    return """
    <div style="max-width:400px;margin:50px auto;font-family:Arial">
        <h2>Admin Login</h2>
        <form method="post" action="/admin/login">
            <div style="margin:15px 0">
                <label>Username:</label><br>
                <input type="text" name="username" required style="width:100%;padding:8px">
            </div>
            <div style="margin:15px 0">
                <label>Password:</label><br>
                <input type="password" name="password" required style="width:100%;padding:8px">
            </div>
            <button type="submit" style="background:#007cba;color:white;padding:10px 20px;border:none;border-radius:4px">
                Login
            </button>
        </form>
    </div>
    """


@app.route("/admin/login", methods=["POST"])
def admin_login():
    """Admin Login verarbeiten"""
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    # Einfache Admin-Credentials (ändern Sie diese!)
    ADMIN_USER = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "change-me-123")

    if username == ADMIN_USER and password == ADMIN_PASS:
        session["is_admin"] = True
        return redirect("/admin/dashboard")
    else:
        return 'Falscher Username oder Password. <a href="/admin">Zurück</a>'


@app.route("/admin/logout")
def admin_logout():
    """Admin Logout"""
    session.pop("is_admin", None)
    return redirect("/admin")


@app.route("/admin/dashboard")
def admin_dashboard():
    """Admin Dashboard"""
    if not session.get("is_admin"):
        return redirect("/admin")

    # Statistiken aus der Datenbank holen
    conn = get_db()
    cur = conn.cursor()

    user_count = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    alert_count = cur.execute(
        "SELECT COUNT(*) FROM search_alerts WHERE is_active=1"
    ).fetchone()[0]
    total_alerts = cur.execute("SELECT COUNT(*) FROM search_alerts").fetchone()[0]

    conn.close()

    return f"""
    <div style="font-family:Arial;max-width:1000px;margin:20px auto;padding:20px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:30px">
            <h1>Admin Dashboard</h1>
            <a href="/admin/logout" style="color:#dc3545">Logout</a>
        </div>

        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin-bottom:40px">
            <div style="background:#f8f9fa;padding:20px;border-radius:8px;text-align:center">
                <h3 style="margin:0;color:#28a745">{user_count}</h3>
                <p style="margin:5px 0 0 0">Benutzer</p>
            </div>
            <div style="background:#f8f9fa;padding:20px;border-radius:8px;text-align:center">
                <h3 style="margin:0;color:#007cba">{alert_count}</h3>
                <p style="margin:5px 0 0 0">Aktive Alerts</p>
            </div>
            <div style="background:#f8f9fa;padding:20px;border-radius:8px;text-align:center">
                <h3 style="margin:0;color:#6c757d">{total_alerts}</h3>
                <p style="margin:5px 0 0 0">Alerts gesamt</p>
            </div>
        </div>

        <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:30px">
            <div>
                <h3>Benutzerverwaltung</h3>
                <a href="/admin/users" style="background:#007cba;color:white;padding:10px 20px;text-decoration:none;border-radius:4px;display:inline-block">
                    Benutzer verwalten
                </a>
            </div>
            <div>
                <h3>Alert-Verwaltung</h3>
                <a href="/admin/alerts" style="background:#28a745;color:white;padding:10px 20px;text-decoration:none;border-radius:4px;display:inline-block">
                    Alerts verwalten
                </a>
            </div>
        </div>

        <div style="margin-top:40px">
            <h3>Bounce-Management</h3>
            <a href="/admin/bounces" style="background:#dc3545;color:white;padding:10px 20px;text-decoration:none;border-radius:4px;display:inline-block">
                Gebounce E-Mails verwalten
            </a>
        </div>
    </div>
    """


@app.route("/admin/users")
def admin_users():
    """Benutzerverwaltung"""
    if not session.get("is_admin"):
        return redirect("/admin")

    conn = get_db()
    cur = conn.cursor()
    users = cur.execute(
        "SELECT id, email, password, is_premium FROM users ORDER BY id DESC"
    ).fetchall()
    conn.close()

    user_rows = ""
    for user in users:
        premium_badge = "🌟 Premium" if user[3] else "🆓 Free"
        user_rows += f"""
        <tr>
            <td>{user[0]}</td>
            <td>{user[1]}</td>
            <td>{premium_badge}</td>
            <td>
                <a href="/admin/user/{user[0]}/alerts" style="margin-right:10px">Alerts</a>
                <a href="/admin/user/{user[0]}/delete" onclick="return confirm('Wirklich löschen?')" style="color:red">Löschen</a>
            </td>
        </tr>
        """

    return f"""
    <div style="font-family:Arial;max-width:1000px;margin:20px auto;padding:20px">
        <div style="margin-bottom:20px">
            <a href="/admin/dashboard">← Zurück zum Dashboard</a>
        </div>

        <h2>Benutzerverwaltung</h2>
        <table style="width:100%;border-collapse:collapse;margin-top:20px">
            <tr style="background:#f8f9fa">
                <th style="padding:12px;text-align:left;border:1px solid #ddd">ID</th>
                <th style="padding:12px;text-align:left;border:1px solid #ddd">E-Mail</th>
                <th style="padding:12px;text-align:left;border:1px solid #ddd">Status</th>
                <th style="padding:12px;text-align:left;border:1px solid #ddd">Aktionen</th>
            </tr>
            {user_rows}
        </table>
    </div>
    """


@app.route("/admin/alerts")
def admin_alerts():
    """Alert-Verwaltung"""
    if not session.get("is_admin"):
        return redirect("/admin")

    conn = get_db()
    cur = conn.cursor()
    alerts = cur.execute(
        """
        SELECT id, user_email, terms_json, is_active, last_run_ts
        FROM search_alerts
        ORDER BY id DESC
        LIMIT 50
    """
    ).fetchall()
    conn.close()

    alert_rows = ""
    for alert in alerts:
        try:
            terms = json.loads(alert[2])
            terms_text = ", ".join(terms[:3])  # Erste 3 Begriffe
        except:
            terms_text = "Fehlerhafte Daten"

        status = "🟢 Aktiv" if alert[3] else "🔴 Inaktiv"
        last_run = "Nie" if alert[4] == 0 else f"Zuletzt: {alert[4]}"

        alert_rows += f"""
        <tr>
            <td style="padding:8px;border:1px solid #ddd">{alert[0]}</td>
            <td style="padding:8px;border:1px solid #ddd">{alert[1]}</td>
            <td style="padding:8px;border:1px solid #ddd">{terms_text}</td>
            <td style="padding:8px;border:1px solid #ddd">{status}</td>
            <td style="padding:8px;border:1px solid #ddd">
                <a href="/admin/alert/{alert[0]}/toggle">Toggle</a> |
                <a href="/admin/alert/{alert[0]}/delete" style="color:red">Löschen</a>
            </td>
        </tr>
        """

    return f"""
    <div style="font-family:Arial;max-width:1200px;margin:20px auto;padding:20px">
        <div style="margin-bottom:20px">
            <a href="/admin/dashboard">← Zurück zum Dashboard</a>
        </div>

        <h2>Alert-Verwaltung</h2>
        <table style="width:100%;border-collapse:collapse;margin-top:20px">
            <tr style="background:#f8f9fa">
                <th style="padding:12px;text-align:left;border:1px solid #ddd">ID</th>
                <th style="padding:12px;text-align:left;border:1px solid #ddd">E-Mail</th>
                <th style="padding:12px;text-align:left;border:1px solid #ddd">Suchbegriffe</th>
                <th style="padding:12px;text-align:left;border:1px solid #ddd">Status</th>
                <th style="padding:12px;text-align:left;border:1px solid #ddd">Aktionen</th>
            </tr>
            {alert_rows}
        </table>
    </div>
    """


@app.route("/admin/alert/<int:alert_id>/toggle")
def admin_toggle_alert(alert_id):
    """Alert aktivieren/deaktivieren"""
    if not session.get("is_admin"):
        return redirect("/admin")

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE search_alerts SET is_active = 1 - is_active WHERE id = ?", (alert_id,)
    )
    conn.commit()
    conn.close()

    return redirect("/admin/alerts")


@app.route("/admin/alert/<int:alert_id>/delete")
def admin_delete_alert(alert_id):
    """Alert löschen"""
    if not session.get("is_admin"):
        return redirect("/admin")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM search_alerts WHERE id = ?", (alert_id,))
    cur.execute(
        "DELETE FROM alert_seen WHERE search_hash IN (SELECT search_hash FROM search_alerts WHERE id = ?)",
        (alert_id,),
    )
    conn.commit()
    conn.close()

    return redirect("/admin/alerts")


@app.route("/admin/bounces")
def admin_bounces():
    """Bounce-Management"""
    if not session.get("is_admin"):
        return redirect("/admin")

    # Bounce-Liste laden
    from mailer import get_bounce_stats

    stats = get_bounce_stats()

    bounce_rows = ""
    for email in stats["bounced_emails"]:
        bounce_rows += f"""
        <tr>
            <td style="padding:8px;border:1px solid #ddd">{email}</td>
            <td style="padding:8px;border:1px solid #ddd">
                <a href="/admin/bounce/{email}/remove" style="color:green">Entfernen</a>
            </td>
        </tr>
        """

    return f"""
    <div style="font-family:Arial;max-width:800px;margin:20px auto;padding:20px">
        <div style="margin-bottom:20px">
            <a href="/admin/dashboard">← Zurück zum Dashboard</a>
        </div>

        <h2>Bounce-Management</h2>
        <p>Gesamt: {stats['total_bounced']} gebounce E-Mail-Adressen</p>

        <div style="margin:20px 0">
            <a href="/admin/bounces/clear"
               onclick="return confirm('Alle Bounces löschen?')"
               style="background:#dc3545;color:white;padding:10px 20px;text-decoration:none;border-radius:4px">
                Alle Bounces löschen
            </a>
        </div>

        <table style="width:100%;border-collapse:collapse;margin-top:20px">
            <tr style="background:#f8f9fa">
                <th style="padding:12px;text-align:left;border:1px solid #ddd">E-Mail-Adresse</th>
                <th style="padding:12px;text-align:left;border:1px solid #ddd">Aktion</th>
            </tr>
            {bounce_rows}
        </table>
    </div>
    """


@app.route("/admin/bounces/clear")
def admin_clear_bounces():
    """Alle Bounces löschen"""
    if not session.get("is_admin"):
        return redirect("/admin")

    from mailer import clear_bounce_list

    clear_bounce_list()

    return redirect("/admin/bounces")

# ============================================================================
# TELEGRAM ROUTES
# ============================================================================

@app.route("/telegram/settings")
def telegram_settings():
    """Zeigt Telegram-Einstellungen"""
    if not session.get("user_id"):
        flash("Bitte einloggen.", "info")
        return redirect(url_for("login"))

    user_email = session.get("user_email")
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            telegram_chat_id,
            telegram_enabled,
            telegram_verified,
            telegram_username
        FROM users
        WHERE email = ?
    """, (user_email,))

    user_row = cur.fetchone()
    conn.close()

    if user_row:
        user = dict(user_row)
    else:
        user = {
            "telegram_chat_id": None,
            "telegram_enabled": False,
            "telegram_verified": False,
            "telegram_username": None
        }

    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "")

    return safe_render(
        "telegram_settings.html",
        user=user,
        bot_configured=bool(TELEGRAM_BOT_TOKEN),
        bot_username=TELEGRAM_BOT_USERNAME
    )


@app.route("/telegram/connect", methods=["POST"])
def telegram_connect():
    """Startet Telegram-Verbindungsprozess"""
    if not session.get("user_id"):
        return jsonify({"success": False, "error": "Not logged in"}), 401

    user_email = session.get("user_email")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "")

    if not TELEGRAM_BOT_TOKEN:
        return jsonify({
            "success": False,
            "error": "Telegram Bot nicht konfiguriert"
        }), 500

    # Deep Link zu Telegram Bot
    deep_link = f"https://t.me/{TELEGRAM_BOT_USERNAME}?start={user_email.replace('@', '_at_')}"

    print(f"[Telegram] Deep Link erstellt: {deep_link}")

    return jsonify({
        "success": True,
        "deep_link": deep_link,
        "message": "Bitte klicke in Telegram auf 'Start'"
    })


@app.route("/telegram/verify", methods=["POST"])
def telegram_verify():
    """Wird vom Telegram Bot aufgerufen wenn User /start klickt"""
    # Token-Check
    token = request.headers.get("Authorization", "").replace("Bearer ", "")

    if token != AGENT_TRIGGER_TOKEN:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    data = request.get_json()
    chat_id = data.get("chat_id")
    username = data.get("username")
    user_email = data.get("user_email")

    if not all([chat_id, user_email]):
        return jsonify({"success": False, "error": "Missing data"}), 400

    conn = get_db()
    cur = conn.cursor()

    try:
        # User-Email dekodieren
        user_email = user_email.replace("_at_", "@")

        # Telegram-Daten setzen
        cur.execute("""
            UPDATE users
            SET telegram_chat_id = ?,
                telegram_username = ?,
                telegram_enabled = 1,
                telegram_verified = 1
            WHERE email = ?
        """, (str(chat_id), username, user_email))

        if cur.rowcount == 0:
            conn.close()
            return jsonify({"success": False, "error": "User not found"}), 404

        conn.commit()
        conn.close()

        # Willkommensnachricht senden
        from telegram_bot import send_welcome_notification
        send_welcome_notification(str(chat_id), username or "User")

        print(f"[Telegram] ✅ User {user_email} verknüpft mit Chat-ID {chat_id}")

        return jsonify({
            "success": True,
            "message": "User erfolgreich verknüpft"
        })

    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"[Telegram] ❌ Fehler: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/telegram/toggle", methods=["POST"])
def telegram_toggle():
    """Aktiviert/Deaktiviert Telegram-Benachrichtigungen"""
    if not session.get("user_id"):
        return jsonify({"success": False, "error": "Not logged in"}), 401

    user_email = session.get("user_email")
    data = request.get_json()
    enabled = data.get("enabled", False)

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET telegram_enabled = ?
        WHERE email = ?
    """, (1 if enabled else 0, user_email))

    conn.commit()
    conn.close()

    status = "aktiviert" if enabled else "deaktiviert"
    print(f"[Telegram] User {user_email}: Benachrichtigungen {status}")

    return jsonify({
        "success": True,
        "message": f"Telegram-Alerts {status}"
    })


@app.route("/telegram/test", methods=["POST"])
def telegram_test():
    """Sendet Test-Benachrichtigung"""
    if not session.get("user_id"):
        return jsonify({"success": False, "error": "Not logged in"}), 401

    user_email = session.get("user_email")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT telegram_chat_id, telegram_enabled, telegram_verified
        FROM users
        WHERE email = ?
    """, (user_email,))

    user_row = cur.fetchone()
    conn.close()

    if not user_row:
        return jsonify({"success": False, "message": "User nicht gefunden"}), 404

    user = dict(user_row)

    if not user["telegram_verified"]:
        return jsonify({"success": False, "message": "Telegram nicht verbunden"}), 400

    if not user["telegram_enabled"]:
        return jsonify({"success": False, "message": "Telegram-Alerts sind deaktiviert"}), 400

    # Test-Nachricht senden
    from telegram_bot import TelegramBot
    bot = TelegramBot()

    message = """
🧪 <b>Test-Benachrichtigung</b>

Dein Telegram ist korrekt konfiguriert! ✅

Du erhältst ab sofort Echtzeit-Benachrichtigungen,
wenn neue Artikel gefunden werden.

<i>Diese Nachricht kannst du ignorieren.</i>
"""

    success = bot.send_message(user["telegram_chat_id"], message)

    if success:
        return jsonify({"success": True, "message": "Test-Nachricht gesendet! Prüfe Telegram."})
    else:
        return jsonify({"success": False, "message": "Fehler beim Senden"}), 500


@app.route("/telegram/disconnect", methods=["POST"])
def telegram_disconnect():
    """Trennt Telegram-Verbindung"""
    if not session.get("user_id"):
        return jsonify({"success": False, "error": "Not logged in"}), 401

    user_email = session.get("user_email")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET telegram_chat_id = NULL,
            telegram_enabled = 0,
            telegram_verified = 0,
            telegram_username = NULL
        WHERE email = ?
    """, (user_email,))

    conn.commit()
    conn.close()

    print(f"[Telegram] User {user_email}: Verbindung getrennt")

    return jsonify({"success": True, "message": "Telegram getrennt"})


print("[Telegram] ✅ Routes registriert")


# --- Admin Blueprint: simple stats view --------------------------------------
import sqlite3

from flask import Blueprint, abort, render_template, request

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")  # in Render als ENV setzen
DB_PATH = "instance/db.sqlite3"

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _is_admin() -> bool:
    if not ADMIN_TOKEN:
        # Wenn kein Token gesetzt ist, nur lokal erlauben
        return request.host.startswith("127.0.0.1") or request.host.startswith(
            "localhost"
        )
    return request.args.get("token") == ADMIN_TOKEN


@admin_bp.route("/stats")
def admin_stats():
    if not _is_admin():
        abort(403)

    with _db() as conn:
        cur = conn.cursor()

        # Live-Kennzahlen
        users_total = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        premium_total = cur.execute(
            "SELECT COUNT(*) FROM users WHERE is_premium=1"
        ).fetchone()[0]
        alerts_total = cur.execute("SELECT COUNT(*) FROM search_alerts").fetchone()[0]
        alerts_active = cur.execute(
            "SELECT COUNT(*) FROM search_alerts WHERE is_active=1"
        ).fetchone()[0]

        plans = cur.execute(
            """
            SELECT id, name, price, max_agents, max_email_alerts
            FROM plans WHERE is_active=1 ORDER BY sort_order
        """
        ).fetchall()

        # System-Statistik (eine Zeile, id=1)
        sys = cur.execute("SELECT * FROM system_stats WHERE id=1").fetchone()

        # Plan-Usage (aus View; existiert durch init_db.py)
        plan_usage = cur.execute(
            """
            SELECT plan, plan_name, user_count, total_alerts, max_agents, price
            FROM v_plan_usage
            ORDER BY price
        """
        ).fetchall()

    data = {
        "users_total": users_total,
        "premium_total": premium_total,
        "alerts_total": alerts_total,
        "alerts_active": alerts_active,
        "plans": plans,
        "sys": sys,
        "plan_usage": plan_usage,
    }
    return render_template("admin_stats.html", **data)


@admin_bp.route("/stats/recalc", methods=["POST"])
def admin_stats_recalc():
    if not _is_admin():
        abort(403)

    with _db() as conn:
        cur = conn.cursor()
        # einfache Aggregation – passe nach Bedarf an
        users_total = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        premium_total = cur.execute(
            "SELECT COUNT(*) FROM users WHERE is_premium=1"
        ).fetchone()[0]
        alerts_total = cur.execute("SELECT COUNT(*) FROM search_alerts").fetchone()[0]
        emails_sent = cur.execute(
            "SELECT COALESCE(SUM(total_emails_sent),0) FROM user_stats"
        ).fetchone()[0]

        cur.execute(
            """
            UPDATE system_stats
               SET total_users=?,
                   total_premium_users=?,
                   total_alerts=?,
                   total_emails_sent=?,
                   last_cron_run=CURRENT_TIMESTAMP,
                   updated_at=CURRENT_TIMESTAMP
             WHERE id=1
        """,
            (users_total, premium_total, alerts_total, emails_sent),
        )
        conn.commit()

    # nach Recalc wieder zur Übersicht
    q = f"?token={ADMIN_TOKEN}" if ADMIN_TOKEN else ""
    return (
        "",
        204,
        {"HX-Redirect": f"/admin/stats{q}"},
    )  # funktioniert normal & mit HTMX

    # ============================================================================
# WATCHLIST & TELEGRAM INTEGRATION
# ============================================================================

# ============================================================================
# WATCHLIST ROUTES (direkt in app.py definiert)
# ============================================================================
# Integration-Dateien wurden deaktiviert, Routes sind direkt hier definiert




if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    debug = as_bool(os.getenv("FLASK_DEBUG", "1"))
    app.run(host="0.0.0.0", port=port, debug=debug)
