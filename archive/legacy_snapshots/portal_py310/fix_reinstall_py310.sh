#!/usr/bin/env bash
set -euo pipefail
APP_DIR="/opt/mseed-web-portal"

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root: sudo bash fix_reinstall_py310.sh" >&2
  exit 1
fi

echo "[1/4] Installing Python 3.10 venv support"
apt-get update
apt-get install -y python3.10 python3.10-venv python3.10-dev python3-pip build-essential

echo "[2/4] Recreating web portal virtualenv with Python 3.10"
systemctl stop mseed-web-portal 2>/dev/null || true
rm -rf "$APP_DIR/.venv"
/usr/bin/python3.10 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/python" -m pip install --upgrade pip wheel setuptools
"$APP_DIR/.venv/bin/python" -m pip install --prefer-binary -r "$APP_DIR/requirements.txt"

echo "[3/4] Verifying runtime"
"$APP_DIR/.venv/bin/python" -c "import sys, obspy; print('Python:', sys.version); print('ObsPy:', obspy.__version__)"

echo "[4/4] Restarting service"
systemctl daemon-reload
systemctl restart mseed-web-portal
systemctl status mseed-web-portal --no-pager -l
