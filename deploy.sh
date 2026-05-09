#!/usr/bin/env bash
# ============================================================
# DEPLOY SCRIPT - Square Cloud / VPS
# Execute: bash deploy.sh
# ============================================================

set -e

APP_DIR="."

echo "=========================================="
echo "  DEPLOY PROBUX"
echo "=========================================="

# Detecta se é Square Cloud ou VPS
if [ -n "$SQUARECLOUD_ENV" ]; then
    echo "[INFO] Ambiente: Square Cloud"
    IS_SQUARE=true
else
    echo "[INFO] Ambiente: VPS"
    IS_SQUARE=false
fi

echo "[1/4] Atualizando dependências Python..."
python3 -m pip install --upgrade pip --quiet 2>/dev/null || pip install --upgrade pip --quiet 2>/dev/null || pip3 install --upgrade pip --quiet 2>/dev/null
pip install -r requirements.txt 2>&1 | tail -5

echo "[2/4] Garantindo diretórios..."
mkdir -p logs

echo "[3/4] Verificando banco de dados..."
python3 -c "
from app import create_app
app = create_app()
with app.app_context():
    from extensions import db
    from models import Product, User
    db.create_all()
    # Atualiza price_per_robux
    products = Product.query.all()
    for p in products:
        if p.price_per_robux != 0.034:
            p.price_per_robux = 0.034
    db.session.commit()
    print('[OK] Banco de dados verificado!')
"

# Para Square Cloud, NÃO reiniciar serviço (o próprio platform faz isso)
# Para VPS, reiniciar com systemd
if [ "$IS_SQUARE" = false ]; then
    echo "[4/4] Reiniciando serviço..."
    sudo systemctl restart probux 2>/dev/null || echo "[AVISO] Não foi possível reiniciar via systemd"
else
    echo "[4/4] Deploy concluído! O Square Cloud vai reiniciar automaticamente."
fi

# Limpa screenshots antigos
rm -f debug-*.png logs/debug-*.png 2>/dev/null || true

echo ""
echo "=========================================="
echo "  DEPLOY CONCLUÍDO!"
echo "=========================================="