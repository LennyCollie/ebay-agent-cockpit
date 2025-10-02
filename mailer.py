# mailer.py - Postmark API with Bounce Handling
import os
from datetime import datetime
from pathlib import Path

import requests

# Telegram bleibt erhalten (wird unten nur optional in einer Beispiel-Funktion verwendet)
from utils.telegram_bot import notify_new_listing, send_telegram

# Bounce-Liste Datei
BOUNCE_FILE = Path("bounced_emails.txt")


# ----------------------------- Helper für ENV -----------------------------
def _pm_token() -> str:
    """Unterstützt beide Varianten: POSTMARK_TOKEN oder POSTMARK_SERVER_TOKEN"""
    return os.getenv("POSTMARK_TOKEN") or os.getenv("POSTMARK_SERVER_TOKEN") or ""


def _from_email() -> str:
    """Unterstützt FROM_EMAIL oder SENDER_EMAIL"""
    return os.getenv("FROM_EMAIL") or os.getenv("SENDER_EMAIL") or ""


def _msg_stream() -> str:
    """Message-Stream, Standard 'outbound'"""
    return os.getenv("POSTMARK_MESSAGE_STREAM", "outbound")


def _default_to() -> str:
    """Fallback-Empfänger (für Tests/Heartbeat)"""
    return os.getenv("EMAIL_TO", "").strip()


# --------------------------- Bounce-Handling ------------------------------
def load_bounced_emails():
    """Load bounced email addresses from file"""
    try:
        if BOUNCE_FILE.exists():
            with open(BOUNCE_FILE, "r", encoding="utf-8") as f:
                return set(line.strip().lower() for line in f if line.strip())
    except Exception as e:
        print(f"[BOUNCE] Error loading bounce file: {e}")
    return set()


def add_bounced_email(email):
    """Add email to bounce list"""
    try:
        email = (email or "").lower().strip()
        if not email:
            return
        bounced = load_bounced_emails()
        if email not in bounced:
            with open(BOUNCE_FILE, "a", encoding="utf-8") as f:
                f.write(f"{email}\n")
            print(f"[BOUNCE] Added to blacklist: {email}")
    except Exception as e:
        print(f"[BOUNCE] Error adding email: {e}")


def is_email_bounced(email):
    """Check if email is in bounce list"""
    return (email or "").lower().strip() in load_bounced_emails()


# ------------------------------- Mailversand ------------------------------
def _normalize_recipients(to_email) -> list[str]:
    """
    Nimmt str (auch Komma-Liste) oder Liste entgegen und gibt eine Liste (lowercased) zurück.
    """
    if not to_email:
        to_email = _default_to()

    if isinstance(to_email, str):
        parts = [p.strip().lower() for p in to_email.split(",")]
    else:
        parts = [str(p).strip().lower() for p in to_email]

    return [p for p in parts if p]


def send_mail(to_email, subject, text_body, html_body=None):
    """
    Send email via Postmark API with bounce handling.
    to_email: str | list[str]  (Komma-Liste wird akzeptiert)
    Returns: True if sent successfully, False otherwise
    """
    # Empfänger normalisieren
    recipients = _normalize_recipients(to_email)
    if not recipients:
        print("[ERROR] No recipient email provided")
        return False

    # Bounces filtern
    bounced = load_bounced_emails()
    recipients_ok = [r for r in recipients if r not in bounced]
    if not recipients_ok:
        print(f"[SKIP] All recipients are in bounce list: {', '.join(recipients)}")
        return False

    # Konfiguration
    api_key = _pm_token()
    from_email = _from_email()
    stream = _msg_stream()

    if not api_key:
        print("[ERROR] POSTMARK_TOKEN/POSTMARK_SERVER_TOKEN not configured")
        return False
    if not from_email:
        print("[ERROR] FROM_EMAIL/SENDER_EMAIL not configured")
        return False

    # Payload
    payload = {
        "From": from_email,
        "To": ",".join(recipients_ok),
        "Subject": subject or "No Subject",
        "TextBody": text_body or "",
        "MessageStream": stream,
    }
    if html_body:
        payload["HtmlBody"] = html_body

    try:
        response = requests.post(
            "https://api.postmarkapp.com/email",
            headers={
                "X-Postmark-Server-Token": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=payload,
            timeout=30,
        )

        if response.status_code == 200:
            print(f"[SUCCESS] Email sent to {', '.join(recipients_ok)}")
            return True

        # Fehlerdetails lesen
        error_data = {}
        try:
            error_data = response.json()
        except Exception:
            pass

        error_code = int(error_data.get("ErrorCode", 0) or 0)
        error_message = error_data.get("Message", "Unknown error")
        print(f"[ERROR] Postmark API error {response.status_code}: {error_message}")

        # Codes, die auf Bounce / ungültige Adressen hindeuten
        bounce_error_codes = {
            300,  # address suppressed due to hard bounce
            406,  # email address is invalid
            409,  # sender signature not confirmed
            422,  # invalid email address format / Unprocessable Entity
        }

        if error_code in bounce_error_codes or response.status_code == 422:
            # Wir kennen nicht, welcher Empfänger schuld war → alle versuchen wir zu markieren.
            for r in recipients_ok:
                add_bounced_email(r)

        return False

    except requests.exceptions.Timeout:
        print(f"[ERROR] Timeout sending email to {', '.join(recipients_ok)}")
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


# ------------------------------- Admin/Stats ------------------------------
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
    """Testfunktion für Debugging — sendet nichts, zeigt nur ENV-Status"""
    print("=== Email System Test ===")
    print(
        f"POSTMARK_TOKEN/POSTMARK_SERVER_TOKEN: {'Set' if _pm_token() else 'Missing'}"
    )
    print(f"FROM_EMAIL/SENDER_EMAIL: {_from_email() or 'Not set'}")
    print(f"POSTMARK_MESSAGE_STREAM: {_msg_stream()}")
    print(f"EMAIL_TO (fallback): {_default_to() or 'Not set'}")

    stats = get_bounce_stats()
    print(f"Bounce list: {stats['total_bounced']} emails")
    return stats


# ---------- Beispiel-Funktion (optional), damit Telegram-Import bestehen bleibt ----------
def _example_notify_listing():
    """
    Nur Beispiel; wird NICHT automatisch ausgeführt.
    Zeigt, wie notify_new_listing aufgerufen wird, ohne Fehler beim Import zu erzeugen.
    """
    try:
        agent_info = {"name": "example-agent"}
        item_info = {
            "title": "Beispielartikel",
            "price": "199 €",
            "url": "https://example.com/item",
            "condition": "Gebraucht",
        }
        notify_new_listing(agent_info, item_info)
    except Exception as e:
        print("[TELEGRAM] skip:", e)


if __name__ == "__main__":
    # Nur Status ausgeben; kein Versand
    test_email_system()
    # _example_notify_listing()  # optional
