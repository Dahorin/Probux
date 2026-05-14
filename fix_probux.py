#!/usr/bin/env python3
"""Corrige bugs na entrega de pedidos do Probux"""
import os
os.chdir("C:/Users/Rafael/Documents/GitHub/Probux")

# =============================================
# CORRECAO 1: routes.py - Checkout bug (rollback quando preference)
# =============================================
with open('routes.py', 'r', encoding='utf-8') as f:
    routes = f.read()

old1 = "    if mp_payment and mp_payment.get('qr_code'):"
new1 = "    if mp_payment:"

if old1 in routes:
    routes = routes.replace(old1, new1)
    print("CORRECAO 1 APLICADA: Checkout aceita qualquer mp_payment (não apenas qr_code)")
else:
    print("CORRECAO 1 JA APLICADA ou padrao nao encontrado")

# =============================================
# CORRECAO 2: routes.py - Webhook removendo delivery_attempted block
# =============================================
old2 = """                        if mp_status == 'approved':
                            if order.status == 'delivered':
                                print(f"[WEBHOOK] Pedido {order.id}: Ja entregue, ignorando notificacao duplicada.")
                                return jsonify({'status': 'processed'}), 200
                            elif order.delivery_attempted:
                                print(f"[WEBHOOK] Pedido {order.id}: Entrega ja tentada anteriormente, ignorando.")
                                if order.status != 'paid':
                                    order.status = 'paid'
                                    db.session.commit()
                                return jsonify({'status': 'processed'}), 200
                            elif order.status == 'paid':
                                # Ja esta como pago, tenta entregar se ainda nao entregou
                                print(f"[WEBHOOK] Pedido {order.id}: Status 'paid', tentando entregar...")
                                from mercadopago_utils import deliver_gamepasses
                                success, msg = deliver_gamepasses(order)
                                # Recarrega do banco para garantir status atualizado
                                db.session.refresh(order)
                                print(f"[WEBHOOK] Pedido {order.id}: Entrega - {msg}")
                                print(f"[WEBHOOK] Pedido {order.id}: Status final: {order.status}")
                            else:
                                # Primeira vez que recebe approved
                                order.status = 'paid'
                                db.session.commit()
                                print(f"[WEBHOOK] Pedido {order.id}: Status atualizado para 'paid', iniciando entrega...")
                                from mercadopago_utils import deliver_gamepasses
                                success, msg = deliver_gamepasses(order)
                                db.session.refresh(order)
                                print(f"[WEBHOOK] Pedido {order.id}: Entrega - {msg}")
                                print(f"[WEBHOOK] Pedido {order.id}: Status final: {order.status}")"""

new2 = """                        if mp_status == 'approved':
                            if order.status == 'delivered':
                                print(f"[WEBHOOK] Pedido {order.id}: Ja entregue, ignorando notificacao duplicada.")
                                return jsonify({'status': 'processed'}), 200
                            # Sempre tenta entregar se pagamento aprovado (permite retry)
                            print(f"[WEBHOOK] Pedido {order.id}: Pagamento aprovado, tentando entrega...")
                            from mercadopago_utils import deliver_gamepasses
                            success, msg = deliver_gamepasses(order)
                            db.session.refresh(order)
                            print(f"[WEBHOOK] Pedido {order.id}: Entrega - {msg}")
                            print(f"[WEBHOOK] Pedido {order.id}: Status final: {order.status}")"""

if old2 in routes:
    routes = routes.replace(old2, new2)
    print("CORRECAO 2 APLICADA: Webhook - removido delivery_attempted block")
else:
    print("CORRECAO 2: padrao webhook nao encontrado (pode ja estar corrigido)")

# =============================================
# CORRECAO 3: routes.py - check_payment removendo delivery_attempted block
# =============================================
old3 = """        if mp_status == 'approved' and order.status not in ['delivered']:
            # Se ainda nao tentou entregar, tenta agora
            if order.status != 'paid':
                order.status = 'paid'
                db.session.commit()
                print(f"[CHECK_PAYMENT] Pedido {order.id}: Pagamento aprovado! Iniciando entrega...")
            elif order.delivery_attempted:
                # Ja tentou entregar e nao conseguiu — nao tenta de novo
                print(f"[CHECK_PAYMENT] Pedido {order.id}: Entrega ja tentada anteriormente, aguardando retry manual.")
                return jsonify({'status': order.status})
            else:
                print(f"[CHECK_PAYMENT] Pedido {order.id}: Status 'paid', tentando entregar...")

            # Processa entrega automatica da Gamepass
            from mercadopago_utils import deliver_gamepasses
            success, msg = deliver_gamepasses(order)
            db.session.refresh(order)
            print(f"[CHECK_PAYMENT] Pedido {order.id}: Entrega - {msg}")
            print(f"[CHECK_PAYMENT] Pedido {order.id}: Status atual: {order.status}")"""

