# routes/inbound.py
from __future__ import annotations

import os
import hmac
import base64
import hashlib
import fnmatch
import logging
from datetime import datetime
from typing import Dict, Any

from flask import Blueprint, request, abort, current_app, has_app_context

bp = Blueprint("inbound", __name__)


def _to_str(x) -> str:
    """Sicher zu String konvertieren (None -> '', Dict/List -> repr)."""
    if isinstance(x, str):
        return x
    if x is None:
        return ""
    return str(x)

def _ka_is_from(subject: str, text: str) -> bool:
    """Adapter für verschiedene Parser-Signaturen."""
    try:
        # Neuer Stil: is_from_kleinanzeigen(subject=..., text=...)
        return _is_from_kleinanzeigen(subject=subject, text=text)  # type: ignore
    except TypeError:
        try:
            # Alter Stil: is_from_kleinanzeigen(payload_dict)
            return _is_from_kleinanzeigen({"subject": subject, "text": text})  # type: ignore
        except Exception:
            return False

def _ka_extract_summary(subject: str, text: str) -> dict:
    """Adapter für verschiedene Parser-Signaturen."""
    try:
        # Neuer Stil
        return _extract_summary(subject=subject, text=text) or {}  # type: ignore
    except TypeError:
        try:
            # Alter Stil
            return _extract_summary({"subject": subject, "text": text}) or {}  # type: ignore
        except Exception:
            return {}


# --------------------------------------------------------------------------- #
# Logging (nutzt current_app.logger wenn verfügbar, sonst eigenen Logger)
# --------------------------------------------------------------------------- #
_logger = logging.getLogger("inbound")

def _log(level: str, msg: str, *args) -> None:
    if has_app_context():
        getattr(current_app.logger, level)(msg, *args)
    else:
        getattr(_logger, level)(msg, *args)

# --------------------------------------------------------------------------- #
# Store-Funktion (echte Implementierung optional, sonst Stub)
# --------------------------------------------------------------------------- #
def store_event(source: str, payload: Dict[str, Any]) -> None:
    # Stub – wird überschrieben, falls echte Funktion vorhanden ist
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
    _log("info", "inbound_store not available (using stub): %s", e)

# --------------------------------------------------------------------------- #
# Kleinanzeigen-Parser (optional, fail-safe Fallbacks)
# --------------------------------------------------------------------------- #
def _is_from_kleinanzeigen(_payload: Dict[str, Any]) -> bool:
    return False

def _extract_summary(_payload: Dict[str, Any]) -> Dict[str, Any]:
    return {}

try:
    from services.kleinanzeigen_parser import (  # type: ignore
        is_from_kleinanzeigen, extract_summary
    )
    _is_from_kleinanzeigen = is_from_kleinanzeigen
    _extract_summary = extract_summary
except Exception as e:
    _log("info", "kleinanzeigen_parser not available (ok): %s", e)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _ok_sender(sender: str) -> bool:
    """
    Erlaubte Absender per Wildcard-Liste in INBOUND_ALLOWED_SENDERS,
    z. B.: '*postmarkapp.com, *kleinanzeigen.de'
    """
    allowed = os.getenv("INBOUND_ALLOWED_SENDERS", "")
    if not allowed.strip():
        return True

    s = (sender or "").lower().strip()
    patterns = [p.strip().lower() for p in allowed.split(",") if p.strip()]
    for patt in patterns:
        if fnmatch.fnmatch(s, patt):
            return True
    return False

def _basic_ok() -> bool:
    """Basic Auth nur prüfen, wenn User+Pass gesetzt sind."""
    user = os.getenv("INBOUND_BASIC_USER")
    pw = os.getenv("INBOUND_BASIC_PASS")
    if not user or not pw:
        return True

    expected = "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()
    auth = request.headers.get("Authorization", "")
    return hmac.compare_digest(auth, expected)

def _signature_ok(raw_body: bytes) -> bool:
    """Postmark Inbound HMAC-SHA256 (Base64) prüfen, wenn Secret gesetzt ist."""
    key = os.getenv("POSTMARK_INBOUND_SIGNING_SECRET", "")
    if not key:
        return True

    sig = request.headers.get("X-Postmark-Signature", "")
    digest = hmac.new(key.encode(), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(sig, expected)

def _get_sender(data: Dict[str, Any]) -> str:
    return ((data.get("FromFull") or {}).get("Email") or data.get("From") or "").strip()

# --------------------------------------------------------------------------- #
# Route
# --------------------------------------------------------------------------- #
@bp.route("/inbound/postmark", methods=["GET", "POST"])
def inbound_postmark():
    # Healthcheck
    if request.method == "GET":
        return "inbound ok", 200

    # 1) URL-Secret (Pflicht)
    if request.args.get("secret") != os.getenv("INBOUND_SECRET", ""):
        abort(401)

    # 2) Optional Basic-Auth
    if not _basic_ok():
        abort(401)

    # 3) Body + optionale Signaturprüfung
    raw = request.get_data()
    if not _signature_ok(raw):
        abort(401)

    data: Dict[str, Any] = request.get_json(silent=True) or {}
    sender = _get_sender(data)

    # 4) Absender-Filter
    if not _ok_sender(sender):
        _log("warning", "Inbound blocked by sender filter: %s", sender)
        # 204 statt 403, damit Postmark die Mail NICHT retried
        return "", 204

    # 5) Event-Daten
    event: Dict[str, Any] = {
        "Subject":   data.get("Subject") or "",
        "From":      sender,
        "TextBody":  data.get("TextBody") or "",
        "HtmlBody":  data.get("HtmlBody") or "",
        "MessageID": data.get("MessageID") or "",
        "ReceivedAt": datetime.utcnow().isoformat() + "Z",
        "Raw":       data,
    }

    # 6) Optional: Kleinanzeigen-Zusammenfassung
    # 6) Optional: Kleinanzeigen-Zusammenfassung (robust)
subject = _to_str(data.get("Subject"))
text = _to_str(
    data.get("TextBody")
    or data.get("StrippedTextReply")   # Postmark-Feld mit „nur Antwort“
    or data.get("HtmlBody")            # notfalls HTML (dann ggf. weniger sauber)
    or ""
)

try:
    if _ka_is_from(subject, text):
        event["Summary"] = _ka_extract_summary(subject, text)
except Exception as e:
    _log("warning", "extract_summary failed: %s", e)


    # 7) Speichern / Weiterverarbeiten
    try:
        store_event("postmark", event)
    except Exception as e:
        _log("error", "store_event failed: %s", e)

    return "ok", 200
