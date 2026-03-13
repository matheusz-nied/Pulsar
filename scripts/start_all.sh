#!/bin/bash
# Inicia todos os serviços do Pulsar: backend, bot, frontend.

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

trap 'echo ""; echo "Encerrando serviços..."; kill $(jobs -p) 2>/dev/null; exit 0' EXIT INT TERM

echo "==============================="
echo "  PULSAR — Iniciando serviços"
echo "==============================="
echo ""

# Ativar ambiente Python
if [ -d "$PROJECT_DIR/.conda_env" ]; then
  export PATH="$PROJECT_DIR/.conda_env/bin:$PATH"
  echo "[env] Usando .conda_env"
elif [ -d "$PROJECT_DIR/.venv" ]; then
  source "$PROJECT_DIR/.venv/bin/activate"
  echo "[env] Usando .venv"
fi

# Carregar variáveis de ambiente
if [ -f "$PROJECT_DIR/.env" ]; then
  set -a
  source "$PROJECT_DIR/.env"
  set +a
fi

# 1. Backend
echo "[1/3] Iniciando backend (porta 8000)..."
cd "$PROJECT_DIR"
uvicorn backend.main:app --reload --port 8000 > "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
echo "      PID: $BACKEND_PID | Log: logs/backend.log"

# 2. Telegram Bot (se token configurado)
if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
  echo "[2/3] Iniciando Telegram Bot..."
  python "$PROJECT_DIR/scripts/start_bot.py" > "$LOG_DIR/bot.log" 2>&1 &
  BOT_PID=$!
  echo "      PID: $BOT_PID | Log: logs/bot.log"
else
  echo "[2/3] Telegram Bot: TELEGRAM_BOT_TOKEN não definido, pulando."
fi

# 3. Frontend Tauri
echo "[3/3] Iniciando frontend Tauri..."
cd "$PROJECT_DIR/frontend"
npx tauri dev > "$LOG_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!
echo "      PID: $FRONTEND_PID | Log: logs/frontend.log"

echo ""
echo "==============================="
echo "  Todos os serviços iniciados"
echo "==============================="
echo ""
echo "  Backend:  http://localhost:8000"
echo "  Logs:     $LOG_DIR/"
echo ""
echo "  Pressione Ctrl+C para encerrar tudo."
echo ""

wait
