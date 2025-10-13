# telegram_bot.py
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


class TelegramBot:
    """Telegram Bot Handler für eBay Alerts"""

    def __init__(self, token: Optional[str] = None):
        self.token = token or TELEGRAM_BOT_TOKEN
        self.api_url = f"https://api.telegram.org/bot{self.token}"

        if not self.token:
            logger.warning("⚠️ TELEGRAM_BOT_TOKEN nicht gesetzt!")

    def is_configured(self) -> bool:
        """Prüft ob Bot konfiguriert ist"""
        return bool(self.token and len(self.token) > 10)

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

        Args:
            chat_id: Telegram Chat ID
            text: Nachrichtentext (unterstützt HTML)
            parse_mode: "HTML" oder "Markdown"
            disable_web_page_preview: Keine Link-Vorschau
            reply_markup: Inline Keyboard Buttons
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
                logger.info(f"✅ Telegram Nachricht gesendet an {chat_id}")
                return True
            else:
                logger.error(f"❌ Telegram API Error: {response.text}")
                return False

        except Exception as e:
            logger.error(f"❌ Fehler beim Senden: {e}")
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

            return response.status_code == 200

        except Exception as e:
            logger.error(f"❌ Fehler beim Senden des Bildes: {e}")
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
            return None

        except Exception as e:
            logger.error(f"❌ Fehler beim Abrufen der Chat-Info: {e}")
            return None


# Template Functions für verschiedene Nachrichtentypen


def format_ebay_alert(item: Dict[str, Any], agent_name: str = "eBay Alert") -> str:
    """
    Formatiert eine schöne Telegram-Nachricht für ein neues eBay Item

    Args:
        item: Dict mit eBay Item Daten (title, price, url, etc.)
        agent_name: Name des Such-Agenten
    """
    title = item.get("title", "Unbekannt")
    price = item.get("price", "N/A")
    currency = item.get("currency", "EUR")
    url = item.get("url", "")
    condition = item.get("condition", "")
    location = item.get("location", "")

    # Emoji basierend auf Preis
    emoji = "🔥" if "Angebot" in title.lower() else "📦"

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


def create_item_buttons(item_url: str) -> Dict:
    """Erstellt Inline-Buttons für ein Item"""
    return {
        "inline_keyboard": [
            [{"text": "🛒 Zu eBay", "url": item_url}],
            [
                {"text": "🔕 Stumm für 1h", "callback_data": "mute_1h"},
                {"text": "⏸️ Agent pausieren", "callback_data": "pause_agent"},
            ],
        ]
    }


def format_welcome_message(user_name: str = "User") -> str:
    """Willkommensnachricht bei Verknüpfung"""
    return f"""
👋 <b>Willkommen bei eBay Super-Agent, {user_name}!</b>

Dein Telegram wurde erfolgreich verknüpft! 🎉

Ab sofort erhältst du <b>Echtzeit-Benachrichtigungen</b>, sobald neue Artikel gefunden werden, die zu deinen Such-Agenten passen.

<b>Vorteile:</b>
⚡ Sofortige Push-Notifications
📱 Direkt auf dein Handy
🔗 Klick direkt zum eBay-Angebot
🔕 Flexible Einstellungen

Du kannst Telegram-Alerts jederzeit in deinen Einstellungen aktivieren/deaktivieren.

Viel Erfolg beim Schnäppchen-Jagen! 🎯
"""


def format_daily_summary(
    agent_count: int, new_items: int, saved_money: float = 0
) -> str:
    """Tägliche Zusammenfassung"""
    return f"""
📊 <b>Deine tägliche Zusammenfassung</b>

<b>🔍 Aktive Agenten:</b> {agent_count}
<b>🆕 Neue Artikel heute:</b> {new_items}
<b>💰 Gespartes Geld:</b> ~{saved_money:.2f} €

Weiter so! 🚀
"""


# Convenience Functions


def send_new_item_alert(
    chat_id: str,
    item: Dict[str, Any],
    agent_name: str = "eBay Alert",
    with_image: bool = True,
) -> bool:
    """
    Sendet einen formatierten Alert für ein neues eBay Item

    Args:
        chat_id: Telegram Chat ID des Users
        item: Dict mit Item-Daten
        agent_name: Name des Such-Agenten
        with_image: Soll Produktbild mitgesendet werden?
    """
    bot = TelegramBot()

    if not bot.is_configured():
        return False

    message = format_ebay_alert(item, agent_name)
    buttons = create_item_buttons(item.get("url", ""))

    # Mit Bild, wenn vorhanden
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


# Webhook Handler (falls du später Webhooks nutzen willst)
def handle_telegram_update(update: Dict[str, Any]):
    """
    Verarbeitet Telegram Updates (z.B. Button-Klicks)

    Args:
        update: Telegram Update Object
    """
    # Beispiel: Callback Query (Button Click)
    if "callback_query" in update:
        callback = update["callback_query"]
        data = callback.get("data")
        chat_id = callback["message"]["chat"]["id"]

        if data == "mute_1h":
            # TODO: Agent für 1h stumm schalten
            bot = TelegramBot()
            bot.send_message(chat_id, "🔕 Agent für 1 Stunde stummgeschaltet.")

        elif data == "pause_agent":
            # TODO: Agent pausieren
            bot = TelegramBot()
            bot.send_message(chat_id, "⏸️ Agent pausiert.")


if __name__ == "__main__":
    # Test
    bot = TelegramBot()

    if bot.is_configured():
        print("✅ Telegram Bot ist konfiguriert!")

        # Test-Item
        test_item = {
            "title": "iPhone 15 Pro Max 256GB Neu OVP",
            "price": "999",
            "currency": "EUR",
            "url": "https://ebay.de/itm/123456",
            "image_url": "https://i.ebayimg.com/images/g/test.jpg",
            "condition": "Neu",
            "location": "Berlin",
        }

        # Test-Nachricht (ersetze DEINE_CHAT_ID)
        # send_new_item_alert("DEINE_CHAT_ID", test_item, "Test Agent")
    else:
        print("❌ TELEGRAM_BOT_TOKEN fehlt in .env!")
