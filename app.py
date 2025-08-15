# app.py
import os
import sqlite3
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, g, jsonify, Response
)
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import stripe
import requests

# =============================================================================
# Konfiguration & Flask
# =============================================================================
load_dotenv()

DB_PATH = (
    os.getenv("DATABASE_FILE")
    or os.getenv("DATABASE_URL")
    or ("/tmp/agent.db" if os.getenv("RENDER") or os.getenv("DYNO") else "database.db")
)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev_key")

# Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
PRICE_ID = os.getenv("STRIPE_PRICE_PRO")
SUCCESS_URL = os.getenv("STRIPE_SUCCESS_URL")
CANCEL_URL = os.getenv("STRIPE_CANCEL_URL")

# eBay
EBAY_APP_ID = os.getenv("EBAY_APP_ID", "").strip()
EBAY_GLOBAL_ID = os.getenv("EBAY_GLOBAL_ID", "EBAY-DE")

FREE_SEARCH_LIMIT = int(os.getenv("FREE_SEARCH_LIMIT", "3"))
PREMIUM_SEARCH_LIMIT = int(os.getenv("PREMIUM_SEARCH_LIMIT", "10"))

# =============================================================================
# Hilfen
# =============================================================================
def safe_render(template_name: str, **ctx):
    try:
        return render_template(template_name, **ctx)
    except Exception:
        title = ctx.get("title") or template_name
        body = ctx.get("body") or ""
        return Response(f"""<!doctype html>
<html lang="de"><meta charset="utf-8">
<title>{title}</title>
<body style="font-family:system-ui;max-width:900px;margin:40px auto">
<h1>{title}</h1><p>{body}</p>
<p style="margin-top:24px"><a href="{url_for('public_home')}">Zur Startseite</a></p>
</body></html>""", mimetype="text/html")

def get_db():
    if "db" not in g:
        os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
        g.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def ensure_schema():
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL DEFAULT '',
            is_premium INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.commit()

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Bitte einloggen.", "info")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

# Einmalige Initialisierung pro Prozess
_initialized = False
@app.before_request
def _init_once():
    global _initialized
    if not _initialized:
        ensure_schema()
        _initialized = True