new3 = """        if mp_status == 'approved' and order.status not in ['delivered']:
            # Atualiza status se necessario
            if order.status != 'paid':
                order.status = 'paid'
                db.session.commit()
                print(f"[CHECK_PAYMENT] Pedido {order.id}: Pagamento aprovado! Iniciando entrega...")
            else:
                print(f"[CHECK_PAYMENT] Pedido {order.id}: Status 'paid', tentando entregar...")

            # Processa entrega automatica da Gamepass (sempre permite retry)
            from mercadopago_utils import deliver_gamepasses
            success, msg = deliver_gamepasses(order)
            db.session.refresh(order)
            print(f"[CHECK_PAYMENT] Pedido {order.id}: Entrega - {msg}")
            print(f"[CHECK_PAYMENT] Pedido {order.id}: Status atual: {order.status}")"""

if old3 in routes:
    routes = routes.replace(old3, new3)
    print("CORRECAO 3 APLICADA: check_payment - removido delivery_attempted block")
else:
    print("CORRECAO 3: padrao check_payment nao encontrado")

# =============================================
# CORRECAO 4: Webhook - payment_id extraction
# =============================================
old4 = "        payment_id = data.get('data', {}).get('id')"
new4 = "        # O Mercado Pago pode enviar 'id' no top level ou dentro de 'data'\n        payment_id = data.get('data', {}).get('id') or data.get('id')"

if old4 in routes:
    routes = routes.replace(old4, new4)
    print("CORRECAO 4 APLICADA: Webhook - tenta data.id e data.data.id")
else:
    print("CORRECAO 4: padrao payment_id nao encontrado")

with open('routes.py', 'w', encoding='utf-8') as f:
    f.write(routes)

# =============================================
# CORRECAO 5: mercadopago_utils.py - isinstance checks no buy_gamepass
# =============================================
with open('mercadopago_utils.py', 'r', encoding='utf-8') as f:
    mpu = f.read()

changes = 0
if "if data and data.get('success'):" in mpu:
    mpu = mpu.replace(
        "if data and data.get('success'):",
        "if data and isinstance(data, dict) and data.get('success'):"
    )
    changes += 1

if "elif data:\n" in mpu:
    mpu = mpu.replace(
        "elif data:\n",
        "elif data and isinstance(data, dict):\n"
    )
    changes += 1

if "if data2 and data2.get('success'):" in mpu:
    mpu = mpu.replace(
        "if data2 and data2.get('success'):",
        "if data2 and isinstance(data2, dict) and data2.get('success'):"
    )
    changes += 1

print(f"CORRECAO 5: {changes} isinstance checks adicionados no buy_gamepass")

# =============================================
# CORRECAO 6: deliver_gamepasses - delivery_attempted logica
# =============================================
old6 = """    # Marca que ja tentamos entregar (evita loop infinito no check_payment)
    order.delivery_attempted = True

    if all_success:
        order.delivered = True
        order.delivered_at = datetime.utcnow()
        order.status = 'delivered'
    else:
        order.status = 'paid'"""

new6 = """    if all_success:
        order.delivered = True
        order.delivered_at = datetime.utcnow()
        order.status = 'delivered'
        order.delivery_attempted = True
    else:
        order.status = 'paid'
        # Permite retry em caso de falha parcial
        # delivery_attempted so e setado quando TODOS os itens foram entregues"""

if old6 in mpu:
    mpu = mpu.replace(old6, new6)
    print("CORRECAO 6 APLICADA: delivery_attempted so setado no sucesso total")
else:
    print("CORRECAO 6: padrao delivery_attempted nao encontrado")

with open('mercadopago_utils.py', 'w', encoding='utf-8') as f:
    f.write(mpu)

print("\n=== RESUMO ===")
print("1. Checkout: aceita qualquer mp_payment (nao apenas qr_code)")
print("2. Webhook: removido delivery_attempted block (permite retry)")
print("3. check_payment: removido delivery_attempted block (permite retry)")
print("4. Webhook: tenta data.id e data.data.id para payment_id")
print("5. buy_gamepass: isinstance checks evitam crash com string")
print("6. deliver_gamepasses: delivery_attempted so no sucesso total")
print("\nPronto! Verifique os logs após testar um pedido.")