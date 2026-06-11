#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VENV_DIR="${VENV_DIR:-.venv}"

if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "Virtualenv not found at $VENV_DIR. Run scripts/install.sh first." >&2
  exit 1
fi

if [ ! -f .env ]; then
  echo ".env not found. Copy .env.example to .env and set TELEGRAM_BOT_TOKEN." >&2
  exit 1
fi

exec "$VENV_DIR/bin/python" bot.py
