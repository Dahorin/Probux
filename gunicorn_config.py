# Gunicorn Configuration for Probux
# Usage: gunicorn --config gunicorn_config.py "app:create_app()"

import multiprocessing
import os

# Server socket
bind = os.environ.get('GUNICORN_BIND', "127.0.0.1:5000")
backlog = 2048

# Application factory - importa do app.py
# Gunicorn vai chamar: app:create_app()
# O 'app' aqui refere-se ao módulo app.py dentro de /var/www/probux
# IMPORTANTE: No probux.service, use o WorkingDirectory correto
app = 'app:create_app'

# Worker processes
workers = int(os.environ.get('GUNICORN_WORKERS', multiprocessing.cpu_count() * 2 + 1))
worker_class = "sync"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50
timeout = 120
keepalive = 5

# Logging
accesslog = os.environ.get('GUNICORN_ACCESS_LOG', "-")
errorlog = os.environ.get('GUNICORN_ERROR_LOG', "-")
loglevel = os.environ.get('GUNICORN_LOGLEVEL', "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "probux_app"

# Server mechanics
daemon = False
pidfile = "/var/run/probux/gunicorn.pid"
user = None
group = None
umask = 0
tmp_upload_dir = None

# SSL (descomentar se Gunicorn servir diretamente com HTTPS)
# keyfile = "/etc/letsencrypt/live/seu-dominio.com/privkey.pem"
# certfile = "/etc/letsencrypt/live/seu-dominio.com/fullchain.pem"

# Graceful shutdown
graceful_timeout = 30
spew = False

# Preload app (melhora performance, mas desabilita live code reload)
preload_app = True