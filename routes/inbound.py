# routes/inbound.py
from __future__ import annotations

import base64
import fnmatch
import hmac
import hashlib
import logging
import os
from datetime import datetime
from typing import Any, Dict

from flask import Blueprint, request, abort, current_app, has_app_context

bp = Blueprint("inbound", __name__)

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
_logger = logging.getLogger("inbound")

def _log(level: str, msg: str, *args: Any) -> None:
    if has_app_context():
        getattr(current_app.logger, level)(msg, *args)
    else:
        getattr(_logger, level)(msg, *args)

# -----------------------------------------------------------------------------
# store_event – sichere Fallback-Implementation, echte Version optional
# -----------------------------------------------------------------------------
def store_event(source: str, payload: Dict[str, Any]) -> None:
    _log(
        "warning",
        "store_event STUB used | source=%s | subject=%s | received=%s",
        source,
        payload.get("Subject"),
        datetime.utcnow().isoformat() + "Z",
    )

try:
    from services.inbound_store import store_event as _real_store_event  # type: ignore
    store_event = _real_store_event  # noqa: F811
except Exception as e:
    _log("info", "using store_event STUB (import failed): %s", e)

# -----------------------------------------------------------------------------
# Kleinanzeigen-Parser optional
# -----------------------------------------------------------------------------
def _is_from_kleinanzeigen(_payload: Dict[str, Any]) -> bool:
    return False

def _extract_summary(_payload: Dict[str, Any]) -> Dict[str, Any]:
    return {}

try:
    from services.kleinanzeigen_parser import (  # type: ignore
        is_from_kleinanzeigen as _is_from_kleinanzeigen,
        extract_summary as _extract_summary,
    )
    _log("info", "kleinanzeigen_parser available")
except Exception as e:
    _log("info", "kleinanzeigen_parser not available (ok): %s", e)

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _ok_sender(sender: str) -> bool:
    """
    INBOUND_ALLOWED_SENDERS: kommagetrennt, Wildcards erlaubt.
    Beispiel: '*postmarkapp.com, *kleinanzeigen.de'
    """
    allow = os.getenv("INBOUND_ALLOWED_SENDERS", "")
    if not allow.strip():
        return True
    s = (sender or "").lower().strip()
    for patt in [p.strip().lower() for p in allow.split(",") if p.strip()]:
        if fnmatch.fnmatch(s, patt):
            return True
    return False

def _basic_ok() -> bool:
    user = os.getenv("INBOUND_BASIC_USER")
    pw = os.getenv("INBOUND_BASIC_PASS")
    if not user or not pw:
        return True
    auth = request.headers.get("Authorization", "")
    expected = "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()
    return hmac.compare_digest(auth, expected)

def _signature_ok(raw_body: bytes) -> bool:
    """
    Postmark Inbound HMAC-SHA256 (Base64) – nur prüfen, wenn Secret gesetzt.
    Header: X-Postmark-Signature
    """
    key = os.getenv("POSTMARK_INBOUND_SIGNING_SECRET", "")
    if not key:
        return True
    sig = request.headers.get("X-Postmark-Signature", "")
    digest = hmac.new(key.encode(), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(sig, expected)

def _get_sender(data: Dict[str, Any]) -> str:
    return ((data.get("FromFull") or {}).get("Email")
            or data.get("From")
            or "").strip()

# -----------------------------------------------------------------------------
# Route
# -----------------------------------------------------------------------------
@bp.route("/inbound/postmark", methods=["GET", "POST"])
def inbound_postmark():
    # 0) Healthcheck
    if request.method == "GET":
        return "inbound ok", 200

    # 1) URL-Secret (Pflicht)
    if request.args.get("secret") != os.getenv("INBOUND_SECRET", ""):
        abort(401)

    # 2) Optional Basic-Auth
    if not _basic_ok():
        abort(401)

    # 3) Optionale Signaturprüfung (nur wenn Secret gesetzt)
    raw = request.get_data()
    if not _signature_ok(raw):
        abort(401)

    # 4) Payload
    data: Dict[str, Any] = request.get_json(silent=True) or {}
    sender = _get_sender(data)

    # 5) Allow-List
    if not _ok_sender(sender):
        _log("warning", "Inbound blocked by sender filter: %s", sender)
        abort(403)

    # 6) Normiertes Event
    event: Dict[str, Any] = {
        "Subject": data.get("Subject") or "",
        "From": sender,
        "TextBody": data.get("TextBody") or "",
        "HtmlBody": data.get("HtmlBody") or "",
        "MessageID": data.get("MessageID") or "",
        "ReceivedAt": datetime.utcnow().isoformat() + "Z",
        "Raw": data,
    }

    # 7) Mini-Parser (optional & fail-safe)
    try:
        if _is_from_kleinanzeigen(data):
            event["Summary"] = _extract_summary(data) or {}
    except Exception as e:
        _log("warning", "extract_summary failed: %s", e)

    # 8) Persistenz / Weiterverarbeitung
    try:
        store_event("postmark", event)
    except Exception as e:
        _log("error", "store_event failed: %s", e)

    # 9) Immer 200, sonst retried Postmark
    return "ok", 200
