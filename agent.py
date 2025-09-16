# agent.py — Optimized Cron/HTTP-Worker für E-Mail-Benachrichtigungen
# - Rate Limiting: verhindert zu häufige Ausführung
# - Batch Processing: mehrere Items pro Email
# - Performance optimiert
# - Lock-System gegen parallele Ausführung

from __future__ import annotations
import os, time, json, sqlite3, smtplib, ssl, hashlib
from typing import List, Dict, Optional, Iterable, Tuple
from email.message import EmailMessage
from pathlib import Path
import threading

import requests

# -----------------------
# Rate Limiting & Lock
# -----------------------
MIN_INTERVAL_SECONDS = int(os.getenv("AGENT_MIN_INTERVAL", "300"))  # 5 Minuten default
MAX_RUNTIME_SECONDS = int(os.getenv("AGENT_MAX_RUNTIME", "600"))    # 10 Minuten timeout
LOCK_FILE = Path("/tmp/agent_lock")
LAST_RUN_FILE = Path("/tmp/last_agent_run")

class AgentLock:
    def __init__(self, timeout: int = MAX_RUNTIME_SECONDS):
        self.timeout = timeout
        self.acquired = False
    
    def __enter__(self):
        # Check if already running
        if LOCK_FILE.exists():
            try:
                lock_time = float(LOCK_FILE.read_text().strip())
                if time.time() - lock_time < self.timeout:
                    print(f"[agent] already running (locked {int(time.time() - lock_time)}s ago)")
                    return None
                else:
                    print(f"[agent] removing stale lock (>{self.timeout}s old)")
                    LOCK_FILE.unlink(missing_ok=True)
            except:
                LOCK_FILE.unlink(missing_ok=True)
        
        # Acquire lock
        LOCK_FILE.write_text(str(time.time()))
        self.acquired = True
        return self
    
    def __exit__(self, *args):
        if self.acquired:
            LOCK_FILE.unlink(missing_ok=True)
            self.acquired = False

def check_rate_limit() -> bool:
    """Returns True if enough time has passed since last run"""
    if not LAST_RUN_FILE.exists():
        return True
    
    try:
        last_run = float(LAST_RUN_FILE.read_text().strip())
        elapsed = time.time() - last_run
        if elapsed < MIN_INTERVAL_SECONDS:
            print(f"[agent] rate limited - only {int(elapsed)}s since last run (min {MIN_INTERVAL_SECONDS}s)")
            return False
        return True
    except:
        return True

def update_last_run():
    """Update last run timestamp"""
    LAST_RUN_FILE.write_text(str(time.time()))

# -----------------------
# Helpers & ENV (unchanged)
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
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "", 1)
    return url

DB_URL   = os.getenv("DB_PATH", "sqlite:///instance/db.sqlite3")
DB_FILE  = sqlite_file_from_url(DB_URL)

# eBay API (unchanged)
EBAY_CLIENT_ID     = getenv_any("EBAY_CLIENT_ID", "EBAY_APP_ID")
EBAY_CLIENT_SECRET = getenv_any("EBAY_CLIENT_SECRET", "EBAY_CERT_ID")
EBAY_SCOPES        = os.getenv("EBAY_SCOPES", "https://api.ebay.com/oauth/api_scope")
EBAY_GLOBAL_ID     = os.getenv("EBAY_GLOBAL_ID", "EBAY-DE")

MARKETPLACE_BY_GLOBAL = {
    "EBAY-DE": ("EBAY_DE","EUR"),
    "EBAY-AT": ("EBAY_AT","EUR"),
    "EBAY-CH": ("EBAY_CH","CHF"),
    "EBAY-GB": ("EBAY_GB","GBP"),
    "EBAY-US": ("EBAY_US","USD"),
}
EBAY_MARKETPLACE_ID, EBAY_CURRENCY = MARKETPLACE_BY_GLOBAL.get(EBAY_GLOBAL_ID, ("EBAY_DE","EUR"))

