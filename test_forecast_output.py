#!/usr/bin/env python
import sys
with open('test_result.txt', 'w') as f:
    f.write("Testing imports...\n")
    
    try:
        from services.price_forecast import (
            get_price_forecast,
            get_forecast_summary,
            calculate_moving_averages,
            forecast_with_linear_regression
        )
        f.write("OK: price_forecast.py imports\n")
    except ImportError as e:
        f.write(f"ERROR: {e}\n")
        sys.exit(1)
    
    try:
        from routes.stats import bp as stats_bp
        f.write("OK: routes/stats.py imports\n")
    except ImportError as e:
        f.write(f"ERROR: {e}\n")
        sys.exit(1)
    
    try:
        from database import get_db, get_placeholder, dict_cursor
        f.write("OK: database.py imports\n")
    except ImportError as e:
        f.write(f"ERROR: {e}\n")
        sys.exit(1)
    
    f.write("\nAll imports successful!\n")
    f.write("Ready for Phase 2.2 ML Forecasting\n")
