
import json
import time
import requests
from datetime import datetime, timezone

# Beispielhafte Konfiguration
WEBHOOK_URL = "https://example.com/webhook"  # <- Ersetze durch echte URL
DATA_FILE = "auftraege.json"

def lade_auftraege():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        return []

def sende_webhook(auftrag):
    payload = {
        "title": auftrag.get("titel", "Kein Titel"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "details": auftrag
    }

    try:
        response = requests.post(WEBHOOK_URL, json=payload)
        if response.status_code == 200:
            print(f"Webhook gesendet für Auftrag: {auftrag['titel']}")
        else:
            print(f"Fehler beim Senden: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Webhook-Fehler: {e}")

def main():
    print("Starte Agent...")
    auftraege = lade_auftraege()

    for auftrag in auftraege:
        sende_webhook(auftrag)
        time.sleep(2)  # kurze Pause zwischen Webhooks

    print("Alle Aufträge verarbeitet.")

if __name__ == "__main__":
    main()
