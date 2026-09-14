#!/usr/bin/env bash
set -euo pipefail

APP_SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="/opt/mseed-web-portal"
CONFIG_DIR="/etc/mseed-web-portal"
STATE_DIR="/var/lib/mseed-web-portal"
LOG_DIR="/var/log/mseed-web-portal"
SERVICE_FILE="/etc/systemd/system/mseed-web-portal.service"

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root: sudo bash install.sh" >&2
  exit 1
fi

echo "[1/8] Installing OS packages"
apt-get update
apt-get install -y python3 python3-venv python3-pip nginx openssl sqlite3

echo "[2/8] Creating service user"
if ! id -u mseedweb >/dev/null 2>&1; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin mseedweb
fi
if getent group mseed >/dev/null 2>&1; then
  usermod -aG mseed mseedweb || true
fi

echo "[3/8] Installing application files"
mkdir -p "$APP_DIR" "$CONFIG_DIR" "$STATE_DIR" "$LOG_DIR"
rsync -a --delete --exclude '.venv' "$APP_SRC_DIR/" "$APP_DIR/"

if [[ ! -f "$CONFIG_DIR/portal.ini" ]]; then
  cp "$APP_DIR/config/portal.ini" "$CONFIG_DIR/portal.ini"
  SECRET=$(openssl rand -hex 32)
  sed -i "s/^secret_key = .*/secret_key = ${SECRET}/" "$CONFIG_DIR/portal.ini"
fi

echo "[4/8] Creating Python virtual environment"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip wheel setuptools
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "[5/8] Setting permissions"
chown -R mseedweb:mseedweb "$APP_DIR" "$STATE_DIR" "$LOG_DIR"
chmod 750 "$STATE_DIR" "$LOG_DIR"
if [[ -d /var/lib/mseed-tcp-server/devices ]]; then
  chmod o+rx /var/lib/mseed-tcp-server || true
  chmod o+rx /var/lib/mseed-tcp-server/devices || true
fi

echo "[6/8] Installing systemd service"
cp "$APP_DIR/systemd/mseed-web-portal.service" "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable mseed-web-portal

echo "[7/8] Installing nginx reverse proxy"
cp "$APP_DIR/nginx/mseed-web-portal.conf" /etc/nginx/sites-available/mseed-web-portal.conf
ln -sf /etc/nginx/sites-available/mseed-web-portal.conf /etc/nginx/sites-enabled/mseed-web-portal.conf
if [[ -f /etc/nginx/sites-enabled/default ]]; then
  rm -f /etc/nginx/sites-enabled/default
fi
nginx -t
systemctl enable nginx
systemctl reload nginx || systemctl restart nginx

echo "[8/8] Starting service"
systemctl restart mseed-web-portal

echo
cat <<MSG
Installed.

Next steps:
1) Create admin user:
   sudo /opt/mseed-web-portal/.venv/bin/python /opt/mseed-web-portal/tools/create_admin.py --username admin --role admin

2) Sync receiver devices:
   sudo /opt/mseed-web-portal/.venv/bin/python /opt/mseed-web-portal/tools/sync_devices.py

3) Open in browser:
   http://<server-ip>/

4) Check service:
   sudo systemctl status mseed-web-portal
   sudo journalctl -u mseed-web-portal -f
MSG
