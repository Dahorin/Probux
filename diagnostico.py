#!/usr/bin/env python3
"""Script de diagnóstico - Execute na Square Cloud para testar a API"""
import os
import sys

sys.path.insert(0, '.')
os.chdir('/application' if os.path.exists('/application') else '.')

from dotenv import load_dotenv
load_dotenv()

print("=" * 60)
print("  DIAGNÓSTICO PROBUX")
print("=" * 60)

# 1. Verificar variáveis de ambiente
print("\n[1] VARIÁVEIS DE AMBIENTE:")
vars_to_check = [
    'ROBLOX_COOKIE', 'MERCADO_PAGO_ACCESS_TOKEN', 'MERCADO_PAGO_WEBHOOK_URL',
    'PIX_KEY', 'DATABASE_URL', 'MAIL_SERVER', 'MAIL_USERNAME', 'MAIL_PASSWORD',
    'PORT', 'FLASK_ENV', 'DISCOUNT_PERCENT', 'SECRET_KEY'
]
for var in vars_to_check:
    val = os.getenv(var, 'NÃO CONFIGURADO')
    if len(val) > 50:
        val = val[:50] + '...'
    print(f"  {var}: {val}")

# 2. Testar conexão com API do Roblox
print("\n[2] TESTE DE CONEXÃO COM O ROBLOX:")
try:
    import requests
    s = requests.Session()
    cookie = os.getenv('ROBLOX_COOKIE', '')
    if cookie:
        s.cookies.set('.ROBLOSECURITY', cookie, domain='.roblox.com')
    s.headers.update({'User-Agent': 'Roblox/WinInet', 'Accept': 'application/json'})

    # Testar XSRF token
    resp = s.post('https://auth.roblox.com/v2/logout', json={}, timeout=10)
    xsrf = resp.headers.get('X-CSRF-TOKEN')
    print(f"  XSRF Token: {'OBTIDO' if xsrf else 'FALHOU'}")
    print(f"  IP detectado pelo Roblox: {resp.headers.get('X-Roblox-ProxyEndpoint', 'N/A')}")

    # Testar API de compra
    print("\n  Testando API de compra (endpoint /v1/purchases/game-pass/1)...")
    purchase_resp = s.post(
        'https://api.roblox.com/v1/purchases/game-pass/1',
        json={'expectedPrice': 1},
        timeout=15
    )
    print(f"  Status: {purchase_resp.status_code}")
    print(f"  Resposta: {purchase_resp.text[:200]}")

    if purchase_resp.status_code == 403:
        print("  ⚠️  ERRO 403: IP bloqueado ou cookie inválido!")
        print("  → Tente renovar o cookie do Roblox (faça login novamente)")

except requests.exceptions.ConnectionError as e:
    print(f"  ❌ ERRO DE CONEXÃO: {e}")
    print("  → A Square Cloud pode estar bloqueando conexões de saída")
    print("  → Verifique se a porta 443 está liberada")
except requests.exceptions.Timeout:
    print("  ❌ TIMEOUT: O Roblox demorou muito para responder")
except Exception as e:
    print(f"  ❌ ERRO: {type(e).__name__}: {e}")

# 3. Testar Mercado Pago SDK
print("\n[3] TESTE DO MERCADO PAGO SDK:")
try:
    import mercadopago
    token = os.getenv('MERCADO_PAGO_ACCESS_TOKEN', '')
    if token:
        sdk = mercadopago.SDK(token)
        test_resp = sdk.payment().get(1)  # Qualquer pagamento para testar autenticação
        print(f"  SDK inicializado: OK")
    else:
        print("  Token não configurado")
except Exception as e:
    print(f"  ❌ ERRO: {e}")

# 4. Testar banco de dados
print("\n[4] TESTE DO BANCO DE DADOS:")
try:
    from extensions import db
    from app import create_app
    app = create_app()
    with app.app_context():
        from models import User
        count = User.query.count()
        print(f"  Conexão: OK")
        print(f"  Usuários registrados: {count}")
except Exception as e:
    print(f"  ❌ ERRO: {e}")

# 5. Verificar estrutura de pastas
print("\n[5] ESTRUTURA DE PASTAS:")
import os.path
for item in ['templates', 'static', '.env', 'mercadopago_utils.py', 'app.py']:
    exists = os.path.exists(item)
    print(f"  {item}: {'✅' if exists else '❌ NÃO ENCONTRADO'}")

print("\n" + "=" * 60)
print("  FIM DO DIAGNÓSTICO")
print("=" * 60)