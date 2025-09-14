# routes/inbound.py
from __future__ import annotations

import base64
import fnmatch
import hashlib
import hmac
import logging
import os
from datetime import datetime
from typing import Dict, Any

from flask import Blueprint, request, abort, current_app, has_app_context

bp = Blueprint("inbound", __name__)

# ---------------------------------------------------------------------------
# Logging utilities
# ---------------------------------------------------------------------------

logger = logging.getLogger("inbound")

def _log(level: str, msg: str, *args: Any) -> None:
    """Loggt sicher – mit current_app.logger (falls Kontext), sonst std-Logger."""
    if has_app_context():
        getattr(current_app.logger, level)(msg, *args)
    else:
        getattr(logger, level)(msg, *args)

# ---------------------------------------------------------------------------
# Optional: Store-Adapter (Stub → kann durch services.inbound_store überschrieben werden)
# ---------------------------------------------------------------------------

def store_event(source: str, payload: Dict[str, Any]) -> None:
    """Fallback-Store: nur loggen (wird überschrieben, wenn echter Store vorhanden ist)."""
    _log("info", "store_event (STUB) source=%s subject=%s", source, payload.get("Subject"))

try:
    # wenn vorhanden, den echten Store benutzen
    from services.inbound_store import store_event as _real_store_event  # type: ignore
    store_event = _real_store_event  # noqa: F811
except Exception as e:
    _log("warning", "using store_event STUB (import failed): %s", e)

# ---------------------------------------------------------------------------
# Optional: Kleinanzeigen-Mini-Parser (sanft; wenn nicht vorhanden -> no-op)
# ---------------------------------------------------------------------------

def _is_from_kleinanzeigen(_payload: Dict[str, Any]) -> bool:
    return False

def _extract_summary(_payload: Dict[str, Any]) -> Dict[str, Any]:
    return {}

try:
    from services.kleinanzeigen_parser import (  # type: ignore
        is_from_kleinanzeigen as _is_from_kleinanzeigen,
        extract_summary as _extract_summary,
    )
except Exception as e:
    _log("info", "kleinanzeigen_parser not available (ok): %s", e)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_sender(data: Dict[str, Any]) -> str:
    """Zieht die Absenderadresse robust aus dem Postmark-Payload und normalisiert sie."""
    sender = ((data.get("FromFull") or {}) or {}).get("Email") or data.get("From") or ""
    return sender.strip().lower()

def _allowed_sender(sender: str) -> bool:
    """
    Allow-List per ENV INBOUND_ALLOWED_SENDERS.
    Beispiele: "*@kleinanzeigen.de, *@postmarkapp.com"
    Wildcards werden mit fnmatch unterstützt.
    Leere Liste ⇒ alles erlauben.
    """
    raw = (os.getenv("INBOUND_ALLOWED_SENDERS") or "").strip()
    if not raw:
        return True
    patterns = [p.strip().lower() for p in raw.split(",") if p.strip()]
    s = (sender or "").lower()
    for patt in patterns:
        if fnmatch.fnmatch(s, patt):
            return True
    return False

def _basic_ok() -> bool:
    """Optional: Basic-Auth, wenn INBOUND_BASIC_USER / INBOUND_BASIC_PASS gesetzt."""
    user = os.getenv("INBOUND_BASIC_USER") or ""
    pw = os.getenv("INBOUND_BASIC_PASS") or ""
    if not user or not pw:
        return True
    header = request.headers.get("Authorization", "")
    expected = "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()
    # timing-safe compare
    return hmac.compare_digest(header, expected)

def _signature_ok(raw_body: bytes) -> bool:
    """
    Optional: Postmark-Inbound-Signatur prüfen (HMAC-SHA256 Base64),
    wenn POSTMARK_INBOUND_SIGNING_SECRET gesetzt.
    """
    secret = os.getenv("POSTMARK_INBOUND_SIGNING_SECRET") or ""
    if not secret:
        return True
    recv_sig = request.headers.get("X-Postmark-Signature", "") or ""
    digest = hmac.new(secret.encode(), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(recv_sig, expected)

def _is_postmark_ping() -> bool:
    """
    Erlaubt Postmark-„Healthchecks“ mit User-Agent enthält 'postmark'
    und gleichzeitig fehlendem Absender. Solche Pings sollen immer 200 liefern.
    """
    ua = (request.headers.get("User-Agent") or "").lower()
    data = request.get_json(silent=True) or {}
    sender_present = bool(_get_sender(data))
    return ("postmark" in ua) and (not sender_present)

# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@bp.route("/inbound/postmark", methods=["GET", "POST"])
def inbound_postmark():
    # 0) einfacher Healthcheck
    if request.method == "GET":
        return "inbound ok", 200

    # 1) Secret in URL (Pflicht)
    if request.args.get("secret") != (os.getenv("INBOUND_SECRET") or ""):
        abort(401)

    # 1b) Postmark-Ping erlauben (User-Agent=Postmark & kein Sender)
    if _is_postmark_ping():
        _log("info", "Postmark ping OK (no sender; UA contains 'postmark')")
        return "ok", 200

    # 2) Optional Basic-Auth
    if not _basic_ok():
        abort(401)

    # 3) Optionale Signaturprüfung (HMAC)
    raw = request.get_data(cache=False, as_text=False)
    if not _signature_ok(raw):
        abort(401)

    # 4) Payload & Sender holen
    data: Dict[str, Any] = request.get_json(silent=True) or {}
    sender = _get_sender(data)

    # 5) Allow-List
    if not _allowed_sender(sender):
        _log("warning", "Inbound blocked by sender filter: %s", sender)
        abort(403)

    # 6) Event aufbereiten
    event: Dict[str, Any] = {
        "Subject": data.get("Subject") or "",
        "From": sender,
        "TextBody": data.get("TextBody") or "",
        "HtmlBody": data.get("HtmlBody") or "",
        "MessageID": data.get("MessageID") or "",
        "ReceivedAt": datetime.utcnow().isoformat() + "Z",
        "Raw": data,
    }

    # 7) Optional: Kleinanzeigen-Zusammenfassung
    try:
        if _is_from_kleinanzeigen(data):
            event["Summary"] = _extract_summary(data) or {}
    except Exception as e:
        _log("warning", "kleinanzeigen summary failed: %s", e)

    # 8) Speichern / Weiterverarbeiten
    try:
        store_event("postmark", event)
    except Exception as e:
        _log("error", "store_event failed: %s", e)

    return "ok", 200
