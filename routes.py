from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from markupsafe import Markup
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import login_user, login_required, logout_user, current_user
from flask_mail import Message
from models import User, Product, CartItem, Order, OrderItem
from extensions import db, mail
import re
import secrets
import requests
from datetime import datetime, timedelta
import os
import urllib.parse

main = Blueprint('main', __name__)

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
            'Referer': 'https://www.roblox.com/',
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

        # Fallback: usa a URL original enviada pelo usuário (com slug completo)
        try:
            # Se o link já tem slug, usa ele diretamente
            if '/DONATE' in gamepass_link or '/donate' in gamepass_link.lower():
                page_url = gamepass_link
            else:
                page_url = f'https://www.roblox.com/game-pass/{gamepass_id}'

            resp = s.get(page_url, timeout=15, allow_redirects=True)
            if resp.status_code == 200:
                html = resp.text
                # Procura por padrões comuns de preço
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

def is_valid_email(email):
    # Validação simples mas eficaz de email
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        return False
    return True

@main.route('/')
def index():
    products = Product.query.all()
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

        # Gerar token de verificação e enviar email
        token = new_user.generate_verification_token()
        db.session.commit()

        verification_url = url_for('main.verify_email', token=token, _external=True)

        # Enviar email de verificação via SMTP (Flask-Mail)
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
            # Se falhar o envio, mostrar link no terminal
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

        # Verificar se é email ou username
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

            # Enviar email via SMTP
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
                # Se falhar, mostrar no terminal
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
    flash(f"{product.name} adicionado ao carrinho!", "success")
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

        # Verificar o preço real da Gamepass no Roblox
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
    cart_items = CartItem.query.filter_by(user_id=current_user.id).all()
    total = 0
    for item in cart_items:
        if item.robux_amount and item.product.is_gamepass:
            total += round(item.robux_amount * item.product.price_per_robux, 2) * item.quantity
        else:
            total += item.product.price * item.quantity
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

        # Verificar senha atual
        if not check_password_hash(current_user.password, current_password):
            flash("Senha atual incorreta!", "error")
            return render_template('profile.html')

        # Verificar se novas senhas coincidem
        if new_password != confirm_password:
            flash("Novas senhas não coincidem!", "error")
            return render_template('profile.html')

        # Alterar senha
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

    pix_key = current_app.config.get('PIX_KEY') or os.getenv('PIX_KEY', '')
    if not pix_key:
        flash("Erro: Chave Pix não configurada!", "error")
        return redirect(url_for('main.cart'))

    # Gerar Pix Copia e Cola (formato BR Code simplificado)
    pix_code = f"00020126580014br.gov.bcb.pix0136{pix_key}520400005303986540{int(total*100):02d}5802BR5925Probux Robux6009Sao Paulo62070503***6304"
    import zlib
    crc = zlib.crc32(pix_code.encode()) & 0xffffffff
    pix_code = pix_code + f"{crc:04X}"

    # Gerar QR Code usando Google Charts API (sem biblioteca externa)
    qr_url = f"https://chart.googleapis.com/chart?cht=qr&chs=250x250&chl={urllib.parse.quote(pix_code)}"

    return render_template('checkout.html', total=total, qr_url=qr_url, pix_code=pix_code, cart_items=cart_items)

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
    pix_code = f"00020126580014br.gov.bcb.pix0136{pix_key}520400005303986540{int(total*100):02d}5802BR5925Probux Robux6009Sao Paulo62070503***6304"
    import zlib
    crc = zlib.crc32(pix_code.encode()) & 0xffffffff
    pix_code = pix_code + f"{crc:04X}"

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
    order = Order.query.get_or_404(order_id)
    if order.user_id != current_user.id:
        flash("Acesso negado!", "error")
        return redirect(url_for('main.index'))
    return render_template('order.html', order=order)

@main.route('/como-criar-gamepass')
def como_criar_gamepass():
    return render_template('como-criar-gamepass.html')
