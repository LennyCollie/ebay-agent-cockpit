from services.search_integration import filter_invalid_listings

test_items = [
    {'title': 'iPhone 12 Pro Max 128GB', 'description': 'Sehr guter Zustand', 'url': 'https://quoka.de/item1'},
    {'title': 'iPhone 12 gebraucht', 'description': 'Mit Zubehör', 'url': 'https://quoka.de/item2'},
    {'title': 'Zuhause', 'description': 'Navigation', 'url': 'https://quoka.de/nav'},
]

print('[*] TEST: filter_invalid_listings mit source=quoka')
result = filter_invalid_listings(test_items, term='iPhone 12', source='quoka')
print(f'[OK] Input: 3 items | Output: {len(result)} items')
for item in result:
    print(f'  - {item["title"][:50]}')

print('\n[*] TEST: filter_invalid_listings mit source=ebay (alte Logik)')
result_ebay = filter_invalid_listings(test_items, term='iPhone 12', source='ebay')
print(f'[OK] Input: 3 items | Output: {len(result_ebay)} items')
for item in result_ebay:
    print(f'  - {item["title"][:50]}')
