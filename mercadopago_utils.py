import mercadopago
import os
import re
import subprocess
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

def buy_gamepass_with_cookie(gamepass_link, roblox_cookie, expected_price=None):
    """
    Compra uma Gamepass usando o Node.js + Puppeteer (via subprocess).
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
        print(f"[GAMEPASS] Tentando comprar gamepass {gamepass_id} (preço: {expected_price})")
        print(f"[GAMEPASS] Chamando Node.js via subprocess...")

        # Define o cookie no ambiente para o Node.js
        env = os.environ.copy()
        env['ROBLOX_COOKIE'] = roblox_cookie

        # Caminho para o script Node.js
        script_dir = os.path.dirname(os.path.abspath(__file__))
        script_path = os.path.join(script_dir, 'comprar-gamepass.js')

        if not os.path.exists(script_path):
            return (False, f"Script Node.js não encontrado: {script_path}")

        print(f"[GAMEPASS] Executando: node {script_path} {gamepass_id} {expected_price or '0'}")

        result = subprocess.run(
            ['node', script_path, gamepass_id, str(expected_price or '0')],
            capture_output=True,
            text=True,
            env=env,
            timeout=120  # 2 minutos de timeout
        )

        print(f"[GAMEPASS] Node.js STDOUT: {result.stdout}")
        if result.stderr:
            print(f"[GAMEPASS] Node.js STDERR: {result.stderr}")

        if result.returncode == 0:
            # Tenta fazer parse do JSON retornado pelo Node.js
            try:
                import json
                # O Node.js imprime JSON na última linha
                lines = result.stdout.strip().split('\n')
                for line in reversed(lines):
                    line = line.strip()
                    if line.startswith('{') and line.endswith('}'):
                        try:
                            node_result = json.loads(line)
                            if node_result.get('success'):
                                return (True, f"Gamepass {gamepass_id} comprada com sucesso!")
                            else:
                                return (False, f"Falha na compra: {node_result.get('message', 'Erro desconhecido')}")
                        except:
                            continue
                # Se não conseguiu fazer parse do JSON
                if 'SUCESSO' in result.stdout or 'sucesso' in result.stdout:
                    return (True, f"Gamepass {gamepass_id} comprada!")
                else:
                    return (False, f"Resultado ambíguo: {result.stdout[:200]}")
            except Exception as e:
                return (False, f"Erro ao processar resultado: {str(e)}")
        else:
            return (False, f"Erro no Node.js (código {result.returncode}): {result.stderr[:200]}")

    except subprocess.TimeoutExpired:
        return (False, "Timeout: Node.js demorou muito para executar (limite: 2min)")
    except Exception as e:
        return (False, f"Erro ao chamar Node.js: {str(e)}")

def deliver_gamepasses(order):
    """
    Entrega as Gamepasses de um pedido após pagamento confirmado.
    Usa a conta configurada no ROBLOX_COOKIE para comprar.
    Retorna uma tupla (sucesso, mensagem).
    """
    from models import OrderItem

    # Busca todos os itens do pedido que são gamepass
    gamepass_items = [item for item in order.items if item.product.is_gamepass]

    if not gamepass_items:
        return (False, "Nenhum item de gamepass no pedido")

    roblox_cookie = ROBLOX_COOKIE
    if not roblox_cookie:
        return (False, "Cookie do Roblox não configurado no .env")

    print(f"[ENTREGA] Iniciando entrega do pedido {order.id}...")
    results = []

    for item in gamepass_items:
        gamepass_link = item.gamepass_link
        robux_amount = item.robux_amount

        if not robux_amount:
            results.append(f"Gamepass: Preço em Robux não informado")
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
