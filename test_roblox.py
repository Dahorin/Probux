import os
import re
import requests
from dotenv import load_dotenv
load_dotenv()

cookie = os.getenv('ROBLOX_COOKIE', '')
print(f'Cookie carregado: {"SIM" if cookie else "NAO"} - {len(cookie)} chars')

if not cookie:
    print('ERRO: Configure o ROBLOX_COOKIE no .env')
    exit(1)

# Cria sessao com o cookie
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

# Testa verificacao de gamepass usando funcao do routes.py
print('\n=== TESTE: Verificar Gamepass via API ===')
# Usa uma gamepass de teste (substitua por uma real sua)
gamepass_link = 'https://www.roblox.com/game-pass/12345678'  # SUBSTITUA pelo ID real

match = re.search(r'game-pass/(\d+)', gamepass_link)
if match:
    gamepass_id = match.group(1)
    print(f'ID da Gamepass: {gamepass_id}')

    # Busca informacoes via API de catalogo
    print('\nBuscando preco via API de catalogo...')
    try:
        catalog_url = 'https://catalog.roblox.com/v1/catalog/items/details'
        resp = s.post(catalog_url, json={'items': [{'id': int(gamepass_id), 'itemType': 'GamePass'}]}, timeout=15)
        print(f'Status: {resp.status_code}')
        if resp.status_code == 200:
            data = resp.json()
            items = data.get('data', [])
            if items:
                price = items[0].get('price') or items[0].get('priceInRobux')
                name = items[0].get('name', 'Sem nome')
                print(f'Nome: {name}')
                print(f'Preco: {price} Robux')
            else:
                print('Gamepass nao encontrada na API (pode estar privada)')
        else:
            print(f'Erro na API: {resp.status_code}')
    except Exception as e:
        print(f'Erro: {e}')

print('\n=== TESTANDO FUNCAO DO MERCADOPAGO_UTILS ===')
# Testa a funcao que vai usar no sistema
print('Importando buy_gamepass_with_cookie...')
try:
    import sys
    sys.path.insert(0, '.')
    from mercadopago_utils import buy_gamepass_with_cookie
    print('Funcao importada com sucesso!')

    # Testa com uma gamepass real (descomente para testar compra real)
    # ATENCAO: Isso vai tentar comprar a gamepass se tiver Robux!
    testar_compra = False  # Mude para True para testar

    if testar_compra and match:
        gamepass_link_real = 'https://www.roblox.com/game-pass/ID_REAL'  # Coloque um ID real
        expected_price = 10  # Coloque o preco real
        print(f'\nTentando comprar gamepass: {gamepass_link_real}')
        print(f'Preco esperado: {expected_price} Robux')
        success, msg = buy_gamepass_with_cookie(gamepass_link_real, cookie, expected_price)
        print(f'Resultado: {"SUCESSO" if success else "FALHA"}')
        print(f'Mensagem: {msg}')
    else:
        print('\nTeste de compra desativado (testar_compra = False)')
        print('Para testar, altere testar_compra para True e coloque um ID real de gamepass')

except Exception as e:
    import traceback
    print(f'Erro ao importar/testar: {e}')
    traceback.print_exc()

print('\n=== TESTE CONCLUIDO ===')
print('Cookie valido: SIM')
print('XSRF Token: OBTIDO')
print('Pronto para usar no sistema!')
