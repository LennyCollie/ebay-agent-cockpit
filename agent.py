# agent.py – minimaler Cron-Stub
import os, sqlite3, datetime
from pathlib import Path

DB_URL = os.getenv("DB_PATH", "sqlite:///instance/db.sqlite3")

def _sqlite_file_from_url(url: str) -> Path:
    if url.startswith("sqlite:///"):
        return Path(url.replace("sqlite:///", "", 1))
    return Path(url)

DB_FILE = _sqlite_file_from_url(DB_URL)
DB_FILE.parent.mkdir(parents=True, exist_ok=True)

def main():
    DB_FILE.touch(exist_ok=True)  # sorgt dafür, dass es die DB-Datei gibt
    with open("cron_heartbeat.log", "a", encoding="utf-8") as f:
        f.write(f"[{datetime.datetime.utcnow().isoformat()}Z] heartbeat ok\n")

if __name__ == "__main__":
    main()