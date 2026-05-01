from flask import Flask
from flask_mail import Mail
from dotenv import load_dotenv
import os
from extensions import db, login_manager
from models import User
from routes import main

# Carregar variáveis de ambiente do arquivo .env
load_dotenv()

app = Flask(__name__)

app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'segredo_super_secreto_padrao')
# PostgreSQL como banco oficial
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'postgresql://postgres@localhost:5432/probux')

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
    return User.query.get(int(user_id))

app.register_blueprint(main)

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
