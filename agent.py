import os
import time
import json
import base64
import requests
import smtplib
import urllib.parse
from datetime import datetime
from email.mime.text import MIMEText
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

# === Setup ===
app = Flask(__name__)
db_url = os.getenv('DATABASE_URL')

# Fix für alte PostgreSQL-URLs
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# === eBay & Mail Konfiguration ===
EBAY_APP_ID = os.getenv("EBAY_APP_ID")
EBAY_CERT_ID = os.getenv("EBAY_CERT_ID")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
MEMORY_FILE = "seen_items.json"

# === Datenbankmodelle ===
class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String, nullable=False)
    auftraege = db.relationship("Auftrag", backref="author", lazy=True)

class Auftrag(db.Model):
    __tablename__ = 'auftrag'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    keywords = db.Column(db.String, nullable=False)
    filter = db.Column(db.String)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    aktiv = db.Column(db.Boolean, default=True)

# === Hilfsfunktionen ===
def load_seen():
    try:
        with open(MEMORY_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_seen(seen):
    with open(MEMORY_FILE, 'w') as f:
        json.dump(seen, f)

def get_ebay_token():
    if not (EBAY_APP_ID and EBAY_CERT_ID):
        print("❌ EBAY Credentials fehlen")
        return None
    creds = f"{EBAY_APP_ID}:{EBAY_CERT_ID}"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": "Basic " + base64.b64encode(creds.encode()).decode()
    }
    data = {"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"}
    try:
        r = requests.post("https://api.ebay.com/identity/v1/oauth2/token", headers=headers, data=data)
        r.raise_for_status()
        return r.json().get("access_token")
    except Exception as e:
        print(f"❌ Tokenfehler: {e}")
        return None

def send_email(to, subject, body):
    msg = MIMEText(body, "plain", "utf-8")
    msg['Subject'] = subject
    msg['From'] = SENDER_EMAIL
    msg['To'] = to

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(SENDER_EMAIL, EMAIL_PASSWORD)
            server.sendmail(SENDER_EMAIL, to, msg.as_string())
        print(f"📧 E-Mail an {to} gesendet.")
    except Exception as e:
        print(f"❌ Mailfehler: {e}")

def search_items(token, auftrag, seen_ids):
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_DE"
    }

    query = f"q={urllib.parse.quote(auftrag.keywords)}"
    if auftrag.filter:
        query += f"&filter={urllib.parse.quote(auftrag.filter)}"

    url = f"https://api.ebay.com/buy/browse/v1/item_summary/search?{query}&limit=20"

    try:
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        items = r.json().get("itemSummaries", [])
        new_items = []
        for item in items:
            item_id = item.get("itemId")
            if item_id and item_id not in seen_ids:
                new_items.append({
                    "title": item.get("title"),
                    "price": item.get("price", {}).get("value"),
                    "url": item.get("itemWebUrl")
                })
                seen_ids.add(item_id)
        return new_items, seen_ids
    except Exception as e:
        print(f"❌ Suchfehler: {e}")
        return [], seen_ids

# === Agentenlogik ===
def run_agent():
    print(f"\n🕘 Agentenlauf gestartet: {datetime.utcnow()}")

    token = get_ebay_token()
    if not token:
        return

    seen = load_seen()
    auftraege = Auftrag.query.filter_by(aktiv=True).all()
    print(f"🔍 {len(auftraege)} aktive Aufträge gefunden")

    for auftrag in auftraege:
        key = f"{auftrag.user_id}_{auftrag.name}"
        known_ids = set(seen.get(key, []))
        neue_funde, updated_ids = search_items(token, auftrag, known_ids)

        if neue_funde:
            body = f"Hallo!\n\nFür deinen Auftrag '{auftrag.name}' wurden {len(neue_funde)} neue Artikel gefunden:\n\n"
            for f in neue_funde:
                body += f"- {f['title']} für {f['price']} EUR\n{f['url']}\n\n"
            send_email(auftrag.author.email, f"[{auftrag.name}] Neue eBay Funde", body)

        seen[key] = list(updated_ids)
        time.sleep(1)

    save_seen(seen)
    print(f"✅ Agentenlauf beendet\n")

# === Main ===
if __name__ == "__main__":
    with app.app_context():
        run_agent()

