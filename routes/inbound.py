# routes/inbound.py
from __future__ import annotations

import os
import re
import hmac
import base64
import hashlib
from typing import Any, Dict

from flask import Blueprint, request, abort, jsonify, current_app

# interne Services (sind in deinem Projekt vorhanden)
from services.inbound_store import store_event
from services.kleinanzeigen_parser import is_from_kleinanzeigen, extract_summary

bp = Blueprint("inbound", __name__)

# -------------------------
# Erkennung Kleinanzeigen
# -------------------------
RX_KA_SENDER = re.compile(r'@(?:mail\.)?kleinanzeigen\.de$', re.I)
RX_KA_URL = re.compile(
    r'https?://(?:www\.)?kleinanzeigen\.de/s-anzeige/[^"\s<>]+', re.I
)

def _ok_sender(sender: str) -> bool:
    """
    Prüft, ob der äußere From-Absender (z. B. bei Weiterleitungen) zur Allowlist passt.
    INBOUND_ALLOWED_SENDERS nimmt komma-separierte Patterns, z. B.:
      "*@mail.kleinanzeigen.de, *@kleinanzeigen.de, *@freenet.de"
    Ein '*' bedeutet: Teilstring-Match.
    """
    sender = (sender or "").lower().strip()
    allowed_raw = os.getenv("INBOUND_ALLOWED_SENDERS", "")
    for p in (allowed_raw or "").split(","):
        patt = p.strip().lower()
        if not patt:
            continue
        # simples Wildcard-Matching: '*' entfernen -> Teilstring
        if "*" in patt:
            patt = patt.replace("*", "")
            if patt and patt in sender:
                return True
        else:
            if sender.endswith(patt):
                return True
    return False


def _ok_by_payload(pm: Dict[str, Any]) -> bool:
    """
    Zulassen, wenn der Postmark-Payload eindeutig nach Kleinanzeigen aussieht:
     - innerer Absender @mail.kleinanzeigen.de oder
     - im Text/HTML/Betreff steckt eine Kleinanzeigen-URL
    """
    from_email = ((pm.get("FromFull") or {}).get("Email")) or pm.get("From") or ""
    if RX_KA_SENDER.search(from_email):
        return True
    text = " ".join([
        pm.get("TextBody") or "",
        pm.get("HtmlBody") or "",
        pm.get("Subject") or "",
    ])
    return bool(RX_KA_URL.search(text))


def _check_basic_auth() -> bool:
    """Optionales Basic-Auth-Gate. Aktiv, wenn beide ENV-Variablen gesetzt sind."""
    user = os.getenv("INBOUND_BASIC_USER")
    pw = os.getenv("INBOUND_BASIC_PASS")
    if not user or not pw:
        return True  # nicht konfiguriert -> nicht prüfen

    auth_hdr = request.headers.get("Authorization", "")
    expected = "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()
    return auth_hdr == expected


def _check_postmark_signature(raw_body: bytes) -> bool:
    """
    Verifiziert die Postmark-Inbound-Signatur, falls POSTMARK_INBOUND_SIGNING_SECRET gesetzt ist.
    Postmark sendet 'X-Postmark-Signature' (hex oder base64 je nach lib). Wir prüfen beides.
    """
    secret = os.getenv("POSTMARK_INBOUND_SIGNING_SECRET")
    if not secret:
        return True  # kein Secret -> nicht prüfen

    header_sig = request.headers.get("X-Postmark-Signature", "") or ""
    if not header_sig:
        return False

    digest = hmac.new(
        key=secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).digest()

    # 1) Base64-Vergleich
    b64_sig = base64.b64encode(digest).decode()
    if hmac.compare_digest(header_sig, b64_sig):
        return True

    # 2) Hex-Vergleich (manche Clients nutzen das)
    hex_sig = digest.hex()
    if hmac.compare_digest(header_sig.lower(), hex_sig.lower()):
        return True

    return False


@bp.route("/inbound/postmark", methods=["GET", "POST"])
def inbound_postmark():
    # --- Healthcheck (einfach im Browser prüfbar)
    if request.method == "GET":
        return "inbound ok", 200

    # --- URL-Secret
    if request.args.get("secret") != os.getenv("INBOUND_SECRET", ""):
        abort(401)

    # --- optional Basic-Auth
    if not _check_basic_auth():
        abort(401)

    # --- rohen Body holen (für Signatur) + JSON parsen
    raw = request.get_data(cache=False, as_text=False)
    if not _check_postmark_signature(raw):
        abort(401)

    pm = request.get_json(force=True, silent=False)  # Postmark sendet JSON

    # --- Absender/Fallback-Prüfung
    outer_from = ((pm.get("FromFull") or {}).get("Email")) or pm.get("From") or ""
    sender_ok = _ok_sender(outer_from) or _ok_by_payload(pm)
    if not sender_ok:
        current_app.logger.warning(
            "Inbound blocked by sender filter",
            extra={"outer_from": outer_from}
        )
        abort(403)

    # --- Quelle bestimmen und zusammenfassen
    source = "kleinanzeigen" if is_from_kleinanzeigen(pm) else "email"
    summary = extract_summary(pm)

    # --- Event speichern / weiterreichen
    try:
        store_event(source, pm, summary=summary)
    except Exception as exc:
        current_app.logger.exception("Failed to store inbound event", extra={"err": str(exc)})
        # Wir antworten trotzdem 204, damit Postmark nicht spamt; Logging reicht uns hier.
        return "", 204

    # Postmark erwartet i. d. R. 200/204 bei Erfolg
    return "", 204
