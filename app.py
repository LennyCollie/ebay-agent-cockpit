
from flask import Flask, render_template, request, redirect, url_for, session
import subprocess

app = Flask(__name__, template_folder='template')
# Ein geheimes Passwort, das nur du kennst. Ändere das!
# Dieses Passwort wird für den Login auf der Webseite gebraucht.
COCKPIT_PASSWORT = "sepshhtclwtrjwoz"

# Ein "Secret Key" ist für die sichere Verwaltung von Sessions (Login-Status) nötig.
# Die Zeichenkette kann irgendetwas Langes und Zufälliges sein.
app.secret_key = 'irgendeine-zufaellige-und-geheime-zeichenkette'


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        # Prüft, ob das eingegebene Passwort korrekt ist
        if request.form['passwort'] == COCKPIT_PASSWORT:
            # Speichert in der Session, dass der Nutzer eingeloggt ist
            session['logged_in'] = True
            # Leitet zur geheimen Dashboard-Seite weiter
            return redirect(url_for('dashboard'))
        else:
            # Zeigt eine Fehlermeldung an
            error = 'Falsches Passwort!'
    # Zeigt die login.html Seite an
    return render_template('login.html', error=error)


@app.route('/')
def dashboard():
    # Prüft, ob der Nutzer eingeloggt ist
    if not session.get('logged_in'):
        # Wenn nicht, wird er zur Login-Seite geschickt
        return redirect(url_for('login'))

    # Wenn er eingeloggt ist, zeige die dashboard.html Seite an
    return render_template('dashboard.html')


# Den alten "Startknopf" behalten wir vorerst, falls wir ihn brauchen
@app.route('/starte-suche-bitte-danke')
def starte_suche():
    befehl = "/home/LennyColli/suche_mit_browse_api.py"
    subprocess.Popen([befehl])
    return "Suchprozess wurde im Hintergrund gestartet!"

