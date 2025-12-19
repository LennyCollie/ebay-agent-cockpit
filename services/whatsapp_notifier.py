"""
📱 WHATSAPP BENACHRICHTIGUNGEN
Integration via Twilio API (professionell & zuverlässig)
"""
import os
import logging
from typing import List, Dict, Optional
from datetime import datetime

log = logging.getLogger(__name__)


def send_whatsapp_alert(
    phone_number: str,
    items: List[Dict],
    query: str,
    max_items: int = 5
) -> Dict:
    """
    📱 Sendet WhatsApp-Benachrichtigung via Twilio

    Setup:
    1. Twilio Account erstellen: https://www.twilio.com/
    2. WhatsApp Sender beantragen (dauert ~24h)
    3. Environment Variables setzen:
       - TWILIO_ACCOUNT_SID
       - TWILIO_AUTH_TOKEN
       - TWILIO_WHATSAPP_NUMBER (Format: whatsapp:+14155238886)

    Args:
        phone_number: Empfänger (Format: +4917012345678)
        items: Neue Artikel
        query: Suchbegriff
        max_items: Max Anzahl in einer Nachricht

    Returns:
        Dict mit Status
    """
    try:
        from twilio.rest import Client

        # Twilio Credentials
        account_sid = os.getenv('TWILIO_ACCOUNT_SID')
        auth_token = os.getenv('TWILIO_AUTH_TOKEN')
        from_whatsapp = os.getenv('TWILIO_WHATSAPP_NUMBER', 'whatsapp:+14155238886')

        if not all([account_sid, auth_token]):
            return {
                'success': False,
                'error': 'Twilio credentials fehlen',
                'message': 'Bitte TWILIO_ACCOUNT_SID und TWILIO_AUTH_TOKEN setzen'
            }

        # Twilio Client
        client = Client(account_sid, auth_token)

        # Nachricht erstellen
        message_body = _format_whatsapp_message(items[:max_items], query)

        # WhatsApp senden
        to_whatsapp = f"whatsapp:{phone_number}"

        message = client.messages.create(
            body=message_body,
            from_=from_whatsapp,
            to=to_whatsapp
        )

        log.info(f"[OK] WhatsApp sent: {message.sid}")

        return {
            'success': True,
            'message_sid': message.sid,
            'items_sent': len(items[:max_items]),
            'phone': phone_number
        }

    except ImportError:
        return {
            'success': False,
            'error': 'Twilio nicht installiert',
            'message': 'pip install twilio'
        }

    except Exception as e:
        log.error(f"WhatsApp error: {e}")
        return {
            'success': False,
            'error': str(e)
        }


def _format_whatsapp_message(items: List[Dict], query: str) -> str:
    """Formatiert WhatsApp-Nachricht"""

    # Header
    message = f"🔔 *{len(items)} neue Schnäppchen für '{query}'!*\n\n"

    # Items
    for i, item in enumerate(items, 1):
        source_emoji = {
            'ebay': '🏪',
            'kleinanzeigen': '[+]',
            'quoka': '📱',
            'shpock': '🛍️',
            'marktde': '🏪',
            'facebook': '👥'
        }.get(item.get('source', ''), '🔗')

        price_str = f"{item['price']:.2f}€" if item.get('price') else "Preis auf Anfrage"

        message += f"{source_emoji} *{item['title'][:45]}*\n"
        message += f"💰 {price_str}\n"

        if item.get('location'):
            message += f"📍 {item['location'][:30]}\n"

        message += f"🔗 {item['url']}\n\n"

    # Footer
    if len(items) > len(items[:5]):
        message += f"... und {len(items) - 5} weitere!\n\n"

    message += "⚡ _Powered by Super-Agent_"

    return message


# ===================================================================
# ALTERNATIVE: WHATSAPP BUSINESS API (Für große Volumes)
# ===================================================================

