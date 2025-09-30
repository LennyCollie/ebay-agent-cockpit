# init_db.py
import hashlib
import json
import sqlite3
from datetime import datetime

# Datenbankverbindung
DB_PATH = "instance/db.sqlite3"  # Gleicher Pfad wie in Ihrer app.py


def init_database():
    """Initialisiert alle Tabellen für die eBay Agent App"""

    # Ordner erstellen falls nicht vorhanden
    import os

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("📦 Erstelle Datenbank-Schema...")

    # ==========================================
    # 1. USERS TABELLE (mit Preismodell)
    # ==========================================
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,

            -- Preismodell
            plan TEXT DEFAULT 'free',  -- free, basic, pro, dealer
            is_premium INTEGER DEFAULT 0,  -- Legacy Support

            -- Stripe Integration
            stripe_customer_id TEXT,
            stripe_subscription_id TEXT,

            -- Tracking
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP,

            -- Limits
            max_agents INTEGER DEFAULT 5,
            max_email_alerts INTEGER DEFAULT 50
        )
    """
    )

    # Index für schnelle E-Mail-Suche
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_users_email
        ON users(email)
    """
    )

    # ==========================================
    # 2. SEARCH_ALERTS (Gespeicherte Suchen)
    # ==========================================
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS search_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT NOT NULL,

            -- Suchparameter
            terms_json TEXT NOT NULL,      -- ["Mercedes W113", "Pagode", etc.]
            filters_json TEXT NOT NULL,    -- {"price_min": "", "price_max": "", etc.}

            -- Konfiguration
            per_page INTEGER DEFAULT 30,
            is_active INTEGER DEFAULT 1,
            notify_immediately INTEGER DEFAULT 0,  -- Sofort-Benachrichtigung?

            -- Tracking
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_run_ts INTEGER DEFAULT 0,
            last_found_ts INTEGER DEFAULT 0,
            total_notifications INTEGER DEFAULT 0,

            -- Spezial für Oldtimer
            category TEXT,  -- 'oldtimer', 'sneaker', 'lego', etc.
            priority INTEGER DEFAULT 0,  -- 0=normal, 1=high, 2=urgent

            FOREIGN KEY (user_email) REFERENCES users(email) ON DELETE CASCADE
        )
    """
    )

    # Indices für Performance
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_alerts_active
        ON search_alerts(is_active)
    """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_alerts_user
        ON search_alerts(user_email)
    """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_alerts_category
        ON search_alerts(category)
    """
    )

    # ==========================================
    # 3. ALERT_SEEN (De-Duping für E-Mails)
    # ==========================================
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_seen (
            user_email TEXT NOT NULL,
            search_hash TEXT NOT NULL,
            src TEXT NOT NULL,          -- 'ebay' oder 'amazon'
            item_id TEXT NOT NULL,

            first_seen INTEGER NOT NULL,
            last_sent INTEGER NOT NULL,
            times_seen INTEGER DEFAULT 1,

            -- Zusätzliche Infos
            price_first TEXT,           -- Erster gesehener Preis
            price_current TEXT,          -- Aktueller Preis
            price_lowest TEXT,           -- Niedrigster gesehener Preis

            PRIMARY KEY (user_email, search_hash, src, item_id)
        )
    """
    )

    # ==========================================
    # 4. PRICE_HISTORY (Preisverlauf tracking)
    # ==========================================
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id TEXT NOT NULL,
            src TEXT NOT NULL,
            price TEXT NOT NULL,
            currency TEXT,
            seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            INDEX idx_price_item (item_id, src)
        )
    """
    )

    # ==========================================
    # 5. USER_STATS (Statistiken)
    # ==========================================
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_stats (
            user_email TEXT PRIMARY KEY,

            total_searches INTEGER DEFAULT 0,
            total_alerts_created INTEGER DEFAULT 0,
            total_emails_sent INTEGER DEFAULT 0,
            total_items_found INTEGER DEFAULT 0,

            best_deal_saved REAL DEFAULT 0,  -- Beste Ersparnis in EUR
            best_deal_item TEXT,

            last_activity TIMESTAMP,

            FOREIGN KEY (user_email) REFERENCES users(email) ON DELETE CASCADE
        )
    """
    )

    # ==========================================
    # 6. BOUNCE_LIST (E-Mail Bounces)
    # ==========================================
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS bounce_list (
            email TEXT PRIMARY KEY,
            bounce_type TEXT,  -- 'hard', 'soft', 'complaint'
            bounced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            retry_after TIMESTAMP,
            bounce_count INTEGER DEFAULT 1
        )
    """
    )

    # ==========================================
    # 7. PLANS (Preismodell-Definitionen)
    # ==========================================
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS plans (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            price REAL NOT NULL,

            max_agents INTEGER NOT NULL,
            max_email_alerts INTEGER NOT NULL,

            features_json TEXT,  -- JSON mit Features
            stripe_price_id TEXT,

            is_active INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0
        )
    """
    )

    # ==========================================
    # Standard-Preispläne einfügen
    # ==========================================
    plans_data = [
        (
            "free",
            "Hobby-Schrauber",
            0,
            5,
            50,
            '{"badge": "🆓", "features": ["5 Suchagenten", "50 E-Mails/Monat", "Basis-Support"]}',
            None,
            1,
            0,
        ),
        (
            "basic",
            "Teile-Jäger",
            9.99,
            15,
            200,
            '{"badge": "⭐", "features": ["15 Suchagenten", "200 E-Mails/Monat", "Schreibfehler-Suche", "Priority-Support"]}',
            "price_1234basic",
            1,
            1,
        ),
        (
            "pro",
            "Restaurations-Profi",
            19.99,
            50,
            1000,
            '{"badge": "🏆", "features": ["50 Suchagenten", "1000 E-Mails/Monat", "Schreibfehler-Suche", "Synonym-Suche", "API-Zugang", "Priority-Support"]}',
            "price_1234pro",
            1,
            2,
        ),
        (
            "dealer",
            "Händler/Werkstatt",
            39.99,
            999,
            9999,
            '{"badge": "💎", "features": ["Unbegrenzte Suchagenten", "Unbegrenzte E-Mails", "Alle Features", "Telefon-Support", "Custom-Integration"]}',
            "price_1234dealer",
            1,
            3,
        ),
    ]

    cursor.executemany(
        """
        INSERT OR REPLACE INTO plans
        (id, name, price, max_agents, max_email_alerts, features_json, stripe_price_id, is_active, sort_order)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        plans_data,
    )

    # ==========================================
    # Demo-Benutzer erstellen (für Tests)
    # ==========================================
    demo_users = [
        ("demo@example.com", "demo123", "free", 0),
        ("premium@example.com", "premium123", "pro", 1),
        ("oldtimer-fan@example.com", "pagode123", "basic", 1),
    ]

    for email, password, plan, is_premium in demo_users:
        try:
            cursor.execute(
                """
                INSERT INTO users (email, password, plan, is_premium)
                VALUES (?, ?, ?, ?)
            """,
                (email, password, plan, is_premium),
            )
            print(f"✅ Demo-User erstellt: {email} (Plan: {plan})")
        except sqlite3.IntegrityError:
            print(f"ℹ️ User existiert bereits: {email}")

    # ==========================================
    # Demo-Suchagenten für Oldtimer
    # ==========================================
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

    for alert in demo_alerts:
        try:
            cursor.execute(
                """
                INSERT INTO search_alerts
                (user_email, terms_json, filters_json, category, is_active)
                VALUES (?, ?, ?, ?, 1)
            """,
                (
                    alert["email"],
                    json.dumps(alert["terms"], ensure_ascii=False),
                    json.dumps(alert["filters"], ensure_ascii=False),
                    alert["category"],
                ),
            )
            print(f"✅ Demo-Suchagent erstellt: {alert['terms'][0]}")
        except Exception as e:
            print(f"ℹ️ Suchagent-Fehler: {e}")

    # ==========================================
    # Statistik-Tabelle für Admin-Dashboard
    # ==========================================
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS system_stats (
            id INTEGER PRIMARY KEY DEFAULT 1,

            total_users INTEGER DEFAULT 0,
            total_premium_users INTEGER DEFAULT 0,
            total_alerts INTEGER DEFAULT 0,
            total_emails_sent INTEGER DEFAULT 0,

            last_cron_run TIMESTAMP,
            last_error TEXT,

            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )

    # Initial-Statistik
    cursor.execute(
        """
        INSERT OR IGNORE INTO system_stats (id) VALUES (1)
    """
    )

    # ==========================================
    # Views für einfachere Abfragen
    # ==========================================
    cursor.execute(
        """
        CREATE VIEW IF NOT EXISTS v_active_users AS
        SELECT
            u.email,
            u.plan,
            COUNT(DISTINCT sa.id) as active_alerts,
            MAX(sa.last_run_ts) as last_activity
        FROM users u
        LEFT JOIN search_alerts sa ON u.email = sa.user_email AND sa.is_active = 1
        GROUP BY u.email
    """
    )

    cursor.execute(
        """
        CREATE VIEW IF NOT EXISTS v_plan_usage AS
        SELECT
            u.plan,
            p.name as plan_name,
            COUNT(DISTINCT u.email) as user_count,
            COUNT(DISTINCT sa.id) as total_alerts,
            p.max_agents,
            p.price
        FROM users u
        LEFT JOIN plans p ON u.plan = p.id
        LEFT JOIN search_alerts sa ON u.email = sa.user_email AND sa.is_active = 1
        GROUP BY u.plan
    """
    )

    # Änderungen speichern
    conn.commit()

    # Statistiken ausgeben
    user_count = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    alert_count = cursor.execute("SELECT COUNT(*) FROM search_alerts").fetchone()[0]

    print("\n" + "=" * 50)
    print("✅ Datenbank erfolgreich initialisiert!")
    print(f"📊 Statistiken:")
    print(f"   - Benutzer: {user_count}")
    print(f"   - Suchagenten: {alert_count}")
    print(f"   - Preispläne: 4")
    print("=" * 50)

    conn.close()


if __name__ == "__main__":
    init_database()
