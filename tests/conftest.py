"""Keep the unit suite offline, including imports with application side effects.

database.py initializes real tables on import. Replace that boundary before
collecting tests; mail and Telegram are also test doubles, never live clients.
Individual tests supply their own cursors, search responses and send results.
"""

import socket
import sqlite3
import sys
from types import ModuleType

import dotenv
import psycopg2
import pytest
import requests


_isolation = pytest.MonkeyPatch()
_unexpected_access = []


def _blocked(boundary):
    def reject(*args, **kwargs):
        _unexpected_access.append(boundary)
        raise AssertionError(f"Offline test attempted {boundary}; supply a test double")

    return reject


def pytest_configure(config):
    _isolation.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    _isolation.setenv("KLEINANZEIGEN_DEBUG_HTML", "0")
    _isolation.setenv("ALERT_INTERVAL_FREE", "30")
    _isolation.setenv("ALERT_INTERVAL_PREMIUM", "3")
    _isolation.setenv("ALERT_GRACE_SECONDS", "20")

    _isolation.setattr(requests.sessions.Session, "request", _blocked("HTTP"))
    for name in ("connect", "connect_ex", "sendto"):
        _isolation.setattr(socket.socket, name, _blocked("socket"))
    for name in ("create_connection", "getaddrinfo"):
        _isolation.setattr(socket, name, _blocked("network/DNS"))
    _isolation.setattr(sqlite3, "connect", _blocked("SQLite"))
    _isolation.setattr(psycopg2, "connect", _blocked("PostgreSQL"))

    database = ModuleType("database")
    database.get_db = _blocked("database.get_db")
    database.dict_cursor = lambda connection: connection.cursor()
    database.get_placeholder = lambda: "?"
    database.IS_POSTGRES = False
    database.init_db = _blocked("database.init_db")

    agent = ModuleType("agent")
    agent.get_mail_settings = _blocked("mail configuration")
    agent.send_mail = _blocked("mail delivery")

    telegram = ModuleType("telegram_bot")
    telegram.send_new_item_alert = _blocked("Telegram delivery")

    for module in (database, agent, telegram):
        _isolation.setitem(sys.modules, module.__name__, module)


@pytest.fixture(autouse=True)
def assert_no_external_access():
    # Also fail if production code catches an exception from a blocked boundary.
    assert not _unexpected_access, "External access attempted during test collection"
    yield
    attempted = list(_unexpected_access)
    _unexpected_access.clear()
    assert not attempted, f"Unexpected external access: {attempted}"


def pytest_unconfigure(config):
    _isolation.undo()
