#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
docker compose logs --follow --tail=200
