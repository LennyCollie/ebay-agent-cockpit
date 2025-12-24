# models.py – DIE FINALE, FUNKTIONIERENDE VERSION

import os
from datetime import datetime
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from werkzeug.security import check_password_hash, generate_password_hash

# === DAS FEHLTE BEI DIR!!! ===
from flask_login import UserMixin     # ← OHNE DIESE ZEILE: KEIN is_authenticated!!!

# DB Connection
from pathlib import Path

DB_PATH = Path("instance/db.sqlite3")
DB_PATH.parent.mkdir(exist_ok=True, parents=True)
DB_URL = f"sqlite:///{DB_PATH}"
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

# === JETZT RICHTIG: UserMixin + Base ===
class User(UserMixin, Base):          # ← DAS WAR’S!!! DAS WAR DER LETZTE BUG!!!
    __tablename__ = "model_users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=True)
    # ... alles andere bleibt 100 % gleich ...

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


    def is_active(self):
        return self.is_active  # oder einfach: return True

    def is_anonymous(self):
        return False

    def get_id(self):
        return str(self.id)

        def get_id(self):
            return str(self.id)

    def is_active(self):
        return self.is_active  # oder einfach: return True

    def is_anonymous(self):
        return False

    def is_authenticated(self):
        return True


class SearchAgent(Base):
    __tablename__ = "search_agents"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("model_users.id"), nullable=False)

    # NEU: Erweiterte Filter
    listing_type = Column(
        String(20), default="all"
    )  # all, auction, buy_it_now, auction_with_bin
    location_country = Column(String(10), default="DE")  # DE, AT, CH, etc.
    max_distance_km = Column(Integer, nullable=True)  # z.B. 50, 100, 200
    zip_code = Column(String(10), nullable=True)  # Für Umkreissuche

    free_shipping_only = Column(Boolean, default=False)
    returns_accepted = Column(Boolean, default=False)
    top_rated_seller_only = Column(Boolean, default=False)
    exclude_international = Column(Boolean, default=False)

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


class WatchedItem(Base):
    __tablename__ = "watched_items"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("model_users.id"), nullable=False)

    # eBay Item Info
    ebay_item_id = Column(String(255), nullable=False, index=True)
    item_title = Column(Text, nullable=False)
    item_url = Column(Text, nullable=False)
    image_url = Column(Text, nullable=True)

    # Preis-Tracking
    initial_price = Column(String(50))
    current_price = Column(String(50))
    currency = Column(String(10), default="EUR")
    lowest_price = Column(String(50), nullable=True)

    # Notification Settings
    notify_price_drop = Column(Boolean, default=True)
    notify_auction_ending = Column(Boolean, default=True)
    price_drop_threshold = Column(Integer, default=5)  # % Preissenkung

    # Status
    is_active = Column(Boolean, default=True)
    item_status = Column(String(20), default="active")  # active, ended, unavailable

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    last_checked = Column(DateTime, default=datetime.utcnow)
    last_notified = Column(DateTime, nullable=True)

    # Relationship
    user = relationship("User", backref="watched_items")

    def __repr__(self):
        return f"<WatchedItem {self.ebay_item_id}: {self.item_title[:30]}>"


