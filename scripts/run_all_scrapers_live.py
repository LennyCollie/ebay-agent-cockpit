#!/usr/bin/env python3
"""Manual live runner for all marketplace scrapers."""
import logging
import sys
import os
from datetime import datetime

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)


def print_header(title):
    """Schöner Header für Tests"""
    print("\n" + "="*70)
    print(f"  {title}")
    print("="*70 + "\n")


def print_result(name, success, details=""):
    """Formatiert Test-Ergebnis"""
    emoji = "✅" if success else "❌"
    print(f"{emoji} {name:30} {details}")


def test_dependencies():
    """Test 1: Dependencies prüfen"""
    print_header("TEST 1: Dependencies")

    try:
        import requests
        print_result("requests", True, f"v{requests.__version__}")
    except ImportError as e:
        print_result("requests", False, str(e))
        return False

    try:
        import bs4
        print_result("beautifulsoup4", True, f"v{bs4.__version__}")
    except ImportError as e:
        print_result("beautifulsoup4", False, str(e))
        return False

    try:
        import lxml
        print_result("lxml", True, "OK")
    except ImportError:
        print_result("lxml", False, "Optional aber empfohlen")

    return True


def test_single_scraper(name, scraper_func, query="iPhone 13", **kwargs):
    """Testet einen einzelnen Scraper"""
    try:
        log.info(f"Testing {name}...")

        start = datetime.now()
        results = scraper_func(query=query, limit=10, **kwargs)
        duration = (datetime.now() - start).total_seconds()

        success = len(results) > 0

        details = f"{len(results):2d} results in {duration:.1f}s"
        print_result(name, success, details)

        if success and len(results) > 0:
            # Zeige ein Beispiel-Item
            item = results[0]
            print(f"     Sample: {item['title'][:50]}")
            print(f"             {item.get('price', 'N/A')} | {item['source']}")

        return success

    except Exception as e:
        print_result(name, False, f"ERROR: {str(e)[:40]}")
        return False


def test_all_scrapers():
    """Test 2: Alle Scraper einzeln"""
    print_header("TEST 2: Individual Scrapers")

    results = {}

    # Kleinanzeigen
    try:
        from services.kleinanzeigen import search_kleinanzeigen

        results['Kleinanzeigen'] = test_single_scraper(
            "Kleinanzeigen",
            search_kleinanzeigen,
            price_max=600
        )
    except ImportError as e:
        print_result("Kleinanzeigen", False, "Module nicht gefunden")
        results['Kleinanzeigen'] = False

    # Quoka
    try:
        from services.quoka_scraper import search_quoka
        results['Quoka'] = test_single_scraper(
            "Quoka",
            search_quoka,
            price_max=600
        )
    except ImportError:
        print_result("Quoka", False, "Module nicht gefunden")
        results['Quoka'] = False

    # Shpock
    try:
        from services.shpock_scraper import search_shpock
        results['Shpock'] = test_single_scraper(
            "Shpock",
            search_shpock,
            price_max=600
        )
    except ImportError:
        print_result("Shpock", False, "Module nicht gefunden")
        results['Shpock'] = False

    # Markt.de
    try:
        from services.marktde_scraper import search_marktde
        results['Markt.de'] = test_single_scraper(
            "Markt.de",
            search_marktde,
            price_max=600
        )
    except ImportError:
        print_result("Markt.de", False, "Module nicht gefunden")
        results['Markt.de'] = False

    return results


