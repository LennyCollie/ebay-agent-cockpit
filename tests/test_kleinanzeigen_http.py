"""Offline HTTP and status tests for the Kleinanzeigen search path."""

import logging
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests

from services.kleinanzeigen import (
    KleinanzeigenSearchStatus as Status,
    _create_session,
    search_kleinanzeigen,
)
from services.kleinanzeigen_backend import backend_search_kleinanzeigen


FIXTURE = (
    Path(__file__).parent / "fixtures" / "kleinanzeigen_sample.html"
).read_text(encoding="utf-8")


class FakeResponse:
    def __init__(
        self,
        status=200,
        text=FIXTURE,
        content_type="text/html; charset=utf-8",
        url="https://www.kleinanzeigen.de/s-test/k0",
        history=None,
    ):
        self.status_code = status
        self.text = text
        self.headers = {"Content-Type": content_type}
        self.url = url
        self.history = [] if history is None else history
        self.encoding = None

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


def run_with_response(response):
    session = Mock()
    session.get.return_value = response
    with patch("services.kleinanzeigen._create_session", return_value=session):
        result = search_kleinanzeigen("test", limit=3)
    session.close.assert_called_once()
    return result, session


def test_http_200_with_results():
    result, _ = run_with_response(FakeResponse())
    assert result.status is Status.SUCCESS_WITH_RESULTS
    assert len(result.results) == 3


def test_http_200_regular_empty_page():
    html = "<html><title>Suche</title><body>Keine Anzeigen gefunden</body></html>"
    result, _ = run_with_response(FakeResponse(text=html))
    assert result.status is Status.SUCCESS_EMPTY
    assert result.results == []


def test_price_filter_can_produce_successful_empty_result():
    session = Mock()
    session.get.return_value = FakeResponse()
    with patch("services.kleinanzeigen._create_session", return_value=session):
        result = search_kleinanzeigen("test", price_min=5000, limit=3)
    assert result.status is Status.SUCCESS_EMPTY
    assert result.results == []


def test_unexpected_content_type_is_invalid_response():
    result, _ = run_with_response(
        FakeResponse(text="opaque", content_type="application/octet-stream")
    )
    assert result.status is Status.INVALID_RESPONSE


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        ("", Status.INVALID_RESPONSE),
        ("<html><body>unbekannte Seite</body></html>", Status.INVALID_RESPONSE),
        ("<html><title>Cookie-Einstellungen</title></html>", Status.CONSENT_REQUIRED),
        ("<html><body>Bitte bestätigen Sie, dass Sie kein Roboter sind</body></html>", Status.CAPTCHA_OR_CHALLENGE),
        ("<html><body>Ihre Anfrage wurde blockiert</body></html>", Status.BLOCKED),
    ),
)
def test_http_200_special_pages(text, expected):
    result, _ = run_with_response(FakeResponse(text=text))
    assert result.status is expected
    assert result.results == []


@pytest.mark.parametrize(
    ("status_code", "expected", "retryable"),
    ((403, Status.HTTP_FORBIDDEN, False), (429, Status.RATE_LIMITED, True)),
)
def test_403_and_429_skip_parser(status_code, expected, retryable):
    with patch("services.kleinanzeigen._parse_html_article") as parser:
        result, session = run_with_response(FakeResponse(status=status_code, text="SECRET BODY"))
    assert result.status is expected
    assert result.retryable is retryable
    assert result.results == []
    parser.assert_not_called()
    session.get.assert_called_once()


def test_403_and_429_are_not_in_retry_statuses():
    retries = _create_session().get_adapter("https://").max_retries
    assert 403 not in retries.status_forcelist
    assert 429 not in retries.status_forcelist


def test_redirect_to_results_is_successful():
    result, _ = run_with_response(FakeResponse(history=[Mock(status_code=302)]))
    assert result.status is Status.SUCCESS_WITH_RESULTS


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        ("<html><title>Cookie-Einstellungen</title></html>", Status.CONSENT_REQUIRED),
        ("<html><body>Access denied</body></html>", Status.BLOCKED),
    ),
)
def test_redirect_to_special_page(text, expected):
    result, _ = run_with_response(FakeResponse(text=text, history=[Mock(status_code=302)]))
    assert result.status is expected


@pytest.mark.parametrize("error", (requests.Timeout(), requests.ConnectionError()))
def test_network_errors_are_source_unavailable(error):
    session = Mock()
    session.get.side_effect = error
    with patch("services.kleinanzeigen._create_session", return_value=session):
        result = search_kleinanzeigen("test")
    assert result.status is Status.SOURCE_UNAVAILABLE
    assert result.retryable is True


def test_response_body_is_not_logged(caplog):
    caplog.set_level(logging.DEBUG)
    result, _ = run_with_response(FakeResponse(status=500, text="VERY_SECRET_RESPONSE"))
    assert result.status is Status.SOURCE_UNAVAILABLE
    assert "VERY_SECRET_RESPONSE" not in caplog.text


def test_backend_propagates_failure_without_normalizing_results():
    failure = Mock(
        status=Status.HTTP_FORBIDDEN,
        results=[],
        reason="http_403",
        http_status=403,
        retryable=False,
    )
    with patch("services.kleinanzeigen_backend.search_kleinanzeigen", return_value=failure):
        result = backend_search_kleinanzeigen(["test"], {}, per_page=3)
    assert result.status is Status.HTTP_FORBIDDEN
    assert result.results == []
