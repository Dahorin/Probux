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

# ===================================================================
# IMPORTAR MÓDULOS
# ===================================================================
print("\n[0] CARREGANDO MÓDULOS...")
try:
    import requests
    import mercadopago as mp_sdk
    from extensions import db, mail
    from app import create_app
    from models import User
    import mercadopago_utils as mp_utils
    print("  ✅ Módulos carregados com sucesso")
except ImportError as e:
    print(f"  ❌ Erro ao importar: {e}")
    print("  → Verifique se requirements.txt está completo")
    sys.exit(1)

# ===================================================================
# VARIÁVEIS DE AMBIENTE
# ===================================================================
print("\n[1] VARIÁVEIS DE AMBIENTE:")
vars_to_check = {
    'ROBLOX_COOKIE': 'Cookie do Roblox',
    'MERCADO_PAGO_ACCESS_TOKEN': 'Token Mercado Pago',
    'MERCADO_PAGO_WEBHOOK_URL': 'Webhook MP URL',
    'PIX_KEY': 'Chave PIX',
    'DATABASE_URL': 'URL do banco',
    'MAIL_SERVER': 'Servidor SMTP',
    'MAIL_USERNAME': 'Usuário SMTP',
    'MAIL_PASSWORD': 'Senha SMTP',
    'PORT': 'Porta',
    'FLASK_ENV': 'Ambiente',
    'DISCOUNT_PERCENT': 'Desconto %',
    'SECRET_KEY': 'Secret Key',
    'ROBLOX_PROXY_URL': 'Proxy Cloudflare',
}
all_env_ok = True
for var, desc in vars_to_check.items():
    val = os.getenv(var, 'NÃO CONFIGURADO')
    status = '✅' if val != 'NÃO CONFIGURADO' else '⚠️'
    if var in ('MERCADO_PAGO_ACCESS_TOKEN', 'MAIL_PASSWORD', 'SECRET_KEY', 'ROBLOX_COOKIE') and len(val) > 20:
        display = val[:20] + '...'
    else:
        display = val
    print(f"  {status} {desc}: {display}")
    if val == 'NÃO CONFIGURADO' and var not in ('PIX_KEY', 'ROBLOX_PROXY_URL', 'DISCOUNT_PERCENT'):
        all_env_ok = False
if not all_env_ok:
    print("  ⚠️  Algumas variáveis essenciais não estão configuradas!")

# ===================================================================
# CONEXÃO COM O ROBLOX (NOVO - robusto)
# ===================================================================
print("\n[2] TESTE DE CONEXÃO COM O ROBLOX:")
cookie = os.getenv('ROBLOX_COOKIE', '')
if not cookie:
    print("  ❌ ROBLOX_COOKIE não configurado!")
