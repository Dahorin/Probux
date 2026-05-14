#!/usr/bin/env python3
import os
os.chdir("C:/Users/Rafael/Documents/GitHub/Probux")

with open('routes.py', 'r', encoding='utf-8') as f:
    routes = f.read()

# Encontrar check_payment area em detalhes
idx = routes.find("def check_payment")
if idx >= 0:
    chunk = routes[idx:idx+1200]
    # Print com numeração de linhas
    for i, line in enumerate(chunk.split('\n')):
        print(f"{idx//80 + i}: {repr(line)}")

print("\n\n=== MERCADOPAGO_UTILS - buy_gamepass ===")
with open('mercadopago_utils.py', 'r', encoding='utf-8') as f:
    mpu = f.read()
idx2 = mpu.find("def buy_gamepass_with_cookie")
if idx2 >= 0:
    chunk = mpu[idx2:idx2+600]
    for i, line in enumerate(chunk.split('\n')):
        print(f"{idx2//80 + i}: {repr(line)}")

print("\n\n=== MERCADOPAGO_UTILS - deliver_gamepasses ===")
idx3 = mpu.find("def deliver_gamepasses")
if idx3 >= 0:
    chunk = mpu[idx3:idx3+500]
    for i, line in enumerate(chunk.split('\n')):
        print(f"{idx3//80 + i}: {repr(line)}")