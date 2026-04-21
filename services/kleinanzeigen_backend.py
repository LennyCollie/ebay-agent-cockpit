from __future__ import annotations

from typing import Dict, List, Optional


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
) -> List[Dict]:
    """
    Führt Kleinanzeigen-Suche getrennt pro Suchbegriff aus und dedupliziert die Ergebnisse.
    Geeignet für alert_checker.py und andere Cron-Jobs.
    """
    try:
        from services.kleinanzeigen import search_kleinanzeigen
    except Exception as e:
        print(f"      [!] Kleinanzeigen-Modul nicht importierbar: {e}")
        return []

    search_terms = [t.strip() for t in terms if t and t.strip()]
    if not search_terms:
        return []

    price_min = _parse_price(filters.get("price_min"))
    price_max = _parse_price(filters.get("price_max"))

    all_items: List[Dict] = []
    seen = set()
    per_term_limit = max(1, per_page // max(1, len(search_terms)))

    try:
        for term in search_terms:
            results = search_kleinanzeigen(
                query=term,
                price_min=price_min,
                price_max=price_max,
                limit=per_term_limit,
            )

            for raw in results:
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
        return all_items

    except Exception as e:
        print(f"      [!] Kleinanzeigen-Suche Fehler: {e}")
        import traceback
        traceback.print_exc()
        return []
