# routes/inbound.py
from __future__ import annotations

import base64
import fnmatch
import hashlib
import hmac
import logging
import os
from datetime import datetime

from flask import Blueprint, request, abort, current_app, has_app_context

bp = Blueprint("inbound", __name__)
_log_fallback = logging.getLogger("inbound")


# ---------- Logging helper ----------
def _log(level: str, msg: str, *args) -> None:
    logger = current_app.logger if has_app_context() else _log_fallback
    getattr(logger, level)(msg, *args)


# ---------- Optionale Abhängigkeiten (fail-safe) ----------
try:
    from services.inbound_store import store_event as _store_event  # type: ignore
except Exception:
    def _store_event(source: str, payload: dict) -> None:
        _log(
            "info",
            "store_event STUB used | source=%s | subject=%s",
            source,
            (payload or {}).get("Subject", ""),
        )

try:
    from services.kleinanzeigen_parser import (  # type: ignore
        is_from_kleinanzeigen as _is_from_ka,
        extract_summary as _extract_summary,
    )
except Exception:
    def _is_from_ka(_payload: dict | None = None, **_kw) -> bool:
        return False

    def _extract_summary(*_args, **_kw) -> dict:
        return {}


# ---------- Helpers ----------
def _get_sender(data: dict) -> str:
    return (
        ((data.get("FromFull") or {}).get("Email"))
        or data.get("From")
        or ""
    ).strip()


def _ok_sender(sender: str) -> bool:
    """
    Erlaubt Wildcards in INBOUND_ALLOWED_SENDERS, z. B.:
    '*postmarkapp.com, *kleinanzeigen.de'
    Kein Eintrag -> alles erlaubt.
    """
    allowed = os.getenv("INBOUND_ALLOWED_SENDERS", "")
    if not allowed.strip():
        return True

    s = (sender or "").lower()
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

    auth_hdr = request.headers.get("Authorization", "")
    expected = "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()
    return hmac.compare_digest(auth_hdr, expected)


def _signature_ok(raw_body: bytes) -> bool:
    """Postmark Inbound HMAC-SHA256 (Base64) prüfen, wenn Secret gesetzt ist."""
    key = os.getenv("POSTMARK_INBOUND_SIGNING_SECRET", "")
    if not key:
        return True
    sig = request.headers.get("X-Postmark-Signature", "")
    digest = hmac.new(key.encode(), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(sig, expected)


# ---------- Route ----------
@bp.route("/inbound/postmark", methods=["GET", "POST"])
def inbound_postmark():
    # Healthcheck & Postmark-"Check"-Button:
    # Viele Pings haben keinen Absender. Wenn User-Agent Postmark ist und kein Sender vorhanden,
    # antworte 200, damit der Check grün wird – ohne Allow-List zu triggern.
    if request.method == "GET":
        return "inbound ok", 200

    data = request.get_json(silent=True) or {}
    sender = _get_sender(data)
    ua = (request.headers.get("User-Agent", "") or "").lower()
    if "postmark" in ua and not sender:
        return "inbound ok", 200

    # 1) URL-Secret (Pflicht)
    if request.args.get("secret") != os.getenv("INBOUND_SECRET", ""):
        abort(401)

    # 2) Optional Basic-Auth
    if not _basic_ok():
        abort(401)

    # 3) Optionale Signaturprüfung
    if not _signature_ok(request.get_data()):
        abort(401)

    # 4) Allow-List
    if not _ok_sender(sender):
        _log("warning", "Inbound blocked by sender filter: %s", sender)
        abort(403)

    # 5) Eventdaten
    subject = data.get("Subject") or ""
    text = data.get("TextBody") or ""
    html = data.get("HtmlBody") or ""

    event = {
        "Source": "postmark",
        "Subject": subject,
        "From": sender,
        "TextBody": text,
        "HtmlBody": html,
        "MessageID": data.get("MessageID") or "",
        "ReceivedAt": datetime.utcnow().isoformat() + "Z",
        "Raw": data,
    }

# 6) Optional: Kleinanzeigen-Zusammenfassung (robust)
subject = (data.get("Subject") or "")
text    = (data.get("TextBody") or data.get("HtmlBody") or "")

# Alles zu Strings zwingen (falls Postmark Felder mal nicht-String sind)
if not isinstance(subject, str):
    subject = str(subject)
if not isinstance(text, str):
    text = str(text)

looks_like_ka = "kleinanzeigen" in (subject + "\n" + text).lower()

try:
    if looks_like_ka:
        # Parser-Signatur 1: extract_summary(subject=..., text=...)
        try:
            event["Summary"] = _extract_summary(subject=subject, text=text) or {}
        except TypeError:
            # Fallback auf ältere Signatur: extract_summary(text)
            event["Summary"] = _extract_summary(text) or {}
except Exception as e:
    _log("warning", "extract_summary failed: %s", e)


    # 7) Speichern / Weiterverarbeiten (fail-safe)
    try:
        _store_event("postmark", event)
    except Exception as e:
        _log("error", "store_event failed: %s", e)

    return "ok", 200
