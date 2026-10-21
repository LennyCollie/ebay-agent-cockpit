"""Offline due-time tests, including the existing 20-second Cron tolerance."""

from unittest.mock import ANY, Mock, patch

import pytest

import alert_checker
from services.kleinanzeigen import KleinanzeigenSearchResult, KleinanzeigenSearchStatus


@pytest.fixture(autouse=True)
def enable_source(monkeypatch):
    monkeypatch.setenv("ENABLE_KLEINANZEIGEN", "1")


def _stats():
    return {
        "alerts_checked": 0,
        "ebay_alerts": 0,
        "kleinanzeigen_alerts": 0,
        "new_items_found": 0,
        "notifications_sent": 0,
        "errors": 0,
    }


def _alert(*, last_run_ts=0):
    return {
        "id": 17,
        "user_email": "test@example.invalid",
        "terms_json": '["test"]',
        "filters_json": "{}",
        "last_run_ts": last_run_ts,
        "source": "kleinanzeigen",
        "notify_telegram": 1,
        "notify_email": 1,
    }


def _cursor(*, plan_type="free", is_premium=False):
    cursor = Mock()
    cursor.fetchone.return_value = {
        "telegram_chat_id": "123",
        "telegram_enabled": True,
        "telegram_verified": True,
        "plan_type": plan_type,
        "is_premium": is_premium,
    }
    return cursor


def _result(status=KleinanzeigenSearchStatus.SUCCESS_EMPTY):
    return KleinanzeigenSearchResult(
        results=[],
        status=status,
        retryable=status in {
            KleinanzeigenSearchStatus.RATE_LIMITED,
            KleinanzeigenSearchStatus.SOURCE_UNAVAILABLE,
        },
    )


def _run(alert, cursor, stats, *, now, result=None):
    result = result or _result()
    with (
        patch.object(alert_checker.time, "time", return_value=now),
        patch.object(
            alert_checker,
            "search_kleinanzeigen_for_alert",
            return_value=result,
        ) as search,
        patch.object(alert_checker, "find_new_items", return_value=[]) as find_new,
        patch.object(alert_checker, "send_telegram_alert") as telegram,
        patch.object(alert_checker, "send_email_alert") as email,
        patch.object(alert_checker, "update_alert_timestamp") as update,
    ):
        alert_checker.process_single_alert(alert, cursor, Mock(), stats)
    return search, find_new, telegram, email, update


@pytest.mark.parametrize(
    ("elapsed", "is_due"),
    ((1779, False), (1780, True), (1799, True), (1800, True), (1801, True)),
)
def test_free_alert_before_and_after_interval(elapsed, is_due):
    now = 10_000
    stats = _stats()
    calls = _run(
        _alert(last_run_ts=now - elapsed),
        _cursor(),
        stats,
        now=now,
    )

    assert calls[0].call_count == int(is_due)
    assert calls[1].call_count == int(is_due)
    assert calls[4].call_count == int(is_due)
    assert stats["alerts_checked"] == int(is_due)
    calls[2].assert_not_called()
    calls[3].assert_not_called()


@pytest.mark.parametrize(
    ("plan_type", "is_premium"),
    (("premium", False), ("pro", False), ("free", True)),
)
@pytest.mark.parametrize(("elapsed", "is_due"), ((159, False), (160, True), (179, True), (180, True)))
def test_premium_and_pro_alert_before_and_after_interval(
    plan_type,
    is_premium,
    elapsed,
    is_due,
):
    now = 10_000
    stats = _stats()
    calls = _run(
        _alert(last_run_ts=now - elapsed),
        _cursor(plan_type=plan_type, is_premium=is_premium),
        stats,
        now=now,
    )

    assert calls[0].call_count == int(is_due)
    assert calls[4].call_count == int(is_due)
    assert stats["alerts_checked"] == int(is_due)


def test_new_alert_without_timestamp_is_due_immediately():
    alert = _alert()
    alert.pop("last_run_ts")
    stats = _stats()
    calls = _run(alert, _cursor(), stats, now=10_000)

    calls[0].assert_called_once()
    calls[1].assert_called_once()
    calls[4].assert_called_once_with(17, 10_000, ANY)
    calls[2].assert_not_called()
    calls[3].assert_not_called()
    assert stats["alerts_checked"] == 1


@pytest.mark.parametrize(
    "status",
    (
        KleinanzeigenSearchStatus.HTTP_FORBIDDEN,
        KleinanzeigenSearchStatus.RATE_LIMITED,
        KleinanzeigenSearchStatus.SOURCE_UNAVAILABLE,
    ),
)
def test_source_failure_is_timestamped_and_then_throttled(status):
    now = 10_000
    first_stats = _stats()
    first = _run(
        _alert(last_run_ts=now - 1800),
        _cursor(),
        first_stats,
        now=now,
        result=_result(status),
    )

    first[0].assert_called_once()
    first[1].assert_not_called()
    first[2].assert_not_called()
    first[3].assert_not_called()
    first[4].assert_called_once_with(17, now, ANY)
    assert first_stats["alerts_checked"] == 1
    assert first_stats["errors"] == 1

    repeated_stats = _stats()
    repeated = _run(
        _alert(last_run_ts=now),
        _cursor(),
        repeated_stats,
        now=now + 180,
        result=_result(status),
    )
    for call in repeated:
        call.assert_not_called()
    assert repeated_stats["alerts_checked"] == 0
    assert repeated_stats["errors"] == 0


def test_repeated_cron_call_skips_free_alert_until_interval_elapsed():
    now = 20_000
    first_stats = _stats()
    first = _run(_alert(last_run_ts=0), _cursor(), first_stats, now=now)
    first[0].assert_called_once()
    first[4].assert_called_once()

    skipped_stats = _stats()
    skipped = _run(
        _alert(last_run_ts=now),
        _cursor(),
        skipped_stats,
        now=now + 3 * 60,
    )
    for call in skipped:
        call.assert_not_called()
    assert skipped_stats["alerts_checked"] == 0

    due_stats = _stats()
    due = _run(
        _alert(last_run_ts=now),
        _cursor(),
        due_stats,
        now=now + 30 * 60,
    )
    due[0].assert_called_once()
    assert due_stats["alerts_checked"] == 1


def test_future_timestamp_is_not_due_and_has_no_side_effects():
    stats = _stats()
    calls = _run(
        _alert(last_run_ts=11_000),
        _cursor(),
        stats,
        now=10_000,
    )

    for call in calls:
        call.assert_not_called()
    assert stats == _stats()
