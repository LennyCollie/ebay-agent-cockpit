import os
import psycopg2
from psycopg2.extras import RealDictCursor
import sqlite3
from typing import Union

# ===================================================================
# DATABASE CONFIGURATION
# ===================================================================

# Hole DATABASE_URL von Render
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("DB_PATH")
IS_POSTGRES = DATABASE_URL and DATABASE_URL.startswith("postgresql")

# ===================================================================
# DATABASE CONNECTION FUNCTIONS
# ===================================================================

def get_db():
    """Verbindet zu PostgreSQL oder SQLite (Fallback für lokal)"""
    if IS_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    else:
        from pathlib import Path
        db_file = Path("instance/db.sqlite3")
        db_file.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_file), detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        return conn


def dict_cursor(conn):
    """Gibt einen Dictionary-Cursor zurück (für beide DB-Typen)"""
    if IS_POSTGRES:
        return conn.cursor(cursor_factory=RealDictCursor)
    else:
        return conn.cursor()


def get_placeholder():
    """Gibt den richtigen Platzhalter für die DB zurück (%s für PostgreSQL, ? für SQLite)"""
    return "%s" if IS_POSTGRES else "?"


# ===================================================================
# MIGRATION FUNCTION (NUR EINMALIG NUTZEN!)
# ===================================================================

def drop_all_tables():
    """
    Löscht alle Tabellen - NUR FÜR MIGRATION!
    Wird nur ausgeführt wenn RUN_MIGRATION = True
    """
    print("\n" + "🗑️ "*20)
    print("🗑️  WARNUNG: Lösche ALLE Tabellen!")
    print("🗑️  Alle Daten gehen verloren!")
    print("🗑️ "*20 + "\n")

    conn = get_db()
    cur = dict_cursor(conn) if IS_POSTGRES else conn.cursor()

    try:
        if IS_POSTGRES:
            cur.execute("DROP TABLE IF EXISTS users CASCADE")
            cur.execute("DROP TABLE IF EXISTS alert_seen CASCADE")
            cur.execute("DROP TABLE IF EXISTS search_alerts CASCADE")
            cur.execute("DROP TABLE IF EXISTS watchlist CASCADE")
            cur.execute("DROP TABLE IF EXISTS notification_log CASCADE")
            print("[drop_all_tables] [+] PostgreSQL Tabellen gelöscht")
        else:
            cur.execute("DROP TABLE IF EXISTS users")
            cur.execute("DROP TABLE IF EXISTS alert_seen")
            cur.execute("DROP TABLE IF EXISTS search_alerts")
            cur.execute("DROP TABLE IF EXISTS watchlist")
            cur.execute("DROP TABLE IF EXISTS notification_log")
            print("[drop_all_tables] [+] SQLite Tabellen gelöscht")

        conn.commit()
        print("[drop_all_tables] [OK] Erfolgreich abgeschlossen\n")
    except Exception as e:
        print(f"[drop_all_tables] [!] Fehler: {e}")
    finally:
        conn.close()


# ===================================================================
# INIT DATABASE - Erstellt alle Tabellen
# ===================================================================

