#!/usr/bin/env python3
"""Ajusta _proxy_request para enviar cookie via header HTTP (não só no body JSON)"""
import os
os.chdir("C:/Users/Rafael/Documents/GitHub/Probux")

with open('mercadopago_utils.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Verifica se o proxy request já inclui cookie no header
# O formato atual envia o cookie dentro dos headers do body JSON
# Precisamos enviar como header HTTP separado para o Cloudflare Worker ler

old_code = """def _proxy_request(method, endpoint, headers=None, body=None, timeout=30):
    \"\"\"
    Envia request através do proxy Node.js (robo-roblox.js).
    Isso permite contornar bloqueios de IP do Roblox.

    O proxy espera:
      POST /proxy com body JSON: { method, url, headers, body, domain }
    \"\"\"
    proxy_url = ROBLOX_PROXY_URL.rstrip('/') + '/proxy'

    # Resolve o domínio correto
    domain = _resolve_domain(endpoint)

    # Extrai apenas o path do endpoint (ex: /v1/purchases/game-pass/1)
    if endpoint.startswith('http'):
        endpoint_path = endpoint
    else:
        endpoint_path = endpoint if endpoint.startswith('/') else '/' + endpoint

    payload = {
        'method': method.upper(),
        'url': endpoint_path,
        'headers': headers or {},
        'body': body,
        'domain': domain,
    }

    try:
        resp = requests.post(
            proxy_url,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=timeout + 10,  # Timeout um pouco maior para incluir overhead do proxy
        )"""

new_code = """def _proxy_request(method, endpoint, headers=None, body=None, timeout=30):
    """
    Envia request através do proxy Node.js (robo-roblox.js) ou Cloudflare Worker.
    Isso permite contornar bloqueios de IP do Roblox.

    O proxy espera:
      POST /proxy com body JSON: { method, url, headers, body, domain }
    Se ROBLOX_PROXY_URL for Cloudflare Worker, o cookie será enviado via header HTTP.
    """
    proxy_url = ROBLOX_PROXY_URL.rstrip('/') + '/proxy'

    # Resolve o domínio correto
    domain = _resolve_domain(endpoint)

    # Extrai apenas o path do endpoint (ex: /v1/purchases/game-pass/1)
    if endpoint.startswith('http'):
        endpoint_path = endpoint
    else:
        endpoint_path = endpoint if endpoint.startswith('/') else '/' + endpoint

    payload = {
        'method': method.upper(),
        'url': endpoint_path,
        'headers': headers or {},
        'body': body,
        'domain': domain,
    }

    # Para Cloudflare Worker, envia o cookie do Roblox como header HTTP
    # (o Worker lê tanto do header HTTP "x-roblox-cookie" quanto do body headers)
    http_headers = {'Content-Type': 'application/json'}
    sent_cookie_via_header = False
    if headers and 'Cookie' in headers:
        http_headers['x-roblox-cookie'] = headers['Cookie'].replace('.ROBLOSECURITY=', '')
        sent_cookie_via_header = True

    try:
        resp = requests.post(
            proxy_url,
            json=payload,
            headers=http_headers,
            timeout=timeout + 10,  # Timeout um pouco maior para incluir overhead do proxy
        )"""

if old_code in content:
    content = content.replace(old_code, new_code)
    print("✅ Cookie header HTTP fix aplicado!")
else:
    print("❌ Padrão não encontrado no _proxy_request")

with open('mercadopago_utils.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Feito!")