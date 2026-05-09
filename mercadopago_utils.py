import mercadopago
import os
import re
import requests
import time
import json
import logging
import socket
from datetime import datetime

# ===================================================================
# CONFIGURAÇÃO DO MERCADO PAGO
# ===================================================================
MP_ACCESS_TOKEN = os.getenv('MERCADO_PAGO_ACCESS_TOKEN', '')
ROBLOX_COOKIE = os.getenv('ROBLOX_COOKIE', '')

# Variáveis para controlar conexão direta por IP
ROBLOX_API_IP = os.getenv('ROBLOX_API_IP', 'api.roblox.com')
ECONOMY_API_IP = os.getenv('ECONOMY_API_IP', 'api.roblox.com')

# ===================================================================
# LOGGING — Corrigido: asctime (não "atime")
# ===================================================================
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs', 'delivery.log')

logger = logging.getLogger('probux_delivery')
logger.setLevel(logging.DEBUG)

# Console handler
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
ch.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
logger.addHandler(ch)

# File handler
def _ensure_log_dir():
    os.makedirs(os.path.dirname(LOG_FILE) if os.path.dirname(LOG_FILE) else 'logs', exist_ok=True)

try:
    _ensure_log_dir()
    fh = logging.FileHandler(LOG_FILE, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
    logger.addHandler(fh)
except Exception as e:
    print(f"[WARN] Não foi possível criar log file: {e}")


def _log(msg, level='info'):
    """Log helper que não falha."""
    try:
        if level == 'info':
            logger.info(msg)
        elif level == 'error':
            logger.error(msg)
        elif level == 'warning':
            logger.warning(msg)
        elif level == 'debug':
            logger.debug(msg)
    except Exception:
        print(f"[{level.upper()}] {msg}", flush=True)


# ===================================================================
# TESTE DE REDE — Executado na inicialização
# ===================================================================
def test_network_connectivity():
    """Testa o que está acessível a partir deste container."""
    _log("=" * 50, 'debug')
    _log("INICIANDO TESTE DE REDE", 'debug')
    _log("=" * 50, 'debug')

    tests = [
        ("DNS: google.com", lambda: socket.getaddrinfo('google.com', 443)),
        ("DNS: api.roblox.com", lambda: socket.getaddrinfo('api.roblox.com', 443)),
        ("DNS: api.mercadopago.com", lambda: socket.getaddrinfo('api.mercadopago.com', 443)),
        ("DNS: cloudflare-dns.com", lambda: socket.getaddrinfo('cloudflare-dns.com', 443)),
        ("HTTP: google.com", lambda: requests.get('https://google.com', timeout=5)),
        ("HTTP: api.mercadopago.com", lambda: requests.get('https://api.mercadopago.com/v1/payments/1',
            headers={'Authorization': 'Bearer TEST'}, timeout=5)),
    ]

    results = {}
    for name, test_fn in tests:
        try:
            result = test_fn()
            results[name] = "✅ OK"
            _log(f"{name}: OK", 'debug')
        except socket.gaierror as e:
            results[name] = f"❌ DNS FALHOU: {e}"
            _log(f"{name}: ❌ DNS FALHOU - {e}", 'warning')
        except requests.exceptions.ConnectionError as e:
            results[name] = f"❌ CONEXÃO FALHOU: {e}"
            _log(f"{name}: ❌ CONEXÃO - {e}", 'warning')
        except requests.exceptions.Timeout:
            results[name] = "❌ TIMEOUT"
            _log(f"{name}: ❌ TIMEOUT", 'warning')
        except Exception as e:
            results[name] = f"❌ ERRO: {e}"
            _log(f"{name}: ❌ {type(e).__name__}: {e}", 'warning')

    _log("RESULTADOS DO TESTE DE REDE:", 'debug')
    for name, result in results.items():
        _log(f"  {name}: {result}", 'debug')

    print("\n".join([f"  {name}: {result}" for name, result in results.items()]))
    return results


# Executa teste de rede ao importar
_network_results = test_network_connectivity()


# ===================================================================
# RESOLUÇÃO DNS VIA DOH (DNS over HTTPS)
# ===================================================================
_original_getaddrinfo = socket.getaddrinfo

def _doh_resolve(hostname, family=socket.AF_INET):
    """Resolve hostname usando Cloudflare DNS over HTTPS."""
    try:
        url = f"https://cloudflare-dns.com/dns-query?name={hostname}&type=A"
        if family == socket.AF_INET6:
            url += "&type=AAAA"

        resp = requests.get(url, timeout=5, headers={
            'Accept': 'application/dns-json'
        })

        if resp.status_code == 200:
            data = resp.json()
            answers = data.get('Answer', []) + data.get('answer', [])
            if answers:
                ip = answers[0].get('data', '')
                if ip:
                    _log(f"DOH resolveu: {hostname} -> {ip}", 'debug')
                    return ip
    except Exception as e:
        _log(f"DOH falhou para {hostname}: {e}", 'warning')
    return None


def _patched_getaddrinfo(host, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM,
                         proto=0, flags=0):
    """
    Wrapper que tenta DOH se DNS normal falhar.
    """
    # Primeiro tenta DNS normal
    try:
        return _original_getaddrinfo(host, port, family, type, proto, flags)
    except socket.gaierror:
        pass

    # Se falhou, tenta DOH (mas só para nomes de domínio, não IPs)
    if not host.replace('.', '').isdigit():
        ip = _doh_resolve(host)
        if ip:
            # Tenta novamente com o IP
            try:
                return _original_getaddrinfo(ip, port, family, type, proto, flags)
            except socket.gaierror:
                pass

    raise socket.gaierror(f"Não foi possível resolver '{host}'")


# Aplica o patch DNS
socket.getaddrinfo = _patched_getaddrinfo
_log("Patch de DNS aplicado (DOH fallback habilitado)", 'debug')


# ===================================================================
# MERCADO PAGO FUNCTIONS
# ===================================================================
def get_mp_sdk():
    if not MP_ACCESS_TOKEN:
        _log("Token MP não configurado!", 'warning')
        return None
    try:
        sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
        _log("SDK do MP inicializado", 'debug')
        return sdk
    except Exception as e:
        _log(f"Erro SDK MP: {e}", 'error')
        return None


def create_pix_payment(amount, description, order_id, payer_email=None):
    """Cria um pagamento PIX no Mercado Pago."""
    _log(f"[MP] Criando PIX: R${amount:.2f} Order#{order_id}", 'info')

    sdk = get_mp_sdk()
    if not sdk:
        return None

    payload = {
        "transaction_amount": float(amount),
        "description": description or f"Pedido PROBUX #{order_id}",
        "payment_method_id": "pix",
        "payer": {"email": payer_email or "cliente@probux.com.br"},
        "external_reference": str(order_id),
    }

    webhook = os.getenv('MERCADO_PAGO_WEBHOOK_URL', '')
    if webhook:
        payload["notification_url"] = webhook

    try:
        resp = sdk.payment().create(payload)
        _log(f"[MP] Resposta: {json.dumps(resp, indent=2, default=str)[:1000]}", 'debug')

        if not isinstance(resp, dict):
            _log(f"[MP] ERRO: resposta não é dict: {type(resp)}", 'error')
            return None

        data = resp.get("response", resp)

        if "id" not in data:
            _log(f"[MP] ERRO: 'id' não encontrado. Chaves: {list(data.keys())}", 'error')
            _log(f"[MP] Dados completos: {json.dumps(data, indent=2, default=str)[:500]}", 'error')
            return None

        qr_data = data.get("point_of_interaction", {}).get("transaction_data", {})
        return {
            "id": str(data["id"]),
            "status": data.get("status", "pending"),
            "qr_code": qr_data.get("qr_code", ""),
            "qr_code_base64": qr_data.get("qr_code_base64", ""),
            "ticket_url": qr_data.get("ticket_url", ""),
        }

    except mercadopago.exceptions.MPError as e:
        _log(f"[MP] SDK Error: {e}", 'error')
    except KeyError as e:
        _log(f"[MP] KeyError: {e} — Token pode estar expirado!", 'error')
    except Exception as e:
        _log(f"[MP] Erro: {type(e).__name__}: {e}", 'error')

    return None


def get_payment_status(payment_id):
    sdk = get_mp_sdk()
    if sdk:
        try:
            info = sdk.payment().get(payment_id)
            data = info.get("response", info) if isinstance(info, dict) else info
            status = data.get("status")
            _log(f"[MP] Status {payment_id}: {status}", 'debug')
            return status
        except Exception as e:
            _log(f"[MP] Erro consulta: {e}", 'error')
    return None


# ===================================================================
# ROBLOX — Compra de Gamepass via API REST
# ===================================================================
def _get_roblox_session():
    """Cria sessão autenticada com o Roblox."""
    cookie = ROBLOX_COOKIE or os.getenv('ROBLOX_COOKIE', '')
    if not cookie:
        return None

    session = requests.Session()
    session.cookies.set('.ROBLOSECURITY', cookie, domain='.roblox.com')
    session.headers.update({
        'User-Agent': 'Roblox/WinInet',
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    })

    # Obtém X-CSRF token
    try:
        resp = session.post(
            f'https://{ECONOMY_API_IP}/v2/logout',
            json={}, timeout=10
        )
        xsrf = resp.headers.get('X-CSRF-TOKEN')
        if xsrf:
            session.headers['X-CSRF-TOKEN'] = xsrf
            _log("X-CSRF token obtido", 'debug')
    except Exception as e:
        _log(f"CSRF warning: {e}", 'debug')

    return session


def buy_gamepass_with_cookie(gamepass_link, roblox_cookie, expected_price=None, max_retries=3):
    """Compra gamepass via API do Roblox."""
    if not roblox_cookie:
        return (False, "Cookie do Roblox não configurado")

    match = re.search(r'game-pass/(\d+)', gamepass_link)
    if not match:
        return (False, "Link da Gamepass inválido")

    gamepass_id = match.group(1)
    last_error = "Erro desconhecido"

    # Tenta usar cookie direto na variável de ambiente
    os.environ['ROBLOX_COOKIE'] = roblox_cookie

    _log(f"[GAMEPASS] Comprando gamepass {gamepass_id} (max {max_retries} tentativas)", 'info')

    for attempt in range(1, max_retries + 1):
        session = _get_roblox_session()
        if not session:
            return (False, "Não foi possível criar sessão com o Roblox")

        # Tenta múltiplos endpoints
        endpoints = [
            f'https://{ECONOMY_API_IP}/v1/purchases/game-pass/{gamepass_id}',
            f'https://economy.roblox.com/v1/purchases/game-pass/{gamepass_id}',
        ]

        for endpoint in endpoints:
            try:
                _log(f"[GAMEPASS] T{attempt} → POST {endpoint[:50]}...", 'debug')

                resp = session.post(
                    endpoint,
                    json={'expectedPrice': int(expected_price) if expected_price else 1},
                    timeout=30
                )

                _log(f"[GAMEPASS] Status: {resp.status_code}", 'debug')

                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        if data.get('success'):
                            _log("✅ COMPRA BEM SUCEDIDA!", 'info')
                            return (True, f"Gamepass {gamepass_id} comprada via API!")
                        else:
                            last_error = data.get('error', data.get('errorMessage', 'Erro'))
                            _log(f"[GAMEPASS] API erro: {last_error}", 'warning')
                    except Exception:
                        if any(w in resp.text.lower() for w in ['successfully', 'purchased', 'owned']):
                            return (True, "Gamepass comprada!")
                        last_error = f"Resposta: {resp.text[:200]}"
                elif resp.status_code in [403, 401]:
                    last_error = f"Acesso negado ({resp.status_code}). Cookie possivelmente inválido."
                    _log(f"[GAMEPASS] ❌ {resp.status_code} — cookie inválido", 'warning')
                    return (False, last_error)  # Não tentar mais
                elif resp.status_code == 429:
                    last_error = "Rate limit. Aguardar."
                    break  # Tenta outro endpoint
                else:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    _log(f"[GAMEPASS] {resp.status_code}", 'debug')

            except requests.exceptions.ConnectionError as e:
                last_error = f"Conexão falhou: {str(e)[:100]}"
                _log(f"[GAMEPASS] ❌ ConnectionError: {e}", 'error')
                continue
            except requests.exceptions.Timeout:
                last_error = "Timeout"
                _log(f"[GAMEPASS] ⏰ Timeout", 'debug')
                continue
            except Exception as e:
                last_error = f"Erro: {type(e).__name__}: {e}"
                _log(f"[GAMEPASS] ❌ {type(e).__name__}: {e}", 'error')
                continue

        # Aguarda antes de tentar novamente
        if attempt < max_retries:
            wait = attempt * 3
            _log(f"[GAMEPASS] Aguardando {wait}s...", 'debug')
            time.sleep(wait)

    _log(f"[GAMEPASS] ❌ Falha: {last_error}", 'error')
    return (False, f"{last_error} (após {max_retries} tentativas)")


def _send_email(user_email, order_id, success, message=""):
    """Envia email de notificação."""
    try:
        from flask import current_app
        from flask_mail import Message
        from extensions import mail as mail_ext
        from models import User

        user = User.query.filter_by(email=user_email).first()
        if not user:
            return

        if success:
            subject = 'Gamepass Entregue - Probux'
            body = (f"Olá {user.username},\n\n"
                    f"Sua gamepass foi entregue!\n"
                    f"Pedido: #{order_id}\n"
                    f"Verifique: https://www.roblox.com/transactions\n\n"
                    f"Equipe Probux")
        else:
            subject = 'Falha na Entrega - Probux'
            body = (f"Olá {user.username},\n\n"
                    f"Houve um problema na entrega do pedido #{order_id}.\n"
                    f"Erro: {message}\n\n"
                    f"Tentaremos novamente.\n\n"
                    f"Equipe Probux")

        msg = Message(subject, recipients=[user_email], body=body)
        mail_ext.send(msg)
        _log(f"[EMAIL] Enviado para {user_email}", 'debug')
    except Exception as e:
        _log(f"[EMAIL] Erro: {e}", 'warning')


def deliver_gamepasses(order, notify_user=True):
    """Entrega gamepasses de um pedido."""
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

    _log(f"[ENTREGA] Pedido #{order.id}: {len(gamepass_items)} itens", 'info')

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

    if all_success:
        order.delivered = True
        order.delivered_at = datetime.utcnow()
        order.status = 'delivered'
    else:
        order.status = 'paid'

    db.session.commit()

    _log(f"[ENTREGA] Pedido #{order.id}: {success_count}/{len(gamepass_items)} sucesso", 'info')

    if notify_user:
        _send_email(order.user.email, order.id, all_success,
                    "; ".join(results) if not all_success else "")

    return (all_success, "; ".join(results))