# SMTP Settings with mailer.py fallback
def get_smtp_settings() -> Dict[str, object]:
    # Try to use mailer.py if available
    try:
        from mailer import send_mail as mailer_send_mail
        return {"use_mailer": True, "send_func": mailer_send_mail}
    except ImportError:
        pass
    
    # Fallback to direct SMTP
    host = os.getenv("SMTP_HOST") or os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT") or os.getenv("EMAIL_SMTP_PORT") or "587")
    user = os.getenv("SMTP_USER") or os.getenv("EMAIL_USER", "")
    pwd  = os.getenv("SMTP_PASS") or os.getenv("EMAIL_PASSWORD", "")
    from_addr = os.getenv("SMTP_FROM") or os.getenv("EMAIL_FROM") or (user or "alerts@localhost")
    use_tls = as_bool(os.getenv("SMTP_USE_TLS", "1"))
    use_ssl = as_bool(os.getenv("SMTP_USE_SSL", "0"))
    return {
        "use_mailer": False,
        "host": host, "port": port, "user": user, "password": pwd,
        "from": from_addr, "use_tls": use_tls, "use_ssl": use_ssl,
    }

# Performance settings
NOTIFY_MAX_ITEMS_PER_MAIL = int(os.getenv("ALERT_MAX_ITEMS", "20"))  # Increased from 12
BATCH_SIZE = int(os.getenv("ALERT_BATCH_SIZE", "10"))  # Process alerts in batches
DEBUG_LOG = as_bool(os.getenv("ALERT_DEBUG", "0"))
MAX_ALERTS_PER_RUN = int(os.getenv("MAX_ALERTS_PER_RUN", "50"))  # Limit per run

# -----------------------
# DB (unchanged but with connection pooling)
# -----------------------

def get_db() -> sqlite3.Connection:
    dirname = os.path.dirname(DB_FILE)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    conn = sqlite3.connect(DB_FILE, timeout=30.0)  # Add timeout
    conn.row_factory = sqlite3.Row
    return conn

def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return bool(cur.fetchone())

def init_db_if_needed() -> None:
    conn = get_db()
    cur  = conn.cursor()
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
# Enhanced SMTP with mailer.py integration
# -----------------------

def send_mail_optimized(
    smtp: Dict[str, object],
    to_addrs: Iterable[str],
    subject: str,
    body_html: str,
) -> bool:
    """Enhanced mail sending with mailer.py integration"""
    
    # Use mailer.py if available
    if smtp.get("use_mailer"):
        try:
            send_func = smtp["send_func"]
            for addr in to_addrs:
                if addr and "@" in addr:
                    send_func(to=addr, subject=subject, html=body_html)
            return True
        except Exception as e:
            print(f"[mail] mailer.py failed: {e}")
            return False
    
    # Fallback to direct SMTP
    host = smtp.get("host"); port = int(smtp.get("port") or 0)
    user = smtp.get("user"); pwd  = smtp.get("password")
    from_addr = smtp.get("from")
    use_tls = bool(smtp.get("use_tls")); use_ssl = bool(smtp.get("use_ssl"))

    if not host or not port or not from_addr or not to_addrs:
        print("[mail] SMTP config incomplete")
        return False
    if user and not pwd:
        print("[mail] SMTP password missing")
        return False

    msg = EmailMessage()
    msg["From"] = str(from_addr)
    msg["To"] = ", ".join([t for t in to_addrs if t])
    msg["Subject"] = subject
    msg.set_content("HTML Email")
    msg.add_alternative(body_html, subtype="html")

    try:
        if use_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=context, timeout=60) as s:
                if user: s.login(user, pwd)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=60) as s:
                if use_tls:
                    s.starttls(context=ssl.create_default_context())
                if user: s.login(user, pwd)
                s.send_message(msg)
        return True
    except Exception as e:
        print(f"[mail] SMTP failed: {e}")
        return False

# -----------------------
# De-Dup with cooldown support
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