def test_integration():
    """Test 3: Integration aller Portale"""
    print_header("TEST 3: Integration (All Marketplaces)")

    try:
        from services.search_integration import merge_all_marketplaces

        # Aktiviere alle
        os.environ["ENABLE_KLEINANZEIGEN"] = "1"
        os.environ["ENABLE_QUOKA"] = "1"
        os.environ["ENABLE_SHPOCK"] = "1"
        os.environ["ENABLE_MARKTDE"] = "1"

        # Mock eBay results
        mock_ebay = [
            {"title": "Test iPhone", "url": "http://ebay.test/1", "source": "ebay", "price": 450.0}
        ]

        start = datetime.now()
        results = merge_all_marketplaces(
            term="iPhone 13",
            current_results=mock_ebay,
            price_max=600,
            location="50667",
            max_per_source=10,
            verbose=False
        )
        duration = (datetime.now() - start).total_seconds()

        # Analyse
        sources = {}
        for item in results:
            source = item.get('source', 'unknown')
            sources[source] = sources.get(source, 0) + 1

        print(f"\n📊 Integration Results:")
        print(f"   Total: {len(results)} items in {duration:.1f}s")
        print(f"   Sources:")
        for source, count in sorted(sources.items()):
            print(f"     • {source:15} {count:3d} items")

        success = len(results) > 1  # Mindestens 2 (mock + 1 real)
        print_result("\nIntegration", success, f"{len(results)} total items")

        return success

    except Exception as e:
        print_result("Integration", False, f"ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_deduplication():
    """Test 4: Deduplizierung"""
    print_header("TEST 4: Deduplication")

    try:
        from services.search_integration import merge_all_marketplaces

        # Duplicate URLs
        test_data = [
            {"title": "Item 1", "url": "http://test.com/1", "source": "test1"},
            {"title": "Item 2", "url": "http://test.com/2", "source": "test1"},
            {"title": "Item 1 Dupe", "url": "http://test.com/1", "source": "test2"},  # Duplicate!
        ]

        # Dedup sollte nur 2 zurückgeben
        from services.search_integration import _deduplicate_and_merge
        result = _deduplicate_and_merge([], test_data, "test")

        success = len(result) == 2  # Nur unique URLs
        print_result("Deduplication", success, f"{len(result)}/2 unique items")

        return success

    except Exception as e:
        print_result("Deduplication", False, str(e))
        return False


def test_price_filter():
    """Test 5: Preis-Filter"""
    print_header("TEST 5: Price Filters")

    try:
        from services.quoka_scraper import search_quoka

        # Test mit Preis-Range
        results = search_quoka(
            query="iPhone",
            price_min=300,
            price_max=500,
            limit=10
        )

        # Prüfe ob Filter funktioniert
        filtered = [r for r in results if r.get('price')]
        out_of_range = [r for r in filtered if r['price'] < 300 or r['price'] > 500]

        success = len(out_of_range) == 0
        details = f"{len(filtered)} items, {len(out_of_range)} out of range"
        print_result("Price Filter", success, details)

        return success

    except Exception as e:
        print_result("Price Filter", False, str(e))
        return False


def performance_test():
    """Test 6: Performance"""
    print_header("TEST 6: Performance")

    try:
        from services.search_integration import merge_all_marketplaces

        os.environ["ENABLE_KLEINANZEIGEN"] = "1"
        os.environ["ENABLE_QUOKA"] = "1"

        # Zeitmessung
        import time
        times = []

        for i in range(3):
            start = time.time()
            results = merge_all_marketplaces(
                term="iPhone",
                current_results=[],
                max_per_source=5,
                verbose=False
            )
            duration = time.time() - start
            times.append(duration)
            print(f"  Run {i+1}: {duration:.2f}s ({len(results)} items)")

        avg_time = sum(times) / len(times)
        success = avg_time < 10.0  # Sollte unter 10 Sekunden sein

        print_result("\nPerformance", success, f"Avg: {avg_time:.2f}s")

        return success

    except Exception as e:
        print_result("Performance", False, str(e))
        return False


def run_all_tests():
    """Führt alle Tests aus"""
    print("\n")
    print("🧪 " + "="*68)
    print("🧪  SUPER-AGENT - ULTIMATE TEST SUITE")
    print("🧪 " + "="*68)
    print()

    test_results = {}

    # Test 1: Dependencies
    test_results['Dependencies'] = test_dependencies()

    if not test_results['Dependencies']:
        print("\n❌ Dependencies fehlen! Bitte installieren:")
        print("   pip install requests beautifulsoup4 lxml")
        return

    # Test 2: Einzelne Scraper
    scraper_results = test_all_scrapers()
    test_results.update(scraper_results)

    # Test 3: Integration
    test_results['Integration'] = test_integration()

    # Test 4: Deduplication
    test_results['Deduplication'] = test_deduplication()

    # Test 5: Price Filter
    test_results['Price Filter'] = test_price_filter()

    # Test 6: Performance
    test_results['Performance'] = performance_test()

    # Summary
    print_header("SUMMARY")

    passed = sum(1 for v in test_results.values() if v)
    total = len(test_results)

    for name, success in test_results.items():
        emoji = "✅" if success else "❌"
        print(f"{emoji} {name}")

    print(f"\n📊 Result: {passed}/{total} tests passed ({passed/total*100:.0f}%)")

    if passed == total:
        print("\n🎉 ALLE TESTS BESTANDEN! 🎉")
        print("Deine App ist bereit für den Live-Einsatz! 🚀")
    elif passed >= total * 0.7:
        print("\n⚠️  Die meisten Tests OK - kleine Fehler beheben")
    else:
        print("\n❌ Mehrere Tests fehlgeschlagen - Debug erforderlich")

    return test_results


if __name__ == "__main__":
    try:
        results = run_all_tests()
        sys.exit(0 if all(results.values()) else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Tests abgebrochen")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Fataler Fehler: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
