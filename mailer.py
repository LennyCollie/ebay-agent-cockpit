# mailer.py - Postmark API with Bounce Handling
import os
import requests
from datetime import datetime
from pathlib import Path

# Bounce-Liste Datei
BOUNCE_FILE = Path("bounced_emails.txt")

def load_bounced_emails():
    """Load bounced email addresses from file"""
    try:
        if BOUNCE_FILE.exists():
            with open(BOUNCE_FILE, 'r') as f:
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
            with open(BOUNCE_FILE, 'a') as f:
                f.write(f"{email}\n")
            print(f"[BOUNCE] Added to blacklist: {email}")
    except Excepti
