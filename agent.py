# agent.py — Worker für E-Mail-Benachrichtigungen (API-first mit Postmark, Fallback SMTP)
# - Lädt aktive Alerts aus search_alerts (is_active=1)
# - De-Dup über alert_seen(user_email, search_hash, src, item_id, first_seen, last_sent)
# - Mail: Postmark-API (bevorzugt) oder SMTP-Fallback
# - Optional: Telegram (wenn Module vorhanden)
# - Aufruf: run_agent_once()

from __future__ import annotations

import hashlib
import json
import os
import smtplib
import sqlite3
import ssl
import time
from email.message import EmailMessage
from typing import Dict, Iterable, List, Optional, Tuple

import requests

# -------------------------------------------------
# Optionale Integrationen (nicht zwingend vorhanden)
# -------------------------------------------------
try:
    from models import SessionLocal, User
    from telegram_bot import send_new_item_alert
    TELEGRAM_AVAILABLE = True
except Exception:
    TELEGRAM_AVAILABLE = False
    print("[agent] Telegram module not available - continuing without Telegram alerts")

try:
    from image_analyzer import check_item_damage  # noqa: F401
    VISION_AVAILABLE = True
except Exception:
    VISION_AVAILABLE = False

try:
    from smart_filters import apply_smart_filters  # noqa: F401
    SMART_FILTERS_AVAILABLE = True
except Exception:
    SMART_FILTERS_AVAILABLE = False

# -----------------------
# Helper & ENV
# -----------------------
_http = requests.Session()

def as_bool(v: Optional[str], default=False) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "on"}

def getenv_any(*names: str, default: str = "") -> str:
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    return default

def sqlite_file_from_url(url: str) -> str:
    # erlaubt z. B. "sqlite:///instance/db.sqlite3"
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "", 1)
    return url

DB_URL  = os.getenv("DB_PATH", "sqlite:///instance/db.sqlite3")
DB_FILE = sqlite_file_from_url(DB_URL)

# eBay API
EBAY_CLIENT_ID     = getenv_any("EBAY_CLIENT_ID", "EBAY_APP_ID")
EBAY_CLIENT_SECRET = getenv_any("EBAY_CLIENT_SECRET", "EBAY_CERT_ID")
EBAY_SCOPES        = os.getenv("EBAY_SCOPES", "https://api.ebay.com/oauth/api_scope")
EBAY_GLOBAL_ID     = os.getenv("EBAY_GLOBAL_ID", "EBAY-DE")

MARKETPLACE_BY_GLOBAL = {
    "EBAY-DE": ("EBAY_DE", "EUR"),
    "EBAY-AT": ("EBAY_AT", "EUR"),
    "EBAY-CH": ("EBAY_CH", "CHF"),
    "EBAY-GB": ("EBAY_GB", "GBP"),
    "EBAY-US": ("EBAY_US", "USD"),
}
EBAY_MARKETPLACE_ID, EBAY_CURRENCY = MARKETPLACE_BY_GLOBAL.get(
    EBAY_GLOBAL_ID, ("EBAY_DE", "EUR")
)

# Mail – Postmark-API bevorzugen, mehrere ENV-Alias unterstützt
POSTMARK_TOKEN = (
    getenv_any("POSTMARK_API_TOKEN", "POSTMARK_SERVER_TOKEN", "POSTMARK_TOKEN")
)
POSTMARK_FROM  = getenv_any("FROM_EMAIL", "EMAIL_FROM", "POSTMARK_FROM")
EMAIL_PROVIDER = (os.getenv("EMAIL_PROVIDER") or "").lower()
USE_POSTMARK   = (EMAIL_PROVIDER == "postmark") or (bool(POSTMARK_TOKEN) and bool(POSTMARK_FROM))

NOTIFY_MAX_ITEMS_PER_MAIL  = int(os.getenv("ALERT_MAX_ITEMS", "12"))
NOTIFY_MAX_ITEMS_TELEGRAM  = int(os.getenv("TELEGRAM_MAX_ITEMS", "3"))
DEBUG_LOG                  = as_bool(os.getenv("ALERT_DEBUG", "0"))

# Optional: Empfänger-Whitelist (Komma/semi-kolon getrennt)
_PILOT = os.getenv("PILOT_EMAILS", "")
PILOT_EMAILS = {e.strip().lower() for part in _PILOT.split(",") for e in part.split(";") if e.strip()}

# -----------------------
# DB
# -----------------------
def get_db() -> sqlite3.Connection:
    dirname = os.path.dirname(DB_FILE)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return bool(cur.fetchone())

