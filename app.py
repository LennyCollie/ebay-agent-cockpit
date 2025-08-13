
import os
import sqlite3
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, g, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import stripe

# ---------------------------------------------------------------------
# .env laden & Stripe konfigurieren
# ---------------------------------------------------------------------
load_dotenv()
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# ---------------------------------------------------------------------
# Flask App
# ---------------------------------------------------------------------
app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev_key")

# Performance-Extras (optional)
try:
    from performance_snippets import enable_minify, strong_static_cache
    enable_minify(app)        # HTML/CSS/JS-Minify
    strong_static_cache(app)  # Lange Cache-Dauer für static/
except Exception:
    pass

# SQLite-Datei (im Projekt-Root). Auf Render ephemer – für Tests ok.
DB_PATH = os.getenv("DATABASE_FILE", "database.db")

# ---------------------------------------------------------------------
# DB-Helfer
# ---------------------------------------------------------------------
def get_db():
    """Verbindet sich mit SQLite und gibt die Connection zurück (pro Request gecached)."""
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def ensure_schema():
    """Sicherstellen, dass Tabelle 'users' mit erwarteten Spalten existiert."""
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    

    cur.execute("PRAGMA table_info(users)")
    cols = {row["name"] for row in cur.fetchall()}

    # Fehlende Spalten ergänzen (mit Default, weil SQLite sonst NOT NULL nicht zulässt)
    if "password" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN password TEXT DEFAULT ''")
    if "created_at" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN created_at TEXT DEFAULT CURRENT_TIMESTAMP")
    # 🔽 NEU:
    if "is_premium" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN is_premium INTEGER DEFAULT 0")
    db.commit()

def seed_user():
    """Optionalen Testnutzer aus ENV anlegen (SEED_USER_EMAIL/SEED_USER_PASSWORD)."""
    email = (os.getenv("SEED_USER_EMAIL") or "").strip()
    pw = (os.getenv("SEED_USER_PASSWORD") or "").strip()
    if not email or not pw:
        return
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id FROM users WHERE email = ?", (email,))
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO users (email, password) VALUES (?, ?)",
            (email, generate_password_hash(pw)),
        )
        db.commit()

# Einmalige Initialisierung beim ersten Request (oder über /ping)
_initialized = False
@app.before_request
def _init_once():
    global _initialized
    if not _initialized:
        ensure_schema()
        seed_user()
        _initialized = True

# ---------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Bitte einloggen.")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

