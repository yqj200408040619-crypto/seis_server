#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/mseed-tcp-server"
DB_DIR="/var/lib/mseed-tcp-server/devices"
SERVICE="mseed-tcp-server"
BACKUP_DIR="${APP_DIR}/backups/code-v1-$(date +%Y%m%d-%H%M%S)"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo bash upgrade_v2_search_keys.sh" >&2
  exit 1
fi

if [[ ! -d "$APP_DIR" ]]; then
  echo "Application directory not found: $APP_DIR" >&2
  echo "Run install.sh first." >&2
  exit 1
fi

if [[ ! -x "${APP_DIR}/.venv/bin/python" ]]; then
  echo "Python venv not found: ${APP_DIR}/.venv/bin/python" >&2
  exit 1
fi

echo "Stopping ${SERVICE}..."
systemctl stop "$SERVICE" || true

echo "Backing up current code to ${BACKUP_DIR}..."
mkdir -p "$BACKUP_DIR"
cp -a "${APP_DIR}/mseed_tcp_server" "$BACKUP_DIR/" 2>/dev/null || true
cp -a "${APP_DIR}/tools" "$BACKUP_DIR/" 2>/dev/null || true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Installing updated code..."
rm -rf "${APP_DIR}/mseed_tcp_server" "${APP_DIR}/tools"
cp -a "${SCRIPT_DIR}/mseed_tcp_server" "${APP_DIR}/mseed_tcp_server"
cp -a "${SCRIPT_DIR}/tools" "${APP_DIR}/tools"
chmod +x "${APP_DIR}/tools/"*.py

if id mseed >/dev/null 2>&1; then
  chown -R mseed:mseed "${APP_DIR}/mseed_tcp_server" "${APP_DIR}/tools"
fi

echo "Migrating existing databases under ${DB_DIR}..."
"${APP_DIR}/.venv/bin/python" "${APP_DIR}/tools/migrate_add_search_keys.py" "$DB_DIR" || true

if id mseed >/dev/null 2>&1; then
  chown -R mseed:mseed /var/lib/mseed-tcp-server || true
fi

echo "Starting ${SERVICE}..."
systemctl start "$SERVICE"
systemctl status "$SERVICE" --no-pager -l

echo "Done. Check status with:"
echo "sudo ${APP_DIR}/.venv/bin/python ${APP_DIR}/tools/check_status.py"
