#!/usr/bin/env python3
import ast
import sys

files_to_check = [
    'app.py',
    'models.py',
    'routes/admin.py'
]

errors = []
for filepath in files_to_check:
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            code = f.read()
        ast.parse(code)
        print(f"✓ {filepath} - OK")
    except SyntaxError as e:
        errors.append(f"✗ {filepath} - Line {e.lineno}: {e.msg}")
        print(f"✗ {filepath} - Line {e.lineno}: {e.msg}")
    except Exception as e:
        errors.append(f"✗ {filepath} - {str(e)}")
        print(f"✗ {filepath} - {str(e)}")

if errors:
    print("\n❌ Fehler gefunden:")
    for error in errors:
        print(f"  {error}")
    sys.exit(1)
else:
    print("\n✓ Alle Dateien OK")
    sys.exit(0)
