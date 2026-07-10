"""
Robuster Kleinanzeigen-HTML-Scraper.

Die Datei sucht direkt auf der öffentlichen Kleinanzeigen-Suchergebnisseite,
erkennt mehrere mögliche HTML-Strukturen und normalisiert die Angebote in ein
einheitliches Dictionary-Format.

Wichtig:
- Keine Abhängigkeit von app.py
- Keine erzwungene Brotli-Komprimierung
- Keine aggressive JavaScript-Blockerkennung
- HTTP 200 wird nicht automatisch als erfolgreiche Suche gewertet
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


logger = logging.getLogger(__name__)

BASE_URL = "https://www.kleinanzeigen.de"
SEARCH_URL = f"{BASE_URL}/s-suchanfrage.html"

DEFAULT_TIMEOUT = int(os.getenv("KLEINANZEIGEN_TIMEOUT", "20"))

DEBUG_HTML = os.getenv(
    "KLEINANZEIGEN_DEBUG_HTML",
    "0",
).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


# =============================================================================
# ABHÄNGIGKEITEN
# =============================================================================
def check_dependencies() -> bool:
    """Prüft, ob die benötigten Pakete installiert sind."""
    try:
        import requests as _requests  # noqa: F401
        from bs4 import BeautifulSoup as _BeautifulSoup  # noqa: F401

        return True

    except ImportError as exc:
        logger.error(
            "Dependencies fehlen: %s. "
            "Bitte installieren: pip install requests beautifulsoup4",
            exc,
        )
        return False


# =============================================================================
# HTTP-SESSION
# =============================================================================
def _create_session() -> requests.Session:
    """Erstellt eine HTTP-Session mit wenigen Wiederholungsversuchen."""

    retry_config = Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )

    adapter = HTTPAdapter(
        max_retries=retry_config,
        pool_connections=5,
        pool_maxsize=10,
    )

    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/138.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "DNT": "1",
            "Upgrade-Insecure-Requests": "1",
        }
    )

    return session


# =============================================================================
# ÖFFENTLICHE SUCHFUNKTION
# =============================================================================
def search_kleinanzeigen(
    query: str,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    location: Optional[str] = None,
    radius_km: Optional[int] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Sucht Angebote auf Kleinanzeigen.

    Args:
        query:
            Suchbegriff.
        price_min:
            Optionaler Mindestpreis.
        price_max:
            Optionaler Höchstpreis.
        location:
            Optionaler Ort oder eine fünfstellige Postleitzahl.
        radius_km:
            Optionaler Suchradius.
        limit:
            Maximale Anzahl zurückgegebener Angebote.

    Returns:
        Liste normalisierter Angebots-Dictionaries.
    """

    clean_query = str(query or "").strip()

    if not clean_query:
        logger.warning("Kleinanzeigen-Suche ohne Suchbegriff abgebrochen.")
        return []

    try:
        safe_limit = max(1, min(int(limit or 50), 100))
    except (TypeError, ValueError):
        safe_limit = 50

    url = _build_search_url(
        query=clean_query,
        price_min=price_min,
        price_max=price_max,
        location=location,
        radius_km=radius_km,
    )

    print()
    print("=" * 60)
    print("[*] KLEINANZEIGEN HTML SCRAPING")
    print("=" * 60)
    print(f"URL: {url}")
    print(f"Query: {clean_query}")
    print("=" * 60)

    session = _create_session()

    try:
        response = session.get(
            url,
            timeout=DEFAULT_TIMEOUT,
            allow_redirects=True,
        )

        response.raise_for_status()

        # Kleinanzeigen liefert UTF-8, teilweise aber ohne eindeutige
        # Charset-Angabe im Content-Type. requests nimmt dann Latin-1 an.
        response.encoding = "utf-8"

        content_type = response.headers.get("Content-Type", "")
        html = response.text or ""

        print(f"[OK] Status: {response.status_code}")
        print(f"[DEBUG] Final URL: {response.url}")
        print(f"[DEBUG] Content-Type: {content_type}")
        print(f"[DEBUG] HTML-Länge: {len(html)}")

        if "text/html" not in content_type.lower():
            logger.warning(
                "Kleinanzeigen lieferte keinen HTML-Inhalt: %s",
                content_type,
            )
            return []

        if not html.strip():
            logger.warning("Kleinanzeigen lieferte eine leere HTML-Seite.")
            return []

        if DEBUG_HTML:
            _write_debug_html(html)

        soup = BeautifulSoup(html, "html.parser")

        page_title = (
            soup.title.get_text(" ", strip=True)
            if soup.title
            else ""
        )

        print(f"[DEBUG] Seitentitel: {page_title}")

        offer_links = soup.select('a[href*="/s-anzeige/"]')

        block_reason = _detect_real_block_page(
            soup=soup,
            html=html,
            offer_link_count=len(offer_links),
        )

        if block_reason:
            logger.warning(
                "Kleinanzeigen Block-/Fehlerseite erkannt: %s; URL=%s",
                block_reason,
                response.url,
            )

            print(
                "[WARNUNG] Kleinanzeigen Block-/Fehlerseite erkannt: "
                f"{block_reason}"
            )
            return []

        article_nodes = _find_article_nodes(soup)

        print(
            "[+] Gefundene Artikel-Container: "
            f"{len(article_nodes)}"
        )

        results: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()

        for article in article_nodes:
            if len(results) >= safe_limit:
                break

            try:
                item = _parse_html_article(
                    article=article,
                    query=clean_query,
                )

            except Exception:
                logger.exception(
                    "Unerwarteter Fehler beim Parsen eines Artikels."
                )
                continue

            if not item:
                continue

            item_id = str(item.get("item_id") or "").strip()

            if not item_id:
                continue

            if item_id in seen_ids:
                continue

            if not _matches_price_filter(
                item=item,
                price_min=price_min,
                price_max=price_max,
            ):
                continue

            seen_ids.add(item_id)
            results.append(item)

            if len(results) <= 3:
                print(f"[+] Item {len(results)}:")
                print(f"    Title: {item['title'][:80]}")
                print(f"    Price: {item.get('price', 'N/A')}")
                print(f"    URL: {item['url'][:100]}...")

        if not article_nodes:
            logger.warning(
                "HTTP 200, aber keine Anzeigenstruktur erkannt. "
                "Seitentitel=%r, HTML-Länge=%d, Final-URL=%s",
                page_title,
                len(html),
                response.url,
            )

            print(
                "[WARNUNG] HTTP 200, aber keine Anzeigenstruktur erkannt."
            )
            print(
                "[WARNUNG] Möglicherweise wurde die HTML-Struktur geändert."
            )
            print(f"[DEBUG] Anzeigenlinks im HTML: {len(offer_links)}")
            print(f"[DEBUG] HTML-Anfang: {html[:600]!r}")

        elif article_nodes and not results:
            logger.warning(
                "%d mögliche Anzeigen-Container gefunden, "
                "aber kein vollständiger Artikel konnte geparst werden.",
                len(article_nodes),
            )

            print(
                "[WARNUNG] Anzeigen-Container vorhanden, "
                "aber keine vollständigen Angebote geparst."
            )

        print(f"[OK] Gefunden: {len(results)} Kleinanzeigen")
        print()

        return results

    except requests.Timeout:
        logger.error(
            "Kleinanzeigen-Anfrage nach %s Sekunden abgebrochen.",
            DEFAULT_TIMEOUT,
        )
        return []

    except requests.RequestException as exc:
        status_code = getattr(exc.response, "status_code", None)
        response_text = getattr(exc.response, "text", "") or ""

        logger.error(
            "Kleinanzeigen HTTP-Fehler: status=%s, fehler=%s, antwort=%r",
            status_code,
            exc,
            response_text[:500],
        )
        return []

    except Exception:
        logger.exception(
            "Unerwarteter Fehler bei der Kleinanzeigen-Suche."
        )
        return []

    finally:
        session.close()


