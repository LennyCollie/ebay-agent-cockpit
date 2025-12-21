import re

with open('services/price_tracker.py', 'r') as f:
    content = f.read()

old_code = '''        if get_placeholder() == "%s":
            cur.execute(f"""
                INSERT INTO item_price_history 
                (item_hash, item_title, price_current, price_min, price_max, portal)
                VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                ON CONFLICT (item_hash) DO UPDATE SET
                    price_current = {ph},
                    price_min = LEAST(item_price_history.price_min, {ph}),
                    price_max = GREATEST(item_price_history.price_max, {ph})
            """, (
                item_hash, 
                item.get('title', '')[:255],
                price, price, price,
                item.get('source', 'unknown'),
                price, price
            ))'''

new_code = '''        if get_placeholder() == "%s":
            cur.execute(f"""
                INSERT INTO item_price_history 
                (item_hash, item_title, price_current, price_min, price_max, portal)
                VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                ON CONFLICT (item_hash) DO UPDATE SET
                    price_current = {ph},
                    price_min = LEAST(item_price_history.price_min, {ph}),
                    price_max = GREATEST(item_price_history.price_max, {ph})
            """, (
                item_hash, 
                item.get('title', '')[:255],
                price, price, price,
                item.get('source', 'unknown'),
                price, price, price
            ))'''

content = content.replace(old_code, new_code)

with open('services/price_tracker.py', 'w') as f:
    f.write(content)

print("Fixed: Added missing price parameter for DO UPDATE clause")
