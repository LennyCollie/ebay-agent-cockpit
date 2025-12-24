import sys
import time

modules_to_test = [
    "models",
    "config",
    "routes.search",
    "routes.telegram",
    "routes.webhooks",
    "routes.api_keys",
    "services.webhook",
    "services.api_key",
    "middleware.api_auth",
    "flasgger",
]

for mod in modules_to_test:
    print(f"Testing {mod}...", end="", flush=True)
    start = time.time()
    try:
        __import__(mod)
        elapsed = time.time() - start
        print(f" OK ({elapsed:.2f}s)")
    except Exception as e:
        elapsed = time.time() - start
        print(f" ERROR ({elapsed:.2f}s): {e}")
        import traceback
        traceback.print_exc()
        break

print("\nDone!")
