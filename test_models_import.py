import sys
import time

print("Starting models import...", flush=True)
start = time.time()

try:
    import models
    elapsed = time.time() - start
    print(f"Models imported successfully in {elapsed:.2f}s")
except Exception as e:
    elapsed = time.time() - start
    print(f"Error importing models after {elapsed:.2f}s: {e}")
    import traceback
    traceback.print_exc()
