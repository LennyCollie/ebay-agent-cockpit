# routes/search.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from flask_login import current_user
from alert_checker import ALERT_INTERVAL_FREE, ALERT_INTERVAL_PREMIUM

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
    jsonify,
)

from services.ebay_api import ebay_search
from utils.ebay_browse import browse_search
from utils.ebay_finding import finding_search
from utils.ebay_normalize import normalize_browse, normalize_finding

# Live-Kleinanzeigen + Meta-Suche über mehrere Marktplätze
from services.kleinanzeigen import search_kleinanzeigen
from services.search_integration import merge_all_marketplaces


bp_search = Blueprint("search", __name__)


# =============================================================================
# HELFER: eBay-API -> View-Items
# =============================================================================
def _to_view_items(payload: Dict) -> List[Dict]:
    out: List[Dict] = []
    for it in (payload or {}).get("itemSummaries", []) or []:
        price_txt = ""
        if it.get("price"):
            v = it["price"].get("value")
            c = it["price"].get("currency")
            if v is not None:
                price_txt = f"{v} {c}"
        img_url = (it.get("image") or {}).get("imageUrl") or ""
        out.append(
            {
                "title": it.get("title", "Ohne Titel"),
                "price": price_txt,
                "url": it.get("itemWebUrl") or "#",
                "img": img_url,
                "images": [img_url] if img_url else [],
                "term": "",
                "source": "ebay",
                "src": "ebay",
                "verdict": "unknown",
                "score": None,
            }
        )
    return out


# =============================================================================
# HELFER: Kleinanzeigen-Normalisierung (für dedizierte Route)
# =============================================================================
def _normalize_kleinanzeigen(ka_results: List[Dict]) -> List[Dict]:
    normalized: List[Dict] = []
    for item in ka_results:
        src = (item.get("source") or "kleinanzeigen").lower()
        img_url = item.get("image_url", "")
        normalized.append(
            {
                "title": item.get("title", "Ohne Titel"),
                "price": (
                    f"{item.get('price', 0):.2f} EUR"
                    if item.get("price") not in (None, "")
                    else "Preis auf Anfrage"
                ),
                "url": item.get("url", "#"),
                "img": img_url,
                "images": [img_url] if img_url else [],
                "location": item.get("location", ""),
                "postal_code": item.get("postal_code", ""),
                "description": item.get("description", ""),
                "condition": item.get("condition", "Gebraucht"),
                "published_date": item.get("published_date"),
                "source": src,
                "src": src,
                "item_id": item.get("item_id"),
                "term": "",
                "verdict": "unknown",
                "score": None,
            }
        )
    return normalized


# =============================================================================
# HELFER: Form-/Query-Parameter parsen
# =============================================================================
def _parse_args() -> Dict[str, Any]:
    src = request.args if request.method == "GET" else request.form

    # 1–3 Suchbegriffe
    q1 = (src.get("q") or src.get("q1") or "").strip()
    q2 = (src.get("q2") or "").strip()
    q3 = (src.get("q3") or "").strip()
    terms = [t for t in (q1, q2, q3) if t]
    q = " ".join(terms)

    # Sortierung (UI -> eBay)
    sort_ui = (src.get("sort") or "best").strip()
    sort_map = {
        "best": "bestMatch",
        "price_asc": "price",
        "price_desc": "-price",
        "newly": "newlyListed",
    }
    sort_api = sort_map.get(sort_ui, "bestMatch")

    price_min = (src.get("price_min") or "").strip()
    price_max = (src.get("price_max") or "").strip()
    category_ids = (src.get("category_ids") or "").strip()
    per_page = (src.get("per_page") or "20").strip()

    # Zustände (Checkboxen)
    conds: List[str] = []
    if hasattr(src, "getlist"):
        conds = [c.strip().upper() for c in src.getlist("condition") if c.strip()]
    if not conds:
        cond_field = (src.get("conditions") or "").strip()
        if cond_field:
            conds = [c.strip().upper() for c in cond_field.split(",") if c.strip()]

    # eBay-Filter-String (Preis + Zustand)
    filters: List[str] = []
    if price_min or price_max:
        lo = price_min if price_min else "*"
        hi = price_max if price_max else "*"
        filters.append(f"price:[{lo}..{hi}]")
    if conds:
        filters.append("conditions:{" + ",".join(conds) + "}")
    filter_str = ",".join(filters) if filters else None

    location_country = (src.get("location_country") or "").strip() or None
    listing_type = (src.get("listing_type") or "").strip() or None
    free_shipping = bool(src.get("free_shipping"))
    returns_accepted = bool(src.get("returns_accepted"))
    top_rated_only = bool(src.get("top_rated_only"))

    # Quelle / Portal (ebay, kleinanzeigen, quoka, shpock, marktde, both, all, …)
    source = (src.get("source") or "both").strip().lower()

    return {
        "q": q,
        "terms": terms,
        "sort_ui": sort_ui,
        "sort": sort_api,
        "price_min": price_min or None,
        "price_max": price_max or None,
        "category_ids": category_ids or None,
        "per_page": per_page,
        "filter_str": filter_str,
        "conditions": conds,
        "location_country": location_country,
        "listing_type": listing_type,
        "free_shipping": free_shipping,
        "returns_accepted": returns_accepted,
        "top_rated_only": top_rated_only,
        "source": source,
    }