def init_db_if_needed() -> None:
    conn = get_db()
    cur = conn.cursor()
    if not table_exists(conn, "search_alerts"):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS search_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email   TEXT NOT NULL,
                terms_json   TEXT NOT NULL,
                filters_json TEXT NOT NULL,
                per_page     INTEGER NOT NULL DEFAULT 20,
                is_active    INTEGER NOT NULL DEFAULT 1,
                last_run_ts  INTEGER NOT NULL DEFAULT 0
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_alerts_active ON search_alerts(is_active)")
    if not table_exists(conn, "alert_seen"):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS alert_seen (
                user_email   TEXT    NOT NULL,
                search_hash  TEXT    NOT NULL,
                src          TEXT    NOT NULL,
                item_id      TEXT    NOT NULL,
                first_seen   INTEGER NOT NULL,
                last_sent    INTEGER NOT NULL,
                PRIMARY KEY (user_email, search_hash, src, item_id)
            )
        """)
    conn.commit()
    conn.close()

# -----------------------
# Mail (API-first)
# -----------------------
def get_mail_settings() -> Dict[str, object]:
    """Gibt entweder Postmark- oder SMTP-Einstellungen zurück."""
    if USE_POSTMARK:
        return {
            "provider": "postmark",
            "api_key": POSTMARK_TOKEN,
            "from": POSTMARK_FROM,
        }
    # SMTP Fallback (nur wenn wirklich konfiguriert)
    host = getenv_any("SMTP_HOST", "EMAIL_SMTP_HOST")
    port = int(getenv_any("SMTP_PORT", "EMAIL_SMTP_PORT", default="0") or 0)
    user = getenv_any("SMTP_USER", "EMAIL_USER")
    pwd  = getenv_any("SMTP_PASS", "EMAIL_PASSWORD")
    from_addr = getenv_any("SMTP_FROM", "EMAIL_FROM") or user or "alerts@localhost"
    use_tls = as_bool(os.getenv("SMTP_USE_TLS", "1"))
    use_ssl = as_bool(os.getenv("SMTP_USE_SSL", "0"))
    return {
        "provider": "smtp",
        "host": host,
        "port": port,
        "user": user,
        "password": pwd,
        "from": from_addr,
        "use_tls": use_tls,
        "use_ssl": use_ssl,
    }

def send_mail_postmark(api_key: str, from_addr: str, to_addrs: Iterable[str],
                       subject: str, body_html: str) -> bool:
    """Sendet E-Mail via Postmark API"""
    if not api_key or not from_addr or not to_addrs:
        print("[postmark] Config incomplete")
        return False

    url = "https://api.postmarkapp.com/email"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Postmark-Server-Token": api_key
    }

    success_count = 0
    total_count = 0

    for to_addr in to_addrs:
        if not to_addr or "@" not in to_addr:
            continue

        total_count += 1
        payload = {
            "From": from_addr,
            "To": to_addr,
            "Subject": subject,
            "HtmlBody": body_html,
            "MessageStream": "outbound"
        }

        try:
            r = _http.post(url, json=payload, headers=headers, timeout=30)
            r.raise_for_status()
            response_data = r.json()
            message_id = response_data.get('MessageID', 'unknown')
            print(f"[postmark] ✓ Sent to {to_addr} (ID: {message_id})")
            success_count += 1
        except requests.exceptions.HTTPError as e:
            print(f"[postmark] ✗ HTTP ERROR {e.response.status_code}: {e.response.text}")
        except Exception as e:
            print(f"[postmark] ✗ ERROR: {e}")

    # Erfolg wenn mindestens eine Mail raus ging
    return success_count > 0

def send_mail_smtp(settings: Dict[str, object], to_addrs: Iterable[str],
                   subject: str, body_html: str) -> bool:
    host = settings.get("host"); port = int(settings.get("port") or 0)
    user = settings.get("user");  pwd  = settings.get("password")
    from_addr = settings.get("from")
    use_tls = bool(settings.get("use_tls")); use_ssl = bool(settings.get("use_ssl"))

    if not host or not port or not from_addr:
        print("[mail] SMTP config incomplete -> skip")
        return False
    if user and not pwd:
        print("[mail] SMTP password missing -> skip")
        return False

    msg = EmailMessage()
    msg["From"] = str(from_addr)
    msg["To"]   = ", ".join([t for t in to_addrs if t])
    msg["Subject"] = subject
    msg.set_content("HTML only")
    msg.add_alternative(body_html, subtype="html")

    try:
        if use_ssl:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=60) as s:
                if user: s.login(user, pwd)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=60) as s:
                if use_tls: s.starttls(context=ssl.create_default_context())
                if user: s.login(user, pwd)
                s.send_message(msg)
        print(f"[mail] sent via SMTP {host}:{port} tls={use_tls} ssl={use_ssl}")
        return True
    except Exception as e:
        print(f"[mail] SMTP ERROR: {e}")
        return False

def send_mail(settings: Dict[str, object], to_addrs: Iterable[str],
              subject: str, body_html: str) -> bool:
    provider = (settings.get("provider") or "smtp").lower()
    if provider == "postmark":
        return send_mail_postmark(
            api_key=settings.get("api_key"),
            from_addr=settings.get("from"),
            to_addrs=to_addrs,
            subject=subject,
            body_html=body_html,
        )
    return send_mail_smtp(settings, to_addrs, subject, body_html)

# -----------------------
# De-Dup kompatibel zur app.py
# -----------------------
def make_search_hash(terms: List[str], filters: Dict[str, object]) -> str:
    payload = {
        "terms": [t.strip() for t in terms if str(t).strip()],
        "filters": {
            "price_min": (filters.get("price_min") or ""),
            "price_max": (filters.get("price_max") or ""),
            "sort": (filters.get("sort") or "best"),
            "conditions": sorted(filters.get("conditions") or []),
        },
    }
    s = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()

def mark_and_filter_new(user_email: str, search_hash: str, src: str,
                        items: List[Dict]) -> List[Dict]:
    if not items:
        return []
    now = int(time.time())
    conn = get_db(); cur = conn.cursor()
    new_items: List[Dict] = []
    for it in items:
        iid = str(it.get("id") or it.get("url") or it.get("title"))[:255]
        cur.execute("""
            SELECT last_sent FROM alert_seen
            WHERE user_email=? AND search_hash=? AND src=? AND item_id=?
        """, (user_email, search_hash, src, iid))
        row = cur.fetchone()
        if not row:
            new_items.append(it)
            cur.execute("""
                INSERT INTO alert_seen (user_email, search_hash, src, item_id, first_seen, last_sent)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_email, search_hash, src, iid, now, 0))
        else:
            if int(row["last_sent"] or 0) == 0:
                new_items.append(it)
    conn.commit(); conn.close()
    return new_items

