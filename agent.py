# agent.py — Cron/HTTP-Worker für E-Mail-Benachrichtigungen (kompatibel zur app.py)
# - Liest Alerts aus search_alerts (is_active=1)
# - De-Dup über alert_seen(user_email, search_hash, src, item_id, first_seen, last_sent)
# - SMTP-Patch: unterstützt SMTP_* und EMAIL_*
# - NEU: Telegram-Integration
# - Aufruf: run_agent_once() (von /internal/run-agent) oder lokal via __main__

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

# Telegram-Import (optional, falls noch nicht verfügbar)
try:
    from models import SessionLocal, User
    from telegram_bot import send_new_item_alert

    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("[agent] Telegram module not available - continuing without Telegram alerts")

# In agent.py - nach Zeile 30 einfügen
try:
    from image_analyzer import check_item_damage

    VISION_AVAILABLE = True
except ImportError:
    VISION_AVAILABLE = False
    print("[agent] Image Analyzer nicht verfügbar")

# In agent.py nach Zeile 35
try:
    from smart_filters import apply_smart_filters

    SMART_FILTERS_AVAILABLE = True
except ImportError:
    SMART_FILTERS_AVAILABLE = False


# -----------------------
# Helpers & ENV
# -----------------------


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
    # erlaubt z.B. "sqlite:///instance/db.sqlite3"
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "", 1)
    return url


DB_URL = os.getenv("DB_PATH", "sqlite:///instance/db.sqlite3")
DB_FILE = sqlite_file_from_url(DB_URL)

# eBay API
EBAY_CLIENT_ID = getenv_any("EBAY_CLIENT_ID", "EBAY_APP_ID")
EBAY_CLIENT_SECRET = getenv_any("EBAY_CLIENT_SECRET", "EBAY_CERT_ID")
EBAY_SCOPES = os.getenv("EBAY_SCOPES", "https://api.ebay.com/oauth/api_scope")
EBAY_GLOBAL_ID = os.getenv("EBAY_GLOBAL_ID", "EBAY-DE")

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


# SMTP-Patch: primär SMTP_*, Fallback EMAIL_*
def get_smtp_settings() -> Dict[str, object]:
    host = os.getenv("SMTP_HOST") or os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT") or os.getenv("EMAIL_SMTP_PORT") or "587")
    user = os.getenv("SMTP_USER") or os.getenv("EMAIL_USER", "")
    pwd = os.getenv("SMTP_PASS") or os.getenv("EMAIL_PASSWORD", "")
    from_addr = (
        os.getenv("SMTP_FROM")
        or os.getenv("EMAIL_FROM")
        or (user or "alerts@localhost")
    )
    use_tls = as_bool(os.getenv("SMTP_USE_TLS", "1"))
    use_ssl = as_bool(os.getenv("SMTP_USE_SSL", "0"))
    return {
        "host": host,
        "port": port,
        "user": user,
        "password": pwd,
        "from": from_addr,
        "use_tls": use_tls,
        "use_ssl": use_ssl,
    }


NOTIFY_MAX_ITEMS_PER_MAIL = int(os.getenv("ALERT_MAX_ITEMS", "12"))
NOTIFY_MAX_ITEMS_TELEGRAM = int(os.getenv("TELEGRAM_MAX_ITEMS", "3"))
DEBUG_LOG = as_bool(os.getenv("ALERT_DEBUG", "0"))

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
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    )
    return bool(cur.fetchone())


def init_db_if_needed() -> None:
    # Nur anlegen, falls Tabellen fehlen. (Kompatibel zur app.py)
    conn = get_db()
    cur = conn.cursor()
    # search_alerts (wie in app.py)
    if not table_exists(conn, "search_alerts"):
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS search_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email   TEXT NOT NULL,
                terms_json   TEXT NOT NULL,
                filters_json TEXT NOT NULL,
                per_page     INTEGER NOT NULL DEFAULT 20,
                is_active    INTEGER NOT NULL DEFAULT 1,
                last_run_ts  INTEGER NOT NULL DEFAULT 0
            )
        """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_alerts_active ON search_alerts(is_active)"
        )
    # alert_seen (Schema aus app.py)
    if not table_exists(conn, "alert_seen"):
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS alert_seen (
                user_email   TEXT    NOT NULL,
                search_hash  TEXT    NOT NULL,
                src          TEXT    NOT NULL,
                item_id      TEXT    NOT NULL,
                first_seen   INTEGER NOT NULL,
                last_sent    INTEGER NOT NULL,
                PRIMARY KEY (user_email, search_hash, src, item_id)
            )
        """
        )
    conn.commit()
    conn.close()


