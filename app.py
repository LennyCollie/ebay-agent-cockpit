from flask import Flask, render_template, request, redirect, url_for, session
import json
import os
import requests # Requests brauchen wir jetzt auch hier
import base64   # Für das Kodieren der Datei

app = Flask(__name__, template_folder='template')

COCKPIT_PASSWORT = "sepshhtclwtrjwoz"
app.secret_key = 'irgendeine-zufaellige-und-geheime-zeichenkette'

AUFTRAGS_DATEI = 'auftraege.json'
# Lese die GitHub-Infos aus den geheimen Umgebungsvariablen
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")
GITHUB_REPO = os.getenv("GITHUB_REPO")

# --- Lade/Speicher-Funktionen (lokal auf Render) ---
def lade_auftraege():
    try:
        with open(AUFTRAGS_DATEI, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def speichere_auftraege(auftraege):
    with open(AUFTRAGS_DATEI, 'w', encoding='utf-8') as f:
        json.dump(auftraege, f, indent=2, ensure_ascii=False)

# --- NEUE FUNKTION: Die Brücke zu GitHub ---
def commit_zu_github(datei_pfad, commit_nachricht):
    """Liest eine Datei, kodiert sie und lädt sie via GitHub API hoch."""
    url = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents/{datei_pfad}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    # 1. Aktuellen SHA-Hash der Datei auf GitHub holen (nötig für Update)
    try:
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        sha = r.json()['sha']
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404: # Datei existiert noch nicht
             sha = None
        else:
            print(f"Fehler beim Holen des SHA: {e}")
            return
            
    # 2. Lokale Datei lesen und für die API kodieren
    with open(datei_pfad, 'r', encoding='utf-8') as f:
        inhalt = f.read()
    inhalt_b64 = base64.b64encode(inhalt.encode('utf-8')).decode('utf-8')

    # 3. Daten für den Upload vorbereiten
    data = {
        "message": commit_nachricht,
        "content": inhalt_b64,
        "sha": sha # Der SHA des letzten Zustands
    }
    
    # 4. Upload durchführen
    try:
        r = requests.put(url, headers=headers, json=data)
        r.raise_for_status()
        print(f"Erfolgreich zu GitHub committet: {commit_nachricht}")
    except Exception as e:
        print(f"Fehler beim GitHub-Commit: {e}")
        print(r.text)

# --- Routen für die Webseite ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    # ... unverändert ...
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
    # ... unverändert ...
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    auftraege = lade_auftraege()
    return render_template('dashboard.html', auftragsliste=auftraege)

@app.route('/add', methods=['POST'])
def neuer_auftrag():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    auftraege = lade_auftraege()
    neuer_auftrag = {"name": request.form['name'],"keywords": request.form['keywords'],"filter": request.form['filter']}
    auftraege.append(neuer_auftrag)
    speichere_auftraege(auftraege)
    
    # NEU: Nach dem Speichern direkt zu GitHub hochladen
    commit_zu_github(AUFTRAGS_DATEI, f"Neuen Auftrag hinzugefügt: {request.form['name']}")
    
    return redirect(url_for('dashboard'))

@app.route('/delete/<name>', methods=['POST'])
def loesche_auftrag(name):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    auftraege = lade_auftraege()
    auftraege = [auftrag for auftrag in auftraege if auftrag['name'] != name]
    speichere_auftraege(auftraege)
    
    # NEU: Nach dem Löschen direkt zu GitHub hochladen
    commit_zu_github(AUFTRAGS_DATEI, f"Auftrag gelöscht: {name}")

    return redirect(url_for('dashboard'))
```3.  **Ändere das Passwort** in Zeile 9 und **commite** die Änderungen.

**FERTIG!**

Render wird deine App neu starten. Gehe jetzt zu deinem Cockpit auf `...onrender.com`. Füge einen neuen Test-Auftrag hinzu oder lösche einen alten. Gehe dann zu deinem GitHub-Repository und lade die Seite neu. Du wirst sehen, dass sich die `auftraege.json`-Datei dort wie von Geisterhand aktualisiert hat, mit einer Commit-Nachricht wie "Neuen Auftrag hinzugefügt: Test".

Dein Cockpit ist jetzt die offizielle Fernbedienung für deinen Such-Agenten
  
