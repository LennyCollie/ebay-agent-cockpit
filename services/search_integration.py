# services/search_integration.py
"""
Integration helper for eBay-Kleinanzeigen search.
Provides a safe merge function that checks environment flags and de-duplicates results.
"""
import logging
import os
from typing import List, Dict, Optional

log = logging.getLogger(__name__)


def merge_kleinanzeigen_if_enabled(
    term: str,
    current_results: list,
    max_klein: int = 20
) -> list:
    """
    Merge eBay-Kleinanzeigen results with current results if enabled.
    
    This function:
    - Checks ENABLE_KLEINANZEIGEN environment flag
    - Calls services.kleinanzeigen.search_kleinanzeigen() if enabled
    - De-duplicates by URL
    - Appends results and returns combined list
    - Returns current_results unchanged if disabled or on error
    
    Args:
        term: Search term to query
        current_results: Existing search results (list of dicts with 'url' key)
        max_klein: Maximum number of Kleinanzeigen results to fetch (default: 20)
    
    Returns:
        Combined list of results (current + Kleinanzeigen if enabled)
    """
    # Check if Kleinanzeigen integration is enabled
    enable_flag = os.getenv("ENABLE_KLEINANZEIGEN", "0").lower()
    is_enabled = enable_flag in ("1", "true", "yes", "on")
    
    if not is_enabled:
        log.debug("Kleinanzeigen integration is disabled (ENABLE_KLEINANZEIGEN not set)")
        return current_results
    
    if not term or not term.strip():
        log.warning("Empty search term provided to merge_kleinanzeigen_if_enabled")
        return current_results
    
    try:
        # Import here to avoid loading the module if not needed
        from services.kleinanzeigen import search_kleinanzeigen
        
        log.info(f"Fetching Kleinanzeigen results for: {term}")
        klein_results = search_kleinanzeigen(term.strip(), max_results=max_klein)
        
        if not klein_results:
            log.info("No Kleinanzeigen results found")
            return current_results
        
        # De-duplicate by URL
        existing_urls = {
            _normalize_url(item.get("url", ""))
            for item in current_results
            if item.get("url")
        }
        
        # Filter out duplicates
        unique_klein = []
        for item in klein_results:
            item_url = _normalize_url(item.get("url", ""))
            if item_url and item_url not in existing_urls:
                unique_klein.append(item)
                existing_urls.add(item_url)
        
        if unique_klein:
            log.info(f"Adding {len(unique_klein)} unique Kleinanzeigen results")
            # Append to current results
            combined = list(current_results) + unique_klein
            return combined
        else:
            log.info("All Kleinanzeigen results were duplicates")
            return current_results
            
    except ImportError as e:
        log.error(f"Failed to import kleinanzeigen module: {e}")
        return current_results
    except Exception as e:
        log.error(f"Error merging Kleinanzeigen results: {e}", exc_info=True)
        return current_results


def _normalize_url(url: Optional[str]) -> str:
    """
    Normalize URL for deduplication.
    Removes trailing slashes, query parameters, and anchors.
    
    Args:
        url: URL string to normalize
    
    Returns:
        Normalized URL string
    """
    if not url:
        return ""
    
    # Remove protocol prefix for comparison
    normalized = url.lower()
    normalized = normalized.replace("https://", "").replace("http://", "")
    
    # Remove trailing slash
    normalized = normalized.rstrip("/")
    
    # Remove query parameters and anchors
    if "?" in normalized:
        normalized = normalized.split("?")[0]
    if "#" in normalized:
        normalized = normalized.split("#")[0]
    
    return normalized
