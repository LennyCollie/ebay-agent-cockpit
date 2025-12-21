import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional, List
from dotenv import load_dotenv

load_dotenv()

import requests
from database import get_db, get_placeholder

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
PH = get_placeholder()


class TelegramBot:
    """Telegram Bot Handler für eBay Alerts"""

    def __init__(self, token: Optional[str] = None):
        self.token = token or TELEGRAM_BOT_TOKEN
        self.api_url = f"https://api.telegram.org/bot{self.token}"

        if not self.token:
            logger.warning("[!] TELEGRAM_BOT_TOKEN nicht gesetzt!")

    def is_configured(self) -> bool:
        """Prüft ob Bot konfiguriert ist"""
        return bool(self.token and len(self.token) > 10)

    def get_me(self) -> Optional[Dict[str, Any]]:
        """Ruft Telegram getMe ab und gibt das Result-Objekt zurück (oder None)"""
        if not self.is_configured():
            return None
        try:
            r = requests.get(f"{self.api_url}/getMe", timeout=10)
            if r.status_code == 200:
                data = r.json()
                return data.get("result")
            else:
                logger.error(f"getMe failed: {r.status_code} {r.text}")
        except Exception as e:
            logger.exception(f"getMe exception: {e}")
        return None

    def get_username(self) -> Optional[str]:
        """Versucht den Bot-Username aus getMe zu lesen"""
        me = self.get_me()
        if not me:
            return None
        username = me.get("username")
        if username:
            return username
        return me.get("first_name")

    def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = False,
        reply_markup: Optional[Dict] = None,
    ) -> bool:
        """
        Sendet eine Nachricht an einen User
        """
        if not self.is_configured():
            logger.error("Telegram Bot nicht konfiguriert!")
            return False

        try:
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": disable_web_page_preview,
            }

            if reply_markup:
                payload["reply_markup"] = reply_markup

            response = requests.post(
                f"{self.api_url}/sendMessage", json=payload, timeout=10
            )

            if response.status_code == 200:
                logger.info(f"[OK] Telegram Nachricht gesendet an {chat_id}")
                return True
            else:
                logger.error(f"[!] Telegram API Error: {response.status_code} {response.text}")
                return False

        except Exception as e:
            logger.error(f"[!] Fehler beim Senden: {e}")
            return False

    def send_photo(
        self,
        chat_id: str,
        photo_url: str,
        caption: str = "",
        reply_markup: Optional[Dict] = None,
    ) -> bool:
        """Sendet ein Bild mit Caption"""
        if not self.is_configured():
            return False

        try:
            payload = {
                "chat_id": chat_id,
                "photo": photo_url,
                "caption": caption,
                "parse_mode": "HTML",
            }

            if reply_markup:
                payload["reply_markup"] = reply_markup

            response = requests.post(
                f"{self.api_url}/sendPhoto", json=payload, timeout=10
            )

            if response.status_code == 200:
                logger.info(f"[OK] Telegram Foto gesendet an {chat_id}")
                return True
            else:
                logger.error(f"[!] Telegram API Error sendPhoto: {response.status_code} {response.text}")
                return False

        except Exception as e:
            logger.error(f"[!] Fehler beim Senden des Bildes: {e}")
            return False

    def get_chat_info(self, chat_id: str) -> Optional[Dict[str, Any]]:
        """Holt Infos über einen Chat/User"""
        if not self.is_configured():
            return None

        try:
            response = requests.get(
                f"{self.api_url}/getChat", params={"chat_id": chat_id}, timeout=10
            )

            if response.status_code == 200:
                return response.json().get("result")
            logger.error(f"get_chat_info failed: {response.status_code} {response.text}")
            return None

        except Exception as e:
            logger.error(f"[!] Fehler beim Abrufen der Chat-Info: {e}")
            return None


def format_ebay_alert(item: Dict[str, Any], agent_name: str = "eBay Alert") -> str:
    title = item.get("title", "Unbekannt")
    price = item.get("price", "N/A")
    currency = item.get("currency", "EUR")
    url = item.get("url", "")
    condition = item.get("condition", "")
    location = item.get("location", "")

    emoji = "🔥" if "angebot" in title.lower() or "sale" in title.lower() else "[+]"

    message = f"""
{emoji} <b>Neues Angebot gefunden!</b>

<b>📋 Agent:</b> {agent_name}
<b>🏷️ Titel:</b> {title}

<b>💰 Preis:</b> {price} {currency}
"""

    if condition:
        message += f"<b>✨ Zustand:</b> {condition}\n"

    if location:
        message += f"<b>📍 Standort:</b> {location}\n"

    message += f"\n<b>🔗 Link:</b> <a href='{url}'>Jetzt ansehen</a>"
    message += f"\n\n<i>⏰ Gefunden: {datetime.now().strftime('%H:%M Uhr')}</i>"

    return message


