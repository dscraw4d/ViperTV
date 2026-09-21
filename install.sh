#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: Docker is not installed or is not in PATH."
  echo "Install Docker Engine/Desktop with Docker Compose, then run this again."
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "ERROR: Docker Compose v2 ('docker compose') is required."
  exit 1
fi

mkdir -p data backups media
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

echo "Building and starting ViperTV..."
docker compose up -d --build

echo
echo "ViperTV is starting."
echo "Open: http://localhost:${VIPERTV_PORT:-8409}"
echo "For another device on your LAN, use this machine's LAN IP with the same port."
echo "Run ./logs.sh to watch startup logs."
