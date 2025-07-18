import os
import time
import json
import base64
import requests
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from apscheduler.schedulers.background import BackgroundScheduler

# --- App & DB Konfiguration ---
app = Flask(__name__, template_folder='template')
app.secret_key = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///users.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- Agenten Konfiguration ---
MEMORY_FILE = "gesehene_artikel.json"
MY_APP_ID = os.getenv("EBAY_APP_ID")
MY_CERT_ID = os.getenv("EBAY_CERT_ID")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

# --- Datenbank Modelle ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    auftraege = db.relationship('Auftrag', backref='author', lazy=True, cascade="all, delete-orphan")

class Auftrag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    keywords = db.Column(db.String(200), nullable=False)
    filter = db.Column(db.String(300), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    funde = db.relationship('Fund', backref='auftrag', lazy=True, cascade="all, delete-orphan")

class Fund(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.String(20), unique=True, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    price = db.Column(db.String(50), nullable=False)
    item_url = db.Column(db.String(500), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    auftrag_id = db.Column(db.Integer, db.ForeignKey('auftrag.id'), nullable=False)

# --- Agenten Funktionen ---
def get_oauth_token():
    # ... (Code bleibt gleich)
    pass
def sende_benachrichtigungs_email(neue_funde, auftrag):
    # ... (Code bleibt gleich)
    pass
def search_items(token, auftrag, gesehene_ids_fuer_suche, app_context):
    # ... (Code bleibt gleich)
    pass
def agenten_job():
    # ... (Code bleibt gleich)
    pass

# === Webseiten Routen ===
@app.route('/')
# ... (alle Routen von @app.route('/') bis @app.route('/delete/...') bleiben exakt gleich)

# === Hauptteil des Programms ===

    # Dieser Block wird nur einmal beim Start der App ausgeführt.
    with app.app_context():
        db.create_all()
    
    # Konfiguriere und starte den Wecker
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(agenten_job, 'interval', minutes=10)
    scheduler.start()
    
    # Hinweis: In einer Produktionsumgebung wie Render wird 'app.run()' nicht direkt aufgerufen.
    # Der Gunicorn-Server startet die 'app'. Dieser Block ist eher für lokales Testen.
    # Wir lassen ihn hier weg, um Verwirrung zu vermeiden.

# Führe die Initialisierung aus, wenn die App startet

