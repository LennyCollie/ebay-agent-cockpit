import os, sqlite3

db_path = os.path.join("instance","db.sqlite3")
print("DB:", db_path)

con = sqlite3.connect(db_path)
cur = con.cursor()

def cols(table):
    return [c[1] for c in cur.execute(f"PRAGMA table_info({table})").fetchall()]

# Tabelle anlegen, falls sie gar nicht existiert (neutrale CREATE IF NOT EXISTS)
cur.execute("""
CREATE TABLE IF NOT EXISTS alert_seen (
    user_email   TEXT    NOT NULL,
    search_hash  TEXT    NOT NULL,
    src          TEXT    NOT NULL,
    item_id      TEXT    NOT NULL,
    first_seen   INTEGER NOT NULL DEFAULT 0,
    last_sent    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_email, search_hash, src, item_id)
)
""")

existing = cols("alert_seen")
if "first_seen" not in existing:
    print("-> add column first_seen")
    cur.execute("ALTER TABLE alert_seen ADD COLUMN first_seen INTEGER NOT NULL DEFAULT 0")

existing = cols("alert_seen")
if "last_sent" not in existing:
    print("-> add column last_sent")
    cur.execute("ALTER TABLE alert_seen ADD COLUMN last_sent INTEGER NOT NULL DEFAULT 0")

con.commit()
con.close()
print("Migration OK")
