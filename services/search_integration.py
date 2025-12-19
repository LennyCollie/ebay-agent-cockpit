"""
search_integration.py – Aggregation externer Marktplätze (Kleinanzeigen, Quoka, Shpock, Markt.de)
mit einfacher Duplikat-Erkennung und Filter gegen offensichtliche Dummy-/Navigations-Einträge.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# ⭐ FILTER-FUNKTION - Entfernt Dummy-Daten / Navigation
# =============================================================================

def filter_invalid_listings(
    items: List[Dict] | None,
    term: str | None = None,
    source: str = "unknown",
) -> List[Dict]:
    """
    Entfernt Navigation, System-Texte und offensichtliche Dummy-Daten.

    - BLACKLIST auf Titel-Ebene (z.B. "Zuhause", "KleinanzeigenPostfachmehr", "Finde alles, was du suchst", ...)
    - zu kurze/unsinnige Titel werden entfernt
    - wenn ein Suchbegriff (term) übergeben wird, muss mindestens eines der Keywords
      im Titel oder der Beschreibung vorkommen
    """

    if not items:
        return []

    source = (source or "unknown").lower()

    # BLACKLIST: Exakte Matches (case-insensitive)
    blacklist_exact = {
        "zuhause",
        "startseite",
        "home",
        "suchen",
        "search",
        "anmelden",
        "registrieren",
        "login",
        "register",
        "sign in",
        "mein konto",
        "mein profil",
        "profil",
        "einstellungen",
        "settings",
        "hilfe",
        "help",
        "kontakt",
        "contact",
        "impressum",
        "imprint",
        "agb",
        "terms",
        "datenschutz",
        "privacy",
        "kategorien",
        "categories",
        "postfach",
        "inbox",
        "nachrichten",
        "messages",
        "favoriten",
        "favorites",
        "merkliste",
        "wishlist",
        "warenkorb",
        "cart",
        "kleinanzeigen",
    }

    # BLACKLIST: Substring-Matches für kurze Titel (Navigation, Marketing-Boxen, usw.)
    blacklist_contains = [
        "finde alles",
        "was du suchst",
        "kleinanzeigenpostfach",
        "durchsuchen",
        "entdecken",
        "mehr anzeigen",
        "alle anzeigen",
        "weitere anzeigen",
        "weitere artikel",
        "app herunterladen",
        "jetzt verkaufen",
        "anzeige aufgeben",
        "kostenlos inserieren",
    ]

    # Keywords aus dem Suchbegriff extrahieren
    keywords: List[str] = []
    if term and source not in ("quoka", "shpock", "marktde", "kleinanzeigen"):
        keywords = [
            t.lower()
            for t in re.split(r"\s+", term)
            if len(t.strip()) >= 3
        ]

    filtered: List[Dict] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        title = (item.get("title") or "").strip()
        desc = (item.get("description") or "").strip()

        # [!] Skip: Leere oder extrem kurze Titel
        if not title or len(title) < 5:
            continue

        title_lower = title.lower()
        fulltext_lower = f"{title} {desc}".lower()

        # [!] Skip: Exakte Blacklist-Matches
        if title_lower in blacklist_exact:
            continue

        # [!] Skip: Substring-Matches in kurzen Titeln (typisch Navigation / Teaser)
        is_blacklisted = False
        for word in blacklist_contains:
            if word in title_lower and len(title) < 40:
                is_blacklisted = True
                break
        if is_blacklisted:
            continue

        # [!] Skip: Titel besteht nur aus einem Wort (meist Navigation / Rubrik)
        if len(title.split()) < 2:
            continue

        # [!] Skip: Passt überhaupt nicht zum Suchbegriff (falls term mitgegeben)
        # (für alle Quellen gleich – Navigation wie "Zuhause" fliegt dadurch zusätzlich raus)
        if keywords:
            if not any(kw in fulltext_lower for kw in keywords):
                continue

        # [OK] Item scheint sinnvoll
        filtered.append(item)

    return filtered


# =============================================================================
# ⭐ HAUPT-FUNKTION - Mergt alle Marktplätze
# =============================================================================

def merge_all_marketplaces(
    term: str,
    current_results: Optional[List[Dict]] = None,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    location: Optional[str] = None,
    max_per_source: int = 20,
    verbose: bool = True,
    active_sources: Optional[List[str]] = None,
) -> List[Dict]:
    """
    Durchsucht alle Marktplätze und merged die Ergebnisse.

    - term: Suchbegriff (wird an die Scraper weitergereicht)
    - current_results: bereits vorhandene Items (z.B. eBay)
    - price_min / price_max: optionale Preisfilter
    - location: aktuell PLZ/Ort, falls die Scraper das unterstützen
    - max_per_source: Limit pro Quelle
    - active_sources: Liste gewünschter Quellen, z.B. ["kleinanzeigen", "quoka"].
                      None = alle bekannten Quellen.
    """

    # ------------------------------------------------------------------
    # Welche Quellen sollen überhaupt angefragt werden?
    # ------------------------------------------------------------------
    if active_sources is None:
        active_set = {"kleinanzeigen", "quoka", "shpock", "marktde"}
    else:
        active_set = {s.lower() for s in active_sources}

    # ------------------------------------------------------------------
    # Scraper dynamisch importieren (wo vorhanden)
    # ------------------------------------------------------------------
    # Kleinanzeigen
    try:
        from services.kleinanzeigen import search_kleinanzeigen
    except ImportError:
        logger.error("Kleinanzeigen-Modul nicht gefunden!")
        search_kleinanzeigen = None  # type: ignore

    # Quoka
    search_quoka = None
    for mod in ("scrapers.quoka_scraper", "services.quoka_scraper", "quoka_scraper"):
        if search_quoka:
            break
        try:
            _m = __import__(mod, fromlist=["search_quoka"])
            search_quoka = getattr(_m, "search_quoka", None)
        except ImportError:
            continue
    if not search_quoka:
        logger.warning("Quoka-Scraper nicht gefunden")

    # Shpock
    search_shpock = None
    for mod in ("scrapers.shpock_scraper", "services.shpock_scraper", "shpock_scraper"):
        if search_shpock:
            break
        try:
            _m = __import__(mod, fromlist=["search_shpock"])
            search_shpock = getattr(_m, "search_shpock", None)
        except ImportError:
            continue
    if not search_shpock:
        logger.warning("Shpock-Scraper nicht gefunden")

    # Markt.de
    search_marktde = None
    for mod in ("scrapers.marktde_scraper", "services.marktde_scraper", "marktde_scraper"):
        if search_marktde:
            break
        try:
            _m = __import__(mod, fromlist=["search_marktde"])
            search_marktde = getattr(_m, "search_marktde", None)
        except ImportError:
            continue
    if not search_marktde:
        logger.warning("Markt.de-Scraper nicht gefunden")

    # ------------------------------------------------------------------
    # Initiale Liste + bekannte URLs (für Dedup)
    # ------------------------------------------------------------------
    all_items: List[Dict] = list(current_results) if current_results else []
    seen_urls = {item.get("url") for item in all_items if item.get("url")}

    # Helper für Logging
    def _log_added(src_name: str, added: int) -> None:
        if not verbose:
            return
        if added > 0:
            logger.info("  └─ %s: +%d unique results", src_name, added)
        else:
            logger.info("  └─ %s: 0 results", src_name)

    # =============================================================================
    # 1️⃣ KLEINANZEIGEN
    # =============================================================================
    if search_kleinanzeigen and "kleinanzeigen" in active_set:
        if verbose:
            logger.info("[*] Fetching Kleinanzeigen for: %s", term)

        try:
            ka_items = search_kleinanzeigen(
                query=term,
                price_min=price_min,
                price_max=price_max,
                location=location,
            ) or []

            # sicherstellen, dass 'source' gesetzt ist
            for it in ka_items:
                if isinstance(it, dict):
                    it.setdefault("source", "kleinanzeigen")

            # Filter Navigation / irrelevante Ergebnisse
            ka_items = filter_invalid_listings(ka_items, term=term, source="kleinanzeigen")

            unique_count = 0
            for item in ka_items[:max_per_source]:
                url = item.get("url")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_items.append(_normalize_marketplace_item(item, term))
                    unique_count += 1

            _log_added("Kleinanzeigen", unique_count)

        except Exception as e:
            logger.error("Kleinanzeigen error: %s", e)

    # =============================================================================
    # 2️⃣ QUOKA
    # =============================================================================
    if search_quoka and "quoka" in active_set:
        if verbose:
            logger.info("[*] Fetching Quoka for: %s", term)

        try:
            quoka_items = search_quoka(
                query=term,
                price_min=price_min,
                price_max=price_max,
                location=location,
            ) or []

            for it in quoka_items:
                if isinstance(it, dict):
                    it.setdefault("source", "quoka")

            quoka_items = filter_invalid_listings(quoka_items, term=term, source="quoka")

            unique_count = 0
            for item in quoka_items[:max_per_source]:
                url = item.get("url")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_items.append(_normalize_marketplace_item(item, term))
                    unique_count += 1

            _log_added("Quoka", unique_count)

        except Exception as e:
            logger.error("Quoka error: %s", e)

    # =============================================================================
    # 3️⃣ SHPOCK
    # =============================================================================
    if search_shpock and "shpock" in active_set:
        if verbose:
            logger.info("[*] Fetching Shpock for: %s", term)

        try:
            shpock_items = search_shpock(
                query=term,
                price_min=price_min,
                price_max=price_max,
                location=location,
            ) or []

            for it in shpock_items:
                if isinstance(it, dict):
                    it.setdefault("source", "shpock")

            shpock_items = filter_invalid_listings(shpock_items, term=term, source="shpock")

            unique_count = 0
            for item in shpock_items[:max_per_source]:
                url = item.get("url")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_items.append(_normalize_marketplace_item(item, term))
                    unique_count += 1

            _log_added("Shpock", unique_count)

        except Exception as e:
            logger.error("Shpock error: %s", e)

    # =============================================================================
    # 4️⃣ MARKT.DE
    # =============================================================================
    if search_marktde and "marktde" in active_set:
        if verbose:
            logger.info("[*] Fetching Markt.de for: %s", term)

        try:
            marktde_items = search_marktde(
                query=term,
                price_min=price_min,
                price_max=price_max,
                location=location,
            ) or []

            for it in marktde_items:
                if isinstance(it, dict):
                    it.setdefault("source", "marktde")

            marktde_items = filter_invalid_listings(marktde_items, term=term, source="marktde")

            unique_count = 0
            for item in marktde_items[:max_per_source]:
                url = item.get("url")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_items.append(_normalize_marketplace_item(item, term))
                    unique_count += 1

            _log_added("Markt.de", unique_count)

        except Exception as e:
            logger.error("Markt.de error: %s", e)

    return all_items


# =============================================================================
# HILFS-FUNKTIONEN
# =============================================================================

def _guess_source_from_url(url: str | None) -> str:
    """
    Fallback: Quelle aus der Domain erraten, falls im Item selbst kein "source" steht.
    """
    if not url:
        return "unknown"
    u = url.lower()
    if "kleinanzeigen.de" in u:
        return "kleinanzeigen"
    if "quoka.de" in u:
        return "quoka"
    if "shpock.com" in u:
        return "shpock"
    if "//markt.de" in u or ".markt.de/" in u:
        return "marktde"
    if "ebay." in u:
        return "ebay"
    if "amazon." in u:
        return "amazon"
    return "unknown"


def _normalize_marketplace_item(item: Dict, term: str) -> Dict:
    """
    Konvertiert Marketplace-Item zum Standard-Format des Frontends.
    """
    raw_src = (item.get("source") or item.get("src") or "").lower()
    if not raw_src or raw_src == "unknown":
        raw_src = _guess_source_from_url(item.get("url"))

    return {
        "title": item.get("title", "Ohne Titel"),
        "price": (
            f"{item.get('price', 0):.2f} EUR"
            if item.get("price") is not None
            else "Preis auf Anfrage"
        ),
        "url": item.get("url", "#"),
        "img": item.get("image_url", ""),
        "images": [item.get("image_url")] if item.get("image_url") else [],
        "location": item.get("location", ""),
        "postal_code": item.get("postal_code", ""),
        "description": item.get("description", ""),
        "condition": item.get("condition", "Gebraucht"),
        "published_date": item.get("published_date"),
        "source": raw_src,   # fürs Backend / Filter
        "src": raw_src,      # fürs Template-Badge (ebay/kleinanzeigen/quoka/...)
        "item_id": item.get("item_id") or item.get("id"),
        "term": term,
        "verdict": "unknown",
        "score": None,
    }


def _deduplicate_and_merge(
    current_results: List[Dict],
    new_items: List[Dict],
    source: str = "test",
    max_per_source: int = 50,
    verbose: bool = True,
) -> List[Dict]:
    """
    Einfache Dedup-Funktion für Tests.

    - current_results: bestehende Liste von Items (z.B. von eBay)
    - new_items: neue Items eines Marktplatzes (bereits normalisiert)
    - source: Name des Marktplatzes (für Logging)
    - max_per_source: Limit pro Quelle
    """
    seen_urls = {it.get("url") for it in current_results if it.get("url")}

    unique_count = 0
    for item in new_items[:max_per_source]:
        url = item.get("url")
        if not url or url in seen_urls:
            continue

        seen_urls.add(url)
        current_results.append(item)
        unique_count += 1

    if verbose:
        logger.info("  └─ %s: +%d unique results", source, unique_count)

    return current_results
