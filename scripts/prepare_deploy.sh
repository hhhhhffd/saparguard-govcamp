#!/usr/bin/env bash
# Build a self-contained deployment directory for: scp -r deploy user@host:~/
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="${1:-${ROOT_DIR}/deploy}"
STAGING_DIR="${DEPLOY_DIR}.staging.$$"

if ! command -v corepack >/dev/null 2>&1; then
  echo "ERROR: Corepack (Node.js) is required to build frontend assets before deployment." >&2
  exit 1
fi

(
  cd "${ROOT_DIR}/web-assets"
  corepack pnpm install --frozen-lockfile
  corepack pnpm build
)

cleanup() { rm -rf "${STAGING_DIR}"; }
trap cleanup EXIT

mkdir -p "${STAGING_DIR}"
rsync -a \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '*.py[cod]' \
  --exclude '.pytest_cache/' \
  --exclude 'logs/' \
  --exclude '/data/' \
  --exclude 'deploy/' \
  --exclude '.env' \
  "${ROOT_DIR}/" "${STAGING_DIR}/"

if [[ -f "${ROOT_DIR}/.env" ]]; then
  install -m 600 "${ROOT_DIR}/.env" "${STAGING_DIR}/.env"
  echo "Included local .env in deployment package."
else
  echo "No local .env found; install.sh will create one from .env.example."
fi

mkdir -p "${DEPLOY_DIR}"
rsync -a --delete "${STAGING_DIR}/" "${DEPLOY_DIR}/"
echo "Deployment package is ready: ${DEPLOY_DIR}"
