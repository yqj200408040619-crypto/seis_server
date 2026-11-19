#!/usr/bin/env bash
set -Eeuo pipefail
shopt -s nullglob

ARCHIVE="${1:-}"
WORK="/tmp/mseed_migration_restore_$$"
BACKUP="/root/mseed_pre_restore_backup_$(date +%Y%m%d_%H%M%S).tar.gz"

usage() {
  cat <<'EOF'
Usage:
  sudo bash mseed_migration_restore.sh /path/to/mseed_full_migration_YYYYmmdd_HHMMSS.tar.gz

This script:
  - installs required Ubuntu packages,
  - installs Miniforge if missing,
  - rebuilds the Python 3.10 environments,
  - restores code, configs, app.db, waveform databases, systemd and nginx,
  - repairs ownership and starts services.

Run it on a clean Ubuntu server, preferably x86_64 like the source server.
EOF
}

if [[ -z "$ARCHIVE" || "$ARCHIVE" == "-h" || "$ARCHIVE" == "--help" ]]; then
  usage
  exit 0
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script with sudo/root." >&2
  exit 1
fi

if [[ ! -f "$ARCHIVE" ]]; then
  echo "Archive not found: $ARCHIVE" >&2
  exit 1
fi

cleanup() {
  rm -rf "$WORK"
}
trap cleanup EXIT

mkdir -p "$WORK"
tar -C "$WORK" -xzf "$ARCHIVE"

PAYLOAD="$WORK/payload"
MANIFEST="$WORK/manifest"

if [[ ! -d "$PAYLOAD/opt/mseed-web-portal" || ! -d "$PAYLOAD/opt/mseed-tcp-server" ]]; then
  echo "Invalid migration archive: application directories are missing." >&2
  exit 1
fi

echo "[1/12] Checking architecture..."
SOURCE_ARCH="$(awk -F= '$1=="source_arch"{print $2}' "$MANIFEST/migration-info.txt" 2>/dev/null || true)"
TARGET_ARCH="$(uname -m)"
echo "Source architecture: ${SOURCE_ARCH:-unknown}"
echo "Target architecture: $TARGET_ARCH"
if [[ -n "$SOURCE_ARCH" && "$SOURCE_ARCH" != "$TARGET_ARCH" ]]; then
  echo "WARNING: architecture differs. The code is portable, but dependency availability must be verified."
fi

echo "[2/12] Installing Ubuntu packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
  nginx \
  sqlite3 \
  rsync \
  curl \
  ca-certificates \
  tar \
  gzip \
  python3-venv \
  build-essential

echo "[3/12] Stopping existing services..."
for unit in \
  mseed-alert-worker.timer \
  mseed-device-sync.timer \
  mseed-backup.timer \
  mseed-web-portal.service \
  mseed-tcp-server.service
do
  systemctl stop "$unit" >/dev/null 2>&1 || true
done

echo "[4/12] Backing up any existing deployment..."
EXISTING=()
for p in \
  /opt/mseed-web-portal \
  /opt/mseed-tcp-server \
  /etc/mseed-web-portal \
  /etc/mseed-tcp-server \
  /var/lib/mseed-web-portal \
  /var/lib/mseed-tcp-server
do
  [[ -e "$p" ]] && EXISTING+=("$p")
done
if [[ ${#EXISTING[@]} -gt 0 ]]; then
  tar -czf "$BACKUP" "${EXISTING[@]}" 2>/dev/null || true
  chmod 600 "$BACKUP" || true
  echo "Existing deployment backup: $BACKUP"
fi

echo "[5/12] Creating service account and directories..."
if ! id mseed >/dev/null 2>&1; then
  useradd --system --home /var/lib/mseed-tcp-server --shell /usr/sbin/nologin mseed
fi
mkdir -p \
  /opt/mseed-web-portal \
  /opt/mseed-tcp-server \
  /etc/mseed-web-portal \
  /etc/mseed-tcp-server \
  /var/lib/mseed-web-portal \
  /var/lib/mseed-tcp-server/devices \
  /var/lib/mseed-tcp-server/quarantine \
  /var/log/mseed-web-portal \
  /var/log/mseed-tcp-server \
  /var/backups/mseed-web

echo "[6/12] Restoring code, configurations and data..."
rsync -a --delete "$PAYLOAD/opt/mseed-web-portal/" /opt/mseed-web-portal/
rsync -a --delete "$PAYLOAD/opt/mseed-tcp-server/" /opt/mseed-tcp-server/

if [[ -d "$PAYLOAD/etc/mseed-web-portal" ]]; then
  rsync -a --delete "$PAYLOAD/etc/mseed-web-portal/" /etc/mseed-web-portal/
fi
if [[ -d "$PAYLOAD/etc/mseed-tcp-server" ]]; then
  rsync -a --delete "$PAYLOAD/etc/mseed-tcp-server/" /etc/mseed-tcp-server/
fi
if [[ -d "$PAYLOAD/var/lib/mseed-web-portal" ]]; then
  rsync -a --delete "$PAYLOAD/var/lib/mseed-web-portal/" /var/lib/mseed-web-portal/
fi
if [[ -d "$PAYLOAD/var/lib/mseed-tcp-server" ]]; then
  rsync -a --delete "$PAYLOAD/var/lib/mseed-tcp-server/" /var/lib/mseed-tcp-server/
fi
if [[ -d "$PAYLOAD/var/backups/mseed-web" ]]; then
  rsync -a "$PAYLOAD/var/backups/mseed-web/" /var/backups/mseed-web/
fi

if [[ -d "$PAYLOAD/etc/systemd/system" ]]; then
  rsync -a "$PAYLOAD/etc/systemd/system/" /etc/systemd/system/
fi
if [[ -d "$PAYLOAD/etc/nginx/conf.d" ]]; then
  rsync -a "$PAYLOAD/etc/nginx/conf.d/" /etc/nginx/conf.d/
fi
if [[ -d "$PAYLOAD/etc/nginx/sites-enabled" ]]; then
  rsync -a "$PAYLOAD/etc/nginx/sites-enabled/" /etc/nginx/sites-enabled/
fi

echo "[7/12] Installing Miniforge..."
if [[ ! -x /opt/miniforge3/bin/conda ]]; then
  case "$TARGET_ARCH" in
    x86_64)
      MINI_ARCH="x86_64"
      ;;
    aarch64|arm64)
      MINI_ARCH="aarch64"
      ;;
    *)
      echo "Unsupported Miniforge architecture: $TARGET_ARCH" >&2
      exit 1
      ;;
  esac
  INSTALLER="/tmp/Miniforge3-Linux-${MINI_ARCH}.sh"
  curl -fL \
    "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-${MINI_ARCH}.sh" \
    -o "$INSTALLER"
  bash "$INSTALLER" -b -p /opt/miniforge3
  rm -f "$INSTALLER"
