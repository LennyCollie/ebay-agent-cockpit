import os, sqlite3
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, g, jsonify, Response
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import stripe

# -------------------------------------------------
# Grundkonfiguration
# -------------------------------------------------
load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev_key")

# DB: Render ist read-only -> /tmp verwenden
DB_PATH = (
    os.getenv("DATABASE_FILE")
    or os.getenv("DATABASE_URL")
    or ("/tmp/agent.db" if os.getenv("RENDER") or os.getenv("DYNO") else "database.db")
)

# Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY") or ""
PRICE_ID = os.getenv("STRIPE_PRICE_PRO") or ""
SUCCESS_URL = os.getenv("STRIPE_SUCCESS_URL")  # optional extern
CANCEL_URL = os.getenv("STRIPE_CANCEL_URL")    # optional extern

FREE_SEARCH_LIMIT = int(os.getenv("FREE_SEARCH_LIMIT", "3"))
PREMIUM_SEARCH_LIMIT = int(os.getenv("PREMIUM_SEARCH_LIMIT", "10"))

# -------------------------------------------------
# Hilfsfunktionen
# -------------------------------------------------
def safe_render(template_name: str, **ctx):
    """Render, fällt bei fehlendem Template auf einfache Seite zurück."""
    try:
        return render_template(template_name, **ctx)
    except Exception:
        title = ctx.get("title") or template_name
        body = ctx.get("body") or ""
        home = url_for("public_home")
        return Response(f"""<!doctype html><meta charset="utf-8">
<title>{title}</title>
<body style="font-family:system-ui;max-width:900px;margin:40px auto;line-height:1.5">
<h1>{title}</h1><p>{body}</p>
<p style="margin-top:24px"><a href="{home}">Zur Startseite</a></p>
</body>""", mimetype="text/html")

def get_db():
    if "db" not in g:
        os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
        g.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_exc=None):
    db = g.pop("db", None)
    if db: db.close()

def ensure_schema():
    db = get_db()
    c = db.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL DEFAULT '',
            is_premium INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
    db.commit()

def login_required(view):
    @wraps(view)
    def wrapped(*a, **k):
        if not session.get("user_id"):
            flash("Bitte einloggen.", "info")
            return redirect(url_for("login"))
        return view(*a, **k)
    return wrapped

# einmalige Init
_initialized = False
@app.before_request
def _init_once():
    global _initialized
    if not _initialized:
        ensure_schema()
        _initialized = True

# -------------------------------------------------
# Öffentliche Seiten
# -------------------------------------------------
@app.get("/public")
def public_home():
    return safe_render("public_home.html", title="Start", body="Dein Cockpit für eBay‑Automatisierung.")

@app.get("/pricing")
def public_pricing():
    return safe_render("public_pricing.html", title="Preise", body="Preisseite.")

@app.route("/checkout", methods=["GET", "POST"])
def public_checkout():
    if request.method == "POST":
        email = (request.form.get("email") or session.get("user_email") or "").strip()
        try:
            if not stripe.api_key or not PRICE_ID:
                raise RuntimeError("Stripe nicht konfiguriert (Key/Price).")
            s = stripe.checkout.Session.create(
                mode="subscription",
                line_items=[{"price": PRICE_ID, "quantity": 1}],
                customer_email=email or None,
                success_url=SUCCESS_URL or url_for("checkout_success", _external=True),
                cancel_url=CANCEL_URL or url_for("public_pricing", _external=True),
                allow_promotion_codes=True,
            )
            return redirect(s.url, code=303)
        except Exception as e:
            flash(f"Stripe‑Fehler: {e}", "danger")
            return redirect(url_for("public_checkout"))
    return safe_render("public_checkout.html", title="Checkout", body="Checkout Formular.")

@app.get("/checkout/success")
def checkout_success():
    return safe_render("success.html", title="Vielen Dank!", body="Dein Premium‑Zugang ist jetzt freigeschaltet.")