else:
    # Teste de validação do cookie
    is_valid, error = mp_utils.verify_roblox_cookie(cookie)
    if is_valid:
        print("  ✅ Cookie do Roblox: VÁLIDO")
    else:
        print(f"  ❌ Cookie do Roblox: INVÁLIDO - {error}")
        print("  → Acesse https://www.roblox.com, faça login e copie o .ROBLOSECURITY")

    # Teste de XSRF token
    session = mp_utils._create_session(cookie)
    xsrf = mp_utils._get_xsrf_token(session)
    if xsrf:
        print(f"  ✅ XSRF Token: obtido com sucesso")
    else:
        print(f"  ⚠️  XSRF Token: não obtido (possível bloqueio de IP)")

    # Teste API v2
    try:
        resp = session.get('https://users.roblox.com/v1/users/authenticated', timeout=10)
        if resp.status_code == 200:
            user_data = resp.json()
            print(f"  ✅ API v2 (users/authenticated): OK - {user_data.get('name')} (ID: {user_data.get('id')})")
        else:
            print(f"  ⚠️  API v2: HTTP {resp.status_code}")
    except Exception as e:
        print(f"  ❌ API v2: Erro - {e}")

    # Teste Economy v1 (saldo)
    try:
        resp = session.get('https://economy.roblox.com/v1/user/currency', timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            print(f"  ✅ API Economy v1 (saldo): OK - {data.get('robux')} Robux")
        else:
            print(f"  ⚠️  API Economy v1: HTTP {resp.status_code}")
    except Exception as e:
        print(f"  ❌ API Economy v1: Erro - {e}")

    # Teste Catalog API
    try:
        resp = session.post(
            'https://catalog.roblox.com/v1/catalog/items/details',
            json={'items': [{'id': 1, 'itemType': 'GamePass'}]},
            timeout=10
        )
        if resp.status_code == 200:
            print(f"  ✅ Catalog API: OK")
        else:
            print(f"  ⚠️  Catalog API: HTTP {resp.status_code}")
    except Exception as e:
        print(f"  ❌ Catalog API: Erro - {e}")

    # Teste Purchase API
    print("  Testando Purchase API (tentar comprar gamepass de teste)...")
    success, msg = mp_utils.buy_gamepass_with_cookie(
        'https://www.roblox.com/game-pass/1',  # gamepass de teste
        cookie,
        expected_price=0
    )
    if success:
        print(f"  ✅ Purchase API: COMPRA SUCEDIDA! {msg}")
    else:
        # 400/403 é esperado (gamepass de teste provavelmente não é acessível)
        # O importante é que a API respondeu
        if 'HTTP 400' in msg or 'HTTP 403' in msg or 'HTTP 4' in msg:
            print(f"  ✅ Purchase API: Responde mas rejeitou (esperado para gamepass de teste)")
            print(f"     Detalhes: {msg[:200]}")
        else:
            print(f"  ❌ Purchase API: FALHA - {msg}")

# ===================================================================
# MERCADO PAGO SDK
# ===================================================================
print("\n[3] TESTE DO MERCADO PAGO SDK:")
try:
    mp_token = os.getenv('MERCADO_PAGO_ACCESS_TOKEN', '')
    if mp_token:
        sdk = mercadopago.SDK(mp_token)
        test_resp = sdk.payment().get(1)
        print(f"  ✅ SDK inicializado: OK")
        print(f"  ✅ Consulta de pagamento: HTTP {test_resp.get('status', 'N/A')}")
    else:
        print("  ⚠️  Token não configurado")
except Exception as e:
    print(f"  ❌ ERRO: {e}")

# ===================================================================
# BANCO DE DADOS
# ===================================================================
print("\n[4] TESTE DO BANCO DE DADOS:")
try:
    app = create_app()
    with app.app_context():
        count = User.query.count()
        print(f"  ✅ Conexão: OK")
        print(f"  ✅ Usuários registrados: {count}")

        # Verificar se a tabela Order tem a coluna delivery_attempted
        from sqlalchemy import inspect
        from models import Order
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('order')]
        if 'delivery_attempted' in columns:
            print(f"  ✅ Coluna 'delivery_attempted': existe")
        else:
            print(f"  ⚠️  Coluna 'delivery_attempted': NÃO ENCONTRADA (executar migração!)")
except Exception as e:
    print(f"  ❌ ERRO: {e}")

# ===================================================================
# ESTRUTURA DE PASTAS
# ===================================================================
print("\n[5] ESTRUTURA DE PASTAS:")
required_files = [
    'app.py', 'routes.py', 'models.py', 'mercadopago_utils.py',
    'comprar-gamepass.js', 'templates/order.html', 'templates/checkout.html',
    'templates/index.html', 'templates/dashboard.html', 'templates/test_connection.html'
]
for f in required_files:
    exists = os.path.exists(f)
    print(f"  {'✅' if exists else '❌'} {f}")

# ===================================================================
# RESUMO
# ===================================================================
print("\n" + "=" * 60)
print("  RESUMO:")
print("-" * 60)
if is_valid and all_env_ok:
    print("  ✅ SISTEMA OPERACIONAL - Tudo configurado corretamente!")
else:
    print("  ⚠️  Ajustes necessários:")
    if not is_valid:
        print("     → Atualize o ROBLOX_COOKIE no .env")
    if not all_env_ok:
        print("     → Configure as variáveis de ambiente ausentes")
    print("     → Execute: psql -c \"ALTER TABLE order ADD COLUMN delivery_attempted BOOLEAN DEFAULT FALSE NOT NULL;\"")
print("=" * 60)