import mercadopago
import os
import re
import requests
from datetime import datetime

# Configurações do Mercado Pago
MP_ACCESS_TOKEN = os.getenv('MERCADO_PAGO_ACCESS_TOKEN', '')
ROBLOX_COOKIE = os.getenv('ROBLOX_COOKIE', '')


def get_mp_sdk():
    """Retorna o SDK do Mercado Pago inicializado."""
    if not MP_ACCESS_TOKEN:
        return None
    return mercadopago.SDK(MP_ACCESS_TOKEN)


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
        "notification_url": os.getenv('MERCADO_PAGO_WEBHOOK_URL', '')
    }

    try:
        payment_response = sdk.payment().create(payment_data)
        payment = payment_response["response"]

        return {
            "id": payment["id"],
            "status": payment["status"],
            "qr_code": payment["point_of_interaction"]["transaction_data"]["qr_code"],
            "qr_code_base64": payment["point_of_interaction"]["transaction_data"]["qr_code_base64"],
            "ticket_url": payment["point_of_interaction"]["transaction_data"].get("ticket_url", "")
        }
    except Exception as e:
        print(f"[MP] Erro ao criar pagamento Pix: {e}")
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
        return payment_info["response"]["status"]
    except Exception as e:
        print(f"[MP] Erro ao consultar pagamento: {e}")
        return None


def _get_xcsrf_token(roblox_cookie):
    """
    Obtém o token X-CSRF necessário para fazer requests autenticados ao Roblox.
    """
    session = requests.Session()
    session.cookies.set('.ROBLOSECURITY', roblox_cookie, domain='.roblox.com')
    session.headers.update({
        'User-Agent': 'Roblox/WinInet',
        'Accept': 'application/json',
    })

    try:
        # O endpoint de logout retorna o token X-CSRF no header
        resp = session.post(
            'https://auth.roblox.com/v2/logout',
            json={},
            timeout=10
        )
        token = resp.headers.get('X-CSRF-TOKEN')
        if token:
            return token
    except Exception as e:
        print(f"[ROBLOX] Erro ao obter X-CSRF token: {e}")

    return None


def _create_roblox_session(roblox_cookie):
    """
    Cria uma sessão requests autenticada com o Roblox.
    """
    session = requests.Session()
    session.cookies.set('.ROBLOSECURITY', roblox_cookie, domain='.roblox.com')

    # Obter X-CSRF token
    csrf_token = _get_xcsrf_token(roblox_cookie)
    if csrf_token:
        session.headers['X-CSRF-TOKEN'] = csrf_token

    session.headers.update({
        'User-Agent': 'Roblox/WinInet',
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    })

    return session


def buy_gamepass_with_cookie(gamepass_link, roblox_cookie, expected_price=None):
    """
    Compra uma Gamepass usando a API do Roblox diretamente (Python puro).
    Sem necessidade de Node.js ou Puppeteer.
    Retorna uma tupla (sucesso, mensagem).
    """
    if not roblox_cookie:
        return (False, "Cookie do Roblox não configurado")

    # Extrai o ID da Gamepass
    match = re.search(r'game-pass/(\d+)', gamepass_link)
    if not match:
        return (False, "Link da Gamepass inválido")

    gamepass_id = match.group(1)

    try:
        print(f"[GAMEPASS] Tentando comprar gamepass {gamepass_id} (preço esperado: {expected_price})")

        session = _create_roblox_session(roblox_cookie)

        # Tenta a API de compra do Roblox
        purchase_url = f'https://api.roblox.com/v1/purchases/game-pass/{gamepass_id}'

        # Primeiro, verifica o preço se possível
        if expected_price:
            try:
                catalog_url = 'https://catalog.roblox.com/v1/catalog/items/details'
                catalog_resp = session.post(
                    catalog_url,
                    json={'items': [{'id': int(gamepass_id), 'itemType': 'GamePass'}]},
                    timeout=15
                )
                if catalog_resp.status_code == 200:
                    data = catalog_resp.json()
                    items = data.get('data', [])
                    if items:
                        actual_price = items[0].get('price') or items[0].get('priceInRobux')
                        if actual_price and actual_price != expected_price:
                            print(f"[GAMEPASS] Preço não coincide: esperado {expected_price}, real {actual_price}")
                            # Continua tentando a compra mesmo assim
            except Exception as e:
                print(f"[GAMEPASS] Aviso: não foi possível verificar preço: {e}")

        # Tenta a compra
        print(f"[GAMEPASS] Chamando API: POST {purchase_url}")
        payload = {'expectedPrice': int(expected_price) if expected_price else 0}

        resp = session.post(purchase_url, json=payload, timeout=30)
        print(f"[GAMEPASS] Status: {resp.status_code}, Body: {resp.text[:500]}")

        if resp.status_code == 200:
            try:
                data = resp.json()
                if data.get('success'):
                    return (True, f"Gamepass {gamepass_id} comprada com sucesso via API!")
                else:
                    error_msg = data.get('error', data.get('errorMessage', 'Erro desconhecido'))
                    return (False, f"Falha na compra: {error_msg}")
            except Exception:
                if 'successfully' in resp.text.lower() or 'purchased' in resp.text.lower():
                    return (True, f"Gamepass {gamepass_id} comprada com sucesso!")
                return (False, f"Resposta inesperada: {resp.text[:200]}")
        elif resp.status_code == 403:
            return (False, "Acesso negado. Cookie pode estar expirado ou inválido.")
        elif resp.status_code == 400:
            return (False, f"Requisição inválida (400): {resp.text[:300]}")
        elif resp.status_code == 429:
            return (False, "Rate limit atingido. Tente novamente mais tarde.")
        else:
            return (False, f"Erro HTTP {resp.status_code}: {resp.text[:200]}")

    except requests.exceptions.Timeout:
        return (False, "Timeout: a API do Roblox demorou muito para responder")
    except requests.exceptions.ConnectionError as e:
        return (False, f"Erro de conexão com a API do Roblox: {e}")
    except Exception as e:
        print(f"[GAMEPASS] Erro geral: {e}")
        return (False, f"Erro ao comprar gamepass: {str(e)}")


