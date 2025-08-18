import os
import time
import math
import base64
import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from urllib.parse import urlencode

import requests
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, abort
)

# ------------------------------------------------------------
# App & Basis-Config
# ------------------------------------------------------------
def as_bool(val: Optional[str]) -> bool:
    return str(val).lower() in {"1", "true", "yes", "on"}

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-me")

# DB-Pfad (sqlite:///instance/db.sqlite3)
DB_URL = os.getenv("DB_PATH", "sqlite:///instance/db.sqlite3")
def _sqlite_file_from_url(url: str) -> Path:
    if url.startswith("sqlite:///"):
        return Path(url.replace("sqlite:///", "", 1))
    return Path(url)
DB_FILE = _sqlite_file_from_url(DB_URL)
DB_FILE.parent.mkdir(parents=True, exist_ok=True)

FREE_SEARCH_LIMIT = int(os.getenv("FREE_SEARCH_LIMIT", "3"))
PREMIUM_SEARCH_LIMIT = int(os.getenv("PREMIUM_SEARCH_LIMIT", "10"))

# Ergebnisse & Cache
PER_PAGE_DEFAULT = int(os.getenv("RESULTS_PER_PAGE", "20"))
SEARCH_CACHE_TTL = int(os.getenv("SEARCH_CACHE_TTL", "60"))  # Sekunden

# ------------------------------------------------------------
# eBay – Client Credentials + Browse API
# ------------------------------------------------------------
EBAY_CLIENT_ID = os.getenv("EBAY_CLIENT_ID", "")
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET", "")
EBAY_MARKETPLACE_ID = os.getenv("EBAY_MARKETPLACE_ID", "EBAY_DE")
EBAY_SCOPE = os.getenv("EBAY_SCOPE", "https://api.ebay.com/oauth/api_scope")
EBAY_CURRENCY = os.getenv("EBAY_CURRENCY", "EUR")

_EBAY_TOKEN = {"access_token": None, "expires_at": 0}

_http = requests.Session()
_http.headers.update({"User-Agent": "ebay-agent-cockpit/1.0"})

# ------------------------------------------------------------
# Stripe (optional; fällt sauber zurück, wenn nicht konfiguriert)
# ------------------------------------------------------------
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PRICE_PRO = os.getenv("STRIPE_PRICE_PRO", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

STRIPE_OK = False
try:
    import stripe as _stripe  # type: ignore
    if STRIPE_SECRET_KEY:
        _stripe.api_key = STRIPE_SECRET_KEY
    STRIPE_OK = True
    stripe = _stripe
except Exception:
    STRIPE_OK = False
    stripe = None

# ------------------------------------------------------------
# DB – Mini-User-Table mit Premium-Flag
# ------------------------------------------------------------
def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_FILE), detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    return conn

def init_db() -> None:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,         -- Demo: Klartext (in echt hash!)
            is_premium INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

init_db()  # direkt (Flask 3-kompatibel)

# ------------------------------------------------------------
# Template-Fallback
# ------------------------------------------------------------
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

# ------------------------------------------------------------
# Context-Processor (Limits + QS-Helper)
# ------------------------------------------------------------
def _build_query(existing: dict, **extra) -> str:
    """Querystring mit Support für Mehrfachwerte (z. B. condition=NEW&condition=USED)."""
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
def inject_limits_and_helpers():
    return {
        "FREE_SEARCH_LIMIT": FREE_SEARCH_LIMIT,
        "PREMIUM_SEARCH_LIMIT": PREMIUM_SEARCH_LIMIT,
        "qs": _build_query,
    }

# ------------------------------------------------------------
# Session-Defaults & kleine Helfer
# ------------------------------------------------------------
@app.before_request
def _ensure_session_defaults():
    session.setdefault("free_search_count", 0)
    session.setdefault("is_premium", False)
    session.setdefault("user_email", "guest")

