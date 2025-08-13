
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

# -----------------------------------------------------------------------------
# Setup
# -----------------------------------------------------------------------------
load_dotenv()  # lokal nützlich; auf Render ignoriert
app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev_key")

DB_PATH = os.getenv("DATABASE_FILE", "database.db")

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")  # secret key (test oder live)

# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------
def env_required(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Fehlende Umgebungsvariable: {name}")
    return val

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def ensure_schema():
    """
    users: id, email (unique), password, is_premium (0/1), created_at
    """
    db = get_db()
    cur = db.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            is_premium INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # defensive: Spalten nachziehen, falls alte DB
    cur.execute("PRAGMA table_info(users)")
    cols = {r["name"] for r in cur.fetchall()}
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
            "INSERT INTO users (email, password, is_premium) VALUES (?, ?, 0)",
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

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Bitte einloggen.")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

# -----------------------------------------------------------------------------
# Öffentliche Seiten
# -----------------------------------------------------------------------------
@app.get("/public")
def public_home():
    return render_template("public_home.html")

@app.get("/pricing")
def public_pricing():
    return render_template("public_pricing.html")

# -----------------------------------------------------------------------------
# Checkout (Stripe)
# -----------------------------------------------------------------------------
@app.route("/checkout", methods=["GET", "POST"])
def public_checkout():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        # Erfolg/Abbruch-URLs
        success_url = os.getenv("STRIPE_SUCCESS_URL", url_for("checkout_success", _external=True))
        cancel_url  = os.getenv("STRIPE_CANCEL_URL",  url_for("public_pricing", _external=True))

        try:
            # Subscription-Checkout mit Price-ID aus ENV
            session_obj = stripe.checkout.Session.create(
                mode="subscription",
                line_items=[{"price": env_required("STRIPE_PRICE_PRO"), "quantity": 1}],
                customer_email=email or None,
                success_url=success_url,
                cancel_url=cancel_url,
                allow_promotion_codes=True,
            )
            return redirect(session_obj.url, code=303)
        except Exception as e:
            flash(f"Stripe-Fehler: {e}", "danger")
            return redirect(url_for("public_checkout"))

    # Für späteres clientseitiges Stripe nutzbar:
    return render_template("public_checkout.html",
                           STRIPE_PUBLIC_KEY=os.getenv("STRIPE_PUBLIC_KEY"))

@app.get("/checkout/success")
def checkout_success():
    # Einfache Erfolgsmeldung; Status wird zuverlässig über Webhook gesetzt.
    flash("Zahlung erfolgreich! Dein Zugang wird in Kürze freigeschaltet.")
    return render_template("checkout_success.html")

# -----------------------------------------------------------------------------
# Webhook (Stripe)
# -----------------------------------------------------------------------------
@app.post("/webhook/stripe")
def stripe_webhook():
    """
    Erwartet STRIPE_WEBHOOK_SECRET in den ENVs.
    Reagiert auf checkout.session.completed & invoice.paid
    und setzt users.is_premium=1 anhand der Kunden-E-Mail.
    """
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature")
    endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    try:
        if not endpoint_secret:
            raise ValueError("STRIPE_WEBHOOK_SECRET fehlt")
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    event_type = event["type"]

    def _activate_by_email(email: str):
        if not email:
            return
        db = get_db()
        cur = db.cursor()
        cur.execute("UPDATE users SET is_premium=1 WHERE lower(email)=lower(?)", (email,))
        db.commit()

    try:
        if event_type == "checkout.session.completed":
            sess = event["data"]["object"]
            email = None
            # eine der beiden Quellen sollte vorhanden sein
            if "customer_details" in sess and sess["customer_details"]:
                email = (sess["customer_details"].get("email") or "").strip().lower()
            if not email:
                email = (sess.get("customer_email") or "").strip().lower()
            _activate_by_email(email)

        elif event_type == "invoice.paid":
            inv = event["data"]["object"]
            # Kundendaten ziehen
            cust_id = inv.get("customer")
            email = None
            if cust_id:
                try:
                    cust = stripe.Customer.retrieve(cust_id)
                    email = (cust.get("email") or "").strip().lower()
                except Exception:
                    pass
            _activate_by_email(email)

        # andere Events ignorieren wir leise
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# -----------------------------------------------------------------------------
# App-Bereich
# -----------------------------------------------------------------------------
@app.get("/")
@login_required
def dashboard():
    # User ziehen inkl. Premium-Flag
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT email, is_premium FROM users WHERE id = ?", (session["user_id"],))
    user = cur.fetchone()
    return render_template("dashboard.html", user=user)

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

@app.get("/sync")
@login_required
def sync_get():
    flash("Sync gestartet (Demo).")
    return redirect(url_for("dashboard"))

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        flash("Einstellungen gespeichert.")
        return redirect(url_for("settings"))
    return render_template("settings.html")

# Dev-Helfer (optional & abgesichert)
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

# -----------------------------------------------------------------------------
# Fehlerseiten
# -----------------------------------------------------------------------------
@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404

@app.errorhandler(500)
def server_error(e):
    # Nichts leaken – nur generische Seite
    return render_template("500.html"), 500

# -----------------------------------------------------------------------------
# Debug (einmalig!)
# -----------------------------------------------------------------------------
@app.get("/debug")
def debug_env():
    return jsonify({
        "ok": True,
        "env": {
            "STRIPE_SECRET_KEY_set": bool(os.getenv("STRIPE_SECRET_KEY")),
            "STRIPE_PUBLIC_KEY_set": bool(os.getenv("STRIPE_PUBLIC_KEY")),
            "STRIPE_PRICE_PRO": os.getenv("STRIPE_PRICE_PRO"),
            "STRIPE_WEBHOOK_SECRET_set": bool(os.getenv("STRIPE_WEBHOOK_SECRET")),
        }
    }), 200

@app.get("/_debug/stripe")
def debug_stripe():
    result = {"ok": False, "can_call_api": False, "price_ok": None, "error": None}
    try:
        stripe.Balance.retrieve()  # schlägt bei falschem Secret Key fehl
        result["can_call_api"] = True

        price_id = os.getenv("STRIPE_PRICE_PRO")
        if price_id:
            try:
                stripe.Price.retrieve(price_id)
                result["price_ok"] = True
            except Exception as e:
                result["price_ok"] = False
                result["error"] = str(e)
        result["ok"] = True
    except Exception as e:
        result["error"] = str(e)
    return jsonify(result), 200

# -----------------------------------------------------------------------------
# Ping / lokal starten
# -----------------------------------------------------------------------------
@app.get("/ping")
def ping():
    ensure_schema()
    return "pong"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
