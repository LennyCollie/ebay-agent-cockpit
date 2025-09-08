import os
import json
import time
import math
import base64
import sqlite3
import smtplib
import ssl
import hashlib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from urllib.parse import urlencode
from mailer import send_mail
from datetime import datetime
  

import requests
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify,
    abort,
    current_app,
    Blueprint,
)


from mailer import send_mail
# -------------------------------------------------------------------
# .env laden
# -------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv(".env.local", override=True)
    load_dotenv()
except Exception:
    pass

# -------------------------------------------------------------------
# App & Basis-Konfig
# -------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-me")

# Plausible (für base.html)
PLAUSIBLE_DOMAIN = os.getenv("PLAUSIBLE_DOMAIN", "")

def as_bool(val: Optional[str]) -> bool:
    return str(val).strip().lower() in {"1", "true", "yes", "on"}

def getenv_any(*names: str, default: str = "") -> str:
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    return default

# --- Security Headers (basic hardening) ---
@app.after_request
def add_security_headers(resp):
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # optional, aber sinnvoll:
    resp.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    return resp


# Limits / Defaults
FREE_SEARCH_LIMIT     = int(os.getenv("FREE_SEARCH_LIMIT", "3"))
PREMIUM_SEARCH_LIMIT  = int(os.getenv("PREMIUM_SEARCH_LIMIT", "10"))
PER_PAGE_DEFAULT      = int(os.getenv("PER_PAGE_DEFAULT", "20"))
SEARCH_CACHE_TTL      = int(os.getenv("SEARCH_CACHE_TTL", "60"))  # Sekunden

# E-Mail / Notify
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", "Agent <noreply@example.com>")
SMTP_USE_TLS = as_bool(os.getenv("SMTP_USE_TLS", "1"))
SMTP_USE_SSL = as_bool(os.getenv("SMTP_USE_SSL", "0"))
NOTIFY_COOLDOWN_MIN = int(os.getenv("NOTIFY_COOLDOWN_MINUTES", "120"))
NOTIFY_MAX_ITEMS_PER_MAIL = int(os.getenv("NOTIFY_MAX_ITEMS_PER_MAIL", "10"))

# NEU: Token für den privaten HTTP-Cron-Trigger
AGENT_TRIGGER_TOKEN = os.getenv("AGENT_TRIGGER_TOKEN", "")

# ALT (deprecated): Query-Token für /cron/run-alerts
CRON_TOKEN = os.getenv("CRON_TOKEN", "")

# DB (SQLite Pfad auch für Render kompatibel)
DB_URL = os.getenv("DB_PATH", "sqlite:///instance/db.sqlite3")
def _sqlite_file_from_url(url: str) -> Path:
    if url.startswith("sqlite:///"):
        rel = url.replace("sqlite:///", "", 1)
        return Path(rel)
    return Path(url)
DB_FILE = _sqlite_file_from_url(DB_URL)
DB_FILE.parent.mkdir(parents=True, exist_ok=True)

# -------------------------------------------------------------------
# eBay – OAuth Client Credentials + Suche
# -------------------------------------------------------------------
EBAY_CLIENT_ID     = getenv_any("EBAY_CLIENT_ID", "EBAY_APP_ID")
EBAY_CLIENT_SECRET = getenv_any("EBAY_CLIENT_SECRET", "EBAY_CERT_ID")
EBAY_SCOPES        = os.getenv("EBAY_SCOPES", "https://api.ebay.com/oauth/api_scope")
EBAY_GLOBAL_ID     = os.getenv("EBAY_GLOBAL_ID", "EBAY-DE")
LIVE_SEARCH        = as_bool(os.getenv("LIVE_SEARCH", "0"))

def _marketplace_from_global(gid: str) -> str:
    gid = (gid or "").upper()
    if gid in {"EBAY-DE", "EBAY_DE"}: return "EBAY_DE"
    if gid in {"EBAY-US", "EBAY_US"}: return "EBAY_US"
    if gid in {"EBAY-GB", "EBAY_GB"}: return "EBAY_GB"
    if gid in {"EBAY-FR", "EBAY_FR"}: return "EBAY_FR"
    return "EBAY_DE"

def _currency_for_marketplace(mkt: str) -> str:
    mkt = (mkt or "").upper()
    if mkt == "EBAY_US": return "USD"
    if mkt == "EBAY_GB": return "GBP"
    if mkt == "EBAY_FR": return "EUR"
    return "EUR"

EBAY_MARKETPLACE_ID = _marketplace_from_global(EBAY_GLOBAL_ID)
EBAY_CURRENCY       = _currency_for_marketplace(EBAY_MARKETPLACE_ID)

# Optional: Affiliate-Parameter (an itemWebUrl anhängen)
AFFILIATE_PARAMS = os.getenv("AFFILIATE_PARAMS", "")  # "campid=XXXX;customid=YOURTAG"
def _append_affiliate(url: Optional[str]) -> Optional[str]:
    if not url or not AFFILIATE_PARAMS:
        return url
    parts = [p.strip() for p in AFFILIATE_PARAMS.split(";") if p.strip()]
    q = "&".join(parts)
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{q}" if q else url

# HTTP Session + Token Cache
_http = requests.Session()
_EBAY_TOKEN: Dict[str, object] = {"access_token": None, "expires_at": 0.0}

def ebay_get_token() -> Optional[str]:
    tok = _EBAY_TOKEN.get("access_token")
    if tok and time.time() < float(_EBAY_TOKEN.get("expires_at") or 0):
        return str(tok)

    if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
        print("[ebay_get_token] missing client id/secret")
        return None

    token_url = "https://api.ebay.com/identity/v1/oauth2/token"
    basic = base64.b64encode(f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}".encode()).decode()
    headers = {"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"}
    data = {"grant_type": "client_credentials", "scope": EBAY_SCOPES}
    try:
        r = _http.post(token_url, headers=headers, data=data, timeout=15)
        r.raise_for_status()
        j = r.json() or {}
        _EBAY_TOKEN["access_token"] = j.get("access_token")
        _EBAY_TOKEN["expires_at"]   = time.time() + int(j.get("expires_in", 7200)) - 60
        return str(_EBAY_TOKEN["access_token"])
    except Exception as e:
        print(f"[ebay_get_token] {e}")
        return None

def _build_ebay_filters(price_min: str, price_max: str, conditions: List[str]) -> Optional[str]:
    parts: List[str] = []
    pmn = (price_min or "").strip()
    pmx = (price_max or "").strip()
    if pmn or pmx:
        parts.append(f"price:[{pmn}..{pmx}]")
        if EBAY_CURRENCY:
            parts.append(f"priceCurrency:{EBAY_CURRENCY}")
    conds = [c.strip().upper() for c in (conditions or []) if c.strip()]
    if conds:
        parts.append("conditions:{" + ",".join(conds) + "}")
    return ",".join(parts) if parts else None

def _map_sort(ui_sort: str) -> Optional[str]:
    s = (ui_sort or "").strip()
    if not s or s == "best":  # Best Match
        return None
    if s == "price_asc":  return "price"
    if s == "price_desc": return "-price"
    if s == "newly":      return "newlyListed"
    return None

