from __future__ import annotations

from typing import Any, Dict, List, Tuple

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
    jsonify,
    make_response,
)
from flask_login import current_user

from alert_checker import ALERT_INTERVAL_FREE, ALERT_INTERVAL_PREMIUM
from services.price_tracker import track_item_price
from services.kleinanzeigen import KleinanzeigenSearchStatus
from services.csv_exporter import export_search_results_to_csv
from smart_filters import SmartFilter
from services.ebay_backend import backend_search_ebay
from services.kleinanzeigen_backend import backend_search_kleinanzeigen

bp_search = Blueprint("search", __name__)

MAX_TERMS_FREE = 3
MAX_TERMS_PREMIUM = 6


# =============================================================================
# HELPERS
# =============================================================================

def _to_view_items(payload: Dict, *, term: str = "") -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for it in (payload or {}).get("itemSummaries", []) or []:
        price_txt = ""
        price_raw = 0.0
        if it.get("price"):
            v = it["price"].get("value")
            c = it["price"].get("currency")
            if v is not None:
                price_txt = f"{v} {c}"
                try:
                    price_raw = float(v)
                except Exception:
                    price_raw = 0.0

        img_url = (it.get("image") or {}).get("imageUrl") or ""
        out.append(
            {
                "title": it.get("title", "Ohne Titel"),
                "price": price_txt,
                "price_raw": price_raw,
                "url": it.get("itemWebUrl") or "#",
                "img": img_url,
                "images": [img_url] if img_url else [],
                "term": term,
                "source": "ebay",
                "src": "ebay",
                "verdict": "unknown",
                "score": None,
            }
        )
    return out


def _normalize_kleinanzeigen(ka_results: List[Dict], *, term: str = "") -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for item in ka_results:
        src = (item.get("source") or "kleinanzeigen").lower()
        img_url = item.get("image_url", "")
        price_value = item.get("price")
        if price_value not in (None, ""):
            try:
                price_text = f"{float(price_value):.2f} EUR"
                price_raw = float(price_value)
            except Exception:
                price_text = str(price_value)
                price_raw = 0.0
        else:
            price_text = "Preis auf Anfrage"
            price_raw = 0.0

        normalized.append(
            {
                "title": item.get("title", "Ohne Titel"),
                "price": price_text,
                "price_raw": price_raw,
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
                "term": term,
                "verdict": "unknown",
                "score": None,
            }
        )
    return normalized


def _dedupe_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for item in items:
        key = (
            item.get("url")
            or item.get("item_id")
            or item.get("id")
            or item.get("title")
        )
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _parse_args() -> Dict[str, Any]:
    src = request.args if request.method == "GET" else request.form

    q1 = (src.get("q") or src.get("q1") or "").strip()
    q2 = (src.get("q2") or "").strip()
    q3 = (src.get("q3") or "").strip()
    q4 = (src.get("q4") or "").strip()
    q5 = (src.get("q5") or "").strip()
    q6 = (src.get("q6") or "").strip()
    terms = [t for t in (q1, q2, q3, q4, q5, q6) if t]
    q = " ".join(terms)

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

    conds: List[str] = []
    if hasattr(src, "getlist"):
        conds = [c.strip().upper() for c in src.getlist("condition") if c.strip()]
    if not conds:
        cond_field = (src.get("conditions") or "").strip()
        if cond_field:
            conds = [c.strip().upper() for c in cond_field.split(",") if c.strip()]

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
    only_main_product = bool(src.get("only_main_product"))
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
        "only_main_product": only_main_product,
        "source": source,
    }


def _get_plan_info():
    if not current_user.is_authenticated:
        return None

    plan_type = (getattr(current_user, "plan_type", "") or "").strip().lower()
    is_premium_flag = bool(getattr(current_user, "is_premium", False))

    if plan_type in ("pro", "premium") or is_premium_flag:
        interval_min = ALERT_INTERVAL_PREMIUM
        max_terms = MAX_TERMS_PREMIUM
    else:
        interval_min = ALERT_INTERVAL_FREE
        max_terms = MAX_TERMS_FREE

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
        "max_terms": max_terms,
        "max_terms_premium": MAX_TERMS_PREMIUM,
    }