def create_item_buttons(item_url: str, alert_id: Optional[int] = None) -> Dict:
    """Erstellt Inline-Buttons für ein Item"""
    buttons = [
        [{"text": "🛒 Zu eBay", "url": item_url}],
    ]
    
    if alert_id:
        buttons.append([
            {"text": "⏸️ Pausieren", "callback_data": f"pause_alert_{alert_id}"},
            {"text": "🗑️ Löschen", "callback_data": f"delete_alert_{alert_id}"},
        ])
    
    return {"inline_keyboard": buttons}


def format_welcome_message(user_name: str = "User") -> str:
    """Willkommensnachricht bei Verknüpfung"""
    return f"""
👋 <b>Willkommen bei eBay Super-Agent, {user_name}!</b>

Dein Telegram wurde erfolgreich verknüpft! 🎉

Ab sofort erhältst du <b>Echtzeit-Benachrichtigungen</b>, sobald neue Artikel gefunden werden, die zu deinen Such-Agenten passen.

<b>📱 Verfügbare Befehle:</b>
/list – Zeige alle meine Alerts
/pause [ID] – Alert pausieren
/resume [ID] – Alert weitermachen
/delete [ID] – Alert löschen
/help – Hilfe anzeigen

<b>Vorteile:</b>
⚡ Sofortige Push-Notifications
📱 Direkt auf dein Handy
🔗 Klick direkt zum eBay-Angebot
🔕 Flexible Einstellungen

Viel Erfolg beim Schnäppchen-Jagen! 🎯
"""


def format_alert_list(alerts: List[Dict[str, Any]]) -> str:
    """Formatiert die Liste aller Alerts"""
    if not alerts:
        return "📭 <b>Keine Alerts gefunden</b>\n\nErstelle einen neuen Alert auf der Website! 🌐"
    
    message = "<b>📋 Deine aktiven Alerts:</b>\n\n"
    
    for alert in alerts:
        alert_id = alert.get("id", "?")
        terms = alert.get("terms", [])
        source = alert.get("source", "ebay").upper()
        is_active = alert.get("is_active", False)
        status = "✅ AKTIV" if is_active else "⏸️ PAUSIERT"
        
        terms_str = ", ".join(terms[:3]) if terms else "keine"
        message += f"<b>#{alert_id}</b> [{status}]\n"
        message += f"  🔍 {terms_str}\n"
        message += f"  📦 {source}\n"
        message += f"  ➡️ /pause {alert_id}  /resume {alert_id}  /delete {alert_id}\n\n"
    
    return message


def format_help_message() -> str:
    """Hilfenachricht mit allen Commands"""
    return """
<b>🤖 Super-Agent Bot Befehle:</b>

<b>/list</b> – Zeige alle meine Alerts
<b>/pause [ID]</b> – Alert pausieren
  Beispiel: /pause 5

<b>/resume [ID]</b> – Alert weitermachen
  Beispiel: /resume 5

<b>/delete [ID]</b> – Alert löschen
  Beispiel: /delete 5

<b>/help</b> – Diese Hilfe

<b>💡 Tipp:</b> Deine Alert-ID findest du mit /list

<b>🌐 Mehr Features auf:</b> /settings
"""


def handle_telegram_update(update: Dict[str, Any]) -> bool:
    """
    Verarbeitet Telegram Updates (Befehle & Button-Clicks)
    """
    bot = TelegramBot()
    
    try:
        if "message" in update:
            return handle_message(update["message"], bot)
        elif "callback_query" in update:
            return handle_callback_query(update["callback_query"], bot)
    except Exception as e:
        logger.error(f"[telegram] handle_telegram_update error: {e}")
    
    return False


