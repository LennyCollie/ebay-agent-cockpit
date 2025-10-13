import os
import sqlite3
import time
from functools import wraps

import requests
import stripe
from dotenv import load_dotenv  # lokal praktisch; auf Render ignoriert
from flask import (
    Flask,
    Response,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

# =============================================================================
# Konfiguration
# =============================================================================

load_dotenv()  # lokal: .env lesen

# Render ist read-only; nur /tmp ist schreibbar. Lokal z.B. "database.db"
DB_PATH = (
    os.getenv("DATABASE_FILE")
    or os.getenv("DATABASE_URL")
    or ("/tmp/agent.db" if os.getenv("RENDER") or os.getenv("DYNO") else "database.db")
)

SECRET_KEY = os.getenv("SECRET_KEY", "dev_key")

# Stripe Keys / IDs
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")  # LIVE oder TEST – kommt aus Env
PRICE_ID = os.getenv("STRIPE_PRICE_PRO")  # z.B. price_...
SUCCESS_URL = os.getenv("STRIPE_SUCCESS_URL")  # optional
CANCEL_URL = os.getenv("STRIPE_CANCEL_URL")  # optional


EBAY_CLIENT_ID = os.getenv("EBAY_CLIENT_ID")  # z.B. xxx-xxx
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET")  # geheim
EBAY_ENV = os.getenv("EBAY_ENV", "SANDBOX").upper()  # "SANDBOX" oder "PROD"

# Token-Cache (einfach)
_ebay_token = {"access_token": None, "expires_at": 0}


# =============================================================================
# Flask App
# =============================================================================

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY


# =============================================================================
# Hilfen: Template-Fallback (verhindert 500 bei fehlenden Dateien)
# =============================================================================


def safe_render(template_name: str, **ctx):
    """
    Versucht ein Template zu rendern; wenn es nicht existiert, liefert
    eine einfache HTML-Seite zurück (keine 500er mehr wegen fehlender Templates).
    """
    try:
        return render_template(template_name, **ctx)
    except Exception:
        title = ctx.get("title") or template_name
        body = ctx.get("body") or ""
        return Response(
            f"""<!doctype html>
<html lang="de">
<head><meta charset="utf-8"><title>{title}</title></head>
<body style="font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:900px;margin:40px auto;line-height:1.5">
<h1>{title}</h1>
<p>{body}</p>
<p style="margin-top:24px"><a href="{url_for('public_home')}">Zur Startseite</a></p>
</body></html>""",
            mimetype="text/html",
        )


def _ebay_oauth_token():
    """
    Holt ein App-Token von eBay (Browse API). Cached es bis zum Ablauf.
    Fällt auf None zurück, wenn keine Credentials gesetzt sind oder Fehler.
    """
    if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
        return None

    now = time.time()
    if _ebay_token["access_token"] and _ebay_token["expires_at"] - 60 > now:
        return _ebay_token["access_token"]

    base = (
        "https://api.sandbox.ebay.com"
        if EBAY_ENV == "SANDBOX"
        else "https://api.ebay.com"
    )
    url = f"{base}/identity/v1/oauth2/token"
    auth = (EBAY_CLIENT_ID, EBAY_CLIENT_SECRET)
    data = {
        "grant_type": "client_credentials",
        # Minimaler Scope für Browse API:
        "scope": "https://api.ebay.com/oauth/api_scope",
    }
    try:
        r = requests.post(url, data=data, auth=auth, timeout=15)
        r.raise_for_status()
        j = r.json()
        _ebay_token["access_token"] = j.get("access_token")
        _ebay_token["expires_at"] = now + int(j.get("expires_in", 0))
        return _ebay_token["access_token"]
    except Exception:
        return None


def ebay_search_items(query: str, limit: int = 5):
    """
    Sucht Artikel mit der eBay Browse API.
    Wenn kein Token/Fehler -> liefert kleine Mock-Liste zurück, damit die UI funktioniert.
    """
    query = (query or "").strip()
    if not query:
        return []

    token = _ebay_oauth_token()
    if token:
        base = (
            "https://api.sandbox.ebay.com"
            if EBAY_ENV == "SANDBOX"
            else "https://api.ebay.com"
        )
        url = f"{base}/buy/browse/v1/item_summary/search"
        try:
            r = requests.get(
                url,
                params={"q": query, "limit": str(limit)},
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            r.raise_for_status()
            j = r.json()
            items = []
            for it in (j.get("itemSummaries") or [])[:limit]:
                items.append(
                    {
                        "title": it.get("title"),
                        "price": f'{it.get("price",{}).get("value","")} {it.get("price",{}).get("currency","")}',
                        "image": (it.get("image", {}) or {}).get("imageUrl"),
                        "url": it.get("itemWebUrl"),
                    }
                )
            return items
        except Exception:
            pass  # fällt unten auf Mock zurück

    # Mock (damit du ohne eBay-Keys testen kannst)
    return [
        {
            "title": f"{query} – Beispiel 1",
            "price": "19.99 EUR",
            "image": None,
            "url": "#",
        },
        {
            "title": f"{query} – Beispiel 2",
            "price": "49.00 EUR",
            "image": None,
            "url": "#",
        },
        {
            "title": f"{query} – Beispiel 3",
            "price": "7.95 EUR",
            "image": None,
            "url": "#",
        },
    ][:limit]


@app.route("/search", methods=["GET", "POST"])
@login_required
def search():
    # Premium prüfen
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT is_premium FROM users WHERE id=?", (session["user_id"],))
    row = cur.fetchone()
    is_premium = bool(row and row["is_premium"])

    # Limits (Server-seitig durchsetzen!)
    max_terms = 3 if not is_premium else 20
    per_query_limit = 5 if not is_premium else 20

    results = {}
    q_list = []

    if request.method == "POST":
        # Wir erwarten mehrere Eingabefelder mit name="q[]"
        q_list = [q.strip() for q in (request.form.getlist("q[]") or []) if q.strip()]
        if len(q_list) > max_terms:
            flash(
                f"Maximal {max_terms} Suchbegriffe in deiner aktuellen Stufe.",
                "warning",
            )
            q_list = q_list[:max_terms]

        # Suchen
        for q in q_list:
            results[q] = ebay_search_items(q, per_query_limit)

    return safe_render(
        "search.html",
        title="Suche",
        is_premium=is_premium,
        max_terms=max_terms,
        per_query_limit=per_query_limit,
        q_list=q_list,
        results=results,
    )


# =============================================================================
# DB-Helfer
# =============================================================================


def get_db():
    """
    Öffnet/verwendet eine SQLite-Connection für den Request.
    Stellt sicher, dass das Zielverzeichnis existiert (für /tmp auf Render).
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
    Legt die Tabelle users an (falls fehlt) und ergänzt fehlende Spalten.
    """
    db = get_db()
    cur = db.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL DEFAULT '',
            is_premium INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """
    )
    # fehlende Spalten ergänzen (bei alten DBs)
    cur.execute("PRAGMA table_info(users)")
    cols = {r["name"] for r in cur.fetchall()}
    if "password" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN password TEXT NOT NULL DEFAULT ''")
    if "is_premium" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN is_premium INTEGER DEFAULT 0")
    if "created_at" not in cols:
        cur.execute(
            "ALTER TABLE users ADD COLUMN created_at TEXT DEFAULT CURRENT_TIMESTAMP"
        )
    db.commit()


def seed_user():
    """
    Optional: Testnutzer anlegen (Env: SEED_USER_EMAIL, SEED_USER_PASSWORD).
    """
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
# Öffentliche Seiten
# =============================================================================


@app.get("/public")
def public_home():
    return safe_render(
        "public_home.html",
        title="Start",
        body="Dein leichtes Cockpit für eBay‑Automatisierung.",
    )


@app.get("/pricing")
def public_pricing():
    return safe_render(
        "public_pricing.html", title="Preise", body="Hier erscheint deine Preisseite."
    )


@app.route("/checkout", methods=["GET", "POST"])
def public_checkout():
    """
    Unterstützt:
      - POST:  Formular-Checkout (empfohlen)
      - GET :  /checkout?buy=1[&email=...]  -> startet Stripe Checkout
               /checkout                    -> zeigt die (optionale) Checkout-Seite
    """

    def _start_checkout(email_arg: str | None):
        if not PRICE_ID:
            flash("Kein STRIPE_PRICE_PRO gesetzt. Bitte Env prüfen.", "danger")
            return redirect(url_for("public_pricing"))

        # E-Mail bevorzugt aus Session, sonst Parameter
        email = (session.get("user_email") or (email_arg or "")).strip() or None

        try:
            session_obj = stripe.checkout.Session.create(
                mode="subscription",
                line_items=[{"price": PRICE_ID, "quantity": 1}],
                customer_email=email,  # None ist erlaubt
                success_url=SUCCESS_URL or url_for("checkout_success", _external=True),
                cancel_url=CANCEL_URL or url_for("public_pricing", _external=True),
                allow_promotion_codes=True,
            )
            return redirect(session_obj.url, code=303)
        except Exception as e:
            flash(f"Stripe‑Fehler: {e}", "danger")
            return redirect(url_for("public_pricing"))

    if request.method == "POST":
        # aus Formular
        email = (request.form.get("email") or "").strip()
        return _start_checkout(email)

    # GET
    buy = (request.args.get("buy") or "").lower()
    if buy in ("1", "true", "yes", "go"):
        email = (request.args.get("email") or "").strip()
        return _start_checkout(email)

    # Fallback: einfache Seite anzeigen (wenn du eine eigene Checkout-Seite hast)
    return safe_render(
        "public_checkout.html", title="Checkout", body="Checkout Formular."
    )


@app.get("/checkout/success")
def checkout_success():
    return safe_render(
        "success.html",
        title="Vielen Dank!",
        body="Dein Kauf war erfolgreich. Dein Premium‑Zugang ist jetzt freigeschaltet.",
    )


# =============================================================================
# Dashboard & einfache Seiten
# =============================================================================


@app.get("/")
@login_required
def dashboard():
    return safe_render(
        "dashboard.html", title="Dashboard", body="Willkommen im Dashboard."
    )


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
    return safe_render(
        "register.html", title="Registrieren", body="Registrierungsformular."
    )


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
    return jsonify(
        {
            "ok": True,
            "env": {
                "DB_PATH": DB_PATH,
                "STRIPE_SECRET_KEY_set": bool(os.getenv("STRIPE_SECRET_KEY")),
                "STRIPE_PRICE_PRO": PRICE_ID,
                "STRIPE_WEBHOOK_SECRET_set": bool(os.getenv("STRIPE_WEBHOOK_SECRET")),
            },
        }
    )


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


# favicon, damit keine Fehler im Log auftauchen
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
