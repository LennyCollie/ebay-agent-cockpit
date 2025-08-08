import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import stripe

# 🌍 .env laden
load_dotenv()

# 🧱 Flask-App einrichten
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev_key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///database.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 💳 Stripe-Setup (optional)
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# 🗃️ Datenbank-Setup
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# 👤 Benutzer-Modell
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

# ✔ Datenbank automatisch erstellen (nur wenn leer)
with app.app_context():
    db.create_all()

# 📄 Dashboard (nur wenn eingeloggt)
@app.route("/")
def dashboard():
    if "user_id" not in session:
        flash("Bitte zuerst einloggen.")
        return redirect(url_for("login"))
    return render_template("dashboard.html")

# 🔑 Login
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            session["user_id"] = user.id
            flash("Login erfolgreich!")
            return redirect(url_for("dashboard"))
        else:
            flash("Ungültige E-Mail oder Passwort.")
            return redirect(url_for("login"))
    return render_template("login.html")

# 📝 Registrierung
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        hashed_pw = generate_password_hash(password)

        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash("Diese E-Mail ist bereits registriert.")
            return redirect(url_for("register"))

        new_user = User(email=email, password=hashed_pw)
        db.session.add(new_user)
        db.session.commit()
        flash("Registrierung erfolgreich. Bitte einloggen.")
        return redirect(url_for("login"))
    return render_template("register.html")

# 🚪 Logout
@app.route("/logout")
def logout():
    session.clear()
    flash("Logout erfolgreich!")
    return redirect(url_for("login"))

# 💳 Stripe Checkout (optional)
@app.route("/checkout", methods=["POST"])
def checkout():
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "eur",
                    "product_data": {"name": "Agent Premium-Zugang"},
                    "unit_amount": 1000,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=url_for("success", _external=True),
            cancel_url=url_for("cancel", _external=True),
        )
        return redirect(session.url, code=303)
    except Exception as e:
        return f"Stripe Fehler: {e}"

# 🔍 Fake-Suche
@app.route("/search", methods=["POST"])
def search():
    try:
        data = request.get_json(force=True) or {}
        query = data.get("query", "").strip()

        print(f"🔍 Benutzer sucht nach: {query}")

        if not query:
            return jsonify({"error": "Keine Suchanfrage übergeben."}), 400

        fake_results = [
            {
                "title": f"{query} – Beispiel A",
                "price": "19,99 €",
                "image": "https://via.placeholder.com/300x200.png?text=Produkt+A",
                "url": "https://www.ebay.de",
            },
        ]

        return jsonify(fake_results)

    except Exception as e:
        print("❌ Fehler in /search:", e)
        return jsonify({"error": str(e)}), 500

@app.route("/success")
def success():
    return render_template("success.html")

@app.route("/cancel")
def cancel():
    return render_template("cancel.html")

# ▶ App starten
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
