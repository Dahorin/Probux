#!/bin/bash
# ============================================================
# DEPLOY SCRIPT - Atualização do Probux na VPS
# Execute na VPS: bash deploy.sh
# ============================================================

set -e

APP_DIR="/var/www/probux"
BRANCH="main"

echo "=========================================="
echo "  DEPLOY PROBUX"
echo "=========================================="

cd "$APP_DIR"

echo "[1/5] Puxando atualizações do Git..."
git fetch origin
git checkout "$BRANCH"
git pull origin "$BRANCH"

echo "[2/5] Ativando ambiente virtual..."
source venv/bin/activate

echo "[3/5] Instalando/atualizando dependências..."
pip install --upgrade pip
pip install -r requirements.txt

echo "[4/5] Rodando migrações do banco de dados..."
python -c "from app import app, db; app.app_context().push(); db.create_all()"

echo "[5/5] Reiniciando serviço..."
deactivate
sudo systemctl restart probux

# Limpa arquivos temporários do Puppeteer
rm -f "$APP_DIR"/debug-*.png
rm -f "$APP_DIR"/logs/*.png 2>/dev/null || true

echo ""
echo "=========================================="
echo "  DEPLOY CONCLUÍDO!"
echo "=========================================="
echo "  Status: sudo systemctl status probux"
echo "  Logs:   tail -f /var/log/probux/gunicorn.log"