def mark_and_filter_new(user_email: str, search_hash: str, src: str, items: List[Dict]) -> List[Dict]:
    """Enhanced de-duping with cooldown support"""
    if not items:
        return []
    
    now = int(time.time())
    cooldown_seconds = int(os.getenv("NOTIFY_COOLDOWN_SECONDS", "7200"))  # 2 hours default
    
    conn = get_db()
    cur  = conn.cursor()
    new_items: List[Dict] = []
    
    for it in items:
        iid = str(it.get("id") or it.get("url") or it.get("title"))[:255]
        cur.execute("""
            SELECT last_sent FROM alert_seen
            WHERE user_email=? AND search_hash=? AND src=? AND item_id=?
        """, (user_email, search_hash, src, iid))
        row = cur.fetchone()
        
        if not row:
            # Completely new item
            new_items.append(it)
            cur.execute("""
                INSERT INTO alert_seen (user_email, search_hash, src, item_id, first_seen, last_sent)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_email, search_hash, src, iid, now, 0))
        else:
            # Check cooldown
            last_sent = int(row["last_sent"] or 0)
            if last_sent == 0 or (now - last_sent) >= cooldown_seconds:
                new_items.append(it)
    
    conn.commit()
    conn.close()
    return new_items

def mark_sent(user_email: str, search_hash: str, src: str, items: List[Dict]) -> None:
    if not items:
        return
    now = int(time.time())
    conn = get_db()
    cur  = conn.cursor()
    for it in items:
        iid = str(it.get("id") or it.get("url") or it.get("title"))[:255]
        cur.execute("""
            UPDATE alert_seen SET last_sent=? 
            WHERE user_email=? AND search_hash=? AND src=? AND item_id=?
        """, (now, user_email, search_hash, src, iid))
    conn.commit()
    conn.close()

# -----------------------
# eBay API (optimized with connection reuse)
# -----------------------

_http = requests.Session()
_http.headers.update({'User-Agent': 'eBayAgent/1.0'})
_EBAY_TOKEN: Dict[str, object] = {"access_token": None, "expires_at": 0.0}

def ebay_get_token() -> Optional[str]:
    now = time.time()
    if _EBAY_TOKEN["access_token"] and now < float(_EBAY_TOKEN["expires_at"] or 0):
        return str(_EBAY_TOKEN["access_token"])
    
    if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
        if DEBUG_LOG:
            print("[ebay] Missing credentials")
        return None
    
    url  = "https://api.ebay.com/identity/v1/oauth2/token"
    auth = requests.auth.HTTPBasicAuth(EBAY_CLIENT_ID, EBAY_CLIENT_SECRET)
    data = {"grant_type": "client_credentials", "scope": EBAY_SCOPES}
    
    try:
        r = _http.post(url, auth=auth, data=data, timeout=20)
        r.raise_for_status()
        j = r.json() or {}
        _EBAY_TOKEN["access_token"] = j.get("access_token")
        _EBAY_TOKEN["expires_at"]  = time.time() + int(j.get("expires_in", 7200)) - 60
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
    conds = [c.strip().upper() for c in (conditions or []) if c.strip()]
    if conds:
        parts.append("conditions:{" + ",".join(conds) + "}")
    return ",".join(parts) if parts else None

def _map_sort(s: str) -> Optional[str]:
    s = (s or "").strip()
    if not s or s == "best":
        return None
    if s == "price_asc":  return "price"
    if s == "price_desc": return "-price"
    if s == "newly":      return "newlyListed"
    return None

def ebay_search(term: str, limit: int, offset: int,
                price_min: str, price_max: str,
                conditions: List[str], sort_ui: str) -> List[Dict]:
    """Optimized eBay search with better error handling"""
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
        "X-EBAY-C-MARKETPLACE-ID": EBAY_MARKETPLACE_ID
    }
    
    try:
        r = _http.get(url, headers=headers, params=params, timeout=20)
        r.raise_for_status()
        j = r.json() or {}
        
        items: List[Dict] = []
        for it in j.get("itemSummaries", []) or []:
            # Enhanced item data extraction
            price_obj = it.get("price") or {}
            items.append({
                "id": it.get("itemId") or it.get("legacyItemId") or it.get("itemWebUrl"),
                "title": it.get("title") or "—",
                "url": it.get("itemWebUrl"),
                "img": (it.get("image") or {}).get("imageUrl"),
                "price": price_obj.get("value"),
                "cur": price_obj.get("currency"),
                "condition": it.get("condition"),
                "seller": (it.get("seller") or {}).get("username"),
                "src": "ebay",
                "term": term,
            })
        
        if DEBUG_LOG:
            print(f"[ebay] found {len(items)} items for '{term}'")
        
        return items
    except Exception as e:
        print(f"[ebay_search] {term}: {e}")
        return []

# -----------------------
# Optimized Alert Loading
# -----------------------

def load_alerts(limit: int = MAX_ALERTS_PER_RUN) -> List[Dict]:
    """Load active alerts with priority ordering"""
    conn = get_db()
    
    # Prioritize alerts that haven't run recently
    rows = conn.execute("""
        SELECT id, user_email, terms_json, filters_json, per_page, last_run_ts
        FROM search_alerts 
        WHERE is_active=1 
        ORDER BY last_run_ts ASC, id ASC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    
    out: List[Dict] = []
    for r in rows:
        try:
            terms = json.loads(r["terms_json"] or "[]") or []
            filters = json.loads(r["filters_json"] or "{}") or {}
        except Exception:
            continue
        
        # Skip invalid alerts
        if not terms or not r["user_email"] or "@" not in r["user_email"]:
            continue
        
        filters_norm = {
            "price_min": (filters.get("price_min") or "").strip(),
            "price_max": (filters.get("price_max") or "").strip(),
            "sort": (filters.get("sort") or "best").strip(),
            "conditions": [c.strip().upper() for c in (filters.get("conditions") or []) if c and str(c).strip()],
        }
        
        out.append({
            "id": int(r["id"]),
            "user_email": r["user_email"],
            "terms": [t.strip() for t in terms if str(t).strip()],
            "filters": filters_norm,
            "per_page": min(50, max(10, int(r["per_page"] or 30))),  # Reasonable bounds
            "last_run_ts": int(r["last_run_ts"] or 0),
        })
    
    return out

# -----------------------
# Enhanced Email Rendering
# -----------------------

def render_email_html(title: str, items: List[Dict]) -> str:
    """Enhanced HTML email template"""
    rows = []
    for it in items[:NOTIFY_MAX_ITEMS_PER_MAIL]:
        price = f"{it.get('price')} {it.get('cur')}" if it.get("price") and it.get("cur") else "—"
        img = it.get("img") or "https://via.placeholder.com/96x72?text=No+Image"
        url = it.get("url") or "#"
        title_txt = (it.get("title") or "—")[:100]  # Limit title length
        condition = it.get("condition") or ""
        seller = it.get("seller") or ""
        
        # Enhanced row with more info
        seller_info = f"<br><small style='color:#888'>Verkäufer: {seller}</small>" if seller else ""
        condition_info = f"<br><small style='color:#666'>Zustand: {condition}</small>" if condition else ""
        
        rows.append(f"""
        <tr style='border-bottom:1px solid #eee'>
            <td style='padding:12px;width:110px'>
                <img src='{img}' width='96' height='72' 
                     style='border-radius:6px;object-fit:cover;border:1px solid #ddd'>
            </td>
            <td style='padding:12px'>
                <div style='margin-bottom:6px'>
                    <a href='{url}' target='_blank' 
                       style='text-decoration:none;color:#0066cc;font-weight:500;line-height:1.3'>
                        {title_txt}
                    </a>
                </div>
                <div style='color:#333;font-size:16px;font-weight:600;margin-bottom:4px'>{price}</div>
                {condition_info}
                {seller_info}
            </td>
        </tr>
        """)
    
    more_info = ""
    if len(items) > NOTIFY_MAX_ITEMS_PER_MAIL:
        more_count = len(items) - NOTIFY_MAX_ITEMS_PER_MAIL
        more_info = f"<p style='margin-top:16px;color:#666;font-style:italic'>+ {more_count} weitere Treffer nicht angezeigt</p>"
    
    return f"""
    <div style='font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif;max-width:600px;margin:0 auto'>
        <div style='background:#f8f9fa;padding:20px;border-radius:8px;margin-bottom:20px'>
            <h2 style='margin:0;color:#333;font-size:20px'>{title}</h2>
            <p style='margin:8px 0 0 0;color:#666;font-size:14px'>
                Gefunden: {len(items)} neue Artikel
            </p>
        </div>
        <table style='width:100%;border-collapse:collapse;background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1)'>
            {''.join(rows)}
        </table>
        {more_info}
        <div style='margin-top:24px;padding:16px;background:#f8f9fa;border-radius:6px;font-size:12px;color:#666'>
            Du erhältst diese E-Mail, weil du einen Suchagenten für diese Begriffe aktiviert hast.
            <br>Zeitpunkt: {time.strftime('%d.%m.%Y %H:%M')}
        </div>
    </div>
    """

# -----------------------
# Optimized Orchestrator
# -----------------------

def run_agent_once() -> Dict[str, int]:
    """
    Optimized agent run with comprehensive stats
    Returns: {"checked": int, "mailed": int, "errors": int, "runtime_s": int}
    """
    start_time = time.time()
    
    # Rate limiting check
    if not check_rate_limit():
        return {"checked": 0, "mailed": 0, "errors": 0, "runtime_s": 0, "skipped": True}
    
    # Lock system
    with AgentLock() as lock:
        if lock is None:
            return {"checked": 0, "mailed": 0, "errors": 0, "runtime_s": 0, "locked": True}
        
        print(f"[agent] starting optimized run (max {MAX_ALERTS_PER_RUN} alerts)")
        
        # Initialize
        try:
            init_db_if_needed()
            smtp = get_smtp_settings()
        except Exception as e:
            print(f"[agent] initialization failed: {e}")
            return {"checked": 0, "mailed": 0, "errors": 1, "runtime_s": int(time.time() - start_time)}
        
        # Load alerts
        alerts = load_alerts(MAX_ALERTS_PER_RUN)
        print(f"[agent] loaded {len(alerts)} active alerts")
        
        stats = {"checked": 0, "mailed": 0, "errors": 0}
        
        # Process alerts in batches
        for i in range(0, len(alerts), BATCH_SIZE):
            batch = alerts[i:i + BATCH_SIZE]
            batch_stats = process_alert_batch(batch, smtp)
            
            # Update stats
            for key in stats:
                stats[key] += batch_stats.get(key, 0)
            
            # Progress logging
            if DEBUG_LOG:
                progress = min(i + BATCH_SIZE, len(alerts))
                print(f"[agent] processed {progress}/{len(alerts)} alerts")
        
        # Update last run timestamp
        update_last_run()
        
        runtime = int(time.time() - start_time)
        stats["runtime_s"] = runtime
        
        print(f"[agent] completed: checked={stats['checked']}, mailed={stats['mailed']}, errors={stats['errors']}, runtime={runtime}s")
        return stats

def process_alert_batch(alerts: List[Dict], smtp: Dict[str, object]) -> Dict[str, int]:
    """Process a batch of alerts efficiently"""
    stats = {"checked": 0, "mailed": 0, "errors": 0}
    
    for alert in alerts:
        try:
            stats["checked"] += 1
            
            # Extract alert data
            terms = alert["terms"]
            filters = alert["filters"]
            per_page = alert["per_page"]
            
            # Search eBay
            items_all = search_all_terms(terms, filters, per_page)
            
            if not items_all:
                continue
            
            # De-duplication
            search_hash = make_search_hash(terms, filters)
            new_items = deduplicate_items(alert["user_email"], search_hash, items_all)
            
            if not new_items:
                if DEBUG_LOG:
                    print(f"[agent] alert {alert['id']}: no new items")
                continue
            
            # Send email
            if send_alert_email(alert, new_items, smtp):
                mark_items_as_sent(alert["user_email"], search_hash, new_items)
                stats["mailed"] += 1
                print(f"[agent] alert {alert['id']}: sent {len(new_items)} items to {alert['user_email']}")
            else:
                stats["errors"] += 1
            
            # Update last run timestamp for this alert
            update_alert_timestamp(alert["id"])
            
        except Exception as e:
            print(f"[agent] alert {alert.get('id', '?')} failed: {e}")
            stats["errors"] += 1
    
    return stats

def search_all_terms(terms: List[str], filters: Dict[str, str], per_page: int) -> List[Dict]:
    """Search all terms efficiently"""
    if not terms:
        return []
    
    # Distribute items across terms
    per_term = max(1, per_page // len(terms))
    
    items_all: List[Dict] = []
    for term in terms:
        items = ebay_search(
            term=term,
            limit=per_term,
            offset=0,
            price_min=filters.get("price_min", ""),
            price_max=filters.get("price_max", ""),
            conditions=filters.get("conditions", []),
            sort_ui=filters.get("sort", "best"),
        )
        items_all.extend(items)
    
    return items_all[:per_page]  # Respect overall limit

def deduplicate_items(user_email: str, search_hash: str, items: List[Dict]) -> List[Dict]:
    """Deduplicate items across all sources"""
    # Group by source
    groups: Dict[str, List[Dict]] = {}
    for item in items:
        src = (item.get("src") or "ebay").lower()
        groups.setdefault(src, []).append(item)
    
    # Process each group
    new_all: List[Dict] = []
    for src, group in groups.items():
        new_items = mark_and_filter_new(user_email, search_hash, src, group)
        new_all.extend(new_items)
    
    return new_all

def send_alert_email(alert: Dict, items: List[Dict], smtp: Dict[str, object]) -> bool:
    """Send alert email with enhanced template"""
    terms = alert["terms"]
    user_email = alert["user_email"]
    
    subject = f"🔔 {len(items)} neue Treffer für „{', '.join(terms[:2])}" {'…' if len(terms) > 2 else ''}"
    html_body = render_email_html(subject, items)
    
    return send_mail_optimized(smtp, [user_email], subject, html_body)

def mark_items_as_sent(user_email: str, search_hash: str, items: List[Dict]) -> None:
    """Mark all items as sent across all sources"""
    # Group by source
    groups: Dict[str, List[Dict]] = {}
    for item in items:
        src = (item.get("src") or "ebay").lower()
        groups.setdefault(src, []).append(item)
    
    # Mark each group
    for src, group in groups.items():
        mark_sent(user_email, search_hash, src, group)

def update_alert_timestamp(alert_id: int) -> None:
    """Update last_run_ts for specific alert"""
    conn = get_db()
    conn.execute("UPDATE search_alerts SET last_run_ts=? WHERE id=?", (int(time.time()), alert_id))
    conn.commit()
    conn.close()

# -----------------------
# Health Check & Stats
# -----------------------

def get_agent_stats() -> Dict:
    """Get comprehensive agent statistics"""
    conn = get_db()
    
    # Alert stats
    alert_stats = conn.execute("""
        SELECT 
            COUNT(*) as total_alerts,
            SUM(is_active) as active_alerts,
            COUNT(*) - SUM(is_active) as inactive_alerts
        FROM search_alerts
    """).fetchone()
    
    # Recent activity
    one_hour_ago = int(time.time()) - 3600
    recent_activity = conn.execute("""
        SELECT COUNT(*) as recent_runs
        FROM search_alerts 
        WHERE last_run_ts > ?
    """, (one_hour_ago,)).fetchone()
    
    # Seen items stats
    seen_stats = conn.execute("""
        SELECT 
            COUNT(*) as total_seen_items,
            COUNT(CASE WHEN last_sent > 0 THEN 1 END) as sent_items
        FROM alert_seen
    """).fetchone()
    
    conn.close()
    
    # Runtime info
    runtime_info = {
        "last_run_exists": LAST_RUN_FILE.exists(),
        "lock_exists": LOCK_FILE.exists(),
        "min_interval_seconds": MIN_INTERVAL_SECONDS,
        "max_runtime_seconds": MAX_RUNTIME_SECONDS,
    }
    
    if LAST_RUN_FILE.exists():
        try:
            last_run = float(LAST_RUN_FILE.read_text().strip())
            runtime_info["last_run_timestamp"] = last_run
            runtime_info["seconds_since_last_run"] = int(time.time() - last_run)
        except:
            pass
    
    return {
        "alerts": dict(alert_stats) if alert_stats else {},
        "recent_activity": dict(recent_activity) if recent_activity else {},
        "seen_items": dict(seen_stats) if seen_stats else {},
        "runtime": runtime_info,
        "config": {
            "batch_size": BATCH_SIZE,
            "max_items_per_mail": NOTIFY_MAX_ITEMS_PER_MAIL,
            "max_alerts_per_run": MAX_ALERTS_PER_RUN,
            "debug_enabled": DEBUG_LOG,
        }
    }

def health_check() -> Dict[str, bool]:
    """Basic health check for the agent"""
    checks = {}
    
    # Database connection
    try:
        conn = get_db()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        checks["database"] = True
    except:
        checks["database"] = False
    
    # eBay API credentials
    checks["ebay_credentials"] = bool(EBAY_CLIENT_ID and EBAY_CLIENT_SECRET)
    
    # eBay API token
    try:
        token = ebay_get_token()
        checks["ebay_token"] = bool(token)
    except:
        checks["ebay_token"] = False
    
    # SMTP config
    smtp = get_smtp_settings()
    if smtp.get("use_mailer"):
        checks["email_config"] = True
    else:
        checks["email_config"] = bool(smtp.get("host") and smtp.get("from"))
    
    # Rate limiting
    checks["rate_limit_ok"] = check_rate_limit()
    
    # Lock system
    checks["not_locked"] = not LOCK_FILE.exists()
    
    return checks

# -----------------------
# CLI Interface for Testing
# -----------------------

def test_single_alert(alert_id: int = None, email: str = None) -> None:
    """Test a single alert for debugging"""
    print(f"[test] Testing single alert...")
    
    conn = get_db()
    if alert_id:
        query = "SELECT * FROM search_alerts WHERE id=? AND is_active=1"
        params = (alert_id,)
    elif email:
        query = "SELECT * FROM search_alerts WHERE user_email=? AND is_active=1 LIMIT 1"
        params = (email,)
    else:
        query = "SELECT * FROM search_alerts WHERE is_active=1 LIMIT 1"
        params = ()
    
    row = conn.execute(query, params).fetchone()
    conn.close()
    
    if not row:
        print(f"[test] No active alert found")
        return
    
    # Convert to alert dict
    try:
        terms = json.loads(row["terms_json"] or "[]")
        filters = json.loads(row["filters_json"] or "{}")
    except:
        print(f"[test] Invalid JSON in alert {row['id']}")
        return
    
    alert = {
        "id": row["id"],
        "user_email": row["user_email"],
        "terms": terms,
        "filters": filters,
        "per_page": row["per_page"],
    }
    
    print(f"[test] Testing alert {alert['id']} for {alert['user_email']}")
    print(f"[test] Terms: {alert['terms']}")
    print(f"[test] Filters: {alert['filters']}")
    
    # Get SMTP settings
    smtp = get_smtp_settings()
    
    # Process the alert
    stats = process_alert_batch([alert], smtp)
    
    print(f"[test] Results: {stats}")

# -----------------------
# Main Entry Point
# -----------------------

def main():
    """Main entry point with command line options"""
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "test":
            if len(sys.argv) > 2:
                if sys.argv[2].isdigit():
                    test_single_alert(alert_id=int(sys.argv[2]))
                elif "@" in sys.argv[2]:
                    test_single_alert(email=sys.argv[2])
                else:
                    print("Usage: python agent.py test [alert_id|email]")
            else:
                test_single_alert()
                
        elif command == "stats":
            import pprint
            stats = get_agent_stats()
            pprint.pprint(stats)
            
        elif command == "health":
            health = health_check()
            print("Health Check Results:")
            for check, status in health.items():
                status_str = "✅ PASS" if status else "❌ FAIL"
                print(f"  {check}: {status_str}")
                
        elif command == "run":
            result = run_agent_once()
            print(f"Agent run completed: {result}")
            
        else:
            print("Available commands: run, test, stats, health")
            
    else:
        # Default: run the agent
        result = run_agent_once()
        if result.get("skipped"):
            print("Agent run skipped due to rate limiting")
            sys.exit(0)
        elif result.get("locked"):
            print("Agent run skipped - already running")
            sys.exit(0)
        elif result.get("errors", 0) > 0:
            print(f"Agent run completed with {result['errors']} errors")
            sys.exit(1)
        else:
            print("Agent run completed successfully")
            sys.exit(0)

# For compatibility with existing code
if __name__ == "__main__":
    main()
    run_agent_once()
