import os
from flask import Flask, render_template, request, redirect, url_for, jsonify
from dotenv import load_dotenv
import stripe
import sqlite3
from datetime import datetime

# -----------------------------------------------------------
# Setup
# -----------------------------------------------------------
load_dotenv()  # lokal nützlich; auf Render ignoriert
app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev_key")

# Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# -----------------------------------------------------------
# Datenbank
# -----------------------------------------------------------
def get_db():
    db_path = os.getenv("DATABASE_URL", "database.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def ensure_schema():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            is_premium INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

ensure_schema()

# -----------------------------------------------------------
# Routes
# -----------------------------------------------------------
@app.route("/")
def index():
    return redirect(url_for("public_home"))

@app.route("/public")
def public_home():
    return render_template("public_home.html")

@app.route("/pricing")
def pricing():
    return render_template("pricing.html")

@app.route("/checkout", methods=["POST"])
def checkout():
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card", "sepa_debit"],
            line_items=[{
                "price_data": {
                    "currency": "eur",
                    "product_data": {
                        "name": "Premium Zugang"
                    },
                    "unit_amount": 500,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=url_for("checkout_success", _external=True),
            cancel_url=url_for("pricing", _external=True),
        )
        return redirect(session.url, code=303)
    except Exception as e:
        return str(e), 400

@app.route("/checkout/success")
def checkout_success():
    return render_template("success.html")

# -----------------------------------------------------------
# Webhook
# -----------------------------------------------------------
@app.route("/webhook", methods=["POST"])
def webhook_received():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")
    endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except stripe.error.SignatureVerificationError:
        return "Webhook signature verification failed", 400

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        customer_email = session.get("customer_email")

        if customer_email:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO users (email, is_premium)
                VALUES (?, 1)
                ON CONFLICT(email) DO UPDATE SET is_premium=1
            """, (customer_email,))
            conn.commit()
            conn.close()

    return "", 200

# -----------------------------------------------------------
# Search Route (GET erlaubt)
# -----------------------------------------------------------
@app.route("/search", methods=["GET", "POST"])
def search():
    if request.method == "POST":
        query = request.form.get("query")
        return f"Suchergebnisse für: {query}"
    else:
        return render_template("search.html")

# -----------------------------------------------------------
# Main
# -----------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
