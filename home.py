# home.py - Blueprint desativado
# A rota "/" é tratada em routes.py (blueprint 'main')
# NÃO importar este módulo no app.py
from flask import Blueprint, render_template

home_route = Blueprint('home', __name__, url_prefix='/home_page')

@home_route.route('/')
def home_fallback():
    return render_template('index.html')