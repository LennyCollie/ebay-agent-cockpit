import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from dotenv import load_dotenv
import stripe
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

# 🔐 Umgebungsvariablen laden
load_dotenv()

# 🔧 Flask-Konfiguration
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "devkey")
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL", "sqlite:///db.sqlite3")

# 💳 Stripe konfigurieren (Testmodus)
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# 🔌 Datenbank-Setup
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# 📊 Dummy User-Modell
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

# 🌐 Routen
@app.route("/")
def home():
    return render_template("dashboard.html")

@app.route("/login")
def login():
    return render_template("login.html")

@app.route("/register")
def register():
    return render_template("register.html")

@app.route("/checkout", methods=["POST"])
def checkout():
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "eur",
                    "product_data": {"name": "Agent Premium-Zugang"},
                    "unit_amount": 1000,  # = 10,00 €
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=url_for("success", _external=True),
            cancel_url=url_for("cancel", _external=True),
        )
        return redirect(session.url, code=303)
    except Exception as e:
        return f"Fehler bei Stripe Checkout: {e}"

@app.route("/success")
def success():
    return render_template("success.html")

@app.route("/cancel")
def cancel():
    return render_template("cancel.html")

# ▶ App starten
if __name__ == "__main__":
    app.run(debug=True)
