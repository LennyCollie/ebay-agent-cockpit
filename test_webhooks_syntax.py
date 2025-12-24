#!/usr/bin/env python3

import sys
import py_compile

files = [
    'models.py',
    'services/webhook.py',
    'routes/webhooks.py',
    'app.py'
]

errors = []
for file in files:
    try:
        py_compile.compile(file, doraise=True)
        print(f"✓ {file}")
    except py_compile.PyCompileError as e:
        print(f"✗ {file}")
        errors.append(str(e))

if errors:
    print("\n=== ERRORS ===")
    for error in errors:
        print(error)
    sys.exit(1)
else:
    print("\n✓ All files passed syntax check")
    sys.exit(0)
