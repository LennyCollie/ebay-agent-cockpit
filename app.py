from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from dotenv import load_dotenv
import os
import stripe

# 🔑 .env laden (API Keys, DB-URI, ...)
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv("API_SECRET_KEY")
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("SQLALCHEMY_DATABASE_URI")

# 📦 Stripe Testmodus einrichten
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# 🔌 DB-Verbindung + Migration
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# 📊 Beispiel-Datenmodell (User-Tabelle etc.)
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

# 🌐 Startseite

def home():
    print("🏠 Dashboard-Route wurde aufgerufen")
    return render_template("dashboard.html")

# 🧾 Stripe Checkout (Testdemo)
@app.route("/checkout", methods=["POST"])
def checkout():
    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "eur",
                    "product_data": {"name": "Testprodukt"},
                    "unit_amount": 1000,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=url_for("success", _external=True),
            cancel_url=url_for("cancel", _external=True),
        )
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        return str(e)

@app.route("/success")
def success():
    return "<h2>Zahlung erfolgreich! ✅</h2>"

@app.route("/cancel")
def cancel():
    return "<h2>Zahlung abgebrochen ❌</h2>"

# 🧪 Testseite Login
@app.route("/login")
def login():
    return render_template("login.html")

@app.route("/register")
def register():
    return render_template("register.html")

# ▶ Starten
if __name__ == "__main__":
    app.run(debug=True)
