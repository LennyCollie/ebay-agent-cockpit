import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import stripe
from dotenv import load_dotenv
from flask_migrate import Migrate

# --- .env laden ---
load_dotenv()

# --- App & Datenbank Konfiguration ---
app = Flask(__name__, template_folder='template')
app.secret_key = os.getenv('SECRET_KEY')

# --- Datenbank URL ---
database_url = os.getenv('DATABASE_URL')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
    if "sslmode" not in database_url:
        database_url += "?sslmode=require"

app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///db.sqlite3'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

from flask import Flask, render_template

app = Flask(__name__)

# Startseite
@app.route('/')
def index():
    return '✅ Flask App läuft!'

# Dashboardseite
@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

# --- Stripe Konfiguration ---
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

# --- DB & Migration ---
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# --- Beispielroute ---
@app.route('/')
def index():
    return '✅ Flask App läuft auf Render!'

# --- App nur lokal starten ---
if __name__ == '__main__':
    app.run(debug=True)
