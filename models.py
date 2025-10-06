# models.py
import os
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from werkzeug.security import check_password_hash, generate_password_hash

# DB Connection
DB_URL = os.getenv(
    "DB_PATH",
    "postgresql://agent_db_final_user:7FfbPfBywc3Xd0qCDWSwCT3cxl7NSMvt@dpg-d1ua2849c44c73cp4cag-a.oregon-postgres.render.com/agent_db_final",
)
engine = create_engine(DB_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(
        String(255), nullable=True
    )  # Nullable für OAuth/Social Login

    # Subscription Info
    stripe_customer_id = Column(String(255), unique=True, nullable=True)
    stripe_subscription_id = Column(String(255), nullable=True)
    plan = Column(String(50), default="free")  # free, basic, pro, team
    plan_status = Column(String(50), default="active")  # active, canceled, past_due

    # Telegram
    telegram_chat_id = Column(String(255), nullable=True, unique=True)
    telegram_username = Column(String(255), nullable=True)
    telegram_verified = Column(Boolean, default=False)
    telegram_enabled = Column(
        Boolean, default=True
    )  # User kann Telegram Alerts aus/einschalten

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    # Relationships
    agents = relationship(
        "SearchAgent", back_populates="user", cascade="all, delete-orphan"
    )

    def set_password(self, password):
        """Hash und speichere Passwort"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Überprüfe Passwort"""
        return check_password_hash(self.password_hash, password)

    def get_alert_limit(self):
        """Gibt Limit basierend auf Plan zurück"""
        limits = {"free": 3, "basic": 10, "pro": 30, "team": 100}
        return limits.get(self.plan, 3)

    def can_create_agent(self):
        """Prüft ob User noch Agenten erstellen kann"""
        return len(self.agents) < self.get_alert_limit()

    def __repr__(self):
        return f"<User {self.email} ({self.plan})>"


class SearchAgent(Base):
    __tablename__ = "search_agents"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Suchparameter
    name = Column(String(255), nullable=False)  # User-defined Name
    keywords = Column(Text, nullable=False)
    category = Column(String(100), nullable=True)
    min_price = Column(Integer, nullable=True)
    max_price = Column(Integer, nullable=True)
    condition = Column(String(50), nullable=True)  # new, used, etc.

    # Alert Settings
    check_interval = Column(Integer, default=60)  # Minuten
    notify_email = Column(Boolean, default=True)
    notify_telegram = Column(Boolean, default=True)

    # Status
    is_active = Column(Boolean, default=True)
    last_check = Column(DateTime, nullable=True)
    last_result_count = Column(Integer, default=0)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="agents")
    results = relationship(
        "SearchResult", back_populates="agent", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<SearchAgent '{self.name}' by User {self.user_id}>"


class SearchResult(Base):
    __tablename__ = "search_results"

    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, ForeignKey("search_agents.id"), nullable=False)

    # eBay Item Info
    item_id = Column(String(255), unique=True, nullable=False, index=True)
    title = Column(Text, nullable=False)
    price = Column(String(50), nullable=True)
    currency = Column(String(10), default="EUR")
    url = Column(Text, nullable=False)
    image_url = Column(Text, nullable=True)
    condition = Column(String(50), nullable=True)
    location = Column(String(255), nullable=True)

    # Notification tracking
    notified_email = Column(Boolean, default=False)
    notified_telegram = Column(Boolean, default=False)

    # Metadata
    found_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    agent = relationship("SearchAgent", back_populates="results")

    def __repr__(self):
        return f"<SearchResult {self.item_id}: {self.title[:30]}>"


# Erstelle alle Tabellen
def init_db():
    """Initialisiert die Datenbank"""
    Base.metadata.create_all(bind=engine)
    print("✅ Datenbank-Tabellen erstellt!")


# Helper Functions
def get_db():
    """Gibt eine DB-Session zurück (für Flask Routes)"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


if __name__ == "__main__":
    # Wenn direkt ausgeführt: Tabellen erstellen
    init_db()
