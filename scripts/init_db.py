#!/usr/bin/env python3
# scripts/init_db.py
# Sicherstellen, dass das Projekt-Root im sys.path ist, damit `from models import ...` funktioniert
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))

# Wenn PROJECT_ROOT noch nicht im sys.path ist, ganz nach vorne einfügen
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Jetzt sicher importieren
try:
    from models import init_db
except Exception as e:
    import traceback, sys as _sys
    print("ERROR: konnte models nicht importieren:", file=_sys.stderr)
    traceback.print_exc()
    raise

def main():
    init_db()

if __name__ == "__main__":
    main()