# =============================================================================
# HELFER: Plan-/Abo-Infos
# =============================================================================
def _get_plan_info():
    if not current_user.is_authenticated:
        return None

    plan_type = (getattr(current_user, "plan_type", "") or "").strip().lower()
    is_premium_flag = bool(getattr(current_user, "is_premium", False))

    if plan_type in ("pro", "premium") or is_premium_flag:
        interval_min = ALERT_INTERVAL_PREMIUM
    else:
        interval_min = ALERT_INTERVAL_FREE

    if plan_type in ("pro", "premium"):
        label = plan_type.upper()
    elif is_premium_flag:
        label = "PREMIUM"
    else:
        label = "FREE"

    return {
        "label": label,
        "interval_min": interval_min,
        "plan_type": plan_type or "free",
        "is_premium": is_premium_flag,
    }


# =============================================================================
# 1) ZENTRALE ALLROUND-SUCHE  (/search)
# =============================================================================
@bp_search.route("/search", methods=["GET", "POST"])
def search_page():
    current_app.logger.debug("=== /search called, method=%s ===", request.method)
    current_app.logger.debug("request.args: %s", dict(request.args))
    if request.method == "POST":
        current_app.logger.debug("request.form: %s", dict(request.form))

    args = _parse_args()
    plan_info = _get_plan_info()

    source = (args.get("source") or request.args.get("source") or "both").strip().lower()
    args["source"] = source
    current_app.logger.debug("Parsed search args: %r", args)

    # Prüfen, ob irgendein Suchbegriff vorhanden ist (q oder q1/q2/q3)
    has_search_term = bool(
        args["q"]
        or request.args.get("q1")
        or request.args.get("q")
        or request.form.get("q1")
        or request.form.get("q")
    )

    # 1. Nur Formular anzeigen (erste Aufrufe ohne Suchbegriff)
    if request.method == "GET" and not has_search_term:
        current_app.logger.debug("No search term detected - showing empty form")
        return render_template("search.html", plan_info=plan_info, source=source)

    # 2. Kein Suchbegriff -> Hinweis & zurück
    if not args["q"]:
        current_app.logger.warning("Search submitted but no term found after parsing")
        flash("Bitte mindestens einen Suchbegriff angeben.", "warning")
        return redirect(url_for("search.search_page"))

    current_app.logger.info("Searching for: %s (source: %s)", args["q"], source)

    items: List[Dict[str, Any]] = []

    # -------------------------------------------------------------------------
    # 3. eBay-Suche – nur wenn eBay Teil der Auswahl ist
    # -------------------------------------------------------------------------
    if source in ("ebay", "both", "all"):
        try:
            current_app.logger.debug("Calling eBay API...")
            payload = ebay_search(
                args["q"],
                limit=int(args["per_page"] or 24),
                sort=args["sort"],
                category_ids=args["category_ids"],
                filter_str=args["filter_str"],
                country_code=args["location_country"],
            )
            items = _to_view_items(payload)
            for it in items:
                it["term"] = args["q"]
            current_app.logger.info("eBay returned %d items", len(items))
        except Exception as e:
            current_app.logger.error("eBay-Suche fehlgeschlagen: %s", e, exc_info=True)
            flash(f"eBay-Suche fehlgeschlagen: {e}", "danger")

    # -------------------------------------------------------------------------
    # 4. Weitere Marktplätze (Kleinanzeigen + Quoka + Shpock + Markt.de)
    # -------------------------------------------------------------------------
    # Mapping von UI-"source" zu externen Marktplätzen (Quoka deaktiviert)
    src = source
    if src == "ebay":
        active_sources: List[str] = []
    elif src in ("kleinanzeigen", "shpock", "marktde"):
        active_sources = [src]
    elif src == "quoka":
        active_sources = ["kleinanzeigen"]
    elif src in ("both", "all"):
        # "Alle Portale" -> eBay + alle weiteren Marktplätze (ohne Quoka)
        active_sources = ["kleinanzeigen", "shpock", "marktde"]
    else:
        # Fallback: Kleinanzeigen als zusätzliche Quelle
        active_sources = ["kleinanzeigen"]

    try:
        price_min_f = float(args["price_min"]) if args["price_min"] else None
        price_max_f = float(args["price_max"]) if args["price_max"] else None

        if active_sources:
            current_app.logger.debug(
                "Calling merge_all_marketplaces with active_sources=%s",
                active_sources,
            )
            items = merge_all_marketplaces(
                term=args["q"],
                current_results=items,
                price_min=price_min_f,
                price_max=price_max_f,
                location=None,  # später ggf. PLZ übergeben
                max_per_source=20,
                verbose=True,
                active_sources=active_sources,
            )
            current_app.logger.info("After merge: %d total items", len(items))
        else:
            current_app.logger.debug(
                "No external marketplaces requested (source=%s)", src
            )
    except Exception as e:
        current_app.logger.error(
            "Fehler beim Marketplace-Merge: %s",
            e,
            exc_info=True,
        )

    current_app.logger.debug("Total items after merge & filtering: %d", len(items))

    # -------------------------------------------------------------------------
    # 5. Template-Daten vorbereiten
    # -------------------------------------------------------------------------
    terms = args["terms"]
    base_qs = {
        "q1": terms[0] if len(terms) > 0 else "",
        "q2": terms[1] if len(terms) > 1 else "",
        "q3": terms[2] if len(terms) > 2 else "",
        "price_min": args["price_min"] or "",
        "price_max": args["price_max"] or "",
        "sort": args["sort_ui"],
        "per_page": args["per_page"],
        "location_country": args["location_country"] or "",
        "listing_type": args["listing_type"] or "",
        "source": source,
    }

    filters = {
        "price_min": args["price_min"],
        "price_max": args["price_max"],
        "sort": args["sort_ui"],
        "location_country": args["location_country"],
        "listing_type": args["listing_type"],
        "conditions": args["conditions"],
        "free_shipping": args["free_shipping"],
        "returns_accepted": args["returns_accepted"],
        "top_rated_only": args["top_rated_only"],
    }

    # (Pagination kannst du später richtig bauen)
    pagination = {
        "page": 1,
        "has_prev": False,
        "has_next": False,
        "total_estimated": None,
        "total_pages": None,
    }

    return render_template(
        "search_results.html",
        title="Suchergebnisse",
        terms=terms,
        results=items,
        items=items,
        plan_info=plan_info,
        base_qs=base_qs,
        filters=filters,
        pagination=pagination,
        source=source,
    )


