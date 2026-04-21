from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

from services.ebay_api import ebay_search


def _build_ebay_filter_str(filters: dict) -> Optional[str]:
    """Baut den eBay Browse API filter-String."""
    if not isinstance(filters, dict):
        return None

    parts: List[str] = []

    price_min = filters.get("price_min")
    price_max = filters.get("price_max")
    if price_min or price_max:
        lo = str(price_min).strip() if price_min not in (None, "") else "*"
        hi = str(price_max).strip() if price_max not in (None, "") else "*"
        parts.append(f"price:[{lo}..{hi}]")

    conditions = filters.get("conditions") or []
    if isinstance(conditions, str):
        conditions = [c.strip().upper() for c in conditions.split(",") if c.strip()]
    else:
        conditions = [str(c).strip().upper() for c in conditions if str(c).strip()]

    if conditions:
        parts.append("conditions:{" + ",".join(conditions) + "}")

    listing_type = str(filters.get("listing_type") or "").strip().lower()
    if listing_type:
        if listing_type in ("buy_it_now", "bin", "fixed_price", "fixedprice", "fixed"):
            parts.append("buyingOptions:{FIXED_PRICE}")
        elif listing_type in ("auction", "auktion"):
            parts.append("buyingOptions:{AUCTION}")

    free_shipping = filters.get("free_shipping")
    if free_shipping is True or str(free_shipping).strip().lower() in ("1", "true", "yes", "on"):
        parts.append("deliveryOptions:{FREE}")

    returns_accepted = filters.get("returns_accepted")
    if returns_accepted is True or str(returns_accepted).strip().lower() in ("1", "true", "yes", "on"):
        parts.append("returnsAccepted:true")

    top_rated_only = filters.get("top_rated_only")
    if top_rated_only is True or str(top_rated_only).strip().lower() in ("1", "true", "yes", "on"):
        parts.append("sellerTopRated:true")

    return ",".join(parts) if parts else None


def _map_sort(sort_value: Optional[str]) -> str:
    """Mappt UI-Sortierungen auf services.ebay_api.ebay_search."""
    s = (sort_value or "").strip()
    if not s or s == "best":
        return "bestMatch"
    if s == "price_asc":
        return "price"
    if s == "price_desc":
        return "-price"
    if s == "newly":
        return "newlyListed"
    return s


def _payload_to_items(payload: Dict, term: str) -> Tuple[List[Dict], Optional[int]]:
    """Normalisiert eBay Browse API Payload in dein Standard-Item-Format."""
    items_raw = (payload or {}).get("itemSummaries", []) or []
    total = (payload or {}).get("total")

    items: List[Dict] = []
    for raw in items_raw:
        item_id = (
            raw.get("itemId")
            or raw.get("legacyItemId")
            or raw.get("itemWebUrl")
            or raw.get("title")
        )
        if not item_id:
            continue

        price_text = "–"
        price_obj = raw.get("price") or {}
        if price_obj.get("value") is not None and price_obj.get("currency"):
            price_text = f"{price_obj.get('value')} {price_obj.get('currency')}"

        image_url = (raw.get("image") or {}).get("imageUrl")

        items.append(
            {
                "id": str(item_id),
                "title": raw.get("title") or "Ohne Titel",
                "price": price_text,
                "url": raw.get("itemWebUrl"),
                "img": image_url,
                "image_url": image_url,
                "condition": raw.get("condition"),
                "src": "ebay",
                "term": term,
            }
        )

    return items, (int(total) if isinstance(total, int) else None)


def backend_search_ebay(
    terms: List[str],
    filters: dict,
    page: int,
    per_page: int,
) -> Tuple[List[Dict], Optional[int]]:
    """
    Führt eBay-Suche getrennt pro Suchbegriff aus und dedupliziert die Ergebnisse.
    Unabhängig von app.py, geeignet für alert_checker.py und andere Cron-Jobs.
    """
    live_search = str(os.getenv("LIVE_SEARCH", "false")).strip().lower() in ("true", "1", "yes", "on")
    if not live_search:
        print("[WARNUNG] LIVE_SEARCH ist deaktiviert")
        return [], 0

    search_terms = [t.strip() for t in terms if t and t.strip()]
    if not search_terms:
        return [], 0

    filter_str = _build_ebay_filter_str(filters or {})
    sort = _map_sort(filters.get("sort", "best"))
    category_ids = filters.get("category_ids")
    country_code = filters.get("location_country")

    n = max(1, len(search_terms))
    per_term = max(1, per_page // n)
    offset = max(0, (page - 1) * per_term)

    items_all: List[Dict] = []
    totals: List[int] = []
    seen = set()

    for term in search_terms:
        payload = ebay_search(
            term,
            limit=per_term,
            offset=offset,
            sort=sort,
            category_ids=category_ids,
            filter_str=filter_str,
            country_code=country_code,
        )
        items, total = _payload_to_items(payload, term)

        for item in items:
            key = item.get("id") or item.get("url") or item.get("title")
            if key and key not in seen:
                seen.add(key)
                items_all.append(item)

        if isinstance(total, int):
            totals.append(total)

    if len(items_all) < per_page and search_terms:
        rest = per_page - len(items_all)
        extra_per_term = max(1, rest // len(search_terms))

        for term in search_terms:
            payload = ebay_search(
                term,
                limit=extra_per_term,
                offset=offset + per_term,
                sort=sort,
                category_ids=category_ids,
                filter_str=filter_str,
                country_code=country_code,
            )
            extra_items, _ = _payload_to_items(payload, term)

            for item in extra_items:
                key = item.get("id") or item.get("url") or item.get("title")
                if key and key not in seen:
                    seen.add(key)
                    items_all.append(item)

            if len(items_all) >= per_page:
                break

    total_estimated = sum(totals) if totals else None
    return items_all[:per_page], total_estimated
