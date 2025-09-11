# routes/inbound.py
import os
import re
import hmac
import json
import base64
import hashlib
from typing import Dict, Any

from flask import Blueprint, request, abort, jsonify, current_app

# --- optionale Services laden (fallen auf Stubs zurück, wenn lokal nicht vorhanden) ----
try:
    from services.inbound_store import store_event  # z.B. DB/Log persistieren
except Exception:
    def store_event(source: str, payload: Dict[str, Any]) -> None:
        current_app.logger.info("store_event (stub) %s: %s", source, payload.get("Subject"))

try:
    from services.kleinanzeigen_parser import is_from_kleinanzeigen, extract_summary
except Exception:
    def is_from_kleinanzeigen(payload: Dict[str, Any]) -> bool:
        return False

    def extract_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {}

# ---------------------------------------------------------------------------------------

bp = Blueprint("inbound", __name__)

# ----------------------------- Helper -----------------------------------------------

def _ok_sender(sender: str) -> bool:
    """
    Optionaler Absender-Filter über INBOUND_ALLOWED_SENDERS.
    Komma-separierte Liste, Wildcards * erlaubt (z.B. *@postmarkapp.com, *@kleinanzeigen.de).
    Ist die Variable leer, ist ALLES erlaubt.
    """
    allowed = os.getenv("INBOUND_ALLOWED_SENDERS", "")
    if not allowed.strip():
        return True  # nichts konfiguriert -> nicht filtern

    sender = (sender or "").lower()
    patterns = [p.strip().lower() for p in allowed.split(",") if p.strip()]
    for pat in patterns:
        # Wildcard zu Regex
        rx = "^" + re.escape(pat).replace(r"\*", ".*") + "$"
        if re.match(rx, sender):
            return True
    return False


def _check_basic_auth() -> bool:
    """
    Optionaler Basic-Auth Schutz über INBOUND_BASIC_USER / INBOUND_BASIC_PASS.
    Ist eins davon leer, ist Basic-Auth deaktiviert.
    """
    user = os.getenv("INBOUND_BASIC_USER")
    pw = os.getenv("INBOUND_BASIC_PASS")
    if not user or not pw:
        return True  # deaktiviert

    auth = request.headers.get("Authorization", "")
    expected = "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()
    return hmac.compare_digest(auth, expected)


def _verify_postmark_signature(raw_body: bytes) -> bool:
    """
    Prüft die X-Postmark-Signature, wenn POSTMARK_INBOUND_SIGNING_SECRET gesetzt ist.
    """
    secret = os.getenv("POSTMARK_INBOUND_SIGNING_SECRET", "").strip()
    if not secret:
        return True  # keine Prüfung gewünscht

    header_sig = request.headers.get("X-Postmark-Signature", "")
    calc = base64.b64encode(
        hmac.new(secret.encode(), msg=raw_body, digestmod=hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(header_sig, calc)

# ------------------------------ Routes ----------------------------------------------

@bp.route("/inbound/postmark", methods=["GET", "POST"])
def inbound_postmark():
    """
    Healthcheck: GET  -> 'inbound ok'
    Produktiv:  POST -> Postmark Inbound Webhook
    Schutz:
      - ?secret=...   (INBOUND_SECRET, verpflichtend wenn gesetzt)
      - Basic-Auth   (INBOUND_BASIC_USER/PASS, optional)
      - Signatur     (POSTMARK_INBOUND_SIGNING_SECRET, optional)
      - Absender     (INBOUND_ALLOWED_SENDERS, optional)
    """
    if request.method == "GET":
        return "inbound ok", 200

    # 1) URL-Secret (wenn gesetzt)
    expected_secret = os.getenv("INBOUND_SECRET", "")
    if expected_secret:
        if request.args.get("secret") != expected_secret:
            abort(401)

    # 2) Basic-Auth (wenn konfiguriert)
    if not _check_basic_auth():
        abort(401)

    # 3) Postmark-Signatur (wenn konfiguriert)
    raw = request.get_data(cache=False, as_text=False)
    if not _verify_postmark_signature(raw):
        abort(401)

    # 4) Payload parsen
    payload = request.get_json(silent=True) or {}
    from_addr = (payload.get("FromFull", {}) or {}).get("Email") or payload.get("From") or ""
    subject = payload.get("Subject", "")

    # 5) Optional Absender-Filter
    if not _ok_sender(from_addr):
        current_app.logger.warning("Inbound blocked by sender filter: %s", from_addr)
        abort(403)

    # 6) Kleinanzeigen-Heuristik (optional)
    ka = is_from_kleinanzeigen(payload)
    summary = extract_summary(payload) if ka else None

    # 7) Persistieren / Weiterverarbeiten
    try:
        store_event("kleinanzeigen" if ka else "postmark", payload)
    except Exception as e:
        current_app.logger.exception("store_event failed: %s", e)

    current_app.logger.info(
        "Inbound OK from=%s subject=%s kleinanzeigen=%s", from_addr, subject, ka
    )
    return jsonify({"status": "ok"}), 200
