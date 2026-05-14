from flask import Flask
from flask_mail import Mail
from dotenv import load_dotenv
import os
from extensions import db, login_manager


def create_app():
    """Application factory - necessário para Gunicorn + systemd."""
    import os
    load_dotenv()

    app = Flask(__name__, template_folder='templates')

    # Segredo da aplicação
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

    return app


# Instância global - usada pelo Gunicorn via factory
app = create_app()


if __name__ == '__main__':
    import os
    import subprocess
    import sys
    import signal

    # Se RUN_PROXY=true (padrão), inicia o proxy Node.js automaticamente
    # Defina RUN_PROXY=false se o proxy já estiver rodando separadamente
    # (ex: Cloudflare Worker, servidor remoto, etc.)
    run_proxy = os.environ.get('RUN_PROXY', 'true').lower() == 'true'

    proxy_process = None

    if run_proxy:
        # Mata processos Node presos na porta 3999 antes de iniciar
        try:
            if sys.platform == 'win32':
                subprocess.run(
                    'for /f "tokens=5" %a in (\'netstat -ano ^| findstr :3999\') do taskkill /f /pid %a 2>nul',
                    shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5
                )
            else:
                subprocess.run(
                    'pkill -f "node proxy-roblox.js" 2>/dev/null; sleep 0.5',
                    shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5
                )
        except Exception:
            pass

        try:
            print('🚀 Iniciando proxy Roblox (Node.js)...')
            proxy_process = subprocess.Popen(
                ['node', 'proxy-roblox.js'],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            # Verifica se o proxy iniciou com sucesso
            import time
            time.sleep(0.5)
            if proxy_process.poll() is not None:
                stdout, _ = proxy_process.communicate()
                print(f'⚠️  Proxy falhou ao iniciar: {stdout.decode("utf-8", errors="replace")}')
                proxy_process = None
            else:
                print(f'✅ Proxy Roblox rodando (PID: {proxy_process.pid})')
                print(f'   Endpoint: http://localhost:3999/proxy')
        except FileNotFoundError:
            print('⚠️  "node" não encontrado no PATH. Proxy não será iniciado.')
            print('   Instale o Node.js ou defina RUN_PROXY=false')
            proxy_process = None
        except Exception as e:
            print(f'⚠️  Erro ao iniciar proxy: {e}')
            proxy_process = None

    try:
        # Square Cloud / Railway / Render definem a porta via variável PORT
        port = int(os.environ.get('PORT', 8080))
        is_production = os.getenv('FLASK_ENV', 'production') == 'production'

        # Nunca use debug=True em produção!
        print(f'🌐 Flask rodando na porta {port}')
        app.run(debug=False, host='0.0.0.0', port=port)
    except KeyboardInterrupt:
        print('\n🛑 Servidor interrompido pelo usuário.')
    except Exception as e:
        print(f'\n❌ Erro no servidor Flask: {e}')
    finally:
        if proxy_process:
            print('🛑 Encerrando proxy Roblox...')
            proxy_process.terminate()
            try:
                proxy_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proxy_process.kill()
                proxy_process.wait()
            print('✅ Proxy Roblox encerrado.')