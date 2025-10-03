#!/usr/bin/env python3
import os

print(f"[HEARTBEAT] Starting - Version 2.0")
print(f"[HEARTBEAT] EMAIL_TO: {os.getenv('EMAIL_TO', 'not set')}")
print(f"[HEARTBEAT] This is a test heartbeat without any email sending")
print("[HEARTBEAT] Success - no SMTP used!")
