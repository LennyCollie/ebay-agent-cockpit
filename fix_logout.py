#!/usr/bin/env python
import os

filepath = 'app.py'

with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

old = 'return redirect(url_for("public_home"))'
new = 'return redirect(url_for("login"))'

if old in content:
    content = content.replace(old, new)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Fixed: replaced logout redirect")
else:
    print(f"Error: Could not find logout redirect in file")
