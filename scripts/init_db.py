#!/usr/bin/env python3
# Einfaches Init‑Script: nutzt models.init_db(), weil models.py engine/Base/init_db() bereits definiert.
from models import init_db

if __name__ == "__main__":
    init_db()
