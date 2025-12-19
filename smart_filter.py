with open('services/quoka_scraper.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = """    job_keywords = ['job', 'minijob', 'nebenjob', 'stelle', 'arbeit', 'beschaeftigung', 'reinigung', 'zaunmonteur', 'alltagshelfer', 'kinderbetreuung', 'hausmeister', 'pflegedienstleiter', 'komplettservice', 'umzug', 'garten', 'haushaltshelfer', 'lieferunternehmen', 'suche', 'gesucht', 'ich suche']
    for kw in job_keywords:
        if kw in title:
            return True"""

new = """    if len(title) < 40:
        job_phrases = ['job gesucht', 'stelle gesucht', 'arbeit gesucht', 'minijob', 'nebenjob', 'ich suche', 'suche stelle', 'suche arbeit', 'stellengesuche', 'hilfe bei', 'komplettservice']
        for phrase in job_phrases:
            if phrase in title:
                return True"""

if old in content:
    content = content.replace(old, new)
    with open('services/quoka_scraper.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('[OK] Reverted to smart filter - only short listings with obvious job phrases')
else:
    print('[!] Pattern not found')
