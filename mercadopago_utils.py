import mercadopago
import os
import re
import requests
import time
import json
import logging
from datetime import datetime

# Configurações do Mercado Pago
MP_ACCESS_TOKEN = os.getenv('MERCADO_PAGO_ACCESS_TOKEN', '')
ROBLOX_COOKIE = os.getenv('ROBLOX_COOKIE', '')

# Arquivo de log local
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs', 'delivery.log')

# Logger
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')


def _ensure_log_dir():
    """Garante que o diretório de logs existe."""
    os.makedirs(os.path.dirname(LOG_FILE) if os.path.dirname(LOG_FILE) else 'logs', exist_ok=True)


def _log(message):
    """Faz log em arquivo e no print."""
    _ensure_log_dir()
    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    log_line = f"[{timestamp}] {message}"
    print(log_line, flush=True)
    logger.info(message)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_line + '\n')
    except Exception as e:
        print(f"[WARN] Não foi possível salvar log: {e}")


def get_mp_sdk():
    """Retorna o SDK do Mercado Pago inicializado."""
    if not MP_ACCESS_TOKEN:
        _log("[MP] Token não configurado!")
        return None
    try:
        sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
        _log(f"[MP] SDK inicializado com sucesso")
        return sdk
    except Exception as e:
        _log(f"[MP] Erro ao inicializar SDK: {e}")
        return None


def create_pix_payment(amount, description, order_id, payer_email=None):
    """
    Cria um pagamento Pix no Mercado Pago.
    Retorna um dicionário com os dados do pagamento ou None em caso de erro.
    """
    sdk = get_mp_sdk()
    if not sdk:
        return None

    payment_data = {
        "transaction_amount": float(amount),
        "description": description,
        "payment_method_id": "pix",
        "payer": {
            "email": payer_email or "test@test.com"
        },
        "external_reference": str(order_id),
    }

    # Adiciona webhook URL apenas se configurada
    webhook = os.getenv('MERCADO_PAGO_WEBHOOK_URL', '')
    if webhook:
        payment_data["notification_url"] = webhook
        _log(f"[MP] Webhook configurado: {webhook[:50]}...")

    _log(f"[MP] Criando pagamento: R$ {amount:.2f} | Order #{order_id}")
    _log(f"[MP] Dados enviados: {json.dumps(payment_data, indent=2)}")

    try:
        payment_response = sdk.payment().create(payment_data)
        _log(f"[MP] Resposta bruta: {json.dumps(payment_response, indent=2, default=str)[:2000]}")

        # Verifica se a resposta é um dict
        if not isinstance(payment_response, dict):
            _log(f"[MP] ERRO: Resposta não é um dicionário: {type(payment_response)}")
            return None

        # Tenta extrair dados do pagamento
        # Versões mais novas do SDK retornam diretamente os dados
        if "response" in payment_response:
            payment = payment_response["response"]
        elif "id" in payment_response:
            payment = payment_response
        else:
            _log(f"[MP] ERRO: Resposta inesperada - chaves disponíveis: {list(payment_response.keys())}")
            return None

        # Verifica se o pagamento foi criado
        payment_id = payment.get("id")
        if not payment_id:
            _log(f"[MP] ERRO: Campo 'id' não encontrado na resposta")
            _log(f"[MP] Conteúdo da 'response': {json.dumps(payment, indent=2, default=str)[:1000]}")
            return None

        # Extrai dados do QR Code
        qr_data = payment.get("point_of_interaction", {}).get("transaction_data", {})
        qr_code = qr_data.get("qr_code", "")
        qr_code_base64 = qr_data.get("qr_code_base64", "")
        ticket_url = qr_data.get("ticket_url", "")

        status = payment.get("status", "pending")

        _log(f"[MP] ✅ Pagamento criado! ID: {payment_id}, Status: {status}")

        return {
            "id": str(payment_id),
            "status": status,
            "qr_code": qr_code,
            "qr_code_base64": qr_code_base64,
            "ticket_url": ticket_url
        }

    except mercadopago.exceptions.MPError as e:
        _log(f"[MP] SDK Error: {type(e).__name__}: {e}")
        return None
    except KeyError as e:
        _log(f"[MP] KeyError ao processar resposta: {e}")
        _log(f"[MP] Verifique se o token de acesso está correto e ativo")
        return None
    except Exception as e:
        _log(f"[MP] Erro inesperado: {type(e).__name__}: {e}")
        return None


