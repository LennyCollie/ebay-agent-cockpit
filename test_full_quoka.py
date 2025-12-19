import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

print("="*60)
print("[*] FULL QUOKA INTEGRATION TEST")
print("="*60)

from services.search_integration import merge_all_marketplaces

print("\n[*] Suche nach: 'Iphone 12'")
print("[*] Source: Quoka")
print("[*] Location: DE")

results = merge_all_marketplaces(
    term='Iphone 12',
    active_sources=['quoka'],
    max_per_source=20,
    verbose=True
)

print(f"\n{'='*60}")
print(f"[OK] ERGEBNIS: {len(results)} Quoka-Items gefunden!")
print(f"{'='*60}\n")

if results:
    for i, item in enumerate(results[:10], 1):
        title = item.get('title', 'N/A')[:60]
        price = item.get('price', 'N/A')
        source = item.get('src', 'unknown')
        print(f"{i}. [{source}] {title}")
        print(f"   Preis: {price}")
        print()
else:
    print("[!] KEINE ERGEBNISSE - Something is wrong!")
