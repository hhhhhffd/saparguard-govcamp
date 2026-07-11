#!/usr/bin/env bash
# Install SaparGuard on Debian/Ubuntu. Run from the uploaded deploy directory.
set -Eeuo pipefail

SERVICE_NAME="saparguard"
SERVICE_USER="saparguard"
INSTALL_DIR="${INSTALL_DIR:-/opt/${SERVICE_NAME}}"
BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT=()

note() { printf '\n==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; REPORT+=("WARNING: $*"); }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
require_root() { [[ "${EUID}" -eq 0 ]] || fail "Run as root: sudo bash scripts/install.sh"; }

require_root
[[ -r /etc/os-release ]] || fail "Unsupported OS: /etc/os-release is missing"
. /etc/os-release
case "${ID}" in ubuntu|debian) ;; *) fail "Supported operating systems: Debian and Ubuntu (found ${ID})" ;; esac

note "Checking ports and installing system dependencies"
if ss -ltnH "sport = :8000" | grep -q .; then
  fail "Port 8000 is already in use. Set another API_PORT in .env before installing."
fi
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-pip postgresql postgresql-contrib rsync curl openssl

PYTHON_BIN="$(command -v python3.12 || true)"
[[ -n "${PYTHON_BIN}" ]] || fail "Python 3.12 is required. Install python3.12 and python3.12-venv, then rerun."

if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "/var/lib/${SERVICE_NAME}" --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

note "Preparing application files in ${INSTALL_DIR}"
install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${INSTALL_DIR}"
rsync -a --delete \
  --exclude '.venv/' --exclude 'data/' --exclude 'logs/' --exclude '.env' \
  "${BUNDLE_DIR}/" "${INSTALL_DIR}/"
install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${INSTALL_DIR}/data" "${INSTALL_DIR}/logs"
if [[ ! -f "${INSTALL_DIR}/.env" ]]; then
  if [[ -f "${BUNDLE_DIR}/.env" ]]; then
    install -m 600 -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${BUNDLE_DIR}/.env" "${INSTALL_DIR}/.env"
  else
    install -m 600 -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${INSTALL_DIR}/.env.example" "${INSTALL_DIR}/.env"
    warn "Created ${INSTALL_DIR}/.env. Fill TELEGRAM_API_ID and TELEGRAM_API_HASH before authorizing Telethon."
  fi
fi
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"

note "Checking prebuilt frontend assets"
for asset in \
  "app/web/static/css/app.css" \
  "app/web/static/js/app.js" \
  "app/web/static/vendor/htmx.min.js" \
  "app/web/static/vendor/alpine-csp.min.js"; do
  [[ -f "${INSTALL_DIR}/${asset}" ]] || fail "Missing prebuilt frontend asset: ${asset}. Run scripts/prepare_deploy.sh before uploading the bundle."
done

note "Configuring PostgreSQL without removing existing data"
systemctl enable --now postgresql
for _ in {1..15}; do pg_isready -q && break; sleep 1; done
pg_isready -q || fail "PostgreSQL did not become ready"

if ! grep -qE '^DATABASE_URL=.+$' "${INSTALL_DIR}/.env"; then
  DB_PASSWORD="$(openssl rand -hex 24)"
  sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${SERVICE_NAME}'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE USER ${SERVICE_NAME} WITH PASSWORD '${DB_PASSWORD}';"
  sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${SERVICE_NAME}'" | grep -q 1 || \
    sudo -u postgres createdb -O "${SERVICE_NAME}" "${SERVICE_NAME}"
  printf '\nDATABASE_URL=postgresql+asyncpg://%s:%s@localhost:5432/%s\n' "${SERVICE_NAME}" "${DB_PASSWORD}" "${SERVICE_NAME}" >> "${INSTALL_DIR}/.env"
  chown "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}/.env"
  chmod 600 "${INSTALL_DIR}/.env"
else
  REPORT+=("Using DATABASE_URL already provided in .env; existing PostgreSQL data was not modified.")
fi

note "Creating Python environment and installing dependencies"
sudo -u "${SERVICE_USER}" "${PYTHON_BIN}" -m venv "${INSTALL_DIR}/.venv"
sudo -u "${SERVICE_USER}" "${INSTALL_DIR}/.venv/bin/pip" install --upgrade pip
sudo -u "${SERVICE_USER}" "${INSTALL_DIR}/.venv/bin/pip" install -r "${INSTALL_DIR}/requirements.txt"

note "Applying Alembic migrations"
sudo -u "${SERVICE_USER}" bash -c "cd '${INSTALL_DIR}' && .venv/bin/alembic upgrade head"

note "Installing systemd services"
sed "s|__INSTALL_DIR__|${INSTALL_DIR}|g" "${INSTALL_DIR}/deployment/systemd/saparguard-api.service" > /etc/systemd/system/saparguard-api.service
sed "s|__INSTALL_DIR__|${INSTALL_DIR}|g" "${INSTALL_DIR}/deployment/systemd/saparguard-collector.service" > /etc/systemd/system/saparguard-collector.service
systemctl daemon-reload
systemctl enable --now saparguard-api.service

sleep 2
if ! curl --fail --silent "http://127.0.0.1:$(grep '^API_PORT=' "${INSTALL_DIR}/.env" | cut -d= -f2 || echo 8000)/health" >/dev/null; then
  systemctl status --no-pager saparguard-api.service || true
  fail "API health check failed"
fi

if [[ -f "${INSTALL_DIR}/data/telethon.session" ]]; then
  systemctl enable --now saparguard-collector.service
  REPORT+=("Collector service started with the existing Telethon session.")
else
  systemctl disable --now saparguard-collector.service 2>/dev/null || true
  warn "Collector was not started: no Telethon session exists. After setting Telegram credentials, run: sudo -u ${SERVICE_USER} -H bash -c 'cd ${INSTALL_DIR} && .venv/bin/python -m app.collector.service' and complete Telegram login once."
fi

note "Installation report"
printf 'API: %s\n' "$(systemctl is-active saparguard-api.service)"
printf 'PostgreSQL: %s\n' "$(systemctl is-active postgresql.service)"
printf 'Collector: %s\n' "$(systemctl is-active saparguard-collector.service || true)"
printf '%s\n' "${REPORT[@]:-No warnings.}"