fi

echo "[8/12] Rebuilding Web Portal Python 3.10 environment..."
CONDA="/opt/miniforge3/bin/conda"
"$CONDA" env remove -n mseed-web -y >/dev/null 2>&1 || true
"$CONDA" create -n mseed-web -y python=3.10 pip
WEB_PY="/opt/miniforge3/envs/mseed-web/bin/python"
"$WEB_PY" -m pip install --upgrade pip setuptools wheel
if [[ -s "$MANIFEST/web-pip-freeze.txt" ]]; then
  "$WEB_PY" -m pip install -r "$MANIFEST/web-pip-freeze.txt"
else
  "$WEB_PY" -m pip install \
    fastapi uvicorn jinja2 python-multipart itsdangerous \
    "passlib[bcrypt]" "bcrypt==4.0.1" obspy numpy plotly sqlalchemy
fi

echo "[9/12] Rebuilding TCP receiver Python 3.10 virtual environment..."
rm -rf /opt/mseed-tcp-server/.venv
"$WEB_PY" -m venv /opt/mseed-tcp-server/.venv
TCP_PY="/opt/mseed-tcp-server/.venv/bin/python"
"$TCP_PY" -m pip install --upgrade pip setuptools wheel
if [[ -s "$MANIFEST/tcp-pip-freeze.txt" ]]; then
  "$TCP_PY" -m pip install -r "$MANIFEST/tcp-pip-freeze.txt"
elif [[ -f /opt/mseed-tcp-server/requirements.txt ]]; then
  "$TCP_PY" -m pip install -r /opt/mseed-tcp-server/requirements.txt
else
  "$TCP_PY" -m pip install obspy numpy
fi

echo "[10/12] Repairing permissions..."
chown -R root:root /opt/mseed-web-portal /opt/mseed-tcp-server
chown -R root:root /etc/mseed-web-portal
chown -R root:mseed /etc/mseed-tcp-server
chown -R root:root /var/lib/mseed-web-portal /var/log/mseed-web-portal /var/backups/mseed-web
chown -R mseed:mseed /var/lib/mseed-tcp-server /var/log/mseed-tcp-server

chmod 750 /etc/mseed-web-portal /etc/mseed-tcp-server || true
chmod 600 /etc/mseed-web-portal/portal.ini 2>/dev/null || true
chmod 600 /etc/mseed-web-portal/alerts.ini 2>/dev/null || true
chmod 640 /etc/mseed-tcp-server/server.ini 2>/dev/null || true

echo "[11/12] Validating configuration..."
"$WEB_PY" -m py_compile \
  /opt/mseed-web-portal/app/main.py \
  /opt/mseed-web-portal/app/app_db.py \
  /opt/mseed-web-portal/app/data_reader.py

systemctl daemon-reload
nginx -t

echo "[12/12] Enabling and starting services..."
systemctl enable --now mseed-tcp-server.service
systemctl enable --now mseed-web-portal.service
for unit in mseed-alert-worker.timer mseed-device-sync.timer mseed-backup.timer; do
  if systemctl cat "$unit" >/dev/null 2>&1; then
    systemctl enable --now "$unit"
  fi
done
systemctl enable --now nginx

if [[ -f /opt/mseed-web-portal/tools/sync_devices.py ]]; then
  PYTHONPATH=/opt/mseed-web-portal \
    "$WEB_PY" /opt/mseed-web-portal/tools/sync_devices.py || true
fi

echo
echo "Restore completed."
echo
echo "Service status:"
systemctl --no-pager --full status mseed-tcp-server.service mseed-web-portal.service nginx.service || true
echo
echo "Listening ports:"
ss -lntp | grep -E '(:80[[:space:]]|:443[[:space:]]|:8080[[:space:]]|:18000[[:space:]])' || true
echo
echo "Local HTTP checks:"
curl -sS -o /dev/null -w "Portal 8080: HTTP %{http_code}\n" http://127.0.0.1:8080/ || true
curl -sS -o /dev/null -w "Nginx 80:   HTTP %{http_code}\n" http://127.0.0.1/ || true
echo
echo "Next steps:"
echo "1. Open firewall/security-group ports 80, 443 and 18000/TCP as required."
echo "2. Point the instruments or DNS name to this new server's public IP."
echo "3. Test admin login, device visibility, alerts, export and historical waveform."
echo "4. After verification, stop the old receiver to avoid two servers accepting the same instruments."