def _user_search_limit() -> int:
    return PREMIUM_SEARCH_LIMIT if session.get("is_premium") else FREE_SEARCH_LIMIT

# ------------------------------------------------------------
# Auth – Demo
# ------------------------------------------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return safe_render("register.html", title="Registrieren")

    email = (request.form.get("email") or "").strip().lower()
    password = (request.form.get("password") or "").strip()
    if not email or not password:
        flash("Bitte E-Mail und Passwort angeben.", "warning")
        return redirect(url_for("register"))

    conn = get_db()
    try:
        conn.execute("INSERT INTO users (email, password, is_premium) VALUES (?, ?, 0)", (email, password))
        conn.commit()
    except sqlite3.IntegrityError:
        flash("Diese E-Mail ist bereits registriert.", "warning")
        return redirect(url_for("register"))
    finally:
        conn.close()

    flash("Registrierung erfolgreich. Bitte einloggen.", "success")
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return safe_render("login.html", title="Login")

    email = (request.form.get("email") or "").strip().lower()
    password = (request.form.get("password") or "").strip()

    conn = get_db()
    row = conn.execute("SELECT id, password, is_premium FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()

    if not row or row["password"] != password:
        flash("E-Mail oder Passwort ist falsch.", "warning")
        return redirect(url_for("login"))

    session["user_id"] = int(row["id"])
    session["user_email"] = email
    session["is_premium"] = bool(row["is_premium"])
    flash("Login erfolgreich.", "success")
    return redirect(url_for("dashboard"))

@app.route("/logout")
def logout():
    session.clear()
    flash("Logout erfolgreich.", "info")
    return redirect(url_for("public_home"))

# ------------------------------------------------------------
# Public / Dashboard / Free-Start
# ------------------------------------------------------------
@app.route("/")
def root_redirect():
    return redirect(url_for("public_home"))

@app.route("/public")
def public_home():
    return safe_render("public_home.html", title="Start – ebay-agent-cockpit")

@app.route("/pricing")
def public_pricing():
    return safe_render("public_pricing.html", title="Preise – ebay-agent-cockpit")

@app.route("/dashboard")
def dashboard():
    if not session.get("user_id"):
        flash("Bitte einloggen.", "info")
        return redirect(url_for("login"))
    return safe_render("dashboard.html", title="Dashboard")

@app.route("/start-free")
@app.route("/free")
def start_free():
    session["is_premium"] = False
    session["free_search_count"] = 0
    session["user_email"] = "guest"
    return redirect(url_for("search"))

# ------------------------------------------------------------
# eBay OAuth & Suche
# ------------------------------------------------------------
def ebay_get_token() -> Optional[str]:
    """Client-Credentials Token holen & cachen."""
    if _EBAY_TOKEN["access_token"] and time.time() < _EBAY_TOKEN["expires_at"]:
        return _EBAY_TOKEN["access_token"]

    if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
        return None

    token_url = "https://api.ebay.com/identity/v1/oauth2/token"
    basic = base64.b64encode(f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}".encode()).decode()
    headers = {"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"}
    data = {"grant_type": "client_credentials", "scope": EBAY_SCOPE}
    try:
        r = _http.post(token_url, headers=headers, data=data, timeout=15)
        r.raise_for_status()
        j = r.json()
        _EBAY_TOKEN["access_token"] = j.get("access_token")
        _EBAY_TOKEN["expires_at"] = time.time() + int(j.get("expires_in", 7200)) - 60
        return _EBAY_TOKEN["access_token"]
    except Exception as e:
        print(f"[ebay_get_token] {e}")
        return None

def _build_ebay_filters(price_min: Optional[str], price_max: Optional[str], conditions: List[str]) -> Optional[str]:
    parts: List[str] = []
    pmn = (price_min or "").strip()
    pmx = (price_max or "").strip()
    if pmn or pmx:
        parts.append(f"price:[{pmn}..{pmx}]")
        if EBAY_CURRENCY:
            parts.append(f"priceCurrency:{EBAY_CURRENCY}")
    conds = [c.strip().upper() for c in (conditions or []) if c.strip()]
    if conds:
        parts.append("conditions:{" + ",".join(conds) + "}")
    return ",".join(parts) if parts else None

def _map_sort(ui_sort: str) -> Optional[str]:
    s = (ui_sort or "").strip()
    if not s or s == "best":
        return None
    if s == "price_asc":
        return "price"
    if s == "price_desc":
        return "-price"
    if s == "newly":
        return "newlyListed"
    return None

# Mini-Cache für identische Suchen (gleiche Filter & Seite)
_search_cache: dict = {}  # key -> (ts, (items, total_estimated))
def _cache_get(key):
    row = _search_cache.get(key)
    if not row:
        return None
    ts, payload = row
    if (time.time() - ts) > SEARCH_CACHE_TTL:
        _search_cache.pop(key, None)
        return None
    return payload

def _cache_set(key, payload):
    _search_cache[key] = (time.time(), payload)

def ebay_search_one(term: str, limit: int, offset: int,
                    filter_str: Optional[str], sort: Optional[str]) -> Tuple[List[Dict], Optional[int]]:
    """Einzelterm-Suche mit Limit/Offset, liefert (items,total) für diesen Term."""
    token = ebay_get_token()
    if not token or not term:
        return [], None

    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    params = {"q": term, "limit": max(1, min(limit, 50)), "offset": max(0, offset)}
    if filter_str: params["filter"] = filter_str
    if sort: params["sort"] = sort
    headers = {"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": EBAY_MARKETPLACE_ID}

    try:
        r = _http.get(url, headers=headers, params=params, timeout=15)
        r.raise_for_status()
        j = r.json() or {}
        items_raw = j.get("itemSummaries", []) or []
        total = j.get("total")
        items: List[Dict] = []
        for it in items_raw:
            title = it.get("title") or "—"
            web = it.get("itemWebUrl")
            img = (it.get("image") or {}).get("imageUrl")
            price = (it.get("price") or {}).get("value")
            cur = (it.get("price") or {}).get("currency")
            price_str = f"{price} {cur}" if price and cur else "–"
            items.append({"title": title, "price": price_str, "url": web, "img": img, "term": term})
        return items, total
    except Exception as e:
        print(f"[ebay_search_one] {e}")
        return [], None

def _backend_search_ebay(terms: List[str], filters: dict, page: int, per_page: int) -> Tuple[List[Dict], Optional[int]]:
    """
    Mehrere Suchbegriffe: wir holen pro Term anteilig Ergebnisse.
    Gesamt-Pagination über mehrere Begriffe ist schwer exakt; wir zeigen Vor/Zurück,
    und wenn totals verfügbar sind, schätzen wir die Gesamtsumme.
    """
    if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
        return _backend_search_demo(terms, page, per_page)

    filter_str = _build_ebay_filters(filters.get("price_min"), filters.get("price_max"), filters.get("conditions") or [])
    sort = _map_sort(filters.get("sort", "best"))

    n = max(1, len(terms))
    per_term = max(1, per_page // n)
    offset = (page - 1) * per_term

    items_all: List[Dict] = []
    totals = []
    for t in terms:
        items, total = ebay_search_one(t, per_term, offset, filter_str, sort)
        items_all.extend(items)
        if isinstance(total, int):
            totals.append(total)

    # Falls weniger Elemente eingeflossen sind (z. B. ungleich verteilt), evtl. Rest vom ersten Term holen
    if len(items_all) < per_page and terms:
        rest = per_page - len(items_all)
        extra, _ = ebay_search_one(terms[0], rest, offset + per_term, filter_str, sort)
        items_all.extend(extra)

    total_estimated = sum(totals) if totals else None
    return items_all[:per_page], total_estimated

def _backend_search_demo(terms: List[str], page: int, per_page: int) -> Tuple[List[Dict], int]:
    total = max(30, len(terms) * 40)
    start = (page - 1) * per_page
    stop = min(total, start + per_page)
    items = []
    for i in range(start, stop):
        t = terms[i % max(1, len(terms))] if terms else f"Artikel {i+1}"
        items.append({
            "title": f"Demo-Ergebnis für „{t}“ #{i+1}",
            "price": "9,99 €",
            "url": f"https://www.ebay.de/sch/i.html?_nkw={t}",
            "img": "https://via.placeholder.com/64x48?text=%20",
            "term": t,
        })
    return items, total

def _search_with_cache(terms: List[str], filters: dict, page: int, per_page: int):
    key = (tuple(terms),
           filters.get("price_min") or "",
           filters.get("price_max") or "",
           filters.get("sort") or "best",
           tuple(filters.get("conditions") or []),
           page, per_page)
    cached = _cache_get(key)
    if cached:
        return cached
    items, total = _backend_search_ebay(terms, filters, page, per_page)
    _cache_set(key, (items, total))
    return items, total

# ------------------------------------------------------------
# Suche – PRG + Pagination
# ------------------------------------------------------------
def _collect_params(src) -> dict:
    params = {
        "q1": (src.get("q1") or "").strip(),
        "q2": (src.get("q2") or "").strip(),
        "q3": (src.get("q3") or "").strip(),
        "price_min": (src.get("price_min") or "").strip(),
        "price_max": (src.get("price_max") or "").strip(),
        "sort": (src.get("sort") or "best").strip(),
        "per_page": (src.get("per_page") or "").strip(),
    }
    try:
        params["condition"] = src.getlist("condition")
    except Exception:
        raw = (src.get("condition") or "").strip()
        params["condition"] = [s for s in raw.split(",") if s]
    return params

def _params_to_terms(params: dict) -> List[str]:
    return [t for t in [params.get("q1"), params.get("q2"), params.get("q3")] if t]

@app.route("/search", methods=["GET", "POST"])
def search():
    # POST -> Redirect mit Querystring (PRG)
    if request.method == "POST":
        params = _collect_params(request.form)
        # Free-Limit nur beim Absenden zählen
        if not session.get("is_premium", False):
            count = int(session.get("free_search_count", 0))
            if count >= FREE_SEARCH_LIMIT:
                flash(f"Kostenloses Limit ({FREE_SEARCH_LIMIT}) erreicht – bitte Upgrade buchen.", "info")
                return redirect(url_for("public_pricing"))
            session["free_search_count"] = count + 1
        params["page"] = 1
        return redirect(url_for("search", **params))

    # GET -> tatsächliche Suche
    params = _collect_params(request.args)
    terms = _params_to_terms(params)
    if not terms:
        return safe_render("search.html", title="Suche", body="Suche starten.")

    try:
        page = max(int(request.args.get("page", 1)), 1)
    except Exception:
        page = 1
    try:
        per_page = int(params.get("per_page") or PER_PAGE_DEFAULT)
        per_page = min(max(per_page, 5), 100)
    except Exception:
        per_page = PER_PAGE_DEFAULT

    filters = {
        "price_min": params.get("price_min") or "",
        "price_max": params.get("price_max") or "",
        "sort": params.get("sort") or "best",
        "conditions": params.get("condition") or [],
    }

    items, total_estimated = _search_with_cache(terms, filters, page, per_page)

    total_pages = math.ceil(total_estimated / per_page) if total_estimated else None
    has_prev = page > 1
    has_next = (total_pages and page < total_pages) or (not total_pages and len(items) == per_page)

    base_qs = {
        "q1": params.get("q1", ""),
        "q2": params.get("q2", ""),
        "q3": params.get("q3", ""),
        "price_min": filters["price_min"],
        "price_max": filters["price_max"],
        "sort": filters["sort"],
        "condition": filters["conditions"],
        "per_page": per_page,
    }

    return safe_render(
        "search_results.html",
        title="Suchergebnisse",
        terms=terms,
        results=items,
        filters={
            "price_min": filters["price_min"],
            "price_max": filters["price_max"],
            "sort": filters["sort"],
            "conditions": filters["conditions"],
        },
        pagination={
            "page": page,
            "per_page": per_page,
            "total_estimated": total_estimated,
            "total_pages": total_pages,
            "has_prev": has_prev,
            "has_next": has_next,
        },
        base_qs=base_qs
    )

# ------------------------------------------------------------
# Stripe Checkout (optional)
# ------------------------------------------------------------
@app.route("/checkout", methods=["POST"])
def public_checkout():
    if not STRIPE_OK or not STRIPE_SECRET_KEY or not STRIPE_PRICE_PRO:
        flash("Stripe ist nicht konfiguriert.", "warning")
        return redirect(url_for("public_pricing"))
    try:
        success_url = url_for("checkout_success", _external=True)
        cancel_url = url_for("checkout_cancel", _external=True)
        session_stripe = stripe.checkout.Session.create(  # type: ignore
            mode="subscription",
            line_items=[{"price": STRIPE_PRICE_PRO, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            allow_promotion_codes=True,
        )
        return redirect(session_stripe.url, code=303)
    except Exception as e:
        flash(f"Stripe-Fehler: {e}", "danger")
        return redirect(url_for("public_pricing"))

@app.route("/checkout/success")
def checkout_success():
    flash("Dein Premium-Zugang ist jetzt freigeschaltet.", "success")
    return safe_render("success.html", title="Erfolg")

@app.route("/checkout/cancel")
def checkout_cancel():
    flash("Vorgang abgebrochen.", "info")
    return redirect(url_for("public_pricing"))

# ------------------------------------------------------------
# Debug / Health
# ------------------------------------------------------------
@app.route("/_debug/ebay")
def debug_ebay():
    return jsonify({
        "configured": bool(EBAY_CLIENT_ID and EBAY_CLIENT_SECRET),
        "marketplace": EBAY_MARKETPLACE_ID,
        "currency": EBAY_CURRENCY,
        "token_cached": bool(_EBAY_TOKEN["access_token"]),
        "token_valid_for_s": max(0, int(_EBAY_TOKEN["expires_at"] - time.time())),
    })

@app.route("/debug")
def debug_env():
    data = {
        "env": {
            "DB_PATH": DB_URL,
            "FREE_SEARCH_LIMIT": FREE_SEARCH_LIMIT,
            "PREMIUM_SEARCH_LIMIT": PREMIUM_SEARCH_LIMIT,
            "STRIPE_PRICE_PRO_set": bool(STRIPE_PRICE_PRO),
            "STRIPE_SECRET_KEY_set": bool(STRIPE_SECRET_KEY),
            "STRIPE_WEBHOOK_SECRET_set": bool(STRIPE_WEBHOOK_SECRET),
            # >>> NEU: eBay-Flags
            "LIVE_SEARCH": os.getenv("LIVE_SEARCH", "0"),
            "EBAY_CLIENT_ID_set": bool(os.getenv("EBAY_CLIENT_ID")),
            "EBAY_CLIENT_SECRET_set": bool(os.getenv("EBAY_CLIENT_SECRET")),
            "EBAY_SCOPES": os.getenv("EBAY_SCOPES", ""),
            "EBAY_GLOBAL_ID": os.getenv("EBAY_GLOBAL_ID", ""),
        },
        "session": {
            "free_search_count": int(session.get("free_search_count", 0)),
            "is_premium": bool(session.get("is_premium", False)),
            "user_email": session.get("user_email", "guest"),
        },
    }
    return jsonify(data)
@app.route("/healthz")
def healthz():
    return "ok", 200

# ------------------------------------------------------------
# Run (nur lokal)
# ------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    debug = as_bool(os.getenv("FLASK_DEBUG", "1"))
    app.run(host="0.0.0.0", port=port, debug=debug)