# =============================================================================
# URL-ERSTELLUNG
# =============================================================================
def _build_search_url(
    query: str,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    location: Optional[str] = None,
    radius_km: Optional[int] = None,
) -> str:
    """Erstellt die Kleinanzeigen-Suchadresse."""

    params: Dict[str, Any] = {
        "keywords": query,
        "sortingField": "SORTING_DATE",
    }

    if price_min is not None or price_max is not None:
        params["priceType"] = "FIXED"

    if price_min is not None:
        try:
            params["minPrice"] = max(0, int(float(price_min)))
        except (TypeError, ValueError):
            pass

    if price_max is not None:
        try:
            params["maxPrice"] = max(0, int(float(price_max)))
        except (TypeError, ValueError):
            pass

    postal_code = _extract_postal_code(location)

    if postal_code:
        params["locationStr"] = postal_code

        if radius_km is not None:
            try:
                params["radius"] = max(
                    0,
                    min(int(radius_km), 500),
                )
            except (TypeError, ValueError):
                pass

    return f"{SEARCH_URL}?{urlencode(params)}"


# =============================================================================
# BLOCK-/FEHLERSEITEN ERKENNEN
# =============================================================================
def _detect_real_block_page(
    soup: BeautifulSoup,
    html: str,
    offer_link_count: int,
) -> Optional[str]:
    """
    Erkennt nur eindeutige Block- oder Fehlerseiten.

    Allgemeine Hinweise wie „JavaScript aktivieren“ werden nicht mehr
    automatisch als Blockierung gewertet, da diese auch auf normalen
    Suchseiten vorkommen können.
    """

    if offer_link_count > 0:
        return None

    page_title = (
        soup.title.get_text(" ", strip=True).lower()
        if soup.title
        else ""
    )

    visible_text = soup.get_text(
        " ",
        strip=True,
    ).lower()

    strong_title_markers = (
        "access denied",
        "zugriff verweigert",
        "forbidden",
        "service unavailable",
        "robot verification",
        "sicherheitsüberprüfung",
    )

    for marker in strong_title_markers:
        if marker in page_title:
            return marker

    strong_text_markers = (
        "ungewöhnlicher datenverkehr wurde erkannt",
        "automatisierte zugriffe wurden erkannt",
        "ihre anfrage wurde blockiert",
        "your request has been blocked",
        "verify you are human",
        "bitte bestätigen sie, dass sie kein roboter sind",
    )

    for marker in strong_text_markers:
        if marker in visible_text:
            return marker

    html_lower = html.lower()

    technical_markers = (
        "cf-chl-",
        "challenge-platform",
        "cloudflare ray id",
    )

    for marker in technical_markers:
        if marker in html_lower:
            return marker

    return None


