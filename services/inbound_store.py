# services/inbound_store.py
from datetime import datetime
import json, os
import json, sqlite3, time

from typing import Optional, Dict, Any

DB_PATH = "instance/app.db"  # falls du einen anderen Pfad nutzt, anpassen

_SCHEMA = """
CREATE TABLE IF NOT EXISTS inbound_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    src TEXT NOT NULL,
    from_email TEXT,
    to_email TEXT,
    subject TEXT,
    body TEXT,
    raw_json TEXT NOT NULL
);
"""

def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def ensure_table() -> None:
    with _conn() as conn:
        conn.executescript(_SCHEMA)

def store_event(src: str, payload: Dict[str, Any]) -> None:
    ensure_table()
    ts = int(time.time())
    from_email = payload.get("FromFull", {}).get("Email") or payload.get("From")
    to_list = payload.get("ToFull") or []
    to_email = to_list[0]["Email"] if to_list else None
    subject = payload.get("Subject")
    # TextBody ist meist am einfachsten zu parsen; zur Not HtmlBody
    body = payload.get("TextBody") or payload.get("HtmlBody") or ""
    raw_json = json.dumps(payload, ensure_ascii=False)
    with _conn() as conn:
        conn.execute(
            """INSERT INTO inbound_events
               (ts, src, from_email, to_email, subject, body, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (ts, src, from_email, to_email, subject, body, raw_json),
        )

def store_event(source: str, payload: dict, summary: str | None = None):
    """Schreibt jedes Inbound-Event als JSONL-Zeile (append) – super zum Debuggen & Replays."""
    line = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "source": source,
        "summary": summary,
        "payload": payload,
    }
    out = os.getenv("INBOUND_DUMP_PATH", "/tmp/inbound_events.jsonl")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
