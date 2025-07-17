from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
import json

# --- App & Datenbank Konfiguration ---
app = Flask(__name__, template_folder='template')
app.secret_key = os.urandom(24)

# Konfiguriere die SQLite-Datenbank. Render speichert sie persistent.
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- Datenbank-Modelle (Die Tabellen) ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    # Verknüpfung zu den Aufträgen
    auftraege = db.relationship('Auftrag', backref='author', lazy=True)

class Auftrag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    keywords = db.Column(db.String(200), nullable=False)
    filter = db.Column(db.String(300), nullable=True)
    # Fremdschlüssel zum User-Modell
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

# --- Routen für die Webseite ---

@app.route('/')
def index():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    # Finde den aktuellen User in der Datenbank
    user = User.query.get(session['user_id'])
    # Lade nur die Aufträge DIESES Users
    auftraege = user.auftraege
    return render_template('dashboard.html', auftragsliste=auftraege)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        # Prüfe, ob der Benutzer schon existiert
        user = User.query.filter_by(email=email).first()
        if user:
            flash('Diese E-Mail-Adresse ist bereits registriert.')
            return redirect(url_for('register'))

        # Erstelle einen sicheren Hash des Passworts
        password_hash = generate_password_hash(password, method='pbkdf2:sha256')
        
        # Erstelle einen neuen Benutzer und speichere ihn in der DB
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
        
        # Prüfe, ob der User existiert UND das Passwort korrekt ist
        if not user or not check_password_hash(user.password_hash, password):
            flash('Bitte überprüfe deine Login-Daten und versuche es erneut.')
            return redirect(url_for('login'))
            
        # Speichere die User-ID in der Session
        session['logged_in'] = True
        session['user_id'] = user.id
        
        return redirect(url_for('index'))
        
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear() # Löscht alle Session-Daten
    return redirect(url_for('login'))

@app.route('/add', methods=['POST'])
def neuer_auftrag():
    if not session.get('logged_in'): return redirect(url_for('login'))
    
    neuer_auftrag = Auftrag(
        name=request.form.get('name'),
        keywords=request.form.get('keywords'),
        filter=request.form.get('filter'),
        user_id=session['user_id'] # Verknüpfe den Auftrag mit dem eingeloggten User
    )
    db.session.add(neuer_auftrag)
    db.session.commit()
    
    return redirect(url_for('index'))

@app.route('/delete/<int:auftrag_id>', methods=['POST'])
def loesche_auftrag(auftrag_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
        
    auftrag = Auftrag.query.get_or_404(auftrag_id)
    # Sicherheitscheck: Darf dieser User diesen Auftrag löschen?
    if auftrag.author.id != session['user_id']:
        return "Nicht autorisiert", 403
        
    db.session.delete(auftrag)
    db.session.commit()
    
    return redirect(url_for('index'))

# Einmaliger Befehl, um die Datenbank zu erstellen
with app.app_context():
    # ... (der ganze Code von vorher bleibt unverändert) ...

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
            "filter": auftrag.filter
        })
        
    # Wir geben die Liste als sauberen JSON-Text zurück
    return jsonify(auftragsliste_fuer_agent)


# Einmaliger Befehl, um die Datenbank zu erstellen
with app.app_context():
    db.create_all()
    db.create_all()
