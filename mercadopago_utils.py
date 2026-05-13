import mercadopago
import os
import re
import requests
import time
import json
import logging
from datetime import datetime

# ===================================================================
# CONFIGURAÇÃO DO MERCADO PAGO
# ===================================================================
MP_ACCESS_TOKEN = os.getenv('MERCADO_PAGO_ACCESS_TOKEN', '')
ROBLOX_COOKIE = os.getenv('ROBLOX_COOKIE', '').strip()

# URL do Cloudflare Worker proxy (deixe vazio para conexão direta)
# Exemplo: https://roblox-proxy.seu-nome.workers.dev
ROBLOX_PROXY_URL = os.getenv('ROBLOX_PROXY_URL', '').strip()

USE_PROXY = bool(ROBLOX_PROXY_URL)

# Detectar se suporta brotli
try:
    import brotli
    HAS_BROTLI = True
except ImportError:
    HAS_BROTLI = False

# Headers padrão para simular navegador real (evita bloqueios)
_accept_encoding = 'gzip, deflate'
if HAS_BROTLI:
    _accept_encoding += ', br'

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept-Encoding': _accept_encoding,
    'Content-Type': 'application/json; charset=UTF-8',
    'Origin': 'https://www.roblox.com',
    'Referer': 'https://www.roblox.com/',
    'Connection': 'keep-alive',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-site',
}

HOMEPAGE_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept-Encoding': _accept_encoding,
    'Connection': 'keep-alive',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Upgrade-Insecure-Requests': '1',
}

# ===================================================================
# LOGGING
# ===================================================================
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs', 'delivery.log')

logger = logging.getLogger('probux_delivery')
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
ch.setFormatter(formatter)
logger.addHandler(ch)

try:
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    fh = logging.FileHandler(LOG_FILE, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)
except Exception:
    pass


def _log(msg, level='info'):
    try:
        getattr(logger, level)(msg)
    except Exception:
        print(f"[{level.upper()}] {msg}", flush=True)


def _create_session(roblox_cookie=None, use_homepage_headers=False):
    """Cria uma sessão requests configurada para Roblox."""
    s = requests.Session()
    if use_homepage_headers:
        s.headers.update(HOMEPAGE_HEADERS)
    else:
        s.headers.update(DEFAULT_HEADERS)

    if roblox_cookie:
        # Limpa espaços e quebras de linha do cookie
        roblox_cookie = roblox_cookie.strip()
        s.cookies.set('.ROBLOSECURITY', roblox_cookie, domain='.roblox.com', path='/')
        _log(f"[ROBLOX] Cookie configurado ({len(roblox_cookie)} chars)", 'debug')
    return s


def _get_xsrf_token(session):
    """Obtém o token XSRF necessário para operações POST no Roblox."""
    # Método 1: via logout (funciona se o cookie NÃO for válido - retorna 401 com XSRF)
    try:
        resp = session.post('https://auth.roblox.com/v2/logout', json={}, timeout=10)
        xsrf = resp.headers.get('X-CSRF-TOKEN') or resp.headers.get('x-csrf-token')
        if xsrf:
            session.headers['X-CSRF-TOKEN'] = xsrf
            _log(f"[ROBLOX] XSRF token obtido via /v2/logout", 'debug')
            return xsrf
    except Exception as e:
        _log(f"[ROBLOX] Erro XSRF logout: {e}", 'debug')

    # Método 2: via authenticate
    try:
        resp = session.post('https://auth.roblox.com/v2/authenticate', json={}, timeout=10)
        xsrf = resp.headers.get('X-CSRF-TOKEN') or resp.headers.get('x-csrf-token')
        if xsrf:
            session.headers['X-CSRF-TOKEN'] = xsrf
            _log(f"[ROBLOX] XSRF token obtido via /v2/authenticate", 'debug')
            return xsrf
    except Exception as e:
        _log(f"[ROBLOX] Erro XSRF authenticate: {e}", 'debug')

    # Método 3: via página de login (fallback HTML)
    try:
        resp = session.get('https://www.roblox.com/login', timeout=10)
        if resp.status_code == 200:
            match = re.search(r'name="__RequestVerificationToken"[^>]*?value="([^"]+)"', resp.text)
            if match:
                token = match.group(1)
                session.headers['X-CSRF-TOKEN'] = token
                _log(f"[ROBLOX] XSRF token obtido via HTML login", 'debug')
                return token
    except Exception as e:
        _log(f"[ROBLOX] Erro XSRF HTML: {e}", 'debug')

    return None


