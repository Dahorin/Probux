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
from datetime import datetime, timedelta
import os
import urllib.parse
import mercadopago_utils

# Log simples para debug
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

def get_roblox_balance(roblox_cookie):
    """
    Consulta o saldo de Robux da conta do Roblox.
    Usa proxy Node.js se configurado (evita bloqueio de IP).
    Retorna o saldo ou None em caso de erro.
    """
    if not roblox_cookie:
        return None

    try:
        roblox_cookie = roblox_cookie.strip()
        found_balance = None

        # Método 1: Via proxy Node.js (se disponível)
        if USE_PROXY and ROBLOX_PROXY_URL:
            # Verificar autenticidade via users API
            data, status, err = mercadopago_utils._proxy_request(
                'GET',
                '/v1/users/authenticated',
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                         'Cookie': f'.ROBLOSECURITY={roblox_cookie}'}
            )
            if status == 200 and isinstance(data, dict):
                print(f"[ROBLOX] Usuário autenticado: {data.get('name')} (ID: {data.get('id')})")

                # Agora pega o saldo via economy API v1
                data2, status2, err2 = mercadopago_utils._proxy_request(
                    'GET',
                    '/v1/user/currency',
                    headers={
                        'User-Agent': 'Mozilla/5.0',
                        'Cookie': f'.ROBLOSECURITY={roblox_cookie}',
                        'X-CSRF-TOKEN': ''
                    },
                    timeout=15
                )
                if status2 == 200:
                    if isinstance(data2, dict):
                        found_balance = data2.get('robux') or data2.get('data', {}).get('robux')
                    elif isinstance(data2, str):
                        try:
                            d = json.loads(data2)
                            found_balance = d.get('robux')
                        except Exception:
                            pass

                if found_balance is not None:
                    print(f"[ROBLOX] 💰 Saldo via proxy: {found_balance} Robux")
                    return found_balance

            # Se não conseguiu via users+economy, tenta economy direto
            data3, status3, err3 = mercadopago_utils._proxy_request(
                'GET',
                '/v1/user/currency',
                headers={
                    'User-Agent': 'Mozilla/5.0',
                    'Cookie': f'.ROBLOSECURITY={roblox_cookie}',
                },
                timeout=15
            )
            if status3 == 200:
                if isinstance(data3, dict):
                    found_balance = data3.get('robux') or data3.get('data', {}).get('robux')
                elif isinstance(data3, str):
                    try:
                        d = json.loads(data3)
                        found_balance = d.get('robux')
                    except Exception:
                        pass
            if found_balance is not None:
                print(f"[ROBLOX] 💰 Saldo via proxy (direto): {found_balance} Robux")
                return found_balance

            if err:
                print(f"[ROBLOX] Proxy erro: {err}")

        # Método 2: Conexão direta (sem proxy)
        import requests as req_lib
        s = req_lib.Session()
        s.cookies.set('.ROBLOSECURITY', roblox_cookie, domain='.roblox.com', path='/')
        s.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
        })

        # Pega XSRF
        try:
            r = s.post('https://auth.roblox.com/v2/logout', json={}, timeout=10)
            xsrf = r.headers.get('X-CSRF-TOKEN')
            if xsrf:
                s.headers['X-CSRF-TOKEN'] = xsrf
        except Exception:
            pass

        # Tenta Economy v1 direto
        try:
            resp = s.get('https://economy.roblox.com/v1/user/currency', timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                return data.get('robux')
        except Exception as e:
            print(f"[ROBLOX] Economy direto erro: {e}")

        # Tenta via users API + economy v2
        try:
            resp_user = s.get('https://users.roblox.com/v1/users/authenticated', timeout=10)
            if resp_user.status_code == 200:
                user_data = resp_user.json()
                user_id = user_data.get('id')
                if user_id:
                    resp = s.get(f'https://economy.roblox.com/v2/users/{user_id}/currency', timeout=15)
                    if resp.status_code == 200:
                        data = resp.json()
                        return data.get('robux')
        except Exception:
            pass

        print("[ROBLOX] Todas as tentativas de obter saldo falharam")

    except Exception as e:
        print(f"[ROBUx] Erro ao consultar saldo: {e}")

    return None

main = Blueprint('main', __name__)

@main.context_processor
def inject_roblox_balance():
    """Injeta o saldo de Robux em todos os templates."""
    roblox_balance = None
    roblox_cookie = current_app.config.get('ROBLOX_COOKIE') or os.getenv('ROBLOX_COOKIE')
    if roblox_cookie:
        roblox_balance = get_roblox_balance(roblox_cookie)
    return dict(roblox_balance=roblox_balance)

def is_valid_email(email):
    """Verifica se o email tem formato válido."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def get_roblox_gamepass_price(gamepass_link, roblox_cookie, discount_percent=0):
    """Extract gamepass ID and return ORIGINAL price (without account discount).
    Uses shared session and _roblox_api_request for robust connection."""
    try:
        match = re.search(r'game-pass/(\d+)', gamepass_link)
        if not match:
            return None, None, None, None, "Invalid link"

        gamepass_id = match.group(1)

        # Cria sessão com headers realistas
        session = mercadopago_utils._create_session(roblox_cookie)

        # Tenta obter XSRF token
        mercadopago_utils._get_xsrf_token(session)

        # Try catalog API (endpoint principal)
        try:
            resp, err = mercadopago_utils._roblox_api_request(
                'POST', '/v1/catalog/items/details',
                session=session,
                json_data={'items': [{'id': int(gamepass_id), 'itemType': 'GamePass'}]},
                max_retries=2
            )
            if resp and 'data' in resp:
                items = resp['data']
                if items:
                    price = items[0].get('price') or items[0].get('priceInRobux')
                    if price is not None:
                        if discount_percent > 0:
                            original = round(price / (1 - discount_percent))
                            _log(f'[ROBLOX] Price returned: {price}, Original adjusted: {original}')
                            return int(original), False, None, None
                        return int(price), False, None, None
        except Exception as e:
            _log(f'[ROBLOX] Catalog error: {e}')

        # Fallback: HTML - search for data-expected-price="NUMBER"
        try:
            resp_html, err = mercadopago_utils._roblox_api_request(
                'GET', gamepass_link,
                session=session,
                max_retries=2
            )
            if resp_html and isinstance(resp_html, str):
                html = resp_html

                if 'already own' in html.lower() or 'você possui' in html.lower():
                    return None, True, None, "You already own this item!"

                # Search for data-expected-price="NUMBER"
                m = re.search(r'data-expected-price="(\d+)"', html)
                if m:
                    price = int(m.group(1))
                    if discount_percent > 0:
                        original = round(price / (1 - discount_percent))
                        _log(f'[ROBLOX] Price from HTML: {price}, Original adjusted: {original}')
                        return int(original), False, None, None
                    return price, False, None, None

                # Alternative patterns
                patterns = [
                    r'"price"\s*:\s*(\d+)',
                    r'"priceInRobux"\s*:\s*(\d+)',
                    r'data-price="(\d+)"',
                    r'(\d+)\s*Robux',
                ]
                for p in patterns:
                    m = re.search(p, html)
                    if m:
                        price = int(m.group(1))
                        if discount_percent > 0:
                            original = round(price / (1 - discount_percent))
                            _log(f'[ROBLOX] Price from HTML: {price}, Original adjusted: {original}')
                            return int(original), False, None, None
                        return price, False, None, None
        except Exception as e:
            _log(f'[ROBLOX] HTML error: {e}')

        return None, None, None, "Could not find price."
    except Exception as e:
        return None, None, None, f"Error: {str(e)}"

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
        discount_percent = current_app.config.get('DISCOUNT_PERCENT', 0)
        if roblox_cookie:
            actual_price, already_owned, balance, error = get_roblox_gamepass_price(gamepass_link, roblox_cookie, discount_percent)
            if already_owned:
                flash(f"Você já possui esta Gamepass! Não é possível comprar o mesmo passe duas vezes.", "error")
                return render_template('gamepass_form.html', product=product)
            if error:
                if '404' in error:
                    flash(f"{error}", "error")
                    flash(Markup('Dica: Sua Gamepass pode estar privada. <a href="/como-criar-gamepass" class="has-text-weight-bold" style="color: #3273dc;">Clique aqui para saber como criar uma Gamepass pública</a>'), "warning")
                elif 'já possui' in error:
                    flash(f"{error}", "error")
                else:
                    flash(f"Erro ao verificar Gamepass: {error}", "error")
                return render_template('gamepass_form.html', product=product)
            elif actual_price is not None and actual_price != robux_amount:
                # Verifica se o preço digitado é o original (sem desconto da conta)
                discount_percent = current_app.config.get('DISCOUNT_PERCENT', 0)
                discounted_price = int(actual_price * (1 - discount_percent))
                if robux_amount != actual_price and robux_amount != discounted_price:
                    flash(f"O preço informado ({robux_amount} Robux) não corresponde ao preço da Gamepass no Roblox ({actual_price} Robux). Por favor, verifique.", "error")
                    return render_template('gamepass_form.html', product=product)
                # Se o usuário digitou o preço com desconto, ajusta para o original
                if robux_amount == discounted_price:
                    robux_amount = actual_price
                    flash(f"Preço ajustado para o valor original da Gamepass: {actual_price} Robux", "info")
            # Verifica se a conta tem saldo suficiente
            if balance is not None and robux_amount > balance:
                flash(f"Saldo insuficiente! A conta do Roblox tem apenas {balance} Robux disponível, mas a Gamepass custa {robux_amount} Robux.", "error")
                flash(f"Adicione mais Robux à conta ou escolha uma Gamepass de menor valor.", "warning")
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

    # Cria os itens do pedido a partir do carrinho
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
        # Remove o item do carrinho
        db.session.delete(item)

    # Cria pagamento Pix no Mercado Pago
    description = f"Pedido PROBUX LTDA #{order.id}"
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
        # FALHA: Não é possível criar PIX sem Mercado Pago
        db.session.rollback()
        flash("Erro ao criar pagamento via Mercado Pago. Tente novamente ou entre em contato com o suporte.", "error")
        return redirect(url_for('main.cart'))
        db.session.commit()

    # Calcula o tempo de expiração (15 minutos após criação)
    expiration_time = order.created_at + timedelta(minutes=15)
    expiration_timestamp = int(expiration_time.timestamp())

    return render_template('checkout.html', total=total, qr_code=qr_url, pix_code=pix_code,
                           mp_payment=mp_payment, order_id=order.id, cart_items=cart_items,
                           expiration_timestamp=expiration_timestamp)

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

    # Cria o pedido primeiro (PIX será gerado pelo Mercado Pago via checkout)
    order = Order(user_id=current_user.id, total=total, status='pending')
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

    # Se o pedido está pendente ou aguardando confirmação, mostra o QR Code
    qr_url = None
    if order.status in ['pending', 'payment_claimed'] and order.pix_code:
        if order.mp_qr_code_base64:
            qr_url = f"data:image/png;base64,{order.mp_qr_code_base64}"
        else:
            qr_url = f"https://quickchart.io/qr?size=250&text={urllib.parse.quote(order.pix_code)}"

    expiration_time = order.created_at + timedelta(minutes=15)
    expiration_timestamp = int(expiration_time.timestamp())
    return render_template('order.html', order=order, qr_url=qr_url, expiration_timestamp=expiration_timestamp)

@main.route('/confirm_order/<int:order_id>', methods=['POST'])
@login_required
def confirm_order(order_id):
    order = Order.query.get_or_404(order_id)
    if order.user_id != current_user.id:
        flash("Acesso negado!", "error")
        return redirect(url_for('main.index'))
    if order.status not in ['pending', 'payment_claimed']:
        flash("Este pedido já foi processado ou cancelado!", "error")
        return redirect(url_for('main.order_details', order_id=order.id))

    # Tenta verificar se o Mercado Pago já aprovou
    if order.mp_payment_id:
        mp_status = mercadopago_utils.get_payment_status(order.mp_payment_id)
        if mp_status == 'approved':
            order.status = 'paid'
            db.session.commit()
            print(f"[CONFIRM_ORDER] Pedido {order.id}: Pago! Tentando entregar...")
            from mercadopago_utils import deliver_gamepasses
            success, msg = deliver_gamepasses(order)
            if success:
                flash(f"Pagamento aprovado e gamepass entregue! {msg}", "success")
            else:
                flash(f"Pago, mas erro na entrega: {msg}", "error")
            return redirect(url_for('main.order_details', order_id=order.id))

    # Se não aprovou ainda, marca como aguardando
    order.status = 'payment_claimed'
    order.payment_claimed_at = datetime.utcnow()
    db.session.commit()
    flash("Pagamento registrado! Assim que confirmado, sua gamepass será entregue automaticamente.", "info")
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
    # Não mostra pedidos cancelados para o cliente
    orders = Order.query.filter(
        Order.user_id == current_user.id,
        Order.status != 'cancelled'
    ).order_by(Order.created_at.desc()).all()
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
    print(f"\n[WEBHOOK] Requisição recebida: {request.method}")
    print(f"[WEBHOOK] Headers: {dict(request.headers)}")
    print(f"[WEBHOOK] Data: {request.json or request.form.to_dict()}")

    if request.method == 'GET':
        # O Mercado Pago pode fazer um GET para verificar se o webhook está ativo
        return jsonify({'status': 'ok'}), 200

    data = request.json or request.form.to_dict()
    print(f"[WEBHOOK] Dados processados: {data}")

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
                            if order.status == 'delivered':
                                print(f"[WEBHOOK] Pedido {order.id}: Já entregue, ignorando notificação duplicada.")
                                return jsonify({'status': 'processed'}), 200
                            elif order.delivery_attempted:
                                print(f"[WEBHOOK] Pedido {order.id}: Entrega já tentada anteriormente, ignorando.")
                                if order.status != 'paid':
                                    order.status = 'paid'
                                    db.session.commit()
                                return jsonify({'status': 'processed'}), 200
                            elif order.status == 'paid':
                                # Já está como pago, tenta entregar se ainda não entregou
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
                                print(f"[WEBHOOK] Pedido {order.id}: Status final: {order.status}")
                        elif mp_status == 'pending' and order.status not in ['paid', 'delivered', 'cancelled']:
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

        if mp_status == 'approved' and order.status not in ['delivered']:
            # Se ainda não tentou entregar, tenta agora
            if order.status != 'paid':
                order.status = 'paid'
                db.session.commit()
                print(f"[CHECK_PAYMENT] Pedido {order.id}: Pagamento aprovado! Iniciando entrega...")
            elif order.delivery_attempted:
                # Já tentou entregar e não conseguiu — não tenta de novo
                print(f"[CHECK_PAYMENT] Pedido {order.id}: Entrega já tentada anteriormente, aguardando retry manual.")
                return jsonify({'status': order.status})
            else:
                print(f"[CHECK_PAYMENT] Pedido {order.id}: Status 'paid', tentando entregar...")

            # Processa entrega automatica da Gamepass
            from mercadopago_utils import deliver_gamepasses
            success, msg = deliver_gamepasses(order)
            db.session.refresh(order)
            print(f"[CHECK_PAYMENT] Pedido {order.id}: Entrega - {msg}")
            print(f"[CHECK_PAYMENT] Pedido {order.id}: Status atual: {order.status}")

    return jsonify({'status': order.status})

@main.route('/delete_order/<int:order_id>')
@login_required
def delete_order(order_id):
    """Exclui um pedido (apenas se estiver pago)."""
    order = Order.query.get_or_404(order_id)
    
    if order.user_id != current_user.id:
        flash("Acesso negado!", "error")
        return redirect(url_for('main.meus_pedidos'))
    
    if order.status != 'paid':
        flash("Só é possível excluir pedidos pagos!", "error")
        return redirect(url_for('main.meus_pedidos'))
    
    db.session.delete(order)
    db.session.commit()
    flash("Pedido excluído com sucesso!", "success")
    return redirect(url_for('main.meus_pedidos'))

@main.route('/test_deliver/<int:order_id>')
@login_required
def test_deliver(order_id):
    """Rota de teste para forçar a entrega de um pedido."""
    order = Order.query.get_or_404(order_id)
    if order.user_id != current_user.id:
        flash("Acesso negado!", "error")
        return redirect(url_for('main.meus_pedidos'))

    print(f"\n[TESTE] Forçando entrega do pedido {order.id}...")
    print(f"[TESTE] Status atual: {order.status}")
    print(f"[TESTE] Itens: {len(order.items)}")

    from mercadopago_utils import deliver_gamepasses
    success, msg = deliver_gamepasses(order)

    print(f"[TESTE] Resultado: {msg}")

    if success:
        flash(f"Entrega realizada! {msg}", "success")
    else:
        flash(f"Erro na entrega: {msg}", "error")

    return redirect(url_for('main.order_details', order_id=order.id))

@main.route('/delete_all_paid_orders')
@login_required
def delete_all_paid_orders():
    """Exclui TODOS os pedidos pagos e entregues do usuário."""
    paid_orders = Order.query.filter(
        Order.user_id == current_user.id,
        Order.status.in_(['paid', 'delivered'])
    ).all()

    count = len(paid_orders)

    if count == 0:
        flash("Você não tem pedidos pagos ou entregues para excluir!", "info")
        return redirect(url_for('main.meus_pedidos'))

    for order in paid_orders:
        db.session.delete(order)

    db.session.commit()
    flash(f"{count} pedido(s) excluído(s) com sucesso!", "success")
    return redirect(url_for('main.meus_pedidos'))


@main.route('/manual_deliver/<int:order_id>', methods=['POST'])
@login_required
def manual_deliver(order_id):
    """Força a entrega de um pedido manualmente pelo botão na interface."""
    order = Order.query.get_or_404(order_id)
    if order.user_id != current_user.id:
        flash("Acesso negado!", "error")
        return redirect(url_for('main.meus_pedidos'))

    if order.status not in ['paid', 'payment_claimed']:
        flash(f"Pedido não está em estado válido para entrega (status: {order.status}).", "error")
        return redirect(url_for('main.order_details', order_id=order.id))

    from mercadopago_utils import deliver_gamepasses
    success, msg = deliver_gamepasses(order)

    if success:
        flash(f"✅ Entrega forçada realizada com sucesso! {msg}", "success")
    else:
        flash(f"❌ Erro na entrega forçada: {msg}", "error")

    return redirect(url_for('main.order_details', order_id=order.id))


@main.route('/delivery_logs')
@login_required
def delivery_logs():
    """Mostra os logs de entrega."""
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'logs', 'delivery.log')
    logs = []
    if os.path.exists(log_path):
        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                logs = f.readlines()
                logs.reverse()  # Mais recente primeiro
        except Exception:
            logs = ["Erro ao ler o arquivo de logs."]
    return render_template('delivery_logs.html', logs=logs)


@main.route('/test_roblox_connection')
@login_required
def test_roblox_connection():
    """Testa a conexão com a API do Roblox e exibe os resultados detalhados."""
    from flask import current_app

    roblox_cookie = current_app.config.get('ROBLOX_COOKIE') or os.getenv('ROBLOX_COOKIE', '')

    # Usa a função helper para testar todos os endpoints
    if not roblox_cookie:
        return render_template('test_connection.html', results={
            'error': 'ROBLOX_COOKIE não configurado no .env',
            'endpoints': [],
            'overall_success': False,
        })

    # Limpa e valida cookie
    roblox_cookie = roblox_cookie.strip()
    if len(roblox_cookie) < 20:
        return render_template('test_connection.html', results={
            'error': 'Cookie muito curto. Copie o .ROBLOSECURITY completo do navegador.',
            'endpoints': [],
            'overall_success': False,
        })

    # Usa a função de balance que já testa tudo internamente
    from mercadopago_utils import _create_session, _get_xsrf_token, verify_roblox_cookie

    results = {
        'error': None,
        'endpoints': [],
        'cookie_valid': False,
        'overall_success': False,
    }

    # Verifica cookie
    is_valid, error_msg = verify_roblox_cookie(roblox_cookie)
    results['cookie_valid'] = is_valid

    if not is_valid:
        results['error'] = error_msg
        results['endpoints'].append({
            'name': 'Cookie Check',
            'url': 'users.roblox.com/v1/users/authenticated',
            'status': 'error',
            'message': error_msg
        })
        return render_template('test_connection.html', results=results)

    # Cookie válido, agora testa os endpoints
    session = _create_session(roblox_cookie)
    _get_xsrf_token(session)

    endpoints = [
        {
            'name': 'Usuário Autenticado (v2)',
            'url': 'https://users.roblox.com/v1/users/authenticated',
            'method': 'GET',
        },
        {
            'name': 'Saldo Robux (Economy v1)',
            'url': 'https://economy.roblox.com/v1/user/currency',
            'method': 'GET',
        },
        {
            'name': 'Catalog API',
            'url': 'https://catalog.roblox.com/v1/catalog/items/details',
            'method': 'POST',
            'json': {'items': [{'id': 1, 'itemType': 'GamePass'}]},
        },
        {
            'name': 'Purchase API',
            'url': 'https://api.roblox.com/v1/purchases/game-pass/1',
            'method': 'POST',
            'json': {'expectedPrice': 1},
        },
    ]

    all_passed = True

    for ep in endpoints:
        try:
            if ep['method'] == 'GET':
                resp = session.get(ep['url'], timeout=15)
            else:
                resp = session.post(ep['url'], json=ep.get('json', {}), timeout=15)

            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if ep['name'] == 'Usuário Autenticado (v2)':
                        username = data.get('name', 'Unknown')
                        user_id = data.get('id')
                        msg = f"✅ Conectado como: {username} (ID: {user_id})"
                        results['endpoints'].append({
                            'name': ep['name'], 'status': 'ok',
                            'message': msg
                        })
                    elif ep['name'] == 'Saldo Robux (Economy v1)':
                        robux = data.get('robux', '?')
                        msg = f"💰 Saldo: {robux} Robux"
                        results['endpoints'].append({
                            'name': ep['name'], 'status': 'ok',
                            'message': msg
                        })
                    else:
                        msg = f"HTTP 200 - OK"
                        results['endpoints'].append({
                            'name': ep['name'], 'status': 'ok',
                            'message': msg,
                            'raw': json.dumps(data, default=str)[:300]
                        })
                except Exception:
                    results['endpoints'].append({
                        'name': ep['name'], 'status': 'ok',
                        'message': f"HTTP 200 (resposta não-JSON)",
                        'raw': resp.text[:300]
                    })
            elif resp.status_code == 401:
                results['endpoints'].append({
                    'name': ep['name'], 'status': 'error',
                    'message': f"HTTP 401 - Não autorizado (cookie expirado?)"
                })
                all_passed = False
            elif resp.status_code == 403:
                # 403 pode ser IP bloqueado
                body = resp.text[:200]
                results['endpoints'].append({
                    'name': ep['name'], 'status': 'warning',
                    'message': f"HTTP 403 - IP possivelmente bloqueado pelo Roblox. Considere usar proxy Cloudflare."
                })
                all_passed = False
            elif resp.status_code == 429:
                results['endpoints'].append({
                    'name': ep['name'], 'status': 'warning',
                    'message': f"HTTP 429 - Rate limit (tente novamente em alguns minutos)"
                })
                all_passed = False
            else:
                results['endpoints'].append({
                    'name': ep['name'], 'status': 'error',
                    'message': f"HTTP {resp.status_code}: {resp.text[:300]}"
                })
                all_passed = False

        except requests.exceptions.ConnectionError:
            results['endpoints'].append({
                'name': ep['name'], 'status': 'error',
                'message': 'Falha de conexão - rede/proxy pode estar bloqueando'
            })
            all_passed = False
        except requests.exceptions.Timeout:
            results['endpoints'].append({
                'name': ep['name'], 'status': 'error',
                'message': 'Timeout - servidor Roblox demorou muito para responder'
            })
            all_passed = False
        except Exception as e:
            results['endpoints'].append({
                'name': ep['name'], 'status': 'error',
                'message': str(e)[:200]
            })
            all_passed = False

    # Se purchase API deu 400/422 com mensagem de "insufficient funds", na verdade a API está OK
    # (significa que a compra foi recusada por falta de Robux, não por erro de conexão)
    for ep_result in results['endpoints']:
        if ep_result['name'] == 'Purchase API' and ep_result['status'] == 'error':
            raw = ep_result.get('message', '')
            if '400' in raw or '422' in raw:
                # A API respondeu, só rejeitou a compra
                ep_result['status'] = 'ok_partial'
                ep_result['message'] = raw + " ⟵ API funciona, compra rejeitada (sem Robux suficiente ou gamepass já comprada)"

    results['overall_success'] = all_passed

    return render_template('test_connection.html', results=results)
