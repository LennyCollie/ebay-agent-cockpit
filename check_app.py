import time
import requests

time.sleep(2)

try:
    response = requests.get("http://localhost:5000", timeout=5)
    print(f"✓ App is running! Status: {response.status_code}")
except Exception as e:
    print(f"✗ App not responding: {e}")
