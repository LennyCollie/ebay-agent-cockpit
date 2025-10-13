# services/kleinanzeigen_parser.py
import re
from typing import Dict, Optional

from utils.text import normalize

_RX_URL = re.compile(r"https?://www\.kleinanzeigen\.de/s-anzeige/[^\s<>\"]+", re.I)
_RX_PRICE = re.compile(r"(\d{1,3}(?:[.\s]\d{3})*(?:[.,]\d{2})?)\s*€", re.I)
_RX_ID = re.compile(r"Anzeigenummer[:\s]*([0-9]{6,})", re.I)
_RX_TITLE = re.compile(r'Anzeige\s+"([^"]+)"', re.I)  # Fallback aus Betreff/Text


def is_from_kleinanzeigen(sender) -> bool:
    """Robuster Check für Absender (verträgt dict/list/None)."""
    return "kleinanzeigen" in normalize(sender)


def _norm_price(raw: str) -> Optional[str]:
    if not raw:
        return None
    # 1.234,56 => 1234.56 (intern)
    val = raw.replace(" ", "").replace(".", "").replace(",", ".")
    return val


def extract_summary(subject, text) -> Dict[str, Optional[str]]:
    """Extrahiert Eckdaten aus Betreff/Text (robust gegen None/dicts)."""
    subject = normalize(subject)
    text = normalize(text)

    url = None
    price = None
    ad_id = None
    title = None

    m = _RX_URL.search(subject) or _RX_URL.search(text)
    if m:
        url = m.group(0)

    m = _RX_PRICE.search(subject) or _RX_PRICE.search(text)
    if m:
        price = _norm_price(m.group(1))

    m = _RX_ID.search(subject) or _RX_ID.search(text)
    if m:
        ad_id = m.group(1)

    # Titel zuerst aus Betreff, sonst aus Text
    m = _RX_TITLE.search(subject) or _RX_TITLE.search(text)
    if m:
        title = m.group(1)
    elif subject:
        title = subject.strip()

    return {
        "title": title,
        "price": price,  # "1234.56"
        "url": url,
        "ad_id": ad_id,
    }