# =============================================================================
# 2) LEGACY-ROUTE: /search-legacy -> nutzt jetzt dieselbe Logik
# =============================================================================
@bp_search.route("/search-legacy", methods=["GET", "POST"])
def search_legacy():
    """
    Alte Links /search-legacy verwenden jetzt exakt die gleiche Logik wie /search.
    Dadurch ist es egal, ob irgendwo noch /search-legacy verlinkt ist.
    """
    return search_page()


# =============================================================================
# 3) Alte eBay-only Beta-Suche (optional, kann später weg)
# =============================================================================
@bp_search.get("/search/results")
def search_results():
    """
    Historische eBay/Kleinanzeigen-Route. Wird von der neuen Allround-Suche
    eigentlich nicht mehr gebraucht, aber bleibt für Kompatibilität erhalten.
    """
    q = (request.args.get("q") or "").strip()
    auction = request.args.get("auction") == "1"
    bin_buy = request.args.get("bin") == "1"
    postal = (request.args.get("postal") or "").strip() or None
    radius = int(request.args.get("radius_km") or 0) or None
    ship_to = (request.args.get("ship_to") or "").strip() or None
    located_in = (request.args.get("located_in") or "").strip() or None

    source = (request.args.get("source") or "ebay").strip().lower()
    price_min = request.args.get("price_min")
    price_max = request.args.get("price_max")

    # Kleinanzeigen-only Modus dieser Legacy-Route
    if source == "kleinanzeigen":
        try:
            ka_results = search_kleinanzeigen(
                query=q,
                price_min=float(price_min) if price_min else None,
                price_max=float(price_max) if price_max else None,
                location=postal,
                radius_km=radius,
            )
            results = _normalize_kleinanzeigen(ka_results)
            return render_template(
                "search_results.html",
                results=results,
                q=q,
                params=request.args,
                items=results,
                source="kleinanzeigen",
            )
        except Exception as e:
            current_app.logger.error(
                "Kleinanzeigen-Fehler (legacy): %s", e, exc_info=True
            )
            flash(f"Kleinanzeigen-Suche fehlgeschlagen: {e}", "danger")
            return render_template(
                "search_results.html",
                results=[],
                q=q,
                params=request.args,
                items=[],
                source="kleinanzeigen",
            )

    # eBay-Teil dieser Legacy-Route
    mode = (current_app.config.get("EBAY_MODE") or "auto").lower()
    use_finding = (mode == "finding") or (mode == "auto" and postal and radius)

    if use_finding:
        raw = finding_search(
            q,
            auction=auction,
            bin_buy=bin_buy,
            buyer_postal=postal,
            max_distance_km=radius,
            ship_to=ship_to,
            located_in=located_in,
            entries=50,
        )
        results = normalize_finding(raw)
    else:
        raw = browse_search(
            q,
            auction=auction,
            bin_buy=bin_buy,
            ship_to=ship_to,
            postal=postal,
            located_in=located_in,
            located_region=None,
            price_min=None,
            price_max=None,
            local_pickup_radius_km=None,
            pickup_country=None,
            limit=50,
        )
        results = normalize_browse(raw)

    # optionaler KI-Bildcheck
    try:
        from utils.vision_dispatch import analyze_images

        for it in results:
            vis = analyze_images(it.get("images") or [])
            it["verdict"] = vis["verdict"]
            it["score"] = vis["score"]
    except Exception:
        pass

    strict = current_app.config.get("VISION_FILTER_STRICT", True) in (True, "1", "true")
    if strict:
        results = [r for r in results if r.get("verdict") != "damaged"]

    return render_template(
        "search_results.html",
        results=results,
        q=q,
        params=request.args,
        items=results,
        source="ebay",
    )