# =============================================================================
# ANZEIGEN-CONTAINER FINDEN
# =============================================================================
def _find_article_nodes(
    soup: BeautifulSoup,
) -> List[Tag]:
    """
    Findet Anzeigenkarten über mehrere bekannte Strukturen.

    Falls keine passende Kartenklasse existiert, werden Links mit
    /s-anzeige/ gesucht und sinnvolle Eltern-Container verwendet.
    """

    selectors = (
        "article.aditem",
        "article[data-adid]",
        "article[data-testid]",
        "li.ad-listitem",
        "div.ad-listitem",
        "[data-adid]",
        '[data-testid*="ad"]',
    )

    for selector in selectors:
        nodes: List[Tag] = []

        for node in soup.select(selector):
            if not isinstance(node, Tag):
                continue

            if not node.select_one('a[href*="/s-anzeige/"]'):
                continue

            nodes.append(node)

        nodes = _dedupe_tags(nodes)

        if nodes:
            print(
                f"[DEBUG] Artikel-Selektor: {selector} "
                f"({len(nodes)} Treffer)"
            )
            return nodes

    fallback_nodes: List[Tag] = []

    for link in soup.select('a[href*="/s-anzeige/"]'):
        if not isinstance(link, Tag):
            continue

        container = (
            link.find_parent("article")
            or link.find_parent("li")
            or _find_reasonable_parent_div(link)
            or link
        )

        if isinstance(container, Tag):
            fallback_nodes.append(container)

    fallback_nodes = _dedupe_tags(fallback_nodes)

    if fallback_nodes:
        print(
            "[DEBUG] Anzeigenlink-Fallback: "
            f"{len(fallback_nodes)} mögliche Artikel"
        )

    return fallback_nodes


