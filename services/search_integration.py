"""
services/search_integration.py

Helper to merge Kleinanzeigen results into existing result lists.
This is intentionally isolated and safe: it checks an env flag and never raises.
"""
import os
import logging
from typing import List, Dict

from services.kleinanzeigen import search_kleinanzeigen

logger = logging.getLogger(__name__)


def merge_kleinanzeigen_if_enabled(term: str, current_results: List[Dict], max_klein: int = 20) -> List[Dict]:
    """
    If ENABLE_KLEINANZEIGEN=1 in env, fetch kleinanzeigen results and append deduped items.
    Returns the combined list (original list returned unchanged on errors).
    """
    try:
        if os.getenv("ENABLE_KLEINANZEIGEN", "0") != "1":
            return current_results

        kitems = search_kleinanzeigen(term, page=1, per_page=max_klein)
        if not kitems:
            return current_results

        # Basic dedupe by url
        existing_urls = {it.get("url") for it in current_results if it.get("url")}
        for it in kitems:
            url = it.get("url")
            if url and url in existing_urls:
                continue
            current_results.append(it)
        return current_results
    except Exception:
        logger.exception("merge_kleinanzeigen_if_enabled failed")
        return current_results