def deliver_gamepasses(order, notify_user=True):
    """
    Entrega as Gamepasses de um pedido após pagamento confirmado.
    Usa a API do Roblox diretamente (Python puro - sem Node.js).
    Retorna uma tupla (sucesso, mensagem).
    """
    from models import OrderItem, User, Order
    from extensions import db, mail
    from flask_mail import Message

    # Busca todos os itens do pedido que são gamepass
    gamepass_items = [item for item in order.items if item.product.is_gamepass]

    if not gamepass_items:
        return (False, "Nenhum item de gamepass no pedido")

    roblox_cookie = os.getenv('ROBLOX_COOKIE', '')
    if not roblox_cookie:
        return (False, "Cookie do Roblox não configurado no ambiente")

    # Se tiver cookie nas config do app, usa ele
    from flask import current_app
    app_cookie = current_app.config.get('ROBLOX_COOKIE', '')
    roblox_cookie = app_cookie or roblox_cookie

    print(f"[ENTREGA] Iniciando entrega do pedido {order.id}...")
    results = []
    success_count = 0

    for item in gamepass_items:
        gamepass_link = item.gamepass_link
        robux_amount = item.robux_amount

        if not robux_amount:
            results.append(f"Gamepass: Preço em Robux não informado para item {item.id}")
            continue

        if not gamepass_link:
            results.append(f"Gamepass: Link não informado para item {item.id}")
            continue

        print(f"[ENTREGA] Processando: {gamepass_link} ({robux_amount} Robux)")
        success, msg = buy_gamepass_with_cookie(gamepass_link, roblox_cookie, expected_price=robux_amount)
        results.append(f"Gamepass ({robux_amount} Robux): {msg}")

        if success:
            success_count += 1
            print(f"[ENTREGA] Pedido {order.id}: Gamepass comprada com sucesso!")
        else:
            print(f"[ENTREGA] Pedido {order.id}: Erro ao comprar - {msg}")

    # Marca como entregue no banco (se todas compradas)
    all_success = (success_count == len(gamepass_items)) and (len(gamepass_items) > 0)
    if all_success:
        order.delivered = True
        order.delivered_at = datetime.utcnow()
        order.status = 'delivered'
        db.session.commit()
        print(f"[ENTREGA] Pedido {order.id}: Todas gamepasses entregues! Status: {order.status}")

        # Envia email de notificação para o usuário
        if notify_user:
            try:
                user = User.query.get(order.user_id)
                if user and user.email:
                    msg = Message(
                        'Gamepass Entregue - Probux',
                        recipients=[user.email],
                        body=f'''Olá {user.username},

Sua gamepass foi entregue com sucesso!

Pedido: #{order.id}
Data de entrega: {order.delivered_at.strftime('%d/%m/%Y às %H:%M')}

Agora você já pode usar sua gamepass no Roblox!

IMPORTANTE: Verifique se os Robux estão pendentes em:
https://www.roblox.com/transactions

Atenciosamente,
Equipe Probux
'''
                    )
                    mail.send(msg)
                    print(f"[ENTREGA] Email de confirmação enviado para {user.email}")
            except Exception as e:
                print(f"[ENTREGA] Erro ao enviar email: {e}")
    else:
        # Se falhou, volta o status para 'paid' para tentar novamente
        print(f"[ENTREGA] Pedido {order.id}: Falha na entrega ({success_count}/{len(gamepass_items)} sucesso). Status mantido como 'paid'")
        order.status = 'paid'
        db.session.commit()

    return (all_success, "; ".join(results))