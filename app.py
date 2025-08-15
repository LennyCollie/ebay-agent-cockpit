# app.py
import os
import sqlite3
from pathlib import Path
from typing import Optional, List, Dict

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, abort
)

# -------------------------------------------------------------------
# Optionale Stripe-Integration – fällt sauber zurück, wenn nicht da
# -------------------------------------------------------------------
STRIPE_OK = False
stripe = None
try:
    import stripe as _stripe
    stripe = _stripe
    STRIPE_OK = True
except Exception:
    STRIPE_OK = False

# -------------------------------------------------------------------
# App & Config
# -------------------------------------------------------------------
def as_bool(val: Optional[str]) -> bool:
    return str(val).lower() in {"1", "true", "yes", "on"}

app = Flask(__name__)

app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-me")

# Datenbank: Pfad aus ENV (Render: sqlite:///instance/db.sqlite3)
DB_URL = os.getenv("DB_PATH", "sqlite:///instance/db.sqlite3")

def _sqlite_file_from_url(url: str) -> Path:
    # erlaubt: "sqlite:///instance/db.sqlite3" oder absolute Pfade
    if url.startswith("sqlite:///"):
        rel = url.replace("sqlite:///", "", 1)
        return Path(rel)
    return Path(url)

DB_FILE = _sqlite_file_from_url(DB_URL)
DB_FILE.parent.mkdir(parents=True, exist_ok=True)

FREE_SEARCH_LIMIT = int(os.getenv("FREE_SEARCH_LIMIT", "3"))
PREMIUM_SEARCH_LIMIT = int(os.getenv("PREMIUM_SEARCH_LIMIT", "10"))

