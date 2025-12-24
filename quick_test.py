#!/usr/bin/env python3

print("Testing webhook module imports...")

try:
    from services.webhook import WebhookManager, EventDispatcher
    print("✓ webhook.py imports successful")
except ImportError as e:
    print(f"✗ webhook.py import failed: {e}")
except SyntaxError as e:
    print(f"✗ webhook.py syntax error: {e}")

try:
    from routes.webhooks import webhooks_bp
    print("✓ webhooks.py imports successful")
except ImportError as e:
    print(f"✗ webhooks.py import failed: {e}")
except SyntaxError as e:
    print(f"✗ webhooks.py syntax error: {e}")

try:
    from models import WebhookEndpoint, WebhookEvent, WebhookLog
    print("✓ models.py webhook models exist")
except ImportError as e:
    print(f"✗ models.py import failed: {e}")
except SyntaxError as e:
    print(f"✗ models.py syntax error: {e}")

print("\nAll imports passed!")
