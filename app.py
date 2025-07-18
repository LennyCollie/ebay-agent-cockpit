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

# --- App & DB Konfiguration ---
app = Flask(__name__, template_folder='template')
app.secret_key = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///users.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- Agenten Konfiguration aus Umgebungsvariablen ---
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
def lade_gesehene_artikel():
    try:
        with open(MEMORY_FILE, 'r') as f: return json.load(f)
    except: return {}

def speichere_gesehene_artikel(artikel_daten):
    with open(MEMORY_FILE, 'w') as f: json.dump(artikel_daten, f)

def get_oauth_token():
    print("AGENT: Hole Zugangsticket...")
    if not all([MY_APP_ID, MY_CERT_ID]):
        print("AGENT FEHLER: eBay Keys sind nicht konfiguriert.")
        return None
    url = "https://api.ebay.com/identity/v1/oauth2/token"
    headers = {'Content-Type': 'application/x-www-form-urlencoded', 'Authorization': 'Basic ' + base64.b64encode(f"{MY_APP_ID}:{MY_CERT_ID}".encode()).decode()}
    body = {'grant_type': 'client_credentials', 'scope': 'https://api.ebay.com/oauth/api_scope'}
    try:
        response = requests.post(url, headers=headers, data=body)
        response.raise_for_status()
        print("AGENT: ERFOLG! Token erhalten.")
        return response.json().get('access_token')
    except Exception as e:
        print(f"AGENT FEHLER beim Holen des Tokens: {e}")
        return None

def sende_benachrichtigungs_email(neue_funde, auftrag):
    recipient_email = auftrag.author.email
    auftrags_name = auftrag.name
    print(f"AGENT INFO: Sende E-Mail für '{auftrags_name}' an {recipient_email}...")
    email_body = f"Hallo,\n\nfür deinen Suchauftrag '{auftrags_name}' wurden {len(neue_funde)} neue Artikel gefunden:\n\n"
    for item in neue_funde:
        email_body += f"Titel: {item['title']}\nPreis: {item['price']}\nLink: {item['itemWebUrl']}\n" + "-"*20 + "\n"
    betreff = f"{len(neue_funde)} neue eBay Artikel für '{auftrags_name}' gefunden!"
    msg = MIMEText(email_body, 'plain', 'utf-8')
    msg['Subject'] = betreff
    msg['From'] = SENDER_EMAIL
    msg['To'] = recipient_email
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(SENDER_EMAIL, EMAIL_PASSWORD)
        server.sendmail(SENDER_EMAIL, recipient_email, msg.as_string())
        server.quit()
        print("AGENT: ERFOLG! E-Mail wurde versendet.")
    except Exception as e:
        print(f"AGENT FEHLER beim Senden der E-Mail: {e}")

def search_items(token, auftrag, gesehene_ids_fuer_suche, app_context):
    print(f"AGENT: Führe Auftrag aus: '{auftrag.name}'")
    keywords = auftrag.keywords
    filters = auftrag.filter
    params = {'q': keywords, 'limit': 20}
    if filters: params['filter'] = filters
    url = f"https://api.ebay.com/buy/browse/v1/item_summary/search?{urllib.parse.urlencode(params)}"
    headers = {'Authorization': f'Bearer {token}', 'X-EBAY-C-MARKETPLACE-ID': 'EBAY_DE'}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        results = response.json()
        if results.get('total', 0) > 0:
            neue_funde_details = []
            with app_context:
                for item in results.get('itemSummaries', []):
                    item_id = item.get('itemId')
                    if item_id and item_id not in gesehene_ids_fuer_suche:
                        existierender_fund = Fund.query.filter_by(item_id=item_id).first()
                        if not existierender_fund:
                            details = {'title': item.get('title', 'N/A'), 'price': item.get('price', {}).get('value', 'N/A') + " " + item.get('price', {}).get('currency', ''), 'itemWebUrl': item.get('itemWebUrl', '#')}
                            neuer_fund = Fund(item_id=item_id, title=details['title'], price=details['price'], item_url=details['itemWebUrl'], auftrag_id=auftrag.id)
                            db.session.add(neuer_fund)
                            neue_funde_details.append(details)
                        gesehene_ids_fuer_suche.add(item_id)
                db.session.commit()
            if neue_funde_details:
                sende_benachrichtigungs_email(neue_funde_details, auftrag)
    except Exception as e:
        print(f"AGENT FEHLER bei der Suche: {e}")
    return gesehene_ids_fuer_suche

def agenten_job():
    print("\n" + "="*50)
    print(f"AGENT JOB STARTET ({time.ctime()})")
    print("="*50)
    alle_gesehenen_artikel = lade_gesehene_artikel()
    access_token = get_oauth_token()
    if access_token:
        with app.app_context():
            alle_auftraege = Auftrag.query.all()
        print(f"AGENT: {len(alle_auftraege)} Aufträge werden verarbeitet.")
        for auftrag in alle_auftraege:
            gedaechtnis_schluessel = f"{auftrag.author.email}_{auftrag.name}"
            ids_fuer_diesen_auftrag = set(alle_gesehenen_artikel.get(gedaechtnis_schluessel, []))
            neue_ids = search_items(access_token, auftrag, ids_fuer_diesen_auftrag, app.app_context())
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
        password_hash = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(email=email, password_hash=password_hash)
        db.session.add(new_user)
        db.session.commit()
        flash('Registrierung erfolgreich! Du kannst dich jetzt einloggen.')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password_hash, password):
            flash('Bitte überprüfe deine Login-Daten.')
            return redirect(url_for('login'))
        session['logged_in'] = True
        session['user_id'] = user.id
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/add', methods=['POST'])
def neuer_auftrag():
    if not session.get('logged_in'): return redirect(url_for('login'))
    neuer_auftrag = Auftrag(name=request.form.get('name'), keywords=request.form.get('keywords'), filter=request.form.get('filter'), user_id=session['user_id'])
    db.session.add(neuer_auftrag)
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/delete/<int:auftrag_id>', methods=['POST'])
def loesche_auftrag(auftrag_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    auftrag = Auftrag.query.get_or_404(auftrag_id)
    if auftrag.author.id != session['user_id']:
        return "Nicht autorisiert", 403
    db.session.delete(auftrag)
    db.session.commit()
    return redirect(url_for('dashboard'))


with app.app_context():
    db.create_all()

def agenten_job_wrapper():
    with app.app_context():
        agenten_job()

if __name__ != '__main__':
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(agenten_job_wrapper, 'interval', minutes=10)
    scheduler.start()
    print(">>> APScheduler (Wecker) wurde erfolgreich gestartet.")
