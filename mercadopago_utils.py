import mercadopago
import os
import re
import requests
import time
import json
import logging
import socket
import ssl
import struct
from datetime import datetime
from urllib3.util.connection import allowed_gai_family

# Configurações do Mercado Pago
MP_ACCESS_TOKEN = os.getenv('MERCADO_PAGO_ACCESS_TOKEN', '')
ROBLOX_COOKIE = os.getenv('ROBLOX_COOKIE', '')

# Arquivo de log local
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs', 'delivery.log')

# Logger
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(atime)s - %(message)s')

# ============================================================
# Mapeamento de IPs diretos (evita necessidade de DNS)
# Atualize periodicamente com: nslookup api.roblox.com
# ============================================================
# api.roblox.com -> Fastly CDN (IP pode mudar)
# Economytest é alternativa para testes
ROBLOX_API_IP = os.getenv('ROBLOX_API_IP', 'api.roblox.com')  # Se DNS bloquear, use IP direto
ECONOMY_API_IP = os.getenv('ECONOMY_API_IP', 'economy.roblox.com')

# Mercado Pago API
MP_API_HOST = os.getenv('MP_API_HOST', 'api.mercadopago.com')


def _ensure_log_dir():
    os.makedirs(os.path.dirname(LOG_FILE) if os.path.dirname(LOG_FILE) else 'logs', exist_ok=True)


def _log(message):
    _ensure_log_dir()
    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    log_line = f"[{timestamp}] {message}"
    print(log_line, flush=True)
    logger.info(message)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_line + '\n')
    except Exception:
        pass


# ============================================================
# SOLUÇÃO DNS: Usa DOH (DNS over HTTPS) para resolver nomes
# Funciona mesmo quando DNS tradicional está bloqueado
# ============================================================
def _resolve_via_doh(hostname):
    """Resolve hostname usando DNS over HTTPS (Cloudflare)."""
    try:
        doh_url = f"https://cloudflare-dns.com/dns-query?name={hostname}&type=A"
        resp = requests.get(doh_url, timeout=5, headers={
            'Accept': 'application/dns-json'
        })
        if resp.status_code == 200:
            data = resp.json()
            answers = data.get('Answer', [])
            if answers:
                ip = answers[0].get('data', '')
                _log(f"[DNS] {hostname} -> {ip} (via DOH)")
                return ip
    except Exception as e:
        _log(f"[DNS] DOH falhou para {hostname}: {e}")
    return None


def _requests_session_with_dns():
    """Cria sessão requests que resolve DNS via DOH."""
    session = requests.Session()

    # Monkey-patch para resolver DNS via DOH
    original_send = session.send

    def patched_send(request, **kwargs):
        # Resolve o hostname antes
        parsed_url = request.url.replace('https://', '').replace('http://', '').split('/')[0]
        if ':' in parsed_url:
            hostname = parsed_url.split(':')[0]
        else:
            hostname = parsed_url

        if hostname and not hostname[0].isdigit():
            ip = _resolve_via_doh(hostname)
            if ip:
                # Substitui o host no URL pelo IP
                new_url = request.url.replace(hostname, ip, 1)
                request.prepare_url(new_url, {})
                # Adiciona header Host original
                request.headers['Host'] = hostname
                _log(f"[DNS] Usando IP {ip} para {hostname}")

        return original_send(request, **kwargs)

    session.send = patched_send
    return session


# Cache da sessão
_roblox_session = None


def _get_roblox_session():
    global _roblox_session
    if _roblox_session is None:
        cookie = ROBLOX_COOKIE or os.getenv('ROBLOX_COOKIE', '')
        _roblox_session = requests.Session()

        if cookie:
            _roblox_session.cookies.set('.ROBLOSECURITY', cookie, domain='.roblox.com')

        _roblox_session.headers.update({
            'User-Agent': 'Roblox/WinInet',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        })

        # Tenta obter X-CSRF
        try:
            resp = _roblox_session.post(
                f'https://{ECONOMY_API_IP}/v2/logout',
                json={}, timeout=10
            )
            xsrf = resp.headers.get('X-CSRF-TOKEN')
            if xsrf:
                _roblox_session.headers['X-CSRF-TOKEN'] = xsrf
                _log(f"[ROBLOX] X-CSRF obtido")
        except Exception as e:
            _log(f"[ROBLOX] CSRF tentativa: {e}")

    return _roblox_session


def get_mp_sdk():
    if not MP_ACCESS_TOKEN:
        _log("[MP] Token não configurado!")
        return None
    try:
        sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
        _log("[MP] SDK inicializado")
        return sdk
    except Exception as e:
        _log(f"[MP] Erro SDK: {e}")
        return None


