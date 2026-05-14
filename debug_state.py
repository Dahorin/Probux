#!/usr/bin/env python3
"""Debug - ver estado atual dos arquivos"""
import os
os.chdir("C:/Users/Rafael/Documents/GitHub/Probux")

with open('routes.py', 'r', encoding='utf-8') as f:
    routes = f.read()

# Procurar trechos do webhook
print("=== WEBHOOK AREA ===")
idx = routes.find("if mp_status == 'approved':")
while idx != -1 and idx < len(routes):
    chunk = routes[idx:idx+400]
    print(repr(chunk))
    print("---")
    idx = routes.find("if mp_status == 'approved':", idx+1)
    if idx > 100:
        break

print("\n=== CHECK PAYMENT AREA ===")
idx = routes.find("check_payment")
if idx >= 0:
    print(routes[idx:idx+800])

print("\n=== DELIVER GAMEPASSES AREA ===")
with open('mercadopago_utils.py', 'r', encoding='utf-8') as f:
    mpu = f.read()
idx = mpu.find("delivery_attempted")
if idx >= 0:
    print(repr(mpu[idx-50:idx+400]))

idx = mpu.find("if data and")
while idx != -1:
    print(repr(mpu[idx:idx+80]))
    idx = mpu.find("if data and", idx+1)
    if idx > 5:
        break

print("\n=== MP_PAYMENT CHECKER ===")
idx2 = routes.find("if mp_payment and mp_payment.get('qr_code')")
print(f"Still has qr_code check: {idx2 != -1} (at pos {idx2})")
idx3 = routes.find("if mp_payment:")
print(f"Has simple mp_payment check: {idx3 != -1} (at pos {idx3})")