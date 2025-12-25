#!/usr/bin/env python
import sys
try:
    from app import app
    print("[OK] App initialization successful")
    print(f"[OK] Flask app object: {app}")
    sys.exit(0)
except Exception as e:
    print(f"[ERR] App initialization failed: {str(e)}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