def _find_reasonable_parent_div(
    link: Tag,
) -> Optional[Tag]:
    """Sucht einen sinnvollen DIV-Elterncontainer."""

    current = link.parent
    depth = 0

    while isinstance(current, Tag) and depth < 6:
        if current.name == "div":
            text = current.get_text(
                " ",
                strip=True,
            )

            text_length = len(text)

            if 10 <= text_length <= 3000:
                return current

        current = current.parent
        depth += 1

    return None


def _dedupe_tags(
    nodes: List[Tag],
) -> List[Tag]:
    """Entfernt doppelte HTML-Knoten."""

    output: List[Tag] = []
    seen: set[int] = set()

    for node in nodes:
        node_key = id(node)

        if node_key in seen:
            continue

        seen.add(node_key)
        output.append(node)

    return output


# =============================================================================
# EINZELNE ANZEIGE PARSEN
# =============================================================================
def _parse_html_article(
    article: Tag,
    query: str,
) -> Optional[Dict[str, Any]]:
    """Parst einen einzelnen Anzeigencontainer."""

    link = _find_offer_link(article)

    if not link:
        return None

    raw_url = (
        link.get("href")
        or link.get("data-href")
        or ""
    )

    relative_url = str(raw_url).strip()

    if not relative_url:
        return None

    url = urljoin(
        BASE_URL,
        relative_url,
    )

    if "/s-anzeige/" not in url:
        return None

    title = _extract_title(
        article=article,
        link=link,
    )

    if not title:
        return None

    price = _extract_article_price(article)
    image_url = _extract_image_url(article)
    location = _extract_location(article)
    postal_code = _extract_postal_code(location)
    published_date = _extract_published_date(article)
    item_id = _generate_item_id(url)
    condition = _detect_condition(title)

    return {
        "id": item_id,
        "item_id": item_id,
        "title": title[:500],
        "price": price,
        "url": url,
        "image_url": image_url,
        "img": image_url,
        "location": location,
        "postal_code": postal_code,
        "condition": condition,
        "description": title,
        "published_date": published_date,
        "source": "kleinanzeigen",
        "src": "kleinanzeigen",
        "term": query,
    }


def _find_offer_link(
    article: Tag,
) -> Optional[Tag]:
    """Findet bevorzugt den echten Titellink einer Anzeige."""

    preferred_selectors = (
        "h2 a[href*='/s-anzeige/']",
        "h3 a[href*='/s-anzeige/']",
        "a.ellipsis[href*='/s-anzeige/']",
        "[class*='title'] a[href*='/s-anzeige/']",
        "[data-testid*='title'] a[href*='/s-anzeige/']",
    )

    for selector in preferred_selectors:
        link = article.select_one(selector)

        if isinstance(link, Tag):
            return link

    # Fallback: Nur Links mit brauchbarem Text verwenden.
    for link in article.select('a[href*="/s-anzeige/"]'):
        if not isinstance(link, Tag):
            continue

        text = _clean_text(
            link.get("title")
            or link.get("aria-label")
            or link.get_text(" ", strip=True)
        )

        if text and not text.isdigit() and len(text) >= 4:
            return link

    return None


def _extract_title(
    article: Tag,
    link: Tag,
) -> Optional[str]:
    """Extrahiert einen plausiblen Angebotstitel."""

    title_nodes = (
        article.select_one("h2"),
        article.select_one("h3"),
        article.select_one("[class*='title']"),
        article.select_one("[data-testid*='title']"),
    )

    for node in title_nodes:
        if not isinstance(node, Tag):
            continue

        title = _clean_text(node.get_text(" ", strip=True))

        if title and not title.isdigit() and len(title) >= 4:
            return title

    candidates = (
        link.get("title"),
        link.get("aria-label"),
        link.get_text(" ", strip=True),
    )

    for candidate in candidates:
        title = _clean_text(candidate)

        if title and not title.isdigit() and len(title) >= 4:
            return title

    return None


