from flask import Flask, render_template, request, redirect, url_for, session
import json
import os # NEU: Für GitHub-Authentifizierung

app = Flask(__name__, template_folder='template')

COCKPIT_PASSWORT = "sepshhtclwtrjwoz"
app.secret_key = 'irgendeine-zufaellige-und-geheime-zeichenkette'

# --- Pfad zur lokalen Kopie der Auftragsdatei ---
# Render klont das GitHub Repo, die Datei ist also lokal verfügbar
AUFTRAGS_DATEI = 'auftraege.json'

def lade_auftraege():
    """Lädt die Auftragsliste aus der JSON-Datei."""
    try:
        with open(AUFTRAGS_DATEI, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def speichere_auftraege(auftraege):
    """Speichert die Auftragsliste in die JSON-Datei."""
    with open(AUFTRAGS_DATEI, 'w', encoding='utf-8') as f:
        # indent=2 sorgt für eine schön formatierte Datei
        json.dump(auftraege, f, indent=2)

@app.route('/login', methods=['GET', 'POST'])
def login():
    #... (unverändert)
    error = None
    if request.method == 'POST':
        if request.form['passwort'] == COCKPIT_PASSWORT:
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        else:
            error = 'Falsches Passwort!'
    return render_template('login.html', error=error)

@app.route('/')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    auftraege = lade_auftraege()
    return render_template('dashboard.html', auftragsliste=auftraege)

@app.route('/add', methods=['POST'])
def neuer_auftrag():
    """NEU: Fügt einen neuen Auftrag hinzu."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    auftraege = lade_auftraege()
    neuer_auftrag = {
        "name": request.form['name'],
        "keywords": request.form['keywords'],
        "filter": request.form['filter']
    }
    auftraege.append(neuer_auftrag)
    speichere_auftraege(auftraege)
    
    # Hier müssten wir den Commit zu GitHub machen (nächster Schritt)
    print("TODO: Änderungen zu GitHub pushen!")

    return redirect(url_for('dashboard'))

@app.route('/delete/<name>', methods=['POST'])
def loesche_auftrag(name):
    """NEU: Löscht einen Auftrag."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    auftraege = lade_auftraege()
    # Erstellt eine neue Liste ohne den zu löschenden Auftrag
    auftraege = [auftrag for auftrag in auftraege if auftrag['name'] != name]
    speichere_auftraege(auftraege)
    
    # Hier müssten wir den Commit zu GitHub machen (nächster Schritt)
    print("TODO: Änderungen zu GitHub pushen!")

    return redirect(url_for('dashboard'))
    
  
