# routes/inbound.py
from __future__ import annotations

import os
import hmac
import base64
import hashlib
import fnmatch
import logging
from datetime import datetime
from typing import Any, Callable, Optional

from flask import Blueprint, request, abort, current_app, has_app_context

bp = Blueprint("inbound", __name__)

# -----------------------------------------------------------------------------
# Logging (sicher – funktioniert auch ohne app context)
# -----------------------------------------------------------------------------
_logger = logging.getLogger("inbound")

def _log(level: str, msg: str, *args: Any) -> None:
    if has_app_context():
        getattr(current_app.logger, level)(msg, *args)
    else:
        getattr(_logger, level)(msg, *args)


# -----------------------------------------------------------------------------
# Optionales Persistieren: store_event (Stub, wenn kein echter Store vorhanden)
# -----------------------------------------------------------------------------
def store_event(source: str, payload: dict) -> None:
    _log(
        "warning",
        "store_event STUB used | source=%s | subject=%s | received=%s",
        source, payload.get("Subject", ""),
        datetime.utcnow().isoformat() + "Z",
    )

try:
    # Wenn vorhanden, echten Store verwenden
    from services.inbound_store import store_event as _real_store_event  # type: ignore
    store_event = _real_store_event  # type: ignore[assignment]
except Exception as e:
    _log("info", "using store_event STUB (import failed): %s", e)


# -----------------------------------------------------------------------------
# Mini-Parser für Kleinanzeigen (robuste Adapter + Heuristik-Fallback)
# -----------------------------------------------------------------------------
_ka_is: Optional[Callable[..., Any]] = None
_ka_extract: Optional[Callable[..., Any]] = None
try:
    from services.kleinanzeigen_parser import (  # type: ignore
        is_from_kleinanzeigen as _ka_is,  # type: ignore[assignment]
        extract_summary as _ka_extract,   # type: ignore[assignment]
    )
except Exception as e:
    _log("info", "kleinanzeigen_parser not available (ok): %s", e)
    _ka_is = None
    _ka_extract = None


def _ka_detect(subject: str, text: str, sender: str) -> bool:
    """Erkennt Kleinanzeigen robust – unterstützt payload/kwargs/positional + Heuristik."""
    subj = subject or ""
    txt = text or ""
    if _ka_is:
        try:
            return bool(_ka_is({"subject": subj, "text": txt, "from": sender}))
        except TypeError:
            try:
                return bool(_ka_is(subject=subj, text=txt))
            except TypeError:
                try:
                    return bool(_ka_is(subj, txt))
                except Exception as e:
                    _log("info", "ka detect failed: %s", e)
        except Exception as e:
            _log("info", "ka detect failed: %s", e)

    # Heuristik (wenn kein Parser vorhanden oder fehlgeschlagen)
    s_low = (sender or "").lower()
    return "kleinanzeigen" in s_low or "kleinanzeigen" in subj.lower()


def _ka_summary(subject: str, text: str) -> dict:
    """Liefert Summary robust – unterstützt payload/kwargs/positional."""
    subj = subject or ""
    txt = text or ""
    if _ka_extract:
        try:
            out = _ka_extract({"subject": subj, "text": txt})  # type: ignore[misc]
            return out or {}
        except TypeError:
            try:
                out = _ka_extract(subject=subj, text=txt)  # type: ignore[misc]
                return out or {}
            except TypeError:
                try:
                    out = _ka_extract(subj, txt)  # type: ignore[misc]
                    return out or {}
                except Exception as e:
                    _log("warning", "extract_summary failed: %s", e)
        except Exception as e:
            _log("warning", "extract_summary failed: %s", e)
    return {}


# -----------------------------------------------------------------------------
# Helpers: Sender, Allow-List, Basic-Auth, Signatur
# -----------------------------------------------------------------------------
def _get_sender(data: dict) -> str:
    return (
        ((data.get("FromFull") or {}) or {}).get("Email")
        or data.get("From")
        or ""
    ).strip()

def _ok_sender(sender: str) -> bool:
    """Wildcards in INBOUND_ALLOWED_SENDERS, z. B. '*postmarkapp.com, *kleinanzeigen.de'."""
    allowed = os.getenv("INBOUND_ALLOWED_SENDERS", "")
    if not allowed.strip():
        return True
    s = (sender or "").lower().strip()
    for patt in [p.strip().lower() for p in allowed.split(",") if p.strip()]:
        if fnmatch.fnmatch(s, patt):
            return True
    return False

def _basic_ok() -> bool:
    """Basic Auth nur prüfen, wenn User+Pass gesetzt sind."""
    user = os.getenv("INBOUND_BASIC_USER")
    pw = os.getenv("INBOUND_BASIC_PASS")
    if not user or not pw:
        return True
    auth = request.headers.get("Authorization", "")
    expected = "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()
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


# -----------------------------------------------------------------------------
# Route: /inbound/postmark
# -----------------------------------------------------------------------------
@bp.route("/inbound/postmark", methods=["GET", "POST"])
def inbound_postmark():
    # Healthcheck im Browser
    if request.method == "GET":
        return "inbound ok", 200

    # 1) URL-Secret (Pflicht)
    if request.args.get("secret") != os.getenv("INBOUND_SECRET", ""):
        abort(401)

    # 2) Optional Basic-Auth
    if not _basic_ok():
        abort(401)

    # 3) Body + optionale Signaturprüfung
    raw = request.get_data(cache=False, as_text=False)
    if not _signature_ok(raw):
        abort(401)

    # 4) Payload + Sender
    data = request.get_json(silent=True) or {}
    sender = _get_sender(data)

    # 5) Allow-List
    if not _ok_sender(sender):
        _log("warning", "Inbound blocked by sender filter: %s", sender)
        abort(403)

    # 6) Event aufbauen
    subject = str(data.get("Subject") or "")
    text    = str(data.get("TextBody") or "")
    event = {
        "Subject": subject,
        "From": sender,
        "TextBody": text,
        "HtmlBody": data.get("HtmlBody") or "",
        "MessageID": data.get("MessageID") or "",
        "ReceivedAt": datetime.utcnow().isoformat() + "Z",
        "Raw": data,
    }

    # 7) Optional: Kleinanzeigen-Summary
    try:
        if _ka_detect(subject, text, sender):
            summary = _ka_summary(subject, text)
            if summary:
                event["Summary"] = summary
    except Exception as e:
        _log("warning", "summary build failed: %s", e)

    # 8) Speichern / Weiterverarbeiten
    try:
        store_event("postmark", event)
    except Exception as e:
        _log("error", "store_event failed: %s", e)

    # 9) Immer 200 – sonst retried Postmark
    return "ok", 200