def _extract_article_price(
    article: Tag,
) -> Optional[float]:
    """Extrahiert den Preis aus einer Anzeigenkarte."""

    selectors = (
        ".aditem-main--middle--price-shipping--price",
        ".aditem-main--middle--price",
        '[class*="price"]',
        '[data-testid*="price"]',
    )

    for selector in selectors:
        price_node = article.select_one(selector)

        if not isinstance(price_node, Tag):
            continue

        price_text = price_node.get_text(
            " ",
            strip=True,
        )

        parsed_price = _extract_price(price_text)

        if parsed_price is not None:
            return parsed_price

        if _is_free_offer(price_text):
            return 0.0

    complete_text = article.get_text(
        " ",
        strip=True,
    )

    if _is_free_offer(complete_text):
        return 0.0

    return _extract_price(complete_text)


def _extract_image_url(
    article: Tag,
) -> Optional[str]:
    """Extrahiert eine mögliche Bild-URL."""

    image = article.select_one("img")

    if not isinstance(image, Tag):
        return None

    candidates = (
        image.get("src"),
        image.get("data-src"),
        image.get("data-imgsrc"),
        image.get("data-lazy-src"),
        image.get("data-original"),
    )

    for candidate in candidates:
        normalized = _normalize_image_url(candidate)

        if normalized:
            return normalized

    srcset = (
        image.get("srcset")
        or image.get("data-srcset")
    )

    if srcset:
        parts = [
            part.strip().split(" ")[0]
            for part in str(srcset).split(",")
            if part.strip()
        ]

        if parts:
            normalized = _normalize_image_url(parts[-1])

            if normalized:
                return normalized

    return None


def _normalize_image_url(
    value: Any,
) -> Optional[str]:
    """Bereinigt eine Bild-URL."""

    if not value:
        return None

    image_url = str(value).strip()

    if not image_url:
        return None

    if image_url.startswith("data:"):
        return None

    if image_url.startswith("//"):
        return f"https:{image_url}"

    return urljoin(
        BASE_URL,
        image_url,
    )


def _extract_location(
    article: Tag,
) -> Optional[str]:
    """Extrahiert Ort und PLZ."""

    selectors = (
        ".aditem-main--top--left",
        ".aditem-details",
        '[class*="location"]',
        '[data-testid*="location"]',
    )

    for selector in selectors:
        node = article.select_one(selector)

        if not isinstance(node, Tag):
            continue

        text = _clean_text(
            node.get_text(
                " ",
                strip=True,
            )
        )

        if text:
            return text[:200]

    complete_text = _clean_text(
        article.get_text(
            " ",
            strip=True,
        )
    )

    match = re.search(
        r"\b\d{5}\s+"
        r"[A-Za-zÄÖÜäöüß]"
        r"[A-Za-zÄÖÜäöüß .\-/]{1,60}",
        complete_text,
    )

    if match:
        return match.group(0).strip()[:200]

    return None


def _extract_published_date(
    article: Tag,
) -> Optional[datetime]:
    """Liest ein maschinenlesbares Veröffentlichungsdatum."""

    time_node = article.select_one("time")

    if not isinstance(time_node, Tag):
        return None

    raw_value = str(
        time_node.get("datetime")
        or time_node.get("title")
        or ""
    ).strip()

    if not raw_value:
        return None

    try:
        return datetime.fromisoformat(
            raw_value.replace(
                "Z",
                "+00:00",
            )
        )

    except ValueError:
        return None


# =============================================================================
# PREIS UND TEXTE
# =============================================================================
def _extract_price(
    text: str,
) -> Optional[float]:
    """Extrahiert einen Europreis."""

    if not text:
        return None

    normalized = (
        str(text)
        .replace("\xa0", " ")
        .replace("EUR", "€")
    )

    patterns = (
        r"(\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?)\s*€",
        r"(\d+(?:,\d{1,2})?)\s*€",
    )

    for pattern in patterns:
        match = re.search(
            pattern,
            normalized,
        )

        if not match:
            continue

        raw_price = (
            match.group(1)
            .replace(".", "")
            .replace(",", ".")
        )

        try:
            return float(raw_price)

        except ValueError:
            continue

    return None


