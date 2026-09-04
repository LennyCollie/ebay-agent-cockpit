"""Offline UI propagation tests for Kleinanzeigen source failures."""

from pathlib import Path
from unittest.mock import patch

from flask import Flask

from routes import search as search_route
from services.kleinanzeigen import KleinanzeigenSearchResult, KleinanzeigenSearchStatus


def search_args():
    return {
        "q": "test",
        "terms": ["test"],
        "source": "kleinanzeigen",
        "per_page": 20,
        "price_min": None,
        "price_max": None,
        "sort_ui": "newlyListed",
        "location_country": None,
        "listing_type": None,
        "conditions": [],
        "free_shipping": False,
        "returns_accepted": False,
        "top_rated_only": False,
        "only_main_product": True,
    }


def test_route_propagates_failure_and_skips_smart_filter():
    app = Flask(__name__)
    app.secret_key = "test"
    failure = KleinanzeigenSearchResult(
        results=[],
        status=KleinanzeigenSearchStatus.HTTP_FORBIDDEN,
        reason="http_403",
        http_status=403,
    )

    with app.test_request_context("/search?q=test&source=kleinanzeigen"):
        with (
            patch.object(search_route, "_parse_args", return_value=search_args()),
            patch.object(search_route, "_get_plan_info", return_value={"max_terms": 3}),
            patch.object(search_route, "backend_search_kleinanzeigen", return_value=failure),
            patch.object(search_route, "SmartFilter") as smart_filter,
            patch.object(search_route, "render_template", side_effect=lambda name, **ctx: (name, ctx)),
        ):
            template_name, context = search_route.search_page()

    assert template_name == "search_results.html"
    assert context["kleinanzeigen_status"] == "http_forbidden"
    assert context["items"] == []
    smart_filter.assert_not_called()


def test_used_template_contains_neutral_unavailable_message():
    template = (
        Path(__file__).parent.parent / "templates" / "search_results.html"
    ).read_text(encoding="utf-8")
    assert "Kleinanzeigen ist derzeit nicht verfügbar" in template
    assert "http_forbidden" not in template
