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

load_dotenv()  # lokal: .env lesen (Render ignoriert das automatisch)

# Render ist read-only; nur /tmp ist schreibbar. Lokal z.B. "database.db"
DB_PATH = (
    os.getenv("DATABASE_FILE")
    or os.getenv("DATABASE_URL")
    or ("/tmp/agent.db" if os.getenv("RENDER") or os.getenv("DYNO") else "database.db")
)

SECRET_KEY = os.getenv("SECRET_KEY", "dev_key")

# Stripe Keys / IDs
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")      # LIVE oder TEST
PRICE_ID = os.getenv("STRIPE_PRICE_PRO")             # z.B. price_...
SUCCESS_URL = os.getenv("STRIPE_SUCCESS_URL")        # optional override
CANCEL_URL  = os.getenv("STRIPE_CANCEL_URL")         # optional override
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")  # optional (Webhook)

# =============================================================================
# Flask
# =============================================================================

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY

# =============================================================================
# Safe Template Render (Fallback statt 500 bei fehlender Datei)
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
<body style="font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:900px;margin:40px auto;line-height:1.5">
<h1>{title}</h1>
<p>{body}</p>
<p style="margin-top:24px"><a href="{url_for('public_home')}">Zur Startseite</a></p>
</body></html>""", mimetype="text/html")

# =============================================================================
# DB-Helfer
# =============================================================================

# --- Helpers ---------------------------------------------------------------
def current_user_is_premium() -> bool:
    """Liest das Premium-Flag des eingeloggten Users aus der DB."""
    uid = session.get("user_id")
    if not uid:
        return False
    db = get_db()
    cur = db.execute("SELECT is_premium FROM users WHERE id = ?", (uid,))
    row = cur.fetchone()
    return bool(row and row["is_premium"])

# --- Suche -----------------------------------------------------------------
@app.get("/search")
@login_required
def search_get():
    # Formular liegt auf dem Dashboard – GET führt zurück dorthin
    return redirect(url_for("dashboard"))

@app.post("/search")
@login_required
def search_post():
    """
    Nimmt eine Liste von Suchbegriffen (eine Zeile pro Begriff) entgegen,
    begrenzt Anzahl für Free-User, und zeigt (vorerst Mock-)Ergebnisse.
    """
    raw = (request.form.get("query") or "").strip()
    # Erlaube Komma- ODER Zeilen-getrennt:
    parts = []
    for line in raw.splitlines():
        parts.extend([p.strip() for p in line.split(",")])

    terms = [p for p in (t.strip() for t in parts) if p]  # sauber + ohne Leere
    is_prem = current_user_is_premium()
    limit = 3 if not is_prem else 50  # Premium-Limit kannst du später erhöhen

    if len(terms) > limit:
        terms = terms[:limit]
        flash(f"Free-Version: max. {limit} Suchbegriffe – Rest wurde ignoriert.", "warning")

    if not terms:
        flash("Bitte mindestens einen Suchbegriff eingeben.", "warning")
        return redirect(url_for("dashboard"))

    # TODO: Hier später echte eBay-API-Abfrage einbauen.
    # Vorläufige Mock-Ergebnisse:
    results = [
        {"term": t, "hits": 0, "note": "API folgt"}
        for t in terms
    ]

    return safe_render(
        "search_results.html",
        title="Suche",
        terms=terms,
        results=results,
        is_premium=is_prem,
        limit=limit,
    )

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
    # fehlende Spalten ergänzen (alte DBs)
    cur.execute("PRAGMA table_info(users)")
    cols = {r["name"] for r in cur.fetchall()}
    if "password"  not in cols: cur.execute("ALTER TABLE users ADD COLUMN password TEXT NOT NULL DEFAULT ''")
    if "is_premium" not in cols: cur.execute("ALTER TABLE users ADD COLUMN is_premium INTEGER DEFAULT 0")
    if "created_at" not in cols: cur.execute("ALTER TABLE users ADD COLUMN created_at TEXT DEFAULT CURRENT_TIMESTAMP")
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
# Auth-Decorator
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
    return safe_render("public_home.html", title="Start")

@app.get("/pricing")
def public_pricing():
    return safe_render("public_pricing.html", title="Preise")

@app.route("/checkout", methods=["GET", "POST"])
def public_checkout():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        try:
            if not PRICE_ID:
                raise RuntimeError("Kein STRIPE_PRICE_PRO gesetzt.")
            session_obj = stripe.checkout.Session.create(
                mode="subscription",
                line_items=[{"price": PRICE_ID, "quantity": 1}],
                customer_email=email or None,
                success_url=SUCCESS_URL or url_for("checkout_success", _external=True),
                cancel_url=CANCEL_URL  or url_for("public_pricing", _external=True),
                allow_promotion_codes=True,
            )
            return redirect(session_obj.url, code=303)
        except Exception as e:
            flash(f"Stripe‑Fehler: {e}", "danger")
            return redirect(url_for("public_checkout"))
    # GET
    return safe_render("public_checkout.html", title="Checkout")

@app.get("/checkout/success")
def checkout_success():
    # Hinweis: Premium-Flag wird regulär via Webhook gesetzt (s.u.)
    return safe_render("success.html", title="Vielen Dank!")

# Optional: Webhook (setzt is_premium nach erfolgreichem Checkout)
@app.post("/webhook")
def stripe_webhook():
    if not WEBHOOK_SECRET:
        return "Webhook disabled", 200
    sig_header = request.headers.get("Stripe-Signature", "")
    payload = request.data
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, WEBHOOK_SECRET)
    except Exception as e:
        return f"invalid payload: {e}", 400

    if event.get("type") == "checkout.session.completed":
        obj = event["data"]["object"]
        email = (obj.get("customer_details", {}) or {}).get("email") or obj.get("customer_email")
        if email:
            db = get_db()
            cur = db.cursor()
            # upsert: premium = 1
            cur.execute("""
                INSERT INTO users (email, password, is_premium)
                VALUES (?, '', 1)
                ON CONFLICT(email) DO UPDATE SET is_premium=1
            """, (email,))
            db.commit()
    return "", 200

# =============================================================================
# Dashboard & Seiten (geschützt)
# =============================================================================

@app.get("/")
@login_required
def dashboard():
    return safe_render("dashboard.html", title="Dashboard")

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        flash("Einstellungen gespeichert.", "success")
        return redirect(url_for("settings"))
    return safe_render("settings.html", title="Einstellungen")

# Einfache Suche: Free = max 3 Begriffe, Premium = beliebig
@app.route("/search", methods=["GET", "POST"])
@login_required
def search():
    results = []
    if request.method == "POST":
        raw = (request.form.get("queries") or "").strip()
        # erwartet z.B. "iphone, kamera, smartwatch"
        queries = [q.strip() for q in raw.split(",") if q.strip()]
        # Premium-Check
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT is_premium FROM users WHERE id = ?", (session.get("user_id"),))
        row = cur.fetchone()
        is_premium = bool(row and row["is_premium"])

        if not is_premium and len(queries) > 3:
            queries = queries[:3]
            flash("Free‑Modus: max. 3 Suchbegriffe; für mehr bitte upgraden.", "info")

        # Demo: Stub‑Ergebnisse (hier später eBay‑API anbinden)
        for q in queries:
            results.append({
                "query": q,
                "items": [
                    {"title": f"Beispiel zu {q} – 1", "price": "€ 19,99", "link": "#"},
                    {"title": f"Beispiel zu {q} – 2", "price": "€ 24,99", "link": "#"},
                ]
            })
    # Dein search.html kann 'results' anzeigen, falls vorhanden
    return safe_render("search.html", title="Suche", results=results)

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

# favicon verhindert 404/500 Spam im Log
@app.get("/favicon.ico")
def favicon():
    return Response(status=204)

# Fehlerseiten
@app.errorhandler(404)
def _404(e):
    return safe_render("404.html", title="404", body="Seite nicht gefunden."), 404

@app.errorhandler(500)
def _500(e):
    return safe_render("500.html", title="500", body="Interner Fehler."), 500

# =============================================================================
# Dev-Reset (nur wenn ALLOW_RESET=1)
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
