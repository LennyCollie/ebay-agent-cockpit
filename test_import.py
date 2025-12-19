try:
    from services.search_integration import merge_all_marketplaces, filter_invalid_listings
    print('[OK] search_integration Module loaded successfully')
except Exception as e:
    print(f'[ERROR] {e}')

try:
    from services.quoka_scraper import search_quoka
    print('[OK] quoka_scraper Module loaded successfully')
except Exception as e:
    print(f'[ERROR] {e}')