def handle_message(message: Dict[str, Any], bot: TelegramBot) -> bool:
    """Verarbeitet Nachrichten/Commands"""
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip()
    
    if not chat_id or not text:
        return False
    
    logger.info(f"[telegram] Message from {chat_id}: {text}")
    
    if text.startswith("/list"):
        return cmd_list_alerts(chat_id, bot)
    
    elif text.startswith("/pause"):
        alert_id = extract_alert_id(text)
        if alert_id:
            return cmd_pause_alert(chat_id, alert_id, bot)
        else:
            bot.send_message(chat_id, "⚠️ Format: /pause [ID]\nBeispiel: /pause 5")
            return True
    
    elif text.startswith("/resume"):
        alert_id = extract_alert_id(text)
        if alert_id:
            return cmd_resume_alert(chat_id, alert_id, bot)
        else:
            bot.send_message(chat_id, "⚠️ Format: /resume [ID]\nBeispiel: /resume 5")
            return True
    
    elif text.startswith("/delete"):
        alert_id = extract_alert_id(text)
        if alert_id:
            return cmd_delete_alert(chat_id, alert_id, bot)
        else:
            bot.send_message(chat_id, "⚠️ Format: /delete [ID]\nBeispiel: /delete 5")
            return True
    
    elif text.startswith("/help"):
        return bot.send_message(chat_id, format_help_message())
    
    elif text.startswith("/start"):
        return bot.send_message(chat_id, format_welcome_message())
    
    else:
        return bot.send_message(
            chat_id,
            "❓ Unbekannter Befehl. Nutze /help für verfügbare Befehle."
        )


def handle_callback_query(callback: Dict[str, Any], bot: TelegramBot) -> bool:
    """Verarbeitet Button-Clicks"""
    chat_id = callback.get("message", {}).get("chat", {}).get("id")
    data = callback.get("data", "")
    
    if not chat_id or not data:
        return False
    
    logger.info(f"[telegram] Callback from {chat_id}: {data}")
    
    if data.startswith("pause_alert_"):
        alert_id = int(data.replace("pause_alert_", ""))
        return cmd_pause_alert(chat_id, alert_id, bot)
    
    elif data.startswith("resume_alert_"):
        alert_id = int(data.replace("resume_alert_", ""))
        return cmd_resume_alert(chat_id, alert_id, bot)
    
    elif data.startswith("delete_alert_"):
        alert_id = int(data.replace("delete_alert_", ""))
        return cmd_delete_alert(chat_id, alert_id, bot)
    
    return False


def extract_alert_id(text: str) -> Optional[int]:
    """Extrahiert Alert-ID aus Command-Text"""
    parts = text.split()
    if len(parts) >= 2:
        try:
            return int(parts[1])
        except ValueError:
            pass
    return None


