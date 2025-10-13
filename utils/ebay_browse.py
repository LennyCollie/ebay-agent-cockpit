# utils/ebay_browse.py
import os
from typing import Optional

import requests

from utils.ebay_auth import get_browse_token

BROWSE_ENDPOINT = "https://api.ebay.com/buy/browse/v1/item_summary/search"

REGION_MAP = {  # für itemLocationRegion
    "EU": "EUROPEAN_UNION",
}


def browse_search(
    q: str,
    *,
    auction: bool,
    bin_buy: bool,
    ship_to: Optional[str],
    postal: Optional[str],
    located_in: Optional[str],
    located_region: Optional[str],
    price_min: float | None = None,
    price_max: float | None = None,
    local_pickup_radius_km: int | None = None,
    pickup_country: str | None = None,
    limit: int = 50,
) -> dict:
    token = os.getenv("EBAY_BROWSE_TOKEN", "").strip()
    if not token:
        raise RuntimeError("EBAY_BROWSE_TOKEN missing")
    headers = {"Authorization": f"Bearer {token}"}

    filters = []

    # Auktion / Sofortkauf
    opts = []
    if auction:
        opts.append("AUCTION")
    if bin_buy:
        opts.append("FIXED_PRICE")
    if opts:
        filters.append(f"buyingOptions:{{{'|'.join(opts)}}}")

    # Ship-to
    if ship_to:
        filters.append(f"deliveryCountry:{ship_to}")
        if postal:  # deliveryPostalCode erfordert Country
            filters.append(f"deliveryPostalCode:{postal}")

    # Standort (Land ODER Region)
    if located_in:
        if located_in == "EU":
            filters.append(f"itemLocationRegion:{REGION_MAP['EU']}")
        else:
            filters.append(f"itemLocationCountry:{located_in}")
    elif located_region:
        filters.append(f"itemLocationRegion:{located_region}")

    # Preis
    if price_min is not None or price_max is not None:
        low = "" if price_min is None else f"{price_min}"
        high = "" if price_max is None else f"{price_max}"
        filters.append(f"price:[{low}..{high}]")
        filters.append("priceCurrency:EUR")

    # Local Pickup Radius (optional)
    if local_pickup_radius_km and pickup_country and postal:
        filters.append("deliveryOptions:{SELLER_ARRANGED_LOCAL_PICKUP}")
        filters += [
            f"pickupCountry:{pickup_country}",
            f"pickupPostalCode:{postal}",
            f"pickupRadius:{local_pickup_radius_km}",
            "pickupRadiusUnit:km",
        ]

    params = {"q": q, "limit": str(limit)}
    if filters:
        params["filter"] = ",".join(filters)

    r = requests.get(BROWSE_ENDPOINT, headers=headers, params=params, timeout=20)
    r.raise_for_status()
    return r.json()
