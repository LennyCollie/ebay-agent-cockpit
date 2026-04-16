import imaplib
import email
from email.header import decode_header
import re
import logging
import os
import json
import sys

# Pfad zum Hauptverzeichnis hinzufügen, um database importieren zu können
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_db, dict_cursor, get_placeholder
from mailer import send_mail

log = logging.getLogger(__name__)

# ==== Mail-Konfiguration ====
# WICHTIG: Diese Werte müssen in der .env oder hier gesetzt werden!
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com")
EMAIL_USER = os.getenv("IMAP_USER", "USER@YOURDOMAIN.TLD")
EMAIL_PASS = os.getenv("IMAP_PASS", "PASSWORD")
MAILBOX = "INBOX"

SUBJECT_KEYWORDS_MOBILE = ["mobile.de", "Suchauftrag", "Neues Inserat"]
SUBJECT_KEYWORDS_AUTOSCOUT = ["autoscout24", "Suchauftrag", "Neues Inserat"]
LINK_REGEX = re.compile(r'https?://[\w\-./?=&%#]+')

def get_relevant_alerts(conn, channel_flag, search_body):
    # channel_flag: 'notify_mobilede' oder 'notify_autoscout'
    cur = dict_cursor(conn)
    PH = get_placeholder()
    
    # Sicherstellen, dass channel_flag valide ist (SQL Injection Schutz)
    if channel_flag not in ['notify_mobilede', 'notify_autoscout']:
        return []

    cur.execute(f"""
        SELECT id, user_email, terms_json
        FROM search_alerts
        WHERE is_active = 1 AND {channel_flag} = 1
    """)
    
    results = []
    rows = cur.fetchall()
    for row in rows:
        # row ist ein dict (wegen dict_cursor) oder ein tuple
        if isinstance(row, dict):
            alert_id = row['id']
            user_email = row['user_email']
            terms_json = row['terms_json']
        else:
            alert_id, user_email, terms_json = row
            
        terms = json.loads(terms_json or "[]")
        # Treffer, falls einer der Begriffe im Body enthalten ist
        if not terms or any(term.lower() in search_body.lower() for term in terms):
            results.append({'id': alert_id, 'user_email': user_email, 'terms': terms})
    return results

def fetch_new_alert_emails():
    if EMAIL_USER == "USER@YOURDOMAIN.TLD":
        log.warning("[EmailAlertImporter] IMAP-Zugangsdaten nicht konfiguriert.")
        return []

    log.info("[EmailAlertImporter] Checking mailbox for new alert emails...")
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_USER, EMAIL_PASS)
        mail.select(MAILBOX)
        status, messages = mail.search(None, '(UNSEEN)')
        if status != 'OK':
            log.error("[EmailAlertImporter] Failed to search mailbox.")
            return []
        
        new_alerts = []
        for num in messages[0].split():
            res, msg_data = mail.fetch(num, '(RFC822)')
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    subject, encoding = decode_header(msg["Subject"])[0]
                    if isinstance(subject, bytes):
                        subject = subject.decode(encoding if encoding else "utf-8")
                    mail_from = msg.get("From", "")
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                body = part.get_payload(decode=True).decode(errors="ignore")
                    else:
                        body = msg.get_payload(decode=True).decode(errors="ignore")
                    
                    if body:
                        links = LINK_REGEX.findall(body)
                        new_alerts.append({'subject': subject, 'from': mail_from, 'links': links, 'body': body})
        
        mail.logout()
        log.info(f"[EmailAlertImporter] Found {len(new_alerts)} new emails.")
        return new_alerts
    except Exception as e:
        log.error(f"[EmailAlertImporter] Fehler beim Mail-Abruf: {e}")
        return []

def process_alert_emails(alerts):
    if not alerts:
        log.info("Keine neuen Angebotsmails gefunden.")
        return
    
    conn = get_db()
    try:
        # Bearbeite Mobile.de Mails
        for alert in alerts:
            # Check Mobile.de
            if any(kw.lower() in alert['subject'].lower() for kw in SUBJECT_KEYWORDS_MOBILE):
                user_alerts = get_relevant_alerts(conn, 'notify_mobilede', alert['body'])
                for ua in user_alerts:
                    send_mail_to_user(ua['user_email'], f"Neues Mobile.de-Angebot: {alert['subject']}", alert['body'])
                    log.info(f"[EmailAlertImporter] Mobile.de-Benachrichtigung an {ua['user_email']} gesendet.")
            
            # Check AutoScout24
            if any(kw.lower() in alert['subject'].lower() for kw in SUBJECT_KEYWORDS_AUTOSCOUT):
                user_alerts = get_relevant_alerts(conn, 'notify_autoscout', alert['body'])
                for ua in user_alerts:
                    send_mail_to_user(ua['user_email'], f"Neues AutoScout24-Angebot: {alert['subject']}", alert['body'])
                    log.info(f"[EmailAlertImporter] AutoScout24-Benachrichtigung an {ua['user_email']} gesendet.")
    finally:
        conn.close()

def send_mail_to_user(to_email, subject, body):
    from agent import get_mail_settings, send_mail
    try:
        settings = get_mail_settings()
        send_mail(settings, [to_email], subject, body)
    except Exception as e:
        log.error(f"Fehler beim Senden der Benachrichtigungs-Mail an {to_email}: {e}")

def check_and_import_email_alerts():
    alerts = fetch_new_alert_emails()
    process_alert_emails(alerts)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    check_and_import_email_alerts()
