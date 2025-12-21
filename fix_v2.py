with open('services/price_tracker.py', 'r') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if i == 65 and 'price, price' in line:
        lines[i] = line.rstrip() + ', price\n'

with open('services/price_tracker.py', 'w') as f:
    f.writelines(lines)

print("Fixed line 66")