def ebay_search_one(term: str, limit: int, offset: int,
                    filter_str: Optional[str], sort: Optional[str]) -> Tuple[List[Dict], Optional[int]]:
    token = ebay_get_token()
    if not token or not term:
        return [], None

    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    params = {"q": term, "limit": max(1, min(limit, 50)), "offset": max(0, offset)}
    if filter_str: params["filter"] = filter_str
    if sort:       params["sort"]   = sort
    headers = {"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": EBAY_MARKETPLACE_ID}

    try:
        r = _http.get(url, headers=headers, params=params, timeout=15)
        r.raise_for_status()
        j = r.json() or {}
        items_raw = j.get("itemSummaries", []) or []
        total     = j.get("total")
        items: List[Dict] = []
        for it in items_raw:
            title = it.get("title") or "—"
            web   = _append_affiliate(it.get("itemWebUrl"))
            img   = (it.get("image") or {}).get("imageUrl")
            price = (it.get("price") or {}).get("value")
            cur   = (it.get("price") or {}).get("currency")
            price_str = f"{price} {cur}" if price and cur else "–"
            # stabile ID (für De-Duping)
            iid = it.get("itemId") or it.get("legacyItemId") or it.get("epid") or (web or "")[:200]
            items.append({"id": iid, "title": title, "price": price_str, "url": web, "img": img, "term": term, "src": "ebay"})
        return items, (int(total) if isinstance(total, int) else None)
    except Exception as e:
        print(f"[ebay_search_one] {e}")
        return [], None

# Demo-Backend
def _backend_search_demo(terms: List[str], page: int, per_page: int) -> Tuple[List[Dict], int]:
    total = max(30, len(terms) * 40)
    start = (page - 1) * per_page
    stop  = min(total, start + per_page)
    items: List[Dict] = []
    for i in range(start, stop):
        t = terms[i % max(1, len(terms))] if terms else f"Artikel {i+1}"
        items.append({
            "id": f"demo-{i+1}",
            "title": f"Demo-Ergebnis für „{t}“ #{i+1}",
            "price": "9,99 €",
            "url": f"https://www.ebay.de/sch/i.html?_nkw={t}",
            "img": "https://via.placeholder.com/64x48?text=%20",
            "term": t,
            "src": "demo",
        })
    return items, total

# Mini-Cache
_search_cache: dict = {}  # key -> (ts, (items, total_estimated))
def _cache_get(key):
    row = _search_cache.get(key)
    if not row:
        return None
    ts, payload = row
    if (time.time() - ts) > SEARCH_CACHE_TTL:
        _search_cache.pop(key, None)
        return None
    return payload

def _cache_set(key, payload):
    _search_cache[key] = (time.time(), payload)

