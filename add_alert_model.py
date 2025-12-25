#!/usr/bin/env python
import re

with open('models.py', 'r', encoding='utf-8') as f:
    content = f.read()

alert_class = '''class Alert(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("model_users.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    keywords = Column(Text, nullable=False)
    category = Column(String(100), nullable=True)
    min_price = Column(Float, nullable=True)
    max_price = Column(Float, nullable=True)
    current_price = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True)
    last_check = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user = relationship("User", backref="alerts")
    price_histories = relationship("PriceHistory", back_populates="alert", cascade="all, delete-orphan")
    price_forecasts = relationship("PriceForecast", back_populates="alert", cascade="all, delete-orphan")
    trend_analyses = relationship("PriceTrendAnalysis", back_populates="alert", cascade="all, delete-orphan")
    def __repr__(self):
        return f"<Alert {self.name} user={self.user_id}>"
'''

pattern = r'(    def __repr__\(self\):\s+return f"<SearchAgent.*?>\"\n)\n\nclass SearchResult\(Base\):'

if "class Alert(" not in content:
    content = re.sub(
        pattern,
        r'\1\n\n' + alert_class + '\n\nclass SearchResult(Base):',
        content,
        flags=re.DOTALL
    )
    with open('models.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("[OK] Alert class added to models.py")
else:
    print("[SKIP] Alert class already exists")
