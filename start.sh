#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p data backups media
[ -f .env ] || cp .env.example .env
docker compose up -d --build
