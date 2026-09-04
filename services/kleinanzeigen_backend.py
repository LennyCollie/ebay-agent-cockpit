from __future__ import annotations

from typing import Dict, List, Optional

from services.kleinanzeigen import (
    KleinanzeigenSearchResult,
    KleinanzeigenSearchStatus,
    search_kleinanzeigen,
)


def _parse_price(val):
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return None
    s = s.replace("€", "").replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


def backend_search_kleinanzeigen(
    terms: List[str],
    filters: Dict,
    per_page: int = 20,
) -> KleinanzeigenSearchResult:
    """
    Führt Kleinanzeigen-Suche getrennt pro Suchbegriff aus und dedupliziert die Ergebnisse.
    Geeignet für alert_checker.py und andere Cron-Jobs.
    """
    search_terms = [t.strip() for t in terms if t and t.strip()]
    if not search_terms:
        return KleinanzeigenSearchResult(
            results=[],
            status=KleinanzeigenSearchStatus.INVALID_RESPONSE,
            reason="empty_terms",
        )

    price_min = _parse_price(filters.get("price_min"))
    price_max = _parse_price(filters.get("price_max"))

    all_items: List[Dict] = []
    seen = set()
    per_term_limit = max(1, per_page // max(1, len(search_terms)))

    try:
        for term in search_terms:
            search_result = search_kleinanzeigen(
                query=term,
                price_min=price_min,
                price_max=price_max,
                limit=per_term_limit,
            )

            if search_result.status not in {
                KleinanzeigenSearchStatus.SUCCESS_WITH_RESULTS,
                KleinanzeigenSearchStatus.SUCCESS_EMPTY,
            }:
                return KleinanzeigenSearchResult(
                    results=all_items,
                    status=search_result.status,
                    reason=search_result.reason,
                    http_status=search_result.http_status,
                    retryable=search_result.retryable,
                )

            for raw in search_result.results:
                item_id = raw.get("item_id") or raw.get("id") or raw.get("url")
                if not item_id:
                    continue

                key = str(item_id)
                if key in seen:
                    continue
                seen.add(key)

                raw_price = raw.get("price")
                if isinstance(raw_price, (int, float)):
                    price_text = f"{float(raw_price):.2f} EUR"
                elif isinstance(raw_price, str) and raw_price.strip():
                    price_text = raw_price.strip()
                else:
                    price_text = "VB"

                all_items.append(
                    {
                        "id": key,
                        "title": raw.get("title") or "Ohne Titel",
                        "price": price_text,
                        "url": raw.get("url"),
                        "img": raw.get("image_url"),
                        "image_url": raw.get("image_url"),
                        "location": raw.get("location"),
                        "condition": raw.get("condition"),
                        "src": "kleinanzeigen",
                        "term": term,
                    }
                )

        print(f"      [OK] Kleinanzeigen-Backend: {len(all_items)} Items zurückgegeben")
        return KleinanzeigenSearchResult(
            results=all_items,
            status=(
                KleinanzeigenSearchStatus.SUCCESS_WITH_RESULTS
                if all_items
                else KleinanzeigenSearchStatus.SUCCESS_EMPTY
            ),
        )

    except Exception:
        return KleinanzeigenSearchResult(
            results=[],
            status=KleinanzeigenSearchStatus.INVALID_RESPONSE,
            reason="backend_error",
        )
