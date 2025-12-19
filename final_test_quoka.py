import sys
import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

print("\n" + "="*70)
print(" FINAL QUOKA FIX TEST - iPhone 12 Search")
print("="*70 + "\n")

from services.search_integration import merge_all_marketplaces
from services.quoka_scraper import search_quoka, _is_invalid_quoka_listing

print("[STEP 1] Testing Quoka Scraper...")
quoka_raw = search_quoka(query='Iphone 12', limit=50)
print(f"  Raw items from scraper: {len(quoka_raw)}")

if quoka_raw:
    print(f"  Sample titles:")
    for i, item in enumerate(quoka_raw[:3], 1):
        title = item.get('title', 'N/A')[:70]
        is_invalid = _is_invalid_quoka_listing(item)
        status = "[FILTERED]" if is_invalid else "[KEEP]"
        print(f"    {i}. {status} {title}")

print("\n[STEP 2] Testing Full Integration with merge_all_marketplaces...")
results = merge_all_marketplaces(
    term='Iphone 12',
    active_sources=['quoka'],
    max_per_source=20,
    verbose=False
)

print(f"  Final results: {len(results)} items\n")

if results:
    print("[SUCCESS] Quoka is working! Items found:\n")
    for i, item in enumerate(results[:10], 1):
        title = item.get('title', 'N/A')[:60]
        price = item.get('price', 'N/A')
        src = item.get('src', 'unknown')
        print(f"{i:2}. [{src}] {title}")
        print(f"    Price: {price}")
        print()
    
    print(f"...and {max(0, len(results) - 10)} more items")
else:
    print("[FAILURE] No results found - something is still wrong!")
    sys.exit(1)

print("\n" + "="*70)
print(" TEST COMPLETE - App is ready!")
print("="*70)
print("\nOpen browser: http://127.0.0.1:5000/search")
print("Search for: Iphone 12")
print("Select Source: Quoka")
print("="*70 + "\n")
