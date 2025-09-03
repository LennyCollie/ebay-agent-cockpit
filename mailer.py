# mailer.py
import os, smtplib
from email.message import EmailMessage

def _env(*keys, default=None):
    for k in keys:
        v = os.getenv(k)
        if v not in (None, ""):
            return v
    return default

SMTP_HOST = _env("SMTP_HOST", default="smtp.gmail.com")
SMTP_PORT = int(_env("SMTP_PORT", default="587"))
SMTP_USE_TLS = _env("SMTP_USE_TLS", default="1") in ("1","true","True")
SMTP_USE_SSL = _env("SMTP_USE_SSL", default="0") in ("1","true","True")

SMTP_USERNAME = _env("SMTP_USERNAME", "SMTP_USER")
SMTP_PASSWORD = _env("SMTP_PASSWORD", "SMTP_PASS")

SENDER_EMAIL = _env("SENDER_EMAIL", "SMTP_FROM", default=SMTP_USERNAME)
SENDER_NAME  = _env("SENDER_NAME", default="Ebay Agent")

MAIL_TIMEOUT_SECONDS = int(_env("MAIL_TIMEOUT_SECONDS", default="30"))

def send_mail(to_addr: str, subject: str, body: str):
    if not all([SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SENDER_EMAIL]):
        raise RuntimeError("SMTP-ENV unvollständig (Host/Port/User/Pass/Sender)")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{SENDER_NAME} <{SENDER_EMAIL}>"
    msg["To"] = to_addr
    msg["Reply-To"] = SENDER_EMAIL
    msg.set_content(body)

    if SMTP_USE_SSL:
        import ssl
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=MAIL_TIMEOUT_SECONDS, context=ctx) as s:
            s.login(SMTP_USERNAME, SMTP_PASSWORD)
            s.send_message(msg)
        return

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=MAIL_TIMEOUT_SECONDS) as s:
        s.ehlo()
        if SMTP_USE_TLS:
            s.starttls()
            s.ehlo()
        s.login(SMTP_USERNAME, SMTP_PASSWORD)
        s.send_message(msg)