"""Render the real view templates without starting the application or a browser."""

import ast
import json
from datetime import datetime
from math import ceil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from bs4 import BeautifulSoup
from flask import Flask, get_flashed_messages, render_template, request, session, flash, redirect, url_for
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader

from routes import alerts as alerts_route
from routes import search as search_route
from services import kleinanzeigen as ka


ROOT = Path(__file__).resolve().parents[1]
PAUSE = "Kleinanzeigen ist vorübergehend pausiert."
EBAY_ITEM = {"id": "ebay-1", "title": "eBay Testangebot", "price": "100 EUR",
             "src": "ebay", "url": "https://example.invalid/item", "img": "", "term": "test"}


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("ENABLE_KLEINANZEIGEN", "0")
    app = Flask(__name__)
    app.config.update(SECRET_KEY="offline-test", TESTING=True, LOGIN_DISABLED=True)
    app.register_blueprint(search_route.bp_search)
    app.register_blueprint(alerts_route.bp)
    app.add_url_rule("/pricing", "public_pricing", lambda: "")
    app.add_url_rule("/watchlist", "watchlist.add", lambda: "", methods=["POST"])
    app.jinja_loader = ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"}),
        FileSystemLoader(ROOT / "templates"),
    ])
    user = SimpleNamespace(is_authenticated=True, email="test@example.invalid",
                           plan_type="premium", is_premium=True, telegram_verified=True)
    monkeypatch.setattr(search_route, "current_user", user)
    monkeypatch.setattr(alerts_route, "current_user", user)
    app.context_processor(lambda: {"current_user": user})
    return app


def _text(html):
    return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)


@pytest.mark.parametrize("source", ["kleinanzeigen", "both", "all", "ebay"])
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_disabled_search_renders_real_templates_and_keeps_ebay(app, source, method):
    values = {"q": "test", "source": source}
    request_args = {"query_string": values} if method == "GET" else {"data": values}
    with (
        patch.object(ka, "_create_session") as http_session,
        patch.object(search_route, "backend_search_ebay", return_value=([EBAY_ITEM], 1)) as ebay,
        patch.object(search_route, "track_item_price") as track,
        app.test_request_context("/search", method=method, **request_args),
    ):
        html = search_route.search_page()
    text = _text(html)
    assert "Kleinanzeigen-Treffer sind Live-Daten" not in text
    assert "Noch keine Treffer" not in text
    assert (PAUSE in text) == (source != "ebay")
    assert ("eBay Testangebot" in text) == (source != "kleinanzeigen")
    assert ebay.call_count == int(source != "kleinanzeigen")
    assert track.call_count == int(source != "kleinanzeigen")
    http_session.assert_not_called()
    soup = BeautifulSoup(html, "html.parser")
    assert soup.select_one('input[type="hidden"][name="source"]')["value"] == source


def test_combined_empty_search_only_describes_ebay_results(app):
    with (
        patch.object(search_route, "backend_search_ebay", return_value=([], 0)),
        app.test_request_context("/search?q=test&source=both"),
    ):
        text = _text(search_route.search_page())
    assert PAUSE in text
    assert "Die eBay-Suche hat keine Treffer geliefert. Kleinanzeigen wurde nicht abgefragt." in text
    assert "Noch keine Treffer" not in text


def test_initial_form_explains_pause_without_searching(app):
    with (
        patch.object(search_route, "backend_search_ebay") as ebay,
        patch.object(search_route, "backend_search_kleinanzeigen") as kleinanzeigen,
        app.test_request_context("/search?source=kleinanzeigen"),
    ):
        text = _text(search_route.search_page())
    assert PAUSE in text
    assert "Noch keine Treffer" not in text
    ebay.assert_not_called()
    kleinanzeigen.assert_not_called()


def test_reenabled_combined_search_shows_both_sources(app, monkeypatch):
    monkeypatch.setenv("ENABLE_KLEINANZEIGEN", "1")
    item = {**EBAY_ITEM, "id": "ka_1", "src": "kleinanzeigen",
            "title": "Kleinanzeigen Testangebot", "url": "https://example.invalid/ka"}
    result = ka.KleinanzeigenSearchResult([item], ka.KleinanzeigenSearchStatus.SUCCESS_WITH_RESULTS)
    with (
        patch.object(search_route, "backend_search_ebay", return_value=([EBAY_ITEM], 1)),
        patch.object(search_route, "backend_search_kleinanzeigen", return_value=result),
        patch.object(search_route, "track_item_price"),
        app.test_request_context("/search?q=test&source=both"),
    ):
        text = _text(search_route.search_page())
    assert PAUSE not in text
    assert "eBay Testangebot" in text
    assert "Kleinanzeigen Testangebot" in text


def _row(*, source="kleinanzeigen", active=1, last_run=100):
    return (17, '["test"]', "{}", source, last_run, active, 1, 1, 0, 0, "premium", True)


