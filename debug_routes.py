import os
os.chdir("C:/Users/Rafael/Documents/GitHub/Probux")

with open('routes.py', 'rb') as f:
    raw = f.read()
lines = raw.split(b'\r\n')
for i in range(1059, min(1095, len(lines))):
    print(i+1, repr(lines[i]))