class PriceHistory(Base):
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True)

    # Suchbegriff
    search_term = Column(String(255), nullable=False, index=True)
    category = Column(String(100), nullable=True)

    # Preis-Statistiken
    avg_price = Column(Float, nullable=False)
    min_price = Column(Float, nullable=False)
    max_price = Column(Float, nullable=False)
    median_price = Column(Float, nullable=True)

    # Metadata
    item_count = Column(Integer, default=0)
    condition = Column(String(50), nullable=True)  # NEW, USED, etc.

    # Zeitstempel
    recorded_at = Column(DateTime, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f"<PriceHistory '{self.search_term}' @ {self.recorded_at.strftime('%Y-%m-%d')}>"


class ItemPriceTracking(Base):
    __tablename__ = "item_price_tracking"

    id = Column(Integer, primary_key=True)
    watched_item_id = Column(Integer, ForeignKey("watched_items.id"), nullable=False)

    price = Column(Float, nullable=False)
    currency = Column(String(10), default="EUR")

    # Status
    item_available = Column(Boolean, default=True)
    bid_count = Column(Integer, default=0)  # Bei Auktionen

    recorded_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Relationship
    watched_item = relationship("WatchedItem", backref="price_snapshots")

    def __repr__(self):
        return f"<ItemPriceTracking {self.watched_item_id}: {self.price} @ {self.recorded_at}>"


# Erstelle alle Tabellen
def init_db():
    """Initialisiert die Datenbank"""
    Base.metadata.create_all(bind=engine)
    print("[OK] Datenbank-Tabellen erstellt!")


try:
    Base.metadata.create_all(bind=engine)
    print("[OK] models.py: Tabellen initialisiert")
except Exception as e:
    print(f"[models] Fehler beim Erstellen der Tabellen: {e}")



# Helper Functions
def get_db_session():
    """Gibt eine DB-Session zurück (für Flask Routes) - GENERATOR für use in with Statements"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db():
    """Gibt eine neue SQLAlchemy Session direkt zurück (kein Generator)"""
    return SessionLocal()


    # In models.py - am Ende einfügen

class NotificationSettings(Base):
    __tablename__ = "notification_settings"

    user_id = Column(Integer, ForeignKey("model_users.id"), primary_key=True)

    # Zeitfenster (Ruhezeiten)
    quiet_hours_enabled = Column(Boolean, default=False)
    quiet_hours_start = Column(String(5), default="22:00")  # HH:MM
    quiet_hours_end = Column(String(5), default="08:00")

    # Frequenz-Limits
    max_notifications_per_day = Column(Integer, default=50)
    max_notifications_per_hour = Column(Integer, default=10)
    batch_notifications = Column(Boolean, default=False)  # Sammeln & 1x/Tag senden
    batch_time = Column(String(5), default="09:00")  # Wann Batch senden

    # Kanäle
    email_enabled = Column(Boolean, default=True)
    telegram_enabled = Column(Boolean, default=True)
    sms_enabled = Column(Boolean, default=False)  # Premium-Feature

    # Prioritäten
    only_high_priority = Column(Boolean, default=False)  # Nur wichtige Alerts
    min_price_drop_percent = Column(Integer, default=5)  # Min. X% Preissenkung

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    user = relationship("User", backref="notification_settings")


class NotificationLog(Base):
    __tablename__ = "notification_log"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("model_users.id"), nullable=False)

    # Notification Details
    notification_type = Column(String(50), nullable=False)  # price_drop, new_item, auction_ending, etc.
    channel = Column(String(20), nullable=False)  # email, telegram, sms

    subject = Column(String(255))
    content = Column(Text)

    # Item Reference (optional)
    watched_item_id = Column(Integer, ForeignKey("watched_items.id"), nullable=True)
    agent_id = Column(Integer, ForeignKey("search_agents.id"), nullable=True)

    # Status
    status = Column(String(20), default="pending")  # pending, sent, failed, skipped
    sent_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Relationships
    user = relationship("User")
    watched_item = relationship("WatchedItem")
    agent = relationship("SearchAgent")


    # --- safe fallback / stub für sync_user_from_app ---
# Füge das am Ende von models.py ein, falls die Funktion fehlt.
from typing import Optional

def sync_user_from_app(session, app_user_id: Optional[int] = None, email: Optional[str] = None):
    """
    Minimaler Fallback: versucht, einen User anhand email/app_user_id zu finden.
    - session: entweder SessionLocal() Factory oder eine bereits geöffnete Session
    Gibt ein User-Objekt zurück oder ein Dummy-Objekt mit id/email Attributen.
    Passe die Implementierung an dein User-Model an.
    """
    created_session = False
    db = None
    try:
        # Wenn session eine Factory ist (SessionLocal), rufe sie auf
        if callable(session):
            db = session()
            created_session = True
        else:
            db = session
    except Exception:
        db = None

    try:
        if db is not None and email:
            # Versuche echten User aus DB zu holen — passe User-Attribute an
            try:
                user_obj = db.query(User).filter(User.email == email).first()
                if user_obj:
                    return user_obj
            except Exception:
                # falls ORM/Model anders ist, safe fallback
                pass

        # Wenn kein DB-User gefunden: gib ein einfaches Dummy-Objekt zurück
        TmpUser = type("TmpUser", (), {"id": app_user_id or None, "email": email})
        return TmpUser
    finally:
        if created_session and db is not None:
            try:
                db.close()
            except Exception:
                pass



class AffiliateAccount(Base):
    __tablename__ = "affiliate_accounts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("model_users.id"), nullable=False, unique=True)
    
    referral_code = Column(String(50), unique=True, nullable=False, index=True)
    referral_url = Column(Text, nullable=False)
    
    total_clicks = Column(Integer, default=0)
    total_conversions = Column(Integer, default=0)
    total_earnings = Column(Float, default=0.0)
    
    commission_rate = Column(Float, default=0.15)
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("User", backref="affiliate_account")
    referral_clicks = relationship("AffiliateClick", back_populates="affiliate", cascade="all, delete-orphan")
    referral_conversions = relationship("AffiliateConversion", back_populates="affiliate", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<AffiliateAccount {self.referral_code}>"


class AffiliateClick(Base):
    __tablename__ = "affiliate_clicks"

    id = Column(Integer, primary_key=True)
    affiliate_id = Column(Integer, ForeignKey("affiliate_accounts.id"), nullable=False)
    
    referrer_ip = Column(String(50), nullable=True)
    referrer_url = Column(Text, nullable=True)
    user_agent = Column(Text, nullable=True)
    
    converted = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    affiliate = relationship("AffiliateAccount", back_populates="referral_clicks")

    def __repr__(self):
        return f"<AffiliateClick {self.affiliate_id} @ {self.created_at}>"


class AffiliateConversion(Base):
    __tablename__ = "affiliate_conversions"

    id = Column(Integer, primary_key=True)
    affiliate_id = Column(Integer, ForeignKey("affiliate_accounts.id"), nullable=False)
    click_id = Column(Integer, ForeignKey("affiliate_clicks.id"), nullable=True)
    
    converted_user_id = Column(Integer, ForeignKey("model_users.id"), nullable=True)
    
    conversion_type = Column(String(50), default="signup")
    commission_amount = Column(Float, default=0.0)
    
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    affiliate = relationship("AffiliateAccount", back_populates="referral_conversions")
    click = relationship("AffiliateClick")
    converted_user = relationship("User")

    def __repr__(self):
        return f"<AffiliateConversion {self.affiliate_id}>"


class CommunityLink(Base):
    __tablename__ = "community_links"

    id = Column(Integer, primary_key=True)
    
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    url = Column(Text, nullable=False)
    
    category = Column(String(50), nullable=False)
    icon = Column(String(50), nullable=True)
    
    is_featured = Column(Boolean, default=False)
    display_order = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<CommunityLink '{self.title}'>"


class NewsletterSubscriber(Base):
    __tablename__ = "newsletter_subscribers"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    verified = Column(Boolean, default=False)
    verification_token = Column(String(255), nullable=True, unique=True)
    is_active = Column(Boolean, default=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    verified_at = Column(DateTime, nullable=True)
    unsubscribed_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<NewsletterSubscriber {self.email}>"


class Coupon(Base):
    __tablename__ = "coupons"

    id = Column(Integer, primary_key=True)
    
    code = Column(String(50), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    
    amount = Column(Float, nullable=False)
    discount_type = Column(String(20), default="fixed")
    
    is_affiliate = Column(Boolean, default=False)
    affiliate_conversion_id = Column(Integer, ForeignKey("affiliate_conversions.id"), nullable=True)
    
    user_id = Column(Integer, ForeignKey("model_users.id"), nullable=True)
    
    usage_limit = Column(Integer, nullable=True)
    used_count = Column(Integer, default=0)
    
    valid_from = Column(DateTime, default=datetime.utcnow)
    valid_until = Column(DateTime, nullable=True)
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("User", backref="coupons")
    affiliate_conversion = relationship("AffiliateConversion")
    usages = relationship("CouponUsage", back_populates="coupon", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Coupon {self.code}>"
    
    def is_valid(self):
        """Check if coupon is still valid and can be used"""
        now = datetime.utcnow()
        if not self.is_active:
            return False
        if self.valid_until and now > self.valid_until:
            return False
        if self.valid_from and now < self.valid_from:
            return False
        if self.usage_limit and self.used_count >= self.usage_limit:
            return False
        return True


class CouponUsage(Base):
    __tablename__ = "coupon_usages"

    id = Column(Integer, primary_key=True)
    coupon_id = Column(Integer, ForeignKey("coupons.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("model_users.id"), nullable=False)
    
    applied_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    coupon = relationship("Coupon", back_populates="usages")
    user = relationship("User", backref="coupon_usages")

    def __repr__(self):
        return f"<CouponUsage {self.coupon_id} by User {self.user_id}>"


class AnalyticsSnapshot(Base):
    __tablename__ = "analytics_snapshots"

    id = Column(Integer, primary_key=True)
    
    snapshot_date = Column(DateTime, default=datetime.utcnow, index=True)
    
    total_users = Column(Integer, default=0)
    total_premium_users = Column(Integer, default=0)
    total_basic_users = Column(Integer, default=0)
    total_pro_users = Column(Integer, default=0)
    total_team_users = Column(Integer, default=0)
    
    new_signups = Column(Integer, default=0)
    churned_users = Column(Integer, default=0)
    
    affiliate_clicks = Column(Integer, default=0)
    affiliate_conversions = Column(Integer, default=0)
    affiliate_earnings = Column(Float, default=0.0)
    
    coupons_created = Column(Integer, default=0)
    coupons_redeemed = Column(Integer, default=0)
    coupons_total_value = Column(Float, default=0.0)
    
    agents_created = Column(Integer, default=0)
    agents_active = Column(Integer, default=0)
    alerts_triggered = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<AnalyticsSnapshot {self.snapshot_date.strftime('%Y-%m-%d')}>"


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("model_users.id"), nullable=True)
    
    event_type = Column(String(50), nullable=False, index=True)
    event_name = Column(String(255), nullable=False)
    
    event_data = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    user = relationship("User", backref="analytics_events")

    def __repr__(self):
        return f"<AnalyticsEvent {self.event_type}:{self.event_name}>"


class Achievement(Base):
    __tablename__ = "achievements"

    id = Column(Integer, primary_key=True)
    
    code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    icon = Column(String(100), nullable=True)
    
    category = Column(String(50), nullable=False)
    points = Column(Integer, default=10)
    
    trigger_type = Column(String(50), nullable=False)
    trigger_condition = Column(String(255), nullable=False)
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user_badges = relationship("UserBadge", back_populates="achievement", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Achievement {self.code}>"


class UserBadge(Base):
    __tablename__ = "user_badges"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("model_users.id"), nullable=False, index=True)
    achievement_id = Column(Integer, ForeignKey("achievements.id"), nullable=False)
    
    earned_at = Column(DateTime, default=datetime.utcnow, index=True)
    is_public = Column(Boolean, default=True)
    
    achievement = relationship("Achievement", back_populates="user_badges")
    user = relationship("User", backref="badges")

    def __repr__(self):
        return f"<UserBadge user={self.user_id} achievement={self.achievement_id}>"


class UserEngagement(Base):
    __tablename__ = "user_engagement"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("model_users.id"), nullable=False, unique=True)
    
    login_streak = Column(Integer, default=0)
    last_login = Column(DateTime, nullable=True)
    
    searches_count = Column(Integer, default=0)
    agents_created = Column(Integer, default=0)
    alerts_triggered = Column(Integer, default=0)
    
    affiliate_clicks = Column(Integer, default=0)
    affiliate_conversions = Column(Integer, default=0)
    
    coupons_applied = Column(Integer, default=0)
    coupons_created = Column(Integer, default=0)
    
    total_points = Column(Integer, default=0)
    tier = Column(String(50), default="bronze")
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("User", backref="engagement", uselist=False)

    def __repr__(self):
        return f"<UserEngagement user={self.user_id} tier={self.tier}>"


class LeaderboardSnapshot(Base):
    __tablename__ = "leaderboard_snapshots"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("model_users.id"), nullable=False)
    
    period = Column(String(20), nullable=False)
    rank = Column(Integer, nullable=True)
    points = Column(Integer, default=0)
    metric_value = Column(Integer, default=0)
    metric_type = Column(String(50), nullable=False)
    
    snapshot_date = Column(DateTime, default=datetime.utcnow, index=True)
    
    user = relationship("User", backref="leaderboard_snapshots")

    def __repr__(self):
        return f"<LeaderboardSnapshot user={self.user_id} period={self.period}>"


if __name__ == "__main__":
    # Wenn direkt ausgeführt: Tabellen erstellen
    init_db()
