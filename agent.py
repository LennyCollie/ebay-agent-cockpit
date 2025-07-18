      
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
MEMORY_FILE = "gesehene_artikel.json"
MY_APP_ID = "MarkusSc-Producti-PRD-ec5701265-b8cbab3a"
MY_CERT_ID = "PRD-c5701265d502-a21a-4d72-aca5-2817"
COCKPIT_API_URL = "https://ebay-agent-cockpit.onrender.com"
API_SECRET_KEY = os.getenv("API_SECRET_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")
GITHUB_REPO = os.getenv("GITHUB_REPO")

# === HILFSFUNKTIONEN (Die lassen wir vorerst ungenutzt) ===
def dummy_funktion():
    pass

# === HAUPTPROGRAMM (Die "Lebenszeichen"-Schleife) ===
print("Super-Agent (Lebenszeichen-Test) wird gestartet...")

while True:
    print(f"Agent lebt! Zeit: {time.ctime()}. Schlafe für 60 Sekunden.")
    time.sleep(60) # Warte 60 Sekunden

    
