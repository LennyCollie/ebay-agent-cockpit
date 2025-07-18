#!/usr/bin/env python3
import requests
import base64
import os
import time

# === KONFIGURATION ===
MY_APP_ID = "MarkusSc-Producti-PRD-ec5701265-b8cbab3x"
MY_CERT_ID = "PRD-c5701265d502-a21a-4d72-aca5-2817"

# === FUNKTIONEN ===
def get_oauth_token():
    print(">>> Hole Zugangsticket...")
    url = "https://api.ebay.com/identity/v1/oauth2/token"
    headers = {'Content-Type': 'application/x-www-form-urlencoded', 'Authorization': 'Basic ' + base64.b64encode(f"{MY_APP_ID}:{MY_CERT_ID}".encode()).decode()}
    body = {'grant_type': 'client_credentials', 'scope': 'https://api.ebay.com/oauth/api_scope'}
    try:
        response = requests.post(url, headers=headers, data=body)
        response.raise_for_status()
        token_data = response.json()
        print("    ERFOLG! Token erhalten.")
        return token_data.get('access_token')
    except Exception as e:
        print(f"    FEHLER beim Holen des Tokens: {e}")
        return None

# === HAUPTPROGRAMM ===
print("Super-Agent (Phase 2 Test) wird gestartet...")

while True:
    print(f"\n=== Neuer Testlauf startet ({time.ctime()}) ===")
    access_token = get_oauth_token()
    
    if access_token:
        print("    --> Authentifizierung bei eBay war ERFOLGREICH!")
    else:
        print("    --> Authentifizierung bei eBay ist FEHLGESCHLAGEN.")
        
    print(f"Schlafe für 60 Sekunden.")
    time.sleep(60)
    
