#!/usr/bin/env python3
import sys
from models import init_db, Base, engine

try:
    print("Initializing database tables...")
    Base.metadata.create_all(bind=engine)
    print("[OK] Database tables created successfully!")
    sys.exit(0)
except Exception as e:
    print(f"[ERROR] Failed to initialize database: {e}")
    sys.exit(1)
