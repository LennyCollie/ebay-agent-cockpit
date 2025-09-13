# routes/inbound.py
import os, hmac, base64, hashlib, fnmatch, logging
from datetime import datetime
from flask import Blueprint, request, abort, current_app, has_app_context

bp = Blueprint("inbound", __name__)
logger = logging.getLogger("inbound")

# -- logging helper (nutzt current_app wenn vorhanden) -----------------------
def _log(level: str, msg: str, *args):
    if has_app_context():
        getattr(current_app.logger, level)(msg, *args)
    else:
        getattr(logger, level)(msg, *args)

# -- optionales store_event: echter Store wenn vorhanden, sonst Stub ----------
def _store_stub(source: str, payload: dict) -> None:
    _log(
        "warning",
        "store_event STUB used | source=%s | subject=%s | received=%s",
        source, payload.get("Subject"), datetime.utcnow().isoformat() + "Z",
    )

store_event = _store_stub
try:
    from services.inbound_store import store_event as _real_store_event  # type: ignore
    store_event = _real_store_event
except Exception as e:
    _log("warning", "using store_event STUB (import failed): %s", e)

# -- Kleinanzeigen-Parser optional/fail-safe ----------------------------------
def _is_from_kleinanzeigen(_payload: dict) -> bool:  # Stub
    return False

def _extract_summary(_payload: dict) -> dict:       # Stub
    return {}

try:
    from services.kleinanzeigen_parser import is_from_kleinanzeigen, extract_summary  # type: ignore
    _is_from_kleinanzeigen = is_from_kleinanzeigen
    _extract_summary = extract_summary
except Exception as e:
    _log("info", "kleinanzeigen_parser not available (ok): %s", e)

# -- helpers ------------------------------------------------------------------
def _ok_sender(sender: str) -> bool:
    """
    Wildcards unterstützt: INBOUND_ALLOWED_SENDERS="*postmarkapp.com, *kleinanzeigen.de"
    Leer = alles erlaubt.
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
    """Basic Auth nur prüfen, wenn User+Pass gesetzt sind."""
    user = os.getenv("INBOUND_BASIC_USER")
    pw = os.getenv("INBOUND_BASIC_PASS")
    if not user or not pw:
        return True
    auth = request.headers.get("Authorization", "")
    expected = "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()
    return hmac.compare_digest(auth, expected)

def _signature_ok(raw_body: bytes) -> bool:
    """Postmark HMAC-SHA256 (Base64) prüfen, wenn Secret gesetzt ist."""
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

# -- einziger Endpoint --------------------------------------------------------
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
    # Strings für den Parser herstellen
    subject = (data.get("Subject") or "").strip()
    # Text bevorzugt aus TextBody, sonst HTML als Fallback (ohne Anspruch auf perfektes Strippen)
    text = (data.get("TextBody") or data.get("HtmlBody") or "").strip()

    summary = {}
    if _is_from_kleinanzeigen(data) or "kleinanzeigen" in subject.lower():
        # robust aufrufen – verschiedene Parser-Signaturen abfangen
        try:
            summary = _extract_summary(subject=subject, text=text) or {}
        except TypeError:
            try:
                summary = _extract_summary(text) or {}
            except TypeError:
                summary = _extract_summary(subject + "\n" + text) or {}

    if summary:
        event["Summary"] = summary
except Exception as e:
    _log("warning", "extract_summary failed: %s", e)

    return "ok", 200
