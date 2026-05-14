#!/usr/bin/env python3
import os
os.chdir("C:/Users/Rafael/Documents/GitHub/Probux")

# ============ CORRECAO 1: isinstance check no data2 ============
with open('mercadopago_utils.py', 'r', encoding='utf-8') as f:
    mpu = f.read()

# Procurar e corrigir
if 'elif data2 and isinstance(data2, dict) and data2.get(' not in mpu and 'elif data2:' in mpu:
    # A linha original pode ter \r\n
    old = "elif data2:\n            _log"
    new = "elif data2 and isinstance(data2, dict):\n            _log"
    if old in mpu:
        mpu = mpu.replace(old, new)
        print("CORRIGIDO: data2 isinstance check")
    else:
        # Tentar com \r\n
        old2 = "elif data2:\r\n            _log"
        if old2 in mpu:
            mpu = mpu.replace(old2, new.replace("\n", "\r\n"))
            print("CORRIGIDO: data2 isinstance check (CRLF)")
        else:
            print("data2 isinstance: nao encontrado, procurando variante...")
            # Procurar linha com data2
            lines = mpu.split('\n')
            for i, line in enumerate(lines):
                if 'elif data2' in line:
                    print(f"  Linha {i+1}: {repr(line)}")
else:
    print("CORRECAO 1: ja aplicada ou nao encontrada")

with open('mercadopago_utils.py', 'w', encoding='utf-8') as f:
    f.write(mpu)

# ============ CORRECAO 2: webhook payment_id fallback ============
with open('routes.py', 'r', encoding='utf-8') as f:
    routes = f.read()

# Verificar como está agora
wh_start = routes.find("def mercadopago_webhook")
wh_area = routes[wh_start:wh_start+3000]

if 'data.get(\'id\') or' in wh_area or 'data.get("id") or' in wh_area:
    print("CORRECAO 2: payment_id fallback ja aplicado")
else:
    # Encontrar a linha exata
    old_line = "payment_id = data.get('data', {}).get('id')"
    new_line = "payment_id = data.get('data', {}).get('id') or data.get('id')"
    if old_line in routes:
        routes = routes.replace(old_line, new_line)
        print("CORRECAO 2: payment_id fallback aplicado")
    else:
        # Procurar com outros formatos
        lines = routes.split('\n')
        for i, line in enumerate(lines):
            if "payment_id = data.get" in line and "id')" in line:
                print(f"  Linha {i+1}: {repr(line)}")

with open('routes.py', 'w', encoding='utf-8') as f:
    f.write(routes)

print("\nFeito!")