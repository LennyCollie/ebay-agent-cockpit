#!/usr/bin/env python3
import os
import socket
from datetime import datetime, timezone

from mailer import get_bounce_stats, send_mail

TO = [a.strip() for a in os.getenv("EMAIL_TO", "").split(",") if a.strip()]
if not TO:
    print("[HEARTBEAT] No EMAIL_TO configured - nothing to send.")
    exit(0)

print(f"[HEARTBEAT] Version 4.0 - Postmark API")
print(f"[HEARTBEAT] Sending to: {', '.join(TO)}")

host = socket.gethostname()
ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

subject = f"✅ Heartbeat OK - {host}"
stats = get_bounce_stats()
body = (
    f"Service: {os.getenv('RENDER_SERVICE_NAME','ebay-agent-heartbeat')}\n"
    f"Host:    {host}\n"
    f"Time:    {ts}\n"
    f"Bounces: {stats.get('total_bounced', 0)}\n"
    f"Status:  ✓ All systems operational\n"
)

success_count = 0
for addr in TO:
    print(f"[HEARTBEAT] Sending to {addr}...")
    if send_mail(addr, subject, body):
        print(f"[HEARTBEAT] ✓ Sent to {addr}")
        success_count += 1
    else:
        print(f"[HEARTBEAT] ✗ Failed for {addr}")

print(f"[HEARTBEAT] Complete - {success_count}/{len(TO)} emails sent via Postmark API")
