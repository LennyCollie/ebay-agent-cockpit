# Importiere die App und die Datenbank-Instanz aus unserer Haupt-Anwendung
from app import app, db

# Dieser "with"-Block ist entscheidend. Er gibt uns Zugriff auf die App-Konfiguration.
with app.app_context():
    print(">>> Datenbank wird zurückgesetzt...")

    # Lösche alle bestehenden Tabellen
    db.drop_all()
    print("    Alte Tabellen gelöscht.")

    # Erstelle alle Tabellen neu, basierend auf den Models in app.py
    db.create_all()
    print("    Neue, korrekte Tabellen erstellt.")

    print(">>> Wartung abgeschlossen.")
