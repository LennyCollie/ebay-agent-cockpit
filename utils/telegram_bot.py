"""
Simple Telegram bot notifier.
Env vars (Render or .env):
  TELEGRAM_BOT_TOKEN = 123456:ABC...
  TELEGRAM_CHAT_IDS  = 11111111,22222222   # comma-separated
Usage:
  from utils.telegram_bot import notify_new_listing, send_telegram
  send_telegram("Hello from Super-Agent")
  notify_new_listing({"name":"Agent"}, {"title":"Item","price":"199 €","url":"https://...","condition":"Gebraucht"})
"""
from __future__ import annotations
import os, html, requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_IDS_RAW = os.getenv("TELEGRAM_CHAT_IDS", "").strip()
CHAT_IDS = [c.strip() for c in CHAT_IDS_RAW.split(",") if c.strip()]

API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
TIMEOUT = 10

def _post(method: str, payload: dict):
    if not TELEGRAM_BOT_TOKEN or not CHAT_IDS:
        return {"ok": False, "skipped": True, "reason": "no_token_or_chat"}
    url = f"{API}/{method}"
    try:
        r = requests.post(url, json=payload, timeout=TIMEOUT)
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

def send_telegram(text: str, parse_mode: str = "HTML"):
    """Send simple text to all configured chat IDs."""
    results = []
    for chat_id in CHAT_IDS:
        results.append(_post("sendMessage", {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }))
    return results

def notify_new_listing(agent: dict, item: dict):
    """Format and send a new-listing alert."""
    title = html.escape(item.get("title", "Neues Angebot"))
    price = html.escape(item.get("price", "—"))
    cond  = html.escape(item.get("condition", "—"))
    url   = item.get("url", "#")
    ag    = html.escape(agent.get("name", "Agent"))

    text = (
        f"<b>Neues Angebot gefunden</b>\n"
        f"<b>{title}</b>\n"
        f"Preis: {price} • Zustand: {cond}\n"
        f"Agent: {ag}\n"
        f"➡️ <a href='{url}'>Zum Angebot</a>"
    )
    return send_telegram(text)

