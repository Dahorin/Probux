import mercadopago
import os
import re
import requests
from datetime import datetime

# Configuracoes do Mercado Pago
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
    Retorna um dicionario com os dados do pagamento ou None em caso de erro.
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

def buy_gamepass_with_cookie(gamepass_link, roblox_cookie, expected_price=None):
    """
    Compra uma Gamepass usando o cookie do Roblox.
    Retorna uma tupla (sucesso, mensagem).
    """
    if not roblox_cookie:
        return (False, "Cookie do Roblox nao configurado")

    # Extrai o ID da Gamepass
    match = re.search(r'game-pass/(\d+)', gamepass_link)
    if not match:
        return (False, "Link da Gamepass invalido")

    gamepass_id = match.group(1)

    try:
        s = requests.Session()
        s.cookies.set('.ROBLOSECURITY', roblox_cookie, domain='.roblox.com')
        s.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        })

        # Pega XSRF token
        try:
            r = s.post('https://auth.roblox.com/v2/logout', json={}, timeout=10)
            xsrf = r.headers.get('X-CSRF-TOKEN')
            if xsrf:
                s.headers['X-CSRF-TOKEN'] = xsrf
                print(f"[GAMEPASS] XSRF Token obtido: {xsrf[:20]}...")
        except Exception as e:
            print(f"[GAMEPASS] Erro ao obter XSRF: {e}")

        # Endpoint de compra (não oficial - usa economy.roblox.com)
        print(f"[GAMEPASS] Tentando comprar gamepass {gamepass_id} (preco: {expected_price})")
        # Tenta diferentes endpoints possiveis
        endpoints = [
            f'https://economy.roblox.com/v1/purchases/game-pass/{gamepass_id}/purchase',
            f'https://api.roblox.com/mobile-api/game-pass/{gamepass_id}/purchase',
            f'https://economy.roblox.com/v1/purchases/game-pass/{gamepass_id}/purchase'
        ]

        payload = {}
        if expected_price is not None:
            payload['expectedPrice'] = int(expected_price)

        resp = None
        for purchase_url in endpoints:
            print(f"[GAMEPASS] Tentando endpoint: {purchase_url}")
            try:
                resp = s.post(purchase_url, json=payload, timeout=15)
                print(f"[GAMEPASS] Status: {resp.status_code}")
                print(f"[GAMEPASS] Resposta: {resp.text[:300]}")
                if resp.status_code != 404:
                    break
            except Exception as e:
                print(f"[GAMEPASS] Erro neste endpoint: {e}")
                continue

        if not resp:
            return (False, "Nenhum endpoint funcionou")

        if resp.status_code == 200:
            try:
                data = resp.json()
                if data.get('success'):
                    return (True, f"Gamepass {gamepass_id} comprada com sucesso!")
                else:
                    error_msg = data.get('error', 'Erro desconhecido')
                    return (False, f"Falha na compra: {error_msg}")
            except Exception as e:
                return (False, f"Resposta invalida da API: {resp.text[:200]}")
        elif resp.status_code == 403:
            return (False, "Acesso negado: cookie invalido/expirado ou Robux insuficiente")
        elif resp.status_code == 400:
            return (False, f"Erro na requisicao (400): {resp.text[:200]}")
        else:
            return (False, f"Erro na API do Roblox: {resp.status_code} - {resp.text[:200]}")

    except Exception as e:
        return (False, f"Erro na API Roblox: {str(e)}")

def deliver_gamepasses(order):
    """
    Entrega as Gamepasses de um pedido apos pagamento confirmado.
    Usa a conta configurada no ROBLOX_COOKIE para comprar.
    Retorna uma tupla (sucesso, mensagem).
    """
    from models import OrderItem

    # Busca todos os itens do pedido que sao gamepass
    gamepass_items = [item for item in order.items if item.product.is_gamepass]

    if not gamepass_items:
        return (False, "Nenhum item de gamepass no pedido")

    roblox_cookie = ROBLOX_COOKIE
    if not roblox_cookie:
        return (False, "Cookie do Roblox nao configurado no .env")

    print(f"[ENTREGA] Iniciando entrega do pedido {order.id}...")
    results = []

    for item in gamepass_items:
        gamepass_link = item.gamepass_link
        robux_amount = item.robux_amount

        if not robux_amount:
            results.append(f"Gamepass: Preco em Robux nao informado")
            continue

        print(f"[ENTREGA] Processando: {gamepass_link} ({robux_amount} Robux)")
        success, msg = buy_gamepass_with_cookie(gamepass_link, roblox_cookie, expected_price=robux_amount)
        results.append(f"Gamepass ({robux_amount} Robux): {msg}")

        if success:
            print(f"[ENTREGA] Pedido {order.id}: Gamepass comprada com sucesso!")
        else:
            print(f"[ENTREGA] Pedido {order.id}: Erro ao comprar - {msg}")

    # Marca como entregue no banco (se todas compradas)
    all_success = all('sucesso' in r.lower() for r in results)
    if all_success and results:
        order.delivered = True
        order.delivered_at = datetime.utcnow()
        from extensions import db
        db.session.commit()
        print(f"[ENTREGA] Pedido {order.id}: Todas gamepasses entregues!")

    return (all_success, "; ".join(results))
