#!/usr/bin/python3.13
import requests
import base64
import json
import os
import smtplib
from email.mime.text import MIMEText
import time
import urllib.parse




MEMORY_FILE = "gesehene_artikel.json"


# Deine eBay Production Keys
MY_APP_ID = "MarkusSc-Producti-PRD-ec5701265-b8cbab3a"
MY_CERT_ID = "PRD-c5701265d502-a21a-4d72-aca5-2817"

# URLs und geheime Schlüssel
COCKPIT_API_URL = "https://ebay-agent-cockpit.onrender.com"
API_SECRET_KEY = os.getenv("API_SECRET_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")
GITHUB_REPO = os.getenv("GITHUB_REPO")

# === Funktionen ===

def lade_auftraege_vom_cockpit():
    """Lädt die Auftragsliste von der Cockpit-API."""
    try:
        print(">>> Lade aktuelle Auftragsliste vom Cockpit...")
        url = COCKPIT_API_URL + "/api/get_all_jobs"
        response = requests.get(url)
        response.raise_for_status()
        auftragsliste = response.json()
        print(f"    ERFOLG! {len(auftragsliste)} Aufträge geladen.")
        return auftragsliste
    except Exception as e:
        print(f"    FEHLER: Konnte Auftragsliste vom Cockpit nicht laden: {e}")
        return []

def lade_gedaechtnis_von_github():
    # ... (Diese Funktion bleibt unverändert) ...
    pass
def speichere_gedaechtnis_zu_github(artikel_daten):
    # ... (Diese Funktion bleibt unverändert) ...
    pass
def get_oauth_token():
    # ... (Diese Funktion bleibt unverändert) ...
    pass
def sende_benachrichtigungs_email(neue_funde, auftrag):
    # ... (Diese Funktion bleibt unverändert) ...
    pass

# NEUE FUNKTION: Meldet einen einzelnen Fund an das Cockpit
def melde_fund_an_cockpit(item_details, auftrag):
    """Sendet die Daten eines neuen Funds an die API des Cockpits."""
    print(f"    INFO: Melde Fund '{item_details['title']}' an das Cockpit...")

    url = COCKPIT_API_URL + "/api/report_fund"
    headers = {
        'Content-Type': 'application/json',
        'X-API-Secret': API_SECRET_KEY
    }

    # Wir erstellen den "Payload", also die Daten, die wir senden
    payload = item_details.copy()
    payload['auftrags_name'] = auftrag['name']
    payload['user_email'] = auftrag['user_email']

    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 201:
            print("    ERFOLG: Cockpit hat Fund gespeichert.")
        else:
            print(f"    WARNUNG: Cockpit hat den Fund nicht gespeichert. Status: {response.status_code}, Antwort: {response.text}")
    except Exception as e:
        print(f"    FEHLER bei der Meldung an das Cockpit: {e}")

def search_items(token, auftrag, gesehene_ids_fuer_suche):
    keywords = auftrag["keywords"]
    filters = auftrag.get("filter", "")
    print(f"\n>>> **STARTE AUFTRAG:** '{auftrag['name']}'")
    params = {'q': keywords, 'limit': 20}
    if filters: params['filter'] = filters
    url = f"https://api.ebay.com/buy/browse/v1/item_summary/search?{urllib.parse.urlencode(params)}"
    headers = {'Authorization': f'Bearer {token}', 'X-EBAY-C-MARKETPLACE-ID': 'EBAY_DE'}
    gefundene_neue_artikel = []

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        results = response.json()
        if results.get('total', 0) > 0:
            for item in results.get('itemSummaries', []):
                item_id = item.get('itemId')
                if item_id and item_id not in gesehene_ids_fuer_suche:
                    details = {
                        'item_id': item_id,
                        'title': item.get('title', 'N/A'),
                        'price': item.get('price', {}).get('value', 'N/A') + " " + item.get('price', {}).get('currency', ''),
                        'itemWebUrl': item.get('itemWebUrl', '#')
                    }
                    gefundene_neue_artikel.append(details)
                    gesehene_ids_fuer_suche.add(item_id)

                    # HIER WIRD DIE NEUE FUNKTION AUFGERUFEN!
                    melde_fund_an_cockpit(details, auftrag)
    except Exception as e:
        print(f"    FEHLER bei der Suche: {e}")
    return gefundene_neue_artikel, gesehene_ids_fuer_suche

# === HAUPTPROGRAMM (bleibt fast gleich) ===
# ... (Hier der unveränderte Code der Hauptschleife) ...

