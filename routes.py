from flask import Blueprint, render_template, redirect, url_for, request, flash
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import login_user, login_required, logout_user, current_user
from models import User
from extensions import db

main = Blueprint('main', __name__)

@main.route('/')
def index():
    return render_template('index.html')
@login_required
def dashboard():
    return render_template('dashboard.html', name=current_user.username)

@main.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])

        if User.query.filter_by(username=username).first():
            flash("Usuário já existe!")
            return redirect(url_for('main.register'))

        new_user = User(username=username, password=password)
        db.session.add(new_user)
        db.session.commit()

        flash("Conta criada com sucesso!")
        return redirect(url_for('main.login'))

    return render_template('register.html')

@main.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()

        if user and check_password_hash(user.password, request.form['password']):
            login_user(user)
            return redirect(url_for('main.dashboard'))
        else:
            flash("Credenciais inválidas")

    return render_template('login.html')

@main.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('main.login'))