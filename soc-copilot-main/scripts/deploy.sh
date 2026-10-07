#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────────────
# SOC Copilot — production deploy on Hetzner.
# Run on the server as user `soc` from anywhere:
#   bash /opt/soc-copilot/scripts/deploy.sh
# ────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_DIR="/opt/soc-copilot"
COMPOSE="docker compose -f ${REPO_DIR}/infra/docker-compose.prod.yml --env-file ${REPO_DIR}/.env"

cd "$REPO_DIR"

echo "==> git pull"
git pull --ff-only

echo "==> guard: required env vars"
required=(GEMINI_API_KEY POSTGRES_PASSWORD JWT_SECRET APP_ENCRYPTION_KEY \
          NEXTAUTH_SECRET PUBLIC_DOMAIN ACME_EMAIL NEXT_PUBLIC_API_URL)
missing=0
for v in "${required[@]}"; do
  if ! grep -qE "^${v}=.+" .env; then
    echo "  MISSING: $v" >&2
    missing=1
  fi
done
[ "$missing" -eq 1 ] && { echo "Aborting: .env incomplete." >&2; exit 1; }

echo "==> build + up"
$COMPOSE up -d --build

echo "==> status"
$COMPOSE ps

echo "==> recent logs"
$COMPOSE logs --tail=15 api web caddy

echo "==> done. https://$(grep ^PUBLIC_DOMAIN .env | cut -d= -f2)"