      
from flask import Flask, render_template, request, redirect, url_for, session
import json # Wir brauchen json, um die neue Datei zu lesen

app = Flask(__name__, template_folder='template')

COCKPIT_PASSWORT = "sepshhtclwtrjwoz"
app.secret_key = 'irgendeine-zufaellige-und-geheime-zeichenkette'

def lade_auftraege():
    """NEU: Lädt die Auftragsliste aus der zentralen JSON-Datei."""
    try:
        # Im Live-Betrieb auf Render liegt die Datei im selben Ordner.
        with open('auftraege.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Fehler beim Laden der Aufträge: {e}")
        return []

@app.route('/login', methods=['GET', 'POST'])
def login():
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
    
    # NEU: Lade die Aufträge und übergebe sie an die Webseite
    auftraege = lade_auftraege()
    return render_template('dashboard.html', auftragsliste=auftraege)

# Den alten Startknopf entfernen wir, da wir ihn nicht mehr brauchen

    
  
