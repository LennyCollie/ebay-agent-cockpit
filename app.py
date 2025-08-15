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

# =============================================================================
# Konfiguration
# =============================================================================

load_dotenv()  # lokal nützlich; auf Render ignoriert

# DB: auf Render ist nur /tmp schreibbar
DB_PATH = (
    os.getenv("DATABASE_FILE")
    or os.getenv("DATABASE_URL")
    or ("/tmp/agent.db" if os.getenv("RENDER") or os.getenv("DYNO") else "database.db")
)

SECRET_KEY = os.getenv("SECRET_KEY", "dev_key_change_me")

# Stripe (optional – wenn Keys fehlen, bleiben Stripe-Features einfach inaktiv)
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PRICE_PRO = os.getenv("STRIPE_PRICE_PRO")  # z.B. price_...
STRIPE_SUCCESS_URL = os.getenv("STRIPE_SUCCESS_URL")
STRIPE_CANCEL_URL = os.getenv("STRIPE_CANCEL_URL")

# Suche: Limits (frei/premium)
FREE_SEARCH_LIMIT = int(os.getenv("FREE_SEARCH_LIMIT", "3"))
PREMIUM_SEARCH_LIMIT = int(os.getenv("PREMIUM_SEARCH_LIMIT", "10"))

# eBay-App-ID (für später, aktuell noch nicht verwendet)
EBAY_APP_ID = os.getenv("EBAY_APP_ID", "").strip()

# =============================================================================
# Flask App
# =============================================================================

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY


# =============================================================================
# Rendering-Fallback (verhindert 500 bei fehlenden Templates)
# =============================================================================

def safe_render(template_name: str, **ctx):
    try:
        return render_template(template_name, **ctx)
    except Exception:
        title = ctx.get("title") or template_name
        body = ctx.get("body") or ""
        # schlichte HTML-Fallback-Seite
        return Response(f"""<!doctype html>
<html lang="de">
<head><meta charset="utf-8"><title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:900px;margin:40px auto;line-height:1.5">
<h1>{title}</h1>
<p>{body}</p>
<p style="margin-top:24px"><a href="{url_for('public_home')}">Zur Startseite</a></p>
</body></html>""", mimetype="text/html")


# =============================================================================
# DB-Helfer
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
            is_premium INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # robust gegen alte DBs
    cur.execute("PRAGMA table_info(users)")
    cols = {r["name"] for r in cur.fetchall()}
    if "password" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN password TEXT NOT NULL DEFAULT ''")
    if "is_premium" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN is_premium INTEGER NOT NULL DEFAULT 0")
    if "created_at" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN created_at TEXT DEFAULT CURRENT_TIMESTAMP")
    db.commit()

def seed_user():
    """Optionale Testdaten: SEED_USER_EMAIL / SEED_USER_PASSWORD (Premium)."""
    email = (os.getenv("SEED_USER_EMAIL") or "").strip().lower()
    pw = (os.getenv("SEED_USER_PASSWORD") or "").strip()
    if not email or not pw:
        return
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id FROM users WHERE email = ?", (email,))
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO users (email, password, is_premium) VALUES (?, ?, 1)",
            (email, generate_password_hash(pw)),
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
        body="Hier erscheint deine Preisseite."
    )

@app.route("/checkout", methods=["GET", "POST"])
def public_checkout():
    # Wenn keine Stripe-Konfig da ist, simple Seite zeigen
    if request.method == "GET":
        return safe_render(
            "public_checkout.html",
            title="Checkout",
            body="Checkout Formular."
        )

    # POST → Stripe Checkout Session
    email = (request.form.get("email") or "").strip()
    try:
        if not stripe.api_key or not STRIPE_PRICE_PRO:
            raise RuntimeError("Stripe ist nicht konfiguriert (KEY/PRICE_ID fehlt).")
        session_obj = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": STRIPE_PRICE_PRO, "quantity": 1}],
            customer_email=email or None,
            success_url=STRIPE_SUCCESS_URL or url_for("checkout_success", _external=True),
            cancel_url=STRIPE_CANCEL_URL or url_for("public_pricing", _external=True),
            allow_promotion_codes=True,
        )
        return redirect(session_obj.url, code=303)
    except Exception as e:
        flash(f"Stripe‑Fehler: {e}", "danger")
        return redirect(url_for("public_checkout"))

