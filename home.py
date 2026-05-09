# home.py - DESATIVADO
# A rota "/" é tratada em routes.py (blueprint 'main')
# Não registrar este blueprint em app.py
from flask import Blueprint, render_template

home_route = Blueprint('home', __name__, url_prefix='/home_page')

# Rota movida para routes.py@main.route('/')
# Esta versão existe apenas como fallback acessando /home_page/index
@home_route.route('/')
def home_fallback():
    return render_template('index.html')