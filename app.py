# app.py
import os
import sqlite3
from functools import wraps
from datetime import datetime

import requests
import stripe
from dotenv import load_dotenv
from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, g, jsonify, Response
)
from werkzeug.security import generate_password_hash, check_password_hash


# =============================================================================
# Konfiguration & Setup
# =============================================================================
load_dotenv()  # lokal nützlich; auf Render ignoriert

DB_PATH = (
    os.getenv("DATABASE_FILE")
    or os.getenv("DATABASE_URL")
    or ("/tmp/agent.db" if os.getenv("RENDER") or os.getenv("DYNO") else "database.db")
)

SECRET_KEY = os.getenv("SECRET_KEY", "dev_key")

# Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
PRICE_ID = os.getenv("STRIPE_PRICE_PRO")
SUCCESS_URL = os.getenv("STRIPE_SUCCESS_URL")   # optional
CANCEL_URL  = os.getenv("STRIPE_CANCEL_URL")    # optional

# Suche (Limits)
FREE_SEARCH_LIMIT    = int(os.getenv("FREE_SEARCH_LIMIT", "3"))
PREMIUM_SEARCH_LIMIT = int(os.getenv("PREMIUM_SEARCH_LIMIT", "10"))

# eBay API (Finding API – AppID genügt)
EBAY_APP_ID = os.getenv("EBAY_APP_ID")  # z.B. 'YourAppID-1234567890'


# =============================================================================
# Flask
# =============================================================================
app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY


# =============================================================================
# Safe Template Render (verhindert 500 bei fehlenden Templates)
# =============================================================================
def safe_render(template_name: str, **ctx):
    try:
        return render_template(template_name, **ctx)
    except Exception:
        title = ctx.get("title") or template_name
        body = ctx.get("body") or ""
        return Response(f"""<!doctype html>
<html lang="de">
<head><meta charset="utf-8"><title>{title}</title></head>
<body style="font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:900px;margin:40px auto;line-height:1.5">
<h1>{title}</h1>
<p>{body}</p>
<p style="margin-top:24px"><a href="{url_for('public_home')}">Zur Startseite</a></p>
</body></html>""", mimetype="text/html")


# =============================================================================
# DB
# =============================================================================
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
    cur.execute("PRAGMA table_info(users)")
    cols = {r["name"] for r in cur.fetchall()}
    if "password" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN password TEXT NOT NULL DEFAULT ''")
    if "is_premium" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN is_premium INTEGER DEFAULT 0")
    if "created_at" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN created_at TEXT DEFAULT CURRENT_TIMESTAMP")
    db.commit()

def seed_user():
    email = (os.getenv("SEED_USER_EMAIL") or "").strip().lower()
    pw    = (os.getenv("SEED_USER_PASSWORD") or "").strip()
    if not email or not pw:
        return
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id FROM users WHERE email = ?", (email,))
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO users (email, password, is_premium) VALUES (?, ?, 1)",
            (email, generate_password_hash(pw))
        )
        db.commit()

_initialized = False
@app.before_request
def _init_once():
    global _initialized
    if not _initialized:
        ensure_schema()
        seed_user()
        _initialized = True


# =============================================================================
# Auth-Helfer
# =============================================================================
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Bitte einloggen.", "info")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


# =============================================================================
# Öffentliche Seiten
# =============================================================================
@app.get("/public")
def public_home():
    return safe_render(
        "public_home.html",
        title="Start",
        body="Dein leichtes Cockpit für eBay‑Automatisierung."
    )

@app.get("/pricing")
def public_pricing():
    return safe_render(
        "public_pricing.html",
        title="Preise",
        body="Alles drin, was du brauchst."
    )

