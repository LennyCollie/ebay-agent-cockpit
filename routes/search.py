# routes/search.py
from __future__ import annotations

from typing import Dict, List, Optional

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

# ⭐ NEU: Kleinanzeigen-Import
from services.kleinanzeigen import search_kleinanzeigen

bp_search = Blueprint("search", __name__)


@bp_search.get("/search/results")
def search_results():
    q = (request.args.get("q") or "").strip()
    auction = request.args.get("auction") == "1"
    bin_buy = request.args.get("bin") == "1"
    postal = (request.args.get("postal") or "").strip() or None
    radius = int(request.args.get("radius_km") or 0) or None
    ship_to = (request.args.get("ship_to") or "").strip() or None
    located_in = (request.args.get("located_in") or "").strip() or None

    # ⭐ NEU: Source-Parameter (ebay oder kleinanzeigen)
    source = (request.args.get("source") or "ebay").strip().lower()
    price_min = request.args.get("price_min")
    price_max = request.args.get("price_max")

    # ========================================
    # KLEINANZEIGEN-SUCHE (NEU!)
    # ========================================
    if source == "kleinanzeigen":
        try:
            # Kleinanzeigen durchsuchen
            ka_results = search_kleinanzeigen(
                query=q,
                price_min=float(price_min) if price_min else None,
                price_max=float(price_max) if price_max else None,
                location=postal,
                radius_km=radius
            )

            # Konvertiere zu deinem Standard-Format
            results = _normalize_kleinanzeigen(ka_results)

            return render_template(
                "search_results.html",
                results=results,
                q=q,
                params=request.args,
                items=results,
                source="kleinanzeigen"
            )

        except Exception as e:
            current_app.logger.error(f"Kleinanzeigen-Fehler: {e}")
            flash(f"Kleinanzeigen-Suche fehlgeschlagen: {e}", "danger")
            return render_template(
                "search_results.html",
                results=[],
                q=q,
                params=request.args,
                items=[],
                source="kleinanzeigen"
            )

    # ========================================
    # EBAY-SUCHE (DEIN BESTEHENDER CODE)
    # ========================================
    # API-Auswahl: auto = Finding bei Radius, sonst Browse
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

    # (optional) KI-Bildcheck anhängen
    try:
        from utils.vision_dispatch import analyze_images

        for it in results:
            vis = analyze_images(it.get("images") or [])
            it["verdict"] = vis["verdict"]
            it["score"] = vis["score"]
    except Exception:
        pass

    # (optional) harte Filterung
    strict = current_app.config.get("VISION_FILTER_STRICT", True) in (True, "1", "true")
    if strict:
        results = [r for r in results if r.get("verdict") != "damaged"]

    return render_template(
        "search_results.html",
        results=results,
        q=q,
        params=request.args,
        items=results,
        source="ebay"
    )


# ========================================
# ⭐ NEU: Kleinanzeigen-Normalisierung
# ========================================
def _normalize_kleinanzeigen(ka_results: List[Dict]) -> List[Dict]:
    """
    Konvertiert Kleinanzeigen-Ergebnisse in dein Standard-Format
    """
    normalized = []

    for item in ka_results:
        normalized.append({
            "title": item.get("title", "Ohne Titel"),
            "price": f"{item.get('price', 0):.2f} EUR" if item.get('price') else "Preis auf Anfrage",
            "url": item.get("url", "#"),
            "img": item.get("image_url", ""),
            "images": [item.get("image_url")] if item.get("image_url") else [],
            "location": item.get("location", ""),
            "postal_code": item.get("postal_code", ""),
            "description": item.get("description", ""),
            "condition": item.get("condition", "Gebraucht"),
            "published_date": item.get("published_date"),
            "source": "kleinanzeigen",
            "item_id": item.get("item_id"),
            "term": "",
            "verdict": "unknown",
            "score": None
        })

    return normalized


def _to_view_items(payload: Dict) -> List[Dict]:
    out: List[Dict] = []
    for it in (payload or {}).get("itemSummaries", []) or []:
        price_txt = ""
        if it.get("price"):
            v = it["price"].get("value")
            c = it["price"].get("currency")
            if v is not None:
                price_txt = f"{v} {c}"
        out.append(
            {
                "title": it.get("title", "Ohne Titel"),
                "price": price_txt,
                "url": it.get("itemWebUrl") or "#",
                "img": (it.get("image") or {}).get("imageUrl") or "",
                "term": "",
                "source": "ebay"
            }
        )
    return out


