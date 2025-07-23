import os
import time
import json
import base64
import requests
import smtplib
import urllib.parse
from email.mime.text import MIMEText
from datetime import datetime
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

# === 1. App & Datenbank-Setup (wird nur für den Kontext benötigt) ===
app = Flask(__name__)
database_url = os.getenv('DATABASE_URL')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
if database_url and "sslmode" not in database_url:
    database_url += "?sslmode=require"
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- 2. Konfiguration ---
MEMORY_FILE = "gesehene_artikel.json"
MY_APP_ID = os.getenv("EBAY_APP_ID")
MY_CERT_ID = os.getenv("EBAY_CERT_ID")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

# --- 3. Datenbank-Modelle (müssen exakt wie in app.py sein) ---
class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    plan = db.Column(db.String(50), nullable=False, default='free')
    auftraege = db.relationship('Auftrag', backref='author', lazy=True)

class Auftrag(db.Model):
    __tablename__ = 'auftrag'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    keywords = db.Column(db.String(300), nullable=False)
    filter = db.Column(db.String(500), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    aktiv = db.Column(db.Boolean, default=True, nullable=False)

# --- 4. Agenten Funktionen ---
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
    print(f"AGENT INFO: Sende E-Mail fuer '{auftrags_name}' an {recipient_email}...")
    email_body = f"Hallo,\n\nfuer deinen Suchauftrag '{auftrags_name}' wurden {len(neue_funde)} neue Artikel gefunden:\n\n"
    for item in neue_funde:
        email_body += f"Titel: {item['title']}\nPreis: {item['price']}\nLink: {item['itemWebUrl']}\n" + "-"*20 + "\n"
    betreff = f"{len(neue_funde)} neue eBay Artikel fuer '{auftrags_name}' gefunden!"
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

def search_items(token, auftrag, gesehene_ids_fuer_suche):
    print(f"AGENT: Fuehre Auftrag aus: '{auftrag.name}'")
    keywords = auftrag.keywords
    filters = auftrag.filter
    params = {'q': urllib.parse.quote(keywords)}
    if filters:
        params['filter'] = urllib.parse.quote(filters)
    url = f"https://api.ebay.com/buy/browse/v1/item_summary/search?{urllib.parse.urlencode(params)}&limit=20"
    headers = {'Authorization': f'Bearer {token}', 'X-EBAY-C-MARKETPLACE-ID': 'EBAY_DE'}
    neue_funde_details = []
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        results = response.json()
        if results.get('total', 0) > 0:
            for item in results.get('itemSummaries', []):
                item_id = item.get('itemId')
                if item_id and item_id not in gesehene_ids_fuer_suche:
                    details = {'title': item.get('title', 'N/A'), 'price': item.get('price', {}).get('value', 'N/A') + " " + item.get('price', {}).get('currency', ''), 'itemWebUrl': item.get('itemWebUrl', '#')}
                    neue_funde_details.append(details)
                    gesehene_ids_fuer_suche.add(item_id)
    except Exception as e:
        print(f"AGENT FEHLER bei der Suche: {e}")
    return neue_funde_details, gesehene_ids_fuer_suche

# --- 5. Haupt-Job ---
def agenten_job():
    with app.app_context():
        print(f"\nAGENT JOB STARTET ({time.ctime()})")
        alle_gesehenen_artikel = lade_gesehene_artikel()
        access_token = get_oauth_token()
        if access_token:
            alle_auftraege = Auftrag.query.filter_by(aktiv=True).all()
            print(f"AGENT: {len(alle_auftraege)} aktive Auftraege gefunden.")
            for auftrag in alle_auftraege:
                gedaechtnis_schluessel = f"{auftrag.author.email}_{auftrag.name}"
                ids_fuer_diesen_auftrag = set(alle_gesehenen_artikel.get(gedaechtnis_schluessel, []))
                neue_funde, neue_ids = search_items(access_token, auftrag, ids_fuer_diesen_auftrag)
                alle_gesehenen_artikel[gedaechtnis_schluessel] = list(neue_ids)
                if neue_funde:
                    sende_benachrichtigungs_email(neue_funde, auftrag)
                time.sleep(2)
        speichere_gesehene_artikel(alle_gesehenen_artikel)
        print(f"AGENT JOB BEENDET ({time.ctime()})")

# --- 6. Endlosschleife ---
if __name__ == '__main__':
    print(">>> Agenten-Dienst wird gestartet. Erste Suche startet in 10 Sekunden...")
    time.sleep(10)
    
    while True:
        agenten_job()
        wartezeit_in_minuten = 10
        print(f"\nAGENT: SUCHLAUF BEENDET. Naechster Lauf in {wartezeit_in_minuten} Minuten.")
        time.sleep(wartezeit_in_minuten * 60)