@app.get("/checkout/success")
def checkout_success():
    return safe_render(
        "success.html",
        title="Erfolg",
        body="Dein Premium‑Zugang ist jetzt freigeschaltet."
    )


# =============================================================================
# Dashboard & Settings
# =============================================================================

@app.get("/")
@login_required
def dashboard():
    return safe_render("dashboard.html", title="Dashboard", body="Willkommen im Dashboard.")

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        flash("Einstellungen gespeichert.", "success")
        return redirect(url_for("settings"))
    return safe_render("settings.html", title="Einstellungen", body="Einstellungen.")


# =============================================================================
# Suche (Demo – Endpunktname "search" für Navbar)
# =============================================================================

@app.get("/search", endpoint="search")
@login_required
def search_get():
    # Ergebnisse vom letzten POST (aus Session) anzeigen
    results = session.pop("search_results", None)
    terms = session.pop("search_terms", None)
    return safe_render("search.html", title="Suche", results=results, terms=terms)

@app.post("/search")
@login_required
def search_post():
    # bis zu 3 Suchbegriffe einsammeln
    raw = [
        (request.form.get("q1") or "").strip(),
        (request.form.get("q2") or "").strip(),
        (request.form.get("q3") or "").strip(),
    ]
    terms = [t for t in raw if t]
    if not terms:
        flash("Bitte mindestens einen Suchbegriff eingeben.", "warning")
        return redirect(url_for("search"))

    # Limit je nach Premium-Status
    per_term_limit = FREE_SEARCH_LIMIT
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT is_premium FROM users WHERE id = ?", (session["user_id"],))
        row = cur.fetchone()
        if row and row["is_premium"]:
            per_term_limit = PREMIUM_SEARCH_LIMIT
    except Exception:
        pass

    # Demo-Ergebnisse (Platzhalter). Hier später eBay-API anschließen.
    results = []
    for term in terms:
        items = []
        for i in range(per_term_limit):
            items.append({
                "title": f"Demo-Ergebnis für „{term}“",
                "price": "9,99 €",
                "url": "https://www.ebay.de/",
                "image": None,
                "term": term,
            })
        results.append({"term": term, "items": items})

    # Für GET-Render in die Session legen
    session["search_results"] = results
    session["search_terms"] = terms
    return redirect(url_for("search"))


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
            flash("Login erfolgreich!", "success")
            return redirect(url_for("dashboard"))
        flash("Ungültige E‑Mail oder Passwort.", "danger")
        return redirect(url_for("login"))
    return safe_render("login.html", title="Login", body="Login Formular.")

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
            "EBAY_APP_ID_set": bool(EBAY_APP_ID),
            "FREE_SEARCH_LIMIT": FREE_SEARCH_LIMIT,
            "PREMIUM_SEARCH_LIMIT": PREMIUM_SEARCH_LIMIT,
            "STRIPE_PRICE_PRO": bool(STRIPE_PRICE_PRO),
            "STRIPE_SECRET_KEY_set": bool(os.getenv("STRIPE_SECRET_KEY")),
            "STRIPE_WEBHOOK_SECRET_set": bool(os.getenv("STRIPE_WEBHOOK_SECRET")),
        }
    })

@app.get("/_debug/stripe")
def debug_stripe():
    out = {"ok": False, "can_call_api": False, "price_ok": None, "error": None}
    try:
        if not stripe.api_key:
            raise RuntimeError("Kein STRIPE_SECRET_KEY gesetzt.")
        stripe.Balance.retrieve()
        out["can_call_api"] = True
        if STRIPE_PRICE_PRO:
            try:
                stripe.Price.retrieve(STRIPE_PRICE_PRO)
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
    # Vermeidet 404‑Spam im Log
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
# Main (lokal)
# =============================================================================

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=True)