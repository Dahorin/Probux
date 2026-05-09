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


# ===================================================================
# MERCADO PAGO
# ===================================================================
def get_mp_sdk():
    if not MP_ACCESS_TOKEN:
        _log("[MP] Token não configurado!", 'warning')
        return None
    try:
        return mercadopago.SDK(MP_ACCESS_TOKEN)
    except Exception as e:
        _log(f"[MP] Erro SDK: {e}", 'error')
        return None


def create_pix_payment(amount, description, order_id, payer_email=None):
    """Cria um pagamento PIX no Mercado Pago."""
    _log(f"[MP] Criando PIX: R${amount:.2f} | Order #{order_id}", 'info')

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
        resp_data = sdk.payment().create(payload)
        _log(f"[MP] Resposta: {json.dumps(resp_data, indent=2, default=str)[:1000]}", 'debug')

        if not isinstance(resp_data, dict):
            return None

        data = resp_data.get("response", resp_data)
        if "id" not in data:
            _log(f"[MP] ERRO: campo 'id' não encontrado. Chaves: {list(data.keys())}", 'error')
            return None

        qr_data = data.get("point_of_interaction", {}).get("transaction_data", {})
        return {
            "id": str(data["id"]),
            "status": data.get("status", "pending"),
            "qr_code": qr_data.get("qr_code", ""),
            "qr_code_base64": qr_data.get("qr_code_base64", ""),
            "ticket_url": qr_data.get("ticket_url", ""),
        }

    except KeyError as e:
        _log(f"[MP] KeyError: {e} — Token pode estar inválido!", 'error')
    except Exception as e:
        _log(f"[MP] Erro: {type(e).__name__}: {e}", 'error')

    return None


def get_payment_status(payment_id):
    sdk = get_mp_sdk()
    if sdk:
        try:
            info = sdk.payment().get(payment_id)
            data = info.get("response", info) if isinstance(info, dict) else info
            return data.get("status")
        except Exception as e:
            _log(f"[MP] Erro consulta: {e}", 'error')
    return None


# ===================================================================
# PROXY CLOUDFLARE (para contornar bloqueio de IP do Roblox)
# ===================================================================
def _roblox_request(method, endpoint, json_data=None, max_retries=3):
    """
    Faz request para a API do Roblox, usando proxy Cloudflare se configurado.
    """
    headers = {
        'User-Agent': 'Roblox/WinInet',
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    }

    # Monta a URL
    if USE_PROXY:
        # Via Cloudflare Worker
        url = f"{ROBLOX_PROXY_URL}{endpoint}"
        _log(f"[ROBLOX] 🔀 Proxy: {method} {url}", 'debug')
    else:
        # Direto
        url = f"https://api.roblox.com{endpoint}"
        _log(f"[ROBLOX] Direct: {method} {url}", 'debug')

    cookie = ROBLOX_COOKIE or os.getenv('ROBLOX_COOKIE', '')
    if cookie:
        headers['Cookie'] = f'.ROBLOSECURITY={cookie}'

    last_error = "Erro desconhecido"

    for attempt in range(1, max_retries + 1):
        try:
            if method == 'POST':
                resp = requests.post(url, headers=headers, json=json_data, timeout=30)
            elif method == 'GET':
                resp = requests.get(url, headers=headers, timeout=30)
            else:
                resp = requests.request(method, url, headers=headers, json=json_data, timeout=30)

            _log(f"[ROBLOX] Status: {resp.status_code} | Body: {resp.text[:300]}", 'debug')

            if resp.status_code == 200:
                return resp.json(), None
            elif resp.status_code == 403:
                return None, "Acesso negado (403) — cookie inválido ou IP bloqueado"
            elif resp.status_code == 429:
                wait = attempt * 5
                _log(f"[ROBLOX] Rate limit, aguardando {wait}s...", 'warning')
                time.sleep(wait)
                last_error = "Rate limit"
                continue
            else:
                return None, f"HTTP {resp.status_code}: {resp.text[:200]}"

        except requests.exceptions.Timeout:
            last_error = "Timeout"
            _log(f"[ROBLOX] ⏰ Timeout (tentativa {attempt})", 'warning')
        except requests.exceptions.ConnectionError as e:
            last_error = f"Conexão falhou: {str(e)[:100]}"
            _log(f"[ROBLOX] ❌ Conexão (tentativa {attempt}): {last_error}", 'error')
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            _log(f"[ROBLOX] ❌ Erro (tentativa {attempt}): {last_error}", 'error')

        if attempt < max_retries:
            time.sleep(attempt * 2)

    return None, f"{last_error} (falhou após {max_retries} tentativas)"


# ===================================================================
# COMPRA DE GAMEPASS
# ===================================================================
def buy_gamepass_with_cookie(gamepass_link, roblox_cookie, expected_price=None, max_retries=3):
    """Compra gamepass via API do Roblox (com proxy Cloudflare opcional)."""
    global ROBLOX_COOKIE
    ROBLOX_COOKIE = roblox_cookie  # Atualiza cookie global

    if not roblox_cookie:
        return (False, "Cookie do Roblox não configurado")

    match = re.search(r'game-pass/(\d+)', gamepass_link)
    if not match:
        return (False, "Link da Gamepass inválido")

    gamepass_id = match.group(1)

    _log(f"[GAMEPASS] 🎮 Comprando gamepass {gamepass_id} (proxy={'ON' if USE_PROXY else 'OFF'})", 'info')

    # Verifica preço via catálogo
    if expected_price:
        data, err = _roblox_request('POST', '/v1/catalog/items/details', {
            'items': [{'id': int(gamepass_id), 'itemType': 'GamePass'}]
        }, max_retries=1)
        if data and 'data' in data:
            items = data['data']
            if items:
                actual_price = items[0].get('price') or items[0].get('priceInRobux')
                _log(f"[GAMEPASS] Preço real: {actual_price} Robux", 'debug')
                if actual_price and int(actual_price) != int(expected_price):
                    _log(f"[GAMEPASS] ⚠️ Preço diferente: esperado {expected_price}, real {actual_price}", 'warning')

    # Tenta a compra
    data, err = _roblox_request('POST', f'/v1/purchases/game-pass/{gamepass_id}', {
        'expectedPrice': int(expected_price) if expected_price else 1
    }, max_retries=max_retries)

    if data and data.get('success'):
        _log(f"[GAMEPASS] ✅ COMPRA SUCEDIDA! Gamepass {gamepass_id}", 'info')
        return (True, f"Gamepass {gamepass_id} comprada com sucesso!")
    elif data:
        error = data.get('error', data.get('errorMessage', 'Erro desconhecido'))
        _log(f"[GAMEPASS] ❌ API erro: {error}", 'error')
        return (False, f"API erro: {error}")
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
                        f"Houve um erro na entrega do pedido #{order_id}.\n"
                        f"Nossa equipe foi notificada.\n\n"
                        f"— Equipe Probux"
                    )

                msg = Message(subject, recipients=[user.email], body=body)
                mail_ext.send(msg)
        except Exception as e:
            _log(f"[EMAIL] Erro ao enviar: {e}", 'warning')

    return (all_success, "; ".join(results))