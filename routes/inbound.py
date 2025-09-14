# routes/inbound.py
from __future__ import annotations

import base64
import fnmatch
import hmac
import hashlib
import logging
import os
from datetime import datetime

from flask import Blueprint, request, abort, current_app, has_app_context

bp = Blueprint("inbound", __name__)

# -----------------------------------------------------------------------------
# Logging helpers
# -----------------------------------------------------------------------------
_logger = logging.getLogger("inbound")

def _log(level: str, msg: str, *args):
    if has_app_context():
        getattr(current_app.logger, level)(msg, *args)
    else:
        getattr(_logger, level)(msg, *args)

# -----------------------------------------------------------------------------
# Optional store_event – echter Import wenn vorhanden, sonst Stub
# -----------------------------------------------------------------------------
def store_event(source: str, payload: dict) -> None:
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
# Optional Kleinanzeigen-Parser – robust mit Fallback
# -----------------------------------------------------------------------------
def _extract_summary_safe(subject: str, text: str) -> dict:
    """
    Versucht extract_summary in zwei Varianten:
    1) extract_summary(subject=..., text=...)
    2) extract_summary(text)
    Gibt {} zurück, falls Parser nicht vorhanden oder Fehler.
    """
    try:
        from services.kleinanzeigen_parser import extract_summary  # type: ignore
    except Exception:
        return {}

    try:
        # Neuere Signatur
        return extract_summary(subject=subject, text=text) or {}
    except TypeError:
        # Ältere Signatur
        try:
            return extract_summary(text) or {}
        except Exception:
            return {}
    except Exception:
        return {}

# -----------------------------------------------------------------------------
# Helfer: Sender, Allow-List, Basic-Auth, Signatur
# -----------------------------------------------------------------------------
def _get_sender(data: dict) -> str:
    # Postmark liefert häufig FromFull: { Email, Name }
    sender = ((data.get("FromFull") or {}) or {}).get("Email")
    if not sender:
        sender = data.get("From")
    sender = (sender or "").strip()
    return sender

def _allowed_sender(sender: str) -> bool:
    """
    INBOUND_ALLOWED_SENDERS: Kommagetrennte Wildcards, z.B.:
        "*postmarkapp.com, *@kleinanzeigen.de, noreply@beispiel.de"
    Leer -> alles erlaubt.
    """
    allowed = os.getenv("INBOUND_ALLOWED_SENDERS", "")
    if not allowed.strip():
        return True

    s = (sender or "").lower().strip()
    for patt in [p.strip().lower() for p in allowed.split(",") if p.strip()]:
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
    Postmark Inbound Signature (HMAC SHA256, Base64) prüfen, wenn Secret gesetzt.
    """
    key = os.getenv("POSTMARK_INBOUND_SIGNING_SECRET", "")
    if not key:
        return True
    provided = request.headers.get("X-Postmark-Signature", "")
    digest = hmac.new(key.encode(), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(provided, expected)

# -----------------------------------------------------------------------------
# Route
# -----------------------------------------------------------------------------
@bp.route("/inbound/postmark", methods=["GET", "POST"])
def inbound_postmark():
    # 0) GET = Healthcheck
    if request.method == "GET":
        return "inbound ok", 200

    # 1) URL-Secret (Pflicht)
    if request.args.get("secret") != os.getenv("INBOUND_SECRET", ""):
        abort(401)

    # 2) Basic-Auth (optional)
    if not _basic_ok():
        abort(401)

    # 3) Signatur (optional)
    raw = request.get_data()  # bytes
    if not _signature_ok(raw):
        abort(401)

    # 4) Payload aus JSON
    data = request.get_json(silent=True) or {}
    sender = _get_sender(data)

    # 4a) Postmark-Webhook-Ping: User-Agent enthält "Postmark", Sender leer
    #     => immer 200 OK zurückgeben, damit Postmark "grün" bleibt.
    ua = (request.headers.get("User-Agent") or "").lower()
    if "postmark" in ua and not sender:
        _log("info", "Postmark ping detected (no sender) -> allow")
        return "ok", 200

    # 5) Allow-List prüfen
    if not _ok_sender(sender):
    _log("info", "Inbound blocked by sender filter: %s", sender)
    abort(403)


    # 6) Felder sicher als Strings holen
    subject = data.get("Subject") or ""
    text = data.get("TextBody") or data.get("HtmlBody") or ""
    if not isinstance(subject, str):
        subject = str(subject)
    if not isinstance(text, str):
        text = str(text)

    # 7) Event aufbauen
    event = {
        "Subject": subject,
        "From": sender,
        "TextBody": text,
        "HtmlBody": data.get("HtmlBody") or "",
        "MessageID": data.get("MessageID") or "",
        "ReceivedAt": datetime.utcnow().isoformat() + "Z",
        "Raw": data,
    }

    # 8) Kleinanzeigen-Zusammenfassung (heuristisch)
    looks_like_ka = "kleinanzeigen" in (subject + "\n" + text).lower()
    if looks_like_ka:
        try:
            event["Summary"] = _extract_summary_safe(subject, text)
        except Exception as e:
            _log("warning", "extract_summary failed: %s", e)

    # 9) Speichern / Weiterverarbeiten
    try:
        store_event("postmark", event)
    except Exception as e:
        _log("error", "store_event failed: %s", e)

    return "ok", 200