def get_user_email_from_chat_id(chat_id: str) -> Optional[str]:
    """Findet Email für eine Chat-ID in der Datenbank"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            f"SELECT email FROM users WHERE telegram_chat_id = {PH}",
            (chat_id,)
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return row[0]
    except Exception as e:
        logger.error(f"get_user_email_from_chat_id error: {e}")
    return None


def cmd_list_alerts(chat_id: str, bot: TelegramBot) -> bool:
    """Listet alle Alerts des Users auf"""
    user_email = get_user_email_from_chat_id(chat_id)
    if not user_email:
        return bot.send_message(
            chat_id,
            "❌ Telegram-Account nicht mit Super-Agent verbunden.\n"
            "Bitte verbinde ihn in den Einstellungen! ⚙️"
        )
    
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute(
            f"""
            SELECT id, terms_json, filters_json, source, is_active
            FROM search_alerts
            WHERE user_email = {PH}
            ORDER BY id DESC
            """,
            (user_email,)
        )
        rows = cur.fetchall()
        conn.close()
        
        if not rows:
            message = format_alert_list([])
        else:
            import json
            alerts = []
            for row in rows:
                alert_id, terms_json, _, source, is_active = row
                terms = json.loads(terms_json or "[]")
                alerts.append({
                    "id": alert_id,
                    "terms": terms,
                    "source": source or "ebay",
                    "is_active": bool(is_active)
                })
            message = format_alert_list(alerts)
        
        return bot.send_message(chat_id, message)
    
    except Exception as e:
        logger.error(f"cmd_list_alerts error: {e}")
        return bot.send_message(chat_id, f"❌ Fehler: {str(e)}")


def cmd_pause_alert(chat_id: str, alert_id: int, bot: TelegramBot) -> bool:
    """Pausiert einen Alert"""
    user_email = get_user_email_from_chat_id(chat_id)
    if not user_email:
        return bot.send_message(chat_id, "❌ Telegram-Account nicht verbunden!")
    
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute(
            f"SELECT is_active FROM search_alerts WHERE id = {PH} AND user_email = {PH}",
            (alert_id, user_email)
        )
        row = cur.fetchone()
        
        if not row:
            return bot.send_message(chat_id, f"❌ Alert #{alert_id} nicht gefunden!")
        
        cur.execute(
            f"UPDATE search_alerts SET is_active = 0 WHERE id = {PH}",
            (alert_id,)
        )
        conn.commit()
        conn.close()
        
        return bot.send_message(chat_id, f"⏸️ Alert #{alert_id} ist jetzt pausiert.")
    
    except Exception as e:
        logger.error(f"cmd_pause_alert error: {e}")
        return bot.send_message(chat_id, f"❌ Fehler: {str(e)}")


def cmd_resume_alert(chat_id: str, alert_id: int, bot: TelegramBot) -> bool:
    """Setzt einen Alert fort"""
    user_email = get_user_email_from_chat_id(chat_id)
    if not user_email:
        return bot.send_message(chat_id, "❌ Telegram-Account nicht verbunden!")
    
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute(
            f"SELECT is_active FROM search_alerts WHERE id = {PH} AND user_email = {PH}",
            (alert_id, user_email)
        )
        row = cur.fetchone()
        
        if not row:
            return bot.send_message(chat_id, f"❌ Alert #{alert_id} nicht gefunden!")
        
        cur.execute(
            f"UPDATE search_alerts SET is_active = 1 WHERE id = {PH}",
            (alert_id,)
        )
        conn.commit()
        conn.close()
        
        return bot.send_message(chat_id, f"✅ Alert #{alert_id} läuft wieder!")
    
    except Exception as e:
        logger.error(f"cmd_resume_alert error: {e}")
        return bot.send_message(chat_id, f"❌ Fehler: {str(e)}")


def cmd_delete_alert(chat_id: str, alert_id: int, bot: TelegramBot) -> bool:
    """Löscht einen Alert"""
    user_email = get_user_email_from_chat_id(chat_id)
    if not user_email:
        return bot.send_message(chat_id, "❌ Telegram-Account nicht verbunden!")
    
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute(
            f"SELECT id FROM search_alerts WHERE id = {PH} AND user_email = {PH}",
            (alert_id, user_email)
        )
        row = cur.fetchone()
        
        if not row:
            return bot.send_message(chat_id, f"❌ Alert #{alert_id} nicht gefunden!")
        
        cur.execute(
            f"UPDATE search_alerts SET is_active = 0 WHERE id = {PH}",
            (alert_id,)
        )
        conn.commit()
        conn.close()
        
        return bot.send_message(chat_id, f"🗑️ Alert #{alert_id} wurde gelöscht.")
    
    except Exception as e:
        logger.error(f"cmd_delete_alert error: {e}")
        return bot.send_message(chat_id, f"❌ Fehler: {str(e)}")


def send_new_item_alert(
    chat_id: str,
    item: Dict[str, Any],
    agent_name: str = "eBay Alert",
    alert_id: Optional[int] = None,
    with_image: bool = True,
) -> bool:
    """
    Sendet einen formatierten Alert für ein neues eBay Item
    """
    bot = TelegramBot()

    if not bot.is_configured():
        logger.error("send_new_item_alert: Telegram Bot nicht konfiguriert")
        return False

    message = format_ebay_alert(item, agent_name)
    buttons = create_item_buttons(item.get("url", ""), alert_id)

    if with_image and item.get("image_url"):
        return bot.send_photo(
            chat_id=chat_id,
            photo_url=item["image_url"],
            caption=message,
            reply_markup=buttons,
        )
    else:
        return bot.send_message(chat_id=chat_id, text=message, reply_markup=buttons)


def send_welcome_notification(chat_id: str, user_name: str = "User") -> bool:
    """Sendet Willkommensnachricht"""
    bot = TelegramBot()
    message = format_welcome_message(user_name)
    return bot.send_message(chat_id, message)


def verify_telegram_connection(chat_id: str) -> Optional[Dict]:
    """
    Verifiziert eine Telegram-Verbindung
    Gibt User-Info zurück wenn erfolgreich
    """
    bot = TelegramBot()
    return bot.get_chat_info(chat_id)


if __name__ == "__main__":
    bot = TelegramBot()

    if bot.is_configured():
        print("[OK] Telegram Bot ist konfiguriert!")
    else:
        print("[!] TELEGRAM_BOT_TOKEN fehlt in .env!")