def _is_free_offer(
    text: str,
) -> bool:
    """Erkennt kostenlose Angebote."""

    normalized = str(
        text or ""
    ).strip().lower()

    markers = (
        "zu verschenken",
        "kostenlos",
        "gratis",
    )

    return any(
        marker in normalized
        for marker in markers
    )


def _extract_postal_code(
    value: Optional[str],
) -> Optional[str]:
    """Extrahiert eine fünfstellige Postleitzahl."""

    if not value:
        return None

    match = re.search(
        r"\b(\d{5})\b",
        str(value),
    )

    if match:
        return match.group(1)

    return None


def _detect_condition(
    title: str,
) -> str:
    """Leitet grob den Artikelzustand aus dem Titel ab."""

    normalized = str(
        title or ""
    ).lower()

    new_markers = (
        "neu",
        "ovp",
        "originalverpackt",
        "unbenutzt",
        "ungeöffnet",
        "versiegelt",
    )

    if any(
        marker in normalized
        for marker in new_markers
    ):
        return "Neu"

    return "Gebraucht"


def _generate_item_id(
    url: str,
) -> str:
    """Generiert eine stabile Artikel-ID."""

    parsed_url = urlparse(url)
    path = parsed_url.path or ""

    match = re.search(
        r"/(\d{7,})(?:-\d+)+/?$",
        path,
    )

    if match:
        return f"ka_{match.group(1)}"

    number_candidates = re.findall(
        r"\d{7,}",
        path,
    )

    if number_candidates:
        return f"ka_{number_candidates[-1]}"

    normalized_url = (
        f"{parsed_url.netloc}{parsed_url.path}"
        .lower()
    )

    digest = hashlib.sha256(
        normalized_url.encode("utf-8")
    ).hexdigest()[:16]

    return f"ka_{digest}"


def _matches_price_filter(
    item: Dict[str, Any],
    price_min: Optional[float],
    price_max: Optional[float],
) -> bool:
    """Prüft die Preisgrenzen."""

    price = item.get("price")

    if price is None:
        return True

    try:
        numeric_price = float(price)

    except (TypeError, ValueError):
        return True

    if price_min is not None:
        try:
            if numeric_price < float(price_min):
                return False
        except (TypeError, ValueError):
            pass

    if price_max is not None:
        try:
            if numeric_price > float(price_max):
                return False
        except (TypeError, ValueError):
            pass

    return True


def _clean_text(
    value: Any,
) -> str:
    """Entfernt überflüssige Leerzeichen."""

    if value is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value),
    ).strip()


# =============================================================================
# DEBUG-DATEI
# =============================================================================
def _write_debug_html(
    html: str,
) -> None:
    """Schreibt optional die empfangene HTML-Seite in eine Datei."""

    filename = "kleinanzeigen_debug.html"

    try:
        with open(
            filename,
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write(html)

        print(f"[DEBUG] HTML gespeichert: {filename}")

    except OSError as exc:
        logger.warning(
            "Debug-HTML konnte nicht gespeichert werden: %s",
            exc,
        )


# =============================================================================
# LOKALER TEST
# =============================================================================
def test_search() -> None:
    """Führt einen lokalen Funktionstest aus."""

    print("=" * 60)
    print("KLEINANZEIGEN HTML SCRAPER TEST")
    print("=" * 60)

    if not check_dependencies():
        print("[!] Dependencies fehlen.")
        return

    print("[OK] Dependencies verfügbar.")

    results = search_kleinanzeigen(
        query="Wohnwagen",
        limit=10,
    )

    print(f"[TEST] Ergebnisanzahl: {len(results)}")

    for index, item in enumerate(
        results[:5],
        1,
    ):
        if isinstance(
            item.get("price"),
            (int, float),
        ):
            price_text = f"{item['price']:.2f} EUR"
        else:
            price_text = "Preis auf Anfrage"

        print()
        print(f"{index}. {item['title'][:80]}")
        print(f"   Preis: {price_text}")
        print(f"   Ort: {item.get('location') or '–'}")
        print(f"   ID: {item['item_id']}")
        print(f"   URL: {item['url']}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_search()
