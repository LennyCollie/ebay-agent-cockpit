# app.py
import os
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, abort
)

# ------------------------------------------------------------
# Optionale Stripe-Integration – fällt sauber zurück, wenn nicht vorhanden
# ------------------------------------------------------------
STRIPE_OK = False
stripe = None
try:
    import stripe as _stripe  # type: ignore
    stripe = _stripe
    STRIPE_OK = True
except Exception:
    STRIPE_OK = False


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def as_bool(val: Optional[str]) -> bool:
    return str(val).strip().lower() in {"1", "true", "yes", "on"}


def _sqlite_file_from_url(url: str) -> Path:
    """
    Erlaubt sowohl "sqlite:///relative/pfad.db" als auch absolute Pfade.
    """
    if url.startswith("sqlite:///"):
        rel = url.replace("sqlite:///", "", 1)
        return Path(rel)
    return Path(url)


# ------------------------------------------------------------
# App & Basis-Config
# ------------------------------------------------------------
app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
app.permanent_session_lifetime = timedelta(days=30)

# Datenbank (Datei wird bei Bedarf angelegt)
DB_URL = os.getenv("DB_PATH", "sqlite:///instance/db.sqlite3")
DB_FILE = _sqlite_file_from_url(DB_URL)
DB_FILE.parent.mkdir(parents=True, exist_ok=True)

# Limits
FREE_SEARCH_LIMIT = int(os.getenv("FREE_SEARCH_LIMIT", "3"))
PREMIUM_SEARCH_LIMIT = int(os.getenv("PREMIUM_SEARCH_LIMIT", "10"))

# --- Neu: Limits automatisch in allen Templates verfügbar machen ---
@app.context_processor
def inject_limits():
    return {
        "FREE_SEARCH_LIMIT": FREE_SEARCH_LIMIT,
        "PREMIUM_SEARCH_LIMIT": PREMIUM_SEARCH_LIMIT,
    }

# Stripe Keys (optional)
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PRICE_PRO = os.getenv("STRIPE_PRICE_PRO", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
if STRIPE_OK and STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY  # type: ignore


# ------------------------------------------------------------
# DB Helpers
# ------------------------------------------------------------
def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_FILE), detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,         -- Demo: Klartext (für Produktion Hash!)
            is_premium INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.commit()
    conn.close()


# Initialisieren (Flask 3: kein before_first_request mehr verwenden)
try:
    init_db()
except Exception as e:
    print(f"[init_db] {e}")


# ------------------------------------------------------------
# Session-Defaults (stabil gegen leere/neu gesetzte Sessions)
# ------------------------------------------------------------
@app.before_request
def _ensure_session_defaults():
    session.permanent = True
    session.setdefault("free_search_count", 0)
    session.setdefault("is_premium", False)
    session.setdefault("user_email", None)


# ------------------------------------------------------------
# Template-Helfer – sicherer Render mit Fallback-HTML
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
# Auth (Demo: minimal)
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
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (email, password, is_premium) VALUES (?, ?, ?)",
            (email, password, 0)
        )
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
    cur = conn.cursor()
    cur.execute("SELECT id, password, is_premium FROM users WHERE email = ?", (email,))
    row = cur.fetchone()
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
# Public / Dashboard
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


# ------------------------------------------------------------
# Kostenlos starten (Gastmodus) + Limits
# ------------------------------------------------------------
@app.route("/start-free")
@app.route("/free")
def start_free():
    session["is_premium"] = False
    session["free_search_count"] = 0
    if not session.get("user_id"):
        session["user_email"] = "guest"
    flash(f"Kostenloser Modus aktiv. Du hast {FREE_SEARCH_LIMIT} Suchen frei.", "info")
    return redirect(url_for("search"))


# ------------------------------------------------------------
# Suche – GET Formular, POST Ergebnisse (Demo bis eBay-API angebunden ist)
# ------------------------------------------------------------
def _user_search_limit() -> int:
    return PREMIUM_SEARCH_LIMIT if session.get("is_premium", False) else FREE_SEARCH_LIMIT


def _demo_results_for(terms: List[str], limit_per_term: int) -> List[Dict]:
    results: List[Dict] = []
    for t in terms:
        results.append({
            "title": f'Demo-Ergebnis für „{t}“',
            "price": "9,99 €",
            "url": f"https://www.ebay.de/sch/i.html?_nkw={t}",
            "img": "https://via.placeholder.com/64x64?text=%20",
            "term": t,
        })
    # für Demo: max. limit_per_term * anzahl_terms
    return results[: (limit_per_term * max(1, len(terms)))]


@app.route("/search", methods=["GET", "POST"])
def search():
    if request.method == "GET":
        return safe_render("search.html", title="Suche", body="Suche starten.")

    # POST – Begriffe einsammeln
    raw = [
        (request.form.get("q1") or "").strip(),
        (request.form.get("q2") or "").strip(),
        (request.form.get("q3") or "").strip(),
    ]
    terms = [t for t in raw if t]
    if not terms:
        flash("Bitte mindestens einen Suchbegriff eingeben.", "warning")
        return redirect(url_for("search"))

    # Free-Limit prüfen (nur wenn NICHT premium)
    if not session.get("is_premium", False):
        count = int(session.get("free_search_count", 0))
        if count >= FREE_SEARCH_LIMIT:
            flash(f"Kostenloses Limit ({FREE_SEARCH_LIMIT}) erreicht – bitte Upgrade buchen.", "warning")
            return redirect(url_for("public_pricing"))
        session["free_search_count"] = count + 1

    per_term_limit = _user_search_limit()
    results = _demo_results_for(terms, per_term_limit)

    return safe_render(
        "search_results.html",
        title="Suchergebnisse",
        terms=terms,
        results=results
    )


# ------------------------------------------------------------
# Stripe Checkout (optional, robust)
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
# Debug/Health
# ------------------------------------------------------------
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
        },
        "session": {
            "user_email": session.get("user_email"),
            "is_premium": session.get("is_premium"),
            "free_search_count": session.get("free_search_count"),
        }
    }
    return jsonify(data)


@app.route("/_debug/session")
def _debug_session():
    return jsonify(dict(session))


@app.route("/_debug/reset_free")
def _debug_reset_free():
    session["free_search_count"] = 0
    flash("Freies Such-Limit zurückgesetzt.", "info")
    return redirect(url_for("public_home"))


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