# Stripe Keys (optional)
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PRICE_PRO = os.getenv("STRIPE_PRICE_PRO", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
if STRIPE_OK and STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

# eBay: (später) – Platzhalter für globale Site-ID
EBAY_GLOBAL_ID = os.getenv("EBAY_GLOBAL_ID", "EBAY-DE")

# -------------------------------------------------------------------
# DB Helpers
# -------------------------------------------------------------------
def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    return conn

def init_db() -> None:
    conn = get_db()
    cur = conn.cursor()
    # minimal: users (ohne aufwändiges Schema; Premium-Flag vorhanden)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,         -- demo: Klartext; bei Bedarf Hash nutzen
            is_premium INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.commit()
    conn.close()

@app.before_first_request
def _ensure_db():
    init_db()

# -------------------------------------------------------------------
# Template-Helfer – sicherer Render mit Fallback-HTML
# -------------------------------------------------------------------
def safe_render(template_name: str, **ctx):
    """
    Rendert ein Template, fällt aber auf minimalen HTML-Stub zurück,
    wenn das Template (noch) fehlt – so bricht nichts.
    """
    try:
        return render_template(template_name, **ctx)
    except Exception:
        # sehr schlanker Fallback – nur das Wichtigste
        title = ctx.get("title", "ebay-agent-cockpit")
        body = ctx.get("body", "")
        return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet"></head>
<body class="container py-4">
<div class="alert alert-warning">Template <code>{template_name}</code> nicht gefunden – Fallback aktiv.</div>
<h1 class="h4">{title}</h1>
<div class="mb-3">{body}</div>
<p><a class="btn btn-primary" href="{url_for('public_home')}">Zur Startseite</a></p>
</body></html>"""

# -------------------------------------------------------------------
# Auth – extrem minimal für Demo-Zwecke
# -------------------------------------------------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return safe_render("register.html", title="Registrieren")

    email = (request.form.get("email") or "").strip().lower()
    password = (request.form.get("password") or "").strip()
    if not email or not password:
        flash("Bitte E‑Mail und Passwort angeben.", "warning")
        return redirect(url_for("register"))

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO users (email, password, is_premium) VALUES (?, ?, ?)",
                    (email, password, 0))
        conn.commit()
    except sqlite3.IntegrityError:
        flash("Diese E‑Mail ist bereits registriert.", "warning")
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
    cur = conn.cursor()
    cur.execute("SELECT id, password, is_premium FROM users WHERE email = ?", (email,))
    row = cur.fetchone()
    conn.close()

    if not row or row["password"] != password:  # Demo! (kein Hash)
        flash("E‑Mail oder Passwort ist falsch.", "warning")
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

# -------------------------------------------------------------------
# Public: Startseite, Preise
# -------------------------------------------------------------------
@app.route("/")
def root_redirect():
    # klare Startseite unter /public
    return redirect(url_for("public_home"))

@app.route("/public")
def public_home():
    return safe_render("public_home.html", title="Start – ebay-agent-cockpit")

@app.route("/pricing")
def public_pricing():
    return safe_render("public_pricing.html", title="Preise – ebay-agent-cockpit")

# -------------------------------------------------------------------
# Dashboard (geschützt – sehr minimal)
# -------------------------------------------------------------------
@app.route("/dashboard")
def dashboard():
    if not session.get("user_id"):
        flash("Bitte einloggen.", "info")
        return redirect(url_for("login"))
    return safe_render("dashboard.html", title="Dashboard")

# -------------------------------------------------------------------
# Suche – GET Formular, POST Ergebnisse (Demo bis eBay-API dran ist)
# -------------------------------------------------------------------
def _user_search_limit() -> int:
    if session.get("user_id") and session.get("is_premium"):
        return PREMIUM_SEARCH_LIMIT
    return FREE_SEARCH_LIMIT

def _demo_results_for(terms: List[str], limit_per_term: int) -> List[Dict]:
    results: List[Dict] = []
    for t in terms:
        # 1 Demo-Ergebnis pro Term (bis echte eBay-API angeschlossen ist)
        results.append({
            "title": f'Demo-Ergebnis für „{t}“',
            "price": "9,99 €",
            "url": f"https://www.ebay.de/sch/i.html?_nkw={t}",
            "img": f"https://via.placeholder.com/64x64?text=%20",
            "term": t,
        })
    return results[: (limit_per_term * max(1, len(terms)))]

@app.route("/search", methods=["GET", "POST"])
def search():
    # Erwartet Templates:
    #  - search.html  (Formular mit 3 Feldern: q1, q2, q3 → POST an /search)
    #  - search_results.html (tabellarische Darstellung der 'results')
    if request.method == "GET":
        return safe_render("search.html", title="Suche", body="Suche starten.")

    # POST – Terms einsammeln
    raw = [
        (request.form.get("q1") or "").strip(),
        (request.form.get("q2") or "").strip(),
        (request.form.get("q3") or "").strip(),
    ]
    terms = [t for t in raw if t]
    if not terms:
        flash("Bitte mindestens einen Suchbegriff eingeben.", "warning")
        return redirect(url_for("search"))

    per_term_limit = _user_search_limit()

    # TODO (später): echte eBay-API hier aufrufen
    results = _demo_results_for(terms, per_term_limit)

    return safe_render(
        "search_results.html",
        title="Suchergebnisse",
        terms=terms,
        results=results
    )

# -------------------------------------------------------------------
# Stripe Checkout (optional) – robust mit Fallback
# -------------------------------------------------------------------
@app.route("/checkout", methods=["POST"])
def public_checkout():
    """
    Erwartet: POST (z. B. von /pricing) → Stripe Checkout Session
    """
    if not STRIPE_OK or not STRIPE_SECRET_KEY or not STRIPE_PRICE_PRO:
        flash("Stripe ist nicht konfiguriert.", "warning")
        return redirect(url_for("public_pricing"))

    try:
        # success/cancel-URLs
        success_url = url_for("checkout_success", _external=True)
        cancel_url = url_for("checkout_cancel", _external=True)

        session_stripe = stripe.checkout.Session.create(
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
    flash("Dein Premium‑Zugang ist jetzt freigeschaltet.", "success")
    # In einer echten App würdest du hier den User in der DB auf premium stellen
    return safe_render("success.html", title="Erfolg")

@app.route("/checkout/cancel")
def checkout_cancel():
    flash("Vorgang abgebrochen.", "info")
    return redirect(url_for("public_pricing"))

# -------------------------------------------------------------------
# Debug/Health
# -------------------------------------------------------------------
@app.route("/debug")
def debug_env():
    data = {
        "env": {
            "DB_PATH": DB_URL,
            "FREE_SEARCH_LIMIT": FREE_SEARCH_LIMIT,
            "PREMIUM_SEARCH_LIMIT": PREMIUM_SEARCH_LIMIT,
            "STRIPE_PRICE_PRO": "true" if STRIPE_PRICE_PRO else "false",
            "STRIPE_SECRET_KEY_set": "true" if STRIPE_SECRET_KEY else "false",
            "STRIPE_WEBHOOK_SECRET_set": "true" if STRIPE_WEBHOOK_SECRET else "false",
            "ok": "true",
        }
    }
    return jsonify(data)

@app.route("/_debug/stripe")
def debug_stripe():
    if not STRIPE_OK:
        abort(404)
    ok = bool(STRIPE_SECRET_KEY and STRIPE_PRICE_PRO)
    return jsonify({"stripe_imported": True, "configured": ok})

# -------------------------------------------------------------------
# Run (nur lokal)
# -------------------------------------------------------------------
if __name__ == "__main__":
    # Für lokales Testen; Render startet via gunicorn
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=as_bool(os.getenv("FLASK_DEBUG", "1")))