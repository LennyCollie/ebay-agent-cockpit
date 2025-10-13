# utils/ebay_normalize.py
from typing import Any, Dict, List


def normalize_browse(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    items = data.get("itemSummaries", []) or []
    for it in items:
        price = (it.get("price") or {}).get("value")
        currency = (it.get("price") or {}).get("currency")
        img = (it.get("image") or {}).get("imageUrl")
        pics = [img] if img else []
        # ggf. mehr Bilder:
        for g in it.get("additionalImages", []) or []:
            u = g.get("imageUrl")
            if u:
                pics.append(u)
        out.append(
            {
                "title": it.get("title"),
                "price": float(price) if price else None,
                "currency": currency or "EUR",
                "url": it.get("itemWebUrl") or it.get("itemHref"),
                "image": pics[0] if pics else None,
                "images": pics,
                "location": (it.get("itemLocation") or {}).get("postalCode")
                or (it.get("itemLocation") or {}).get("city")
                or "",
                "timestamp": it.get("itemCreationDate") or "",
                "verdict": "ok",  # Platzhalter; dein Vision-Check setzt das später
                "score": 0.0,
            }
        )
    return out


def normalize_finding(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    sr = ((data or {}).get("findItemsAdvancedResponse") or [None])[0] or {}
    arr = (((sr.get("searchResult") or [None])[0] or {}).get("item") or []) or []
    for it in arr:
        selling = (it.get("sellingStatus") or [None])[0] or {}
        cur_item = (it.get("currentPrice") or [{}])[0]
        price = (selling.get("currentPrice") or [{}])[0].get(
            "__value__"
        ) or cur_item.get("__value__")
        currency = (
            (selling.get("currentPrice") or [{}])[0].get("@currencyId")
            or cur_item.get("@currencyId")
            or "EUR"
        )
        gallery = (it.get("galleryURL") or [None])[0]
        pics = [gallery] if gallery else []
        out.append(
            {
                "title": (it.get("title") or [""])[0],
                "price": float(price) if price else None,
                "currency": currency,
                "url": (it.get("viewItemURL") or [""])[0],
                "image": pics[0] if pics else None,
                "images": pics,
                "location": (it.get("location") or [""])[0],
                "timestamp": (it.get("listingInfo") or [{}])[0].get("startTime") or "",
                "verdict": "ok",
                "score": 0.0,
            }
        )
    return out
