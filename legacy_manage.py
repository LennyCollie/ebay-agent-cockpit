import click
from flask.cli import AppGroup

from app import app, db


@app.cli.command("create")
def create():
    """Creates all tables"""
    db.create_all()
    print("Tables created")
