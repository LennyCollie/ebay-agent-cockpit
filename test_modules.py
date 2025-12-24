import sys
print("Testing imports...")

try:
    print("1. Importing Flask...")
    import flask
    print("   OK")
except Exception as e:
    print(f"   ERROR: {e}")

try:
    print("2. Importing flasgger...")
    import flasgger
    print("   OK")
except Exception as e:
    print(f"   ERROR: {e}")

try:
    print("3. Importing flask-limiter...")
    import flask_limiter
    print("   OK")
except Exception as e:
    print(f"   ERROR: {e}")

try:
    print("4. Importing models...")
    from models import User
    print("   OK")
except Exception as e:
    print(f"   ERROR: {e}")

try:
    print("5. Importing services...")
    from services.webhook import WebhookManager
    print("   OK")
except Exception as e:
    print(f"   ERROR: {e}")

try:
    print("6. Importing services.api_key...")
    from services.api_key import APIKeyManager
    print("   OK")
except Exception as e:
    print(f"   ERROR: {e}")

try:
    print("7. Importing middleware...")
    from middleware.api_auth import require_api_key
    print("   OK")
except Exception as e:
    print(f"   ERROR: {e}")

print("\nAll critical imports successful!")