def send_whatsapp_business(
    phone_number: str,
    template_name: str,
    items: List[Dict],
    query: str
) -> Dict:
    """
    📱 WhatsApp Business API (für > 1000 Nachrichten/Tag)

    Nutzt offizielle WhatsApp Business API.
    Voraussetzungen:
    - Facebook Business Account
    - WhatsApp Business API Zugang
    - Genehmigte Message Templates

    Setup:
    1. https://business.facebook.com/
    2. WhatsApp Business API beantragen
    3. Message Templates erstellen & genehmigen lassen
    4. Credentials in .env setzen

    Args:
        phone_number: Empfänger
        template_name: Name des genehmigten Templates
        items: Artikel
        query: Suchbegriff

    Returns:
        Status Dict
    """
    try:
        import requests

        # WhatsApp Business API Credentials
        business_phone_id = os.getenv('WHATSAPP_BUSINESS_PHONE_ID')
        access_token = os.getenv('WHATSAPP_BUSINESS_TOKEN')

        if not all([business_phone_id, access_token]):
            return {
                'success': False,
                'error': 'WhatsApp Business credentials fehlen'
            }

        # API Endpoint
        url = f"https://graph.facebook.com/v17.0/{business_phone_id}/messages"

        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }

        # Template Message
        # WICHTIG: Templates müssen vorher bei Facebook genehmigt werden!
        data = {
            'messaging_product': 'whatsapp',
            'to': phone_number,
            'type': 'template',
            'template': {
                'name': template_name,  # z.B. 'new_items_alert'
                'language': {'code': 'de'},
                'components': [
                    {
                        'type': 'body',
                        'parameters': [
                            {'type': 'text', 'text': str(len(items))},
                            {'type': 'text', 'text': query}
                        ]
                    }
                ]
            }
        }

        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()

        result = response.json()

        log.info(f"[OK] WhatsApp Business sent: {result}")

        return {
            'success': True,
            'message_id': result.get('messages', [{}])[0].get('id'),
            'items_sent': len(items)
        }

    except Exception as e:
        log.error(f"WhatsApp Business error: {e}")
        return {
            'success': False,
            'error': str(e)
        }


# ===================================================================
# WHATSAPP WEB API (Unofficial - für kleine Projekte)
# ===================================================================

def send_whatsapp_web(
    phone_number: str,
    items: List[Dict],
    query: str
) -> Dict:
    """
    📱 WhatsApp Web Link (Unofficial)

    Öffnet WhatsApp Web mit vorgefertigter Nachricht.
    User muss nur noch auf "Senden" klicken.

    Vorteil:
    - Keine API Keys nötig
    - Kostenlos
    - Sofort einsetzbar

    Nachteil:
    - User muss manuell senden
    - Kein Automation möglich

    Args:
        phone_number: Empfänger (ohne +)
        items: Artikel
        query: Suchbegriff

    Returns:
        Dict mit WhatsApp-Link
    """
    import urllib.parse

    # Nachricht formatieren
    message = _format_whatsapp_message(items[:3], query)

    # URL-encode
    message_encoded = urllib.parse.quote(message)

    # WhatsApp Link
    phone_clean = phone_number.replace('+', '').replace(' ', '')
    whatsapp_link = f"https://wa.me/{phone_clean}?text={message_encoded}"

    return {
        'success': True,
        'method': 'web_link',
        'link': whatsapp_link,
        'message': 'Link öffnen und auf Senden klicken'
    }


# ===================================================================
# NOTIFICATION MANAGER (Multi-Channel)
# ===================================================================

def send_notification(
    user: Dict,
    items: List[Dict],
    query: str,
    channels: Optional[List[str]] = None
) -> Dict:
    """
    📢 Multi-Channel Notification Manager

    Sendet Benachrichtigungen über mehrere Kanäle:
    - Telegram (deine bestehende Integration)
    - WhatsApp (Twilio)
    - Email (optional)
    - Push (optional)

    Args:
        user: User-Dict mit Preferences
        items: Neue Artikel
        query: Suchbegriff
        channels: Liste von Kanälen ['telegram', 'whatsapp', 'email']

    Returns:
        Dict mit Status pro Kanal
    """
    results = {}

    # Default: Alle aktivierten Kanäle
    if channels is None:
        channels = []
        if user.get('telegram_enabled'):
            channels.append('telegram')
        if user.get('whatsapp_enabled'):
            channels.append('whatsapp')
        if user.get('email_enabled'):
            channels.append('email')

    # Telegram
    if 'telegram' in channels and user.get('telegram_chat_id'):
        try:
            from services.telegram_bot import send_telegram_message
            message = _format_telegram_message(items[:5], query)
            send_telegram_message(user['telegram_chat_id'], message)
            results['telegram'] = {'success': True}
        except Exception as e:
            results['telegram'] = {'success': False, 'error': str(e)}

    # WhatsApp
    if 'whatsapp' in channels and user.get('phone_number'):
        result = send_whatsapp_alert(
            user['phone_number'],
            items,
            query
        )
        results['whatsapp'] = result

    # Email
    if 'email' in channels and user.get('email'):
        result = send_email_alert(
            user['email'],
            items,
            query
        )
        results['email'] = result

    return {
        'sent_to': list(results.keys()),
        'results': results,
        'total_items': len(items)
    }


