from flask_migrate import Migrate, MigrateCommand
from flask.cli import with_appcontext
from app import app, db

migrate = Migrate(app, db)