def create_pix_payment(amount, description, order_id, payer_email=None):
    """Cria pagamento PIX via Mercado Pago API REST direta (sem SDK se necessário)."""
    if not MP_ACCESS_TOKEN:
        _log("[MP] Token não configurado!")
        return None

    _log(f"[MP] Criando PIX: R$ {amount:.2f} | Order #{order_id}")

    payload = {
        "transaction_amount": float(amount),
        "description": description,
        "payment_method_id": "pix",
        "payer": {"email": payer_email or "test@test.com"},
        "external_reference": str(order_id),
    }

    webhook = os.getenv('MERCADO_PAGO_WEBHOOK_URL', '')
    if webhook:
        payload["notification_url"] = webhook
        _log(f"[MP] Webhook: {webhook[:60]}...")

    # Tenta com SDK primeiro
    try:
        sdk = get_mp_sdk()
        if sdk:
            resp = sdk.payment().create(payload)
            _log(f"[MP] SDK Response: {json.dumps(resp, indent=2, default=str)[:2000]}")

            if isinstance(resp, dict):
                if "response" in resp:
                    data = resp["response"]
                else:
                    data = resp

                if "id" in data:
                    qr_data = data.get("point_of_interaction", {}).get("transaction_data", {})
                    return {
                        "id": str(data["id"]),
                        "status": data.get("status", "pending"),
                        "qr_code": qr_data.get("qr_code", ""),
                        "qr_code_base64": qr_data.get("qr_code_base64", ""),
                        "ticket_url": qr_data.get("ticket_url", ""),
                    }
            else:
                _log(f"[MP] SDK retornou tipo inesperado: {type(resp)}")
    except Exception as e:
        _log(f"[MP] SDK falhou: {e}")

    # Fallback: REST direto
    try:
        headers = {
            "Authorization": f"Bearer {MP_ACCESS_TOKEN}",
            "Content-Type": "application/json",
            "X-Idempotency-Key": str(order_id),
            "Accept": "application/json",
        }

        _log(f"[MP] Tentando REST direto para api.mercadopago.com...")
        resp = requests.post(
            "https://api.mercadopago.com/v1/payments",
            headers=headers,
            json=payload,
            timeout=30
        )

        _log(f"[MP] REST Response [{resp.status_code}]: {resp.text[:1500]}")

        if resp.status_code == 200 or resp.status_code == 201:
            data = resp.json()
            if "id" in data:
                qr_data = data.get("point_of_interaction", {}).get("transaction_data", {})
                return {
                    "id": str(data["id"]),
                    "status": data.get("status", "pending"),
                    "qr_code": qr_data.get("qr_code", ""),
                    "qr_code_base64": qr_data.get("qr_code_base64", ""),
                    "ticket_url": qr_data.get("ticket_url", ""),
                }
            else:
                _log(f"[MP] REST 200 sem 'id': chaves={list(data.keys())}")
                return None
        elif resp.status_code == 401:
            _log(f"[MP] ❌ 401 Unauthorized — Token inválido!")
            return None
        else:
            _log(f"[MP] REST erro {resp.status_code}: {resp.text[:300]}")
            return None

    except requests.exceptions.ConnectionError:
        _log(f"[MP] ❌ Conexão bloqueada — DNS/IP inacessível no plano gratuito")
        return None
    except Exception as e:
        _log(f"[MP] REST falhou: {e}")
        return None


def get_payment_status(payment_id):
    if not MP_ACCESS_TOKEN:
        return None

    sdk = get_mp_sdk()
    if sdk:
        try:
            info = sdk.payment().get(payment_id)
            if isinstance(info, dict) and "response" in info:
                return info["response"].get("status")
            elif isinstance(info, dict):
                return info.get("status")
        except Exception as e:
            _log(f"[MP] SDK get error: {e}")

    # Fallback REST
    try:
        headers = {
            "Authorization": f"Bearer {MP_ACCESS_TOKEN}",
            "Accept": "application/json",
        }
        resp = requests.get(
            f"https://api.mercadopago.com/v1/payments/{payment_id}",
            headers=headers, timeout=15
        )
        if resp.status_code == 200:
            return resp.json().get("status")
    except Exception as e:
        _log(f"[MP] REST get status error: {e}")
    return None