def _format_telegram_message(items: List[Dict], query: str) -> str:
    """Formatiert Telegram-Nachricht"""
    message = f"🔔 {len(items)} neue Artikel für '{query}'!\n\n"

    for item in items:
        source_emoji = {
            'ebay': '🏪', 'kleinanzeigen': '[+]', 'quoka': '📱',
            'shpock': '🛍️', 'marktde': '🏪', 'facebook': '👥'
        }.get(item.get('source', ''), '🔗')

        price = f"{item['price']:.2f}€" if item.get('price') else "Preis auf Anfrage"

        message += f"{source_emoji} {item['title'][:50]}\n"
        message += f"💰 {price}\n"
        message += f"🔗 {item['url']}\n\n"

    return message


def send_email_alert(email: str, items: List[Dict], query: str) -> Dict:
    """
    📧 Email-Benachrichtigung

    Nutzt SMTP oder SendGrid
    """
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        # SMTP Config
        smtp_host = os.getenv('SMTP_HOST', 'smtp.gmail.com')
        smtp_port = int(os.getenv('SMTP_PORT', '587'))
        smtp_user = os.getenv('SMTP_USER')
        smtp_pass = os.getenv('SMTP_PASSWORD')

        if not all([smtp_user, smtp_pass]):
            return {'success': False, 'error': 'SMTP credentials fehlen'}

        # Email erstellen
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"🔔 {len(items)} neue Schnäppchen für '{query}'"
        msg['From'] = smtp_user
        msg['To'] = email

        # HTML Body
        html = _format_email_html(items[:10], query)
        msg.attach(MIMEText(html, 'html'))

        # Senden
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)

        return {'success': True, 'items_sent': len(items[:10])}

    except Exception as e:
        log.error(f"Email error: {e}")
        return {'success': False, 'error': str(e)}


def _format_email_html(items: List[Dict], query: str) -> str:
    """Formatiert HTML-Email"""
    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif;">
        <h2>🔔 {len(items)} neue Schnäppchen für '{query}'!</h2>
        <div style="margin: 20px 0;">
    """

    for item in items:
        price = f"{item['price']:.2f}€" if item.get('price') else "Preis auf Anfrage"

        html += f"""
        <div style="border: 1px solid #ddd; padding: 15px; margin: 10px 0; border-radius: 8px;">
            <h3 style="margin: 0 0 10px 0;">{item['title']}</h3>
            <p style="margin: 5px 0;"><strong>💰 {price}</strong></p>
            <p style="margin: 5px 0;">[+] {item.get('source', 'unknown')}</p>
            <a href="{item['url']}" style="color: #667eea; text-decoration: none;">
                🔗 Zum Angebot ->
            </a>
        </div>
        """

    html += """
        </div>
        <p style="color: #666; font-size: 12px;">
            ⚡ Powered by Super-Agent
        </p>
    </body>
    </html>
    """

    return html


# ===================================================================
# TEST
# ===================================================================

def test_whatsapp():
    """Test WhatsApp-Integration"""
    print("\n" + "="*70)
    print("📱 WHATSAPP INTEGRATION TEST")
    print("="*70 + "\n")

    # Mock Items
    items = [
        {
            'title': 'iPhone 13 Pro 128GB',
            'price': 450.0,
            'source': 'kleinanzeigen',
            'location': 'Köln',
            'url': 'https://kleinanzeigen.de/test123'
        },
        {
            'title': 'iPhone 13 64GB Blau',
            'price': 380.0,
            'source': 'quoka',
            'location': 'Düsseldorf',
            'url': 'https://quoka.de/test456'
        }
    ]

    print("Mock-Items erstellt:")
    for item in items:
        print(f"  • {item['title']} - {item['price']}€")

    print("\n1️⃣  Testing WhatsApp Web Link...")
    result = send_whatsapp_web('+4917012345678', items, 'iPhone 13')
    if result['success']:
        print(f"   [OK] Link erstellt: {result['link'][:80]}...")

    print("\n2️⃣  Testing Twilio WhatsApp...")
    if os.getenv('TWILIO_ACCOUNT_SID'):
        result = send_whatsapp_alert('+4917012345678', items, 'iPhone 13')
        print(f"   {'[OK]' if result['success'] else '[!]'} {result}")
    else:
        print("   [!]  Twilio credentials nicht gesetzt")
        print("   Setup: https://www.twilio.com/")

    print("\n3️⃣  Message Preview:")
    message = _format_whatsapp_message(items, 'iPhone 13')
    print("   " + "-"*50)
    for line in message.split('\n'):
        print(f"   {line}")
    print("   " + "-"*50)

    print("\n" + "="*70 + "\n")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_whatsapp()
