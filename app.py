from flask import Flask, render_template, request, redirect, url_for, session
import json
import os
import requests
import base64

# --- App Konfiguration ---
app = Flask(__name__, template_folder='template')
app.secret_key = os.urandom(24) # Erzeugt einen sicheren, zufälligen Secret Key

# --- Globale Variablen ---
COCKPIT_PASSWORT = "sepshhtclwtrjwoz" # BITTE ÄNDERN
AUFTRAGS_DATEI = 'auftraege.json'
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")
GITHUB_REPO = os.getenv("GITHUB_REPO")

# --- Hilfsfunktionen ---
def lade_auftraege():
    try:
        with open(AUFTRAGS_DATEI, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def speichere_auftraege(auftraege):
    with open(AUFTRAGS_DATEI, 'w', encoding='utf-8') as f:
        json.dump(auftraege, f, indent=2, ensure_ascii=False)
    # Nach dem lokalen Speichern, lade die Änderung zu GitHub hoch
    commit_zu_github(AUFTRAGS_DATEI, "Suchaufträge aktualisiert via Cockpit")

def commit_zu_github(datei_pfad, commit_nachricht):
    if not all([GITHUB_TOKEN, GITHUB_USERNAME, GITHUB_REPO]):
        print("GitHub-Umgebungsvariablen sind nicht gesetzt. Überspringe Commit.")
        return

    url = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents/{datei_pfad}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    
    sha = None
    try:
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            sha = r.json()['sha']
    except Exception as e:
        print(f"Fehler beim Holen des SHA: {e}")

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
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form.get('passwort') == COCKPIT_PASSWORT:
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
    if not session.get('logged_in'): return redirect(url_for('login'))
    
    auftraege = lade_auftraege()
    auftraege.append({
        "name": request.form.get('name'),
        "keywords": request.form.get('keywords'),
        "filter": request.form.get('filter')
    })
    speichere_auftraege(auftraege)
    return redirect(url_for('dashboard'))

@app.route('/delete/<name>', methods=['POST'])
def loesche_auftrag(name):
    if not session.get('logged_in'): return redirect(url_for('login'))
    
    auftraege = lade_auftraege()
    auftraege_neu = [auftrag for auftrag in auftraege if auftrag.get('name') != name]
    speichere_auftraege(auftraege_neu)
    return redirect(url_for('dashboard'))

