import os
import subprocess
import json
from flask import Flask, render_template, request, redirect, url_for, flash, session
import stripe
from dotenv import load_dotenv

# .env laden
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret")

# Stripe konfigurieren
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
stripe_price_id = os.getenv("STRIPE_PRICE_ID")

LOGFILE = "logs/agent_log.txt"
AUFTRAEGE_FILE = "auftraege.json"

@app.route("/")
def index():
    return redirect(url_for("dashboard"))

@app.route("/dashboard")
def dashboard():
    logs = []
    auftraege = []
    is_premium = session.get("premium", False)

    if os.path.exists(LOGFILE):
        with open(LOGFILE, "r", encoding="utf-8") as f:
            logs = f.readlines()[-10:]

    if os.path.exists(AUFTRAEGE_FILE):
        with open(AUFTRAEGE_FILE, "r", encoding="utf-8") as f:
            auftraege = json.load(f)

    return render_template("dashboard.html", logs=logs, auftraege=auftraege, is_premium=is_premium)

@app.route("/run-agent", methods=["POST"])
def run_agent():
    try:
        result = subprocess.run(["python", "agent.py"], capture_output=True, text=True)
        with open(LOGFILE, "a", encoding="utf-8") as log:
            log.write(result.stdout)
            log.write(result.stderr)
        flash("Agent wurde erfolgreich gestartet!", "success")
    except Exception as e:
        flash(f"Fehler beim Starten: {str(e)}", "danger")
    return redirect(url_for("dashboard"))

@app.route("/create-checkout-session", methods=["POST"])
def create_checkout_session():
    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price": stripe_price_id,
                "quantity": 1,
            }],
            mode="subscription",
            success_url=url_for("success", _external=True),
            cancel_url=url_for("cancel", _external=True),
        )
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        flash(f"Stripe-Fehler: {str(e)}", "danger")
        return redirect(url_for("dashboard"))

@app.route("/success")
def success():
    session["premium"] = True
    flash("Upgrade auf PREMIUM erfolgreich!", "success")
    return redirect(url_for("dashboard"))

@app.route("/cancel")
def cancel():
    flash("Zahlung abgebrochen. Du bist weiterhin im kostenlosen Plan.", "warning")
    return redirect(url_for("dashboard"))

if __name__ == "__main__":
    app.run(debug=True)