def _test_endpoint(session, method, url, json_data=None, timeout=15):
    """Testa um endpoint específico e retorna resultado legível."""
    try:
        if method.upper() == 'POST':
            resp = session.post(url, json=json_data, timeout=timeout, allow_redirects=False)
        else:
            resp = session.get(url, timeout=timeout, allow_redirects=False)

        # Seguir redirecionamentos manualmente para ver para onde vai
        location = resp.headers.get('Location', '')

        return {
            'status_code': resp.status_code,
            'location': location,
            'body_preview': resp.text[:500],
            'headers': dict(resp.headers),
        }
    except requests.exceptions.ConnectionError as e:
        return {'error': f'ConnectionError: {str(e)[:200]}'}
    except requests.exceptions.Timeout:
        return {'error': 'Timeout'}
    except Exception as e:
        return {'error': f'{type(e).__name__}: {str(e)[:200]}'}


def _roblox_api_request(method, endpoint, session=None, json_data=None, max_retries=3, use_auth=True):
    """
    Faz request para a API do Roblox com retry automático.
    Tenta api.roblox.com primeiro, depois catalog.roblox.com como fallback.
    Suporta redirecionamentos.
    """
    if session is None:
        session = _create_session(ROBLOX_COOKIE if use_auth else None)

    if method.upper() == 'POST' and use_auth:
        _get_xsrf_token(session)

    last_error = "Erro desconhecido"

    urls = []
    if USE_PROXY and ROBLOX_PROXY_URL:
        urls = [f"{ROBLOX_PROXY_URL}{endpoint}"]
    elif endpoint.startswith('/v1/') or endpoint.startswith('/v2/'):
        urls = [
            f"https://api.roblox.com{endpoint}",
            f"https://catalog.roblox.com{endpoint}",
        ]
    else:
        urls = [f"https://api.roblox.com{endpoint}"]

    for url_idx, base_url in enumerate(urls):
        for attempt in range(1, max_retries + 1):
            try:
                if method.upper() == 'POST':
                    resp = session.post(base_url, json=json_data, timeout=30, allow_redirects=True)
                elif method.upper() == 'GET':
                    resp = session.get(base_url, timeout=30, allow_redirects=True)
                else:
                    resp = session.request(method.upper(), base_url, json=json_data, timeout=30, allow_redirects=True)

                _log(f"[ROBLOX] {method} {base_url} | Status: {resp.status_code} | Tentativa: {attempt}", 'debug')

                if resp.status_code == 200:
                    try:
                        return resp.json(), None
                    except Exception:
                        return resp.text, None
                elif resp.status_code == 403:
                    # 403 pode ser IP bloqueado OU cookie inválido
                    _log(f"[ROBLOX] 403 em {base_url}: {resp.text[:200]}", 'warning')
                    if url_idx < len(urls) - 1:
                        _log(f"[ROBLOX] Tentando URL alternativa...", 'info')
                        break
                    return None, "Acesso negado (403) — cookie inválido ou IP bloqueado pelo Roblox"
                elif resp.status_code == 401:
                    return None, "Não autorizado (401) — cookie expirado"
                elif resp.status_code == 429:
                    wait = attempt * 5
                    _log(f"[ROBLOX] Rate limit (429), esperando {wait}s...", 'warning')
                    time.sleep(wait)
                    last_error = "Rate limit"
                    continue
                elif resp.status_code == 500:
                    error_msg = f"Erro interno do servidor (500)"
                    _log(f"[ROBLOX] {error_msg} | Body: {resp.text[:200]}", 'error')
                    time.sleep(3)
                    last_error = error_msg
                    continue
                elif resp.status_code == 422:
                    try:
                        data = resp.json()
                        errors = data.get('errors', [{}])
                        error_msg = errors[0].get('message', resp.text[:200]) if errors else resp.text[:200]
                    except Exception:
                        error_msg = resp.text[:200]
                    return None, f"Erro de validação (422): {error_msg}"
                elif resp.status_code >= 502:
                    wait = attempt * 3
                    _log(f"[ROBLOX] Gateway error ({resp.status_code}), esperando {wait}s...", 'warning')
                    time.sleep(wait)
                    last_error = f"HTTP {resp.status_code}"
                    continue
                elif resp.status_code == 302 or resp.status_code == 301:
                    # Redirecionamento - seguir
                    _log(f"[ROBLOX] Redirecionamento ({resp.status_code}) para: {resp.headers.get('Location')}", 'debug')
                    return {'redirected': True, 'location': resp.headers.get('Location')}, 'redirected'
                else:
                    return None, f"HTTP {resp.status_code}: {resp.text[:300]}"

            except requests.exceptions.Timeout:
                last_error = "Timeout"
                _log(f"[ROBLOX] Timeout (tentativa {attempt})", 'warning')
            except requests.exceptions.ConnectionError as e:
                last_error = f"Conexão falhou: {str(e)[:150]}"
                _log(f"[ROBLOX] ❌ Conexão (tentativa {attempt}): {last_error}", 'error')
            except requests.exceptions.JSONDecodeError:
                last_error = "Resposta não é JSON válido"
                _log(f"[ROBLOX] ⚠️ {last_error}: {resp.text[:200]}", 'warning')
            except Exception as e:
                last_error = f"{type(e).__name__}: {str(e)[:150]}"
                _log(f"[ROBLOX] ❌ Erro (tentativa {attempt}): {last_error}", 'error')

            if attempt < max_retries:
                backoff = min(attempt * 2, 10)
                time.sleep(backoff)

    return None, f"{last_error} (falhou após {max_retries} tentativas, {len(urls)} URLs testadas)"


