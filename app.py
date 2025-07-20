import os
import time
import json
import base64
import requests
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import atexit

# --- App & DB Konfiguration ---
app = Flask(__name__, template_folder='template')
app.secret_key = os.urandom(24)"MeinAbsolutGeheimerSchluesselFuerDieSuperApp123!"

database_url = os.getenv('DATABASE_URL')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- Agenten Konfiguration ---
MEMORY_FILE = "gesehene_artikel.json"
MY_APP_ID = os.getenv("EBAY_APP_ID")
MY_CERT_ID = os.getenv("EBAY_CERT_ID")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

# --- Datenbank Modelle (unverändert) ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    plan = db.Column(db.String(50), nullable=False, default='free') 
    auftraege = db.relationship('Auftrag', backref='author', lazy=True, cascade="all, delete-orphan")

class Auftrag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    keywords = db.Column(db.String(300), nullable=False)
    filter = db.Column(db.String(500), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    funde = db.relationship('Fund', backref='auftrag', lazy=True, cascade="all, delete-orphan")

class Fund(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.String(50), unique=True, nullable=False)
    title = db.Column(db.String(300), nullable=False)
    price = db.Column(db.String(50), nullable=False)
    item_url = db.Column(db.String(1000), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    auftrag_id = db.Column(db.Integer, db.ForeignKey('auftrag.id'), nullable=False)


# --- Agenten Funktionen (unverändert) ---
def lade_gesehene_artikel():
    try:
        with open(MEMORY_FILE, 'r') as f: return json.load(f)
    except: return {}

def speichere_gesehene_artikel(artikel_daten):
    with open(MEMORY_FILE, 'w') as f: json.dump(artikel_daten, f)
    
def get_oauth_token():
    # ... (Inhalt unverändert)
    pass

def sende_benachrichtigungs_email(neue_funde, auftrag):
    # ... (Inhalt unverändert)
    pass
    
def search_items(token, auftrag, gesehene_ids_fuer_suche):
    # ... (Inhalt unverändert)
    pass

def agenten_job():
    with app.app_context():
        print("\n" + "="*50)
        print(f"AGENT JOB STARTET ({time.ctime()})")
        print("="*50)
        alle_gesehenen_artikel = lade_gesehene_artikel()
        access_token = get_oauth_token()
        if access_token:
            alle_auftraege = Auftrag.query.all()
            print(f"AGENT: {len(alle_auftraege)} Aufträge werden verarbeitet.")
            for auftrag in alle_auftraege:
                gedaechtnis_schluessel = f"{auftrag.author.email}_{auftrag.name}"
                ids_fuer_diesen_auftrag = set(alle_gesehenen_artikel.get(gedaechtnis_schluessel, []))
                neue_ids = search_items(access_token, auftrag, ids_fuer_diesen_auftrag)
                alle_gesehenen_artikel[gedaechtnis_schluessel] = list(neue_ids)
                time.sleep(2)
        speichere_gesehene_artikel(alle_gesehenen_artikel)
        print(f"AGENT JOB BEENDET ({time.ctime()})")


# --- Webseiten Routen ---
@app.route('/')
def index():
    if session.get('logged_in'):
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    return render_template('dashboard.html', user=user)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        if user:
            flash('Diese E-Mail-Adresse ist bereits registriert.')
            return redirect(url_for('register'))
        password_hash = generate_password_hash(password, method='pbkdf2:sha26')
        new_user = User(email=email, password_hash=password_hash)
        db.session.add(new_user)
        db.session.commit()
        flash('Registrierung erfolgreich! Du kannst dich jetzt einloggen.')
        return redirect(url_for('login'))
        
    # DIESE ZEILE HAT GEFEHLT: Zeigt das Registrierungs-Formular an
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        
        if not user or not check_password_hash(user.password_hash, password):
            flash('Bitte überprüfe deine Login-Daten und versuche es erneut.')
            return redirect(url_for('login')) # Weiterleitung bei Fehler
            
        session['logged_in'] = True
        session['user_id'] = user.id
        return redirect(url_for('dashboard')) # Weiterleitung bei Erfolg
        
    # DIESE ZEILE HAT GEFEHLT: Zeigt das Login-Formular an, wenn die Seite normal aufgerufen wird
    return render_template('login.html')
    
@app.route('/logout')
def logout():
    session.clear() # Löscht alle Session-Daten (z.B. dass du eingeloggt bist)
    flash("Du wurdest erfolgreich ausgeloggt.")
    # DIESE ZEILE HAT GEFEHLT: Leitet den User zur Login-Seite zurück
    return redirect(url_for('login'))

@app.route('/add', methods=['POST'])
def neuer_auftrag():
    if not session.get('logged_in'): return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    limit_free_plan = 2
    if user.plan == 'free' and len(user.auftraege) >= limit_free_plan:
        flash(f"Limit von {limit_free_plan} Aufträgen erreicht. Bitte upgraden!")
        return redirect(url_for('upgrade_seite'))
    neuer_auftrag = Auftrag(name=request.form.get('name'), keywords=request.form.get('keywords'), filter=request.form.get('filter'), user_id=session['user_id'])
    db.session.add(neuer_auftrag)
    db.session.commit()
    flash("Neuer Suchauftrag erfolgreich hinzugefügt!")
    return redirect(url_for('dashboard'))

@app.route('/delete/<int:auftrag_id>', methods=['POST'])
def loesche_auftrag(auftrag_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    
    auftrag = Auftrag.query.get_or_404(auftrag_id)
    if auftrag.author.id != session['user_id']:
        return "Nicht autorisiert", 403
        
    db.session.delete(auftrag)
    db.session.commit()
    
    # DIESE ZEILE HAT GEFEHLT!
    return redirect(url_for('dashboard'))
    
@app.route('/upgrade')
def upgrade_seite():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('upgrade.html')

@app.route('/make_me_premium_please') # Geänderte, geheimere URL
def make_me_premium():
    if 'user_id' not in session:
        flash("Bitte zuerst einloggen.")
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    if user:
        user.plan = 'premium'
        db.session.commit()
        flash(f"Dein Account ({user.email}) wurde erfolgreich auf PREMIUM hochgestuft!")
    else:
        flash("Fehler: Benutzer nicht gefunden.")
    return redirect(url_for('dashboard'))

# === INITIALISIERUNG ===
with app.app_context():
    db.create_all()

# Dieser Block stellt sicher, dass der Wecker nur EINMAL sauber gestartet wird.
if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(agenten_job, trigger=IntervalTrigger(minutes=10), id='agenten_job_1', replace_existing=True)
    scheduler.start()
    # Stellt sicher, dass der Wecker beim Beenden der App sauber heruntergefahren wird
    atexit.register(lambda: scheduler.shutdown())
