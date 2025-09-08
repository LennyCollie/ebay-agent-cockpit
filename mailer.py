# mailer.py
import os, smtplib
from email.message import EmailMessage
from email.utils import formataddr

def _env(*keys, default=None):
    for k in keys:
        v = os.getenv(k)
        if v not in (None, ""):
            return v
    return default


SMTP_PORT = int(_env("SMTP_PORT", default="587"))
SMTP_USE_TLS = _env("SMTP_USE_TLS", default="1") in ("1","true","True")
SMTP_USE_SSL = _env("SMTP_USE_SSL", default="0") in ("1","true","True")

SMTP_USERNAME = _env("SMTP_USERNAME", "SMTP_USER")
SMTP_PASSWORD = _env("SMTP_PASSWORD", "SMTP_PASS")

SENDER_EMAIL = _env("SENDER_EMAIL", "SMTP_FROM", default=SMTP_USERNAME)
SENDER_NAME  = _env("SENDER_NAME", default="Ebay Agent")

MAIL_TIMEOUT_SECONDS = int(_env("MAIL_TIMEOUT_SECONDS", default="30"))

# ---- Konfiguration je nach Modus holen

MAIL_TIMEOUT_SECONDS = int(os.getenv("MAIL_TIMEOUT_SECONDS", "30"))

# ---- Konfiguration je nach Modus holen
def _mail_cfg(use_pilot: bool):
    prefix = "PILOT_" if use_pilot else ""
    host  = os.getenv(f"{prefix}SMTP_HOST", "smtp.postmarkapp.com")
    port  = int(os.getenv(f"{prefix}SMTP_PORT", "587"))
    user  = os.getenv(f"{prefix}SMTP_USERNAME")         # = Server API Token bei Postmark
    pwd   = os.getenv(f"{prefix}SMTP_PASSWORD")         # = derselbe Token
    use_tls = os.getenv(f"{prefix}SMTP_USE_TLS", "1") in ("1", "true", "True")
    sender = os.getenv(f"{prefix}SENDER_EMAIL") or os.getenv("SENDER_EMAIL")
    sender_name = os.getenv("SENDER_NAME") or os.getenv("SITE_NAME", "App")
    # Stream: erst prefix-spezifisch, sonst global (falls du auch fürs eBay-Stream einen setzen willst)
    stream = os.getenv(f"{prefix}MESSAGE_STREAM") or os.getenv("MESSAGE_STREAM")
    return host, port, user, pwd, use_tls, sender, sender_name, stream

def send_mail(
    to,
    subject,
    text,
    html=None,
    *,
    use_pilot: bool = False,
    stream: str | None = None,
    sender_email: str | None = None,
    sender_name: str | None = None,
    reply_to: str | None = None,
):
    """
    - use_pilot=True  -> nutzt PILOT_* ENV + setzt X-PM-Message-Stream
    - stream=None     -> nimmt ggf. (PILOT_)MESSAGE_STREAM aus ENV
    """
    (host, port, user, pwd, use_tls,
     default_sender, default_sender_name, default_stream) = _mail_cfg(use_pilot)

    sender_email = sender_email or default_sender
    sender_name  = sender_name  or default_sender_name
    stream       = stream or default_stream

    if not sender_email:
        raise RuntimeError("Keine Absenderadresse (SENDER_EMAIL / PILOT_SENDER_EMAIL) konfiguriert.")

    msg = EmailMessage()
    msg["From"] = formataddr((sender_name, sender_email))
    msg["To"] = to if isinstance(to, str) else ", ".join(to)
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to
    if stream:
        msg["X-PM-Message-Stream"] = stream

    if html:
        msg.set_content(text or "")
        msg.add_alternative(html, subtype="html")
    else:
        msg.set_content(text or "")

    with smtplib.SMTP(host, port, timeout=MAIL_TIMEOUT_SECONDS) as s:
        if use_tls:
            s.starttls()
        if user and pwd:
            s.login(user, pwd)
        s.send_message(msg)

# Bequemer Wrapper für den Pilot

def send_mail_simple(to_addr: str, subject: str, body: str):
    """Backwards-compat wrapper that uses the new Postmark-based sender."""
    return send_mail(to=to_addr, subject=subject, text=body)