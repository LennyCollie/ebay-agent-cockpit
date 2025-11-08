"""
services/kleinanzeigen.py
POC scraper for ebay-kleinanzeigen.de
Returns normalized item dicts:
{id, title, price, currency, url, img, source}
"""
import time
import random
import logging
import urllib.parse
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
BASE = "https://www.ebay-kleinanzeigen.de"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/117.0 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9",
}


def _fetch(url: str, timeout: int = 15) -> Optional[str]:
    try:
        # politeness: small random delay
        time.sleep(random.uniform(0.4, 1.0))
        r = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.text
    except Exception as e:
        logger.exception("kleinanzeigen: fetch failed for %s: %s", url, e)
        return None


def _parse_price(price_str: str) -> str:
    if not price_str:
        return ""
    s = price_str.strip().replace("\n", " ").replace("\xa0", " ").strip()
    return s


def search_kleinanzeigen(term: str, page: int = 1, per_page: int = 50) -> List[Dict]:
    """
    Perform a basic search and return normalized item list.
    - term: search string (raw)
    - page: page number (1-indexed)
    - per_page: max items to return
    """
    q = urllib.parse.quote_plus(term)
    url = f"{BASE}/s-{q}/k0"
    if page and page > 1:
        url = f"{url}/?page={page}"

    html = _fetch(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    items = []

    # NOTE: selectors are fragile and may need updates if the site changes.
    # Try a few fallback selectors to be robust
    results = (
        soup.select("article.aditem")
        or soup.select("li.ad-listitem")
        or soup.select("article")
        or []
    )

    for el in results[:per_page]:
        try:
            a = el.select_one("a[href]")
            link = a["href"] if a and a.has_attr("href") else None
            if link and link.startswith("/"):
                link = BASE + link

            title_el = (
                el.select_one("a > h2")
                or el.select_one(".aditem-main h2")
                or el.select_one(".ellipsis")
            )
            title = title_el.get_text(strip=True) if title_el else "–"

            price_el = (
                el.select_one(".aditem-main--middle .aditem-main--middle__price")
                or el.select_one(".aditem-price")
                or el.select_one(".aditem-main--middle")
            )
            price = _parse_price(price_el.get_text()) if price_el else "–"

            img_el = el.select_one("img")
            img = None
            if img_el:
                img = img_el.get("src") or img_el.get("data-src") or img_el.get("data-original")

            item_id = link or f"{title}:{price}"

            items.append(
                {
                    "id": f"kleinanzeigen:{item_id}",
                    "title": title,
                    "price": price,
                    "currency": "EUR",
                    "url": link,
                    "img": img,
                    "source": "kleinanzeigen",
                }
            )
        except Exception:
            logger.exception("kleinanzeigen: parse item failed")
            continue

    return items