def get_payment_status(payment_id):
    """
    Consulta o status de um pagamento no Mercado Pago.
    Retorna o status do pagamento ou None em caso de erro.
    """
    sdk = get_mp_sdk()
    if not sdk:
        return None

    try:
        payment_info = sdk.payment().get(payment_id)
        _log(f"[MP] Consulta pagamento {payment_id}: {json.dumps(payment_info, indent=2, default=str)[:500]}")

        if isinstance(payment_info, dict) and "response" in payment_info:
            status = payment_info["response"].get("status")
        elif isinstance(payment_info, dict) and "status" in payment_info:
            status = payment_info["status"]
        else:
            _log(f"[MP] Resposta inesperada para get_payment: {type(payment_info)}")
            status = None

        _log(f"[MP] Status do pagamento {payment_id}: {status}")
        return status

    except mercadopago.exceptions.MPError as e:
        _log(f"[MP] SDK Error ao consultar: {type(e).__name__}: {e}")
        return None
    except Exception as e:
        _log(f"[MP] Erro ao consultar pagamento {payment_id}: {type(e).__name__}: {e}")
        return None


def _get_xcsrf_token(roblox_cookie):
    """Obtém o token X-CSRF do Roblox."""
    session = requests.Session()
    session.cookies.set('.ROBLOSECURITY', roblox_cookie, domain='.roblox.com')
    session.headers.update({
        'User-Agent': 'Roblox/WinInet',
        'Accept': 'application/json',
    })

    try:
        resp = session.post(
            'https://auth.roblox.com/v2/logout',
            json={},
            timeout=10
        )
        token = resp.headers.get('X-CSRF-TOKEN')
        if token:
            return token
    except Exception as e:
        _log(f"[ROBLOX] Erro ao obter X-CSRF: {e}")

    return None


def _create_roblox_session(roblox_cookie):
    """Cria uma sessão requests autenticada com o Roblox."""
    session = requests.Session()
    session.cookies.set('.ROBLOSECURITY', roblox_cookie, domain='.roblox.com')

    csrf_token = _get_xcsrf_token(roblox_cookie)
    if csrf_token:
        session.headers['X-CSRF-TOKEN'] = csrf_token

    session.headers.update({
        'User-Agent': 'Roblox/WinInet',
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    })

    return session


def buy_gamepass_with_cookie(gamepass_link, roblox_cookie, expected_price=None, max_retries=3):
    """
    Compra uma Gamepass usando a API do Roblox diretamente (Python puro).
    Com retry automático em caso de falha.
    Retorna uma tupla (sucesso, mensagem).
    """
    if not roblox_cookie:
        return (False, "Cookie do Roblox não configurado")

    match = re.search(r'game-pass/(\d+)', gamepass_link)
    if not match:
        return (False, "Link da Gamepass inválido")

    gamepass_id = match.group(1)
    last_error = "Erro desconhecido"

    for attempt in range(1, max_retries + 1):
        try:
            _log(f"[GAMEPASS] Tentativa {attempt}/{max_retries} - Gamepass {gamepass_id}")

            session = _create_roblox_session(roblox_cookie)

            # Verifica preço via catálogo
            if expected_price:
                try:
                    catalog_resp = session.post(
                        'https://catalog.roblox.com/v1/catalog/items/details',
                        json={'items': [{'id': int(gamepass_id), 'itemType': 'GamePass'}]},
                        timeout=15
                    )
                    if catalog_resp.status_code == 200:
                        items = catalog_resp.json().get('data', [])
                        if items:
                            actual_price = items[0].get('price') or items[0].get('priceInRobux')
                            _log(f"[GAMEPASS] Preço real: {actual_price} Robux")
                except Exception as e:
                    _log(f"[GAMEPASS] Aviso: não foi verificar preço: {e}")

            # Tenta a compra pela API
            purchase_url = f'https://api.roblox.com/v1/purchases/game-pass/{gamepass_id}'
            payload = {'expectedPrice': int(expected_price) if expected_price else 1}

            resp = session.post(purchase_url, json=payload, timeout=30)
            _log(f"[GAMEPASS] API Response: {resp.status_code} - {resp.text[:300]}")

            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if data.get('success'):
                        _log(f"[GAMEPASS] ✅ COMPRA BEM SUCEDIDA!")
                        return (True, f"Gamepass {gamepass_id} comprada com sucesso via API!")
                    else:
                        error_msg = data.get('error', data.get('errorMessage', 'Erro desconhecido'))
                        last_error = f"Falha: {error_msg}"
                except Exception:
                    if 'successfully' in resp.text.lower() or 'purchased' in resp.text.lower():
                        return (True, f"Gamepass comprada!")
                    last_error = f"Resposta inesperada: {resp.text[:200]}"

            elif resp.status_code == 403:
                _log(f"[GAMEPASS] 403 - Possível bloqueio de IP ou cookie inválido")
                last_error = "Acesso negado (403). IP pode estar bloqueado ou cookie expirado."
                if attempt < max_retries:
                    time.sleep(attempt * 5)
                    continue
                break

            elif resp.status_code == 429:
                wait_time = attempt * 10
                _log(f"[GAMEPASS] Rate limit! Aguardando {wait_time}s...")
                time.sleep(wait_time)
                if attempt < max_retries:
                    continue
                last_error = "Rate limit excedido"
                break

            elif resp.status_code in [400, 404, 422]:
                last_error = f"Erro HTTP {resp.status_code}: {resp.text[:300]}"
                break

            else:
                last_error = f"Erro HTTP {resp.status_code}: {resp.text[:200]}"
                if attempt < max_retries:
                    time.sleep(attempt * 3)
                    continue
                break

        except requests.exceptions.Timeout:
            last_error = "Timeout na API do Roblox"
            if attempt < max_retries:
                time.sleep(attempt * 3)
                continue
            break

        except requests.exceptions.ConnectionError as e:
            last_error = f"Erro de conexão: {e}"
            if attempt < max_retries:
                time.sleep(attempt * 5)
                continue
            break

        except Exception as e:
            last_error = f"Erro: {str(e)}"
            break

    _log(f"[GAMEPASS] ❌ Falha após {max_retries} tentativas: {last_error}")
    return (False, f"{last_error} (tentativas: {max_retries})")