def mark_sent(user_email: str, search_hash: str, src: str, items: List[Dict]) -> None:
    if not items:
        return
    now = int(time.time())
    conn = get_db(); cur = conn.cursor()
    for it in items:
        iid = str(it.get("id") or it.get("url") or it.get("title"))[:255]
        cur.execute("""
            UPDATE alert_seen SET last_sent=?
            WHERE user_email=? AND search_hash=? AND src=? AND item_id=?
        """, (now, user_email, search_hash, src, iid))
    conn.commit(); conn.close()

# -----------------------
# eBay API
# -----------------------
_EBAY_TOKEN: Dict[str, object] = {"access_token": None, "expires_at": 0.0}

def ebay_get_token() -> Optional[str]:
    now = time.time()
    if _EBAY_TOKEN["access_token"] and now < float(_EBAY_TOKEN["expires_at"] or 0):
        return str(_EBAY_TOKEN["access_token"])
    if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
        print("[ebay] Missing client id/secret")
        return None
    url = "https://api.ebay.com/identity/v1/oauth2/token"
    auth = requests.auth.HTTPBasicAuth(EBAY_CLIENT_ID, EBAY_CLIENT_SECRET)
    data = {"grant_type": "client_credentials", "scope": EBAY_SCOPES}
    try:
        r = _http.post(url, auth=auth, data=data, timeout=20)
        r.raise_for_status()
        j = r.json() or {}
        _EBAY_TOKEN["access_token"] = j.get("access_token")
        _EBAY_TOKEN["expires_at"] = time.time() + int(j.get("expires_in", 7200)) - 60
        return str(_EBAY_TOKEN["access_token"])
    except Exception as e:
        print(f"[ebay_token] {e}")
        return None

def _build_ebay_filter(price_min: str, price_max: str, conditions: List[str]) -> Optional[str]:
    parts: List[str] = []
    pmn = (price_min or "").strip()
    pmx = (price_max or "").strip()
    if pmn or pmx:
        parts.append(f"price:[{pmn}..{pmx}]")
        if EBAY_CURRENCY:
            parts.append(f"priceCurrency:{EBAY_CURRENCY}")
    conds = [c.strip().upper() for c in (conditions or []) if c and c.strip()]
    if conds:
        parts.append("conditions:{" + ",".join(conds) + "}")
    return ",".join(parts) if parts else None

