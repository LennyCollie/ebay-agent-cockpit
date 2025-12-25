#!/usr/bin/env python
import re

with open('models.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Add alert_id to PriceHistory if it doesn't exist
if 'class PriceHistory(Base):' in content and 'alert_id' not in content[content.find('class PriceHistory(Base):'):content.find('class ItemPriceTracking(Base):')]:
    # Find the line with "recorded_at" in PriceHistory and add alert_id before it
    price_history_section = content[content.find('class PriceHistory(Base):'):content.find('def __repr__(self):')]
    
    new_section = price_history_section.replace(
        '    # Zeitstempel\n    recorded_at',
        '    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=True, index=True)\n    \n    # Zeitstempel\n    recorded_at'
    )
    
    content = content.replace(price_history_section, new_section)
    
    # Add relationship to PriceHistory
    repr_line = '    def __repr__(self):\n        return f"<PriceHistory'
    price_history_end = content.find(repr_line, content.find('class PriceHistory(Base):'))
    
    # Add alert relationship before __repr__
    alert_rel = '    alert = relationship("Alert", back_populates="price_histories")\n    \n'
    content = content[:price_history_end] + alert_rel + content[price_history_end:]
    
    with open('models.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("[OK] alert_id added to PriceHistory")
else:
    print("[SKIP] alert_id already in PriceHistory or class not found")
