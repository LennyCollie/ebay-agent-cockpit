#!/usr/bin/env python
import re

with open('models.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_pattern = """class PriceHistory(Base):
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True)

    # Suchbegriff"""

new_pattern = """class PriceHistory(Base):
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=True, index=True)

    # Suchbegriff"""

if old_pattern in content:
    content = content.replace(old_pattern, new_pattern)
    with open('models.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("[OK] alert_id ForeignKey added to PriceHistory")
else:
    print("[SKIP] Seems alert_id is already present")