# -----------------------
# SMTP
# -----------------------


def send_mail(
    smtp: Dict[str, object],
    to_addrs: Iterable[str],
    subject: str,
    body_html: str,
) -> bool:
    host = smtp.get("host")
    port = int(smtp.get("port") or 0)
    user = smtp.get("user")
    pwd = smtp.get("password")
    from_addr = smtp.get("from")
    use_tls = bool(smtp.get("use_tls"))
    use_ssl = bool(smtp.get("use_ssl"))

    if not host or not port or not from_addr or not to_addrs:
        print("[mail] SMTP config incomplete -> skip")
        return False
    if user and not pwd:
        print("[mail] SMTP password missing -> skip")
        return False

    msg = EmailMessage()
    msg["From"] = str(from_addr)
    msg["To"] = ", ".join([t for t in to_addrs if t])
    msg["Subject"] = subject
    msg.set_content("HTML only")
    msg.add_alternative(body_html, subtype="html")

    try:
        if use_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=context, timeout=60) as s:
                if user:
                    s.login(user, pwd)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=60) as s:
                if use_tls:
                    s.starttls(context=ssl.create_default_context())
                if user:
                    s.login(user, pwd)
                s.send_message(msg)
        print(f"[mail] sent via {host}:{port} tls={use_tls} ssl={use_ssl}")
        return True
    except Exception as e:
        print(f"[mail] ERROR: {e}")
        return False


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


