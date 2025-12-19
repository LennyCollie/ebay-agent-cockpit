with open('services/quoka_scraper.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = """    job_keywords = ['job gesucht', 'minijob', 'nebenjob', 'stellengesuche', 'arbeit gesucht', 'reinigungskraft', 'zaunmonteur', 'alltagshelfer', 'kinderbetreuung']
    for kw in job_keywords:
        if kw in title:
            return True"""

new = """    job_keywords = ['job', 'minijob', 'nebenjob', 'stelle', 'arbeit', 'beschaeftigung', 'reinigung', 'zaunmonteur', 'alltagshelfer', 'kinderbetreuung', 'hausmeister', 'pflegedienstleiter', 'komplettservice', 'umzug', 'garten', 'haushaltshelfer', 'lieferunternehmen', 'suche', 'gesucht', 'ich suche']
    for kw in job_keywords:
        if kw in title:
            return True"""

if old in content:
    content = content.replace(old, new)
    with open('services/quoka_scraper.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('[OK] Expanded job keywords filter')
else:
    print('[!] Old pattern not found - checking content')
    if 'job_keywords' in content:
        print('[*] job_keywords exists in file')
