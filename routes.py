from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import login_user, login_required, logout_user, current_user
from flask_mail import Message
from models import User, Product, CartItem
from extensions import db, mail
import re
import secrets
import requests
from datetime import datetime, timedelta
import os
from bs4 import BeautifulSoup

main = Blueprint('main', __name__)

def get_roblox_gamepass_price(gamepass_link, roblox_cookie):
    """Extrai o ID da Gamepass do link e verifica o preço real no Roblox."""
    try:
        # Extrair o ID da Gamepass do link
        match = re.search(r'game-pass/(\d+)', gamepass_link)
        if not match:
            return None, "Link da Gamepass inválido"

        gamepass_id = match.group(1)

        # Headers com o cookie de autenticação
        headers = {
            'Cookie': f'.ROBLOSECURITY={roblox_cookie}',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept-Language': 'pt-BR,pt;q=0.9'
        }

        # Testar múltiplas variações de URL
        url_variations = [
            f'https://www.roblox.com/pt/game-pass/{gamepass_id}',
            f'https://www.roblox.com/game-pass/{gamepass_id}',
            gamepass_link
        ]

        html_content = None
        for url in url_variations:
            try:
                response = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
                if response.status_code == 200:
                    html_content = response.text
                    break
            except:
                continue

        if not html_content:
            return None, "Não foi possível acessar a página da Gamepass (Status 404)"

        soup = BeautifulSoup(html_content, 'html.parser')

        # Procurar pelo atributo data-expected-price
        elements_with_price = soup.find_all(attrs={'data-expected-price': True})
        for element in elements_with_price:
            price_str = element.get('data-expected-price')
            if price_str and price_str.isdigit():
                return int(price_str), None

        # Fallback: procurar por data-price
        elements_with_price2 = soup.find_all(attrs={'data-price': True})
        for element in elements_with_price2:
            price_str = element.get('data-price')
            if price_str and price_str.isdigit():
                return int(price_str), None

        # Fallback: procurar no texto por "Robux"
        robux_pattern = re.compile(r'(\d+)\s*[Rr]obux')
        matches = robux_pattern.findall(html_content)
        if matches:
            for m in matches:
                if int(m) > 0:
                    return int(m), None

        return None, "Não foi possível encontrar o preço da Gamepass na página"

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
                flash(f"Aviso: {error}", "error")
            elif actual_price is not None and actual_price != robux_amount:
                flash(f"O preço informado ({robux_amount} Robux) não corresponde ao preço da Gamepass no Roblox ({actual_price} Robux). Por favor, verifique.", "error")
                return render_template('gamepass_form.html', product=product)
        else:
            flash("Aviso: Configuração do Roblox não encontrada. Não foi possível verificar o preço.", "error")

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
