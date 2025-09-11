# routes/inbound.py
import os, time, re, hmac, base64, hashlib
from flask import Blueprint, request, jsonify, abort

bp = Blueprint("inbound", __name__)

# sehr einfache Extraktion aus Kleinanzeigen-Mails
_RX_URL   = re.compile(r"https?://www\.kleinanzeigen\.de/s-anzeige/[^\s\"'>]+", re.I)
_RX_PRICE = re.compile(r"(\d+[.,]?\d*)\s*€", re.I)

def _ok_sender(sender: str) -> bool:
    allowed = os.getenv("INBOUND_ALLOWED_SENDERS", "")
    if not allowed:
        return True
    sender = (sender or "").lower()
    for patt in [p.strip().lower().replace("*", "") for p in allowed.split(",") if p.strip()]:
        if patt and patt in sender:
            return True
    return False

def _check_basic_auth() -> bool:
    user = os.getenv("INBOUND_BASIC_USER")
    pw   = os.getenv("INBOUND_BASIC_PASS")
    if not user or not pw:
        return True
    auth = request.headers.get("Authorization", "")
    expected = "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()
    return auth == expected

@bp.route("/inbound/postmark", methods=["GET", "POST"])
def inbound_postmark():
    # ---- einfacher GET-Healthcheck (damit du im Browser sofort siehst, ob die Route da ist)
    if request.method == "GET":
        return "inbound ok", 200

    # ---- URL-Secret prüfen
    if request.args.get("secret") != os.getenv("INBOUND_SECRET", ""):
        abort(401)

    # ---- optional Basic-Auth prüfen
    if not _check_basic_auth():
        abort(401)

    # ---- optional: Postmark-Signatur prüfen (nur wenn Key gesetzt ist)
    pm_secret = os.getenv("POSTMARK_INBOUND_SIGNING_SECRET", "")
    if pm_secret:
        raw = request.get_data()
        sig = request.headers.get("X-Postmark-Signature", "")
        calc = hmac.new(pm_secret.encode(), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(base64.b64encode(calc).decode(), sig):
            abort(401)

    payload = request.get_json(force=True, silent=True) or {}
    from_addr = (payload.get("FromFull") or {}).get("Email") or payload.get("From")
    if not _ok_sender(from_addr):
        abort(403)

    text = (payload.get("TextBody") or "") + "\n" + (payload.get("HtmlBody") or "")
    urls = list(dict.fromkeys(_RX_URL.findall(text)))[:10]
    m_price = _RX_PRICE.search(text)
    price = float(m_price.group(1).replace(",", ".")) if m_price else None

    items = [{
        "id": u,
        "title": payload.get("Subject") or "Kleinanzeigen Angebot",
        "url": u,
        "price": price,
        "currency": "EUR" if price is not None else None,
        "image": None,
        "condition": "used",
        "source": "ebk",
        "seen_at": int(time.time()),
    } for u in urls]

    return jsonify({"received": len(items), "items": items}), 200
