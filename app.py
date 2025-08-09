# app.py
import os
import sys
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

# .env laden (optional)
load_dotenv()

# Flask-App
app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev_key")

# WICHTIG: Wir erzwingen eine lokale SQLite-Datei und ignorieren evtl. alte DATABASE_URLs
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///database.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# --- Modelle -----------------------------------------------------------------
class User(db.Model):
    __tablename__ = "users"  # klar benannt
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


# Datenbanktabellen bei Start sicherstellen
with app.app_context():
    db.create_all()
    print("✅ DB init done (tables ensured).", file=sys.stdout, flush=True)


# --- Routen ------------------------------------------------------------------
@app.route("/")
def dashboard():
    # Simple Dashboard – du kannst dem Template optional Variablen übergeben
    return render_template("dashboard.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            flash("Login erfolgreich!", "success")
            return redirect(url_for("dashboard"))

        flash("Ungültige E-Mail oder Passwort.", "danger")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        if not email or not password:
            flash("E-Mail und Passwort sind erforderlich.", "warning")
            return redirect(url_for("register"))

        if User.query.filter_by(email=email).first():
            flash("Diese E-Mail ist bereits registriert.", "warning")
            return redirect(url_for("register"))

        user = User(email=email, password=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        flash("Registrierung erfolgreich. Bitte einloggen.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/logout")
def logout():
    # Wir führen keine Session-Logik – der Button führt einfach zurück zum Login
    flash("Logout erfolgreich!", "info")
    return redirect(url_for("login"))


# Health/Ping zum schnellen Log-Test
@app.route("/ping")
def ping():
    print("🔎 /ping hit", file=sys.stdout, flush=True)
    return "pong", 200


# Lokaler Start (Render nutzt gunicorn -> Procfile: web: gunicorn app:app)
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
