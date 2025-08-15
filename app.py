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
# Grund-Config
# =============================================================================

load_dotenv()  # lokal .env laden; auf Render egal

# Render: nur /tmp ist beschreibbar
DB_PATH = (
    os.getenv("DATABASE_FILE")
    or os.getenv("DATABASE_URL")
    or ("/tmp/agent.db" if os.getenv("RENDER") or os.getenv("DYNO") else "database.db")
)

SECRET_KEY = os.getenv("SECRET_KEY", "dev_key_change_me")

# Suche: Limits
FREE_SEARCH_LIMIT = int(os.getenv("FREE_SEARCH_LIMIT", "3"))
PREMIUM_SEARCH_LIMIT = int(os.getenv("PREMIUM_SEARCH_LIMIT", "10"))
EBAY_APP_ID = os.getenv("EBAY_APP_ID", "").strip()  # optional (für echte API später)
EBAY_GLOBAL_ID = os.getenv("EBAY_GLOBAL_ID", "EBAY-DE")

# Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY") or ""
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_PRO") or ""
STRIPE_SUCCESS_URL = os.getenv("STRIPE_SUCCESS_URL") or ""
STRIPE_CANCEL_URL = os.getenv("STRIPE_CANCEL_URL") or ""

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY


# =============================================================================
# Hilfsfunktionen
# =============================================================================

def safe_render(template_name: str, **ctx):
    """Template rendern – wenn es fehlt, eine schlichte Seite liefern."""
    try:
        return render_template(template_name, **ctx)
    except Exception:
        title = ctx.get("title") or template_name
        body = ctx.get("body") or ""
        start = url_for("public_home")
        return Response(
            f"""<!doctype html><meta charset="utf-8">
            <title>{title}</title>
            <body style="font-family:system-ui;max-width:900px;margin:40px auto;line-height:1.5">
            <h1>{title}</h1><p>{body}</p>
            <p style="margin-top:24px"><a href="{start}">Zur Startseite</a></p>
            </body>""",
            mimetype="text/html"
        )


def get_db():
    """pro-Request SQLite‑Connection; Verzeichnis ggf. anlegen."""
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
    """Minimal-Tabellen anlegen/ergänzen."""
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
    # alte DBs upgraden (idempotent)
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
    """Optional Test-User (SEED_USER_EMAIL / SEED_USER_PASSWORD)."""
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
            (email, generate_password_hash(pw))
        )
        db.commit()


_initialized = False
@app.before_request
def _init_once():
    """Schema/Seed nur 1× pro Prozess."""
    global _initialized
    if not _initialized:
        ensure_schema()
        seed_user()
        _initialized = True


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Bitte einloggen.", "info")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def current_search_limit() -> int:
    """Welches per-term Limit? premium vs. free."""
    limit = FREE_SEARCH_LIMIT
    try:
        if session.get("user_id"):
            db = get_db()
            cur = db.cursor()
            cur.execute("SELECT is_premium FROM users WHERE id = ?", (session["user_id"],))
            row = cur.fetchone()
            if row and row["is_premium"]:
                limit = PREMIUM_SEARCH_LIMIT
    except Exception:
        pass
    return limit


def parse_terms_from_form(limit: int) -> list[str]:
    """
    Erwartet Felder q1, q2, q3 (oder term1..termN). Liefert bereinigte Liste.
    """
    terms = []
    # bevorzugt q1..qN
    for key in ("q1", "q2", "q3"):
        t = (request.form.get(key) or "").strip()
        if t:
            terms.append(t)
    # Fallback: term1..termN
    i = 1
    while len(terms) < limit:
        t = (request.form.get(f"term{i}") or "").strip()
        if not t:
            break
        terms.append(t)
        i += 1
    # Duplikate entfernen, leer raus
    seen = set()
    cleaned = []
    for t in terms:
        if t and t.lower() not in seen:
            seen.add(t.lower())
            cleaned.append(t)
    return cleaned[:3]  # aktuell max. 3 parallele Begriffe