def verify_roblox_cookie(cookie=None):
    """
    Verifica se o cookie do Roblox é válido usando múltiplos métodos.
    Retorna (is_valid, error_message).
    """
    if not cookie:
        return False, "Cookie não fornecido"

    # Limpa o cookie
    cookie = cookie.strip()

    # Método 1: users.roblox.com/v1/users/authenticated
    session = _create_session(cookie)
    try:
        resp = session.get('https://users.roblox.com/v1/users/authenticated', timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            user_id = data.get('id')
            username = data.get('name', 'Unknown')
            _log(f"[ROBLOX] Cookie VÁLIDO via users API! Usuário: {username} (ID: {user_id})", 'info')
            return True, None
        elif resp.status_code == 401:
            _log(f"[ROBLOX] Cookie inválido via users API (401)", 'warning')
        elif resp.status_code == 403:
            _log(f"[ROBLOX] Acesso negado (403) via users API — IP pode estar bloqueado", 'warning')
            # 403 pode significar que o IP está bloqueado, mas cookie pode ser válido
            # Tenta outro método para confirmar
    except Exception as e:
        _log(f"[ROBLOX] Error na users API: {e}", 'warning')

    # Método 2: Verificar via página da conta (HTML)
    session2 = _create_session(cookie, use_homepage_headers=True)
    try:
        resp = session2.get('https://www.roblox.com/my/account', timeout=15, allow_redirects=True)
        if resp.status_code == 200 and 'Log In' not in resp.text and 'login' not in resp.url.lower():
            # Conseguiu acessar a página de conta = autenticado
            _log(f"[ROBLOX] Cookie VÁLIDO via página de conta!", 'info')
            return True, None
        elif resp.status_code == 200 and 'Log In' in resp.text:
            _log(f"[ROBLOX] Cookie inválido - página redirecionou para login", 'warning')
    except Exception as e:
        _log(f"[ROBLOX] Error ao verificar via página: {e}", 'warning')

    # Método 3: Verificar via catalog (se consegue acessar com cookie, o cookie é válido)
    try:
        resp = session.get('https://catalog.roblox.com/v1/catalog/items/details',
                          json={'items': [{'id': 1, 'itemType': 'GamePass'}]},
                          timeout=15)
        if resp.status_code == 200:
            _log(f"[ROBLOX] Cookie VÁLIDO via Catalog API (200)!", 'info')
            return True, None
        elif resp.status_code == 403:
            _log(f"[ROBLOX] IP provavelmente bloqueado (403 em todas as APIs)", 'warning')
            return False, "IP bloqueado pelo Roblox (403 em múltiplas APIs). Tente de outro IP ou use proxy."
    except Exception as e:
        _log(f"[ROBLOX] Error na catalog API: {e}", 'warning')

    return False, "Cookie inválido, expirado ou IP bloqueado. Renove o cookie ou tente de outro IP."


def get_balancer_status():
    """Testa rapidamente se a conexão com Roblox está funcionando.
    Retorna list de resultados por endpoint."""
    results = []
    cookie = ROBLOX_COOKIE
    if not cookie:
        return [{'endpoint': 'N/A', 'status': 'erro', 'message': 'Cookie não configurado'}]

    session = _create_session(cookie)
    _get_xsrf_token(session)

    endpoints = [
        ('Usuário Autenticado', 'GET', 'https://users.roblox.com/v1/users/authenticated'),
        ('Saldo Economy v1', 'GET', 'https://economy.roblox.com/v1/user/currency'),
        ('Catalog Items', 'POST', 'https://catalog.roblox.com/v1/catalog/items/details'),
    ]

    for name, method, url in endpoints:
        result = _test_endpoint(session, method, url, json_data={'items': [{'id': 1, 'itemType': 'GamePass'}]} if 'items' in url else None)
        if 'error' in result:
            results.append({'endpoint': name, 'status': 'erro', 'message': result['error']})
        elif result.get('status_code') == 200:
            results.append({'endpoint': name, 'status': 'ok', 'message': f"HTTP {result['status_code']}", 'data': result.get('body_preview', '')[:200]})
        else:
            results.append({'endpoint': name, 'status': 'erro', 'message': f"HTTP {result.get('status_code', '?')}: {result.get('body_preview', '')[:150]}"})

    return results
def buy_gamepass_with_cookie(gamepass_link, roblox_cookie, expected_price=None, max_retries=3):
    """Compra gamepass via API do Roblox (com proxy Cloudflare opcional)."""
    if not roblox_cookie:
        return (False, "Cookie do Roblox não configurado")

    match = re.search(r'game-pass/(\d+)', gamepass_link)
    if not match:
        return (False, "Link da Gamepass inválido")

    gamepass_id = match.group(1)
    _log(f"[GAMEPASS] 🎮 Comprando gamepass {gamepass_id} (proxy={'ON' if USE_PROXY else 'OFF'})", 'info')

    # Verifica se o cookie é válido antes de tentar comprar
    is_valid, error = verify_roblox_cookie(roblox_cookie)
    if not is_valid:
        _log(f"[GAMEPASS] ❌ Cookie inválido: {error}", 'error')
        return (False, f"Cookie inválido: {error}")

    session = _create_session(roblox_cookie)

    # Verifica preço via catálogo
    if expected_price:
        data, err = _roblox_api_request(
            'POST', '/v1/catalog/items/details',
            session=session,
            json_data={'items': [{'id': int(gamepass_id), 'itemType': 'GamePass'}]},
            max_retries=1
        )
        if data and 'data' in data:
            items = data['data']
            if items:
                actual_price = items[0].get('price') or items[0].get('priceInRobux')
                _log(f"[GAMEPASS] Preço real: {actual_price} Robux", 'debug')
                if actual_price and int(actual_price) != int(expected_price):
                    _log(f"[GAMEPASS] ⚠️ Preço diferente: esperado {expected_price}, real {actual_price}", 'warning')

    # Tenta a compra — endpoint principal
    _log(f"[GAMEPASS] Tentando compra via /v1/purchases/game-pass/{gamepass_id}...", 'info')
    data, err = _roblox_api_request(
        'POST', f'/v1/purchases/game-pass/{gamepass_id}',
        session=session,
        json_data={'expectedPrice': int(expected_price) if expected_price else 1},
        max_retries=max_retries
    )

    if data and data.get('success'):
        _log(f"[GAMEPASS] ✅ COMPRA SUCEDIDA! Gamepass {gamepass_id}", 'info')
        return (True, f"Gamepass {gamepass_id} comprada com sucesso!")
    elif data:
        error_msg = data.get('error', data.get('errorMessage', 'Erro desconhecido'))
        _log(f"[GAMEPASS] ❌ API erro: {error_msg}", 'error')

        # Fallback: tenta via endpoint alternativo
        _log(f"[GAMEPASS] Tentando endpoint alternativo /marketplace/game-pass/{gamepass_id}...", 'info')
        data2, err2 = _roblox_api_request(
            'POST', f'/marketplace/game-pass/{gamepass_id}',
            session=session,
            json_data={'expectedPrice': int(expected_price) if expected_price else 1},
            max_retries=2
        )
        if data2 and data2.get('success'):
            _log(f"[GAMEPASS] ✅ COMPRA SUCEDIDA (fallback)! Gamepass {gamepass_id}", 'info')
            return (True, f"Gamepass {gamepass_id} comprada com sucesso!")

        return (False, f"API erro: {error_msg}")
    else:
        _log(f"[GAMEPASS] ❌ Falha: {err}", 'error')
        return (False, err)


# ===================================================================
# ENTREGA DE GAMEPASS
# ===================================================================
def deliver_gamepasses(order, notify_user=True):
    """Entrega gamepasses de um pedido após pagamento confirmado."""
    from models import OrderItem, User
    from extensions import db
    from flask import current_app

    gamepass_items = [item for item in order.items if item.product.is_gamepass]
    if not gamepass_items:
        return (False, "Nenhum item de gamepass no pedido")

    cookie = current_app.config.get('ROBLOX_COOKIE', '') or os.getenv('ROBLOX_COOKIE', '')

    if not cookie:
        _log("[ENTREGA] ❌ Cookie não configurado!", 'error')
        return (False, "Cookie do Roblox não configurado")

    _log(f"[ENTREGA] 🚀 Pedido #{order.id}: {len(gamepass_items)} item(s)", 'info')

    # Se usar proxy, mostra no log
    if USE_PROXY:
        _log(f"[ENTREGA] 🔀 Usando proxy: {ROBLOX_PROXY_URL[:50]}...", 'info')
    else:
        _log(f"[ENTREGA] 🔗 Conexão direta com API do Roblox", 'info')

    results = []
    success_count = 0

    for item in gamepass_items:
        if not item.gamepass_link or not item.robux_amount:
            results.append(f"Item {item.id}: dados incompletos")
            continue

        success, msg = buy_gamepass_with_cookie(
            item.gamepass_link, cookie, item.robux_amount
        )
        results.append(f"GP ({item.robux_amount} Robux): {msg}")

        if success:
            success_count += 1

    all_success = success_count == len(gamepass_items) and len(gamepass_items) > 0

    # Marca que já tentamos entregar (evita loop infinito no check_payment)
    order.delivery_attempted = True

    if all_success:
        order.delivered = True
        order.delivered_at = datetime.utcnow()
        order.status = 'delivered'
    else:
        order.status = 'paid'

    db.session.commit()

    _log(f"[ENTREGA] Pedido #{order.id}: {success_count}/{len(gamepass_items)} sucesso", 'info')

    # Notificação por email
    if notify_user:
        try:
            from flask_mail import Message
            from extensions import mail as mail_ext

            user = User.query.get(order.user_id)
            if user:
                if all_success:
                    subject = '✅ Gamepass Entregue - Probux'
                    body = (
                        f"Olá {user.username},\n\n"
                        f"Sua gamepass foi entregue!\n\n"
                        f"Pedido: #{order.id}\n"
                        f"Data: {order.delivered_at.strftime('%d/%m/%Y %H:%M')}\n\n"
                        f"Verifique seus Robux em:\n"
                        f"https://www.roblox.com/transactions\n\n"
                        f"— Equipe Probux"
                    )
                else:
                    subject = '⚠️ Falha na Entrega - Probux'
                    body = (
                        f"Olá {user.username},\n\n"
                        f"Houve um erro na entrega do pedido #{order.id}.\n"
                        f"Nossa equipe foi notificada.\n\n"
                        f"— Equipe Probux"
                    )

                msg = Message(subject, recipients=[user.email], body=body)
                mail_ext.send(msg)
        except Exception as e:
            _log(f"[EMAIL] Erro ao enviar: {e}", 'warning')

    return (all_success, "; ".join(results))