def _send_notification_email(user_email, order_id, success, message):
    """Envia email de notificação sobre a entrega."""
    try:
        from flask import current_app
        from flask_mail import Message
        from extensions import mail as mail_ext
        from models import User
        from extensions import db

        user = User.query.filter_by(email=user_email).first()
        if not user:
            return

        if success:
            subject = 'Gamepass Entregue - Probux'
            body = f'''Olá {user.username},

Sua gamepass foi entregue com sucesso!

Pedido: #{order_id}
Data de entrega: {datetime.utcnow().strftime('%d/%m/%Y às %H:%M')}

Agora você já pode usar sua gamepass no Roblox!

IMPORTANTE: Verifique se os Robux estão pendentes em:
https://www.roblox.com/transactions

Atenciosamente,
Equipe Probux
'''
        else:
            subject = 'Falha na Entrega - Probux'
            body = f'''Olá {user.username},

Houve um problema na entrega da sua gamepass do pedido #{order_id}.

Erro: {message}

Nossa equipe está ciente do problema e tentará novamente.

Atenciosamente,
Equipe Probux
'''

        msg = Message(subject, recipients=[user_email], body=body)
        mail_ext.send(msg)
        _log(f"[EMAIL] Notificação enviada para {user_email}")

    except Exception as e:
        _log(f"[EMAIL] Erro ao enviar email: {e}")


def deliver_gamepasses(order, notify_user=True):
    """
    Entrega as Gamepasses de um pedido após pagamento confirmado.
    Usa a API do Roblox diretamente (Python puro).
    Retorna uma tupla (sucesso, mensagem).
    """
    from models import OrderItem, User
    from extensions import db
    from flask import current_app

    gamepass_items = [item for item in order.items if item.product.is_gamepass]

    if not gamepass_items:
        return (False, "Nenhum item de gamepass no pedido")

    roblox_cookie = current_app.config.get('ROBLOX_COOKIE', '') or os.getenv('ROBLOX_COOKIE', '')

    if not roblox_cookie:
        _log("[ENTREGA] ❌ Cookie do Roblox não configurado!")
        return (False, "Cookie do Roblox não configurado no ambiente")

    _log(f"[ENTREGA] 🚀 Iniciando entrega do pedido {order.id} ({len(gamepass_items)} itens)")
    results = []
    success_count = 0

    for item in gamepass_items:
        gamepass_link = item.gamepass_link
        robux_amount = item.robux_amount

        if not gamepass_link:
            results.append(f"Item {item.id}: Link da gamepass não informado")
            continue

        if not robux_amount:
            results.append(f"Item {item.id}: Preço em Robux não informado")
            continue

        success, msg = buy_gamepass_with_cookie(gamepass_link, roblox_cookie, expected_price=robux_amount)
        results.append(f"Gamepass ({robux_amount} Robux): {msg}")

        if success:
            success_count += 1
            _log(f"[ENTREGA] ✅ Item {item.id}: OK")
        else:
            _log(f"[ENTREGA] ❌ Item {item.id}: {msg}")

    all_success = (success_count == len(gamepass_items)) and (len(gamepass_items) > 0)

    if all_success:
        order.delivered = True
        order.delivered_at = datetime.utcnow()
        order.status = 'delivered'
        db.session.commit()
        _log(f"[ENTREGA] ✅ Pedido {order.id}: TODAS entregues!")
        if notify_user:
            _send_notification_email(order.user.email, order.id, True, "")
    else:
        order.status = 'paid'
        db.session.commit()
        failed_count = len(gamepass_items) - success_count
        _log(f"[ENTREGA] ⚠️ Pedido {order.id}: {success_count}/{len(gamepass_items)} sucesso, {failed_count} falha(s)")
        if notify_user and failed_count > 0:
            failure_msg = "; ".join([r for r in results if "sucesso" not in r.lower()])
            _send_notification_email(order.user.email, order.id, False, failure_msg[:500])

    return (all_success, "; ".join(results))