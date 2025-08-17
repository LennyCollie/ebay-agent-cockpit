# routes/search.py
from __future__ import annotations
from typing import Dict, List, Optional
from flask import Blueprint, request, render_template, flash, redirect, url_for
from services.ebay_api import ebay_search

bp_search = Blueprint("search", __name__)

def _to_view_items(payload: Dict) -> List[Dict]:
    out: List[Dict] = []
    for it in (payload or {}).get("itemSummaries", []) or []:
        price_txt = ""
        if it.get("price"):
            v = it["price"].get("value")
            c = it["price"].get("currency")
            if v is not None:
                price_txt = f"{v} {c}"
        out.append({
            "title": it.get("title", "Ohne Titel"),
            "price": price_txt,
            "url": it.get("itemWebUrl") or "#",
            "img": (it.get("image") or {}).get("imageUrl") or "",
            "term": "",
        })
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

@bp_search.route("/search", methods=["GET", "POST"])
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
            args["q"],                       # type: ignore[arg-type]
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