# init_db.py
import json
import os
import sqlite3
from datetime import datetime

DB_PATH = "instance/db.sqlite3"


def add_column_if_missing(cur, table: str, column: str, type_sql: str) -> None:
    """Fügt eine Spalte hinzu, falls sie noch nicht existiert."""
    cur.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]
    if column not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {type_sql}")


def init_database(reset: bool = False):
    os.makedirs("instance", exist_ok=True)
    if reset and os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()

    # ==========================
    # 1) USERS
    # ==========================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            email       TEXT PRIMARY KEY,
            password    TEXT,
            plan        TEXT DEFAULT 'free',
            is_premium  INTEGER DEFAULT 0,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")

    # ==========================
    # 2) SEARCH_ALERTS
    # ==========================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS search_alerts (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email          TEXT NOT NULL,
            terms_json          TEXT NOT NULL,
            filters_json        TEXT NOT NULL,
            per_page            INTEGER DEFAULT 30,
            is_active           INTEGER DEFAULT 1,
            notify_immediately  INTEGER DEFAULT 0,
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_run_ts         INTEGER DEFAULT 0,
            last_found_ts       INTEGER DEFAULT 0,
            total_notifications INTEGER DEFAULT 0,
            category            TEXT,
            priority            INTEGER DEFAULT 0,
            FOREIGN KEY (user_email) REFERENCES users(email) ON DELETE CASCADE
        )
    """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_alerts_active ON search_alerts(is_active)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_alerts_user ON search_alerts(user_email)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_alerts_category ON search_alerts(category)"
    )

    # Für bestehende DBs: fehlende Spalten ergänzen (Migration)
    add_column_if_missing(cur, "search_alerts", "category", "TEXT")
    add_column_if_missing(cur, "search_alerts", "priority", "INTEGER DEFAULT 0")

    # ==========================
    # 3) ALERT_SEEN
    # ==========================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_seen (
            user_email   TEXT NOT NULL,
            search_hash  TEXT NOT NULL,
            src          TEXT NOT NULL,       -- 'ebay' / 'amazon'
            item_id      TEXT NOT NULL,

            first_seen   INTEGER NOT NULL,
            last_sent    INTEGER NOT NULL,
            times_seen   INTEGER DEFAULT 1,

            price_first   TEXT,
            price_current TEXT,
            price_lowest  TEXT,

            PRIMARY KEY (user_email, search_hash, src, item_id)
        )
    """
    )

    # ==========================
    # 4) PRICE_HISTORY
    # ==========================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS price_history (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id  TEXT NOT NULL,
            src      TEXT NOT NULL,
            price    TEXT NOT NULL,
            currency TEXT,
            seen_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_price_item ON price_history(item_id, src)"
    )

    # ==========================
    # 5) USER_STATS
    # ==========================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_stats (
            user_email            TEXT PRIMARY KEY,
            total_searches        INTEGER DEFAULT 0,
            total_alerts_created  INTEGER DEFAULT 0,
            total_emails_sent     INTEGER DEFAULT 0,
            total_items_found     INTEGER DEFAULT 0,
            best_deal_saved       REAL DEFAULT 0,
            best_deal_item        TEXT,
            last_activity         TIMESTAMP,
            FOREIGN KEY (user_email) REFERENCES users(email) ON DELETE CASCADE
        )
    """
    )

    # ==========================
    # 6) BOUNCE_LIST
    # ==========================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS bounce_list (
            email        TEXT PRIMARY KEY,
            bounce_type  TEXT,  -- 'hard', 'soft', 'complaint'
            bounced_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            retry_after  TIMESTAMP,
            bounce_count INTEGER DEFAULT 1
        )
    """
    )

    # ==========================
    # 7) PLANS
    # ==========================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS plans (
            id               TEXT PRIMARY KEY,
            name             TEXT NOT NULL,
            price            REAL NOT NULL,
            max_agents       INTEGER NOT NULL,
            max_email_alerts INTEGER NOT NULL,
            features_json    TEXT,
            stripe_price_id  TEXT,
            is_active        INTEGER DEFAULT 1,
            sort_order       INTEGER DEFAULT 0
        )
    """
    )

    plans_data = [
        (
            "free",
            "Hobby-Schrauber",
            0.00,
            5,
            50,
            '{"badge":"🆓","features":["5 Suchagenten","50 E-Mails/Monat","Basis-Support"]}',
            None,
            1,
            0,
        ),
        (
            "basic",
            "Teile-Jäger",
            7.00,
            15,
            200,
            '{"badge":"⭐","features":["15 Suchagenten","200 E-Mails/Monat","Schreibfehler-Suche"]}',
            "price_1234basic",
            1,
            1,
        ),
        (
            "pro",
            "Restaurations-Profi",
            15.00,
            50,
            1000,
            '{"badge":"🏆","features":["50 Suchagenten","1000 E-Mails/Monat","Synonym-Suche"]}',
            "price_1234pro",
            1,
            2,
        ),
        (
            "team",
            "Händler/Werkstatt",
            29.00,
            999,
            9999,
            '{"badge":"💎","features":["Unbegrenzte Suchagenten","Unbegrenzte E-Mails","Alle Features"]}',
            "price_1234team",
            1,
            3,
        ),
    ]
    cur.executemany(
        """
        INSERT OR REPLACE INTO plans
        (id, name, price, max_agents, max_email_alerts, features_json, stripe_price_id, is_active, sort_order)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        plans_data,
    )

    # ==========================
    # 8) SYSTEM_STATS
    # ==========================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS system_stats (
            id                   INTEGER PRIMARY KEY DEFAULT 1,
            total_users          INTEGER DEFAULT 0,
            total_premium_users  INTEGER DEFAULT 0,
            total_alerts         INTEGER DEFAULT 0,
            total_emails_sent    INTEGER DEFAULT 0,
            last_cron_run        TIMESTAMP,
            last_error           TEXT,
            updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )
    cur.execute("INSERT OR IGNORE INTO system_stats (id) VALUES (1)")

    # ==========================
    # 9) VIEWS
    # ==========================
    cur.execute(
        """
        CREATE VIEW IF NOT EXISTS v_active_users AS
        SELECT
            u.email,
            u.plan,
            COUNT(DISTINCT sa.id) as active_alerts,
            MAX(sa.last_run_ts)  as last_activity
        FROM users u
        LEFT JOIN search_alerts sa
            ON u.email = sa.user_email AND sa.is_active = 1
        GROUP BY u.email
    """
    )

    cur.execute(
        """
        CREATE VIEW IF NOT EXISTS v_plan_usage AS
        SELECT
            u.plan,
            p.name as plan_name,
            COUNT(DISTINCT u.email) as user_count,
            COUNT(DISTINCT sa.id)   as total_alerts,
            p.max_agents,
            p.price
        FROM users u
        LEFT JOIN plans p ON u.plan = p.id
        LEFT JOIN search_alerts sa
            ON u.email = sa.user_email AND sa.is_active = 1
        GROUP BY u.plan
    """
    )

    # ==========================
    # 10) DEMO-DATEN
    # ==========================
    demo_users = [
        ("demo@example.com", "demo123", "free", 0),
        ("premium@example.com", "premium123", "pro", 1),
        ("oldtimer-fan@example.com", "pagode123", "basic", 1),
    ]
    for email, password, plan, is_premium in demo_users:
        cur.execute(
            """
            INSERT OR IGNORE INTO users (email, password, plan, is_premium)
            VALUES (?, ?, ?, ?)
        """,
            (email, password, plan, is_premium),
        )

    demo_alerts = [
        {
            "email": "oldtimer-fan@example.com",
            "terms": ["Mercedes W113", "Pagode", "280SL"],
            "filters": {"price_min": "", "price_max": "5000", "sort": "newly"},
            "category": "oldtimer",
        },
        {
            "email": "oldtimer-fan@example.com",
            "terms": ["BMW E30", "M3", "Sportevolution"],
            "filters": {"price_min": "100", "price_max": "2000", "sort": "price_asc"},
            "category": "oldtimer",
        },
        {
            "email": "demo@example.com",
            "terms": ["Porsche 911", "Ölkühler", "original"],
            "filters": {"price_min": "", "price_max": "1000", "sort": "newly"},
            "category": "oldtimer",
        },
    ]
    for a in demo_alerts:
        cur.execute(
            """
            INSERT INTO search_alerts
            (user_email, terms_json, filters_json, category, is_active)
            VALUES (?, ?, ?, ?, 1)
        """,
            (
                a["email"],
                json.dumps(a["terms"], ensure_ascii=False),
                json.dumps(a["filters"], ensure_ascii=False),
                a["category"],
            ),
        )

    # ==========================
    # Abschluss
    # ==========================
    conn.commit()

    user_count = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    alert_count = cur.execute("SELECT COUNT(*) FROM search_alerts").fetchone()[0]

    print("\n" + "=" * 50)
    print("✅ Datenbank erfolgreich initialisiert!")
    print("📊 Statistiken")
    print(f"   • Benutzer:      {user_count}")
    print(f"   • Suchagenten:   {alert_count}")
    print(
        f"   • Preispläne:    {cur.execute('SELECT COUNT(*) FROM plans').fetchone()[0]}"
    )
    print("=" * 50)

    conn.close()


if __name__ == "__main__":
    reset = os.environ.get("RESET_DB") == "1"
    init_database(reset=reset)
