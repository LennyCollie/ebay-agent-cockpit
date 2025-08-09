


import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash, session, g
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

# .env laden (optional)
load_dotenv()

# -----------------------------------------------------------------------------
# Flask App
# -----------------------------------------------------------------------------
app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev_key")

# SQLite-Datei (im Projekt-Root). Auf Render ist das ephemer – für Tests ok.
DB_PATH = os.getenv("DATABASE_FILE", "database.db")

# -----------------------------------------------------------------------------
# DB-Helfer
# -----------------------------------------------------------------------------
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
    """
    Stellt sicher, dass die Tabelle 'users' existiert und die erwarteten Spalten hat.
    Falls Spalten fehlen (z. B. durch alte DB), werden sie per ALTER TABLE ergänzt.
    """
    db = get_db()
    cur = db.cursor()

    # Tabelle anlegen, wenn nicht vorhanden
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Prüfen, welche Spalten vorhanden sind
    cur.execute("PRAGMA table_info(users)")
    cols = {row["name"] for row in cur.fetchall()}

    # Fehlende Spalten ergänzen (mit Default, weil SQLite sonst NOT NULL nicht zulässt)
    if "password" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN password TEXT DEFAULT ''")
    if "created_at" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN created_at TEXT DEFAULT CURRENT_TIMESTAMP")

    db.commit()

def seed_user():
    """
    Optional: Testnutzer aus Umgebungsvariablen anlegen.
    SEED_USER_EMAIL / SEED_USER_PASSWORD setzen, falls gewünscht.
    """
    email = os.getenv("SEED_USER_EMAIL", "").strip()
    pw = os.getenv("SEED_USER_PASSWORD", "").strip()
    if not email or not pw:
        return

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id FROM users WHERE email = ?", (email,))
    exists = cur.fetchone()
    if not exists:
        cur.execute(
            "INSERT INTO users (email, password) VALUES (?, ?)",
            (email, generate_password_hash(pw))
        )
        db.commit()

# Einmalige Initialisierung bei erstem Request (oder über /ping)
_initialized = False
@app.before_request
def _init_once():
    global _initialized
    if not _initialized:
        ensure_schema()
        seed_user()
        _initialized = True

# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------
def login_required(view):
    from functools import wraps
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Bitte einloggen.")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

# -----------------------------------------------------------------------------
# Routen
# -----------------------------------------------------------------------------
@app.get("/ping")
def ping():
    # Extra: Initialisierung auch hier sicherstellen
    ensure_schema()
    return "pong" 200

@app.get("/")
@login_required
def dashboard():
    return render_template("dashboard.html")

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
        else:
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
        # Prüfen, ob E-Mail schon existiert
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

# Optional: gefahrloser „Drop & Recreate“ für Tests – nur aktivieren, wenn du es brauchst!
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
# Run (lokal). Auf Render läuft Gunicorn (Procfile) und nutzt app:app.
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
