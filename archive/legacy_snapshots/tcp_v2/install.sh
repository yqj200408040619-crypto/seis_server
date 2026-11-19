#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/mseed-tcp-server"
CONF_DIR="/etc/mseed-tcp-server"
DATA_DIR="/var/lib/mseed-tcp-server"
LOG_DIR="/var/log/mseed-tcp-server"
SERVICE_FILE="/etc/systemd/system/mseed-tcp-server.service"

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root: sudo bash install.sh"
  exit 1
fi

apt-get update
apt-get install -y python3 python3-venv python3-pip build-essential libxml2-dev libxslt1-dev libffi-dev libssl-dev

if ! id -u mseed >/dev/null 2>&1; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin mseed
fi

mkdir -p "$APP_DIR" "$CONF_DIR" "$DATA_DIR/devices" "$DATA_DIR/quarantine" "$LOG_DIR"
cp -r mseed_tcp_server tools requirements.txt "$APP_DIR"/
cp config/server.ini "$CONF_DIR/server.ini"
cp systemd/mseed-tcp-server.service "$SERVICE_FILE"

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip wheel setuptools
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

chown -R mseed:mseed "$APP_DIR" "$DATA_DIR" "$LOG_DIR"
chmod 750 "$DATA_DIR" "$LOG_DIR"
chmod 640 "$CONF_DIR/server.ini"

systemctl daemon-reload
systemctl enable mseed-tcp-server.service

echo "Installed. Edit $CONF_DIR/server.ini if needed, then run:"
echo "  sudo systemctl start mseed-tcp-server"
echo "  sudo journalctl -u mseed-tcp-server -f"
