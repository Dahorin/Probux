import mercadopago
import os
import re
import requests
import time
import json
import logging
import urllib.parse
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

# NOTA: Content-Type NÃO é setado globalmente — GETs não devem ter Content-Type
# POSTs terão Content-Type adicionado individualmente
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept-Encoding': _accept_encoding,
    'Origin': 'https://www.roblox.com',
    'Referer': 'https://www.roblox.com/',
    'Connection': 'keep-alive',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-site',
}

POST_HEADERS = {
    'Content-Type': 'application/json; charset=UTF-8',
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


# Configuração do Mercado Pago SDK
_mp_sdk = None

def get_mp_sdk():
    global _mp_sdk
    if _mp_sdk is None:
        _mp_sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
    return _mp_sdk

def create_pix_payment(total, description, order_id, email):
    """
    Cria um pagamento Pix via Mercado Pago (SDK v2).
    Tenta payment.create (QR code inline) primeiro, depois fallback para preference (redirect).
    Retorna dict com id, qr_code, qr_code_base64, init_point ou None em caso de erro.
    """
    sdk = get_mp_sdk()
    if not sdk:
        return None

    # =============================================
    # MÉTODO 1: Payment API (retorna QR code inline)
    # =============================================
    try:
        result = sdk.payment().create({
            'transaction_amount': float(total),
            'description': description,
            'payment_method_id': 'pix',
            'payer': {
                'email': email
            },
            'external_reference': str(order_id),
            'notification_url': os.getenv('MERCADO_PAGO_WEBHOOK_URL', ''),
        })
        _log(f"[MERCADO PAGO] payment.create result: status={result.get('status')}, code={result.get('status_code')}", 'info')

        if result.get('status') == 201:
            resp = result.get('response', {})
            payment_id = resp.get('id')

            # QR code e EMV estão em point_of_interaction.transaction_data (Pix)
            tx_data = resp.get('point_of_interaction', {}).get('transaction_data', {})
            qr_code = tx_data.get('qr_code', '')
            qr_code_base64 = tx_data.get('qr_code_base64', '')

            _log(f"[MERCADO PAGO] ✅ Pix criado via payment API! ID: {payment_id}, QR len: {len(qr_code)}", 'info')
            return {
                'id': payment_id,
                'qr_code': qr_code,
                'qr_code_base64': qr_code_base64,
                'method': 'payment_api',
            }
    except Exception as e:
        _log(f"[MERCADO PAGO] payment.create falhou: {e}", 'warning')

    # =============================================
    # MÉTODO 2: Preference API (redirecionamento)
    # =============================================
    try:
        import random, string
        ref = f"{order_id}-{''.join(random.choices(string.ascii_lowercase + string.digits, k=8))}"

        preference = {
            "items": [
                {
                    "title": description,
                    "quantity": 1,
                    "unit_price": float(total),
                    "currency_id": "BRL"
                }
            ],
            "payer": {
                "email": email
            },
            "payment_methods": {
                "excluded_payment_types": [
                    {"id": "credit_card"},
                    {"id": "debit_card"},
                    {"id": "ticket"}
                ],
                "installments": 1
            },
            "external_reference": ref,
            "notification_url": os.getenv('MERCADO_PAGO_WEBHOOK_URL', ''),
            "statement_descriptor": "PROBUX",
            "binary_mode": False
        }

        result = sdk.preference().create(preference)
        _log(f"[MERCADO PAGO] preference.create result: status={result.get('status')}", 'info')

        if result.get('status') == 201:
            resp = result.get('response', {})
            payment_id = resp.get('id')
            init_point = resp.get('init_point', '')
            sandbox_init = resp.get('sandbox_init_point', '')

            _log(f"[MERCADO PAGO] ✅ Preferência criada! ID: {payment_id}, init_point: {init_point[:80]}...", 'info')
            return {
                'id': payment_id,
                'qr_code': '',
                'qr_code_base64': '',
                'init_point': init_point,
                'sandbox_init_point': sandbox_init,
                'method': 'preference',
            }
    except Exception as e:
        _log(f"[MERCADO PAGO] preference.create falhou: {e}", 'warning')

    _log(f"[MERCADO PAGO] ❌ Nenhum método de criação de Pix funcionou.", 'error')
    return None


def get_payment_status(payment_id):
    """Consulta o status de um pagamento no Mercado Pago."""
    try:
        sdk = get_mp_sdk()
        if not sdk:
            return None
        result = sdk.payment().get(payment_id)
        _log(f"[MERCADO PAGO] payment.get({payment_id}): status={result.get('status')}", 'debug')
        payment = result.get("response", {})
        return payment.get("status")
    except Exception as e:
        _log(f"[MERCADO PAGO] Erro ao consultar status: {e}", 'error')
        return None


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


def _build_proxy_url(endpoint):
    """
    Constrói a URL para passar pelo Cloudflare Worker proxy.
    Formato: PROXY_URL?url=ENCODED_TARGET_URL
    """
    target_url = f"https://api.roblox.com{endpoint}"
    encoded = urllib.parse.quote(target_url, safe='')
    return f"{ROBLOX_PROXY_URL}?url={encoded}"


def _resolve_domain(endpoint):
    """Resolve o subdomínio correto do Roblox baseado no endpoint."""
    if endpoint.startswith('http'):
        # URL completa - extrai o domínio
        try:
            parsed = urllib.parse.urlparse(endpoint)
            return parsed.netloc  # ex: catalog.roblox.com
        except Exception:
            return 'api.roblox.com'
    # Paths relativos - mapeia por prefixo
    if endpoint.startswith('/v1/users/'):
        return 'users.roblox.com'
    if endpoint.startswith('/v2/users/'):
        return 'economy.roblox.com'
    if endpoint.startswith('/v1/user/currency') or endpoint.startswith('/v1/user/balance'):
        return 'economy.roblox.com'
    if endpoint.startswith('/v1/catalog/'):
        return 'catalog.roblox.com'
    if endpoint.startswith('/v1/auth/') or endpoint.startswith('/v2/auth/'):
        return 'auth.roblox.com'
    if endpoint.startswith('/v1/purchases/') or endpoint.startswith('/v1/assets/'):
        return 'api.roblox.com'
    if endpoint.startswith('/marketplace/'):
        return 'www.roblox.com'
    return 'api.roblox.com'


def _proxy_request(method, endpoint, headers=None, body=None, timeout=30):
    """
    Envia request através do proxy Node.js (robo-roblox.js).
    Isso permite contornar bloqueios de IP do Roblox.

    O proxy espera:
      POST /proxy com body JSON: { method, url, headers, body, domain }
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

    # Prepara headers HTTP - inclui cookie no header para Cloudflare Worker
    proxy_headers = {'Content-Type': 'application/json'}
    if headers and 'Cookie' in headers:
        cookie_val = headers['Cookie'].replace('.ROBLOSECURITY=', '')
        proxy_headers['x-roblox-cookie'] = cookie_val

    try:
        resp = requests.post(
            proxy_url,
            json=payload,
            headers=proxy_headers,
            timeout=timeout + 10,  # Timeout um pouco maior para incluir overhead do proxy
        )
        # Tenta retornar como JSON
        try:
            return resp.json(), resp.status_code, None
        except Exception:
            return resp.text, resp.status_code, None

    except requests.exceptions.Timeout:
        return None, None, "Timeout ao conectar com proxy"
    except requests.exceptions.ConnectionError as e:
        return None, None, f"Proxy indisponível: {str(e)[:150]}"
    except Exception as e:
        return None, None, f"Erro no proxy: {str(e)[:150]}"


def _roblox_api_request(method, endpoint, session=None, json_data=None, max_retries=3, use_auth=True):
    """
    Faz request para a API do Roblox com retry automático.
    - Se USE_PROXY: usa proxy Node.js (evita bloqueio de IP de hospedagem)
    - Se direto: tenta api.roblox.com, depois catalog.roblox.com como fallback
    """
    # Se proxy está configurado, sempre usa proxy
    if USE_PROXY and ROBLOX_PROXY_URL:
        # Monta headers
        headers = dict(DEFAULT_HEADERS)
        if use_auth and ROBLOX_COOKIE:
            headers['Cookie'] = f'.ROBLOSECURITY={ROBLOX_COOKIE}'
        if method.upper() == 'POST':
            headers['Content-Type'] = 'application/json; charset=UTF-8'

        # Extrai XSRF token da session se disponível (importante para POST)
        if session and hasattr(session, 'headers'):
            xsrf = session.headers.get('X-CSRF-TOKEN')
            if xsrf:
                headers['X-CSRF-TOKEN'] = xsrf
                _log(f'[ROBLOX PROXY] XSRF token incluído: {xsrf[:20]}...', 'debug')

        data, status, error = _proxy_request(method, endpoint, headers, json_data)

        _log(f'[ROBLOX PROXY] {method} {endpoint} → status={status}, error={error}', 'debug')

        # Verifica se o proxy retornou erro de rede (DNS falhou no proxy Node.js)
        proxy_network_error = False
        proxy_ip_banned = False
        if status == 500 and isinstance(data, dict):
            error_msg = str(data.get('message', '')) + str(data.get('error', ''))
            if 'ENOTFOUND' in error_msg or 'getaddrinfo' in error_msg or 'ECONNREFUSED' in error_msg:
                proxy_network_error = True
                _log(f"[ROBLOX PROXY] Proxy retornou erro de rede DNS, tentando conexão direta...", 'warning')

        if error and not proxy_network_error:
            # Erro de conexão com o proxy (timeout, etc) — tentar direto
            _log(f"[ROBLOX PROXY] ❌ Erro de conexão com proxy: {error}", 'warning')
            _log(f"[ROBLOX PROXY] Tentando conexão direta como fallback...", 'info')
        elif status == 403 and not proxy_network_error:
            # IP banido pelo Roblox via proxy — tentar conexão direta
            _log(f"[ROBLOX PROXY] 403 - IP possivelmente banido, tentando conexão direta...", 'warning')
            proxy_ip_banned = True
        elif not proxy_network_error and not proxy_ip_banned:
            # Sem erro de rede — processar resposta normalmente
            if status == 200:
                if isinstance(data, dict):
                    return data, None
                return data, None
            elif status == 401:
                return None, "Não autorizado (401) — cookie expirado"
            elif status == 429:
                return None, "Rate limit (429)"
            elif status == 422:
                if isinstance(data, dict):
                    errors = data.get('errors', [{}])
                    msg = errors[0].get('message', str(data)) if errors else str(data)
                else:
                    msg = str(data)[:200]
                return None, f"Erro validação (422): {msg}"
            else:
                return None, f"HTTP {status}: {str(data)[:300] if data else 'sem resposta'}"

    # === SEM PROXY - conexão direta ===
    if session is None:
        session = _create_session(ROBLOX_COOKIE if use_auth else None)

    if method.upper() == 'POST' and use_auth:
        _get_xsrf_token(session)

    last_error = "Erro desconhecido"

    # Define URLs de fallback
    if endpoint.startswith('/v1/') or endpoint.startswith('/v2/'):
        urls = [
            f"https://api.roblox.com{endpoint}",
            f"https://catalog.roblox.com{endpoint}",
        ]
    elif endpoint.startswith('/marketplace/'):
        urls = [
            f"https://www.roblox.com{endpoint}",
        ]
    else:
        urls = [f"https://api.roblox.com{endpoint}"]

    for url_idx, base_url in enumerate(urls):
        for attempt in range(1, max_retries + 1):
            try:
                if method.upper() == 'POST':
                    resp = session.post(
                        base_url,
                        json=json_data,
                        timeout=30,
                        allow_redirects=True,
                        headers={'Content-Type': 'application/json; charset=UTF-8'}
                    )
                elif method.upper() == 'GET':
                    resp = session.get(
                        base_url,
                        timeout=30,
                        allow_redirects=True
                    )
                else:
                    resp = session.request(
                        method.upper(),
                        base_url,
                        json=json_data,
                        timeout=30,
                        allow_redirects=True
                    )

                _log(f"[ROBLOX] {method} {base_url[:80]} | Status: {resp.status_code} | T:{attempt}", 'debug')

                if resp.status_code == 200:
                    try:
                        return resp.json(), None
                    except Exception:
                        return resp.text, None
                elif resp.status_code == 403:
                    _log(f"[ROBLOX] 403 em {base_url[:60]}", 'warning')
                    if url_idx < len(urls) - 1:
                        _log(f"[ROBLOX] Tentando URL alternativa...", 'info')
                        break
                    return None, "Acesso negado (403) — cookie inválido ou IP bloqueado"
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
                    _log(f"[ROBLOX] {error_msg}", 'error')
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
                    return None, f"Erro validação (422): {error_msg}"
                elif resp.status_code >= 502:
                    wait = attempt * 3
                    _log(f"[ROBLOX] Gateway error ({resp.status_code}), esperando {wait}s...", 'warning')
                    time.sleep(wait)
                    last_error = f"HTTP {resp.status_code}"
                    continue
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


def _proxy_api_request(endpoint, headers=None, timeout=15):
    """Faz request via proxy Node.js (se configurado). Retorna (data, status, error)."""
    if not USE_PROXY or not ROBLOX_PROXY_URL:
        return None, None, "Proxy não configurado"
    return _proxy_request('GET', endpoint, headers=headers or {}, timeout=timeout)


def verify_roblox_cookie(cookie=None):
    """
    Verifica se o cookie do Roblox é válido usando múltiplos métodos.
    Prefere proxy Node.js quando disponível (evita bloqueio de IP).
    Retorna (is_valid, error_message).
    """
    if not cookie:
        return False, "Cookie não fornecido"

    # Limpa o cookie
    cookie = cookie.strip()

    # === MÉTODO 1: Via proxy Node.js (PREFERENCIAL) ===
    if USE_PROXY and ROBLOX_PROXY_URL:
        proxy_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Cookie': f'.ROBLOSECURITY={cookie}',
        }

        # Testa users API via proxy
        data, status, err = _proxy_api_request(
            '/v1/users/authenticated',
            headers=proxy_headers,
            timeout=15
        )
        if status == 200 and isinstance(data, dict):
            user_id = data.get('id')
            username = data.get('name', 'Unknown')
            _log(f"[ROBLOX] Cookie VÁLIDO via proxy! Usuário: {username} (ID: {user_id})", 'info')
            return True, None
        elif status == 401:
            _log(f"[ROBLOX] Cookie inválido via proxy (401)", 'warning')
            return False, "Cookie inválido (401 via proxy)"
        elif status == 403:
            _log(f"[ROBLOX] Proxy retornou 403 — possivelmente IP bloqueado no proxy também", 'warning')
        else:
            _log(f"[ROBLOX] Proxy users API: status {status}, erro: {err}", 'warning')

        # Testa catalog API via proxy
        data2, status2, err2 = _proxy_api_request(
            '/v1/catalog/items/details',
            headers={**proxy_headers, 'Content-Type': 'application/json'},
            timeout=15
        )
        if status2 == 200:
            _log(f"[ROBLOX] Cookie VÁLIDO via proxy (Catalog OK)!", 'info')
            return True, None
        elif status2 in [401, 403]:
            _log(f"[ROBLOX] Proxy catalog: {status2} — cookie provavelmente inválido", 'warning')
            return False, f"Cookie inválido ou IP bloqueado (status {status2} via proxy)"

        # Se proxy falhar completamente, tenta direto abaixo

    # === MÉTODO 2: Conexão direta (sem proxy) ===
    import requests as req_lib
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
            _log(f"[ROBLOX] Acesso negado (403) — IP possívelmente bloqueado", 'warning')
    except Exception as e:
        _log(f"[ROBLOX] Error na users API: {e}", 'warning')

    # Método fallback: página HTML
    session2 = _create_session(cookie, use_homepage_headers=True)
    try:
        resp = session2.get('https://www.roblox.com/my/account', timeout=15, allow_redirects=True)
        if resp.status_code == 200 and 'Log In' not in resp.text and 'login' not in resp.url.lower():
            _log(f"[ROBLOX] Cookie VÁLIDO via página de conta!", 'info')
            return True, None
        elif resp.status_code == 200 and 'Log In' in resp.text:
            _log(f"[ROBLOX] Cookie inválido - página redirecionou para login", 'warning')
    except Exception as e:
        _log(f"[ROBLOX] Error ao verificar via página: {e}", 'warning')

    return False, "Cookie inválido, expirado ou IP bloqueado. Renove o cookie, use proxy ou tente de outro IP."


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

    session = _create_session(roblox_cookie)

    # Verifica preço via catálogo (apenas se expected_price informado)
    if expected_price:
        data, err = _roblox_api_request(
            'POST', '/v1/catalog/items/details',
            session=session,
            json_data={'items': [{'id': int(gamepass_id), 'itemType': 'GamePass'}]},
            max_retries=1
        )
        if data and isinstance(data, dict) and 'data' in data:
            items = data['data']
            if items and isinstance(items, list) and len(items) > 0:
                actual_price = items[0].get('price') or items[0].get('priceInRobux')
                _log(f"[GAMEPASS] Preço real: {actual_price} Robux", 'debug')
                if actual_price and int(actual_price) != int(expected_price):
                    _log(f"[GAMEPASS] ⚠️ Preço diferente: esperado {expected_price}, real {actual_price}", 'warning')

    # ============================================
    # TENTATIVA DE COMPRA — múltiplos endpoints
    # ============================================
    endpoints_compra = [
        ('/v1/purchases/game-pass/{id}', 'api.roblox.com'),
        ('/v1/purchases/game-pass/{id}', 'catalog.roblox.com'),
        ('/marketplace/game-pass/{id}', 'www.roblox.com'),
    ]

    ultimo_erro = None

    for endpoint_tpl, domain in endpoints_compra:
        endpoint = endpoint_tpl.replace('{id}', str(gamepass_id))
        _log(f"[GAMEPASS] Tentando compra via {domain}{endpoint}...", 'info')

        data, err = _roblox_api_request(
            'POST', endpoint,
            session=session,
            json_data={'expectedPrice': int(expected_price) if expected_price else 1},
            max_retries=2,
        )

        if data and isinstance(data, dict) and data.get('success'):
            _log(f"[GAMEPASS] ✅ COMPRA SUCEDIDA via {domain}! Gamepass {gamepass_id}", 'info')
            return (True, f"Gamepass {gamepass_id} comprada com sucesso via {domain}!")

        if err:
            ultimo_erro = err
            _log(f"[GAMEPASS] ❌ Falha via {domain}: {err}", 'warning')
            # Se o erro for 403 (banido), tentar próximo endpoint
            if '403' in str(err) or 'banido' in str(err).lower():
                continue
            # Se for erro de rede sem proxy, próximo endpoint pode funcionar
            if 'ENOTFOUND' in str(err) or 'getaddrinfo' in str(err):
                continue

    # Nenhum endpoint funcionou
    msg_erro = ultimo_erro or "Todos os endpoints de compra falharam"
    _log(f"[GAMEPASS] ❌ FALHA em todos os endpoints: {msg_erro}", 'error')
    return (False, msg_erro)


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

    if all_success:
        order.delivered = True
        order.delivered_at = datetime.utcnow()
        order.status = 'delivered'
        order.delivery_attempted = True
    else:
        order.status = 'paid'
        # Permite retry em caso de falha parcial
        # delivery_attempted so e setado quando TODOS os itens foram entregues

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