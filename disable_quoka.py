with open('routes/search.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''    elif src in ("kleinanzeigen", "quoka", "shpock", "marktde"):
        active_sources = [src]
    elif src in ("both", "all"):
        # "Alle Portale" -> eBay + alle weiteren Marktplätze
        active_sources = ["kleinanzeigen", "quoka", "shpock", "marktde"]'''

new = '''    elif src in ("kleinanzeigen", "shpock", "marktde"):
        active_sources = [src]
    elif src == "quoka":
        active_sources = ["kleinanzeigen"]
    elif src in ("both", "all"):
        # "Alle Portale" -> eBay + alle weiteren Marktplätze (ohne Quoka)
        active_sources = ["kleinanzeigen", "shpock", "marktde"]'''

if old in content:
    content = content.replace(old, new)
    with open('routes/search.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('[OK] Quoka deaktiviert in routes/search.py')
else:
    print('[!] Pattern nicht gefunden')
