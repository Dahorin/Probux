from flask import Flask
from flask_mail import Mail
from dotenv import load_dotenv
import os
from extensions import db, login_manager

load_dotenv()

app = Flask(__name__)

app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'awmjd-jawpdjpoJAOI@JOIALJDASLDJl2kdjmnaksmndal')

# Configurações de sessão para HTTPS (produção)
app.config['SESSION_COOKIE_SECURE'] = True  # OBRIGATÓRIO para HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # 1 hora

# ProxyFix para rodar atrás de Nginx/reverso proxy
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
# PostgreSQL como banco oficial
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'postgresql://postgres@localhost:5432/probux')
# Roblox cookie para verificação de Gamepass
app.config['ROBLOX_COOKIE'] = os.getenv('ROBLOX_COOKIE', '')

# Desconto da conta banco (10% = 0.10)
DISCOUNT_PERCENT = float(os.getenv('DISCOUNT_PERCENT', '0'))
app.config['DISCOUNT_PERCENT'] = DISCOUNT_PERCENT

# Configurações do Flask-Mail via variáveis de ambiente (SMTP Umbler)
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.umbler.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True') == 'True'
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER')

mail = Mail(app)

db.init_app(app)
login_manager.init_app(app)
login_manager.login_view = 'main.login'

@login_manager.user_loader
def load_user(user_id):
    from models import User
    return User.query.get(int(user_id))

from routes import main
app.register_blueprint(main)

with app.app_context():
    db.create_all()
    # Update price_per_robux to 0.034 for all products
    from models import Product
    products = Product.query.all()
    for product in products:
        if product.price_per_robux != 0.034:
            product.price_per_robux = 0.034
    db.session.commit()

if __name__ == '__main__':
    # Em produção, use Gunicorn: gunicorn --config gunicorn_config.py app:app
    # Nunca use debug=True em produção!
    import os
    is_production = os.getenv('FLASK_ENV', 'production') == 'production'
    app.run(debug=not is_production, host='0.0.0.0', port=5000)
