#!/usr/bin/env bash
# Sobe o Contract Analyzer com Docker Compose (Linux/macOS)
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  if [[ -f .env.docker.example ]]; then
    cp .env.docker.example .env
    echo "Arquivo .env criado — edite GOOGLE_API_KEY antes de usar em produção."
  else
    echo "Crie um arquivo .env com GOOGLE_API_KEY." >&2
    exit 1
  fi
fi

docker compose up -d --build

APP_PORT=8501
if grep -qE '^[[:space:]]*APP_PORT=' .env 2>/dev/null; then
  APP_PORT=$(grep -E '^[[:space:]]*APP_PORT=' .env | head -1 | cut -d= -f2 | tr -d ' ')
fi

echo ""
echo "Contract Analyzer: http://localhost:${APP_PORT}"
echo "Logs: docker compose logs -f"
echo "Parar: docker compose down"