def _backend_search_ebay(terms: List[str], filters: dict, page: int, per_page: int) -> Tuple[List[Dict], Optional[int]]:
    if not LIVE_SEARCH or not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
        return _backend_search_demo(terms, page, per_page)

    filter_str = _build_ebay_filters(filters.get("price_min",""), filters.get("price_max",""), filters.get("conditions") or [])
    sort       = _map_sort(filters.get("sort", "best"))

    n        = max(1, len(terms))
    per_term = max(1, per_page // n)
    offset   = (page - 1) * per_term

    items_all: List[Dict] = []
    totals: List[int] = []
    for t in terms:
        items, total = ebay_search_one(t, per_term, offset, filter_str, sort)
        items_all.extend(items)
        if isinstance(total, int):
            totals.append(total)

    if len(items_all) < per_page and terms:
        rest, base = per_page - len(items_all), offset + per_term
        extra, _ = ebay_search_one(terms[0], rest, base, filter_str, sort)
        items_all.extend(extra)

    total_estimated = sum(totals) if totals else None
    return items_all[:per_page], total_estimated

# -------------------------------------------------------------------
# Amazon PA-API (optional + fail-safe)
# -------------------------------------------------------------------
AMZ_ENABLED  = os.getenv("AMZ_ENABLED", "0") in {"1", "true", "True", "yes", "on"}
AMZ_ACCESS   = getenv_any("AMZ_ACCESS_KEY_ID", "AMZ_ACCESS_KEY")
AMZ_SECRET   = getenv_any("AMZ_SECRET_ACCESS_KEY", "AMZ_SECRET")
AMZ_TAG      = getenv_any("AMZ_PARTNER_TAG", "AMZ_ASSOC_TAG", "AMZ_TRACKING_ID")
AMZ_COUNTRY  = os.getenv("AMZ_COUNTRY", "DE")

AMZ_OK = False
amazon_client = None
try:
    if AMZ_ENABLED:
        from amazon_paapi import AmazonApi
        if AMZ_ACCESS and AMZ_SECRET and AMZ_TAG:
            amazon_client = AmazonApi(AMZ_ACCESS, AMZ_SECRET, AMZ_TAG, AMZ_COUNTRY)
            AMZ_OK = True
except Exception as _e:
    print("[amazon] init failed:", _e)
    AMZ_OK = False
    amazon_client = None

def amazon_search_one(term: str, limit: int, page: int,
                      price_min: str = "", price_max: str = "") -> Tuple[List[Dict], Optional[int]]:
    if not (AMZ_OK and term and amazon_client):
        return [], None
    try:
        item_count = max(1, min(limit, 10))
        page = max(1, min(page, 10))
        kwargs = {
            "keywords": term,
            "item_count": item_count,
            "item_page": page,
            "search_index": "All",
            "resources": [
                "ItemInfo.Title",
                "Images.Primary.Small",
                "Offers.Listings.Price",
                "DetailPageURL",
            ],
        }
        if price_min: kwargs["min_price"] = int(float(price_min) * 100)
        if price_max: kwargs["max_price"] = int(float(price_max) * 100)

        res = amazon_client.search_items(**kwargs)

        items: List[Dict] = []
        for p in getattr(res, "items", []) or []:
            try:
                title = p.item_info.title.display_value
            except Exception:
                title = "—"
            url = getattr(p, "detail_page_url", None)
            img = None
            try:
                img = p.images.primary.small.url
            except Exception:
                pass
            price_val, currency = None, None
            try:
                pr = p.offers.listings[0].price
                price_val = getattr(pr, "amount", None)
                currency  = getattr(pr, "currency", None)
            except Exception:
                pass
            price_str = f"{price_val} {currency}" if price_val and currency else "–"
            asin = getattr(p, "asin", url or title) or f"{term}-{page}-{len(items)+1}"
            items.append({"id": asin, "title": title, "price": price_str, "img": img, "url": url, "term": term, "src": "amazon"})
        return items, None
    except Exception as e:
        print("[amazon] search error:", e)
        return [], None

def _backend_search_amazon(terms: List[str], filters: dict, page: int, per_page: int):
    if not AMZ_OK:
        return [], None
    per_term = max(1, per_page // max(1, len(terms)))
    all_items: List[Dict] = []
    for t in terms:
        part, _ = amazon_search_one(
            t, per_term, page,
            filters.get("price_min") or "",
            filters.get("price_max") or "",
        )
        all_items.extend(part)
    return all_items[:per_page], None

def _backend_search_combined(terms: List[str], filters: dict, page: int, per_page: int):
    """eBay ist Leitquelle (liefert total), Amazon wird interleaved."""
    ebay_items, ebay_total = _backend_search_ebay(terms, filters, page, per_page)
    amz_items, _ = _backend_search_amazon(terms, filters, page, per_page)
    out: List[Dict] = []
    i = j = 0
    while len(out) < per_page and (i < len(ebay_items) or j < len(amz_items)):
        if i < len(ebay_items):
            ebay_items[i]["src"] = "ebay"
            out.append(ebay_items[i]); i += 1
        if len(out) >= per_page: break
        if j < len(amz_items):
            out.append(amz_items[j]); j += 1
    return out, ebay_total

# -------------------------------------------------------------------
# Suche + Cache Wrapper
# -------------------------------------------------------------------
def _search_with_cache(terms: List[str], filters: dict, page: int, per_page: int):
    use_amazon = AMZ_OK
    key = (
        tuple(terms),
        filters.get("price_min") or "",
        filters.get("price_max") or "",
        filters.get("sort") or "best",
        tuple(filters.get("conditions") or []),
        page, per_page,
        "amz" if use_amazon else "ebay",
    )
    cached = _cache_get(key)
    if cached:
        return cached
    if use_amazon:
        items, total = _backend_search_combined(terms, filters, page, per_page)
    else:
        items, total = _backend_search_ebay(terms, filters, page, per_page)
    _cache_set(key, (items, total))
    return items, total

# -------------------------------------------------------------------
# E-Mail: Versand + De-Duping
# -------------------------------------------------------------------
def _send_email(to_email: str, subject: str, html_body: str) -> bool:
    if not (SMTP_HOST and SMTP_FROM and to_email):
        print("[email] SMTP configuration incomplete")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = SMTP_FROM
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        if SMTP_USE_SSL:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=20) as s:
                if SMTP_USER: s.login(SMTP_USER, SMTP_PASS)
                s.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
                if SMTP_USE_TLS:
                    s.starttls()
                if SMTP_USER: s.login(SMTP_USER, SMTP_PASS)
                s.send_message(msg)
        print(f"[mail] sent via {SMTP_HOST}:{SMTP_PORT} tls={SMTP_USE_TLS} ssl={SMTP_USE_SSL}")
        return True
    except Exception as e:
        print("[email] send failed:", e)
        return False

def _make_search_hash(terms: List[str], filters: dict) -> str:
    payload = {
        "terms": [t.strip() for t in terms if t.strip()],
        "filters": {
            "price_min": filters.get("price_min") or "",
            "price_max": filters.get("price_max") or "",
            "sort": filters.get("sort") or "best",
            "conditions": sorted(filters.get("conditions") or []),
        },
    }
    s = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()

def _render_items_html(title: str, items: List[Dict]) -> str:
    rows = []
    for it in items[:NOTIFY_MAX_ITEMS_PER_MAIL]:
        img = it.get("img") or "https://via.placeholder.com/96x72?text=%20"
        url = it.get("url") or "#"
        price = it.get("price") or "–"
        src = it.get("src") or ""
        badge = f'<span style="background:#eef;padding:2px 6px;border-radius:4px;font-size:12px;margin-left:8px">{src}</span>' if src else ""
        rows.append(f"""
        <tr>
            <td style="padding:8px 12px"><img src="{img}" alt="" width="96" style="border:1px solid #ddd;border-radius:4px"></td>
            <td style="padding:8px 12px">
              <div style="font-weight:600;margin-bottom:4px"><a href="{url}" target="_blank" style="text-decoration:none;color:#0d6efd">{it.get('title') or '—'}</a>{badge}</div>
              <div style="color:#333">{price}</div>
            </td>
        </tr>
        """)
    more = ""
    if len(items) > NOTIFY_MAX_ITEMS_PER_MAIL:
        more = f"<p style='margin-top:8px'>+ {len(items) - NOTIFY_MAX_ITEMS_PER_MAIL} weitere Treffer …</p>"
    return f"""
    <div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
      <h2 style="margin:0 0 12px">{title}</h2>
      <table cellspacing="0" cellpadding="0" border="0">{''.join(rows)}</table>
      {more}
      <p style="margin-top:16px;color:#666;font-size:12px">Du erhältst diese Mail, weil du für diese Suche einen Alarm aktiviert hast.</p>
    </div>
    """

def _mark_and_filter_new(user_email: str, search_hash: str, src: str, items: List[Dict]) -> List[Dict]:
    """Nur Items zurückgeben, die für diese Suche/Person/Src noch nicht (oder nach Cooldown) gemailt wurden."""
    if not items:
        return []
    now = int(time.time())
    conn = get_db()
    cur = conn.cursor()
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
            last_sent = int(row["last_sent"])
            if last_sent == 0:
                new_items.append(it)
            else:
                if now - last_sent >= NOTIFY_COOLDOWN_MIN * 60:
                    new_items.append(it)
    conn.commit()
    conn.close()
    return new_items

def _group_by_src(items: List[Dict]) -> Dict[str, List[Dict]]:
    groups: Dict[str, List[Dict]] = {}
    for it in items:
        src = (it.get("src") or "ebay").lower()
        groups.setdefault(src, []).append(it)
    return groups

def _mark_sent(user_email: str, search_hash: str, src: str, items: List[Dict]) -> None:
    now = int(time.time())
    if not items:
        return
    conn = get_db()
    cur = conn.cursor()
    for it in items:
        iid = str(it.get("id") or it.get("url") or it.get("title"))[:255]
        cur.execute("""
            UPDATE alert_seen
               SET last_sent=?
             WHERE user_email=? AND search_hash=? AND src=? AND item_id=?
        """, (now, user_email, search_hash, src, iid))
    conn.commit()
    conn.close()

# -------------------------------------------------------------------
# DB (Users + Alerts/Seen)
# -------------------------------------------------------------------
def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_FILE), detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    return conn

def init_db() -> None:
    conn = get_db()
    cur = conn.cursor()
    # users
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            is_premium INTEGER NOT NULL DEFAULT 0
        )
    """)
    # items gesehen/versendet
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
    # gespeicherte Alerts (für Cron)
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
    conn.commit()
    conn.close()

init_db()

# -------------------------------------------------------------------
# Template-Fallback
# -------------------------------------------------------------------
def safe_render(template_name: str, **ctx):
    try:
        return render_template(template_name, **ctx)
    except Exception:
        title = ctx.get("title", "ebay-agent-cockpit")
        body  = ctx.get("body", "")
        try:
            home = url_for("public_home")
        except Exception:
            home = "/"
        return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet"></head>
<body class="container py-4">
<div class="alert alert-warning">Template <code>{template_name}</code> nicht gefunden – Fallback aktiv.</div>
<h1 class="h4">{title}</h1>
<div class="mb-3">{body}</div>
<p><a class="btn btn-primary" href="{home}">Zur Startseite</a></p>
</body></html>"""

# -------------------------------------------------------------------
# Context-Processor
# -------------------------------------------------------------------
def _build_query(existing: dict, **extra) -> str:
    merged = {**existing, **{k: v for k, v in extra.items() if v is not None}}
    pairs = []
    for k, v in merged.items():
        if v in (None, ""):
            continue
        if isinstance(v, (list, tuple)):
            for item in v:
                if item not in (None, ""):
                    pairs.append((k, str(item)))
        else:
            pairs.append((k, str(v)))
    return urlencode(pairs)