def mark_and_filter_new(
    user_email: str, search_hash: str, src: str, items: List[Dict]
) -> List[Dict]:
    if not items:
        return []
    now = int(time.time())
    conn = get_db()
    cur = conn.cursor()
    new_items: List[Dict] = []
    for it in items:
        iid = str(it.get("id") or it.get("url") or it.get("title"))[:255]
        cur.execute(
            """
            SELECT last_sent FROM alert_seen
            WHERE user_email=? AND search_hash=? AND src=? AND item_id=?
        """,
            (user_email, search_hash, src, iid),
        )
        row = cur.fetchone()
        if not row:
            new_items.append(it)
            cur.execute(
                """
                INSERT INTO alert_seen (user_email, search_hash, src, item_id, first_seen, last_sent)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (user_email, search_hash, src, iid, now, 0),
            )
        else:
            # Cooldown-Logik optional: hier senden wir nochmal, wenn last_sent==0
            if int(row["last_sent"] or 0) == 0:
                new_items.append(it)
    conn.commit()
    conn.close()
    return new_items


def mark_sent(user_email: str, search_hash: str, src: str, items: List[Dict]) -> None:
    if not items:
        return
    now = int(time.time())
    conn = get_db()
    cur = conn.cursor()
    for it in items:
        iid = str(it.get("id") or it.get("url") or it.get("title"))[:255]
        cur.execute(
            """
            UPDATE alert_seen SET last_sent=?
            WHERE user_email=? AND search_hash=? AND src=? AND item_id=?
        """,
            (now, user_email, search_hash, src, iid),
        )
    conn.commit()
    conn.close()


# -----------------------
# eBay API
# -----------------------

_http = requests.Session()
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


# In agent.py - ca. Zeile 340


def _build_ebay_filter(
    price_min: str,
    price_max: str,
    conditions: List[str],
    # NEU: Zusätzliche Parameter
    listing_type: str = "all",
    location_country: str = "DE",
    free_shipping: bool = False,
    returns_accepted: bool = False,
    top_rated_only: bool = False,
) -> Optional[str]:
    parts: List[str] = []

    # Preis (BESTEHT SCHON)
    pmn = (price_min or "").strip()
    pmx = (price_max or "").strip()
    if pmn or pmx:
        parts.append(f"price:[{pmn}..{pmx}]")
        if EBAY_CURRENCY:
            parts.append(f"priceCurrency:{EBAY_CURRENCY}")

    # Zustand (BESTEHT SCHON)
    conds = [c.strip().upper() for c in (conditions or []) if c.strip()]
    if conds:
        parts.append("conditions:{" + ",".join(conds) + "}")

    # NEU: Angebotsformat
    if listing_type == "auction":
        parts.append("buyingOptions:{AUCTION}")
    elif listing_type == "buy_it_now":
        parts.append("buyingOptions:{FIXED_PRICE}")
    elif listing_type == "auction_with_bin":
        parts.append("buyingOptions:{AUCTION,FIXED_PRICE}")

    # NEU: Standort
    if location_country:
        parts.append(f"itemLocationCountry:{location_country}")

    # NEU: Kostenloser Versand
    if free_shipping:
        parts.append("deliveryOptions:{FREE}")

    # NEU: Rückgaberecht
    if returns_accepted:
        parts.append("returnsAccepted:true")

    # NEU: Top-bewertete Verkäufer
    if top_rated_only:
        parts.append("sellerLevel:TOP_RATED")

    return ",".join(parts) if parts else None


def _map_sort(s: str) -> Optional[str]:
    s = (s or "").strip()
    if not s or s == "best":
        return None
    if s == "price_asc":
        return "price"
    if s == "price_desc":
        return "-price"
    if s == "newly":
        return "newlyListed"
    return None


def ebay_search(
    term: str,
    limit: int,
    offset: int,
    price_min: str,
    price_max: str,
    conditions: List[str],
    sort_ui: str,
    listing_type: str = "all",
    location_country: str = "DE",
    max_distance_km: int = None,
    zip_code: str = None,
    free_shipping: bool = False,
    returns_accepted: bool = False,
    top_rated_only: bool = False,
) -> List[Dict]:
    tok = ebay_get_token()
    if not tok or not term:
        return []
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    params = {"q": term, "limit": max(1, min(limit, 50)), "offset": max(0, offset)}
    filt = _build_ebay_filter(price_min, price_max, conditions)
    listing_type: str = ("all",)
    location_country: str = ("DE",)
    max_distance_km: int = (None,)
    zip_code: str = (None,)
    free_shipping: bool = (False,)
    returns_accepted: bool = (False,)
    top_rated_only: bool = False
    if filt:
        params["filter"] = filt
        if zip_code and max_distance_km:
            params["filter"] = (
                params.get("filter", "") + f",maxDistance:{max_distance_km}km"
            )
            params["fieldgroups"] = "EXTENDED"  # Nötig für Standort-Daten
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
        for it in j.get("itemSummaries", []) or []:
            items.append(
                {
                    "id": it.get("itemId")
                    or it.get("legacyItemId")
                    or it.get("itemWebUrl"),
                    "title": it.get("title") or "—",
                    "url": it.get("itemWebUrl"),
                    "img": (it.get("image") or {}).get("imageUrl"),
                    "price": (it.get("price") or {}).get("value"),
                    "cur": (it.get("price") or {}).get("currency"),
                    "src": "ebay",
                }
            )
        return items
    except Exception as e:
        print(f"[ebay_search] {e}")
        return []

 # In agent.py
def search_all_platforms(terms, filters):
    results = []

    # eBay
    results.extend(search_ebay(terms, filters))

    # eBay Kleinanzeigen (vorsichtig scrapen)
    if user.plan in ["pro", "team"]:
        results.extend(search_kleinanzeigen(terms, filters))

    # Amazon (für Pro+)
    if user.plan == "team":
        results.extend(search_amazon_warehouse(terms, filters))

    return results

def get_related_searches(search_terms):
    # Analysiere was andere User mit ähnlichen Suchen noch suchen
    # ML-Algorithmus oder einfache Co-Occurrence

    similar_users = find_users_with_similar_searches(search_terms)
    their_other_searches = get_their_searches(similar_users)

    return top_related_searches(their_other_searches)



class NotificationSettings(Base):
    __tablename__ = "notification_settings"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)

    # Zeiten
    quiet_hours_start = Column(String(5))  # "22:00"
    quiet_hours_end = Column(String(5))    # "08:00"

    # Frequenz
    max_notifications_per_day = Column(Integer, default=50)
    batch_notifications = Column(Boolean, default=False)  # Sammeln & 1x täglich senden

    # Channels
    email_enabled = Column(Boolean, default=True)
    telegram_enabled = Column(Boolean, default=True)
    sms_enabled = Column(Boolean, default=False)  # Premium-Feature

    user = relationship("User")


    class AutoBid(Base):
        __tablename__ = "auto_bids"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))

    ebay_item_id = Column(String(255))
    max_bid_amount = Column(Float)
    increment = Column(Float, default=1.0)  # Erhöhung um 1€

    status = Column(String(20))  # active, won, lost, stopped
    current_bid = Column(Float)
    times_bid = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)


    class SellerAnalytics(Base):
        __tablename__ = "seller_analytics"

    seller_id = Column(String(255), primary_key=True)
    seller_name = Column(String(255))

    total_items_sold = Column(Integer)
    avg_price = Column(Float)
    avg_rating = Column(Float)
    response_time_hours = Column(Float)

    scam_score = Column(Float)  # 0-1, höher = verdächtiger

    last_updated = Column(DateTime, default=datetime.utcnow)def get_related_searches(search_terms):
    # Analysiere was andere User mit ähnlichen Suchen noch suchen
    # ML-Algorithmus oder einfache Co-Occurrence

    similar_users = find_users_with_similar_searches(search_terms)
    their_other_searches = get_their_searches(similar_users)

    return top_related_searches(their_other_searches)

@app.route("/export/alerts/<format>")
def export_alerts(format):
    # format: csv, pdf, excel

    user_alerts = get_user_alerts(user_id)

    if format == "csv":
        return generate_csv(user_alerts)
    elif format == "pdf":
        return generate_pdf_report(user_alerts)
    elif format == "excel":
        return generate_excel(user_alerts)

    @app.route("/api/v1/search")
def api_search():
    api_key = request.headers.get("X-API-Key")

    if not validate_api_key(api_key):
        return jsonify({"error": "Invalid API key"}), 401

    results = search_ebay(
        request.args.get("q"),
        request.args.get("filters")
    )

    return jsonify(results)





@app.route("/export/alerts/<format>")
def export_alerts(format):
    # format: csv, pdf, excel

    user_alerts = get_user_alerts(user_id)

    if format == "csv":
        return generate_csv(user_alerts)
    elif format == "pdf":
        return generate_pdf_report(user_alerts)
    elif format == "excel":
        return generate_excel(user_alerts)


    @app.route("/api/v1/search")
def api_search():
    api_key = request.headers.get("X-API-Key")

    if not validate_api_key(api_key):
        return jsonify({"error": "Invalid API key"}), 401

    results = search_ebay(
        request.args.get("q"),
        request.args.get("filters")
    )

    return jsonify(results)












# -----------------------
# Alerts laden (aus search_alerts)
# -----------------------


def load_alerts() -> List[Dict]:
    """
    Lädt aktive Alerts aus search_alerts und mapt sie auf ein einheitliches Dict.
    Rückgabe pro Alert:
      {
        'id': int,
        'user_email': str,
        'terms': List[str],
        'filters': {'price_min','price_max','sort','conditions':List[str]},
        'per_page': int
      }
    """
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
        # Normalisieren
        filters_norm = {
            "price_min": (filters.get("price_min") or "").strip(),
            "price_max": (filters.get("price_max") or "").strip(),
            "sort": (filters.get("sort") or "best").strip(),
            "conditions": [
                c.strip().upper()
                for c in (filters.get("conditions") or [])
                if c and str(c).strip()
            ],
        }
        out.append(
            {
                "id": int(r["id"]),
                "user_email": r["user_email"],
                "terms": [t for t in terms if str(t).strip()],
                "filters": filters_norm,
                "per_page": int(r["per_page"] or 30),
            }
        )
    return out


# -----------------------
# E-Mail-Rendering (simpel, HTML)
# -----------------------


def render_email_html(title: str, items: List[Dict]) -> str:
    rows = []
    for it in items[:NOTIFY_MAX_ITEMS_PER_MAIL]:
        price = (
            f"{it.get('price')} {it.get('cur')}"
            if it.get("price") and it.get("cur")
            else "–"
        )
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
# Telegram Alert
# -----------------------


def send_telegram_alert(user_email: str, items: List[Dict], terms: List[str]) -> bool:
    """
    Sendet Telegram-Alert für neue Items
    Returns: True wenn erfolgreich
    """
    if not TELEGRAM_AVAILABLE:
        return False

    try:
        db = SessionLocal()
        user = db.query(User).filter_by(email=user_email).first()

        if not user:
            db.close()
            if DEBUG_LOG:
                print(f"[telegram] User not found: {user_email}")
            return False

        if not user.telegram_verified or not user.telegram_enabled:
            db.close()
            if DEBUG_LOG:
                print(f"[telegram] Telegram not enabled for: {user_email}")
            return False

        # Nur die ersten N Items per Telegram (nicht überladen)
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
                        "condition": "",  # eBay API liefert das nicht immer
                        "location": "",
                    },
                    agent_name=f"eBay Alert: {', '.join(terms[:2])}",
                    with_image=bool(item.get("img")),
                )
                if success:
                    sent_count += 1
            except Exception as e:
                print(f"[telegram] Error sending item {item.get('id')}: {e}")
                continue

        db.close()

        if sent_count > 0:
            print(
                f"[telegram] Sent {sent_count}/{len(items_to_send)} items to {user_email}"
            )
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
      - Alerts laden (search_alerts)
      - je Alert: eBay suchen
      - De-Dup (alert_seen)
      - E-Mail senden
      - Telegram senden (NEU)
      - Versandte Items markieren
    """
    print(f"[agent] start run")
    init_db_if_needed()
    smtp = get_smtp_settings()

    alerts = load_alerts()
    if DEBUG_LOG:
        print(f"[agent] {len(alerts)} aktive Alerts")

    total_checked = 0
    total_mailed = 0
    total_telegram = 0

    for a in alerts:
        total_checked += 1
        terms = a["terms"]
        filters = a["filters"]
        per_page = int(a["per_page"] or 30)
        if not terms:
            continue

        # Suche – einfach gleichmäßig über Begriffe verteilen
        per_term = max(1, per_page // max(1, len(terms)))
        items_all: List[Dict] = []
        for t in terms:
            items = ebay_search(
                term=t,
                limit=per_term,
                offset=0,
                price_min=filters.get("price_min", ""),
                price_max=filters.get("price_max", ""),
                conditions=filters.get("conditions") or [],
                sort_ui=filters.get("sort", "best"),
            )
            items_all.extend(items)

    # Nach: items_all.extend(items)

# NEU: Preis-Historie aufzeichnen
try:
    from utils.price_analyzer import record_search_prices
    record_search_prices(
        search_term=" ".join(terms),
        items=items_all,
        condition=None
    )
except Exception as e:
    print(f"[PRICE] Fehler beim Aufzeichnen: {e}")

        # De-Dup
        search_hash = make_search_hash(terms, filters)
        groups: Dict[str, List[Dict]] = {}
        for it in items_all:
            src = (it.get("src") or "ebay").lower()
            groups.setdefault(src, []).append(it)

        new_all: List[Dict] = []
        for src, group in groups.items():
            new_items = mark_and_filter_new(a["user_email"], search_hash, src, group)
            new_all.extend(new_items)

        if not new_all or not a["user_email"] or "@" not in a["user_email"]:
            if DEBUG_LOG:
                print(f"[agent] alert_id={a['id']} no new items or invalid email")
            continue

        subject = f"Neue Treffer für '{', '.join(terms)}' - {len(new_all)} neu"
        html = render_email_html(subject, new_all)

        # Vor: send_mail(...)

# NEU: Nutze Notification Manager statt direktem send_mail
try:
    from utils.notification_manager import get_notification_manager

    manager = get_notification_manager()

    # Sende via Smart Notifications
    result = manager.send_notification(
        user_id=user.id,  # Du musst User-Objekt haben
        notification_type="new_items",
        channel="email",
        subject=subject,
        content=html,
        agent_id=a["id"]
    )

    if result["sent"]:
        print(f"[NOTIFICATION] Alert gesendet an {a['user_email']}")

        # Auch Telegram senden
        manager.send_notification(
            user_id=user.id,
            notification_type="new_items",
            channel="telegram",
            subject=subject,
            content=f"Neue Treffer: {len(new_all)} Items gefunden!",
            agent_id=a["id"]
        )

except Exception as e:
    print(f"[NOTIFICATION] Fehler: {e}")
    # Fallback auf altes System
    send_mail(smtp, [a["user_email"]], subject, html)

        # E-Mail senden
        if send_mail(smtp, [a["user_email"]], subject, html):
            for src, group in groups.items():
                sent_subset = [
                    it for it in new_all if (it.get("src") or "ebay").lower() == src
                ]
                mark_sent(a["user_email"], search_hash, src, sent_subset)
            total_mailed += 1

            # Telegram senden (NEU)
            if TELEGRAM_AVAILABLE:
                try:
                    if send_telegram_alert(a["user_email"], new_all, terms):
                        total_telegram += 1
                except Exception as e:
                    print(f"[telegram] Failed for {a['user_email']}: {e}")

        # last_run_ts aktualisieren
        conn = get_db()
        conn.execute(
            "UPDATE search_alerts SET last_run_ts=? WHERE id=?",
            (int(time.time()), int(a["id"])),
        )
        conn.commit()
        conn.close()

    summary_msg = f"[agent] summary: alerts_checked={total_checked} alerts_emailed={total_mailed} alerts_telegram={total_telegram}"
    print(summary_msg)
    print("[agent] end run")


# Für lokalen Test:
if __name__ == "__main__":
    run_agent_once()
