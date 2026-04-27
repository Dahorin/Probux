from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import login_user, login_required, logout_user, current_user
from flask_mail import Message
from models import User, Product, CartItem
from extensions import db, mail
import re
import secrets
from datetime import datetime, timedelta

main = Blueprint('main', __name__)

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

        # Enviar email de verificação
        try:
            msg = Message(
                'Confirme seu Email - Probux',
                recipients=[email]
            )
            msg.body = f'''Olá {username},

Obrigado por se cadastrar no Probux!

Para confirmar seu email, clique no link abaixo:
{verification_url}

Este link expira em 24 horas.

Se você não se cadastrou, ignore este email.

Atenciosamente,
Equipe Probux
'''

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

            # Mostrar o link no terminal (sem enviar email)
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
    cart_item = CartItem.query.filter_by(user_id=current_user.id, product_id=product_id).first()

    if cart_item:
        cart_item.quantity += 1
    else:
        cart_item = CartItem(user_id=current_user.id, product_id=product_id, quantity=1)
        db.session.add(cart_item)

    db.session.commit()
    flash(f"{product.name} adicionado ao carrinho!", "success")
    return redirect(url_for('main.index'))

@main.route('/cart')
@login_required
def cart():
    cart_items = CartItem.query.filter_by(user_id=current_user.id).all()
    total = sum(item.product.price * item.quantity for item in cart_items)
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