def init_db() -> None:
    """Initialisiert alle Tabellen mit korrektem Schema"""
    conn = get_db()
    cur = dict_cursor(conn)

    print("[init_db] Erstelle Tabellen...")

    if IS_POSTGRES:
        # ==================== POSTGRESQL SCHEMA ====================

        # Users Tabelle
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                is_premium INTEGER NOT NULL DEFAULT 0,
                telegram_chat_id TEXT,
                telegram_enabled INTEGER NOT NULL DEFAULT 0,
                telegram_verified INTEGER NOT NULL DEFAULT 0,
                telegram_username TEXT,
                plan_type TEXT NOT NULL DEFAULT 'free',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("[init_db] [+] users (PostgreSQL)")

        # Alert Seen (für De-Duping)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS alert_seen (
                user_email TEXT NOT NULL,
                search_hash TEXT NOT NULL,
                src TEXT NOT NULL,
                item_id TEXT NOT NULL,
                first_seen INTEGER NOT NULL,
                last_sent INTEGER NOT NULL,
                PRIMARY KEY (user_email, search_hash, src, item_id)
            )
        """)
        print("[init_db] [+] alert_seen")

        # Search Alerts (gespeicherte Suchen)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS search_alerts (
                id SERIAL PRIMARY KEY,
                user_email TEXT NOT NULL,
                terms_json TEXT NOT NULL,
                filters_json TEXT NOT NULL,
                source TEXT DEFAULT 'ebay',
                per_page INTEGER NOT NULL DEFAULT 20,
                is_active INTEGER NOT NULL DEFAULT 1,
                last_run_ts INTEGER NOT NULL DEFAULT 0,
                notify_email INTEGER NOT NULL DEFAULT 0,
                notify_telegram INTEGER NOT NULL DEFAULT 0,
                notify_mobilede INTEGER NOT NULL DEFAULT 0,
                notify_autoscout INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("[init_db] [+] search_alerts")

        # Index für aktive Alerts
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_alerts_active
            ON search_alerts(is_active)
            WHERE is_active = 1
        """)

        # Watchlist
        cur.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                id SERIAL PRIMARY KEY,
                user_email TEXT NOT NULL,
                item_id TEXT NOT NULL,
                title TEXT,
                price TEXT,
                url TEXT,
                img TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_email, item_id)
            )
        """)
        print("[init_db] [+] watchlist")

        # Notification Log (optional)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notification_log (
                id SERIAL PRIMARY KEY,
                user_email TEXT NOT NULL,
                notification_type TEXT NOT NULL,
                message TEXT,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("[init_db] [+] notification_log")

        # Item Price History (für ML Prognosen)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS item_price_history (
                id SERIAL PRIMARY KEY,
                item_hash TEXT NOT NULL UNIQUE,
                item_title TEXT,
                price_current NUMERIC(10,2),
                price_min NUMERIC(10,2),
                price_max NUMERIC(10,2),
                portal TEXT,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_item_price_hash 
            ON item_price_history(item_hash)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_item_price_seen 
            ON item_price_history(last_seen)
        """)
        print("[init_db] [+] item_price_history (PostgreSQL)")

    else:
        # ==================== SQLITE SCHEMA ====================

        # Users Tabelle
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                is_premium INTEGER NOT NULL DEFAULT 0,
                telegram_chat_id TEXT,
                telegram_enabled INTEGER NOT NULL DEFAULT 0,
                telegram_verified INTEGER NOT NULL DEFAULT 0,
                telegram_username TEXT,
                plan_type TEXT NOT NULL DEFAULT 'free',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("[init_db] [+] users (SQLite)")

        # Alert Seen
        cur.execute("""
            CREATE TABLE IF NOT EXISTS alert_seen (
                user_email TEXT NOT NULL,
                search_hash TEXT NOT NULL,
                src TEXT NOT NULL,
                item_id TEXT NOT NULL,
                first_seen INTEGER NOT NULL,
                last_sent INTEGER NOT NULL,
                PRIMARY KEY (user_email, search_hash, src, item_id)
            )
        """)
        print("[init_db] [+] alert_seen")

        # Search Alerts
        cur.execute("""
            CREATE TABLE IF NOT EXISTS search_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                terms_json TEXT NOT NULL,
                filters_json TEXT NOT NULL,
                source TEXT DEFAULT 'ebay',
                per_page INTEGER NOT NULL DEFAULT 20,
                is_active INTEGER NOT NULL DEFAULT 1,
                last_run_ts INTEGER NOT NULL DEFAULT 0,
                notify_email INTEGER NOT NULL DEFAULT 0,
                notify_telegram INTEGER NOT NULL DEFAULT 0,
                notify_mobilede INTEGER NOT NULL DEFAULT 0,
                notify_autoscout INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("[init_db] [+] search_alerts")

        # Index für aktive Alerts
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_alerts_active
            ON search_alerts(is_active)
        """)

        # Watchlist
        cur.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                item_id TEXT NOT NULL,
                title TEXT,
                price TEXT,
                url TEXT,
                img TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_email, item_id)
            )
        """)
        print("[init_db] [+] watchlist")

        # Notification Log
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notification_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                notification_type TEXT NOT NULL,
                message TEXT,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("[init_db] [+] notification_log")

        # Item Price History (für ML Prognosen)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS item_price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_hash TEXT NOT NULL UNIQUE,
                item_title TEXT,
                price_current REAL,
                price_min REAL,
                price_max REAL,
                portal TEXT,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_item_price_hash 
            ON item_price_history(item_hash)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_item_price_seen 
            ON item_price_history(last_seen)
        """)
        print("[init_db] [+] item_price_history (SQLite)")

    conn.commit()
    conn.close()
    print("[init_db] [OK] Datenbank erfolgreich initialisiert!\n")


# ===================================================================
# MIGRATION CONTROL
# ===================================================================

# [!] WICHTIG: Nach dem ersten Start auf False setzen!
RUN_MIGRATION = False

if RUN_MIGRATION:
    print("\n" + "[!] "*30)
    print("[!]  MIGRATION MODE AKTIV!")
    print("[!]  Alle Tabellen werden gelöscht und neu erstellt!")
    print("[!]  ")
    print("[!]  NACH DEM START:")
    print("[!]  1. App stoppen (Ctrl+C)")
    print("[!]  2. In database.py: RUN_MIGRATION = False setzen")
    print("[!]  3. App neu starten")
    print("[!] "*30 + "\n")
    drop_all_tables()

# Bei Import automatisch initialisieren
init_db()
