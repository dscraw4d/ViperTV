#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p data backups media
[ -f .env ] || cp .env.example .env
if [ ! -e /dev/dri ]; then
  echo "ERROR: /dev/dri is not present. Use ./start.sh for software encoding."
  exit 1
fi
docker compose -f compose.yml -f compose.intel-vaapi.yml up -d --build