@app.context_processor
def inject_globals():
    return {
        "FREE_SEARCH_LIMIT": FREE_SEARCH_LIMIT,
        "PREMIUM_SEARCH_LIMIT": PREMIUM_SEARCH_LIMIT,
        "qs": _build_query,
        "plausible_domain": PLAUSIBLE_DOMAIN,
        "AMZ_TAG": os.getenv("AMZ_ASSOC_TAG", ""),
        "AMZ_COUNTRY": os.getenv("AMZ_COUNTRY", "DE"),
    }

# -------------------------------------------------------------------
# Session-Defaults + UTM
# -------------------------------------------------------------------
@app.before_request
def _ensure_session_defaults():
    session.setdefault("free_search_count", 0)
    session.setdefault("is_premium", False)
    session.setdefault("user_email", "guest")
    # UTM nur einmalig erfassen
    if not session.get("utm"):
        utm_keys = ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"]
        utm = {k: request.args.get(k) for k in utm_keys if request.args.get(k)}
        if utm:
            session["utm"] = utm

def _user_search_limit() -> int:
    return PREMIUM_SEARCH_LIMIT if session.get("is_premium") else FREE_SEARCH_LIMIT

# -------------------------------------------------------------------
# Auth (Demo)
# -------------------------------------------------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return safe_render("register.html", title="Registrieren")

    email = (request.form.get("email") or "").strip().lower()
    password = (request.form.get("password") or "").strip()
    if not email or not password:
        flash("Bitte E-Mail und Passwort angeben.", "warning")
        return redirect(url_for("register"))

    conn = get_db()
    try:
        conn.execute("INSERT INTO users (email, password, is_premium) VALUES (?, ?, 0)", (email, password))
        conn.commit()
    except sqlite3.IntegrityError:
        flash("Diese E-Mail ist bereits registriert.", "warning")
        return redirect(url_for("register"))
    finally:
        conn.close()

    flash("Registrierung erfolgreich. Bitte einloggen.", "success")
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return safe_render("login.html", title="Login")

    email = (request.form.get("email") or "").strip().lower()
    password = (request.form.get("password") or "").strip()

    conn = get_db()
    row = conn.execute("SELECT id, password, is_premium FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()

    if not row or row["password"] != password:
        flash("E-Mail oder Passwort ist falsch.", "warning")
        return redirect(url_for("login"))

    session["user_id"]    = int(row["id"])
    session["user_email"] = email
    session["is_premium"] = bool(row["is_premium"])
    flash("Login erfolgreich.", "success")
    return redirect(url_for("dashboard"))

@app.route("/logout")
def logout():
    session.clear()
    flash("Logout erfolgreich.", "info")
    return redirect(url_for("public_home"))

# -------------------------------------------------------------------
# Public / Dashboard / Free-Start
# -------------------------------------------------------------------
@app.route("/")
def root_redirect():
    return redirect(url_for("public_home"))

@app.route("/public")
def public_home():
    return safe_render("public_home.html", title="Start – ebay-agent-cockpit")

@app.route("/pricing")
def public_pricing():
    ev_free_limit_hit = bool(session.pop("ev_free_limit_hit", False))
    return safe_render("public_pricing.html", title="Preise – ebay-agent-cockpit",
                       ev_free_limit_hit=ev_free_limit_hit)

@app.route("/dashboard")
def dashboard():
    if not session.get("user_id"):
        flash("Bitte einloggen.", "info")
        return redirect(url_for("login"))
    return safe_render("dashboard.html", title="Dashboard")

@app.route("/start-free")
@app.route("/free")
def start_free():
    session["is_premium"]        = False
    session["free_search_count"] = 0
    session["user_email"]        = "guest"
    return redirect(url_for("search"))

# -------------------------------------------------------------------
# Suche – PRG + Pagination + Filter
# -------------------------------------------------------------------
@app.route("/search", methods=["GET", "POST"])
def search():
    # POST -> Redirect mit Querystring (PRG)
    if request.method == "POST":
        params = {
            "q1": (request.form.get("q1") or "").strip(),
            "q2": (request.form.get("q2") or "").strip(),
            "q3": (request.form.get("q3") or "").strip(),
            "price_min": (request.form.get("price_min") or "").strip(),
            "price_max": (request.form.get("price_max") or "").strip(),
            "sort": (request.form.get("sort") or "best").strip(),
            "per_page": (request.form.get("per_page") or "").strip(),
            "condition": request.form.getlist("condition"),
        }
        # Free-Limit zählen (nur beim Absenden)
        if not session.get("is_premium", False):
            count = int(session.get("free_search_count", 0))
            if count >= FREE_SEARCH_LIMIT:
                session["ev_free_limit_hit"] = True
                flash(f"Kostenloses Limit ({FREE_SEARCH_LIMIT}) erreicht – bitte Upgrade buchen.", "info")
                return redirect(url_for("public_pricing"))
            session["free_search_count"] = count + 1

        params["page"] = 1
        return redirect(url_for("search", **params))

    # GET -> tatsächliche Suche
    terms = [t for t in [
        (request.args.get("q1") or "").strip(),
        (request.args.get("q2") or "").strip(),
        (request.args.get("q3") or "").strip(),
    ] if t]

    if not terms:
        return safe_render("search.html", title="Suche")

    filters = {
        "price_min": request.args.get("price_min", "").strip(),
        "price_max": request.args.get("price_max", "").strip(),
        "sort": request.args.get("sort", "best").strip(),
        "conditions": request.args.getlist("condition"),
    }

    try:
        page = max(1, int(request.args.get("page", 1)))
    except Exception:
        page = 1
    try:
        per_page = min(100, max(5, int(request.args.get("per_page", PER_PAGE_DEFAULT))))
    except Exception:
        per_page = PER_PAGE_DEFAULT

    items, total_estimated = _search_with_cache(terms, filters, page, per_page)
    total_pages = math.ceil(total_estimated / per_page) if total_estimated is not None else None
    has_prev = page > 1
    has_next = (total_pages and page < total_pages) or (not total_pages and len(items) == per_page)

    base_qs = {
        "q1": request.args.get("q1", ""),
        "q2": request.args.get("q2", ""),
        "q3": request.args.get("q3", ""),
        "price_min": filters["price_min"],
        "price_max": filters["price_max"],
        "sort": filters["sort"],
        "condition": filters["conditions"],
        "per_page": per_page,
    }

    return safe_render(
        "search_results.html",
        title="Suchergebnisse",
        terms=terms,
        results=items,
        filters=filters,
        pagination={
            "page": page,
            "per_page": per_page,
            "total_estimated": total_estimated,
            "total_pages": total_pages,
            "has_prev": has_prev,
            "has_next": has_next,
        },
        base_qs=base_qs,
    )

@app.route("/", methods=["GET"])
def index():
    try:
        return "<br>".join(map(str, app.url_map.iter_rules()))
    except Exception:
        current_app.logger.exception("index failed")
        return "OK", 200


@app.route("/pilot/info")
def pilot_info():
    waitlist_url = request.url_root.rstrip("/") + "/pilot/waitlist"
    # Deinen internen Widget-Link NICHT direkt anzeigen (nur als Hinweis für das Team-Handout)
    return render_template("pilot_info.html", waitlist_url=waitlist_url)

# -------------------------------------------------------------------
# Alerts: Subscribe / Send-now / Cron (HTTP-Trigger-Variante siehe unten)
# -------------------------------------------------------------------
@app.post("/alerts/subscribe")
def alerts_subscribe():
    """Speichert die aktuelle Suche als Alert (für Cron)."""
    user_email = session.get("user_email") or ""
    if not user_email or user_email.lower() == "guest" or "@" not in user_email:
        flash("Bitte einloggen, um Alarme zu speichern.", "warning")
        return redirect(url_for("login"))

    terms = [t for t in [
        (request.form.get("q1") or "").strip(),
        (request.form.get("q2") or "").strip(),
        (request.form.get("q3") or "").strip(),
    ] if t]
    if not terms:
        flash("Keine Suchbegriffe übergeben.", "warning")
        return redirect(url_for("search"))

    filters = {
        "price_min": (request.form.get("price_min") or "").strip(),
        "price_max": (request.form.get("price_max") or "").strip(),
        "sort": (request.form.get("sort") or "best").strip(),
        "conditions": request.form.getlist("condition"),
    }
    per_page = 30
    try:
        per_page = min(100, max(5, int(request.form.get("per_page", "30"))))
    except Exception:
        pass

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO search_alerts (user_email, terms_json, filters_json, per_page, is_active, last_run_ts)
        VALUES (?, ?, ?, ?, 1, 0)
    """, (user_email, json.dumps(terms, ensure_ascii=False), json.dumps(filters, ensure_ascii=False), per_page))
    conn.commit()
    conn.close()

    flash("Alarm gespeichert. Du erhältst eine E-Mail, wenn neue Treffer gefunden werden.", "success")
    return redirect(url_for("search", **{**request.form}))

@app.post("/alerts/send-now")
def alerts_send_now():
    """Manuell: Suche aus Formular ausführen und E-Mail an (eingeloggt) senden – mit De-Duping."""
    user_email = session.get("user_email") or request.form.get("email") or ""
    if not user_email or user_email.lower() == "guest" or "@" not in user_email:
        flash("Gültige E-Mail erforderlich (einloggen oder E-Mail angeben).", "warning")
        return redirect(url_for("search"))

    terms = [t for t in [
        (request.form.get("q1") or "").strip(),
        (request.form.get("q2") or "").strip(),
        (request.form.get("q3") or "").strip(),
    ] if t]
    if not terms:
        flash("Keine Suchbegriffe übergeben.", "warning")
        return redirect(url_for("search"))

    filters = {
        "price_min": (request.form.get("price_min") or "").strip(),
        "price_max": (request.form.get("price_max") or "").strip(),
        "sort": (request.form.get("sort") or "best").strip(),
        "conditions": request.form.getlist("condition"),
    }

    per_page = 30
    try:
        per_page = min(100, max(5, int(request.form.get("per_page", "30"))))
    except Exception:
        pass

    items, _ = _search_with_cache(terms, filters, page=1, per_page=per_page)
    search_hash = _make_search_hash(terms, filters)

    # De-Duping gruppenweise pro src
    groups = _group_by_src(items)
    new_all: List[Dict] = []
    for src, group in groups.items():
        new_items = _mark_and_filter_new(user_email, search_hash, src, group)
        new_all.extend(new_items)

    if not new_all:
        flash("Keine neuen Treffer (alles schon gemailt oder noch im Cooldown).", "info")
        return redirect(url_for("search", **{**request.form}))

    subject = f"Neue Treffer für „{', '.join(terms)}“ – {len(new_all)} neu"
    html = _render_items_html(subject, new_all)
    ok = _send_email(user_email, subject, html)
    if ok:
        for src, group in groups.items():
            # markiere nur die, die wir tatsächlich geschickt haben
            sent_subset = [it for it in new_all if (it.get("src") or "ebay").lower() == src]
            _mark_sent(user_email, search_hash, src, sent_subset)
        flash(f"E-Mail versendet an {user_email} mit {len(new_all)} neuen Treffern.", "success")
    else:
        flash("E-Mail-Versand fehlgeschlagen (SMTP prüfen).", "danger")

    return redirect(url_for("search", **{**request.form}))

# ALT/Kompatibilität (deprecated): Query-basiertes Cron-Endpoint
@app.get("/cron/run-alerts")
def cron_run_alerts():
    """ALT (deprecated). Bitte künftig den HTTP-Trigger /internal/run-agent (POST + Bearer) verwenden."""
    token = request.args.get("token", "")
    if not CRON_TOKEN or token != CRON_TOKEN:
        return abort(403)

    now = int(time.time())
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, user_email, terms_json, filters_json, per_page FROM search_alerts WHERE is_active=1")
    alerts = cur.fetchall()
    conn.close()

    total_checked = 0
    total_sent = 0
    for a in alerts:
        total_checked += 1
        user_email = a["user_email"]
        try:
            terms = json.loads(a["terms_json"] or "[]")
            filters = json.loads(a["filters_json"] or "{}")
            per_page = int(a["per_page"] or 30)
        except Exception:
            continue

        items, _ = _search_with_cache(terms, filters, page=1, per_page=per_page)
        search_hash = _make_search_hash(terms, filters)

        groups = _group_by_src(items)
        new_all: List[Dict] = []
        for src, group in groups.items():
            new_items = _mark_and_filter_new(user_email, search_hash, src, group)
            new_all.extend(new_items)

        if new_all and user_email and "@" in user_email:
            subject = f"Neue Treffer für „{', '.join(terms)}“ – {len(new_all)} neu"
            html = _render_items_html(subject, new_all)
            if _send_email(user_email, subject, html):
                for src, _group in groups.items():
                    sent_subset = [it for it in new_all if (it.get("src") or "ebay").lower() == src]
                    _mark_sent(user_email, search_hash, src, sent_subset)
                total_sent += 1

        # last_run_ts aktualisieren
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE search_alerts SET last_run_ts=? WHERE id=?", (now, int(a["id"])))
        conn.commit()
        conn.close()

    return jsonify({"ok": True, "alerts_checked": total_checked, "alerts_emailed": total_sent})

@app.get("/pilot/info")
def pilot_info_page():
    base = request.url_root.rstrip("/")
    waitlist_url = base + "/pilot/waitlist"

    # Praxis-ID dynamisch aus der URL, fallback für Demo
    practice = request.args.get("practice", "DEMO-PRAXIS")

    # Interner Key aus ENV
    token = os.getenv("PRACTICE_DEMO_SECRET", "")

    # Widget-Link nur zeigen, wenn der aufrufende Link den korrekten key mitliefert
    show_widget = bool(token) and (request.args.get("key") == token)
    widget_url = None
    if show_widget:
        widget_url = f"{base}/pilot/widget?practice={practice}&key={token}"

    return render_template(
        "pilot_info.html",
        waitlist_url=waitlist_url,
        widget_url=widget_url,     # None ⇒ Button wird versteckt
        practice=practice,
        year=datetime.now().year,
    )

# -------------------------------------------------------------------
# Stripe (optional – fällt zurück, wenn nicht konfiguriert)
# -------------------------------------------------------------------
STRIPE_SECRET_KEY     = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PRICE_PRO      = os.getenv("STRIPE_PRICE_PRO", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

STRIPE_OK = False
try:
    import stripe as _stripe
    if STRIPE_SECRET_KEY:
        _stripe.api_key = STRIPE_SECRET_KEY
    STRIPE_OK = True
    stripe = _stripe
except Exception:
    STRIPE_OK = False
    stripe = None

@app.post("/webhook")
def stripe_webhook():
    wh_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    if not STRIPE_OK or not wh_secret:
        return "webhook not configured", 400

    payload = request.data
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, wh_secret)  # type: ignore
    except ValueError:
        return "invalid payload", 400
    except stripe.error.SignatureVerificationError:  # type: ignore
        return "invalid signature", 400

    etype = event.get("type")
    data  = event.get("data", {}).get("object", {})

    if etype in ("checkout.session.completed", "customer.subscription.created"):
        user_id = data.get("client_reference_id")
        email   = (
            (data.get("customer_details") or {}).get("email")
            or data.get("customer_email")
            or (data.get("metadata") or {}).get("email")
        )
        conn = get_db()
        cur  = conn.cursor()
        if user_id:
            cur.execute("UPDATE users SET is_premium=1 WHERE id=?", (user_id,))
        elif email:
            cur.execute("UPDATE users SET is_premium=1 WHERE lower(email)=lower(?)", (email,))
        conn.commit()
        conn.close()

    return jsonify({"received": True})

@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    if not STRIPE_OK or not STRIPE_SECRET_KEY or not STRIPE_PRICE_PRO:
        flash("Stripe ist nicht konfiguriert.", "warning")
        return redirect(url_for("public_pricing"))

    try:
        success_url = url_for("checkout_success", _external=True)
        cancel_url  = url_for("checkout_cancel",  _external=True)

        client_ref = str(session.get("user_id") or "")
        user_email = (session.get("user_email") or "").strip()
        if user_email.lower() == "guest" or "@" not in user_email:
            user_email = None

        session_stripe = stripe.checkout.Session.create(  # type: ignore
            mode="subscription",
            line_items=[{"price": STRIPE_PRICE_PRO, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            allow_promotion_codes=True,
            client_reference_id=client_ref if client_ref else None,
            customer_email=user_email if user_email else None,
            metadata={"email": user_email} if user_email else None,
        )
        return redirect(session_stripe.url, code=303)

    except Exception as e:
        flash(f"Stripe-Fehler: {e}", "danger")
        return redirect(url_for("public_pricing"))

@app.route("/billing/portal")
def billing_portal():
    flash("Abo-Verwaltung ist demnächst verfügbar.", "info")
    return redirect(url_for("public_pricing"))

@app.route("/checkout/success")
def checkout_success():
    session["is_premium"] = True
    flash("Dein Premium-Zugang ist jetzt freigeschaltet.", "success")
    return safe_render("success.html", title="Erfolg")

@app.route("/checkout/cancel")
def checkout_cancel():
    flash("Vorgang abgebrochen.", "info")
    return redirect(url_for("public_pricing"))

# -------------------------------------------------------------------
# Debug / Health
# -------------------------------------------------------------------
@app.route("/_debug/ebay")
def debug_ebay():
    return jsonify({
        "configured": bool(EBAY_CLIENT_ID and EBAY_CLIENT_SECRET),
        "marketplace": EBAY_MARKETPLACE_ID,
        "currency": EBAY_CURRENCY,
        "token_cached": bool(_EBAY_TOKEN["access_token"]),
        "token_valid_for_s": max(0, int(float(_EBAY_TOKEN.get("expires_at", 0)) - time.time())),
        "live_search": LIVE_SEARCH,
    })

@app.route("/_debug/amazon")
def debug_amazon():
    return jsonify({
        "amz_enabled": AMZ_ENABLED,
        "amz_ok": AMZ_OK,
        "country": AMZ_COUNTRY,
        "has_keys": bool(AMZ_ACCESS and AMZ_SECRET and AMZ_TAG),
    })

@app.route("/debug")
def debug_env():
    user_email = session.get("user_email") or ""
    if not user_email and session.get("user_id"):
        conn = get_db()
        row = conn.execute("SELECT email FROM users WHERE id=?", (session["user_id"],)).fetchone()
        conn.close()
        if row and row["email"]:
            user_email = row["email"]

    data = {
        "env": {
            "DB_PATH": DB_URL,
            "FREE_SEARCH_LIMIT": FREE_SEARCH_LIMIT,
            "PREMIUM_SEARCH_LIMIT": PREMIUM_SEARCH_LIMIT,
            "LIVE_SEARCH": "1" if LIVE_SEARCH else "0",
            "EBAY_CLIENT_ID_set": bool(EBAY_CLIENT_ID),
            "EBAY_CLIENT_SECRET_set": bool(EBAY_CLIENT_SECRET),
            "EBAY_SCOPES": EBAY_SCOPES,
            "EBAY_GLOBAL_ID": EBAY_GLOBAL_ID,
            "STRIPE_PRICE_PRO_set": bool(STRIPE_PRICE_PRO),
            "STRIPE_SECRET_KEY_set": bool(STRIPE_SECRET_KEY),
            "STRIPE_WEBHOOK_SECRET_set": bool(STRIPE_WEBHOOK_SECRET),
            "AMZ_ENABLED": AMZ_ENABLED,
            "AMZ_ACCESS_KEY_set": bool(AMZ_ACCESS),
            "AMZ_SECRET_set": bool(AMZ_SECRET),
            "AMZ_TAG_set": bool(AMZ_TAG),
            "AMZ_COUNTRY": AMZ_COUNTRY,
            "PLAUSIBLE_DOMAIN": PLAUSIBLE_DOMAIN,
        },
        "session": {
            "free_search_count": int(session.get("free_search_count", 0)),
            "is_premium": bool(session.get("is_premium", False)),
            "user_email": user_email,
            "utm": session.get("utm") or {},
        },
    }
    return jsonify(data)

@app.route("/healthz")
def healthz():
    return "ok", 200

# (Optional) Amazon Direkt-Suche
@app.route("/amazon/search")
def amazon_search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return safe_render("search.html", title="Amazon-Suche", body="Bitte Suchbegriff angeben.")
    if not AMZ_OK:
        flash("Amazon ist nicht konfiguriert.", "info")
        return redirect(url_for("public_home"))

    page = 1
    try:
        page = max(1, int(request.args.get("page", 1)))
    except Exception:
        pass

    items, _ = amazon_search_one(q, limit=20, page=page)

    return safe_render(
        "search_results.html",
        title=f"Amazon-Ergebnisse für „{q}“",
        terms=[q],
        results=items,
        filters={"price_min":"", "price_max":"", "sort":"best", "conditions":[]},
        pagination={"page":1, "per_page":len(items), "total_estimated":len(items),
                    "total_pages":1, "has_prev":False, "has_next":False},
        base_qs={"q1": q, "per_page": len(items)}
    )

# -------------------------------------------------------------------
# PRIVATER Cron-Trigger (neu, empfohlen): /internal/run-agent  (POST + Bearer)
# -------------------------------------------------------------------
# Lock laden (mit sicherem Fallback, falls lock.py fehlt)
try:
    from lock import agent_lock  # Datei-Lock über Prozesse/Worker
except Exception:
    from contextlib import contextmanager
    from threading import Lock as _TLock
    _fallback_lock = _TLock()
    @contextmanager
    def agent_lock(timeout: int = 110):
        ok = _fallback_lock.acquire(timeout=timeout if timeout else None)
        try:
            yield
        finally:
            if ok:
                _fallback_lock.release()

internal_bp = Blueprint("internal", __name__)

def require_agent_token():
    token = request.headers.get("Authorization", "")
    if token.startswith("Bearer "):
        token = token[7:]
    env_tok = os.getenv("AGENT_TRIGGER_TOKEN", "")
    if token != os.getenv("AGENT_TRIGGER_TOKEN", ""):
        abort(401)

@internal_bp.route("/mail-test", methods=["GET"])
def internal_mail_test():
    # oben in der Datei muss stehen: from mailer import send_mail

    to = request.args.get("to", "").strip()
    if not to:
        return jsonify({"ok": False, "error": "missing 'to'"}), 400

    try:
        send_mail(
            to=to,
            subject="Test vom ebay-agent-cockpit",
            text="? Mail-Setup ok. (Staging)",
        )
        return jsonify({"ok": True, "to": to}), 200
    except Exception as e:
        current_app.logger.exception("mail test failed")
        return jsonify({"ok": False, "error": str(e)}), 500
@internal_bp.route("/run-agent", methods=["POST"])
def internal_run_agent():
    # Token prüfen (kleiner Helper – siehe unten)
    require_agent_token()

    with agent_lock():  # <- das hast du schon
        try:
            from agent import run_agent_once
        except Exception as e:
            current_app.logger.exception("agent import failed")
            return jsonify({"status": "error", "error": "agent_import_failed"}), 500

        try:
            run_agent_once()
        except Exception as e:
            current_app.logger.exception("agent run failed")
            return jsonify({"status": "error", "error": "agent_run_failed"}), 500

    return jsonify({"ok": True}), 200

# ========= INTERN: Helfer für Alerts / DB-Inspektion =========

def _detect_alerts_table(conn):
    """
    Sucht eine Tabelle mit einer 'email'-Spalte und einer Aktiv-Spalte ('active' oder 'is_active').
    Gibt (table_name, email_col, active_col, id_col) zurück oder (None, ...), falls nicht gefunden.
    """
    cur = conn.cursor()
    # alle Tabellen
    rows = cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    tables = [r[0] for r in rows]
    for t in tables:
        cols = cur.execute(f"PRAGMA table_info({t})").fetchall()  # cid, name, type, notnull, dflt, pk
        names = {c[1].lower(): c for c in cols}
        # Pflicht: email + irgendeine Aktiv-Spalte
        if "email" in names and ("active" in names or "is_active" in names):
            email_col = "email"
            active_col = "active" if "active" in names else "is_active"
            # ID-Spalte heuristisch
            id_col = "id" if "id" in names else ( "alert_id" if "alert_id" in names else list(names.keys())[0] )
            return t, email_col, active_col, id_col
    return None, None, None, None


@internal_bp.route("/db-info", methods=["GET"])
def internal_db_info():
    """Zeigt Tabellen + vermutete Alerts-Tabelle/Spalten – zum Nachsehen im Browser."""
    require_agent_token()  # denselben Token-Check nutzen wie bei deinen anderen /internal-Routen
    conn = get_db()
    cur = conn.cursor()
    tables = cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    found = _detect_alerts_table(conn)
    data = {
        "tables": [{"name": n, "create_sql": s} for (n, s) in tables],
        "alerts_detection": {
            "table": found[0],
            "email_col": found[1],
            "active_col": found[2],
            "id_col": found[3],
        },
    }
    from flask import jsonify
    return jsonify(data), 200


@internal_bp.route("/alerts/disable-all", methods=["POST"])
def internal_alerts_disable_all():
    """Setzt alle Alarme für eine E-Mail auf inaktiv."""
    require_agent_token()
    email = request.form.get("email", "").strip().lower()
    if not email:
        return ("missing email", 400)

    conn = get_db()
    table, email_col, active_col, _ = _detect_alerts_table(conn)
    if not table:
        return ("could not detect alerts table", 500)

    cur = conn.cursor()
    cur.execute(f"UPDATE {table} SET {active_col}=0 WHERE lower({email_col})=?", (email,))
    conn.commit()
    return {"ok": True, "email": email, "updated": cur.rowcount}, 200


@internal_bp.route("/my-alerts", methods=["GET"])
def internal_my_alerts():
    """
    Mini-Übersicht + Toggle. Aufruf: /internal/my-alerts?email=dein@postfach.de
    """
    require_agent_token()
    email = request.args.get("email", "").strip().lower()
    if not email:
        return ("missing ?email=...", 400)

    conn = get_db()
    table, email_col, active_col, id_col = _detect_alerts_table(conn)
    if not table:
        return ("could not detect alerts table", 500)

    cur = conn.cursor()
    rows = cur.execute(
        f"SELECT {id_col} AS id, {email_col} AS email, {active_col} AS active, * FROM {table} WHERE lower({email_col})=? ORDER BY {id_col} DESC",
        (email,),
    ).fetchall()

    # ganz einfacher HTML-Renderer, kein extra Template nötig
    html = ["<h1>Meine Alarme</h1>"]
    html.append(f"<p>Email: <b>{email}</b></p>")
    if not rows:
        html.append("<p>Keine Alarme gefunden.</p>")
    else:
        html.append("<table border=1 cellpadding=6><tr><th>ID</th><th>Aktiv</th><th>Aktion</th></tr>")
        for r in rows:
            rid = r["id"] if isinstance(r, dict) else r[0]
            is_active = r["active"] if isinstance(r, dict) else r[2]
            label = "deaktivieren" if is_active else "aktivieren"
            new_val = 0 if is_active else 1
            html.append(
                f"<tr><td>{rid}</td>"
                f"<td>{'✅ aktiv' if is_active else '⛔ inaktiv'}</td>"
                f"<td>"
                f"<form method='post' action='/internal/alerts/toggle' style='margin:0;'>"
                f"<input type='hidden' name='id' value='{rid}'/>"
                f"<input type='hidden' name='active' value='{new_val}'/>"
                f"<input type='hidden' name='email' value='{email}'/>"
                f"<button type='submit'>{label}</button>"
                f"</form>"
                f"</td></tr>"
            )
        html.append("</table>")
        html.append("<p style='margin-top:12px'>Tipp: <form method='post' action='/internal/alerts/disable-all' style='display:inline;'>"
                    f"<input type='hidden' name='email' value='{email}'/>"
                    "<button>Alle für diese E-Mail deaktivieren</button></form></p>")
    return "\n".join(html), 200


@internal_bp.route("/alerts/toggle", methods=["POST"])
def internal_alerts_toggle():
    """Aktiv-Flag eines Alerts umschalten (von der Tabelle oben aus)."""
    require_agent_token()
    rid = request.form.get("id", "").strip()
    target = request.form.get("active", "").strip()
    email = request.form.get("email", "").strip().lower()

    if not rid or target not in ("0", "1"):
        return ("bad request", 400)

    conn = get_db()
    table, email_col, active_col, id_col = _detect_alerts_table(conn)
    if not table:
        return ("could not detect alerts table", 500)

    cur = conn.cursor()
    cur.execute(f"UPDATE {table} SET {active_col}=? WHERE {id_col}=?", (int(target), rid))
    conn.commit()
    # wieder zurück zur Liste für diese E-Mail
    return redirect(f"/internal/my-alerts?email={email}")


@app.route("/_routes")
def _routes():
    return {"routes": [str(r) for r in app.url_map.iter_rules()]}

def require_agent_token():
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        auth = auth[7:]
    if auth != os.getenv("AGENT_TRIGGER_TOKEN", ""):
        abort(401)


# Registrierung des internen Blueprints (jetzt, wo er existiert)

app.register_blueprint(internal_bp, url_prefix="/internal")

# -------------------------------------------------------------------
# Run (nur lokal)
# -------------------------------------------------------------------

# ======= DEMO BLOCK: Storno-Radar (Begin) =======
import os
from datetime import datetime
from flask import request, render_template_string, jsonify, abort
# nutzt deine existierende send_mail-Funktion:
from mailer import send_mail

# Schalter (kannst du per ENV steuern)
DEMO_ENABLED = os.getenv("DEMO_ENABLED", "1") == "1"
PRACTICE_DEMO_SECRET = os.getenv("PRACTICE_DEMO_SECRET", "")  # optionaler Key

# In-Memory Speicher (nur für Demo)
DEMO_WAITLIST = []   # [{email, fach, plz, fenster, created}]
DEMO_SLOTS    = []   # [{fach, until, link, created}]

def _demo_guard():
    if not DEMO_ENABLED:
        abort(404)

# --- Warteliste (Patient) ---
@app.get("/pilot/waitlist")
def pilot_waitlist_form():
    _demo_guard()
    html = """
    <div style="font-family:sans-serif;max-width:520px;margin:24px auto">
      <h2>Warteliste – Schnelltest</h2>
      <form method="post" action="/pilot/waitlist">
        <label>E-Mail:</label><br><input name="email" required style="width:100%"><br>
        <label>Fachgebiet:</label><br>
          <select name="fach" style="width:100%">
            <option>Orthopädie</option><option>Dermatologie</option><option>HNO</option>
          </select><br>
        <label>PLZ (optional):</label><br><input name="plz" style="width:100%"><br>
        <label>Zeitfenster (z. B. Mo–Fr 8–12):</label><br><input name="fenster" style="width:100%"><br><br>
        <button type="submit">Auf Warteliste</button>
      </form>
      <p style="margin-top:1rem"><a href="/pilot/widget">→ Praxis-Widget öffnen</a></p>
    </div>
    """
    return render_template_string(html)

@app.post("/pilot/waitlist")
def pilot_waitlist_save():
    _demo_guard()
    DEMO_WAITLIST.append({
        "email": request.form.get("email","").strip(),
        "fach": request.form.get("fach","").strip(),
        "plz": request.form.get("plz","").strip(),
        "fenster": request.form.get("fenster","").strip(),
        "created": datetime.utcnow().isoformat()
    })
    return "<p>✅ Eingetragen! <a href='/pilot/waitlist'>Zurück</a> • <a href='/pilot/widget'>Praxis-Widget</a></p>"

# --- Praxis-Widget (Slot freigeben) ---
@app.get("/pilot/widget")
def pilot_widget_form():
    _demo_guard()
    if PRACTICE_DEMO_SECRET and request.args.get("key") != PRACTICE_DEMO_SECRET:
        return "401 demo key missing/invalid", 401
    html = """
    <div style="font-family:sans-serif;max-width:520px;margin:24px auto">
      <h2>Praxis-Widget – Slot freigeben</h2>
      <form method="post" action="/pilot/widget{qs}">
        <label>Fachgebiet:</label><br>
          <select name="fach" style="width:100%">
            <option>Orthopädie</option><option>Dermatologie</option><option>HNO</option>
          </select><br>
        <label>Slot frei bis (HH:MM):</label><br><input name="until" placeholder="15:30" required style="width:100%"><br>
        <label>Buchungslink (116117 / Praxis-Web / Tel-Hinweis):</label><br>
          <input name="link" placeholder="https://www.116117.de/..." style="width:100%"><br><br>
        <button type="submit">Slot freigeben & Benachrichtigen</button>
      </form>
      <p style="margin-top:1rem"><a href="/pilot/waitlist">→ Warteliste</a></p>
    </div>
    """.format(qs=("?key="+PRACTICE_DEMO_SECRET) if PRACTICE_DEMO_SECRET else "")
    return render_template_string(html)

@app.post("/pilot/widget")
def pilot_widget_free():
    _demo_guard()
    if PRACTICE_DEMO_SECRET and request.args.get("key") != PRACTICE_DEMO_SECRET:
        return "401 demo key missing/invalid", 401

    fach  = request.form.get("fach", "").strip()
    until = request.form.get("until", "").strip()
    link  = request.form.get("link", "").strip() or "(Telefon: 01234/56789)"

    DEMO_SLOTS.append({
        "fach": fach,
        "until": until,
        "link": link,
        "created": datetime.utcnow().isoformat()
    })

    # einfache Filterlogik: nur Fachgebiet matchen
    matches = [w for w in DEMO_WAITLIST if w["fach"] == fach]
    sent = 0
    for w in matches[:20]:  # Sicherheitslimit
        try:
            addr = w["email"]
            send_mail_pilot(
                to=addr,
                subject=f"Freier Termin ({fach}) bis {until}",
                text=(
                    f"Hallo,\n\n"
                    f"in {fach} ist kurzfristig ein Termin frei – gültig bis {until}.\n\n"
                    f"Buchen/Info: {link}\n"
                ),
                # optional: separater Message-Stream für Pilot
                stream=os.getenv("PILOT_MESSAGE_STREAM"),
                # optional: Reply-To
                reply_to=os.getenv("PILOT_SENDER_EMAIL"),
            )
            sent += 1
        except Exception:
            current_app.logger.exception("pilot mail failed")

    qs = f"?key={PRACTICE_DEMO_SECRET}" if PRACTICE_DEMO_SECRET else ""
    return (
        f"<p>✅ Slot freigegeben ({fach}) bis {until}. "
        f"Benachrichtigungen verschickt: {sent}. "
        f"<a href='/pilot/widget{qs}'>Zurück</a></p>"
    )          

# ======= DEMO BLOCK: Storno-Radar (End) =======

if __name__ == "__main__":
    port  = int(os.getenv("PORT", "5000"))
    debug = as_bool(os.getenv("FLASK_DEBUG", "1"))
    app.run(host="0.0.0.0", port=port, debug=debug)