def buy_gamepass_with_cookie(gamepass_link, roblox_cookie, expected_price=None, max_retries=3):
    """Compra gamepass via API REST do Roblox (sem DNS se IP configurado)."""
    if not roblox_cookie:
        return (False, "Cookie do Roblox não configurado")

    match = re.search(r'game-pass/(\d+)', gamepass_link)
    if not match:
        return (False, "Link da Gamepass inválido")

    gamepass_id = match.group(1)
    last_error = "Erro desconhecido"

    _log(f"[GAMEPASS] Iniciando compra: gamepass_id={gamepass_id}, max_retries={max_retries}")

    for attempt in range(1, max_retries + 1):
        try:
            session = _get_roblox_session()

            # Endpoint alternativo que pode funcionar melhor
            urls_to_try = [
                f'https://{ROBLOX_API_IP}/v1/purchases/game-pass/{gamepass_id}',
                f'https://economy.roblox.com/v1/purchases/game-pass/{gamepass_id}',
                f'https://{ECONOMY_API_IP}/v1/purchases/game-pass/{gamepass_id}',
            ]

            success = False
            for url in urls_to_try:
                try:
                    _log(f"[GAMEPASS] Tentativa {attempt}: POST {url}")
                    resp = session.post(
                        url,
                        json={'expectedPrice': int(expected_price) if expected_price else 1},
                        timeout=30
                    )
                    _log(f"[GAMEPASS] Response [{resp.status_code}]: {resp.text[:300]}")

                    if resp.status_code == 200:
                        try:
                            data = resp.json()
                            if data.get('success'):
                                _log(f"[GAMEPASS] ✅ COMPRA SUCEDIDA!")
                                return (True, f"Gamepass {gamepass_id} comprada via API!")
                            else:
                                last_error = data.get('error', data.get('errorMessage', 'Erro desconhecido'))
                                _log(f"[GAMEPASS] API retornou erro: {last_error}")
                        except Exception:
                            if 'successfully' in resp.text.lower() or 'purchased' in resp.text.lower():
                                return (True, "Gamepass comprada!")
                            last_error = f"Resposta inválida: {resp.text[:200]}"

                    elif resp.status_code == 403:
                        last_error = "Acesso negado (403) — cookie inválido ou IP bloqueado"
                        _log(f"[GAMEPASS] 403 — possivel cookie expirado")
                        break  # Não tentar mais URLs neste attempt

                    elif resp.status_code == 429:
                        last_error = "Rate limit"
                        _log(f"[GAMEPASS] Rate limit, aguardando...")
                        break

                except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                    _log(f"[GAMEPASS] Falha na URL {url}: {e}")
                    last_error = f"Conexão falhou para {url}"
                    continue  # Tenta próxima URL

            if resp.status_code in [403, 429]:
                break  # Não retry para esses erros

            if attempt < max_retries:
                wait = attempt * 3
                _log(f"[GAMEPASS] Aguardando {wait}s antes de tentar novamente...")
                time.sleep(wait)

        except requests.exceptions.Timeout:
            last_error = "Timeout"
        except requests.exceptions.ConnectionError as e:
            last_error = f"Erro de conexão: {e}"
            _log(f"[GAMEPASS] ❌ Conexão falhou: {e}")
            break  # DNS bloqueado = não adianta retry
        except Exception as e:
            last_error = f"Erro: {e}"

    _log(f"[GAMEPASS] ❌ Falha após {max_retries} tentativas: {last_error}")
    return (False, f"{last_error} (tentativas: {max_retries})")


def deliver_gamepasses(order, notify_user=True):
    from models import OrderItem, User
    from extensions import db
    from flask import current_app

    gamepass_items = [item for item in order.items if item.product.is_gamepass]
    if not gamepass_items:
        return (False, "Nenhum item de gamepass no pedido")

    roblox_cookie = current_app.config.get('ROBLOX_COOKIE', '') or os.getenv('ROBLOX_COOKIE', '')
    if not roblox_cookie:
        return (False, "Cookie do Roblox não configurado")

    _log(f"[ENTREGA] Pedido {order.id}: {len(gamepass_items)} itens")
    results = []
    success_count = 0

    for item in gamepass_items:
        if not item.gamepass_link or not item.robux_amount:
            results.append(f"Item {item.id}: dados incompletos")
            continue

        success, msg = buy_gamepass_with_cookie(
            item.gamepass_link, roblox_cookie, item.robux_amount
        )
        results.append(f"Gamepass ({item.robux_amount} Robux): {msg}")
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
    _log(f"[ENTREGA] Pedido {order.id}: {success_count}/{len(gamepass_items)} sucesso")

    # Envia email
    if notify_user:
        try:
            from flask_mail import Message
            from extensions import mail as mail_ext
            user = User.query.get(order.user_id)
            if user:
                if all_success:
                    subject = 'Gamepass Entregue - Probux'
                    body = f'Sua gamepass foi entregue! Pedido #{order.id}'
                else:
                    subject = 'Falha na Entrega - Probux'
                    body = f'Houve erro na entrega do pedido #{order.id}. Tente novamente mais tarde.'
                msg = Message(subject, recipients=[user.email], body=body)
                mail_ext.send(msg)
        except Exception as e:
            _log(f"[EMAIL] Erro: {e}")

    return (all_success, "; ".join(results))