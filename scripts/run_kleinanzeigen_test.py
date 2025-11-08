#!/usr/bin/env python3
# scripts/run_kleinanzeigen_test.py
"""
Manual test script for Kleinanzeigen scraper.

Usage:
    python scripts/run_kleinanzeigen_test.py <search_term> [max_results]

Examples:
    python scripts/run_kleinanzeigen_test.py "iphone 13"
    python scripts/run_kleinanzeigen_test.py "macbook pro" 10
"""

import json
import logging
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.kleinanzeigen import search_kleinanzeigen, check_dependencies


def main():
    """Run manual test of Kleinanzeigen scraper."""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Parse arguments
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_kleinanzeigen_test.py <search_term> [max_results]")
        print("\nExamples:")
        print("  python scripts/run_kleinanzeigen_test.py 'iphone 13'")
        print("  python scripts/run_kleinanzeigen_test.py 'macbook pro' 10")
        sys.exit(1)
    
    search_term = sys.argv[1]
    max_results = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    
    print("="*70)
    print("Kleinanzeigen Scraper - Manual Test")
    print("="*70)
    print(f"Search term: {search_term}")
    print(f"Max results: {max_results}")
    print("="*70)
    print()
    
    # Check dependencies
    print("1. Checking dependencies...")
    if not check_dependencies():
        print("   ✗ ERROR: Required dependencies not available!")
        print("   Install with: pip install requests beautifulsoup4 lxml")
        sys.exit(1)
    print("   ✓ Dependencies OK")
    print()
    
    # Run search
    print(f"2. Searching Kleinanzeigen for '{search_term}'...")
    print("   (This may take a few seconds due to politeness delays)")
    print()
    
    try:
        results = search_kleinanzeigen(search_term, max_results=max_results)
        
        print(f"3. Results: Found {len(results)} items")
        print("="*70)
        print()
        
        if not results:
            print("No results found. This could mean:")
            print("  - No items match the search term")
            print("  - Network error")
            print("  - Kleinanzeigen changed their HTML structure")
            print("  - Rate limiting")
            print()
            print("Check logs above for error messages.")
            sys.exit(0)
        
        # Display results
        print("Results (formatted):")
        print("-"*70)
        
        for i, item in enumerate(results, 1):
            print(f"\n{i}. {item['title']}")
            print(f"   ID:       {item['id']}")
            print(f"   Price:    {item['price']} {item['currency']}")
            print(f"   URL:      {item['url']}")
            print(f"   Image:    {item['img'] or 'N/A'}")
            print(f"   Source:   {item['source']}")
        
        print("\n" + "="*70)
        print("\nJSON Output:")
        print("-"*70)
        print(json.dumps(results, indent=2, ensure_ascii=False))
        
        print("\n" + "="*70)
        print(f"✓ Test completed successfully - {len(results)} items found")
        print("="*70)
        
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(130)
    
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
