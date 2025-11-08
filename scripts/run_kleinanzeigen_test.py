#!/usr/bin/env python3
"""
Simple script to call the scraper and print JSON results.
Usage:
  python scripts/run_kleinanzeigen_test.py "lego technic" 5
"""
import sys
import json
from services.kleinanzeigen import search_kleinanzeigen

def main():
    if len(sys.argv) < 2:
        print("Usage: run_kleinanzeigen_test.py <term> [max]")
        sys.exit(1)
    term = sys.argv[1]
    max_items = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    items = search_kleinanzeigen(term, per_page=max_items)
    print(json.dumps(items, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