# -------------------------------------------------
# Auth
# -------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        if not email or not password:
            flash("Bitte E‑Mail und Passwort eingeben.", "warning")
            return redirect(url_for("login"))
        db = get_db(); c = db.cursor()
        c.execute("SELECT id, password FROM users WHERE email = ?", (email,))
        row = c.fetchone()
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
        db = get_db(); c = db.cursor()
        c.execute("SELECT id FROM users WHERE email = ?", (email,))
        if c.fetchone():
            flash("Diese E‑Mail ist bereits registriert.", "warning")
            return redirect(url_for("register"))
        c.execute("INSERT INTO users (email, password) VALUES (?, ?)", (email, generate_password_hash(password)))
        db.commit()
        flash("Registrierung erfolgreich. Bitte einloggen.", "success")
        return redirect(url_for("login"))
    return safe_render("register.html", title="Registrieren", body="Registrierungsformular.")

@app.get("/logout")
def logout():
    session.clear()
    flash("Logout erfolgreich!", "info")
    return redirect(url_for("login"))

# -------------------------------------------------
# Dashboard
# -------------------------------------------------
@app.get("/")
@login_required
def dashboard():
    return safe_render("dashboard.html", title="Dashboard", body="Willkommen im Dashboard.")

# -------------------------------------------------
# Suche
# -------------------------------------------------
@app.get("/search")
@login_required
def search_get():
    # Formular anzeigen
    return safe_render("search.html", title="Suche")

@app.post("/search")
@login_required
def search_post():
    # 3 Begriffe (q1..q3)
    raw = [
        (request.form.get("q1") or "").strip(),
        (request.form.get("q2") or "").strip(),
        (request.form.get("q3") or "").strip(),
    ]
    terms = [t for t in raw if t]
    if not terms:
        flash("Bitte mindestens einen Suchbegriff eingeben.", "warning")
        return redirect(url_for("search_get"))

    # Limit je nach Status
    per_term_limit = PREMIUM_SEARCH_LIMIT if _is_premium() else FREE_SEARCH_LIMIT

    # Mock‑Ergebnisse (hier später echte eBay‑API einsetzen)
    results = []
    for t in terms:
        results.append({
            "title": f"Demo‑Ergebnis für „{t}“",
            "price": "9,99 €",
            "url": f"https://www.ebay.de/sch/i.html?_nkw={t}",
            "img": "https://via.placeholder.com/64x48?text=%20",
            "term": t,
        })

    return safe_render("search_results.html",
                       title="Suchergebnisse",
                       terms=terms,
                       results=results,
                       per_term_limit=per_term_limit)

def _is_premium() -> bool:
    if not session.get("user_id"):
        return False
    try:
        db = get_db(); c = db.cursor()
        c.execute("SELECT is_premium FROM users WHERE id = ?", (session["user_id"],))
        row = c.fetchone()
        return bool(row and row["is_premium"])
    except Exception:
        return False

# -------------------------------------------------
# Debug & Health
# -------------------------------------------------
@app.get("/debug")
def debug_env():
    return jsonify({
        "ok": True,
        "env": {
            "DB_PATH": DB_PATH,
            "STRIPE_PRICE_PRO": bool(PRICE_ID),
            "STRIPE_SECRET_KEY_set": bool(stripe.api_key),
            "STRIPE_WEBHOOK_SECRET_set": bool(os.getenv("STRIPE_WEBHOOK_SECRET")),
            "FREE_SEARCH_LIMIT": FREE_SEARCH_LIMIT,
            "PREMIUM_SEARCH_LIMIT": PREMIUM_SEARCH_LIMIT,
            "EBAY_APP_ID_set": bool(os.getenv("EBAY_APP_ID")),
        }
    })

@app.get("/_debug/stripe")
def debug_stripe():
    out = {"ok": False, "can_call_api": False, "price_ok": None, "error": None}
    try:
        # einfacher Ping: Balance (geht auch im Testmode)
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

@app.get("/ping")
def ping():
    ensure_schema()
    return "pong", 200

# -------------------------------------------------
# Fehlerseiten
# -------------------------------------------------
@app.errorhandler(404)
def _404(e):
    return safe_render("404.html", title="404", body="Seite nicht gefunden."), 404

@app.errorhandler(500)
def _500(e):
    return safe_render("500.html", title="500", body="Interner Fehler."), 500

# -------------------------------------------------
# Main
# -------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=True)