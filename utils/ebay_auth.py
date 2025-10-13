# utils/ebay_auth.py
from __future__ import annotations

import os
import time

import requests

_CACHE = {"token": None, "exp": 0}


def get_browse_token() -> str:
    """
    Holt ein eBay Buy/Browse Application Access Token (Client Credentials)
    und cached es bis kurz vor Ablauf.
    ENV:
      EBAY_CLIENT_ID
      EBAY_CLIENT_SECRET
      EBAY_ENV = "production" | "sandbox"  (default production)
    """
    now = time.time()
    if _CACHE["token"] and now < _CACHE["exp"] - 60:
        return _CACHE["token"]

    cid = os.getenv("EBAY_CLIENT_ID", "").strip()
    csec = os.getenv("EBAY_CLIENT_SECRET", "").strip()
    if not cid or not csec:
        raise RuntimeError("EBAY_CLIENT_ID / EBAY_CLIENT_SECRET missing")

    env = (os.getenv("EBAY_ENV") or "production").lower()
    base = (
        "https://api.ebay.com"
        if env == "production"
        else "https://api.sandbox.ebay.com"
    )

    url = f"{base}/identity/v1/oauth2/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "client_credentials",
        "scope": "https://api.ebay.com/oauth/api_scope",
    }
    # Basic Auth mit Client-ID/Secret
    r = requests.post(url, headers=headers, data=data, auth=(cid, csec), timeout=20)
    r.raise_for_status()
    js = r.json()
    tok = js["access_token"]
    exp = int(js.get("expires_in", 7200))  # Sek.
    _CACHE["token"] = tok
    _CACHE["exp"] = now + exp
    return tok
