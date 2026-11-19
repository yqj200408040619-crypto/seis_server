#!/usr/bin/env bash
set -Eeuo pipefail

ARCHIVE="${1:-}"
WORK="/tmp/mseed_runtime_restore_$$"
BACKUP="/root/mseed_runtime_before_restore_$(date +%Y%m%d_%H%M%S).tar.gz"

if [[ -z "$ARCHIVE" ]]; then
  echo "Usage: sudo bash mseed_complete_runtime_restore.sh /path/to/mseed_complete_runtime_*.tar.gz" >&2
  exit 2
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo/root." >&2
  exit 1
fi

[[ -f "$ARCHIVE" ]] || { echo "Archive not found: $ARCHIVE" >&2; exit 1; }

mkdir -p "$WORK"
trap 'rm -rf "$WORK"' EXIT

echo "[1/8] Extracting runtime package..."
tar -C "$WORK" -xzf "$ARCHIVE"

RUNTIME="$WORK/runtime"
MANIFEST="$WORK/manifest"

[[ -d "$RUNTIME/opt/miniforge3" ]] || { echo "Invalid package: Miniforge runtime missing." >&2; exit 1; }
[[ -d "$RUNTIME/opt/mseed-tcp-server/.venv" ]] || { echo "Invalid package: TCP venv missing." >&2; exit 1; }

echo "[2/8] Checking architecture..."
SOURCE_ARCH="$(awk -F= '$1=="source_arch"{print $2}' "$MANIFEST/runtime-info.txt" 2>/dev/null || true)"
TARGET_ARCH="$(uname -m)"
echo "Source: ${SOURCE_ARCH:-unknown}"
echo "Target: $TARGET_ARCH"
if [[ -n "$SOURCE_ARCH" && "$SOURCE_ARCH" != "$TARGET_ARCH" ]]; then
  echo "ERROR: CPU architecture mismatch." >&2
  exit 1
fi

echo "[3/8] Stopping services..."
systemctl stop mseed-web-portal.service 2>/dev/null || true
systemctl stop mseed-tcp-server.service 2>/dev/null || true

echo "[4/8] Backing up existing runtimes..."
EXISTING=()
[[ -d /opt/miniforge3 ]] && EXISTING+=(/opt/miniforge3)
[[ -d /opt/mseed-tcp-server/.venv ]] && EXISTING+=(/opt/mseed-tcp-server/.venv)
if [[ ${#EXISTING[@]} -gt 0 ]]; then
  tar -czf "$BACKUP" "${EXISTING[@]}" 2>/dev/null || true
  chmod 600 "$BACKUP" || true
  echo "Backup: $BACKUP"
fi

echo "[5/8] Restoring runtimes to original absolute paths..."
rm -rf /opt/miniforge3
mkdir -p /opt/miniforge3
rsync -a "$RUNTIME/opt/miniforge3/" /opt/miniforge3/

rm -rf /opt/mseed-tcp-server/.venv
mkdir -p /opt/mseed-tcp-server
rsync -a "$RUNTIME/opt/mseed-tcp-server/.venv/" /opt/mseed-tcp-server/.venv/

echo "[6/8] Repairing permissions..."
chown -R root:root /opt/miniforge3
chown -R root:root /opt/mseed-tcp-server/.venv

echo "[7/8] Validating Python runtimes..."
/opt/miniforge3/envs/mseed-web/bin/python - <<'PY'
import sys
import fastapi, uvicorn, jinja2, numpy, obspy, plotly
print("Web runtime OK:", sys.version)
PY

/opt/mseed-tcp-server/.venv/bin/python - <<'PY'
import sys
import numpy, obspy
print("TCP runtime OK:", sys.version)
PY

echo "[8/8] Restarting services..."
systemctl daemon-reload
systemctl restart mseed-web-portal.service 2>/dev/null || true
systemctl restart mseed-tcp-server.service 2>/dev/null || true

echo
echo "Complete offline runtime restored successfully."
echo "Web Python: /opt/miniforge3/envs/mseed-web/bin/python"
echo "TCP Python: /opt/mseed-tcp-server/.venv/bin/python"