# =============================================================================
# 4) Hilfsrouten: Nur-eBay & Nur-Kleinanzeigen
# =============================================================================
@bp_search.route("/search_ebay", methods=["GET", "POST"])
def search_ebay():
    """
    Historische eBay-Beta-Suche – leitet jetzt einfach auf /search um.
    """
    data = request.form if request.method == "POST" else request.args
    params = data.to_dict(flat=True)
    params.setdefault("source", "ebay")
    return redirect(url_for("search.search_page", **params))


@bp_search.route("/search/kleinanzeigen", methods=["GET", "POST"])
def search_kleinanzeigen_page():
    """
    Dedizierte Route nur für Kleinanzeigen – nutzt den Scraper direkt.
    """
    plan_info = _get_plan_info()

    data = request.form if request.method == "POST" else request.args
    q = (data.get("q") or "").strip()
    price_min = data.get("price_min")
    price_max = data.get("price_max")
    postal = (data.get("postal") or "").strip() or None
    radius = int(data.get("radius_km") or 0) or None

    if not q:
        flash("Bitte einen Suchbegriff eingeben.", "warning")
        return render_template(
            "search.html", source="kleinanzeigen", plan_info=plan_info
        )

    try:
        ka_results = search_kleinanzeigen(
            query=q,
            price_min=float(price_min) if price_min else None,
            price_max=float(price_max) if price_max else None,
            location=postal,
            radius_km=radius,
        )

        results = _normalize_kleinanzeigen(ka_results)

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify(
                {
                    "success": True,
                    "results": results,
                    "count": len(results),
                }
            )

        return render_template(
            "search_results.html",
            results=results,
            q=q,
            params=data,
            items=results,
            source="kleinanzeigen",
            plan_info=plan_info,
        )

    except Exception as e:
        current_app.logger.error(
            "Kleinanzeigen-Fehler (dedizierte Route): %s", e, exc_info=True
        )

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": str(e)}), 500

        flash(f"Fehler bei der Kleinanzeigen-Suche: {e}", "danger")
        return render_template(
            "search.html", source="kleinanzeigen", plan_info=plan_info
        )
