#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Teste direto de compra de gamepass"""
import os
import re
import requests
from dotenv import load_dotenv

load_dotenv()

cookie = os.getenv('ROBLOX_COOKIE', '')
print(f'Cookie carregado: {"SIM" if cookie else "NAO"} - {len(cookie)} chars')

if not cookie:
    print('ERRO: Configure ROBLOX_COOKIE no .env')
    exit(1)

# Cria sessao
s = requests.Session()
s.cookies.set('.ROBLOSECURITY', cookie, domain='.roblox.com')
s.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json',
    'Content-Type': 'application/json',
})

# Obtem XSRF token
print('\nObtendo XSRF token...')
try:
    r = s.post('https://auth.roblox.com/v2/logout', json={}, timeout=10)
    xsrf = r.headers.get('X-CSRF-TOKEN')
    if xsrf:
        s.headers['X-CSRF-TOKEN'] = xsrf
        print(f'XSRF Token obtido: {xsrf[:30]}...')
    else:
        print(f'Falha ao obter XSRF. Status: {r.status_code}')
        exit(1)
except Exception as e:
    print(f'Erro: {e}')
    exit(1)

# Testa com uma gamepass real
print('\n=== TESTE DE COMPRA DE GAMEPASS ===')
print('ATENCAO: Isso vai tentar comprar uma gamepass real se tiver Robux!')
print('Edite este script e coloque um ID valido abaixo.\n')

# COLOQUE UM ID REAL DE GAMEPASS PUBLICA AQUI:
gamepass_id = '12345678'  # SUBSTITUA pelo ID real da gamepass do pedido 13
expected_price = 10  # SUBSTITUA pelo preco real em Robux

print(f'Gamepass ID: {gamepass_id}')
print(f'Preco esperado: {expected_price} Robux')

if gamepass_id == '12345678':
    print('\nERRO: Voce precisa editar este script e colocar um ID real!')
    print('1. Acesse a gamepass no Roblox')
    print('2. Copie o ID da URL (ex: roblox.com/game-pass/12345678)')
    print('3. Edite a linha 42 deste script')
    exit(1)

# Verifica se a gamepass existe e esta publica
print('\nVerificando se a gamepass existe...')
gamepass_url = f'https://www.roblox.com/game-pass/{gamepass_id}'
try:
    r = s.get(gamepass_url, timeout=10)
    print(f'Status: {r.status_code}')
    if r.status_code == 200:
        print('Gamepass acessivel!')
    elif r.status_code == 404:
        print('ERRO: Gamepass nao encontrada (404)')
        exit(1)
except Exception as e:
    print(f'Erro: {e}')

# Tenta comprar
print('\nTentando comprar a gamepass...')
purchase_url = f'https://api.roblox.com/v1/purchases/game-pass/{gamepass_id}/purchase'
payload = {'expectedPrice': int(expected_price)}

try:
    resp = s.post(purchase_url, json=payload, timeout=15)
    print(f'Status da compra: {resp.status_code}')
    print(f'Resposta: {resp.text[:500]}')

    if resp.status_code == 200:
        try:
            data = resp.json()
            if data.get('success'):
                print('\nSUCESSO: Gamepass comprada!')
            else:
                print(f'\nFALHA: {data.get("error", "Erro desconhecido")}')
        except:
            print(f'\nResposta invalida: {resp.text[:200]}')
    elif resp.status_code == 403:
        print('\nFALHA: Acesso negado. Cookie invalido ou Robux insuficiente.')
    elif resp.status_code == 400:
        print(f'\nFALHA (400): {resp.text[:300]}')
    else:
        print(f'\nFALHA: Status {resp.status_code}')
except Exception as e:
    print(f'Erro: {e}')

print('\n=== TESTE CONCLUIDO ===')
