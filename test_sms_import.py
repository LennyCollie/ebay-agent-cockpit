import sys

print("Testing SMS imports...")

try:
    print("1. Importing models...")
    from models import SMSNotificationSetting, SMSSendLog
    print("   OK SMS models")
except Exception as e:
    print(f"   ERROR: {e}")
    sys.exit(1)

try:
    print("2. Importing Twilio...")
    import twilio
    print("   OK Twilio")
except Exception as e:
    print(f"   ERROR: {e}")
    sys.exit(1)

try:
    print("3. Importing phonenumbers...")
    import phonenumbers
    print("   OK phonenumbers")
except Exception as e:
    print(f"   ERROR: {e}")
    sys.exit(1)

try:
    print("4. Importing SMS service...")
    from services.sms import SMSManager
    print("   OK SMS service")
except Exception as e:
    print(f"   ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

try:
    print("5. Importing SMS routes...")
    from routes.sms_notifications import sms_bp
    print("   OK SMS routes")
except Exception as e:
    print(f"   ERROR: {e}")
    sys.exit(1)

try:
    print("6. Testing app import...")
    from app import app
    print("   OK App")
except Exception as e:
    print(f"   ERROR: {e}")
    sys.exit(1)

print("\nAll SMS imports successful!")
