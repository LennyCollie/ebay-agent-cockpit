# agent.py  —  Cron-Worker für E-Mail-Benachrichtigungen
import os, time, sqlite3, smtplib, requests
from email.message import EmailMessage
from html import escape
from typing import List, Dict, Optional, Tuple

# ---------- Helpers ----------
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

# ---------- Config aus ENV ----------
DB_URL   = os.getenv("DB_PATH", "sqlite:///instance/db.sqlite3")
DB_FILE  = sqlite_file_from_url(DB_URL)

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

# SMTP / Mail
SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "587"))
SMTP_USER = os.getenv("EMAIL_USER", "")
SMTP_PASS = os.getenv("EMAIL_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", SMTP_USER or "alerts@localhost")
DEFAULT_TO = os.getenv("ALERT_DEFAULT_TO", "")

# Lauf-Parameter
MAX_ITEMS_PER_ALERT = int(os.getenv("ALERT_MAX_ITEMS", "12"))
DEBUG_LOG = as_bool(os.getenv("ALERT_DEBUG", "0"))

# eBay Token Cache
_EBAY_TOKEN = {"access_token": None, "expires_at": 0.0}

# ---------- DB ----------
def get_db() -> sqlite3.Connection:
    if os.path.dirname(DB_FILE):
        os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT NOT NULL,
            q1 TEXT,
            q2 TEXT,
            q3 TEXT,
            price_min TEXT,
            price_max TEXT,
            sort TEXT,              -- best | price_asc | price_desc | newly
            conditions TEXT,        -- Komma: NEW,USED,OPEN_BOX,...
            per_page INTEGER DEFAULT 30,
            enabled INTEGER NOT NULL DEFAULT 1,
            last_run TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS alert_seen (
            alert_id INTEGER NOT NULL,
            item_id  TEXT NOT NULL,
            PRIMARY KEY (alert_id, item_id)
        )
    """)
    conn.commit()
    conn.close()

# ---------- Mail ----------
def send_email(to_addr: str, subject: str, html_body: str):
    if not SMTP_USER or not SMTP_PASS:
        print("[mail] SMTP credentials missing -> skip")
        return
    msg = EmailMessage()
    msg["From"] = EMAIL_FROM
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content("HTML only", subtype="plain")
    msg.add_alternative(html_body, subtype="html")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)

# ---------- eBay API ----------
def ebay_get_token() -> Optional[str]:
    now = time.time()
    if _EBAY_TOKEN["access_token"] and now < _EBAY_TOKEN["expires_at"]:
        return _EBAY_TOKEN["access_token"]
    if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
        print("[ebay] Missing client id/secret")
        return None
    url  = "https://api.ebay.com/identity/v1/oauth2/token"
    auth = requests.auth.HTTPBasicAuth(EBAY_CLIENT_ID, EBAY_CLIENT_SECRET)
    data = {"grant_type": "client_credentials", "scope": EBAY_SCOPES}
    try:
        r = requests.post(url, auth=auth, data=data, timeout=20)
        r.raise_for_status()
        j = r.json()
        _EBAY_TOKEN["access_token"] = j.get("access_token")
        _EBAY_TOKEN["expires_at"]  = time.time() + int(j.get("expires_in", 7200)) - 60
        return _EBAY_TOKEN["access_token"]
    except Exception as e:
        print(f"[ebay_token] {e}")
        return None

def _build_ebay_filter(price_min: str, price_max: str, conditions: List[str]) -> Optional[str]:
    parts = []
    pmn = (price_min or "").strip()
    pmx = (price_max or "").strip()
    if pmn or pmx:
        parts.append(f"price:[{pmn}..{pmx}]")
        if EBAY_CURRENCY:
            parts.append(f"priceCurrency:{EBAY_CURRENCY}")
    conds = [c.strip().upper() for c in conditions if c.strip()]
    if conds:
        parts.append("conditions:{" + ",".join(conds) + "}")
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
        "X-EBAY-C-MARKETPLACE-ID": EBAY_MARKETPLACE_ID
    }
    try:
        r = requests.get(url, headers=headers, params=params, timeout=20)
        r.raise_for_status()
        j = r.json() or {}
        items = []
        for it in j.get("itemSummaries", []) or []:
            items.append({
                "id": it.get("itemId") or it.get("itemGroupId") or it.get("itemWebUrl"),
                "title": it.get("title") or "—",
                "url": it.get("itemWebUrl"),
                "img": (it.get("image") or {}).get("imageUrl"),
                "price": (it.get("price") or {}).get("value"),
                "cur": (it.get("price") or {}).get("currency"),
            })
        return items
    except Exception as e:
        print(f"[ebay_search] {e}")
        return []

# ---------- Alerts ----------
def ensure_default_alert_if_empty():
    """Legt optional einen Beispiel-Alert an (nur einmal),
       wenn ALERT_DEFAULT_TO gesetzt ist und noch keine Alerts existieren."""
    to = DEFAULT_TO or os.getenv("OWNER_EMAIL", "")
    if not to:
        return
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM alerts")
    count = cur.fetchone()[0]
    if count == 0:
        cur.execute("""INSERT INTO alerts (user_email,q1,q2,q3,price_min,price_max,sort,conditions,per_page,enabled)
                       VALUES (?,?,?,?,?,?,?,?,?,1)""",
                    (to, "iphone", "Tonband", "iphone 11", "", "", "best", "NEW,USED", 30))
        conn.commit()
        print(f"[alerts] default alert created for {to}")
    conn.close()

def load_alerts() -> List[sqlite3.Row]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM alerts WHERE enabled=1").fetchall()
    conn.close()
    return rows

def save_seen(alert_id: int, item_ids: List[str]):
    if not item_ids:
        return
    conn = get_db()
    cur = conn.cursor()
    cur.executemany("INSERT OR IGNORE INTO alert_seen (alert_id,item_id) VALUES (?,?)",
                    [(alert_id, i) for i in item_ids if i])
    conn.commit()
    conn.close()

def unseen_only(alert_id: int, items: List[Dict]) -> List[Dict]:
    if not items:
        return []
    ids = [i["id"] for i in items if i.get("id")]
    if not ids:
        return items
    conn = get_db()
    cur  = conn.cursor()
    q    = ",".join("?" for _ in ids)
    rows = cur.execute(f"SELECT item_id FROM alert_seen WHERE alert_id=? AND item_id IN ({q})",
                       [alert_id, *ids]).fetchall()
    seen = {r["item_id"] for r in rows}
    conn.close()
    return [i for i in items if i.get("id") not in seen]

def render_email_html(title: str, items: List[Dict]) -> str:
    parts = [f"<h3 style='margin:0 0 12px'>{escape(title)}</h3>"]
    parts.append("<table style='width:100%;border-collapse:collapse'>")
    for it in items:
        price = f"{it['price']} {it['cur']}" if it.get("price") and it.get("cur") else "–"
        img = it.get("img") or "https://via.placeholder.com/64x48?text=%20"
        parts.append(
            "<tr style='border-bottom:1px solid #eee'>"
            f"<td style='padding:8px;width:72px'><img src='{img}' width='64' height='48' style='border-radius:4px;object-fit:cover'></td>"
            f"<td style='padding:8px'><a href='{it.get('url')}'>{escape(it.get('title') or '—')}</a><br>"
            f"<span style='color:#666;font-size:12px'>{escape(price)}</span></td>"
            "</tr>"
        )
    parts.append("</table>")
    return "<div style='font-family:system-ui,Segoe UI,Arial,sans-serif'>" + "".join(parts) + "</div>"

def run_once():
    init_db()
    ensure_default_alert_if_empty()
    alerts = load_alerts()
    if DEBUG_LOG:
        print(f"[alerts] {len(alerts)} active alerts")
    for a in alerts:
        terms = [t for t in [a["q1"], a["q2"], a["q3"]] if t]
        if not terms:
            continue
        conds = [c.strip().upper() for c in (a["conditions"] or "").split(",") if c.strip()]
        per_page = int(a["per_page"] or 30)
        per_term = max(1, min(10, per_page // max(1,len(terms))))
        items_all: List[Dict] = []
        for t in terms:
            items = ebay_search(
                term=t,
                limit=per_term,
                offset=0,
                price_min=a["price_min"] or "",
                price_max=a["price_max"] or "",
                conditions=conds,
                sort_ui=a["sort"] or "best"
            )
            items_all.extend(items)

        new_items = unseen_only(a["id"], items_all)
        if DEBUG_LOG:
            print(f"[alerts] alert #{a['id']} -> {len(new_items)} new")
        if not new_items:
            continue

        new_items = new_items[:MAX_ITEMS_PER_ALERT]
        subject = f"Neue Treffer: {', '.join(terms)}"
        html = render_email_html(subject, new_items)
        recipient = a["user_email"] or DEFAULT_TO
        if recipient:
            send_email(recipient, subject, html)
            save_seen(a["id"], [i["id"] for i in new_items])
        else:
            print("[alerts] no recipient -> skip")

if __name__ == "__main__":
    run_once()