def _parse_args() -> Dict[str, Optional[str]]:
    src = request.args if request.method == "GET" else request.form
    q = (src.get("q") or src.get("q1") or "").strip()
    price_min = (src.get("price_min") or "").strip()
    price_max = (src.get("price_max") or "").strip()
    category_ids = (src.get("category_ids") or "").strip()
    sort = (src.get("sort") or "bestMatch").strip()

    conds: List[str] = []
    cond_field = (src.get("condition") or src.get("conditions") or "").strip()
    if cond_field:
        conds = [c.strip().upper() for c in cond_field.split(",") if c.strip()]
    else:
        if (src.get("new") or "").lower() in {"on", "1", "true"}:
            conds.append("NEW")
        if (src.get("used") or "").lower() in {"on", "1", "true"}:
            conds.append("USED")

    filters = []
    if price_min or price_max:
        lo = price_min if price_min else "*"
        hi = price_max if price_max else "*"
        filters.append(f"price:[{lo}..{hi}]")
    if conds:
        filters.append("conditions:{" + ",".join(conds) + "}")
    filter_str = ",".join(filters) if filters else None

    return {
        "q": q,
        "price_min": price_min or None,
        "price_max": price_max or None,
        "category_ids": category_ids or None,
        "sort": sort or "bestMatch",
        "filter_str": filter_str,
    }


@bp_search.route("/search", methods=["GET", "POST"])
def search_page():
    args = _parse_args()

    if request.method == "GET" and not args["q"]:
        return render_template("search.html")

    if not args["q"]:
        flash("Bitte mindestens einen Suchbegriff angeben.", "warning")
        return redirect(url_for("search.search_page"))

    try:
        payload = ebay_search(
            args["q"],
            limit=24,
            sort=args["sort"] or "bestMatch",
            category_ids=args["category_ids"],
            filter_str=args["filter_str"],
        )
        items = _to_view_items(payload)
        for x in items:
            x["term"] = args["q"]
    except Exception as e:
        flash(f"eBay-Suche fehlgeschlagen: {e}", "danger")
        return redirect(url_for("search.search_page"))

    return render_template(
        "search_results.html",
        title="Suchergebnisse",
        terms=[args["q"]],
        results=items,
    )


@bp_search.route("/search_ebay", methods=["GET", "POST"])
def search_ebay():
    """
    Vorläufige eBay-Beta-Suche
    """
    data = request.form if request.method == "POST" else request.args
    params = data.to_dict(flat=True)
    return redirect(url_for("search.search_page", **params))


@bp_search.route("/search/kleinanzeigen", methods=["GET", "POST"])
def search_kleinanzeigen_page():
    """
    Dedizierte Route für Kleinanzeigen-Suche
    """
    if request.method == "POST":
        data = request.form
    else:
        data = request.args

    q = (data.get("q") or "").strip()
    price_min = data.get("price_min")
    price_max = data.get("price_max")
    postal = (data.get("postal") or "").strip() or None
    radius = int(data.get("radius_km") or 0) or None

    if not q:
        flash("Bitte einen Suchbegriff eingeben.", "warning")
        return render_template("search.html", source="kleinanzeigen")

    try:
        ka_results = search_kleinanzeigen(
            query=q,
            price_min=float(price_min) if price_min else None,
            price_max=float(price_max) if price_max else None,
            location=postal,
            radius_km=radius
        )

        results = _normalize_kleinanzeigen(ka_results)

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': True,
                'results': results,
                'count': len(results)
            })

        return render_template(
            "search_results.html",
            results=results,
            q=q,
            params=data,
            items=results,
            source="kleinanzeigen"
        )

    except Exception as e:
        current_app.logger.error(f"Kleinanzeigen-Fehler: {e}")

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

        flash(f"Fehler bei der Kleinanzeigen-Suche: {e}", "danger")
        return render_template(
            "search.html",
            source="kleinanzeigen"
        )
