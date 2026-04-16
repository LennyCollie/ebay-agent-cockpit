import sqlite3
import os
from database import get_db, IS_POSTGRES

def migrate():
    print(f"Starting migration... (Postgres: {IS_POSTGRES})")
    conn = get_db()
    cur = conn.cursor()

    columns_to_add = [
        ("source", "TEXT DEFAULT 'ebay'"),
        ("notify_email", "INTEGER NOT NULL DEFAULT 0"),
        ("notify_telegram", "INTEGER NOT NULL DEFAULT 0"),
        ("notify_mobilede", "INTEGER NOT NULL DEFAULT 0"),
        ("notify_autoscout", "INTEGER NOT NULL DEFAULT 0")
    ]

    for col_name, col_type in columns_to_add:
        try:
            print(f"Adding column {col_name}...")
            if IS_POSTGRES:
                cur.execute(f"ALTER TABLE search_alerts ADD COLUMN IF NOT EXISTS {col_name} {col_type}")
            else:
                # SQLite doesn't support ADD COLUMN IF NOT EXISTS
                try:
                    cur.execute(f"ALTER TABLE search_alerts ADD COLUMN {col_name} {col_type}")
                except sqlite3.OperationalError as e:
                    if "duplicate column name" in str(e).lower():
                        print(f"Column {col_name} already exists.")
                    else:
                        raise e
            print(f"Column {col_name} added or already exists.")
        except Exception as e:
            print(f"Error adding {col_name}: {e}")

    conn.commit()
    conn.close()
    print("Migration finished.")

if __name__ == "__main__":
    migrate()
