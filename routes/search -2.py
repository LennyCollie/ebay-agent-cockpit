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
)

# --- Deine Hilfsfunktionen/APIs (bitte ggf. anpassen, falls Pfade anders) ---
from services.ebay_api import ebay_search
from utils.ebay_browse import browse_search
from utils.ebay_finding import finding_search
from utils.ebay_normalize import normalize_browse, normalize_finding

# ---------------------------------------------------------------------------
# Blueprint: MUSS vor allen @bp.route/@bp.get Dekoratoren stehen!
# ---------------------------------------------------------------------------
bp = Blueprint("search", __name__)


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------
def _bool_param(name: str) -> bool:
    val = (request.args.get(name) or "").strip().lower()
    return val in {"1", "true", "yes", "on"}


def _int_param(name: str) -> Optional[int]:
    raw = (request.args.get(name) or "").strip()
    try:
        return int(raw)
    except Exception:
        return None


def _filters_for_template() -> Dict:
    """kleines Dict, das deine search_results.html als 'filters' anzeigen kann."""
    # du kannst hier beliebig erweitern
    return {
        "price_min": request.args.get("price_min") or None,
        "price_max": request.args.get("price_max") or None,
        "conditions": request.args.getlist("condition") or None,
        "sort": request.args.get("sort", "best"),
    }


# ---------------------------------------------------------------------------
# Neue Ergebnis-Route (mit Browse/Finding + optional Vision)
# ---------------------------------------------------------------------------
@bp.get("/search/results")
def search_results():
    q = (request.args.get("q") or "").strip()

    auction = _bool_param("auction")
    bin_buy = _bool_param("bin")
    postal = (request.args.get("postal") or "").strip() or None
    radius_km = _int_param("radius_km")
    ship_to = (request.args.get("ship_to") or "").strip() or None
    located_in = (request.args.get("located_in") or "").strip() or None

    # API-Auswahl: auto = Finding wenn Umkreissuche (Postleitzahl+Radius), sonst Browse
    mode = (current_app.config.get("EBAY_MODE") or "auto").lower()
    use_finding = (mode == "finding") or (mode == "auto" and postal and radius_km)

    if use_finding:
        raw = finding_search(
            q,
            auction=auction,
            bin_buy=bin_buy,
            buyer_postal=postal,
            max_distance_km=radius_km,
            ship_to=ship_to,
            located_in=located_in,
            entries=50,
        )
        results = normalize_finding(raw)
    else:
        # Tipp: Für EU-Region kannst du located_in="EU" geben (in browse_search entsprechend mappen)
        raw = browse_search(
            q,
            auction=auction,
            bin_buy=bin_buy,
            ship_to=ship_to,
            postal=postal,
            located_in=located_in,
            located_region=None,  # optional, je nach Implementierung
            price_min=None,
            price_max=None,
            local_pickup_radius_km=None,  # oder radius_km, falls du Local Pickup nutzt
            pickup_country=None,
            limit=50,
        )
        results = normalize_browse(raw)

    # Optional: KI-Bildcheck
    try:
        from utils.vision_dispatch import analyze_images  # lazy import

        for it in results:
            vis = analyze_images(it.get("images") or [])
            # nur einfache Felder mappen, damit das Template sie anzeigen/filtern könnte
            it["verdict"] = vis.get("verdict")
            it["score"] = vis.get("score")
    except Exception:
        # leise degradieren – Suche soll niemals daran scheitern
        pass

    # Optional: harte Filterung von klar "defect/damaged" markierten Items
    strict_default = current_app.config.get("VISION_FILTER_STRICT", True)
    strict = strict_default in (True, "1", "true", "yes", "on")
    if strict:
        results = [r for r in results if (r.get("verdict") or "ok") != "damaged"]

    return render_template(
        "search_results.html",
        results=results,
        terms=[q] if q else [],
        base_qs=request.args,  # für "Link kopieren" etc.
        filters=_filters_for_template(),
        pagination=None,  # kannst du später füllen, wenn du echtes Paging baust
    )


# ---------------------------------------------------------------------------
# Alte /search Route (Form + simple API – bleibt für Rückwärtskompatibilität)
# ---------------------------------------------------------------------------
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
                "src": "ebay",
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

    # Bedingungen: akzeptiere entweder "condition=NEW,USED" oder Checkboxen new/used
    conds: List[str] = []
    cond_field = (src.get("condition") or src.get("conditions") or "").strip()
    if cond_field:
        conds = [c.strip().upper() for c in cond_field.split(",") if c.strip()]
    else:
        if (src.get("new") or "").lower() in {"on", "1", "true"}:
            conds.append("NEW")
        if (src.get("used") or "").lower() in {"on", "1", "true"}:
            conds.append("USED")

    # Filter bauen: price:[min..max],conditions:{NEW|USED}
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


@bp.route("/search", methods=["GET", "POST"])
def search_page():
    args = _parse_args()

    # GET ohne q -> nur Formular anzeigen
    if request.method == "GET" and not args["q"]:
        return render_template("search.html")

    if not args["q"]:
        flash("Bitte mindestens einen Suchbegriff angeben.", "warning")
        return redirect(url_for("search.search_page"))

    try:
        payload = ebay_search(
            args["q"],  # type: ignore[arg-type]
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
        base_qs=request.args,
        filters=_filters_for_template(),
        pagination=None,
    )
