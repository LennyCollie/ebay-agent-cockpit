from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import os

# Flask-Anwendung initialisieren
app = Flask(__name__)

# Konfiguration über Umgebungsvariable
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("SQLALCHEMY_DATABASE_URI")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get("API_SECRET_KEY", "fallback-secret")

# Datenbank und Migration initialisieren
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Beispielmodell für Testzwecke (kann später gelöscht werden)
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)

    def __repr__(self):
        return f"<User {self.username}>"

# Routen
@app.route('/')
def index():
    return "✅ Flask App läuft auf Render & Datenbank ist verbunden!"

# Nur lokal ausführen
if __name__ == "__main__":
    app.run(debug=True)
