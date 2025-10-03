#!/usr/bin/env python3
import os
from datetime import datetime, timezone

print(f"[HEARTBEAT] Starting - Version 3.0")
print(f"[HEARTBEAT] EMAIL_TO: {os.getenv('EMAIL_TO', 'not set')}")
print(f"[HEARTBEAT] This is a test heartbeat without any email sending")
print("[HEARTBEAT] Success - no SMTP used!")

# Test ob mailer Import funktioniert
try:
    from mailer import get_bounce_stats, send_mail

    print("[HEARTBEAT] Mailer import successful")
except Exception as e:
    print(f"[HEARTBEAT] Mailer import failed: {e}")
    exit(1)

print("[HEARTBEAT] Success - ready for Postmark API")
