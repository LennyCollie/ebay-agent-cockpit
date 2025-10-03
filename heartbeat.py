# heartbeat.py – verschickt Healthcheck via Postmark (keine SMTP-Variablen mehr)
import os
import socket
from datetime import datetime, timezone

from mailer import get_bounce_stats, send_mail  # nutzt deinen Postmark-Mailer

TO = [a.strip() for a in os.getenv("EMAIL_TO", "").split(",") if a.strip()]
if not TO:
    print("[HEARTBEAT] No EMAIL_TO configured – nothing to send.")
    raise SystemExit(0)

host = socket.gethostname()
ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

subject = f"Heartbeat OK – {host}"
stats = get_bounce_stats()
body = (
    f"Service: {os.getenv('RENDER_SERVICE_NAME','local')}\n"
    f"Host:    {host}\n"
    f"Time:    {ts}\n"
    f"Bounces: {stats.get('total_bounced', 0)}\n"
)

all_ok = True
for addr in TO:
    ok = send_mail(addr, subject, body)
    all_ok = all_ok and ok

print(
    "[SUCCESS] Heartbeat emails sent."
    if all_ok
    else "[ERROR] At least one heartbeat email failed."
)
