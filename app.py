from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
import json
import requests
import base64
from datetime import datetime

# --- App & Datenbank Konfiguration ---
app = Flask(__name__, template_folder='template')
app.secret_key = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- GitHub & Passwort Konfiguration ---
COCKPIT_PASSWORT = "sepshhtclwtrjwoz" # BITTE ÄNDERN
AUFTRAGS_DATEI = 'auftraege.json'
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")
GITHUB_REPO = os.getenv("GITHUB_REPO")


# --- Datenbank-Modelle ---
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

class Fund(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.String(20), unique=True, nullable=False) # Die eBay-Artikelnummer
    title = db.Column(db.String(200), nullable=False)
    price = db.Column(db.String(50), nullable=False)
    item_url = db.Column(db.String(500), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    # Fremdschlüssel zum Auftrag-Modell
    auftrag_id = db.Column(db.Integer, db.ForeignKey('auftrag.id'), nullable=False)
    
# --- Hilfsfunktionen ---
def lade_und_committe_auftraege(user_id, commit_nachricht):
    """Lädt alle Aufträge aus der DB, speichert sie als JSON und committet sie zu GitHub."""
    user = User.query.get(user_id)
    if not user:
        return
        
    auftragsliste = []
    for auftrag in user.auftraege:
        auftragsliste.append({
            "name": auftrag.name,
            "keywords": auftrag.keywords,
            "filter": auftrag.filter
        })
        
    # Schreibe die Aufträge in eine temporäre lokale Datei
    with open(AUFTRAGS_DATEI, 'w', encoding='utf-8') as f:
        json.dump(auftragsliste, f, indent=2, ensure_ascii=False)
        
    # Lade die Datei zu GitHub hoch
    commit_zu_github(AUFTRAGS_DATEI, commit_nachricht)


def commit_zu_github(datei_pfad, commit_nachricht):
    """Liest eine lokale Datei und lädt sie via GitHub API hoch."""
    if not all([GITHUB_TOKEN, GITHUB_USERNAME, GITHUB_REPO]):
        print("GitHub-Umgebungsvariablen sind nicht gesetzt. Überspringe Commit.")
        return

    url = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents/{datei_pfad}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    
    sha = None
    try:
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            sha = r.json().get('sha')
    except Exception as e:
        print(f"Info: Konnte initialen SHA nicht holen: {e}")

    with open(datei_pfad, 'r', encoding='utf-8') as f:
        inhalt = f.read()
    inhalt_b64 = base64.b64encode(inhalt.encode('utf-8')).decode('utf-8')

    data = {"message": commit_nachricht, "content": inhalt_b64}
    if sha:
        data["sha"] = sha
    
    try:
        r_put = requests.put(url, headers=headers, json=data)
        r_put.raise_for_status()
        print(f"Erfolgreich zu GitHub committet: {commit_nachricht}")
    except Exception as e:
        print(f"Fehler beim GitHub-Commit: {e}")
        if 'r_put' in locals(): print(r_put.text)


# --- Webseiten-Routen ---
@app.route('/')
def index():
    if session.get('logged_in'):
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    # Lade den User mit seinen Aufträgen UND den zugehörigen Funden
    user = User.query.get(session['user_id'])
    
    # Die Aufträge sind schon geladen (user.auftraege)
    # Und für jeden Auftrag sind die Funde auch schon geladen (auftrag.funde)
    # SQLAlchemy macht das automatisch für uns!
    
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
    
    neuer_auftrag = Auftrag(
        name=request.form.get('name'),
        keywords=request.form.get('keywords'),
        filter=request.form.get('filter'),
        user_id=session['user_id']
    )
    db.session.add(neuer_auftrag)
    db.session.commit()
    
    # Committe die komplette, aktualisierte Liste des Users zu GitHub
    lade_und_committe_auftraege(session['user_id'], f"Auftrag hinzugefügt: {neuer_auftrag.name}")
    
    return redirect(url_for('dashboard'))

@app.route('/delete/<int:auftrag_id>', methods=['POST'])
def loesche_auftrag(auftrag_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    
    auftrag = Auftrag.query.get_or_404(auftrag_id)
    if auftrag.author.id != session['user_id']:
        return "Nicht autorisiert", 403
        
    geloeschter_name = auftrag.name
    db.session.delete(auftrag)
    db.session.commit()
    
    # Committe die komplette, aktualisierte Liste des Users zu GitHub
    lade_und_committe_auftraege(session['user_id'], f"Auftrag gelöscht: {geloeschter_name}")

    return redirect(url_for('dashboard'))
# ... (der Code für @app.route('/delete/...') bleibt unverändert) ...

# =============================================================
# NEU: Die geheime API-Hintertür für unseren Such-Agenten
# =============================================================
@app.route('/api/get_all_jobs')
def get_all_jobs():
    # Hier könnte man später einen geheimen API-Schlüssel einbauen
    # Für den Moment ist die URL selbst unser "Passwort"
    
    alle_auftraege = Auftrag.query.all()
    
    # Wir formatieren die Daten so, wie unser Agent sie erwartet
    auftragsliste_fuer_agent = []
    for auftrag in alle_auftraege:
        auftragsliste_fuer_agent.append({
            "name": auftrag.name,
            "keywords": auftrag.keywords,
            "filter": auftrag.filter,
            "user_email": auftrag.author.email # HIER DIE NEUE ZEILE!
        })
        
    # Wir importieren jsonify hier, da es nur hier gebraucht wird
    from flask import jsonify
    return jsonify(auftragsliste_fuer_agent)


# --- Datenbank initialisieren ---

@app.route('/api/report_fund', methods=['POST'])
def report_fund():
    # Hier brauchen wir einen geheimen Schlüssel, damit nicht jeder Funde melden kann
    # Wir speichern ihn sicher als Umgebungsvariable
    API_SECRET_KEY = os.getenv("API_SECRET_KEY", "ein-default-geheimnis")
    
    # Prüfe den geheimen Schlüssel
    if request.headers.get('X-API-Secret') != API_SECRET_KEY:
        return "Nicht autorisiert", 401

    data = request.get_json()
    if not data:
        return "Keine Daten erhalten", 400

    # Finde den passenden Auftrag in der Datenbank
    auftrag = Auftrag.query.filter_by(name=data['auftrags_name'], user_id=data['user_id']).first()
    
    if auftrag:
        # Prüfe, ob dieser Fund (anhand der eBay item_id) schon existiert
        existierender_fund = Fund.query.filter_by(item_id=data['item_id']).first()
        if not existierender_fund:
            neuer_fund = Fund(
                item_id=data['item_id'],
                title=data['title'],
                price=data['price'],
                item_url=data['item_url'],
                auftrag_id=auftrag.id
            )
            db.session.add(neuer_fund)
            db.session.commit()
            return "Fund gespeichert", 201
        else:
            return "Fund bereits bekannt", 200
    
    return "Passender Auftrag nicht gefunden", 404

with app.app_context():
    db.create_all()

