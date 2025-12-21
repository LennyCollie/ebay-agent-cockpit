import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DOMAIN = "https://ebay-agent-cockpit.onrender.com"

if not TOKEN:
    print("❌ TELEGRAM_BOT_TOKEN nicht in .env gefunden!")
    exit(1)

url = f"https://api.telegram.org/bot{TOKEN}/setWebhook"
payload = {"url": f"{DOMAIN}/telegram/webhook"}

print(f"🔧 Setze Telegram Webhook...")
print(f"   Domain: {DOMAIN}/telegram/webhook")
print()

response = requests.post(url, json=payload)
print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")
print()

if response.json().get("ok"):
    print("✅ Webhook erfolgreich gesetzt!")
else:
    print("❌ Fehler beim Setzen des Webhooks!")