# =============================================================================
# eBay – echte Suche (Finding API)
# =============================================================================
def ebay_find_items(term: str, limit: int = 3, global_id: str = EBAY_GLOBAL_ID) -> list[dict]:
    """
    Sucht Artikel via eBay Finding API (findItemsByKeywords).
    Nutzt EBAY_APP_ID (Client-ID). Gibt Liste mit title, price, url, image, term.
    """
    if not EBAY_APP_ID:
        # Fallback, falls keine App-ID gesetzt
        return [{
            "title": f"Demo-Ergebnis für „{term}“ (keine EBAY_APP_ID)",
            "price": 9.99,
            "url": f"https://www.ebay.de/sch/i.html?_nkw={term}",
            "image": "",
            "term": term,
        }]

    endpoint = "https://svcs.ebay.com/services/search/FindingService/v1"
    params = {
        "OPERATION-NAME": "findItemsByKeywords",
        "SERVICE-VERSION": "1.0.0",
        "SECURITY-APPNAME": EBAY_APP_ID,
        "RESPONSE-DATA-FORMAT": "JSON",
        "REST-PAYLOAD": "",
        "keywords": term,
        "paginationInput.entriesPerPage": str(limit),
        "GLOBAL-ID": global_id,
    }

    try:
        r = requests.get(endpoint, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()

        items = []
        search_result = data.get("findItemsByKeywordsResponse", [])[0] \
                            .get("searchResult", [])[0] \
                            .get("item", [])

        for it in search_result:
            title = it.get("title", [""])[0]
            view_url = it.get("viewItemURL", [""])[0]
            price = it.get("sellingStatus", [{}])[0] \
                     .get("currentPrice", [{}])[0] \
                     .get("__value__", "0.00")
            image_url = it.get("galleryURL", [""])[0]

            items.append({
                "title": title,
                "price": float(price),
                "url": view_url,
                "image": image_url,
                "term": term,
            })

        return items

    except Exception as e:
        print(f"eBay API Fehler für '{term}': {e}")
        return [{
            "title": f"Demo-Ergebnis für „{term}“ (API-Fehler)",
            "price": 9.99,
            "url": f"https://www.ebay.de/sch/i.html?_nkw={term}",
            "image": "",
            "term": term,
        }]

# =============================================================================
# Öffentliche Seiten
# =============================================================================
@app.get("/public")
def public_home():
    return safe_render("public_home.html", title="Start")

@app.get("/pricing")
def public_pricing():
    return safe_render("public_pricing.html", title="Preise")

@app.route("/checkout", methods=["GET", "POST"])
def public_checkout():
    if request.method == "POST":
        email = (request.form.get("email") or session.get("user_email") or "").strip()
        try:
            if not PRICE_ID:
                raise RuntimeError("STRIPE_PRICE_PRO fehlt.")
            sess = stripe.checkout.Session.create(
                mode="subscription",
                line_items=[{"price": PRICE_ID, "quantity": 1}],
                customer_email=email or None,
                success_url=SUCCESS_URL or url_for("checkout_success", _external=True),
                cancel_url=CANCEL_URL or url_for("public_pricing", _external=True),
                allow_promotion_codes=True,
            )
            return redirect(sess.url, code=303)
        except Exception as e:
            flash(f"Stripe‑Fehler: {e}", "danger")
            return redirect(url_for("public_pricing"))
    return safe_render("public_checkout.html", title="Checkout")

@app.get("/checkout/success")
def checkout_success():
    return safe_render("success.html", title="Danke")

# =============================================================================
# Auth
# =============================================================================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        if not email or not password:
            flash("Bitte E‑Mail und Passwort eingeben.", "warning")
            return redirect(url_for("login"))
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT id, password FROM users WHERE email = ?", (email,))
        row = cur.fetchone()
        if row and check_password_hash(row["password"], password):
            session["user_id"] = row["id"]
            session["user_email"] = email
            flash("Login erfolgreich.", "success")
            return redirect(url_for("dashboard"))
        flash("Ungültige Zugangsdaten.", "danger")
        return redirect(url_for("login"))
    return safe_render("login.html", title="Login")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        if not email or not password:
            flash("Bitte E‑Mail und Passwort angeben.", "warning")
            return redirect(url_for("register"))
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT id FROM users WHERE email = ?", (email,))
        if cur.fetchone():
            flash("Diese E‑Mail ist bereits registriert.", "warning")
            return redirect(url_for("register"))
        cur.execute(
            "INSERT INTO users (email, password) VALUES (?, ?)",
            (email, generate_password_hash(password)),
        )
        db.commit()
        flash("Registrierung erfolgreich. Bitte einloggen.", "success")
        return redirect(url_for("login"))
    return safe_render("register.html", title="Registrieren")

@app.get("/logout")
def logout():
    session.clear()
    flash("Logout erfolgreich.", "info")
    return redirect(url_for("login"))

# =============================================================================
# Dashboard & Suche
# =============================================================================
@app.get("/")
@login_required
def dashboard():
    return safe_render("dashboard.html", title="Dashboard")

@app.route("/search", methods=["GET", "POST"])
def search():
    """
    GET: Formular anzeigen
    POST: bis zu 3 Suchbegriffe (q1..q3) verarbeiten, Limit abhängig von Premium.
    Ergebnisse in search_results.html rendern.
    """
    if request.method == "GET":
        return safe_render("search.html", title="Suche")

    # POST
    # Eingabefelder einsammeln
    raw = [
        (request.form.get("q1") or "").strip(),
        (request.form.get("q2") or "").strip(),
        (request.form.get("q3") or "").strip(),
    ]
    terms = [t for t in raw if t]
    if not terms:
        flash("Bitte mindestens einen Suchbegriff eingeben.", "warning")
        return redirect(url_for("search"))

    # Per-Keyword Limit anhand Premium-Status
    per_term_limit = FREE_SEARCH_LIMIT
    try:
        if session.get("user_id"):
            db = get_db()
            cur = db.cursor()
            cur.execute("SELECT is_premium FROM users WHERE id = ?", (session["user_id"],))
            row = cur.fetchone()
            if row and row["is_premium"]:
                per_term_limit = PREMIUM_SEARCH_LIMIT
            else:
                per_term_limit = FREE_SEARCH_LIMIT
    except Exception:
        pass

    results = []
    for term in terms:
        items = ebay_find_items(term, limit=per_term_limit, global_id=EBAY_GLOBAL_ID)
        results.extend(items)

    return safe_render("search_results.html", title="Suche", results=results, q1=raw[0], q2=raw[1], q3=raw[2])

# =============================================================================
# Debug & Sonstiges
# =============================================================================
@app.get("/debug")
def debug_env():
    return jsonify({
        "ok": True,
        "env": {
            "DB_PATH": DB_PATH,
            "EBAY_APP_ID_set": bool(EBAY_APP_ID),
            "FREE_SEARCH_LIMIT": FREE_SEARCH_LIMIT,
            "PREMIUM_SEARCH_LIMIT": PREMIUM_SEARCH_LIMIT,
            "STRIPE_PRICE_PRO": bool(PRICE_ID),
            "STRIPE_SECRET_KEY_set": bool(os.getenv("STRIPE_SECRET_KEY")),
            "STRIPE_WEBHOOK_SECRET_set": bool(os.getenv("STRIPE_WEBHOOK_SECRET")),
        }
    })

@app.get("/ping")
def ping():
    ensure_schema()
    return "pong", 200

@app.get("/favicon.ico")
def favicon():
    return Response(status=204)

@app.errorhandler(404)
def _404(e):
    return safe_render("404.html", title="404", body="Seite nicht gefunden."), 404

@app.errorhandler(500)
def _500(e):
    return safe_render("500.html", title="500", body="Interner Fehler."), 500

# =============================================================================
# Main
# =============================================================================
if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=True)