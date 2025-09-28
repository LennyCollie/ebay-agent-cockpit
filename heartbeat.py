# heartbeat.py
import datetime as dt
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage


def env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return v if v is not None and v != "" else default


SMTP_HOST = env("SMTP_HOST")
SMTP_PORT = int(env("SMTP_PORT", "587"))
SMTP_USER = env("SMTP_USER")
SMTP_PASSWORD = env("SMTP_PASSWORD")
FROM_EMAIL = env("FROM_EMAIL") or SMTP_USER
TO_EMAILS = [e.strip() for e in env("EMAIL_TO", FROM_EMAIL).split(",") if e.strip()]


def send_email(subject: str, body: str) -> None:
    """Sendet eine UTF-8-kodierte E-Mail via SMTP, unterstützt 587 (STARTTLS) und 465 (SSL)."""
    if not (
        SMTP_HOST
        and SMTP_PORT
        and SMTP_USER
        and SMTP_PASSWORD
        and FROM_EMAIL
        and TO_EMAILS
    ):
        raise RuntimeError(
            "SMTP env vars fehlen (HOST/PORT/USER/PASSWORD/FROM_EMAIL/EMAIL_TO)."
        )

    msg = EmailMessage()
    msg["From"] = FROM_EMAIL
    msg["To"] = ", ".join(TO_EMAILS)
    msg["Subject"] = (
        subject  # EmailMessage kodiert selbst RFC-konform (UTF-8 / QP/Base64)
    )
    msg.set_content(body)  # ebenfalls UTF-8

    ctx = ssl.create_default_context()

    if SMTP_PORT == 465:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx, timeout=25) as s:
            s.login(SMTP_USER, SMTP_PASSWORD)
            s.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=25) as s:
            s.ehlo()
            s.starttls(context=ctx)
            s.ehlo()
            s.login(SMTP_USER, SMTP_PASSWORD)
            s.send_message(msg)


def main() -> int:
    now_utc = dt.datetime.now(dt.timezone.utc)
    when = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")

    subject = "ebay-agent: Daily heartbeat ✓"  # ✓ & Umlaute ok
    body = (
        "Hallo,\n\n"
        "dies ist der tägliche Heartbeat vom Render-Cron.\n"
        f"Zeit (UTC): {when}\n"
        f"Host: {SMTP_HOST}\n"
        "\nViele Grüße\nHeartbeat\n"
    )

    print(
        f"[heartbeat] sending to {TO_EMAILS} via {SMTP_HOST}:{SMTP_PORT} as {FROM_EMAIL}"
    )
    try:
        send_email(subject, body)
        print("[heartbeat] sent ✓")
        return 0
    except Exception as e:
        print(f"[heartbeat] ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
