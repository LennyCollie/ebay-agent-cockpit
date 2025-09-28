import re
from html import unescape
from typing import Optional

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def safe_str(x: Optional[object]) -> str:
    """None-sicher in String wandeln."""
    return "" if x is None else str(x)


def strip_html(s: Optional[str]) -> str:
    """HTML-Tags entfernen & Entities decodieren."""
    s = safe_str(s)
    s = _TAG_RE.sub("", s)
    return unescape(s)


def normalize_ws(s: Optional[str]) -> str:
    """Whitespace normalisieren (Zeilenumbrüche/Mehrfach-Spaces)."""
    return _WS_RE.sub(" ", safe_str(s)).strip()


def shorten(s: Optional[str], max_len: int = 120, ellipsis: str = "…") -> str:
    """
    Auf max_len kürzen – versucht an Wortgrenze zu schneiden.
    """
    s = normalize_ws(strip_html(s))
    if len(s) <= max_len:
        return s
    cut = s.rfind(" ", 0, max_len - len(ellipsis))
    if cut == -1:
        cut = max_len - len(ellipsis)
    return s[:cut].rstrip() + ellipsis


def price_eur(value: Optional[float]) -> str:
    """Sehr einfache EUR-Formatierung (lokal unabhängig)."""
    try:
        return f"{float(value):.2f} €"
    except Exception:
        return safe_str(value)
