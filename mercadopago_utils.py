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
ROBLOX_COOKIE = os.getenv('ROBLOX_COOKIE', '')

# URL do Cloudflare Worker proxy (deixe vazio para conexão direta)
# Exemplo: https://roblox-proxy.seu-nome.workers.dev
ROBLOX_PROXY_URL = os.getenv('ROBLOX_PROXY_URL', '')

USE_PROXY = bool(ROBLOX_PROXY_URL)

# Headers padrão para simular navegador real (evita bloqueios)
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept-Encoding': 'gzip, deflate, br',
    'Content-Type': 'application/json',
    'Origin': 'https://www.roblox.com',
    'Referer': 'https://www.roblox.com/',
}

# ===================================================================
# LOGGING
# ===================================================================
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs', 'delivery.log')

logger = logging.getLogger('probux_delivery')
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

# Console handler
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
ch.setFormatter(formatter)
logger.addHandler(ch)

# File handler
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


def _create_session(roblox_cookie=None):
    """Cria uma sessão requests com headers realistas e cookie configurado."""
    s = requests.Session()
    s.headers.update(DEFAULT_HEADERS)
    if roblox_cookie:
        s.cookies.set('.ROBLOSECURITY', roblox_cookie, domain='.roblox.com', path='/')
    return s


def _get_xsrf_token(session):
    """Obtém o token XSRF necessário para operações POST no Roblox."""
    try:
        # Método 1: via logout endpoint (retorna X-CSRF-TOKEN no header)
        resp = session.post('https://auth.roblox.com/v2/logout', json={}, timeout=10)
        xsrf = resp.headers.get('X-CSRF-TOKEN') or resp.headers.get('x-csrf-token')
        if xsrf:
            session.headers['X-CSRF-TOKEN'] = xsrf
            return xsrf
    except Exception:
        pass

    try:
        # Método 2: via authenticate endpoint (se logout falhar por já estar deslogado)
        resp = session.post('https://auth.roblox.com/v2/authenticate', json={}, timeout=10)
        xsrf = resp.headers.get('X-CSRF-TOKEN') or resp.headers.get('x-csrf-token')
        if xsrf:
            session.headers['X-CSRF-TOKEN'] = xsrf
            return xsrf
    except Exception:
        pass

    try:
        # Método 3: via página de perfil (parsing do HTML)
        resp = session.get('https://www.roblox.com/users/#!/profile', timeout=10)
        if resp.status_code == 200:
            match = re.search(r'name="__RequestVerificationToken"[^>]*?value="([^"]+)"', resp.text)
            if match:
                token = match.group(1)
                session.headers['X-CSRF-TOKEN'] = token
                return token
    except Exception:
        pass

    return None


def _roblox_api_request(method, endpoint, session=None, json_data=None, max_retries=3, use_auth=True):
    """
    Faz request para a API do Roblox com retry automático.
    Tenta api.roblox.com primeiro, depois catalog.roblox.com como fallback para GETs.
    """
    if session is None:
        session = _create_session(ROBLOX_COOKIE if use_auth else None)

    # Tenta obter XSRF token para POSTs
    if method.upper() == 'POST' and use_auth:
        _get_xsrf_token(session)

    last_error = "Erro desconhecido"

    # Define URLs de fallback
    if endpoint.startswith('/v1/') or endpoint.startswith('/v2/'):
        urls = [
            f"https://api.roblox.com{endpoint}",           # API oficial
            f"https://catalog.roblox.com{endpoint}",       # Catalog API (fallback)
        ]
    else:
        urls = [
            f"https://api.roblox.com{endpoint}",
        ]

    if USE_PROXY and ROBLOX_PROXY_URL:
        urls = [f"{ROBLOX_PROXY_URL}{endpoint}"]

    for url_idx, base_url in enumerate(urls):
        for attempt in range(1, max_retries + 1):
            try:
                if method.upper() == 'POST':
                    resp = session.post(base_url, json=json_data, timeout=30)
                elif method.upper() == 'GET':
                    resp = session.get(base_url, timeout=30)
                else:
                    resp = session.request(method.upper(), base_url, json=json_data, timeout=30)

                _log(f"[ROBLOX] URL: {base_url} | Status: {resp.status_code} | Tentativa: {attempt}", 'debug')

                if resp.status_code == 200:
                    try:
                        return resp.json(), None
                    except Exception:
                        return resp.text, None
                elif resp.status_code == 403:
                    error_msg = "Acesso negado (403) — cookie inválido, expirado ou IP bloqueado"
                    _log(f"[ROBLOX] {error_msg} | Body: {resp.text[:200]}", 'error')
                    # Se 403 em uma URL, tenta a próxima URL de fallback
                    if url_idx < len(urls) - 1:
                        _log(f"[ROBLOX] Tentando URL alternativa...", 'info')
                        break
                    return None, error_msg
                elif resp.status_code == 401:
                    return None, "Não autorizado (401) — cookie expirado ou inválido"
                elif resp.status_code == 429:
                    wait = attempt * 5
                    _log(f"[ROBLOX] Rate limit ({resp.status_code}), aguardando {wait}s...", 'warning')
                    time.sleep(wait)
                    last_error = "Rate limit"
                    continue
                elif resp.status_code == 500:
                    error_msg = f"Erro interno do servidor Roblox (500)"
                    _log(f"[ROBLOX] {error_msg} | Body: {resp.text[:200]}", 'error')
                    time.sleep(2)
                    last_error = error_msg
                    continue
                elif resp.status_code == 422:
                    try:
                        data = resp.json()
                        errors = data.get('errors', [{}])
                        error_msg = errors[0].get('message', resp.text[:200]) if errors else resp.text[:200]
                    except Exception:
                        error_msg = resp.text[:200]
                    return None, f"Validação falhou (422): {error_msg}"
                elif resp.status_code >= 502:
                    wait = attempt * 3
                    _log(f"[ROBLOX] Gateway error ({resp.status_code}), aguardando {wait}s...", 'warning')
                    time.sleep(wait)
                    last_error = f"HTTP {resp.status_code}"
                    continue
                else:
                    return None, f"HTTP {resp.status_code}: {resp.text[:300]}"

            except requests.exceptions.Timeout:
                last_error = "Timeout"
                _log(f"[ROBLOX] ⏰ Timeout (tentativa {attempt})", 'warning')
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
    Verifica se o cookie do Roblox é válido autenticando no endpoint de perfil.
    Retorna (is_valid, error_message).
    """
    if not cookie:
        return False, "Cookie não fornecido"

    session = _create_session(cookie)

    try:
        resp = session.get('https://users.roblox.com/v1/users/authenticated', timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            user_id = data.get('id')
            username = data.get('name', 'Unknown')
            _log(f"[ROBLOX] Cookie válido! Usuário: {username} (ID: {user_id})", 'info')
            return True, None
        elif resp.status_code == 401:
            return False, "Cookie inválido ou expirado (401)"
        elif resp.status_code == 403:
            return False, "Acesso negado - IP pode estar bloqueado (403)"
        else:
            return False, f"Erro inesperado: HTTP {resp.status_code}"
    except requests.exceptions.ConnectionError:
        return False, "Falha de conexão - verifique rede/proxy"
    except Exception as e:
        return False, f"Erro: {str(e)}"


# ===================================================================
# COMPRA DE GAMEPASS
# ===================================================================
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