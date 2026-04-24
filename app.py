from flask import Flask
from extensions import db, login_manager
from models import User
from routes import main

app = Flask(__name__)

app.config['SECRET_KEY'] = 'segredo_super_secreto'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'

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
