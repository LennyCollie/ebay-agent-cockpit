"""Offline propagation tests for Kleinanzeigen alert failures."""

from unittest.mock import Mock, patch

import alert_checker
from services.kleinanzeigen import KleinanzeigenSearchResult, KleinanzeigenSearchStatus


def test_alert_failure_skips_smart_filter_and_novelty_check():
    cursor = Mock()
    cursor.fetchone.return_value = {
        "telegram_chat_id": None,
        "telegram_enabled": False,
        "telegram_verified": False,
        "plan_type": "free",
        "is_premium": False,
    }
    alert = {
        "id": 7,
        "user_email": "test@example.invalid",
        "terms_json": '["test"]',
        "filters_json": '{"only_main_product": true}',
        "source": "kleinanzeigen",
        "notify_telegram": 0,
        "notify_email": 0,
    }
    stats = {
        "alerts_checked": 0,
        "ebay_alerts": 0,
        "kleinanzeigen_alerts": 0,
        "new_items_found": 0,
        "notifications_sent": 0,
        "errors": 0,
    }
    failure = KleinanzeigenSearchResult(
        results=[],
        status=KleinanzeigenSearchStatus.HTTP_FORBIDDEN,
        reason="http_403",
        http_status=403,
    )

    with (
        patch.object(alert_checker, "search_kleinanzeigen_for_alert", return_value=failure),
        patch.object(alert_checker, "SmartFilter") as smart_filter,
        patch.object(alert_checker, "find_new_items") as find_new_items,
        patch.object(alert_checker, "update_alert_timestamp") as update_timestamp,
    ):
        alert_checker.process_single_alert(alert, cursor, Mock(), stats)

    smart_filter.assert_not_called()
    find_new_items.assert_not_called()
    update_timestamp.assert_called_once()
    assert stats["errors"] == 1
    assert stats["kleinanzeigen_alerts"] == 1