def _map_sort(s: str) -> Optional[str]:
    s = (s or "").strip().lower()
    if not s or s == "best":
        return None
    if s == "price_asc":
        return "price"
    if s == "price_desc":
        return "-price"
    if s == "newly":
        return "newlyListed"
    return None

def ebay_search(term: str, limit: int, offset: int,
                price_min: str, price_max: str,
                conditions: List[str], sort_ui: str) -> List[Dict]:
    tok = ebay_get_token()
    if not tok or not term:
        return []
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    params = {"q": term, "limit": max(1, min(limit, 50)), "offset": max(0, offset)}
    filt = _build_ebay_filter(price_min, price_max, conditions)
    if filt:
        params["filter"] = filt
    srt = _map_sort(sort_ui)
    if srt:
        params["sort"] = srt
    headers = {
        "Authorization": f"Bearer {tok}",
        "X-EBAY-C-MARKETPLACE-ID": EBAY_MARKETPLACE_ID,
    }
    try:
        r = _http.get(url, headers=headers, params=params, timeout=20)
        r.raise_for_status()
        j = r.json() or {}
        items: List[Dict] = []
        for it in (j.get("itemSummaries") or []):
            items.append({
                "id": it.get("itemId") or it.get("legacyItemId") or it.get("itemWebUrl"),
                "title": it.get("title") or "—",
                "url": it.get("itemWebUrl"),
                "img": (it.get("image") or {}).get("imageUrl"),
                "price": (it.get("price") or {}).get("value"),
                "cur": (it.get("price") or {}).get("currency"),
                "src": "ebay",
            })
        return items
    except Exception as e:
        print(f"[ebay_search] {e}")
        return []

# -----------------------
# Alerts laden
# -----------------------
def load_alerts() -> List[Dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT id, user_email, terms_json, filters_json, per_page FROM search_alerts WHERE is_active=1"
    ).fetchall()
    conn.close()
    out: List[Dict] = []
    for r in rows:
        try:
            terms = json.loads(r["terms_json"] or "[]") or []
        except Exception:
            terms = []
        try:
            filters = json.loads(r["filters_json"] or "{}") or {}
        except Exception:
            filters = {}
        filters_norm = {
            "price_min": (filters.get("price_min") or "").strip(),
            "price_max": (filters.get("price_max") or "").strip(),
            "sort": (filters.get("sort") or "best").strip(),
            "conditions": [c.strip().upper() for c in (filters.get("conditions") or []) if c and str(c).strip()],
        }
        out.append({
            "id": int(r["id"]),
            "user_email": r["user_email"],
            "terms": [t for t in terms if str(t).strip()],
            "filters": filters_norm,
            "per_page": int(r["per_page"] or 30),
        })
    return out

# -----------------------
# E-Mail-Rendering (simpel, HTML)
# -----------------------
def render_email_html(title: str, items: List[Dict]) -> str:
    rows = []
    for it in items[:NOTIFY_MAX_ITEMS_PER_MAIL]:
        price = f"{it.get('price')} {it.get('cur')}" if it.get("price") and it.get("cur") else "–"
        img = it.get("img") or "https://via.placeholder.com/96x72?text=%20"
        url = it.get("url") or "#"
        title_txt = it.get("title") or "—"
        rows.append(
            "<tr style='border-bottom:1px solid #eee'>"
            f"<td style='padding:8px;width:96px'><img src='{img}' width='96' height='72' style='border-radius:4px;object-fit:cover'></td>"
            f"<td style='padding:8px'><a href='{url}' target='_blank'>{title_txt}</a><br>"
            f"<span style='color:#666;font-size:12px'>{price}</span></td>"
            "</tr>"
        )
    more = ""
    if len(items) > NOTIFY_MAX_ITEMS_PER_MAIL:
        more = f"<p style='margin-top:8px'>+ {len(items)-NOTIFY_MAX_ITEMS_PER_MAIL} weitere Treffer …</p>"
    return (
        "<div style='font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif'>"
        f"<h3 style='margin:0 0 12px'>{title}</h3>"
        "<table style='width:100%;border-collapse:collapse'>"
        + "".join(rows)
        + "</table>"
        f"{more}"
        "<p style='margin-top:16px;color:#666;font-size:12px'>Du erhältst diese Mail, weil du für diese Suche einen Alarm aktiviert hast.</p>"
        "</div>"
    )

