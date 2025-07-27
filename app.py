import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import stripe
from dotenv import load_dotenv
from flask_migrate import Migrate

# --- dotenv laden ---
load_dotenv()

# --- 1. App & Datenbank Konfiguration ---
app = Flask(__name__, template_folder='template')
app.secret_key = os.getenv('SECRET_KEY')

database_url = os.getenv('DATABASE_URL')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
    if "sslmode" not in database_url:
        database_url += "?sslmode=require"

app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///db.sqlite3'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# --- 2. Models ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True)
    password_hash = db.Column(db.String(100))
    plan = db.Column(db.String(20), default='free')
    auftraege = db.relationship('Auftrag', backref='user', lazy=True)

class Auftrag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    keywords = db.Column(db.String(100))
    filter = db.Column(db.String(100))
    aktiv = db.Column(db.Boolean, default=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

# --- 3. Beispielroute ---
@app.route('/')
def index():
    return render_template('index.html')

# --- 4. Beispiel API Route ---
@app.route('/api/get_all_jobs')
def get_all_jobs():
    jobs = Auftrag.query.filter_by(aktiv=True).all()
    daten = [
        {
            "id": a.id,
            "user_id": a.user_id,
            "name": a.name,
            "keywords": a.keywords,
            "filter": a.filter,
            "aktiv": a.aktiv
        } for a in jobs
    ]
    return jsonify(daten)

# --- 5. Direktes Ausführen ---
if __name__ == '__main__':
    app.run(debug=False)



