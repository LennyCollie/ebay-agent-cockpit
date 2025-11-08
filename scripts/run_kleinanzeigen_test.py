#!/usr/bin/env python3
# scripts/run_kleinanzeigen_test.py
"""
Simple integration test script for Kleinanzeigen search.
This script can be executed locally or in a container to print sample results for manual QA.

Usage:
    python scripts/run_kleinanzeigen_test.py [search_term] [max_results]

Example:
    python scripts/run_kleinanzeigen_test.py laptop 5
    python scripts/run_kleinanzeigen_test.py "macbook pro" 10
"""
import sys
import os

# Add parent directory to path to import services
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services.kleinanzeigen import search_kleinanzeigen


def format_price(price, currency):
    """Format price for display."""
    if price:
        return f"{price} {currency}"
    return "N/A (VB, free, or negotiable)"


def main():
    # Parse command line arguments
    search_term = sys.argv[1] if len(sys.argv) > 1 else "laptop"
    max_results = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    
    print("=" * 80)
    print(f"eBay-Kleinanzeigen Integration Test")
    print("=" * 80)
    print(f"Search term: {search_term}")
    print(f"Max results: {max_results}")
    print("=" * 80)
    print()
    
    # Perform search
    print("🔍 Searching Kleinanzeigen...")
    print()
    
    results = search_kleinanzeigen(search_term, max_results=max_results)
    
    if not results:
        print("❌ No results found or search failed.")
        print()
        print("Troubleshooting:")
        print("  - Check your internet connection")
        print("  - Try a different search term")
        print("  - Check the logs for error messages")
        return 1
    
    # Display results
    print(f"✅ Found {len(results)} results:")
    print()
    
    for i, item in enumerate(results, 1):
        print(f"{'─' * 80}")
        print(f"Result #{i}")
        print(f"{'─' * 80}")
        print(f"Title:    {item['title']}")
        print(f"ID:       {item['id']}")
        print(f"Price:    {format_price(item['price'], item['currency'])}")
        print(f"URL:      {item['url']}")
        print(f"Image:    {item['img'] if item['img'] else 'N/A'}")
        print(f"Source:   {item['source']}")
        print()
    
    print("=" * 80)
    print("✅ Test completed successfully!")
    print("=" * 80)
    
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
