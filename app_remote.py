"""
app_remote.py
-------------
Kleine Hilfsdatei, damit der Alert-Checker auf dieselbe Datenbank zugreifen kann
wie die Haupt-DB.

Unterstützt:
- PostgreSQL (empfohlen) über DATABASE_URL / DB_URL / DB_PATH
- SQLite als Fallback (lokal)
"""

import os
from pathlib import Path
import sqlite3

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None

# -------------------------------------------------
# DB-URL aus der Umgebung lesen
#   -> für Postgres z.B.:
#      DATABASE_URL muss als Environment-Variable gesetzt sein
# -------------------------------------------------
DB_URL = (
    os.getenv("DATABASE_URL")
    or os.getenv("DB_URL")
    or os.getenv("DB_PATH", "sqlite:///instance/db.sqlite3")
)


def _connect_postgres(url: str):
    """Stellt eine Verbindung zu PostgreSQL her."""
    if psycopg2 is None:
        raise RuntimeError(
            "psycopg2 ist nicht installiert, aber eine PostgreSQL-URL wurde konfiguriert. "
            "Bitte einmal `pip install psycopg2-binary` ausführen."
        )

    # psycopg2 versteht die URL direkt
    conn = psycopg2.connect(url)
    return conn


def _connect_sqlite(url: str):
    """Stellt eine Verbindung zu SQLite her (lokale Datei)."""
    if url.startswith("sqlite:///"):
        path = url.replace("sqlite:///", "", 1)
    else:
        path = url

    path = Path(path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path), detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    return conn


def get_db():
    """
    Liefert eine DB-Verbindung:
      - PostgreSQL, wenn DB_URL mit postgres:// oder postgresql:// beginnt
      - sonst SQLite
    """
    url = (DB_URL or "").strip()

    if url.startswith("postgres://") or url.startswith("postgresql://"):
        return _connect_postgres(url)

    return _connect_sqlite(url)
