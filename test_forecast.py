#!/usr/bin/env python
import sys
print("Testing imports...")

try:
    from services.price_forecast import (
        get_price_forecast,
        get_forecast_summary,
        calculate_moving_averages,
        forecast_with_linear_regression
    )
    print("✓ price_forecast.py imports OK")
except ImportError as e:
    print(f"✗ Import error: {e}")
    sys.exit(1)

try:
    from routes.stats import bp as stats_bp
    print("✓ routes/stats.py imports OK")
except ImportError as e:
    print(f"✗ Import error: {e}")
    sys.exit(1)

try:
    from database import get_db, get_placeholder, dict_cursor
    print("✓ database.py imports OK")
except ImportError as e:
    print(f"✗ Import error: {e}")
    sys.exit(1)

print("\n✓ All imports successful!")
print("\nNow run: python app.py")