@app.route("/checkout", methods=["GET", "POST"])
def public_checkout():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        try:
            if not PRICE_ID:
                raise RuntimeError("Kein STRIPE_PRICE_PRO gesetzt.")
            s = stripe.checkout.Session.create(
                mode="subscription",
                line_items=[{"price": PRICE_ID, "quantity": 1}],
                customer_email=email or None,
                success_url=SUCCESS_URL or url_for("checkout_success", _external=True),
                cancel_url=CANCEL_URL  or url_for("public_pricing", _external=True),
                allow_promotion_codes=True,
            )
            return redirect(s.url, code=303)
        except Exception as e:
            flash(f"Stripe‑Fehler: {e}", "danger")
            return redirect(url_for("public_checkout"))
    return safe_render("public_checkout.html", title="Checkout", body="Checkout Formular.")

@app.get("/checkout/success")
def checkout_success():
    return safe_render("success.html", title="Vielen Dank!", body="Premium freigeschaltet.")


# =============================================================================
# Dashboard
# =============================================================================
@app.get("/")
@login_required
def dashboard():
    return safe_render("dashboard.html", title="Dashboard", body="Willkommen im Dashboard.")


# =============================================================================
# Suche
# =============================================================================
def _ebay_find_items(app_id: str, query: str, limit: int = 10):
    """
    Einfacher Call zur eBay Finding API (REST wrapper).
    Doku: https://developer.ebay.com/devzone/finding/callref/findItemsByKeywords.html
    Hinweis: Finding API akzeptiert AppID in 'SECURITY-APPNAME'.
    """
    endpoint = "https://svcs.ebay.com/services/search/FindingService/v1"
    params = {
        "OPERATION-NAME": "findItemsByKeywords",
        "SERVICE-VERSION": "1.13.0",
        "SECURITY-APPNAME": app_id,
        "RESPONSE-DATA-FORMAT": "JSON",
        "REST-PAYLOAD": "true",
        "paginationInput.entriesPerPage": str(limit),
        "keywords": query,
        "outputSelector": "PictureURLLarge"
    }
    r = requests.get(endpoint, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    # defensive parsing
    try:
        items = data["findItemsByKeywordsResponse"][0]["searchResult"][0].get("item", [])
    except Exception:
        items = []
    results = []
    for it in items:
        selling = it.get("sellingStatus", [{}])[0]
        price = selling.get("currentPrice", [{}])[0].get("__value__", None)
        currency = selling.get("currentPrice", [{}])[0].get("@currencyId", "")
        results.append({
            "title": it.get("title", [""])[0],
            "view_url": it.get("viewItemURL", [""])[0],
            "price": f"{price} {currency}" if price else "",
            "gallery": it.get("galleryURL", [""])[0] or it.get("pictureURLLarge", [""])[0],
            "location": it.get("location", [""])[0],
        })
    return results

@app.get("/search")
@login_required
def search_get():
    # Nur Formular anzeigen
    return safe_render("search.html", title="Suche", body="Suche starten.")

@app.post("/search")
@login_required
def search_post():
    # terms[] kommt aus dem Formular (mehrere Felder gleichen Namens)
    terms = [t.strip() for t in request.form.getlist("terms[]") if (t or "").strip()]
    if not terms:
        flash("Bitte mindestens einen Suchbegriff eingeben.", "warning")
        return redirect(url_for("search_get"))

    # Limit nach Plan
    is_premium = bool(_get_current_user_premium())
    limit = PREMIUM_SEARCH_LIMIT if is_premium else FREE_SEARCH_LIMIT

    # Eine zusammengesetzte Query (ODER-Suche) – simpel: durch Leerzeichen getrennt
    query = " ".join(terms)

    results = []
    error = None
    used_api = False

    if EBAY_APP_ID:
        try:
            results = _ebay_find_items(EBAY_APP_ID, query, limit=limit)
            used_api = True
        except Exception as e:
            error = f"eBay API Fehler: {e}"

    if not used_api:
        # Fallback: Mock-Ergebnisse (damit UI funktioniert)
        base = [
            {
                "title": f"Demo‑Treffer für „{q}“",
                "view_url": "https://www.ebay.de/",
                "price": "9.99 EUR",
                "gallery": "https://picsum.photos/seed/ebay/200/140",
                "location": "—"
            } for q in terms
        ]
        results = base[:limit]

    # Ergebnisse in derselben Seite rendern (search.html erwartet results)
    return safe_render(
        "search.html",
        title="Suchergebnisse",
        results=results,
        query=query,
        limit=limit,
        is_premium=is_premium,
        error=error
    )


def _get_current_user_premium() -> int:
    """liefert 1/0 für Premium-Status des eingeloggten Users"""
    uid = session.get("user_id")
    if not uid:
        return 0
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT is_premium FROM users WHERE id = ?", (uid,))
    row = cur.fetchone()
    return int(row["is_premium"]) if row else 0


# =============================================================================
# Settings / Sync (Platzhalter)
# =============================================================================
@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        flash("Einstellungen gespeichert.", "success")
        return redirect(url_for("settings"))
    return safe_render("settings.html", title="Einstellungen", body="Einstellungen.")

@app.get("/sync")
@login_required
def sync_get():
    flash("Sync gestartet (Demo).", "info")
    return redirect(url_for("dashboard"))


# =============================================================================
# Auth
# =============================================================================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email    = (request.form.get("email") or "").strip().lower()
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
            flash("Login erfolgreich!", "success")
            return redirect(url_for("dashboard"))
        flash("Ungültige E‑Mail oder Passwort.", "danger")
        return redirect(url_for("login"))
    return safe_render("login.html", title="Login", body="Login Formular.")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email    = (request.form.get("email") or "").strip().lower()
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
    return safe_render("register.html", title="Registrieren", body="Registrierungsformular.")

@app.get("/logout")
def logout():
    session.clear()
    flash("Logout erfolgreich!", "info")
    return redirect(url_for("login"))


# =============================================================================
# Debug & Health
# =============================================================================
@app.get("/ping")
def ping():
    ensure_schema()
    return "pong", 200

@app.get("/debug")
def debug_env():
    return jsonify({
        "ok": True,
        "env": {
            "DB_PATH": DB_PATH,
            "STRIPE_SECRET_KEY_set": bool(os.getenv("STRIPE_SECRET_KEY")),
            "STRIPE_PRICE_PRO": PRICE_ID,
            "STRIPE_WEBHOOK_SECRET_set": bool(os.getenv("STRIPE_WEBHOOK_SECRET")),
            "EBAY_APP_ID_set": bool(EBAY_APP_ID),
            "FREE_SEARCH_LIMIT": FREE_SEARCH_LIMIT,
            "PREMIUM_SEARCH_LIMIT": PREMIUM_SEARCH_LIMIT,
        }
    })

@app.get("/_debug/stripe")
def debug_stripe():
    out = {"ok": False, "can_call_api": False, "price_ok": None, "error": None}
    try:
        stripe.Balance.retrieve()
        out["can_call_api"] = True
        if PRICE_ID:
            try:
                stripe.Price.retrieve(PRICE_ID)
                out["price_ok"] = True
            except Exception as e:
                out["price_ok"] = False
                out["error"] = str(e)
        out["ok"] = out["can_call_api"] and (out["price_ok"] in (True, None))
    except Exception as e:
        out["error"] = str(e)
    return jsonify(out)

@app.get("/favicon.ico")
def favicon():
    return Response(status=204)


# =============================================================================
# Fehlerseiten
# =============================================================================
@app.errorhandler(404)
def _404(e):
    return safe_render("404.html", title="404", body="Seite nicht gefunden."), 404

@app.errorhandler(500)
def _500(e):
    return safe_render("500.html", title="500", body="Interner Fehler."), 500


# =============================================================================
# Dev-Reset (optional, nur lokal nutzen)
# =============================================================================
@app.post("/_dev_reset_db")
def _dev_reset_db():
    if os.getenv("ALLOW_RESET") != "1":
        return "disabled", 403
    try:
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
        ensure_schema()
        return "reset ok"
    except Exception as e:
        return f"reset failed: {e}", 500


# =============================================================================
# Main
# =============================================================================
if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=True)