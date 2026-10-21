"""Administrative source pauses must stop I/O without changing alert state."""

from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

import alert_checker
from services import kleinanzeigen as ka
from services.kleinanzeigen_backend import backend_search_kleinanzeigen


@pytest.mark.parametrize("value", [None, "0", "", "true", "false", "2", "1 ", " 1"])
@pytest.mark.parametrize("query", ["Wohnwagen", ""])
def test_disabled_source_never_creates_a_session(monkeypatch, value, query):
    if value is None:
        monkeypatch.delenv("ENABLE_KLEINANZEIGEN", raising=False)
    else:
        monkeypatch.setenv("ENABLE_KLEINANZEIGEN", value)
    with (
        patch.object(ka, "_create_session") as create_session,
        patch.object(ka.requests, "Session") as session,
    ):
        result = ka.search_kleinanzeigen(query)

    assert not ka.is_kleinanzeigen_enabled()
    assert result.status is ka.KleinanzeigenSearchStatus.SOURCE_DISABLED
    assert result.results == []
    assert result.reason == "disabled_by_config"
    assert result.http_status is None
    assert result.retryable is False
    create_session.assert_not_called()
    session.assert_not_called()


def test_backend_stops_after_disabled_result(monkeypatch):
    monkeypatch.setenv("ENABLE_KLEINANZEIGEN", "0")
    with patch(
        "services.kleinanzeigen_backend.search_kleinanzeigen",
        wraps=ka.search_kleinanzeigen,
    ) as search:
        result = backend_search_kleinanzeigen(["Wohnwagen", "Camper"], {})
    search.assert_called_once()
    assert result.status is ka.KleinanzeigenSearchStatus.SOURCE_DISABLED
    assert result.results == []
    assert result.retryable is False


def test_switch_is_read_for_every_search_and_can_be_reenabled(monkeypatch):
    html = (Path(__file__).parent / "fixtures" / "kleinanzeigen_sample.html").read_text(encoding="utf-8")
    response = Mock(status_code=200, headers={"Content-Type": "text/html"}, text=html)
    session = Mock()
    session.get.return_value = response
    with patch.object(ka, "_create_session", return_value=session) as create_session:
        for value, expected in (
            ("0", ka.KleinanzeigenSearchStatus.SOURCE_DISABLED),
            ("1", ka.KleinanzeigenSearchStatus.SUCCESS_WITH_RESULTS),
            ("0", ka.KleinanzeigenSearchStatus.SOURCE_DISABLED),
        ):
            monkeypatch.setenv("ENABLE_KLEINANZEIGEN", value)
            assert ka.search_kleinanzeigen("iphone").status is expected
    create_session.assert_called_once()
    session.get.assert_called_once()


def _stats():
    return dict(alerts_checked=0, ebay_alerts=0, kleinanzeigen_alerts=0,
                new_items_found=0, notifications_sent=0, errors=0)


def _alert(last_run_ts=0, source="kleinanzeigen"):
    return dict(id=17, user_email="test@example.invalid", terms_json='["test"]',
                filters_json='{"smart_filter": true}', source=source,
                last_run_ts=last_run_ts, is_active=1, notify_telegram=1, notify_email=1)


@pytest.mark.parametrize("last_run_ts", [0, 100])
@pytest.mark.parametrize("value", [None, "0", "invalid"])
def test_cron_skips_paused_alert_without_reading_or_writing_user_state(monkeypatch, last_run_ts, value):
    if value is None:
        monkeypatch.delenv("ENABLE_KLEINANZEIGEN", raising=False)
    else:
        monkeypatch.setenv("ENABLE_KLEINANZEIGEN", value)
    alert = _alert(last_run_ts)
    original = deepcopy(alert)
    stats = _stats()
    cursor, connection = Mock(), Mock()
    with (
        patch.object(alert_checker, "search_kleinanzeigen_for_alert") as search,
        patch.object(alert_checker, "SmartFilter") as smart_filter,
        patch.object(alert_checker, "find_new_items") as seen,
        patch.object(alert_checker, "update_alert_timestamp") as timestamp,
        patch.object(alert_checker, "send_email_alert") as email,
        patch.object(alert_checker, "send_telegram_alert") as telegram,
    ):
        # Repeated Cron runs, including new alerts, must remain side-effect free.
        for _ in range(2):
            alert_checker.process_single_alert(alert, cursor, connection, stats)
    for operation in (search, smart_filter, seen, timestamp, email, telegram):
        operation.assert_not_called()
    assert cursor.mock_calls == []
    assert connection.mock_calls == []
    assert alert == original
    assert stats == _stats()


def _user_cursor(plan_type="premium"):
    cursor = Mock()
    cursor.fetchone.return_value = dict(telegram_chat_id="123", telegram_enabled=True,
                                      telegram_verified=True, plan_type=plan_type, is_premium=False)
    return cursor


