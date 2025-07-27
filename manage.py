from flask_migrate import MigrateCommand
from flask.cli import AppGroup
from app import app, db
import click

migrate_cli = AppGroup('db')

@app.cli.command("create")
def create():
    """Creates all tables"""
    db.create_all()
    print("Tables created")

if __name__ == "__main__":
    app.run()
