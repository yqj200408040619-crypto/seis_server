#!/usr/bin/env bash
set -Eeuo pipefail

OUT_DIR="${1:-/home/ftp}"
TS="$(date +%Y%m%d_%H%M%S)"
ARCHIVE="${OUT_DIR%/}/mseed_complete_runtime_${TS}.tar.gz"
STAGE="/tmp/mseed_complete_runtime_${TS}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo/root." >&2
  exit 1
fi

for p in \
  /opt/miniforge3 \
  /opt/mseed-tcp-server/.venv
do
  [[ -e "$p" ]] || { echo "Missing required runtime path: $p" >&2; exit 1; }
done

mkdir -p "$OUT_DIR" "$STAGE/runtime/opt/mseed-tcp-server" "$STAGE/manifest"

cleanup() {
  rm -rf "$STAGE"
}
trap cleanup EXIT

echo "[1/5] Recording versions..."
{
  echo "created_at=$(date -Is)"
  echo "source_hostname=$(hostname)"
  echo "source_arch=$(uname -m)"
  echo "source_kernel=$(uname -a)"
  echo
  echo "web_python=$(/opt/miniforge3/envs/mseed-web/bin/python --version 2>&1 || true)"
  echo "tcp_python=$(/opt/mseed-tcp-server/.venv/bin/python --version 2>&1 || true)"
  echo "conda=$(/opt/miniforge3/bin/conda --version 2>&1 || true)"
} > "$STAGE/manifest/runtime-info.txt"

echo "[2/5] Copying complete Miniforge runtime..."
rsync -a \
  --exclude='pkgs/cache/' \
  --exclude='conda-meta/history.bak*' \
  /opt/miniforge3/ "$STAGE/runtime/opt/miniforge3/"

echo "[3/5] Copying TCP receiver virtual environment..."
rsync -a \
  /opt/mseed-tcp-server/.venv/ \
  "$STAGE/runtime/opt/mseed-tcp-server/.venv/"

echo "[4/5] Writing checksums..."
find "$STAGE/runtime" -type f -print0 \
  | sort -z \
  | xargs -0 sha256sum \
  > "$STAGE/manifest/SHA256SUMS"

echo "[5/5] Creating archive..."
tar -C "$STAGE" -czf "$ARCHIVE" runtime manifest
chmod 600 "$ARCHIVE"

echo
echo "Complete offline runtime archive created:"
echo "$ARCHIVE"
du -h "$ARCHIVE"
echo
echo "This archive contains the complete working Python runtimes."
echo "It is intended for the same CPU architecture and similar Ubuntu/glibc."