@pytest.mark.parametrize("last_run_ts", [0, 100])
def test_disabled_status_from_search_is_not_an_error_or_a_completed_check(monkeypatch, last_run_ts):
    monkeypatch.setenv("ENABLE_KLEINANZEIGEN", "1")
    paused = ka.KleinanzeigenSearchResult([], ka.KleinanzeigenSearchStatus.SOURCE_DISABLED)
    stats = _stats()
    with (
        patch.object(alert_checker.time, "time", return_value=10000),
        patch.object(alert_checker, "search_kleinanzeigen_for_alert", return_value=paused),
        patch.object(alert_checker, "find_new_items") as seen,
        patch.object(alert_checker, "update_alert_timestamp") as timestamp,
        patch.object(alert_checker, "send_email_alert") as email,
        patch.object(alert_checker, "send_telegram_alert") as telegram,
    ):
        alert_checker.process_single_alert(_alert(last_run_ts), _user_cursor(), Mock(), stats)
    for operation in (seen, timestamp, email, telegram):
        operation.assert_not_called()
    assert stats == _stats()


@pytest.mark.parametrize("plan_type, notifications", [("free", 1), ("pro", 2), ("premium", 2)])
def test_ebay_still_searches_and_notifies_while_kleinanzeigen_is_paused(monkeypatch, plan_type, notifications):
    monkeypatch.setenv("ENABLE_KLEINANZEIGEN", "0")
    alert = _alert(last_run_ts=100, source="ebay")
    alert["filters_json"] = "{}"
    item = {"id": "ebay-1", "title": "Test", "url": "https://example.invalid/item"}
    stats = _stats()
    with (
        patch.object(alert_checker.time, "time", return_value=10000),
        patch.object(alert_checker.time, "sleep"),
        patch("services.ebay_backend.backend_search_ebay", return_value=([item], 1)) as ebay,
        patch.object(alert_checker, "search_kleinanzeigen_for_alert") as ka_search,
        patch.object(alert_checker, "find_new_items", return_value=[item]),
        patch.object(alert_checker, "update_alert_timestamp") as timestamp,
        patch.object(alert_checker, "send_email_alert", return_value=True) as email,
        patch.object(alert_checker, "send_telegram_alert", return_value=True) as telegram,
    ):
        alert_checker.process_single_alert(alert, _user_cursor(plan_type), Mock(), stats)
    ebay.assert_called_once()
    ka_search.assert_not_called()
    timestamp.assert_called_once()
    email.assert_called_once()
    assert telegram.call_count == notifications - 1
    assert stats == dict(alerts_checked=1, ebay_alerts=1, kleinanzeigen_alerts=0,
                         new_items_found=1, notifications_sent=notifications, errors=0)


@pytest.mark.parametrize("plan_type, interval", [("free", 1800), ("pro", 180), ("premium", 180)])
@pytest.mark.parametrize("grace", [0, 20])
def test_ebay_due_times_are_unchanged_during_pause(monkeypatch, plan_type, interval, grace):
    monkeypatch.setenv("ENABLE_KLEINANZEIGEN", "0")
    monkeypatch.setattr(alert_checker, "GRACE_SECONDS", grace)
    now = 10000
    for elapsed, expected_calls in [(interval - grace - 1, 0), (interval - grace, 1)]:
        stats = _stats()
        alert = _alert(last_run_ts=now - elapsed, source="ebay")
        alert["filters_json"] = "{}"
        with (
            patch.object(alert_checker.time, "time", return_value=now),
            patch.object(alert_checker, "search_ebay_for_alert", return_value=[]) as search,
            patch.object(alert_checker, "find_new_items", return_value=[]),
            patch.object(alert_checker, "update_alert_timestamp") as timestamp,
        ):
            alert_checker.process_single_alert(alert, _user_cursor(plan_type), Mock(), stats)
        assert search.call_count == expected_calls
        assert timestamp.call_count == expected_calls
        assert stats["alerts_checked"] == expected_calls
        assert stats["errors"] == 0


def test_paused_new_alert_keeps_first_run_behavior_after_reenable(monkeypatch):
    alert = _alert(last_run_ts=0)
    alert["filters_json"] = "{}"
    item = {"id": "ka_1", "title": "Test"}
    result = ka.KleinanzeigenSearchResult([item], ka.KleinanzeigenSearchStatus.SUCCESS_WITH_RESULTS)
    with (
        patch.object(alert_checker.time, "time", return_value=10000),
        patch.object(alert_checker, "search_kleinanzeigen_for_alert", return_value=result) as search,
        patch.object(alert_checker, "find_new_items", return_value=[item]) as seen,
        patch.object(alert_checker, "update_alert_timestamp") as timestamp,
        patch.object(alert_checker, "send_email_alert") as email,
        patch.object(alert_checker, "send_telegram_alert") as telegram,
    ):
        monkeypatch.setenv("ENABLE_KLEINANZEIGEN", "0")
        alert_checker.process_single_alert(alert, _user_cursor(), Mock(), _stats())
        timestamp.assert_not_called()
        monkeypatch.setenv("ENABLE_KLEINANZEIGEN", "1")
        alert_checker.process_single_alert(alert, _user_cursor(), Mock(), _stats())
    search.assert_called_once()
    seen.assert_called_once()
    timestamp.assert_called_once()
    email.assert_not_called()
    telegram.assert_not_called()
