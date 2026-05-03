from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app, jsonify
from markupsafe import Markup
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import login_user, login_required, logout_user, current_user
from flask_mail import Message
from models import User, Product, CartItem, Order, OrderItem
from extensions import db, mail
from sqlalchemy.orm import joinedload
import re
import secrets
import requests
import zlib
from datetime import datetime, timedelta
import os
import urllib.parse
import mercadopago_utils

# Log simples para debug
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

main = Blueprint('main', __name__)

def is_valid_email(email):
    """Verifica se o email tem formato válido."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def get_roblox_gamepass_price(gamepass_link, roblox_cookie):
    """Extrai o ID da Gamepass do link e verifica o preço via API/HTML do Roblox."""
    try:
        match = re.search(r'game-pass/(\d+)', gamepass_link)
        if not match:
            return None, "Link da Gamepass inválido"

        gamepass_id = match.group(1)

        # Cria sessão e injeta o cookie
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

        # Tenta primeiro via API de catálogo (POST) - requer cookie
        try:
            catalog_url = 'https://catalog.roblox.com/v1/catalog/items/details'
            resp = s.post(catalog_url, json={'items': [{'id': int(gamepass_id), 'itemType': 'GamePass'}]}, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get('data', [])
                if items:
                    price = items[0].get('price') or items[0].get('priceInRobux')
                    if price is not None:
                        return int(price), None
        except:
            pass

        # Fallback: usa a URL original com slug
        try:
            page_url = gamepass_link  # usa a URL original com slug
            resp = s.get(page_url, timeout=15, allow_redirects=True)
            if resp.status_code == 200:
                html = resp.text
                patterns = [
                    r'"price"\s*:\s*(\d+)',
                    r'"PriceInRobux"\s*:\s*(\d+)',
                    r'data-expected-price="(\d+)"',
                    r'data-price="(\d+)"',
                    r'(\d+)\s*Robux',
                ]
                for p in patterns:
                    m = re.search(p, html)
                    if m:
                        return int(m.group(1)), None
        except:
            pass

        return None, "Não foi possível encontrar o preço da Gamepass. Verifique se ela está pública e à venda."

    except Exception as e:
        return None, f"Erro ao verificar Gamepass: {str(e)}"

def generate_pix_code(pix_key, total):
    """Gera PIX Code (BR Code / EMV) válido segundo padrão do BC."""
    def tlv(tag, value):
        return f"{tag:02d}{len(value):02d}{value}"

    valor = f"{total:.2f}"  # Formato decimal com 2 casas

    # Payload EMV BR Code
    payload = tlv(0, '01')  # Payload Format Indicator
    # Merchant Account (26) = GUI + Pix Key
    merchant = tlv(0, 'br.gov.bcb.pix') + tlv(1, pix_key)
    payload += tlv(26, merchant)
    payload += tlv(52, '0000')  # Merchant Category
    payload += tlv(53, '986')    # Currency (BRL)
    payload += tlv(54, valor)     # Transaction Amount
    payload += tlv(58, 'BR')     # Country
    payload += tlv(59, 'PROBUX') # Merchant Name (sem acentos)
    payload += tlv(60, 'SAO PAULO')  # City (sem acentos)
    # Additional Data Field (62) com campo 05 (referência)
    payload += tlv(62, tlv(5, '***'))

    # CRC16-CCITT (0x1021)
    crc_input = payload + '6304'
    crc = 0xFFFF
    for byte in crc_input.encode('ascii'):
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc = crc << 1
            crc &= 0xFFFF
    payload += f"6304{crc:04X}"

    return payload

@main.route('/')
def index():
    products = Product.query.all()
    logger.info(f'Home acessado. User: {current_user.id if current_user.is_authenticated else "Anonimo"}')
    return render_template('index.html', products=products)

@main.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', name=current_user.username)

@main.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form['email'].strip().lower()
        password = generate_password_hash(request.form['password'])

        if not is_valid_email(email):
            flash("Email inválido! Use um formato válido (ex: usuario@exemplo.com).", "error")
            return render_template('register.html')

        if User.query.filter_by(username=username).first():
            flash("Este nome de usuário já está em uso! Escolha outro.", "error")
            return render_template('register.html')

        if User.query.filter_by(email=email).first():
            flash("Este email já está cadastrado! Use outro email ou faça login.", "error")
            return render_template('register.html')

        new_user = User(username=username, email=email, password=password)
        db.session.add(new_user)
        db.session.commit()

        # Gera token de verificação e envia email
        token = new_user.generate_verification_token()
        db.session.commit()

        verification_url = url_for('main.verify_email', token=token, _external=True)

        # Envia email de verificação via SMTP (Flask-Mail)
        try:
            msg = Message(
                'Confirme seu Email - Probux',
                recipients=[email],
                body=f'''Olá {username},

Obrigado por se cadastrar no Probux!

Para confirmar seu email, clique no link abaixo:
{verification_url}

Este link expira em 24 horas.

Se você não se cadastrou, ignore este email.

Atenciosamente,
Equipe Probux
'''
            )
            mail.send(msg)
            flash("Conta criada! Verifique seu email para ativar a conta.", "success")
        except Exception as e:
            # Se falhar o envio, mostra o link no terminal
            print("\n" + "="*60)
            print("LINK DE VERIFICAÇÃO DE EMAIL:")
            print(verification_url)
            print("="*60 + "\n")
            flash("Conta criada! Verifique o terminal do servidor para confirmar email.", "success")

        return redirect(url_for('main.login'))

    return render_template('register.html')

@main.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login_input = request.form['username']  # pode ser username ou email
        password = request.form['password']

        # Verifica se é email ou username
        if '@' in login_input:
            user = User.query.filter_by(email=login_input).first()
        else:
            user = User.query.filter_by(username=login_input).first()

        if user and check_password_hash(user.password, password):
            if not user.email_verified:
                flash("Você precisa verificar seu email antes de fazer login! Verifique sua caixa de entrada.", "error")
                return render_template('login.html')
            login_user(user)
            return redirect(url_for('main.index'))
        else:
            flash("Credenciais inválidas", "error")

    return render_template('login.html')

@main.route('/verify_email/<token>')
def verify_email(token):
    user = User.query.filter_by(verification_token=token).first()

    if not user or not user.verify_email_token(token):
        flash("Link inválido ou expirado!", "error")
        return redirect(url_for('main.login'))

    user.clear_verification_token()
    db.session.commit()

    flash("Email verificado com sucesso! Agora você pode fazer login.", "success")
    return redirect(url_for('main.login'))

@main.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('main.login'))

@main.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email']
        user = User.query.filter_by(email=email).first()

        if user:
            token = user.generate_reset_token()
            db.session.commit()

            reset_url = url_for('main.reset_password', token=token, _external=True)

            # Envia email via SMTP
            try:
                msg = Message(
                    'Recuperação de Senha - Probux',
                    recipients=[email],
                    body=f'''Olá {user.username},

Para redefinir sua senha, clique no link abaixo:
{reset_url}

Este link expira em 1 hora.

Se você não solicitou esta recuperação, ignore este email.

Atenciosamente,
Equipe Probux
'''
                )
                mail.send(msg)
                flash("Email de recuperação enviado! Verifique sua caixa de entrada.", "success")
            except Exception as e:
                # Se falhar, mostra no terminal
                print("\n" + "="*60)
                print("LINK DE RECUPERAÇÃO DE SENHA:")
                print(reset_url)
                print("="*60 + "\n")
                flash("Link de recuperação gerado! Verifique o terminal do servidor.", "success")
        else:
            flash("Email não encontrado!", "error")

    return render_template('forgot_password.html')

@main.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    user = User.query.filter_by(reset_token=token).first()

    if not user or not user.verify_reset_token(token):
        flash("Link inválido ou expirado!", "error")
        return redirect(url_for('main.forgot_password'))

    if request.method == 'POST':
        new_password = request.form['password']
        user.password = generate_password_hash(new_password)
        user.clear_reset_token()
        db.session.commit()

        flash("Senha alterada com sucesso! Faça login.", "success")
        return redirect(url_for('main.login'))

    return render_template('reset_password.html')

@main.route('/add_to_cart/<int:product_id>')
@login_required
def add_to_cart(product_id):
    product = Product.query.get_or_404(product_id)

    if product.is_gamepass:
        return redirect(url_for('main.gamepass_form', product_id=product_id))

    cart_item = CartItem.query.filter_by(user_id=current_user.id, product_id=product_id).first()

    if cart_item:
        cart_item.quantity += 1
    else:
        cart_item = CartItem(user_id=current_user.id, product_id=product_id, quantity=1)
        db.session.add(cart_item)

    db.session.commit()
    flash(f"{product.name} adicionada ao carrinho!", "success")
    return redirect(url_for('main.index'))

@main.route('/gamepass_form/<int:product_id>', methods=['GET', 'POST'])
@login_required
def gamepass_form(product_id):
    product = Product.query.get_or_404(product_id)

    if not product.is_gamepass:
        return redirect(url_for('main.add_to_cart', product_id=product_id))

    if request.method == 'POST':
        robux_amount = request.form.get('robux_amount', type=int)
        gamepass_link = request.form.get('gamepass_link', '').strip()

        if not robux_amount or robux_amount <= 0:
            flash("Informe uma quantidade válida de Robux!", "error")
            return render_template('gamepass_form.html', product=product)

        if not gamepass_link:
            flash("Informe o link da Gamepass!", "error")
            return render_template('gamepass_form.html', product=product)

        if 'roblox.com' not in gamepass_link:
            flash("Link inválido! Informe um link válido da Gamepass do Roblox.", "error")
            return render_template('gamepass_form.html', product=product)

        # Verifica o preço real da Gamepass no Roblox
        roblox_cookie = current_app.config.get('ROBLOX_COOKIE') or os.getenv('ROBLOX_COOKIE')
        if roblox_cookie:
            actual_price, error = get_roblox_gamepass_price(gamepass_link, roblox_cookie)
            if error:
                if '404' in error:
                    flash(f"{error}", "error")
                    flash(Markup('Dica: Sua Gamepass pode estar privada. <a href="/como-criar-gamepass" class="has-text-weight-bold" style="color: #3273dc;">Clique aqui para saber como criar uma Gamepass pública</a>'), "warning")
                else:
                    flash(f"Erro ao verificar Gamepass: {error}", "error")
                return render_template('gamepass_form.html', product=product)
            elif actual_price is not None and actual_price != robux_amount:
                flash(f"O preço informado ({robux_amount} Robux) não corresponde ao preço da Gamepass no Roblox ({actual_price} Robux). Por favor, verifique.", "error")
                return render_template('gamepass_form.html', product=product)
        else:
            flash("Aviso: Configuração do Roblox não encontrada. Não foi possível verificar o preço.", "warning")
            return render_template('gamepass_form.html', product=product)

        cart_item = CartItem(
            user_id=current_user.id,
            product_id=product_id,
            quantity=1,
            robux_amount=robux_amount,
            gamepass_link=gamepass_link
        )
        db.session.add(cart_item)
        db.session.commit()

        flash(f"Gamepass ({robux_amount} Robux) adicionada ao carrinho!", "success")
        return redirect(url_for('main.cart'))

    return render_template('gamepass_form.html', product=product)

@main.route('/cart')
@login_required
def cart():
    cart_items = CartItem.query.options(joinedload(CartItem.product)).filter_by(user_id=current_user.id).all()
    total = 0
    for item in cart_items:
        if item.robux_amount and item.product.is_gamepass:
            total += round(item.robux_amount * item.product.price_per_robux, 2) * item.quantity
        else:
            total += item.product.price * item.quantity
    logger.info(f'Carrinho carregado. Usuário: {current_user.id}, Itens: {len(cart_items)}')
    return render_template('cart.html', cart_items=cart_items, total=total)

@main.route('/remove_from_cart/<int:item_id>')
@login_required
def remove_from_cart(item_id):
    cart_item = CartItem.query.get_or_404(item_id)
    if cart_item.user_id != current_user.id:
        flash("Acesso negado!", "error")
        return redirect(url_for('main.cart'))

    db.session.delete(cart_item)
    db.session.commit()
    flash("Item removido do carrinho!", "success")
    return redirect(url_for('main.cart'))

@main.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_password = request.form['current_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        # Verifica senha atual
        if not check_password_hash(current_user.password, current_password):
            flash("Senha atual incorreta!", "error")
            return render_template('profile.html')

        # Verifica se novas senhas coincidem
        if new_password != confirm_password:
            flash("Novas senhas não coincidem!", "error")
            return render_template('profile.html')

        # Altera senha
        current_user.password = generate_password_hash(new_password)
        db.session.commit()

        flash("Senha alterada com sucesso!", "success")
        return redirect(url_for('main.profile'))

    return render_template('profile.html')

@main.route('/checkout')
@login_required
def checkout():
    cart_items = CartItem.query.filter_by(user_id=current_user.id).all()
    if not cart_items:
        flash("Seu carrinho está vazio!", "error")
        return redirect(url_for('main.cart'))

    total = 0
    for item in cart_items:
        if item.robux_amount and item.product.is_gamepass:
            total += round(item.robux_amount * item.product.price_per_robux, 2) * item.quantity
        else:
            total += item.product.price * item.quantity

    # Integração com Mercado Pago Pix
    # Cria o pedido primeiro para ter o ID
    order = Order(
        user_id=current_user.id,
        total=total,
        status='pending'
    )
    db.session.add(order)
    db.session.flush()  # Obtém o ID do pedido

    # Cria pagamento Pix no Mercado Pago
    description = f"Pedido Probux #{order.id}"
    mp_payment = mercadopago_utils.create_pix_payment(
        total,
        description,
        order.id,
        current_user.email
    )

    if mp_payment:
        # Salva os dados do Mercado Pago no pedido
        order.mp_payment_id = str(mp_payment['id'])
        order.pix_code = mp_payment['qr_code']
        order.mp_qr_code_base64 = mp_payment['qr_code_base64']
        db.session.commit()

        # QR Code do Mercado Pago (usando base64 ou o código copia/cola)
        qr_url = None  # O Mercado Pago fornece base64, não URL de imagem
        pix_code = mp_payment['qr_code']
    else:
        # Fallback: gera Pix manual (caso falhe o Mercado Pago)
        pix_key = current_app.config.get('PIX_KEY') or os.getenv('PIX_KEY', '')
        if pix_key:
            pix_code = generate_pix_code(pix_key, total)
            qr_url = f"https://quickchart.io/qr?size=250&text={urllib.parse.quote(pix_code)}"
        else:
            pix_code = ""
            qr_url = ""
        db.session.commit()

    return render_template('checkout.html', total=total, qr_code=qr_url, pix_code=pix_code,
                           mp_payment=mp_payment, order_id=order.id, cart_items=cart_items)

@main.route('/confirm_payment', methods=['POST'])
@login_required
def confirm_payment():
    cart_items = CartItem.query.filter_by(user_id=current_user.id).all()
    if not cart_items:
        flash("Carrinho vazio!", "error")
        return redirect(url_for('main.cart'))

    total = 0
    for item in cart_items:
        if item.robux_amount and item.product.is_gamepass:
            total += round(item.robux_amount * item.product.price_per_robux, 2) * item.quantity
        else:
            total += item.product.price * item.quantity

    pix_key = current_app.config.get('PIX_KEY') or os.getenv('PIX_KEY', '')
    # Gera PIX Code (BR Code válido)
    pix_code = generate_pix_code(pix_key, total)

    order = Order(user_id=current_user.id, total=total, status='pending', pix_code=pix_code)
    db.session.add(order)
    db.session.flush()

    for item in cart_items:
        price = item.product.price
        if item.robux_amount and item.product.is_gamepass:
            price = round(item.robux_amount * item.product.price_per_robux, 2)
        order_item = OrderItem(
            order_id=order.id,
            product_id=item.product_id,
            quantity=item.quantity,
            price=price,
            robux_amount=item.robux_amount,
            gamepass_link=item.gamepass_link
        )
        db.session.add(order_item)
        db.session.delete(item)

    db.session.commit()
    flash("Pedido realizado! Aguardando confirmação do pagamento.", "success")
    return redirect(url_for('main.order_details', order_id=order.id))

@main.route('/order/<int:order_id>')
@login_required
def order_details(order_id):
    order = Order.query.options(joinedload(Order.items).joinedload(OrderItem.product)).get_or_404(order_id)
    if order.user_id != current_user.id:
        flash("Acesso negado!", "error")
        return redirect(url_for('main.index'))

    # Se o pedido está pendente, gera o QR Code novamente
    qr_url = None
    if order.status == 'pending' and order.pix_code:
        if order.mp_qr_code_base64:
            qr_url = f"data:image/png;base64,{order.mp_qr_code_base64}"
        else:
            qr_url = f"https://quickchart.io/qr?size=250&text={urllib.parse.quote(order.pix_code)}"

    return render_template('order.html', order=order, qr_url=qr_url)

@main.route('/confirm_order/<int:order_id>', methods=['POST'])
@login_required
def confirm_order(order_id):
    order = Order.query.get_or_404(order_id)
    if order.user_id != current_user.id:
        flash("Acesso negado!", "error")
        return redirect(url_for('main.index'))
    if order.status != 'pending':
        flash("Este pedido não está pendente ou você já confirmou o pagamento!", "error")
        return redirect(url_for('main.order_details', order_id=order.id))
    # Apenas registra que o usuário afirmou ter pagado (não aprova ainda)
    order.status = 'payment_claimed'
    order.payment_claimed_at = datetime.utcnow()
    db.session.commit()
    flash("Pagamento registrado! Aguarde a confirmação manual da equipe.", "info")
    return redirect(url_for('main.order_details', order_id=order.id))

@main.route('/resend_payment/<int:order_id>')
@login_required
def resend_payment(order_id):
    order = Order.query.get_or_404(order_id)
    if order.user_id != current_user.id:
        flash("Acesso negado!", "error")
        return redirect(url_for('main.index'))
    if order.status != 'pending':
        flash("Este pedido não está pendente!", "error")
        return redirect(url_for('main.order_details', order_id=order.id))
    return redirect(url_for('main.order_details', order_id=order.id))

@main.route('/cleanup_orders')
@login_required
def cleanup_orders():
    """Remove pedidos pendentes com mais de 10 minutos."""
    limite = datetime.utcnow() - timedelta(minutes=10)
    old_orders = Order.query.filter(Order.status == 'pending', Order.created_at < limite).all()
    for order in old_orders:
        db.session.delete(order)
    db.session.commit()
    flash(f"{len(old_orders)} pedido(s) antigo(s) removido(s).", "info")
    return redirect(url_for('main.index'))

@main.route('/meus_pedidos')
@login_required
def meus_pedidos():
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).all()
    return render_template('meus_pedidos.html', orders=orders)

@main.route('/cancel_order/<int:order_id>')
@login_required
def cancel_order(order_id):
    order = Order.query.get_or_404(order_id)
    if order.user_id != current_user.id:
        flash("Acesso negado!", "error")
        return redirect(url_for('main.index'))
    if order.status != 'pending':
        flash("Só é possível cancelar pedidos pendentes!", "error")
        return redirect(url_for('main.meus_pedidos'))
    order.status = 'cancelled'
    db.session.commit()
    flash("Pedido cancelado com sucesso!", "success")
    return redirect(url_for('main.meus_pedidos'))

@main.route('/como-criar-gamepass')
def como_criar_gamepass():
    return render_template('como-criar-gamepass.html')

@main.route('/webhook/mercadopago', methods=['POST', 'GET'])
def mercadopago_webhook():
    """
    Webhook para receber notificações do Mercado Pago sobre pagamentos.
    O Mercado Pago envia uma notificação quando o status do pagamento muda.
    """
    if request.method == 'GET':
        # O Mercado Pago pode fazer um GET para verificar se o webhook está ativo
        return jsonify({'status': 'ok'}), 200

    data = request.json or request.form.to_dict()

    if not data:
        return jsonify({'error': 'No data received'}), 400

    # O Mercado Pago envia diferentes tipos de notificações
    # Para pagamentos Pix, o tipo é 'payment'
    if data.get('type') == 'payment':
        payment_id = data.get('data', {}).get('id')

        if payment_id:
            # Consulta o status do pagamento no Mercado Pago
            sdk = mercadopago_utils.get_mp_sdk()
            if sdk:
                try:
                    payment_info = sdk.payment().get(payment_id)
                    payment = payment_info["response"]

                    # Busca o pedido pelo ID do pagamento do Mercado Pago
                    order = Order.query.filter_by(mp_payment_id=str(payment_id)).first()

                    if order:
                        # Atualiza o status do pedido baseado no status do Mercado Pago
                        mp_status = payment.get('status')

                        if mp_status == 'approved':
                            order.status = 'paid'
                            db.session.commit()
                            # Opcional: enviar email de confirmação
                            print(f"Pedido {order.id} pago via Mercado Pago!")
                        elif mp_status == 'pending':
                            order.status = 'pending'
                            db.session.commit()
                        elif mp_status in ['cancelled', 'rejected']:
                            order.status = 'cancelled'
                            db.session.commit()

                except Exception as e:
                    print(f"Erro ao processar webhook: {e}")
                    return jsonify({'error': str(e)}), 500

    return jsonify({'status': 'processed'}), 200

@main.route('/check_payment/<int:order_id>')
@login_required
def check_payment(order_id):
    """
    Rota para verificar o status do pagamento via AJAX.
    O frontend pode chamar essa rota periodicamente para atualizar o status.
    """
    order = Order.query.get_or_404(order_id)

    if order.user_id != current_user.id:
        return jsonify({'error': 'Acesso negado'}), 403

    # Se tem ID do Mercado Pago, consulta o status
    if order.mp_payment_id:
        mp_status = mercadopago_utils.get_payment_status(order.mp_payment_id)

        if mp_status == 'approved' and order.status != 'paid':
            order.status = 'paid'
            db.session.commit()
            return jsonify({'status': 'paid', 'redirect': url_for('main.order_details', order_id=order.id)})

    return jsonify({'status': order.status})
