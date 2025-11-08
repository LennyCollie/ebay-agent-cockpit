# services/search_integration.py
"""
Search integration helper for merging Kleinanzeigen results.

This module provides fail-safe integration of Kleinanzeigen search results
with existing aggregator results.
"""

import logging
import os
from typing import List, Dict

log = logging.getLogger(__name__)


def merge_kleinanzeigen_if_enabled(
    term: str,
    current_results: list,
    max_klein: int = 20
) -> list:
    """
    Merge Kleinanzeigen results with current results if enabled via environment flag.
    
    This function is completely fail-safe - if anything goes wrong, it returns
    the original results unchanged.
    
    Args:
        term: Search term to query Kleinanzeigen
        current_results: Existing search results (list of dicts)
        max_klein: Maximum number of Kleinanzeigen results to fetch (default 20)
    
    Returns:
        Combined list of results. Original results on any error.
    
    Environment:
        ENABLE_KLEINANZEIGEN: Set to "1" to enable Kleinanzeigen integration
    
    Example:
        >>> results = ebay_search("iphone 13")
        >>> results = merge_kleinanzeigen_if_enabled("iphone 13", results)
    """
    # Check if feature is enabled
    enabled = os.getenv("ENABLE_KLEINANZEIGEN", "0")
    if enabled != "1":
        log.debug("Kleinanzeigen integration disabled (ENABLE_KLEINANZEIGEN != 1)")
        return current_results
    
    # Validate inputs
    if not term or not isinstance(term, str):
        log.warning("Invalid search term for Kleinanzeigen integration")
        return current_results
    
    if not isinstance(current_results, list):
        log.warning("Invalid current_results type for Kleinanzeigen integration")
        return current_results
    
    try:
        # Import here to avoid issues if dependencies not installed
        from services.kleinanzeigen import search_kleinanzeigen, check_dependencies
        
        # Check dependencies
        if not check_dependencies():
            log.warning(
                "Kleinanzeigen integration enabled but dependencies not available. "
                "Install: pip install requests beautifulsoup4 lxml"
            )
            return current_results
        
        log.info(f"Fetching Kleinanzeigen results for: {term}")
        
        # Fetch Kleinanzeigen results
        klein_results = search_kleinanzeigen(term, max_results=max_klein)
        
        if not klein_results:
            log.info("No Kleinanzeigen results found")
            return current_results
        
        # De-duplicate by URL
        # Build set of existing URLs
        existing_urls = set()
        for item in current_results:
            if isinstance(item, dict) and "url" in item:
                existing_urls.add(item["url"])
        
        # Filter out duplicates
        new_items = []
        for item in klein_results:
            if item.get("url") not in existing_urls:
                new_items.append(item)
                existing_urls.add(item.get("url"))
        
        log.info(f"Adding {len(new_items)} unique Kleinanzeigen results")
        
        # Append and return combined results
        return current_results + new_items
    
    except ImportError as e:
        log.warning(f"Could not import Kleinanzeigen module: {e}")
        return current_results
    
    except Exception as e:
        log.error(f"Error in Kleinanzeigen integration: {e}")
        # Always return original results on error (fail-safe)
        return current_results


if __name__ == "__main__":
    # Simple test
    logging.basicConfig(level=logging.INFO)
    
    print("Testing search_integration helper...")
    print("\nTest 1: Disabled (should return original results)")
    
    test_results = [
        {"title": "Item 1", "url": "http://example.com/1", "source": "test"}
    ]
    
    merged = merge_kleinanzeigen_if_enabled("iphone", test_results, max_klein=5)
    print(f"Original: {len(test_results)} items")
    print(f"Merged: {len(merged)} items")
    assert len(merged) == len(test_results), "Should return original when disabled"
    
    print("\nTest 2: Enabled (set ENABLE_KLEINANZEIGEN=1 to test)")
    os.environ["ENABLE_KLEINANZEIGEN"] = "1"
    merged = merge_kleinanzeigen_if_enabled("iphone", test_results, max_klein=5)
    print(f"Merged: {len(merged)} items")
    
    if len(merged) > len(test_results):
        print("✓ Successfully merged Kleinanzeigen results")
        print("\nSample merged items:")
        for i, item in enumerate(merged[:3]):
            print(f"{i+1}. {item.get('title')} ({item.get('source')})")
    else:
        print("ℹ No additional results (may need internet connection)")
    
    print("\n✓ Tests completed")
