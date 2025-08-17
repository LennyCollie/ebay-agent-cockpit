# services/ebay_api.py
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

import requests

log = logging.getLogger(__name__)

# ---------- ENV ----------
EBAY_ENV = os.getenv("EBAY_ENV", "production").lower()
CLIENT_ID = os.getenv("EBAY_CLIENT_ID")
CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET")

# Für Browse genügt ein Application Token (kein Refresh-Token nötig)
# Scopes können bei Bedarf via ENV erweitert werden
SCOPES = os.getenv(
    "EBAY_SCOPES",
    "https://api.ebay.com/oauth/api_scope https://api.ebay.com/oauth/api_scope/buy.browse",
)

MARKETPLACE_ID = os.getenv("EBAY_MARKETPLACE_ID", "EBAY_DE")
ACCEPT_LANGUAGE = os.getenv("EBAY_ACCEPT_LANGUAGE", "de-DE")

AFFILIATE_ENABLE = os.getenv("AFFILIATE_ENABLE", "false").lower() in {"1", "true", "yes", "on"}
AFFILIATE_PARAMS = os.getenv("AFFILIATE_PARAMS", "")  # z.B. campid=XXXX;customid=YOURTAG

BASE = "https://api.ebay.com" if EBAY_ENV == "production" else "https://api.sandbox.ebay.com"

# ---------- Token Cache ----------
_token_cache: Dict[str, Any] = {}


def _get_access_token() -> str:
    now = time.time()
    if _token_cache.get("type") == "app" and _token_cache.get("exp", 0) > now + 30:
        return _token_cache["token"]

    if not CLIENT_ID or not CLIENT_SECRET:
        raise RuntimeError("EBAY_CLIENT_ID/EBAY_CLIENT_SECRET fehlen")

    scopes = os.getenv("EBAY_SCOPES", "https://api.ebay.com/oauth/api_scope")
    def _request_token(scope_str: str):
        resp = requests.post(
            f"{BASE}/identity/v1/oauth2/token",
            data={"grant_type": "client_credentials", "scope": scope_str},
            auth=(CLIENT_ID, CLIENT_SECRET),
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()

    try:
        tok = _request_token(scopes)
    except requests.HTTPError as e:
        text = getattr(e.response, "text", "")
        if e.response is not None and e.response.status_code == 400 and "invalid_scope" in text:
            log.warning("eBay OAuth: invalid_scope – fallback auf Basisscope")
            tok = _request_token("https://api.ebay.com/oauth/api_scope")
        else:
            log.error("eBay OAuth Fehler: %s - %s", getattr(e.response, "status_code", "?"), text)
            raise

    _token_cache.update({
        "type": "app",
        "token": tok["access_token"],
        "exp": now + int(tok.get("expires_in", 7200)) - 60,
    })
    return _token_cache["token"]

def _attach_affiliate(url: str) -> str:
    """Hängt Affiliate-Parameter an itemWebUrl an (wenn aktiviert)."""
    if not (AFFILIATE_ENABLE and AFFILIATE_PARAMS and url and url.startswith("http")):
        return url
    try:
        from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

        p = urlparse(url)
        params = dict(parse_qsl(p.query, keep_blank_values=True))
        # AFFILIATE_PARAMS: "campid=XXXX;customid=YOURTAG"
        for kv in (AFFILIATE_PARAMS or "").split(";"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                params[k.strip()] = v.strip()
        q = urlencode(params, doseq=True)
        return urlunparse((p.scheme, p.netloc, p.path, p.params, q, p.fragment))
    except Exception:
        return url


def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {_get_access_token()}",
        "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE_ID,
        "Accept-Language": ACCEPT_LANGUAGE,
        "Content-Type": "application/json",
    }


def _map_sort(sort_key: str) -> str:
    """
    Mappt UI-Sortierungen auf eBay-Parameter:
      - bestMatch (Default)
      - price (aufsteigend), -price (absteigend)
      - newlyListed / -newlyListed
    """
    if sort_key in {"price_asc", "price"}:
        return "price"
    if sort_key in {"price_desc", "-price"}:
        return "-price"
    if sort_key in {"new", "newly", "newlyListed"}:
        return "newlyListed"
    if sort_key in {"-new", "-newly", "-newlyListed"}:
        return "-newlyListed"
    return "bestMatch"


def ebay_search(
    query: str,
    *,
    limit: int = 10,
    offset: int = 0,
    sort: str = "bestMatch",
    category_ids: Optional[str] = None,
    filter_str: Optional[str] = None,   # <— NEU
) -> Dict[str, Any]:
    ...
    params: Dict[str, Any] = {
        "q": query,
        "limit": max(1, min(limit, 200)),
        "offset": max(0, offset),
        "sort": _map_sort(sort),
    }
    if category_ids:
        params["category_ids"] = category_ids
    if filter_str:                         # <— NEU
        params["filter"] = filter_str
    url = f"{BASE}/buy/browse/v1/item_summary/search"

    hdrs = _headers()

    # 3 Versuche: 401 -> Token erneuern, 429 -> Backoff
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=hdrs, timeout=25)
        except Exception as ex:
            log.warning("eBay Network/Timeout (Try %s/3): %s", attempt + 1, ex)
            time.sleep(1 + attempt)
            continue

        if r.status_code == 401 and attempt == 0:
            log.info("eBay 401: Token wird erneuert…")
            _token_cache.clear()
            hdrs = _headers()
            continue

        if r.status_code == 429:
            wait = 1 + attempt
            log.warning("eBay 429: Rate Limit – Backoff %ss", wait)
            time.sleep(wait)
            continue

        if r.status_code in (403, 404):
            # 403: Policy/Scope; 404: ungültige Query/Filter
            log.error("eBay %s: %s", r.status_code, r.text)
            r.raise_for_status()

        try:
            r.raise_for_status()
        except Exception:
            log.error("eBay HTTP Fehler: %s - %s", r.status_code, r.text)
            raise

        data = r.json() if r.content else {}
        # Affiliate-Link bei Bedarf anhängen
        for it in data.get("itemSummaries", []) or []:
            if it.get("itemWebUrl"):
                it["itemWebUrl"] = _attach_affiliate(it["itemWebUrl"])
        return data

    # Sollte praktisch nie erreicht werden:
    raise RuntimeError("eBay-Suche fehlgeschlagen (max. Retries erreicht)")

