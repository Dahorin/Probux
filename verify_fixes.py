#!/usr/bin/env python3
"""Verificação final do estado de todas as correções"""
import os
os.chdir("C:/Users/Rafael/Documents/GitHub/Probux")

print("=" * 60)
print("VERIFICAÇÃO FINAL DAS CORREÇÕES")
print("=" * 60)

# ===== ROUTES.PY =====
with open('routes.py', 'r', encoding='utf-8') as f:
    routes = f.read()

print("\n📄 routes.py:")

checks = [
    ('if mp_payment:', 'Checkout aceita mp_payment mesmo sem qr_code'),
    ('elif order.delivery_attempted:' not in routes[1040:1100], 'Webhook sem bloqueio delivery_attempted'),
]

# Check webhook
webhook_area = routes[routes.find("def mercadopago_webhook"):routes.find("def mercadopago_webhook")+2000]
if 'elif order.delivery_attempted:' in webhook_area:
    print('  ❌ Webhook ainda tem delivery_attempted block')
else:
    print('  ✅ Webhook: delivery_attempted block removido')

# Check payment_id fallback no webhook
if 'data.get(\'id\') or data.get' in routes:
    print('  ✅ Webhook: payment_id fallback adicionado')
else:
    print('  ❌ Webhook: payment_id fallback faltando')

# Check checkout
if "if mp_payment and mp_payment.get('qr_code'):" in routes:
    print('  ❌ Checkout: ainda exige qr_code')
elif "if mp_payment:" in routes:
    print('  ✅ Checkout: aceita qualquer mp_payment')

# Check check_payment
cp_area = routes[routes.find("def check_payment"):routes.find("def check_payment")+2000]
if 'delivery_attempted:' in cp_area:
    print('  ❌ check_payment: ainda tem delivery_attempted block')
else:
    print('  ✅ check_payment: delivery_attempted block removido')

# ===== MERCADOPAGO_UTILS.PY =====
with open('mercadopago_utils.py', 'r', encoding='utf-8') as f:
    mpu = f.read()

print("\n📄 mercadopago_utils.py:")

checks_mpu = [
    (lambda: "isinstance(data, dict) and data.get('success')" in mpu,
     'buy_gamepass: isinstance check no data.get(success)'),
    (lambda: "isinstance(data, dict)" in mpu and "elif data and isinstance(data, dict):" in mpu,
     'buy_gamepass: isinstance check no elif'),
    (lambda: "isinstance(data2, dict) and data2.get('success')" in mpu,
     'buy_gamepass: isinstance check no data2.get(success)'),
    (lambda: "order.delivery_attempted = True" in mpu[mpu.find("if all_success:"):mpu.find("if all_success:")+300],
     'deliver_gamepasses: delivery_attempted setado SOMENTE no sucesso total'),
    (lambda: "getCachedDNS" not in mpu and "x-roblox-cookie" in mpu,
     '_proxy_request: cookie enviado via header HTTP x-roblox-cookie'),
    (lambda: "proxy_network_error = False" in mpu,
     '_roblox_api_request: fallback quando proxy retorna 403'),
    (lambda: "https://www.roblox.com{endpoint}" in mpu,
     'Fallback marketplace usa www.roblox.com'),
    (lambda: "/marketplace/game-pass/" in mpu,
     'Endpoint alternativo /marketplace/game-pass/ adicionado'),
]

for func, desc in checks_mpu:
    try:
        result = func()
    except:
        result = False
    print(f"  {'✅' if result else '❌'} {desc}")

# ===== PROXY-ROBLOX.JS =====
with open('proxy-roblox.js', 'r', encoding='utf-8') as f:
    proxy = f.read()

print("\n📄 proxy-roblox.js:")
js_checks = [
    ('dns.resolve4' in proxy or 'dns.Resolver' in proxy,
     'DNS manual com servidores públicos'),
    ('8.8.8.8' in proxy,
     'DNS 8.8.8.8 configurado'),
    ('x-roblox-cookie' in proxy,
     'Cookie recebido via header HTTP'),
    ('TLS' in proxy or 'tls' in proxy.lower(),
     'Suporte TLS para HTTPS'),
    ('redirect' in proxy,
     'Segue redirects'),
]

for condition, desc in js_checks:
    print(f"  {'✅' if condition else '❌'} {desc}")

print("\n" + "=" * 60)
print("PRÓXIMO PASSO:")
print("=" * 60)
print("""
1. Crie um Cloudflare Worker em dash.cloudflare.com
2. Cole o código do proxy (veja proxy-cloudflare.js se existir)
3. Configure ROBLOX_PROXY_URL no .env
4. Reinicie o servidor

Ou alternativamente:
- Verifique se o DNS do servidor consegue resolver externamente
- Se o IP estiver banido pelo Roblox, só Cloudflare Worker resolve
""")