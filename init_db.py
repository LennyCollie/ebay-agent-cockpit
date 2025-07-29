import sqlite3

# Verbindung zur Datenbank herstellen (wird erstellt, falls sie nicht existiert)
conn = sqlite3.connect('users.db')

# Cursor-Objekt zum Ausführen von SQL-Befehlen
cursor = conn.cursor()

# Tabelle 'users' erstellen, falls sie noch nicht existiert
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL
)
''')

# Änderungen speichern und Verbindung schließen
conn.commit()
conn.close()

print("Die Datenbank 'users.db' wurde erfolgreich initialisiert.")
