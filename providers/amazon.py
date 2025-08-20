from __future__ import annotations
import os, json, hmac, hashlib, datetime
from typing import List, Dict, Optional, Tuple
import requests

# ---- ENV / Defaults ----
AMZ_ENABLED    = str(os.getenv("AMZ_ENABLED", "1")).strip().lower() in {"1","true","yes","on"}
AMZ_ACCESS_KEY = os.getenv("AMZ_ACCESS_KEY", "")
AMZ_SECRET_KEY = os.getenv("AMZ_SECRET_KEY", "")
AMZ_ASSOC_TAG  = os.getenv("AMZ_ASSOC_TAG", "")   # your Associate tag, e.g. foo-21
AMZ_MARKET     = (os.getenv("AMZ_MARKET", "DE") or "DE").upper()

# Endpoint/region mapping
if AMZ_MARKET == "DE":
    HOST   = "webservices.amazon.de"
    REGION = "eu-west-1"
elif AMZ_MARKET in ("UK","GB"):
    HOST   = "webservices.amazon.co.uk"
    REGION = "eu-west-1"
elif AMZ_MARKET == "US":
    HOST   = "webservices.amazon.com"
    REGION = "us-east-1"
else:
    HOST   = "webservices.amazon.de"
    REGION = "eu-west-1"

SERVICE = "ProductAdvertisingAPI"
ENDPOINT = f"https://{HOST}/paapi5/searchitems"
TARGET   = "com.amazon.paapi5.v1.ProductAdvertisingAPIv1.SearchItems"

_http = requests.Session()

def _hmac(key, msg): return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()
def _sha256_hex(s: bytes) -> str: return hashlib.sha256(s).hexdigest()

def _aws_sig_v4(body: str, amz_date: str, date: str) -> str:
    canonical_uri = "/paapi5/searchitems"
    canonical_headers = (
        f"content-encoding:amz-1.0\n"
        f"content-type:application/json; charset=UTF-8\n"
        f"host:{HOST}\n"
        f"x-amz-date:{amz_date}\n"
        f"x-amz-target:{TARGET}\n"
    )
    signed_headers = "content-encoding;content-type;host;x-amz-date;x-amz-target"
    payload_hash = _sha256_hex(body.encode("utf-8"))
    canonical_request = "POST\n" + canonical_uri + "\n\n" + canonical_headers + "\n" + signed_headers + "\n" + payload_hash

    algo = "AWS4-HMAC-SHA256"
    scope = f"{date}/{REGION}/{SERVICE}/aws4_request"
    string_to_sign = f"{algo}\n{amz_date}\n{scope}\n{_sha256_hex(canonical_request.encode('utf-8'))}"

    k_date    = _hmac(("AWS4" + AMZ_SECRET_KEY).encode("utf-8"), date)
    k_region  = hmac.new(k_date, REGION.encode("utf-8"), hashlib.sha256).digest()
    k_service = hmac.new(k_region, SERVICE.encode("utf-8"), hashlib.sha256).digest()
    k_signing = hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization = (
        f"{algo} Credential={AMZ_ACCESS_KEY}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return authorization

def _signed_headers(body: str) -> Dict[str,str]:
    now = datetime.datetime.utcnow()
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date     = now.strftime("%Y%m%d")
    return {
        "content-encoding": "amz-1.0",
        "content-type": "application/json; charset=UTF-8",
        "host": HOST,
        "x-amz-date": amz_date,
        "x-amz-target": TARGET,
        "Authorization": _aws_sig_v4(body, amz_date, date),
    }

def _fmt_price(offer: dict) -> Optional[str]:
    try:
        p = offer["Listings"][0]["Price"]
        return p.get("DisplayAmount") or f'{p["Amount"]} {p.get("Currency", "")}'
    except Exception:
        return None

def _primary_image(item: dict) -> Optional[str]:
    try:
        return item["Images"]["Primary"]["Medium"]["URL"]
    except Exception:
        return None

def _title(item: dict) -> str:
    try:
        return item["ItemInfo"]["Title"]["DisplayValue"]
    except Exception:
        return "—"

def amazon_search_simple(
    keyword: str,
    limit: int = 10,
    sort: Optional[str] = None
) -> List[Dict]:
    """
    Minimal SearchItems call.
    Returns list of unified item dicts: {title, price, url, img, source}
    """
    if not (AMZ_ENABLED and AMZ_ACCESS_KEY and AMZ_SECRET_KEY and AMZ_ASSOC_TAG):
        return []

    # Map our sort to PA-API's SortBy (few options). Keep it simple.
    sort_by = None
    if sort == "price_asc":  sort_by = "Price:LowToHigh"
    if sort == "price_desc": sort_by = "Price:HighToLow"

    body_obj = {
        "Keywords": keyword,
        "PartnerTag": AMZ_ASSOC_TAG,
        "PartnerType": "Associates",
        "Marketplace": "www.amazon.de" if AMZ_MARKET=="DE" else (
            "www.amazon.co.uk" if AMZ_MARKET in ("UK","GB") else "www.amazon.com"
        ),
        "ItemCount": max(1, min(int(limit or 10), 10)),
        "Resources": [
            "Images.Primary.Medium",
            "ItemInfo.Title",
            "Offers.Listings.Price"
        ],
    }
    if sort_by:
        body_obj["SortBy"] = sort_by

    body = json.dumps(body_obj, separators=(",",":"))
    headers = _signed_headers(body)

    try:
        r = _http.post(ENDPOINT, data=body, headers=headers, timeout=15)
        r.raise_for_status()
        j = r.json()
    except Exception as e:
        print(f"[amazon] request error: {e}")
        return []

    items = []
    for it in (j.get("SearchResult") or {}).get("Items", []) or []:
        items.append({
            "title": _title(it),
            "price": _fmt_price(it.get("Offers") or {}) or "–",
            "url"  : it.get("DetailPageURL"),
            "img"  : _primary_image(it),
            "source": "amazon",
        })
    return items