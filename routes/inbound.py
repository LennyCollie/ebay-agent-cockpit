# routes/inbound.py
import os
import hmac
import base64
import hashlib
import fnmatch
from datetime import datetime
from flask import Blueprint, request, abort, current_app

bp = Blueprint("inbound", __name__)

# --- Fail-safe: immer einen store_event-Stub bereitstellen -------------------
def store_event(source: str, payload: dict) -> None:
    current_app.logger.warning(
        "store_event STUB used | source=%s | subject=%s | received=%s",
        source,
        payload.get("Subject"),
        datetime.utcnow().isoformat() + "Z",
    )

try:
    # echter Store (falls vorhanden) ersetzt den Stub
    from services.inbound_store import store_event as _real_store_event  # type: ignore
    store_event = _real_store_event  # noqa: F811
except Exception as e:
    current_app.logger.warning("using store_event STUB (import failed): %s", e)

# --- Optional: Kleinanzeigen-Parser fail-safe einbinden ----------------------
def _is_from_kleinanzeigen(_payload: dict) -> bool:  # Stub
    return False

def _extract_summary(_payload: dict) -> dict:       # Stub
    return {}

try:
    # Korrekte Import-Form (NICHT "import services.kleinanzeigen_parser.extract_summary")
    from services.kleinanzeigen_parser import is_from_kleinanzeigen, extract_summary  # type: ignore
    _is_from_kleinanzeigen = is_from_kleinanzeigen
    _extract_summary = extract_summary
except Exception as e:
    current_app.logger.info("kleinanzeigen_parser not available (ok): %s", e)

# --- Hilfsfunktionen ---------------------------------------------------------
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
    # Postmark-Inbound: 'FromFull':{'Email':...} oder 'From'
    return ((data.get("FromFull") or {}).get("Email")
            or data.get("From")
            or "").strip()

# --- Routes ------------------------------------------------------------------
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
    raw = request.get_data()  # wichtig für HMAC
    if not _signature_ok(raw):
        abort(401)

    data = request.get_json(silent=True) or {}
    sender = _get_sender(data)

    # 4) Absender-Filter
    if not _ok_sender(sender):
        current_app.logger.warning("Inbound blocked by sender filter: %s", sender)
        abort(403)

    # 5) Event-Daten aufbauen
    subject = data.get("Subject") or ""
    text = data.get("TextBody") or ""
    html = data.get("HtmlBody") or ""
    message_id = data.get("MessageID") or ""

    event = {
        "Subject": subject,
        "From": sender,
        "TextBody": text,
        "HtmlBody": html,
        "MessageID": message_id,
        "ReceivedAt": datetime.utcnow().isoformat() + "Z",
        "Raw": data,
    }

    # 6) Optional: Kleinanzeigen-Zusammenfassung
    if _is_from_kleinanzeigen(data):
        try:
            summary = _extract_summary(data) or {}
            event["Summary"] = summary
        except Exception as e:
            current_app.logger.warning("extract_summary failed: %s", e)

    # 7) Speichern / Weiterverarbeiten (echter Store oder Stub)
    try:
        store_event("postmark", event)
    except Exception as e:
        current_app.logger.error("store_event failed: %s", e)

    return "ok", 200
