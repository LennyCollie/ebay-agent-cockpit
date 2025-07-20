#!/usr/bin/env python3
import requests
import base64
import json
import os
import smtplib
from email.mime.text import MIMEText
import time
import urllib.parse

# === KONFIGURATION ===
# Lade die geheimen Zugangsdaten direkt aus der Render-Umgebung
# Wir brauchen hier KEIN dotenv
MEMORY_FILE_NAME = "gesehene_artikel.json"
MY_APP_ID = os.getenv("EBAY_APP_ID")
MY_CERT_ID = os.getenv("EBAY_CERT_ID")
COCKPIT_API_URL = "https://ebay-agent-cockpit.onrender.com" # Dein Cockpit-Name
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")
GITHUB_REPO = os.getenv("GITHUB_REPO")

# === FUNKTIONEN ===

def lade_auftraege_vom_cockpit():
    """Lädt die Auftragsliste von der Cockpit-API."""
    try:
        print("AGENT: Lade aktuelle Auftragsliste vom Cockpit...")
        url = COCKPIT_API_URL + "/api/get_all_jobs"
        response = requests.get(url)
        response.raise_for_status()
        auftragsliste = response.json()
        print(f"AGENT: ERFOLG! {len(auftragsliste)} Aufträge geladen.")
        return auftragsliste
    except Exception as e:
        print(f"AGENT FEHLER: Konnte Auftragsliste vom Cockpit nicht laden: {e}")
        return []

def lade_gedaechtnis_von_github():
    """Lädt die Gedächtnis-Datei direkt von GitHub."""
    url = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents/{MEMORY_FILE_NAME}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    try:
        r = requests.get(url, headers=headers)
        if r.status_code == 404: return {}
        r.raise_for_status()
        content_b64 = r.json()['content']
        content = base64.b64decode(content_b64).decode('utf-8')
        print("AGENT: Gedächtnis von GitHub geladen.")
        return json.loads(content)
    except Exception as e:
        print(f"AGENT FEHLER beim Laden des Gedächtnisses von GitHub: {e}")
        return {}

def speichere_gedaechtnis_zu_github(artikel_daten):
    """Speichert das Gedächtnis direkt auf GitHub."""
    url = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents/{MEMORY_FILE_NAME}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    
    sha = None
    try:
        r = requests.get(url, headers=headers)
        if r.status_code == 200: sha = r.json().get('sha')
    except Exception: pass

    content = json.dumps(artikel_daten, indent=2)
    content_b64 = base64.b64encode(content.encode('utf-8')).decode('utf-8')
    data = {"message": "Agent aktualisiert Gedächtnis", "content": content_b64}
    if sha: data["sha"] = sha
    
    try:
        r_put = requests.put(url, headers=headers, json=data)
        r_put.raise_for_status()
        print("AGENT: Gedächtnis erfolgreich zu GitHub gespeichert.")
    except Exception as e:
        print(f"AGENT FEHLER beim Speichern des Gedächtnisses auf GitHub: {e}")

def get_oauth_token():
    print("AGENT: Hole Zugangsticket...")
    url = "https://api.ebay.com/identity/v1/oauth2/token"
    headers = {'Content-Type': 'application/x-www-form-urlencoded', 'Authorization': 'Basic ' + base64.b64encode(f"{MY_APP_ID}:{MY_CERT_ID}".encode()).decode()}
    body = {'grant_type': 'client_credentials', 'scope': 'https://api.ebay.com/oauth/api_scope'}
    try:
        response = requests.post(url, headers=headers, data=body)
        response.raise_for_status()
        token_data = response.json()
        print("AGENT: ERFOLG! Token erhalten.")
        return token_data.get('access_token')
    except Exception as e:
        print(f"AGENT FEHLER beim Holen des Tokens: {e}")
        return None

def sende_benachrichtigungs_email(neue_funde, auftrag):
    recipient_email = auftrag["user_email"]
    auftrags_name = auftrag["name"]
    # ... (Rest der E-Mail-Funktion ist identisch)
    pass

def search_items(token, auftrag, gesehene_ids_fuer_suche):
    # ... (Diese Funktion ist identisch)
    pass

# === HAUPTPROGRAMM ===
print("Super-Agent (Render-Edition) wird initialisiert...")

while True:
    print("\n" + "="*50)
    print(f"AGENT: NEUER SUCHLAUF STARTET ({time.ctime()})")
    print("="*50)
    
    auftragsliste = lade_auftraege_vom_cockpit()
    
    if not auftragsliste:
        print("AGENT: Keine Aufträge zum Bearbeiten gefunden.")
    else:
        alle_gesehenen_artikel = lade_gedaechtnis_von_github()
        access_token = get_oauth_token()
        
        if access_token:
            for auftrag in auftragsliste:
                gedaechtnis_schluessel = f"{auftrag['user_email']}_{auftrag['name']}"
                ids_fuer_diesen_auftrag = set(alle_gesehenen_artikel.get(gedaechtnis_schluessel, []))
                
                # Hier müssten wir search_items aufrufen
                # und sende_benachrichtigungs_email
                
                print(f"AGENT: Auftrag '{auftrag['name']}' wird verarbeitet.")
                
                # Platzhalter, damit es nicht leer ist
                aktualisierte_ids = ids_fuer_diesen_auftrag
                alle_gesehenen_artikel[gedaechtnis_schluessel] = list(aktualisierte_ids)
                
                time.sleep(2)
        
        speichere_gedaechtnis_zu_github(alle_gesehenen_artikel)
    
    wartezeit_in_minuten = 10
    print(f"\nAGENT: SUCHLAUF BEENDET. Warte {wartezeit_in_minuten} Minuten.")
    time.sleep(wartezeit_in_minuten * 60)
