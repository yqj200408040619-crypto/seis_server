#!/usr/bin/env bash
set -Eeuo pipefail
shopt -s nullglob

OUTPUT_DIR="/home/ftp"
INCLUDE_WAVEFORM_DATA=1
TS="$(date +%Y%m%d_%H%M%S)"
STAGE=""
ARCHIVE=""
ACTIVE_UNITS=()

usage() {
  cat <<'EOF'
Usage:
  sudo bash mseed_migration_export.sh [--output DIR] [--no-waveform-data]

Options:
  --output DIR         Archive output directory. Default: /home/ftp
  --no-waveform-data  Exclude /var/lib/mseed-tcp-server/devices.
                      User accounts and app.db are still included.
  -h, --help          Show this help.

The archive contains real configuration secrets and user databases.
Transfer it directly to the new server. Do not upload it publicly.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output)
      OUTPUT_DIR="${2:?missing output directory}"
      shift 2
      ;;
    --no-waveform-data)
      INCLUDE_WAVEFORM_DATA=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script with sudo/root." >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"
STAGE="/tmp/mseed_full_migration_${TS}"
ARCHIVE="${OUTPUT_DIR%/}/mseed_full_migration_${TS}.tar.gz"
mkdir -p "$STAGE"/{payload,opt,etc,var,systemd,nginx,manifest}

restart_original_units() {
  local rc=$?
  for unit in "${ACTIVE_UNITS[@]}"; do
    systemctl start "$unit" >/dev/null 2>&1 || true
  done
  if [[ -n "$STAGE" && -d "$STAGE" ]]; then
    rm -rf "$STAGE"
  fi
  exit "$rc"
}
trap restart_original_units EXIT INT TERM

record_and_stop() {
  local unit="$1"
  if systemctl is-active --quiet "$unit"; then
    ACTIVE_UNITS+=("$unit")
    systemctl stop "$unit"
  fi
}

echo "[1/9] Stopping writers for a consistent SQLite snapshot..."
for unit in \
  mseed-alert-worker.timer \
  mseed-device-sync.timer \
  mseed-backup.timer \
  mseed-web-portal.service \
  mseed-tcp-server.service
do
  record_and_stop "$unit"
done

