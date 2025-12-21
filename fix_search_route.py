#!/usr/bin/env python
import subprocess
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

result = subprocess.run(['git', 'show', 'HEAD:routes/search.py'], capture_output=True, text=True)

if result.returncode != 0:
    print(f"Git error: {result.stderr}")
    exit(1)

original_content = result.stdout

lines = original_content.split('\n')
new_lines = []
found_except_block = False
inserted = False

for i, line in enumerate(lines):
    new_lines.append(line)
    
    if not inserted and 'exc_info=True,' in line and i < len(lines) - 5:
        new_lines.append(line[:len(line) - len(line.lstrip())] + ')')
        new_lines.append('')
        new_lines.append(line[:len(line) - len(line.lstrip())] + 'for item in items:')
        new_lines.append(line[:len(line) - len(line.lstrip())] + '    try:')
        new_lines.append(line[:len(line) - len(line.lstrip())] + '        track_item_price(item)')
        new_lines.append(line[:len(line) - len(line.lstrip())] + '    except Exception as e:')
        new_lines.append(line[:len(line) - len(line.lstrip())] + '        current_app.logger.debug("[Price Track Error] %s", e)')
        new_lines.append('')
        inserted = True
        skip_count = 0
        for j in range(i+1, min(i+5, len(lines))):
            if ')' in lines[j] and 'current_app.logger.debug' not in lines[j]:
                skip_count = j - i
                break

with open('routes/search.py', 'w', encoding='utf-8') as f:
    f.write('\n'.join(new_lines))

print("Fixed routes/search.py")
