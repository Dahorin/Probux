import mercadopago
import os
from datetime import datetime

# Inicializa o SDK do Mercado Pago com o access token das variáveis de ambiente
MP_ACCESS_TOKEN = os.getenv('MERCADO_PAGO_ACCESS_TOKEN', '')

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
        "external_reference": str(order_id),  # Referência do pedido no seu sistema
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

def verify_order_payment(order_id):
    """
    Verifica se um pedido foi pago consultando o Mercado Pago.
    O Mercado Pago envia o payment_id via webhook ou podemos buscar pelo external_reference.
    Como simplificação, retornamos None (deve ser implementado via webhook).
    """
    # Em produção, isso seria feito via webhook
    return None
