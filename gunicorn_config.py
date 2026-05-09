# Gunicorn Configuration for Probux
# Usage: gunicorn --config gunicorn_config.py app:app

import multiprocessing

# Server socket
bind = "127.0.0.1:5000"
backlog = 2048

# Worker processes
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50
timeout = 120
keepalive = 5

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"
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