def env_required(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Fehlende Umgebungsvariable: {name}")
    return val

# ---------------------------------------------------------------------
# Öffentliche Seiten
# ---------------------------------------------------------------------
@app.get("/public")
def public_home():
    return render_template("public_home.html")

@app.get("/pricing")
def public_pricing():
    return render_template("public_pricing.html")

# ---------------------------------------------------------------------
# Stripe Checkout (Subscription)
# ---------------------------------------------------------------------
@app.route("/checkout", methods=["GET", "POST"])
def public_checkout():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        try:
            session_obj = stripe.checkout.Session.create(
                mode="subscription",
                line_items=[{"price": env_required("STRIPE_PRICE_PRO"), "quantity": 1}],
                customer_email=email or None,
                success_url=os.getenv("STRIPE_SUCCESS_URL", url_for("checkout_success", _external=True)),
                cancel_url=os.getenv("STRIPE_CANCEL_URL", url_for("public_pricing", _external=True)),
                allow_promotion_codes=True,
            )
            return redirect(session_obj.url, code=303)
        except Exception as e:
            flash(f"Stripe-Fehler: {e}", "danger")
            return redirect(url_for("public_checkout"))

    # PUBLISHABLE KEY ans Template (für späteres clientseitiges Stripe)
    return render_template(
        "public_checkout.html",
        STRIPE_PUBLIC_KEY=os.getenv("STRIPE_PUBLIC_KEY")
    )

@app.get("/checkout/success")
def checkout_success():
    return render_template("success.html")


# ---------------------------------------------------------------------
# Dashboard & Basis
# ---------------------------------------------------------------------
@app.get("/ping")
def ping():
    ensure_schema()
    return "pong"

@app.get("/")
@login_required
def dashboard():
    return render_template("dashboard.html")

# ---------------------------------------------------------------------
# Debug-Helfer
# ---------------------------------------------------------------------
@app.get("/debug")
def debug_env():
    return jsonify({
        "ok": True,
        "env": {
            "STRIPE_SECRET_KEY_set": bool(os.getenv("STRIPE_SECRET_KEY")),
            "STRIPE_PUBLIC_KEY_set": bool(os.getenv("STRIPE_PUBLIC_KEY")),
            "STRIPE_PRICE_PRO": os.getenv("STRIPE_PRICE_PRO"),
        }
    })

@app.get("/_debug/stripe")
def debug_stripe():
    out = {"ok": False, "can_call_api": False, "price_ok": None, "error": None}
    try:
        # einfacher API-Call – schlägt bei falschem KEY fehl
        stripe.Balance.retrieve()
        out["can_call_api"] = True
        pid = os.getenv("STRIPE_PRICE_PRO")
        if pid:
            try:
                stripe.Price.retrieve(pid)
                out["price_ok"] = True
            except Exception as e:
                out["price_ok"] = False
                out["error"] = str(e)
        out["ok"] = out["can_call_api"] and (out["price_ok"] in (True, None))
    except Exception as e:
        out["error"] = str(e)
    return jsonify(out)

@app.get("/debug")
def debug_env():
    return jsonify({
        "ok": True,
        "env": {
            "STRIPE_SECRET_KEY_set": bool(os.getenv("STRIPE_SECRET_KEY")),
            "STRIPE_PUBLIC_KEY_set": bool(os.getenv("STRIPE_PUBLIC_KEY")),
            "STRIPE_PRICE_PRO": os.getenv("STRIPE_PRICE_PRO"),
            "STRIPE_WEBHOOK_SECRET_set": bool(os.getenv("STRIPE_WEBHOOK_SECRET")),  # 🔽 neu
        }
    })

# ---------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        if not email or not password:
            flash("Bitte E-Mail und Passwort eingeben.")
            return redirect(url_for("login"))

        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT id, password FROM users WHERE email = ?", (email,))
        row = cur.fetchone()
        if row and check_password_hash(row["password"], password):
            session["user_id"] = row["id"]
            session["user_email"] = email
            flash("Login erfolgreich!")
            return redirect(url_for("dashboard"))
        flash("Ungültige E-Mail oder Passwort.")
        return redirect(url_for("login"))
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        if not email or not password:
            flash("Bitte E-Mail und Passwort angeben.")
            return redirect(url_for("register"))

        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT id FROM users WHERE email = ?", (email,))
        if cur.fetchone():
            flash("Diese E-Mail ist bereits registriert.")
            return redirect(url_for("register"))

        cur.execute(
            "INSERT INTO users (email, password) VALUES (?, ?)",
            (email, generate_password_hash(password)),
        )
        db.commit()
        flash("Registrierung erfolgreich. Bitte einloggen.")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.get("/logout")
def logout():
    session.clear()
    flash("Logout erfolgreich!")
    return redirect(url_for("login"))

# ---------------------------------------------------------------------
# Settings, Sync (Platzhalter)
# ---------------------------------------------------------------------
@app.get("/sync")
@login_required
def sync_get():
    flash("Sync gestartet (Demo) – Implementierung folgt.")
    return redirect(url_for("dashboard"))

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        flash("Einstellungen gespeichert.")
        return redirect(url_for("settings"))
    return render_template("settings.html")

# ---------------------------------------------------------------------
# Dev-Reset (optional)
# ---------------------------------------------------------------------
@app.post("/_dev_reset_db")
def _dev_reset_db():
    if os.getenv("ALLOW_RESET") != "1":
        return "disabled", 403
    db = get_db()
    cur = db.cursor()
    cur.execute("DROP TABLE IF EXISTS users")
    db.commit()
    ensure_schema()
    return "reset ok"

# Stripe Webhook
# -------------------------
@app.post("/webhook")
def stripe_webhook():
    endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature", "")

    # 1) Signatur/Authentizität prüfen
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    etype = event.get("type")
    data = event.get("data", {}).get("object", {})

    # 2) Relevante Events behandeln
    if etype == "checkout.session.completed":
        # Wir haben im Checkout customer_email gesetzt → hier verfügbar:
        email = (data.get("customer_email") or "").strip().lower()
        if email:
            db = get_db()
            cur = db.cursor()
            cur.execute("UPDATE users SET is_premium = 1 WHERE lower(email)=?", (email,))
            db.commit()

    # Optional: Kündigung / Payment Failed behandeln (nur wenn gewünscht)
    elif etype in ("customer.subscription.deleted", "invoice.payment_failed"):
        # Beispiel (nur wenn du bei Kündigung Premium entziehen willst):
        # customer_id = data.get("customer")
        # -> wenn du später Stripe-Kunden-IDs speicherst, kannst du hier rücksetzen.
        pass

    return jsonify({"status": "ok"}), 200


# ---------------------------------------------------------------------
# Error Pages
# ---------------------------------------------------------------------
@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404

@app.errorhandler(500)
def server_error(e):
    return render_template("500.html"), 500

# ---------------------------------------------------------------------
# Local run (Render nutzt Gunicorn/Procfile mit app:app)
# ---------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
