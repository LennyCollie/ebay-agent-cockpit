
# =============================================================================
# Imports
# =============================================================================
import os
import sqlite3
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, g, jsonify, Response
)
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv  # lokal praktisch; auf Render ignoriert
import stripe


# =============================================================================
# Konfiguration (Env laden, Keys, Pfade)
# =============================================================================
load_dotenv()  # nur lokal relevant

# Render ist read-only; nur /tmp ist schreibbar. Lokal gern "database.db".
DB_PATH = (
    os.getenv("DATABASE_FILE")
    or os.getenv("DATABASE_URL")
    or ("/tmp/agent.db" if os.getenv("RENDER") or os.getenv("DYNO") else "database.db")
)

SECRET_KEY = os.getenv("SECRET_KEY", "dev_key")

# Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
PRICE_ID      = os.getenv("STRIPE_PRICE_PRO")       # z.B. price_...
SUCCESS_URL   = os.getenv("STRIPE_SUCCESS_URL")
CANCEL_URL    = os.getenv("STRIPE_CANCEL_URL")


# =============================================================================
# Flask App
# =============================================================================
app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY


# =============================================================================
# Template-Fallback (verhindert 500 bei fehlenden Dateien)
# =============================================================================
def safe_render(template_name: str, **ctx):
    """
    Versucht ein Template zu rendern; wenn es fehlt, kommt ein schlanker HTML‑Fallback.
    """
    try:
        return render_template(template_name, **ctx)
    except Exception:
        title = ctx.get("title") or template_name
        body  = ctx.get("body") or ""
        return Response(f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><title>{title}</title></head>
<body style="font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:900px;margin:40px auto;line-height:1.5">
<h1>{title}</h1>
<p>{body}</p>
<p style="margin-top:24px"><a href="{url_for('public_home')}">Zur Startseite</a></p>
</body></html>""", mimetype="text/html")


# =============================================================================
# DB-Helfer (Connection, Schema, Seed)
# =============================================================================
def get_db():
    """
    Öffnet/verwendet eine SQLite-Connection für den Request (unter /tmp auf Render).
    """
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
    """
    Legt users an (falls fehlt) und ergänzt fehlende Spalten.
    """
    db  = get_db()
    cur = db.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email      TEXT UNIQUE NOT NULL,
            password   TEXT,
            is_premium INTEGER DEFAULT 0,
            created_at TEXT   DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # fehlende Spalten ergänzen
    cur.execute("PRAGMA table_info(users)")
    cols = {r["name"] for r in cur.fetchall()}
    if "password" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN password TEXT")
    if "is_premium" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN is_premium INTEGER DEFAULT 0")
    if "created_at" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN created_at TEXT DEFAULT CURRENT_TIMESTAMP")
    db.commit()

def seed_user():
    """
    Optional: Testnutzer anlegen (Env: SEED_USER_EMAIL, SEED_USER_PASSWORD).
    """
    email = (os.getenv("SEED_USER_EMAIL") or "").strip().lower()
    pw    = (os.getenv("SEED_USER_PASSWORD") or "").strip()
    if not email or not pw:
        return
    db  = get_db()
    cur = db.cursor()
    cur.execute("SELECT id FROM users WHERE email = ?", (email,))
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO users (email, password, is_premium) VALUES (?, ?, 1)",
            (email, generate_password_hash(pw)),
        )
        db.commit()

# Einmalige Initialisierung
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

# favicon: vermeidet 404/500 im Log
@app.get("/favicon.ico")
def favicon():
    return Response(status=204)


# =============================================================================
# Öffentliche Seiten & Checkout
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
    # hier könntest du auch dynamisch von Stripe lesen, für jetzt statisch:
    return render_template("public_pricing.html", price_label="9,99 €")


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
                cancel_url=CANCEL_URL or url_for("public_pricing", _external=True),
                allow_promotion_codes=True,
            )
            return redirect(session_obj.url, code=303)
        except Exception as e:
            flash(f"Stripe‑Fehler: {e}", "danger")
            return redirect(url_for("public_checkout"))
    # GET
    return safe_render("public_checkout.html", title="Checkout", body="Checkout Formular.")

@app.get("/checkout/success")
def checkout_success():
    return safe_render(
        "success.html",
        title="Vielen Dank!",
        body="Dein Kauf war erfolgreich. Dein Premium‑Zugang ist jetzt freigeschaltet."
    )


# =============================================================================
# Dashboard & einfache Seiten (geschützt)
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

@app.get("/sync")
@login_required
def sync_get():
    flash("Sync gestartet (Demo).", "info")
    return redirect(url_for("dashboard"))


# =============================================================================
# Auth (Login/Registrierung/Logout)
# =============================================================================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email    = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        if not email or not password:
            flash("Bitte E‑Mail und Passwort eingeben.", "warning")
            return redirect(url_for("login"))
        db  = get_db()
        cur = db.cursor()
        cur.execute("SELECT id, password FROM users WHERE email = ?", (email,))
        row = cur.fetchone()
        if row and check_password_hash(row["password"], password):
            session["user_id"]    = row["id"]
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
        db  = get_db()
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
# Fehlerseiten
# =============================================================================
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