#!/usr/bin/env python3
"""Script de diagnóstico - Execute na Square Cloud para testar a API"""
import os
import sys

sys.path.insert(0, '.')
os.chdir('/application' if os.path.exists('/application') else '.')

from dotenv import load_dotenv
load_dotenv()

print("=" * 60)
print("  DIAGNÓSTICO PROBUX v2")
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
    print("  ✅ Todos os módulos carregados com sucesso")
except ImportError as e:
    print(f"  ❌ Erro ao importar: {e}")
    print("  → Verifique se requirements.txt está completo")
    sys.exit(1)

# ===================================================================
# VARIÁVEIS DE AMBIENTE
# ===================================================================
print("\n[1] VARIÁVEIS DE AMBIENTE:")
vars_critical = ['ROBLOX_COOKIE', 'MERCADO_PAGO_ACCESS_TOKEN', 'DATABASE_URL', 'SECRET_KEY']
vars_optional = ['MERCADO_PAGO_WEBHOOK_URL', 'PIX_KEY', 'MAIL_SERVER', 'MAIL_USERNAME',
                 'MAIL_PASSWORD', 'PORT', 'FLASK_ENV', 'DISCOUNT_PERCENT', 'ROBLOX_PROXY_URL']

all_env_ok = True
for var in vars_critical:
    val = os.getenv(var, 'NÃO CONFIGURADO')
    masked = val[:15] + '...' if len(val) > 15 else val
    status = '✅' if val != 'NÃO CONFIGURADO' else '❌'
    print(f"  {status} {var}: {masked}")
    if val == 'NÃO CONFIGURADO':
        all_env_ok = False

for var in vars_optional:
    val = os.getenv(var, 'NÃO CONFIGURADO')
    masked = val[:15] + '...' if len(val) > 15 else val
    status = '✅' if val != 'NÃO CONFIGURADO' else '⚪'
    print(f"  {status} {var}: {masked}")

if not all_env_ok:
    print("\n  ⚠️  Variáveis CRÍTICAS ausentes! O sistema não funcionará sem elas.")

# ===================================================================
# CONEXÃO COM O ROBLOX
# ===================================================================
print("\n[2] TESTE DE CONEXÃO COM O ROBLOX:")
cookie = (os.getenv('ROBLOX_COOKIE', '') or '').strip()

if not cookie:
    print("  ❌ ROBLOX_COOKIE não está configurado!")
    print("     → Copie o .ROBLOSECURITY do navegador e cole no .env")
else:
    print(f"  📋 Cookie carregado: {len(cookie)} caracteres")

    # Validação do cookie
    is_valid, error = mp_utils.verify_roblox_cookie(cookie)
    if is_valid:
        print(f"  ✅ Cookie: VÁLIDO")
    else:
        print(f"  ❌ Cookie: INVÁLIDO — {error}")
        print("     → Acesse https://www.roblox.com, faça login e copie o .ROBLOSECURITY")

    # Teste de endpoints
    session = mp_utils._create_session(cookie)
    xsrf = mp_utils._get_xsrf_token(session)
    if xsrf:
        print(f"  ✅ XSRF Token: obtido com sucesso")
    else:
        print(f"  ⚠️  XSRF Token: não obtido (possível bloqueio de IP)")

    # API v2 - Usuário autenticado
    try:
        resp = session.get('https://users.roblox.com/v1/users/authenticated', timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            print(f"  ✅ API v2 (users): OK → {data.get('name', '?')} (ID: {data.get('id')})")
        else:
            print(f"  ⚠️  API v2 (users): HTTP {resp.status_code}")
    except Exception as e:
        print(f"  ❌ API v2 (users): ERRO → {e}")

    # API Economy v1 (saldo)
    try:
        resp = session.get('https://economy.roblox.com/v1/user/currency', timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            robux = data.get('robux', '?')
            print(f"  ✅ API Economy v1 (saldo): OK → 💰 {robux} Robux")
        else:
            print(f"  ⚠️  API Economy v1: HTTP {resp.status_code}")
    except Exception as e:
        print(f"  ❌ API Economy v1: ERRO → {e}")

    # Catalog API
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
        print(f"  ❌ Catalog API: ERRO → {e}")

    # Purchase API
    print("  Testando Purchase API...")
    try:
        resp = session.post(
            'https://api.roblox.com/v1/purchases/game-pass/1',
            json={'expectedPrice': 1},
            timeout=15
        )
        if resp.status_code in [200, 400, 403, 401, 422, 412]:
            try:
                data = resp.json()
                error_msg = str(data.get('error', {}).get('message', data))[:150]
            except Exception:
                error_msg = resp.text[:150]
            print(f"  ✅ Purchase API: HTTP {resp.status_code} (API funcionando!)")
            print(f"     Mensagem: {error_msg}")
        else:
            print(f"  ❌ Purchase API: HTTP {resp.status_code} inesperado")
    except requests.exceptions.ConnectionError as e:
        print(f"  ❌ Purchase API: Falha de conexão → {e}")
    except Exception as e:
        print(f"  ❌ Purchase API: ERRO → {e}")

# ===================================================================
# MERCADO PAGO SDK
# ===================================================================
print("\n[3] TESTE DO MERCADO PAGO SDK:")
try:
    mp_token = os.getenv('MERCADO_PAGO_ACCESS_TOKEN', '')
    if mp_token:
        sdk = mercadopago.SDK(mp_token)
        test_resp = sdk.payment().get(1)
        status = test_resp.get('status', 'N/A') if isinstance(test_resp, dict) else 'resposta_ok'
        print(f"  ✅ SDK inicializado: OK")
        print(f"  ✅ Consulta de pagamento: {status}")
    else:
        print("  ⚠️  Token não configurado (MERCADO_PAGO_ACCESS_TOKEN)")
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
        print(f"  ✅ Conexão com banco: OK")
        print(f"  ✅ Usuários registrados: {count}")

        from sqlalchemy import inspect
        from models import Order
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('order')]
        if 'delivery_attempted' in columns:
            print(f"  ✅ Coluna 'delivery_attempted': existe")
        else:
            print(f"  ❌ Coluna 'delivery_attempted': NÃO encontrada!")
            print(f"     → Execute a migração: migrations/002_add_delivery_attempted.sql")
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

issues = []
if not cookie:
    issues.append("  → Cookie do Roblox não configurado")
else:
    cookie_valid, _ = mp_utils.verify_roblox_cookie(cookie)
    if not cookie_valid:
        issues.append("  → Cookie do Roblox inválido ou expirado")
if not all_env_ok:
    issues.append("  → Variáveis de ambiente críticas ausentes")

try:
    app_test = create_app()
    with app_test.app_context():
        from sqlalchemy import inspect
        from models import Order
        columns = [col['name'] for col in inspect(db.engine).get_columns('order')]
        if 'delivery_attempted' not in columns:
            issues.append("  → Coluna 'delivery_attempted' faltando (executar migração SQL)")
except Exception:
    issues.append("  → Não foi possível verificar banco de dados")

if not issues:
    print("  ✅ SISTEMA OPERACIONAL - Tudo configurado corretamente!")
else:
    print("  ⚠️  Ajustes necessários:")
    for issue in issues:
        print(issue)
    print("     → Execute a migração: migrations/002_add_delivery_attempted.sql")

print("=" * 60)
print("\nDica: Acesse /test_roblox_connection no navegador para ver o diagnóstico visual.")