# -----------------------
# Telegram Alert (optional)
# -----------------------
def send_telegram_alert(user_email: str, items: List[Dict], terms: List[str]) -> bool:
    if not TELEGRAM_AVAILABLE:
        return False
    try:
        db = SessionLocal()
        user = db.query(User).filter_by(email=user_email).first()
        if not user or not user.telegram_verified or not user.telegram_enabled:
            db.close()
            if DEBUG_LOG:
                print(f"[telegram] not enabled for: {user_email}")
            return False
        items_to_send = items[:NOTIFY_MAX_ITEMS_TELEGRAM]
        sent_count = 0
        for item in items_to_send:
            try:
                success = send_new_item_alert(
                    chat_id=user.telegram_chat_id,
                    item={
                        "title": item.get("title", "Unbekannter Artikel"),
                        "price": str(item.get("price", "")),
                        "currency": item.get("cur", "EUR"),
                        "url": item.get("url", ""),
                        "image_url": item.get("img"),
                        "condition": "",
                        "location": "",
                    },
                    agent_name=f"eBay Alert: {', '.join(terms[:2])}",
                    with_image=bool(item.get("img")),
                )
                if success:
                    sent_count += 1
            except Exception as e:
                print(f"[telegram] Error sending item {item.get('id')}: {e}")
        db.close()
        if sent_count > 0:
            print(f"[telegram] Sent {sent_count}/{len(items_to_send)} items to {user_email}")
            return True
        return False
    except Exception as e:
        print(f"[telegram] Error sending alert to {user_email}: {e}")
        return False

# -----------------------
# Orchestrator
# -----------------------
def run_agent_once() -> None:
    """
    Ein Lauf:
      - Alerts laden
      - eBay suchen
      - De-Dup
      - E-Mail (Postmark bevorzugt) & optional Telegram
      - Versandte Items markieren
    """
    print("[agent] start run")
    init_db_if_needed()
    mail_settings = get_mail_settings()

    alerts = load_alerts()
    if DEBUG_LOG:
        print(f"[agent] {len(alerts)} aktive Alerts")

    total_checked = 0
    total_mailed = 0
    total_telegram = 0

    for a in alerts:
        total_checked += 1
        terms   = a["terms"]
        filters = a["filters"]
        per_page = max(1, int(a["per_page"] or 30))
        if not terms:
            continue

        # optional Pilot-Whitelist
        recipient = (a["user_email"] or "").strip()
        if PILOT_EMAILS and recipient.lower() not in PILOT_EMAILS:
            if DEBUG_LOG:
                print(f"[agent] skip (not whitelisted): {recipient}")
            continue

        # Suche – gleichmäßig über Begriffe verteilen
        per_term = max(1, per_page // max(1, len(terms)))
        items_all: List[Dict] = []
        for t in terms:
            items = ebay_search(
                term=t, limit=per_term, offset=0,
                price_min=filters.get("price_min", ""),
                price_max=filters.get("price_max", ""),
                conditions=filters.get("conditions") or [],
                sort_ui=filters.get("sort", "best"),
            )
            items_all.extend(items)

        # De-Dup
        search_hash = make_search_hash(terms, filters)
        groups: Dict[str, List[Dict]] = {}
        for it in items_all:
            src = (it.get("src") or "ebay").lower()
            groups.setdefault(src, []).append(it)

        new_all: List[Dict] = []
        for src, group in groups.items():
            new_items = mark_and_filter_new(recipient, search_hash, src, group)
            new_all.extend(new_items)

        if not new_all or not recipient or "@" not in recipient:
            if DEBUG_LOG:
                print(f"[agent] alert_id={a['id']} no new items or invalid email")
            continue

        subject = f"Neue Treffer für '{', '.join(terms)}' - {len(new_all)} neu"
        html    = render_email_html(subject, new_all)

        # Versand (API-first)
        if send_mail(mail_settings, [recipient], subject, html):
            for src, group in groups.items():
                sent_subset = [it for it in new_all if (it.get("src") or "ebay").lower() == src]
                mark_sent(recipient, search_hash, src, sent_subset)
            total_mailed += 1

            # Telegram (optional)
            try:
                if send_telegram_alert(recipient, new_all, terms):
                    total_telegram += 1
            except Exception as e:
                print(f"[telegram] Failed for {recipient}: {e}")

        # last_run_ts aktualisieren
        conn = get_db()
        conn.execute("UPDATE search_alerts SET last_run_ts=? WHERE id=?", (int(time.time()), int(a["id"])))
        conn.commit(); conn.close()

    print(f"[agent] summary: alerts_checked={total_checked} alerts_emailed={total_mailed} alerts_telegram={total_telegram}")
    print("[agent] end run")

if __name__ == "__main__":
    run_agent_once()

