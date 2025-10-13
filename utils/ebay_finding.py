# utils/ebay_finding.py
import os

import requests

FINDING_ENDPOINT = "https://svcs.ebay.com/services/search/FindingService/v1"


def finding_search(
    q: str,
    *,
    auction: bool,
    bin_buy: bool,
    buyer_postal: str | None,
    max_distance_km: int | None,
    ship_to: str | None,
    located_in: str | None,
    entries: int = 50,
) -> dict:
    appid = os.getenv("EBAY_APP_ID", "").strip()
    if not appid:
        raise RuntimeError("EBAY_APP_ID missing")

    params = {
        "OPERATION-NAME": "findItemsAdvanced",
        "SERVICE-VERSION": "1.0.0",
        "SECURITY-APPNAME": appid,
        "RESPONSE-DATA-FORMAT": "JSON",
        "REST-PAYLOAD": "true",
        "keywords": q,
        "paginationInput.entriesPerPage": str(entries),
    }

    idx = 0
    # ListingType
    if auction or bin_buy:
        params[f"itemFilter({idx}).name"] = "ListingType"
        j = 0
        if auction:
            params[f"itemFilter({idx}).value({j})"] = "Auction"
            j += 1
        if bin_buy:
            params[f"itemFilter({idx}).value({j})"] = "FixedPrice"
        idx += 1

    # Ship-to
    if ship_to:
        params[f"itemFilter({idx}).name"] = "AvailableTo"
        params[f"itemFilter({idx}).value"] = ship_to
        idx += 1

    # Artikelstandort
    if located_in:
        params[f"itemFilter({idx}).name"] = "LocatedIn"
        params[f"itemFilter({idx}).value"] = (
            "EuropeanUnion" if located_in == "EU" else located_in
        )
        idx += 1

    # Radius
    if buyer_postal and max_distance_km:
        params["buyerPostalCode"] = buyer_postal
        params[f"itemFilter({idx}).name"] = "MaxDistance"
        params[f"itemFilter({idx}).value"] = str(max_distance_km)
        idx += 1

    r = requests.get(FINDING_ENDPOINT, params=params, timeout=20)
    r.raise_for_status()
    return r.json()
