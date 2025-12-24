print("Testing SQLAlchemy import...", flush=True)
import sqlalchemy
print("SQLAlchemy imported successfully", flush=True)

print("Testing create_engine...", flush=True)
from sqlalchemy import create_engine
print("create_engine imported", flush=True)

from pathlib import Path
db_path = Path("instance/db.sqlite3")
print(f"DB path: {db_path}", flush=True)

db_path.parent.mkdir(exist_ok=True, parents=True)
print("Directory created", flush=True)

db_url = f"sqlite:///{db_path}"
print(f"DB URL: {db_url}", flush=True)

print("Creating engine...", flush=True)
engine = create_engine(db_url, connect_args={"check_same_thread": False})
print("Engine created successfully!", flush=True)
