# mailer.py - Postmark API Version
import os
import requests
from datetime import datetime

def send_mail(to_email, subject, text_body, html_body=None):
    """Send email via Postmark API"""
    api_key = os.getenv('POSTMARK_SERVER_TOKEN')
    from_email = os.getenv('SENDER_EMAIL', 'noreply@ebay-agent.com')
    
    if not api_key:
        print("[ERROR] POSTMARK_SERVER_TOKEN not configured")
        return False
    
    payload = {
        'From': from_email,
        'To': to_email,
        'Subject': subject,
        'TextBody': text_body,
        'MessageStream': 'outbound'
    }
    
    if html_body:
        payload['HtmlBody'] = html_body
    
    try:
        response = requests.post(
            'https://api.postmarkapp.com/email',
            headers={
                'X-Postmark-Server-Token': api_key,
                'Content-Type': 'application/json'
            },
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            print(f"[SUCCESS] Email sent to {to_email}")
            return True
        else:
            print(f"[ERROR] Postmark API error: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        print(f"[ERROR] Email send failed: {e}")
        return False

# Backwards compatibility wrapper
def send_mail_simple(to_addr, subject, body):
    return send_mail(to_addr, subject, body)
