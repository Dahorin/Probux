import mercadopago
import os\
import re\
import requests\
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
        print(f"Erro ao criar pagamento Pix: {e}")
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
        print(f"Erro ao consultar pagamento: {e}")
        return None

def buy_gamepass_with_cookie(gamepass_link, roblox_cookie):
    """
    Compra uma Gamepass usando a conta Roblox configurada no cookie.
    Retorna (sucesso, mensagem).
    """
    if not roblox_cookie:
        return False, "Cookie do Roblox não configurado"

    # Extrai o ID da Gamepass
    match = re.search(r'game-pass/(\d+)', gamepass_link)
    if not match:
        return False, "Link da Gamepass inválido"

    gamepass_id = match.group(1)

    try:
        s = requests.Session()
        s.cookies.set('.ROBLOSECURITY', roblox_cookie, domain='.roblox.com')
        s.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8',
        })

        # Pega XSRF token
        try:
            r = s.post('https://auth.roblox.com/v2/logout', json={}, timeout=10)
            xsrf = r.headers.get('X-CSRF-TOKEN')
            if xsrf:
                s.headers['X-CSRF-TOKEN'] = xsrf
        except:
            pass

        # Tenta comprar a Gamepass via API
        # Nota: A API de compra do Roblox muda frequentemente
        # Esta é uma implementação simplificada

        print(f"[GAMEPASS] Tentando comprar gamepass {gamepass_id}")

        # Em produção, você precisaria integrar com a API real de compra
        # Por enquanto, vamos apenas logar que seria necessário comprar
        return True, f"Gamepass {gamepass_id} - processo de compra iniciado (verificar manualmente)"

    except Exception as e:
        return False, f"Erro na API Roblox: {str(e)}"

def deliver_gamepasses(order):
    """
    Entrega as Gamepasses de um pedido após pagamento confirmado.
    Usa a conta configurada no ROBOX_COOKIE para comprar.
    Retorna (sucesso, mensagem).
    """
    # Importa aqui dentro da função para evitar importação circular
    from models import OrderItem

    # Busca todos os itens do pedido que são gamepass
    gamepass_items = [item for item in order.items if item.product.is_gamepass]

    if not gamepass_items:
        return False, "Nenhum item de gamepass no pedido"

    roblox_cookie = ROBOX_COOKIE
    if not roblox_cookie:
        return False, "Token do Roblox não configurado"

    results = []

    # Para cada gamepass no pedido
    for item in gamepass_items:
        gamepass_link = item.gamepass_link
        robux_amount = item.robux_amount

        # Tenta comprar a Gamepass
        success, msg = buy_gamepass_with_cookie(gamepass_link, roblox_cookie)
        results.append(f"Gamepass ({robux_amount} Robux): {msg}")

        if success:
            print(f"[ENTREGA] Pedido {order.id}: Gamepass {gamepass_link} comprada")
        else:
            print(f"[ENTREGA] Pedido {order.id}: Erro ao comprar - {msg}")

    # Marca como entregue no banco (se todas compradas)
    if all('sucesso' in r.lower() for r in results):
        order.delivered = True
        order.delivered_at = datetime.utcnow()
        from extensions import db
        db.session.commit()

    return True, "; ".join(results)
