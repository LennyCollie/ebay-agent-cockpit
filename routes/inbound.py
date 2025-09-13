# routes/inbound.py
import os
import hmac
import base64
import hashlib
import fnmatch
import logging
import os, time, hmac, base64, hashlib, json
from datetime import datetime
from flask import Blueprint, request, abort, current_app, has_app_context
from flask import Blueprint, request, abort, current_app
from services.kleinanzeigen_parser import is_from_kleinanzeigen, extract_summary
from services.inbound_store import store_event   # falls du die Store-Funktion nutzt

bp = Blueprint("inbound", __name__)

# -------- logging helpers ----------------------------------------------------
logger = logging.getLogger("inbound")

def _log(level: str, msg: str, *args):
    """Loggt sicher – mit current_app.logger wenn Kontext da ist, sonst std-Logger."""
    if has_app_context():
        getattr(current_app.logger, level)(msg, *args)
    else:
        getattr(logger, level)(msg, *args)

# -------- fail-safe store_event (Stub by default) ----------------------------
def store_event(source: str, payload: dict) -> None:
    # läuft normalerweise im Request-Kontext, aber hier trotzdem sicher:
    _log("warning",
         "store_event STUB used | source=%s | subject=%s | received=%s",
         source, payload.get("Subject"),
         datetime.utcnow().isoformat() + "Z")

try:
    # echter Store, falls vorhanden
    from services.inbound_store import store_event as _real_store_event  # type: ignore
    store_event = _real_store_event  # noqa: F811
except Exception as e:
    _log("warning", "using store_event STUB (import failed): %s", e)

# -------- Kleinanzeigen-Parser optional & fail-safe --------------------------
def _is_from_kleinanzeigen(_payload: dict) -> bool:  # Stub
    return False

def _extract_summary(_payload: dict) -> dict:       # Stub
    return {}

try:
    from services.kleinanzeigen_parser import (  # type: ignore
        is_from_kleinanzeigen, extract_summary
    )
    _is_from_kleinanzeigen = is_from_kleinanzeigen
    _extract_summary = extract_summary
except Exception as e:
    _log("info", "kleinanzeigen_parser not available (ok): %s", e)

# -------- helpers ------------------------------------------------------------
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

def _get_sender(data: dict) -> str:
    return ((data.get("FromFull") or {}).get("Email")
            or data.get("From")
            or "").strip()

# -------- routes -------------------------------------------------------------
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

    data = request.get_json(silent=True) or {}
    sender = _get_sender(data)

    # 4) Absender-Filter
    if not _ok_sender(sender):
        _log("warning", "Inbound blocked by sender filter: %s", sender)
        abort(403)

    # 5) Event-Daten
    event = {
        "Subject": data.get("Subject") or "",
        "From": sender,
        "TextBody": data.get("TextBody") or "",
        "HtmlBody": data.get("HtmlBody") or "",
        "MessageID": data.get("MessageID") or "",
        "ReceivedAt": datetime.utcnow().isoformat() + "Z",
        "Raw": data,
    }

    # 6) Optional: Kleinanzeigen-Zusammenfassung
    try:
        if _is_from_kleinanzeigen(data):
            event["Summary"] = _extract_summary(data) or {}
    except Exception as e:
        _log("warning", "extract_summary failed: %s", e)

    # 7) Speichern / Weiterverarbeiten
    try:
        store_event("postmark", event)
    except Exception as e:
        _log("error", "store_event failed: %s", e)

    return "ok", 200


@bp.route("/inbound/postmark", methods=["GET", "POST"])
def inbound_postmark():
    # Healthcheck für GET
    if request.method == "GET":
        return "inbound ok", 200

    # Secret in URL prüfen (wie bisher)
    if request.args.get("secret") != os.getenv("INBOUND_SECRET", ""):
        abort(401)

    data = request.get_json(silent=True) or {}
    subject  = data.get("Subject", "")
    text     = data.get("TextBody", "") or ""
    sender   = (data.get("FromFull", {}) or {}).get("Email") or data.get("From", "")

    # --- Allow-List prüfen (dein vorhandener Code) ---
    # ... hier bleibt deine bestehende Sender-Filterlogik ...

    # --- Mini-Parser nur anwenden, wenn es nach Kleinanzeigen aussieht ---
    summary = {}
    if is_from_kleinanzeigen(sender):
        summary = extract_summary(subject=subject, text=text)

    # Rohpayload + Summary speichern (oder loggen)
    payload = {
        "subject": subject,
        "sender": sender,
        "text": text,
        "received_at": int(time.time()),
    }

    # wenn du eine Store-Funktion hast:
    try:
        store_event(source="kleinanzeigen", payload=payload, summary=summary)
    except Exception as exc:
        current_app.logger.warning("store_event failed: %s", exc, exc_info=True)

    # immer 200 an Postmark zurück (sonst retried es)
    return "ok", 200