def build_demo_results(terms: list[str]) -> list[dict]:
    """Demo-Ergebnisse (bis echte eBay-API angeschlossen ist)."""
    results = []
    for term in terms:
        results.append({
            "title": f"Demo‑Ergebnis für „{term}“",
            "price": "9,99 €",
            "url": f"https://www.ebay.de/sch/i.html?_nkw={term}",
            "image": "https://via.placeholder.com/64x48?text=%F0%9F%9B%92",
            "term": term,
        })
    return results


# =============================================================================
# Öffentliche Seiten
# =============================================================================

@app.get("/public")
def public_home():
    return safe_render("public_home.html", title="Start", body="Startseite.")

@app.get("/pricing")
def public_pricing():
    return safe_render("public_pricing.html", title="Preise", body="Preisseite.")

@app.route("/checkout", methods=["GET", "POST"])
def public_checkout():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip() or None
        if not stripe.api_key or not STRIPE_PRICE_ID:
            flash("Stripe ist nicht konfiguriert.", "warning")
            return redirect(url_for("public_pricing"))
        try:
            session_obj = stripe.checkout.Session.create(
                mode="subscription",
                line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
                customer_email=email,
                success_url=STRIPE_SUCCESS_URL or url_for("checkout_success", _external=True),
                cancel_url=STRIPE_CANCEL_URL or url_for("public_pricing", _external=True),
                allow_promotion_codes=True,
            )
            return redirect(session_obj.url, code=303)
        except Exception as e:
            flash(f"Stripe‑Fehler: {e}", "danger")
            return redirect(url_for("public_pricing"))
    # GET
    return safe_render("public_checkout.html", title="Checkout", body="Checkout")


@app.get("/checkout/success")
def checkout_success():
    return safe_render("success.html", title="Erfolg", body="Dein Premium‑Zugang ist jetzt freigeschaltet.")


# =============================================================================
# Suche (GET: Formular, POST: Ergebnisse)
# =============================================================================

@app.route("/search", methods=["GET", "POST"])
def search():
    if request.method == "GET":
        # leeres Formular
        return safe_render("search.html", title="Suche", body="Suche starten.")

    # POST
    terms = parse_terms_from_form(limit=3)
    if not terms:
        flash("Bitte mindestens einen Suchbegriff eingeben.", "warning")
        return redirect(url_for("search"))

    per_term_limit = current_search_limit()

    # Hier später echte eBay API verwenden (EBAY_APP_ID prüfen)
    # Bis dahin: Demo‑Ergebnisse erzeugen:
    results = build_demo_results(terms)

    # Ergebnisse rendern
    return safe_render(
        "search_results.html",
        title="Suchergebnisse",
        terms=terms,
        per_term_limit=per_term_limit,
        results=results
    )


# =============================================================================
# Dashboard & Basics (Login nötig)
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
    return safe_render("login.html", title="Login", body="Login‑Formular.")

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
            (email, generate_password_hash(password))
        )
        db.commit()
        flash("Registrierung erfolgreich. Bitte einloggen.", "success")
        return redirect(url_for("login"))
    return safe_render("register.html", title="Registrieren", body="Registrieren.")

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
            "STRIPE_PRICE_PRO": STRIPE_PRICE_ID,
            "STRIPE_SECRET_KEY_set": bool(stripe.api_key),
            "STRIPE_WEBHOOK_SECRET_set": bool(os.getenv("STRIPE_WEBHOOK_SECRET")),
        }
    })

@app.get("/_debug/stripe")
def _debug_stripe():
    out = {"ok": False, "can_call_api": False, "price_ok": None, "error": None}
    try:
        if stripe.api_key:
            stripe.Balance.retrieve()
            out["can_call_api"] = True
            if STRIPE_PRICE_ID:
                try:
                    stripe.Price.retrieve(STRIPE_PRICE_ID)
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
    return safe_render("404.html", title="404 – Seite nicht gefunden", body="Upps! Diese Adresse gibt es nicht."), 404

@app.errorhandler(500)
def _500(e):
    return safe_render("500.html", title="500 – Fehler", body="Interner Fehler."), 500


# =============================================================================
# Main (lokal)
# =============================================================================

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=True)