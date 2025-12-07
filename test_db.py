from app_remote import get_db

conn = get_db()
cur = conn.cursor()

# Für PostgreSQL: Spalten der Tabelle search_alerts anzeigen
cur.execute("""
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_name = 'search_alerts'
    ORDER BY ordinal_position
""")

rows = cur.fetchall()
for r in rows:
    print(r)

conn.close()
