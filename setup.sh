#!/bin/bash
# ============================================================
# SETUP SCRIPT - Probux VPS Installation
# Para Ubuntu 22.04 / Debian 12
# Execute: bash setup.sh SEU_DOMINIO
# ============================================================

set -e

DOMINIO=${1:-"probux.com.br"}
APP_DIR="/var/www/probux"
APP_USER="www-data"

echo "=========================================="
echo "  SETUP PROBUX - VPS"
echo "  Dominio: $DOMINIO"
echo "=========================================="

# Atualizar sistema
echo "[1/10] Atualizando sistema..."
sudo apt update && sudo apt upgrade -y

# Instalar dependências do sistema
echo "[2/10] Instalando dependências do sistema..."
sudo apt install -y \
    python3-pip python3-venv libpq-dev \
    nginx certbot python3-certbot-nginx \
    curl wget git \
    libatk1.0-0 libatk-bridge2.0-0 \
    libxkbcommon0 libxcomposite1 libxdamage1 \
    libxrandr2 libgbm1 libasound2 \
    libxshmfence1 libnss3 libxss1

# Instalar Node.js 20
echo "[3/10] Instalando Node.js..."
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -
sudo apt install -y nodejs

# Criar diretório do app
echo "[4/10] Criando estrutura de diretórios..."
sudo mkdir -p "$APP_DIR"
sudo mkdir -p /var/log/probux
sudo mkdir -p /var/run/probux
sudo chown -R "$APP_USER":"$APP_USER" "$APP_DIR"
sudo chown -R www-data:www-data /var/log/probux
sudo chown -R www-data:www-data /var/run/probux

# Copiar arquivos do projeto (assumindo que já estão no servidor)
echo "[5/10] Configurando projeto..."
cd "$APP_DIR"

# Criar ambiente virtual
echo "[6/10] Criando ambiente virtual Python..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

# Configurar .env (CRIAR MANUALMENTE com as credenciais!)
echo "[7/10] ATENÇÃO: Configure o arquivo .env com suas credenciais!"
echo "  Copie o arquivo .env de produção para: $APP_DIR/.env"
echo "  Use o comando: cp /caminho/do/.env $APP_DIR/.env"

# Configurar Nginx
echo "[8/10] Configurando Nginx..."
# Substituir o placeholder no arquivo de configuração
sed -i "s|SEU_DOMINIO_AQUI\.COM|$DOMINIO|g" nginx_conf.txt
sudo cp nginx_conf.txt /etc/nginx/sites-available/probux
sudo ln -sf /etc/nginx/sites-available/probux /etc/nginx/sites-enabled/probux
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

# SSL com Let's Encrypt
echo "[9/10] Configurando SSL..."
sudo certbot --nginx -d "$DOMINIO" --non-interactive --agree-tos -m admin@"$DOMINIO"

# Configurar serviço systemd
echo "[10/10] Configurando serviço systemd..."
sudo cp probux.service /etc/systemd/system/probux.service
sudo systemctl daemon-reload
sudo systemctl enable probux
sudo systemctl start probux

echo ""
echo "=========================================="
echo "  SETUP CONCLUÍDO!"
echo "=========================================="
echo ""
echo "Próximos passos:"
echo "  1. Configure o arquivo .env em: $APP_DIR/.env"
echo "  2. Reinicie o serviço: sudo systemctl restart probux"
echo "  3. Verifique o status: sudo systemctl status probux"
echo "  4. Acesse: https://$DOMINIO"
echo ""
echo "Logs:"
echo "  tail -f /var/log/probux/gunicorn.log"
echo "  journalctl -u probux -f"