def filter_main_products(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    blacklist = [
        "hülle", "schutzhülle", "case", "tasche", "panzerglas", "schutzglas",
        "schutzfolie", "displayfolie", "folie", "backcover", "cover", "bumper",
        "ladekabel", "kabel", "netzteil", "ladegerät", "adapter", "halterung",
        "dockingstation", "dock", "lade-dock", "etui", "reparatur", "displaytausch",
        "tausch", "service", "reparieren", "ersatzteil", "ersatzteile", "nur teile",
        "nur für teile", "nur zum ausschlachten", "defekt", "defekte", "funktioniert nicht",
        "ohne funktion", "bastler", "bastlerware", "displaybruch", "display defekt",
        "wasserschaden", "wasser schaden",
    ]

    filtered: List[Dict[str, Any]] = []
    for it in items:
        if isinstance(it, dict):
            title = (it.get("title") or it.get("name") or "").lower()
        else:
            title = ((getattr(it, "title", "") or getattr(it, "name", "") or "")).lower()

        if not title:
            filtered.append(it)
            continue

        if any(word in title for word in blacklist):
            continue

        filtered.append(it)
    return filtered


# =============================================================================
# SEARCH HELPERS
# =============================================================================





# =============================================================================
# 1) ZENTRALE ALLROUND-SUCHE  (/search)
# =============================================================================
@bp_search.route("/search", methods=["GET", "POST"])
def search_page():
    current_app.logger.debug("=== /search called, method=%s ===", request.method)
    current_app.logger.debug("request argument keys: %s", sorted(request.args.keys()))
    if request.method == "POST":
        current_app.logger.debug("request form keys: %s", sorted(request.form.keys()))

    args = _parse_args()
    plan_info = _get_plan_info()

    max_terms = plan_info.get("max_terms") if plan_info else MAX_TERMS_FREE
    orig_terms_len = len(args.get("terms", []))
    terms_trimmed = False
    if orig_terms_len > max_terms:
        args["terms"] = args["terms"][:max_terms]
        args["q"] = " ".join(args["terms"])
        terms_trimmed = True
        current_app.logger.debug("Terms begrenzt auf %d aufgrund des Plans", max_terms)
        try:
            flash(
                f"Hinweis: In deinem aktuellen Tarif werden nur die ersten {max_terms} Suchbegriffe berücksichtigt.",
                "info",
            )
        except Exception:
            pass

    source = (args.get("source") or request.args.get("source") or "both").strip().lower()
    args["source"] = source
    current_app.logger.debug(
        "Parsed search args: source=%s term_count=%d",
        source,
        len(args.get("terms", [])),
    )

    has_search_term = bool(
        args["q"]
        or request.args.get("q1")
        or request.args.get("q")
        or request.form.get("q1")
        or request.form.get("q")
    )

    if request.method == "GET" and not has_search_term:
        current_app.logger.debug("No search term detected - showing empty form")
        return render_template(
            "search.html",
            plan_info=plan_info,
            source=source,
            terms_trimmed=False,
        )

    if not args["q"]:
        current_app.logger.warning("Search submitted but no term found after parsing")
        flash("Bitte mindestens einen Suchbegriff angeben.", "warning")
        return redirect(url_for("search.search_page"))

    current_app.logger.info(
        "Search started: source=%s term_count=%d",
        source,
        len(args.get("terms", [])),
    )

    items: List[Dict[str, Any]] = []
    kleinanzeigen_status = None

    # -------------------------------------------------------------------------
    # 1. eBay
    # -------------------------------------------------------------------------
    if source in ("ebay", "both", "all"):
        try:
            current_app.logger.debug("Calling NEW eBay backend...")

            ebay_items, _ = backend_search_ebay(
                terms=args["terms"],
                filters=args,
                page=1,
                per_page=int(args["per_page"] or 20),
            )

            items.extend(ebay_items)
            current_app.logger.info("eBay returned %d items", len(ebay_items))

        except Exception as e:
            current_app.logger.error("eBay-Suche fehlgeschlagen: %s", e, exc_info=True)

    # -------------------------------------------------------------------------
    # 2. Kleinanzeigen
    # -------------------------------------------------------------------------
    if source in ("kleinanzeigen", "both", "all"):
        try:
            current_app.logger.debug("Calling NEW Kleinanzeigen backend...")

            ka_result = backend_search_kleinanzeigen(
                terms=args["terms"],
                filters=args,
                per_page=20,
            )
            kleinanzeigen_status = ka_result.status.value
            items.extend(ka_result.results)
            current_app.logger.info(
                "Kleinanzeigen classification=%s items=%d",
                kleinanzeigen_status,
                len(ka_result.results),
            )

        except Exception:
            kleinanzeigen_status = KleinanzeigenSearchStatus.SOURCE_UNAVAILABLE.value
            current_app.logger.error(
                "Kleinanzeigen-Suche fehlgeschlagen: classification=source_unavailable"
            )

    # -------------------------------------------------------------------------
    # 3. Dedupe
    # -------------------------------------------------------------------------
    items = _dedupe_items(items)

    # -------------------------------------------------------------------------
    # 4. Smart-Filter
    # -------------------------------------------------------------------------
    kleinanzeigen_failed = kleinanzeigen_status not in (
        None,
        KleinanzeigenSearchStatus.SUCCESS_WITH_RESULTS.value,
        KleinanzeigenSearchStatus.SUCCESS_EMPTY.value,
    )
    if args.get("only_main_product") and not (
        source == "kleinanzeigen" and kleinanzeigen_failed
    ):
        before = len(items)
        sf = SmartFilter()
        res = sf.filter_items(items, search_terms=args["terms"])
        items = res["filtered_items"]
        current_app.logger.debug(
            "Smart-Filter aktiviert (only_main_product=1): %d -> %d Items",
            before,
            len(items),
        )

    # -------------------------------------------------------------------------
    # 5. Preise tracken
    # -------------------------------------------------------------------------
    for item in items:
        try:
            track_item_price(item)
        except Exception as e:
            current_app.logger.debug("[Price Track Error] %s", e)

    current_app.logger.debug("Total items after merge & filtering: %d", len(items))

    terms = args["terms"]
    base_qs = {
        "q1": terms[0] if len(terms) > 0 else "",
        "q2": terms[1] if len(terms) > 1 else "",
        "q3": terms[2] if len(terms) > 2 else "",
        "q4": terms[3] if len(terms) > 3 else "",
        "q5": terms[4] if len(terms) > 4 else "",
        "q6": terms[5] if len(terms) > 5 else "",
        "price_min": args["price_min"] or "",
        "price_max": args["price_max"] or "",
        "sort": args["sort_ui"],
        "per_page": args["per_page"],
        "location_country": args["location_country"] or "",
        "listing_type": args["listing_type"] or "",
        "source": source,
        "only_main_product": "1" if args.get("only_main_product") else "",
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
        "only_main_product": args["only_main_product"],
    }

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
        kleinanzeigen_status=kleinanzeigen_status,
        terms_trimmed=terms_trimmed,
    )


# =============================================================================
# CSV-Export
# =============================================================================
@bp_search.route("/export-csv", methods=["POST"])
def export_csv():
    items = request.json.get("items", [])

    if not items:
        return jsonify({"error": "Keine Items zum exportieren"}), 400

    csv_content, filename = export_search_results_to_csv(items)

    response = make_response(csv_content)
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    return response


# =============================================================================
# 2) LEGACY-ROUTE
# =============================================================================
@bp_search.route("/search-legacy", methods=["GET", "POST"])
def search_legacy():
    return search_page()