@pytest.mark.parametrize("active", [0, 1])
@pytest.mark.parametrize("last_run", [0, 100])
def test_alert_details_pause_without_seen_writes_or_schedule_promises(app, active, last_run):
    connection = Mock()
    cursor = connection.cursor.return_value
    cursor.fetchone.return_value = _row(active=active, last_run=last_run)
    with (
        patch.object(alerts_route, "get_db", return_value=connection),
        patch.object(ka, "_create_session") as http_session,
        app.test_request_context("/results/17"),
    ):
        text = _text(alerts_route.alert_results(17))
    assert PAUSE in text
    assert "Quelle pausiert" in text
    assert "Nächster Check" not in text
    assert "Aktuell gibt es keine passenden Angebote" not in text
    assert "Sobald neue Artikel auftauchen" not in text
    # Only ownership/metadata is read, no seen-item lookups or mutations.
    cursor.execute.assert_called_once()
    assert cursor.execute.call_args.args[0].strip().startswith("SELECT")
    connection.commit.assert_not_called()
    http_session.assert_not_called()


def test_manage_keeps_individual_activation_but_overlays_source_pause(app):
    connection = Mock()
    connection.cursor.return_value.fetchall.return_value = [_row(), _row(source="ebay")]
    with (
        patch.object(alerts_route, "get_db", return_value=connection),
        app.test_request_context("/manage"),
    ):
        html = alerts_route.manage_alerts()
    soup = BeautifulSoup(html, "html.parser")
    ka_row, ebay_row = soup.select("tbody tr")
    assert "Quelle pausiert" in ka_row.get_text()
    assert "Nächster Check" not in ka_row.get_text()
    assert "Pausieren" in ka_row.get_text()
    assert "Quelle pausiert" not in ebay_row.get_text()
    assert "Nächster Check" in ebay_row.get_text()
    assert "Aktiv" in ebay_row.get_text()
    connection.commit.assert_not_called()


@pytest.mark.parametrize("source, saved_sources", [
    ("kleinanzeigen", ["kleinanzeigen"]), ("both", ["ebay", "kleinanzeigen"]), ("ebay", ["ebay"]),
])
def test_save_preserves_alerts_and_reports_pause(app, source, saved_sources):
    connection = Mock()
    with (
        patch.object(alerts_route, "get_db", return_value=connection),
        app.test_request_context("/subscribe", method="POST", data={
            "q1": "test", "source": source, "notify_email": "1", "notify_telegram": "1",
        }),
    ):
        response = alerts_route.alerts_subscribe()
        messages = " ".join(get_flashed_messages())
    assert response.status_code == 302
    inserts = connection.cursor.return_value.execute.call_args_list
    assert [call.args[1][3] for call in inserts] == saved_sources
    assert all(call.args[1][4] == 0 for call in inserts)  # new-alert timestamp
    assert all("1," in call.args[0] for call in inserts)  # is_active stays enabled
    assert (PAUSE in messages) == (source != "ebay")
    if source != "ebay":
        assert "Du wirst bei neuen Treffern benachrichtigt" not in messages
    connection.commit.assert_called_once()


def _app_function(name, **namespace):
    """Load only a legacy view body; importing app.py would initialize services."""
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    function.decorator_list = []
    module = ast.Module(body=[function], type_ignores=[])
    scope = dict(json=json, datetime=datetime, ceil=ceil, request=request, session=session,
                 flash=flash, redirect=redirect, url_for=url_for, safe_render=render_template,
                 current_app=None, ADMIN_EMAILS={"test@example.invalid"},
                 is_kleinanzeigen_enabled=ka.is_kleinanzeigen_enabled)
    scope.update(namespace)
    exec(compile(module, str(ROOT / "app.py"), "exec"), scope)
    return scope[name]


def test_other_reachable_management_view_also_shows_pause(app):
    cursor = Mock()
    columns = ["id", "terms_json", "filters_json", "source", "is_active"]
    cursor.description = [(column,) for column in columns]
    cursor.fetchall.return_value = [(17, '["test"]', "{}", "kleinanzeigen", 1)]
    connection = Mock()
    connection.cursor.return_value = cursor
    view = _app_function("alerts_manage", get_db=lambda: connection)
    with app.test_request_context("/alerts/manage"):
        session.update(user_id=1, user_email="test@example.invalid")
        text = _text(view())
    assert PAUSE in text
    assert "Quelle pausiert" in text
    connection.commit.assert_not_called()


def test_saved_history_explains_that_results_are_not_current(app):
    connection = Mock()
    cursor = connection.cursor.return_value
    cursor.fetchone.side_effect = [(17, "test@example.invalid", '["test"]', "kleinanzeigen"), (0,)]
    cursor.fetchall.return_value = []
    view = _app_function("alert_results", get_db=lambda: connection)
    with app.test_request_context("/alerts/17/results"):
        session.update(user_id=1, user_email="test@example.invalid")
        text = _text(view(17))
    assert PAUSE in text
    assert "früher gespeicherte Ergebnisse" in text
    connection.commit.assert_not_called()


def test_other_reachable_save_view_explains_pause(app):
    connection = Mock()
    view = _app_function(
        "alerts_subscribe", get_db=lambda: connection, dict_cursor=lambda conn: conn.cursor(),
        _find_existing_active_alert=lambda **kwargs: None,
        _normalize_alert_terms=lambda terms: terms, _normalize_alert_filters=lambda filters: filters,
    )
    with app.test_request_context("/alerts/subscribe", method="POST", data={
        "q1": "test", "source": "kleinanzeigen", "notify_email": "1",
    }):
        session.update(user_id=1, user_email="test@example.invalid")
        response = view()
        messages = " ".join(get_flashed_messages())
    assert response.status_code == 302
    assert PAUSE in messages
    assert "neue Treffer werden automatisch geprüft" not in messages
    connection.commit.assert_called_once()
