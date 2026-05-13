#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Teste direto de compra de gamepass usando as funcoes do mercadopago_utils"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import mercadopago_utils as mp

cookie = os.getenv('ROBLOX_COOKIE', '')
print(f'Cookie carregado: {"SIM" if cookie else "NAO"} - {len(cookie)} chars')

if not cookie:
    print('ERRO: Configure ROBLOX_COOKIE no .env')
    exit(1)

print('\n=== TESTE DE CONEXAO COM O ROBLOX ===')

# Teste 1: Verificar cookie
print('\n1. Verificando cookie...')
is_valid, error = mp.verify_roblox_cookie(cookie)
if is_valid:
    print(f'   Cookie VALIDO!')
else:
    print(f'   Cookie INVALIDO: {error}')
    print('\n   COMO CORRIGIR:')
    print('   1. Acesse https://www.roblox.com no navegador')
    print('   2. Faça login na conta')
    print('   3. Abra o console (F12) -> Console -> digite: document.cookie')
    print('   4. Copie o valor de .ROBLOSECURITY')
    print('   5. Cole no .env como ROBLOX_COOKIE')
    exit(1)

# Teste 2: Criar sessao e verificar XSRF
print('\n2. Testando obtencao de XSRF token...')
session = mp._create_session(cookie)
xsrf = mp._get_xsrf_token(session)
if xsrf:
    print(f'   XSRF Token obtido: OK')
else:
    print(f'   XSRF Token: FALHOU (possivel bloqueio de IP)')

# Teste 3: API v2 - usuario autenticado
print('\n3. Testando API v2 (usuario autenticado)...')
try:
    resp = session.get('https://users.roblox.com/v1/users/authenticated', timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        print(f'   OK - Usuario: {data.get("name")} (ID: {data.get("id")})')
    else:
        print(f'   FALHOU - Status: {resp.status_code}')
except Exception as e:
    print(f'   FALHOU - {e}')

# Teste 4: API Economy v1 (saldo)
print('\n4. Testando API Economy v1 (saldo)...')
try:
    resp = session.get('https://economy.roblox.com/v1/user/currency', timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        print(f'   OK - Saldo: {data.get("robux")} Robux')
    else:
        print(f'   FALHOU - Status: {resp.status_code}')
except Exception as e:
    print(f'   FALHOU - {e}')

# Teste 5: Catalog API
print('\n5. Testando Catalog API...')
try:
    resp = session.post(
        'https://catalog.roblox.com/v1/catalog/items/details',
        json={'items': [{'id': 1, 'itemType': 'GamePass'}]},
        timeout=10
    )
    if resp.status_code == 200:
        print(f'   OK - Catalogo acessivel')
    else:
        print(f'   FALHOU - Status: {resp.status_code}')
except Exception as e:
    print(f'   FALHOU - {e}')

# Teste 6: Purchase API (verificar endpoint correto)
print('\n6. Testando Purchase API...')

# Tentar o endpoint V1 principal
for endpoint in [
    '/v1/purchases/game-pass/1',           # Endpoint atual
    '/marketplace/game-pass/1',             # Endpoint alternativo
    '/v1/purchases/game-pass/1/complete',   # Endpoint completo
]:
    print(f'   Tentando: https://api.roblox.com{endpoint} ...')
    try:
        resp = session.post(
            f'https://api.roblox.com{endpoint}',
            json={'expectedPrice': 1} if not endpoint.endswith('/complete') else {},
            timeout=15
        )
        # Qualquer resposta 400+ que nao seja 403/timeout indica que o endpoint existe
        if resp.status_code in [400, 401, 403, 412, 422, 429]:
            data = resp.json() if resp.headers.get('content-type', '').startswith('application/json') else {}
            error_msg = data.get('error', {}).get('message', str(data)) if 'error' in data else resp.text[:200]
            print(f'   ✓ Endpoint ENCONTRADO! Status: {resp.status_code}')
            print(f'     Resposta: {error_msg[:150]}')
            break
        elif resp.status_code == 200:
            print(f'   ✓ Endpoint FUNCIONOU! Status: 200')
            print(f'     Resposta: {resp.text[:200]}')
            break
        else:
            print(f'   ✗ Status {resp.status_code}')
    except Exception as e:
        print(f'   Erro: {str(e)[:100]}')

# Teste final: Tenta compra real de uma gamepass publica conhecida
print('\n=== TESTE DE COMPRA REAL ===')
print('ATENCAO: Isso vai tentar comprar uma gamepass REAL se tiver Robux!')
gamepass_id = os.getenv('TEST_GAMEPASS_ID', '12345678')
expected_price = int(os.getenv('TEST_GAMEPASS_PRICE', '1'))

if gamepass_id == '12345678':
    print('   NENHUM TESTE CONFIGURADO (edite .env: TEST_GAMEPASS_ID e TEST_GAMEPASS_PRICE)')
    print('\n=== TESTE CONCLUIDO ===')
    exit(0)

print(f'   Gamepass ID: {gamepass_id}')
print(f'   Preco esperado: {expected_price} Robux')

success, msg = mp.buy_gamepass_with_cookie(
    f'https://www.roblox.com/game-pass/{gamepass_id}',
    cookie,
    expected_price
)

if success:
    print(f'\n   ✅ SUCESSO: {msg}')
else:
    print(f'\n   ❌ FALHA: {msg}')

print('\n=== TESTE CONCLUIDO ===')
