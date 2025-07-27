from flask.cli import AppGroup
from app import app, db
import click

@app.cli.command("create")
def create():
    """Creates all tables"""
    db.create_all()
    print("Tables created")
