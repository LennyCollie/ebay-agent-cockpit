# mailer.py - Postmark API with Bounce Handling
import os
from datetime import datetime
from pathlib import Path

import requests

from utils.telegram_bot import notify_new_listing, send_telegram

# Bounce-Liste Datei
BOUNCE_FILE = Path("bounced_emails.txt")


def load_bounced_emails():
    """Load bounced email addresses from file"""
    try:
        if BOUNCE_FILE.exists():
            with open(BOUNCE_FILE, "r") as f:
                return set(line.strip().lower() for line in f if line.strip())
    except Exception as e:
        print(f"[BOUNCE] Error loading bounce file: {e}")
    return set()


def add_bounced_email(email):
    """Add email to bounce list"""
    try:
        email = email.lower().strip()
        bounced = load_bounced_emails()
        if email not in bounced:
            with open(BOUNCE_FILE, "a") as f:
                f.write(f"{email}\n")
            print(f"[BOUNCE] Added to blacklist: {email}")
    except Exception as e:
        print(f"[BOUNCE] Error adding email: {e}")


def is_email_bounced(email):
    """Check if email is in bounce list"""
    return email.lower().strip() in load_bounced_emails()


def send_mail(to_email, subject, text_body, html_body=None):
    """
    Send email via Postmark API with bounce handling
    Returns: True if sent successfully, False otherwise
    """
    # Input validation
    if not to_email or not to_email.strip():
        print("[ERROR] No recipient email provided")
        return False

    to_email = to_email.strip().lower()

    # Check bounce list first
    if is_email_bounced(to_email):
        print(f"[SKIP] Email {to_email} is in bounce list - not sending")
        return False

    # Get configuration
    api_key = os.getenv("POSTMARK_SERVER_TOKEN")
    from_email = os.getenv("SENDER_EMAIL", "alerts@alerts.lennycolli.com")

    if not api_key:
        print("[ERROR] POSTMARK_SERVER_TOKEN not configured")
        return False

    if not from_email:
        print("[ERROR] SENDER_EMAIL not configured")
        return False

    # Build payload
    payload = {
        "From": from_email,
        "To": to_email,
        "Subject": subject or "No Subject",
        "TextBody": text_body or "",
        "MessageStream": "outbound",
    }

    if html_body:
        payload["HtmlBody"] = html_body

    try:
        response = requests.post(
            "https://api.postmarkapp.com/email",
            headers={
                "X-Postmark-Server-Token": api_key,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )

        # Handle successful response
        if response.status_code == 200:
            print(f"[SUCCESS] Email sent to {to_email}")
            return True

        # Handle error responses
        error_data = {}
        try:
            error_data = response.json()
        except:
            pass

        error_code = error_data.get("ErrorCode", 0)
        error_message = error_data.get("Message", "Unknown error")

        print(f"[ERROR] Postmark API error {response.status_code}: {error_message}")

        # Handle specific bounce/invalid email errors
        bounce_error_codes = [
            300,  # Email address suppressed due to hard bounce
            406,  # Email address is invalid
            409,  # Sender signature not confirmed
            422,  # Invalid email address format
        ]

        if error_code in bounce_error_codes or response.status_code == 422:
            print(
                f"[BOUNCE] Adding {to_email} to bounce list due to error {error_code}"
            )
            add_bounced_email(to_email)

        return False

    except requests.exceptions.Timeout:
        print(f"[ERROR] Timeout sending email to {to_email}")
        return False
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Network error sending email: {e}")
        return False
    except Exception as e:
        print(f"[ERROR] Unexpected error sending email: {e}")
        return False


def send_mail_simple(to_addr, subject, body):
    """Backwards compatibility wrapper"""
    return send_mail(to_addr, subject, body)


def get_bounce_stats():
    """Get bounce statistics for monitoring"""
    bounced = load_bounced_emails()
    return {
        "total_bounced": len(bounced),
        "bounced_emails": list(bounced),
        "bounce_file_exists": BOUNCE_FILE.exists(),
    }


def clear_bounce_list():
    """Clear all bounced emails (admin function)"""
    try:
        if BOUNCE_FILE.exists():
            BOUNCE_FILE.unlink()
        print("[BOUNCE] Bounce list cleared")
        return True
    except Exception as e:
        print(f"[BOUNCE] Error clearing bounce list: {e}")
        return False


def test_email_system():
    """Test function for debugging"""
    print("=== Email System Test ===")
    print(
        f"POSTMARK_SERVER_TOKEN: {'Set' if os.getenv('POSTMARK_SERVER_TOKEN') else 'Missing'}"
    )
    print(f"SENDER_EMAIL: {os.getenv('SENDER_EMAIL', 'Not set')}")

    stats = get_bounce_stats()
    print(f"Bounce list: {stats['total_bounced']} emails")

    return stats

    # ... E-Mail erfolgreich gesendet ...


try:
    agent_info = {
        "name": agent_name
    }  # oder agent.title / agent["name"], je nachdem wie du’s nennst
    item_info = {
        "title": item_title,  # z. B. listing["title"]
        "price": item_price_str,  # z. B. "199 €"
        "url": item_url,  # Direktlink zum eBay-Angebot
        "condition": item_condition,  # z. B. "Gebraucht"
    }
    notify_new_listing(agent_info, item_info)
except Exception as e:
    print("[TELEGRAM] skip:", e)


if __name__ == "__main__":
    test_email_system()