echo "[2/9] Checkpointing SQLite WAL files..."
if command -v sqlite3 >/dev/null 2>&1; then
  for db in /var/lib/mseed-web-portal/app.db /var/lib/mseed-tcp-server/devices/*.db; do
    [[ -f "$db" ]] || continue
    sqlite3 "$db" "PRAGMA wal_checkpoint(FULL);" >/dev/null 2>&1 || true
  done
fi

echo "[3/9] Copying application code..."
mkdir -p "$STAGE/payload/opt"
if [[ -d /opt/mseed-web-portal ]]; then
  rsync -a \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='*.bak_*' \
    --exclude='.git/' \
    --exclude='*.tar.gz' \
    --exclude='*.zip' \
    /opt/mseed-web-portal/ "$STAGE/payload/opt/mseed-web-portal/"
fi

if [[ -d /opt/mseed-tcp-server ]]; then
  rsync -a \
    --exclude='.venv/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='*.bak_*' \
    --exclude='.git/' \
    /opt/mseed-tcp-server/ "$STAGE/payload/opt/mseed-tcp-server/"
fi

echo "[4/9] Copying configuration files, including secrets..."
mkdir -p "$STAGE/payload/etc"
for d in /etc/mseed-web-portal /etc/mseed-tcp-server; do
  [[ -d "$d" ]] || continue
  rsync -a "$d/" "$STAGE/payload$d/"
done

echo "[5/9] Copying application database and waveform databases..."
mkdir -p "$STAGE/payload/var/lib/mseed-web-portal"
if [[ -d /var/lib/mseed-web-portal ]]; then
  rsync -a /var/lib/mseed-web-portal/ "$STAGE/payload/var/lib/mseed-web-portal/"
fi

mkdir -p "$STAGE/payload/var/lib/mseed-tcp-server"
if [[ -d /var/lib/mseed-tcp-server ]]; then
  if [[ "$INCLUDE_WAVEFORM_DATA" -eq 1 ]]; then
    rsync -a /var/lib/mseed-tcp-server/ "$STAGE/payload/var/lib/mseed-tcp-server/"
  else
    rsync -a \
      --exclude='devices/' \
      --exclude='quarantine/' \
      /var/lib/mseed-tcp-server/ "$STAGE/payload/var/lib/mseed-tcp-server/"
  fi
fi

if [[ -d /var/backups/mseed-web ]]; then
  mkdir -p "$STAGE/payload/var/backups"
  rsync -a /var/backups/mseed-web/ "$STAGE/payload/var/backups/mseed-web/"
fi

echo "[6/9] Copying systemd and nginx configuration..."
mkdir -p "$STAGE/payload/etc/systemd/system" "$STAGE/payload/etc/nginx/conf.d" "$STAGE/payload/etc/nginx/sites-enabled"
for f in /etc/systemd/system/mseed*.service /etc/systemd/system/mseed*.timer; do
  [[ -f "$f" ]] && cp -a "$f" "$STAGE/payload/etc/systemd/system/"
done
for f in /etc/nginx/conf.d/*mseed*.conf /etc/nginx/sites-enabled/*mseed*; do
  [[ -f "$f" ]] || continue
  case "$f" in
    /etc/nginx/conf.d/*)
      cp -a "$f" "$STAGE/payload/etc/nginx/conf.d/"
      ;;
    /etc/nginx/sites-enabled/*)
      cp -aL "$f" "$STAGE/payload/etc/nginx/sites-enabled/"
      ;;
  esac
done

echo "[7/9] Exporting reproducible Python dependency manifests..."
WEB_PY="/opt/miniforge3/envs/mseed-web/bin/python"
WEB_CONDA="/opt/miniforge3/bin/conda"
TCP_PIP="/opt/mseed-tcp-server/.venv/bin/pip"

if [[ -x "$WEB_PY" ]]; then
  "$WEB_PY" -m pip freeze \
    | sed '/ @ file:/d' \
    > "$STAGE/manifest/web-pip-freeze.txt"
  "$WEB_PY" --version > "$STAGE/manifest/web-python-version.txt" 2>&1
fi
if [[ -x "$WEB_CONDA" ]]; then
  "$WEB_CONDA" list -n mseed-web --explicit > "$STAGE/manifest/web-conda-explicit.txt" 2>&1 || true
fi
if [[ -x "$TCP_PIP" ]]; then
  "$TCP_PIP" freeze \
    | sed '/ @ file:/d' \
    > "$STAGE/manifest/tcp-pip-freeze.txt"
fi

echo "[8/9] Writing migration manifest..."
{
  echo "created_at=$(date -Is)"
  echo "source_hostname=$(hostname)"
  echo "source_kernel=$(uname -a)"
  echo "source_arch=$(uname -m)"
  echo "include_waveform_data=${INCLUDE_WAVEFORM_DATA}"
  echo "archive_contains_secrets=yes"
  echo "active_units_before_export=${ACTIVE_UNITS[*]}"
} > "$STAGE/manifest/migration-info.txt"

find "$STAGE/payload" -type f -printf '%P\t%s\n' | sort > "$STAGE/manifest/file-list.tsv"
du -sh /var/lib/mseed-tcp-server/devices 2>/dev/null > "$STAGE/manifest/source-waveform-size.txt" || true
df -h > "$STAGE/manifest/source-disk.txt"

echo "[9/9] Creating archive..."
tar -C "$STAGE" -czf "$ARCHIVE" payload manifest
chmod 600 "$ARCHIVE"

echo
echo "Migration archive created:"
echo "$ARCHIVE"
du -h "$ARCHIVE"
echo
echo "IMPORTANT: This archive contains real secrets, user accounts, and possibly waveform data."
echo "Transfer it directly to the new server. Do not upload it to a public chat or file-sharing site."
