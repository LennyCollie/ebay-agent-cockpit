# routes/inbound.py
from __future__ import annotations

import base64
import fnmatch
import hashlib
import hmac
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict

from flask import Blueprint, request, abort, current_app, has_app_context

bp = Blueprint("inbound", __name__)

# ---------------------------------------------------------------------------
# Logging helper
# ---------------------------------------------------------------------------
_logger = logging.getLogger("inbound")

def _log(level: str, msg: str, *args: Any) -> None:
    """Loggt sicher – mit Flask-Logger, sonst std. Logger."""
    if has_app_context():
        getattr(current_app.logger, level)(msg, *args)
    else:
        getattr(_logger, level)(msg, *args)


# ---------------------------------------------------------------------------
# Optionale Services (robuste Fallbacks)
# ---------------------------------------------------------------------------
def _store_event_stub(source: str, payload: Dict[str, Any]) -> None:
    _log(
        "warning",
        "store_event STUB used | source=%s | subject=%s | received=%s",
        source,
        str(payload.get("Subject", "")),
        datetime.utcnow().isoformat() + "Z",
    )

store_event = _store_event_stub  # default
try:
    # Wenn vorhanden, benutzen
    from services.inbound_store import store_event as _real_store_event  # type: ignore

    store_event = _real_store_event  # type: ignore[assignment]
except Exception as e:
    _log("info", "inbound_store not available (using stub): %s", e)


def _is_from_kleinanzeigen_stub(_sender: str) -> bool:
    return False

def _extract_summary_stub(**_kwargs: Any) -> Dict[str, Any]:
    return {}

_is_from_kleinanzeigen = _is_from_kleinanzeigen_stub
_extract_summary = _extract_summary_stub

try:
    # Falls vorhanden, anbinden – aber immer defensiv aufrufen
    from services.kleinanzeigen_parser import (  # type: ignore
        is_from_kleinanzeigen as _real_is_from_kleinanzeigen,
        extract_summary as _real_extract_summary,
    )

    _is_from_kleinanzeigen = _real_is_from_kleinanzeigen  # type: ignore[assignment]
    _extract_summary = _real_extract_summary  # type: ignore[assignment]
except Exception as e:
    _log("info", "kleinanzeigen_parser not available (ok): %s", e)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _get_sender(data: Dict[str, Any]) -> str:
    """Liest den Absender als String (sicher)."""
    try:
        from_full = data.get("FromFull") or {}
        email = (from_full or {}).get("Email")
        if email:
            return str(email).strip()
    except Exception:
        pass
    return str(data.get("From", "")).strip()


def _ok_sender(sender: str) -> bool:
    """
    Wildcards aus INBOUND_ALLOWED_SENDERS auswerten.
    Beispiel: '*postmarkapp.com, *@kleinanzeigen.de'
    Leer ⇒ alles erlaubt.
    """
    allowed = os.getenv("INBOUND_ALLOWED_SENDERS", "")
    if not allowed.strip():
        return True

    s = str(sender or "").lower().strip()
    for patt in (p.strip().lower() for p in allowed.split(",") if p.strip()):
        if fnmatch.fnmatch(s, patt):
            return True
    return False


def _basic_ok() -> bool:
    """Optional Basic-Auth: nur prüfen, wenn beide Werte gesetzt sind."""
    user = os.getenv("INBOUND_BASIC_USER")
    pw = os.getenv("INBOUND_BASIC_PASS")
    if not user or not pw:
        return True

    expected = "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()
    got = request.headers.get("Authorization", "")
    # safer compare
    return hmac.compare_digest(got, expected)


def _signature_ok(raw_body: bytes) -> bool:
    """
    Optional Postmark-Signaturprüfung (HMAC-SHA256 Base64).
    Prüft Header 'X-Postmark-Signature', wenn Secret gesetzt.
    """
    key = os.getenv("POSTMARK_INBOUND_SIGNING_SECRET", "")
    if not key:
        return True

    provided = request.headers.get("X-Postmark-Signature", "") or ""
    digest = hmac.new(key.encode(), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(provided, expected)


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------
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

    # 3) Signatur (optional, wenn Secret gesetzt)
    raw = request.get_data(cache=False, as_text=False)
    if not _signature_ok(raw):
        abort(401)

    # 4) Payload
    data: Dict[str, Any] = request.get_json(silent=True) or {}

    sender = _get_sender(data)
    subject = str(data.get("Subject") or "")
    text = str(data.get("TextBody") or "")
    html = str(data.get("HtmlBody") or "")

# Postmark-"Check"-Ping erlauben, wenn kein Sender vorhanden ist
ua = (request.headers.get("User-Agent") or "").lower()
is_postmark = ("postmark" in ua) or bool(request.headers.get("X-Postmark-Clock"))

if is_postmark and not sender:
    current_app.logger.info("Inbound check-ping from Postmark – sender empty -> allowed")
    return "ok", 200

# ---------------------------------------------------------------------------


    # 5) Allowlist
    if not _ok_sender(sender):
        _log("warning", "Inbound blocked by sender filter: %s", sender)
        abort(403)

    # 6) Event zusammenstellen (robust)
    event: Dict[str, Any] = {
        "Source": "postmark",
        "Subject": subject,
        "From": sender,
        "TextBody": text,
        "HtmlBody": html,
        "MessageID": str(data.get("MessageID") or ""),
        "ReceivedAt": datetime.utcnow().isoformat() + "Z",
        "Raw": data,
        "ReceivedEpoch": int(time.time()),
    }

    # 7) Optional: Kleinanzeigen-Zusammenfassung
    #    Achtung: NIE das gesamte dict an den Checker geben – immer String!
    try:
        if _is_from_kleinanzeigen(str(sender or "")):
            summary: Dict[str, Any] | None = None
            # bevorzugt keyword-args (falls die Funktion so definiert ist):
            try:
                summary = _extract_summary(subject=subject, text=text)  # type: ignore[call-arg]
            except TypeError:
                # Fallbacks, je nach Implementierung im Projekt:
                try:
                    summary = _extract_summary({"subject": subject, "text": text})  # type: ignore[misc]
                except Exception:
                    summary = _extract_summary(data)  # last resort  # type: ignore[arg-type]

            if summary:
                event["Summary"] = summary
    except Exception as e:
        _log("warning", "kleinanzeigen summary failed: %s", e)

    # 8) Persist / verarbeiten
    try:
        store_event("postmark", event)
    except Exception as e:
        _log("error", "store_event failed: %s", e)

    # 9) Postmark braucht 200, sonst retry
    return "ok", 200
