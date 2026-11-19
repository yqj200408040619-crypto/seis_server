#!/usr/bin/env bash
set -euo pipefail

TS="$(date +%Y%m%d_%H%M%S)"
OUTDIR="/tmp/mseed_portal_debug_${TS}"
ARCHIVE="/tmp/mseed_portal_debug_${TS}.tar.gz"

mkdir -p "$OUTDIR"

echo "[1/8] Copy current program..."
if [ -d /opt/mseed-web-portal ]; then
  mkdir -p "$OUTDIR/opt"
  rsync -a \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='.git/' \
    --exclude='*.bak_*' \
    --exclude='*.tar.gz' \
    --exclude='*.zip' \
    /opt/mseed-web-portal/ "$OUTDIR/opt/mseed-web-portal/"
else
  echo "WARN: /opt/mseed-web-portal not found" | tee -a "$OUTDIR/WARNINGS.txt"
fi

echo "[2/8] Copy sanitized /etc config..."
mkdir -p "$OUTDIR/etc/mseed-web-portal"
if [ -d /etc/mseed-web-portal ]; then
  rsync -a /etc/mseed-web-portal/ "$OUTDIR/etc/mseed-web-portal/"
  # Mask likely secrets in config files.
  find "$OUTDIR/etc/mseed-web-portal" -type f \( -name "*.ini" -o -name "*.toml" -o -name "*.conf" -o -name "*.env" \) -print0 | while IFS= read -r -d '' f; do
    sed -i -E \
      -e 's/^([[:space:]]*(secret|secret_key|token|auth_token|password|smtp_password|webServer\.password|auth\.token)[[:space:]]*[:=][[:space:]]*).*/\1***MASKED***/Ig' \
      -e 's/(password[[:space:]]*[:=][[:space:]]*)[^[:space:]]+/\1***MASKED***/Ig' \
      -e 's/(token[[:space:]]*[:=][[:space:]]*)[^[:space:]]+/\1***MASKED***/Ig' \
      "$f" || true
  done
fi

echo "[3/8] Copy systemd and nginx configs..."
mkdir -p "$OUTDIR/systemd" "$OUTDIR/nginx"
for f in /etc/systemd/system/mseed*.service /etc/systemd/system/mseed*.timer /etc/systemd/system/frp*.service; do
  [ -f "$f" ] && cp -a "$f" "$OUTDIR/systemd/" || true
done
for f in /etc/nginx/conf.d/*.conf /etc/nginx/sites-enabled/*; do
  [ -f "$f" ] && cp -a "$f" "$OUTDIR/nginx/" || true
done

echo "[4/8] Export sanitized app database summary..."
mkdir -p "$OUTDIR/db_summary"
APP_DB=""
for c in /var/lib/mseed-web-portal/app.db /opt/mseed-web-portal/app.db; do
  [ -f "$c" ] && APP_DB="$c" && break
done

if [ -n "$APP_DB" ]; then
  echo "$APP_DB" > "$OUTDIR/db_summary/app_db_path.txt"
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$APP_DB" ".schema" > "$OUTDIR/db_summary/app_db_schema.sql" || true
    sqlite3 -header -csv "$APP_DB" "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;" > "$OUTDIR/db_summary/app_db_tables.csv" || true

    # Export safe rows if tables exist. Do not export password hashes.
    sqlite3 -header -csv "$APP_DB" "SELECT id, username, display_name, role, customer_id, is_active, email FROM users ORDER BY id;" > "$OUTDIR/db_summary/users_safe.csv" 2>/dev/null || true
    sqlite3 -header -csv "$APP_DB" "SELECT * FROM customers ORDER BY id;" > "$OUTDIR/db_summary/customers.csv" 2>/dev/null || true
    sqlite3 -header -csv "$APP_DB" "SELECT id, label, alias, device_key, instrument_type, instrument_serial, client_ip, server_port, db_path, customer_id, site_name, location_note, lat, lon, installation_date FROM devices ORDER BY id;" > "$OUTDIR/db_summary/devices_safe.csv" 2>/dev/null || true
    sqlite3 -header -csv "$APP_DB" "SELECT * FROM user_devices ORDER BY user_id, device_id;" > "$OUTDIR/db_summary/user_devices.csv" 2>/dev/null || true
    sqlite3 -header -csv "$APP_DB" "SELECT * FROM customer_device_rules ORDER BY id;" > "$OUTDIR/db_summary/customer_device_rules.csv" 2>/dev/null || true
  else
    echo "sqlite3 not installed; skipped app.db export" > "$OUTDIR/db_summary/sqlite3_missing.txt"
  fi
else
  echo "app.db not found" > "$OUTDIR/db_summary/app_db_missing.txt"
fi

echo "[5/8] Export receiver DB metadata only, no raw_mseed..."
mkdir -p "$OUTDIR/receiver_db_summary"
python3 - <<'PY' "$OUTDIR/receiver_db_summary"
import csv, sqlite3, sys
from pathlib import Path

out = Path(sys.argv[1])
receiver_dirs = [Path("/var/lib/mseed-tcp-server/devices"), Path("/var/lib/mseed-web-portal/devices")]
dbs = []
for d in receiver_dirs:
    if d.exists():
        dbs.extend(sorted(d.glob("*.db")))

with (out / "receiver_dbs.csv").open("w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["db_path", "size_bytes"])
    for db in dbs:
        w.writerow([str(db), db.stat().st_size])

for db in dbs[:30]:
    safe_name = db.name.replace("/", "_")
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        schema = "\n".join(r[0] for r in con.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name").fetchall())
        (out / f"{safe_name}.schema.sql").write_text(schema)
        cols = {r[1] for r in con.execute("PRAGMA table_info(packets)").fetchall()} if con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='packets'").fetchone() else set()
        if cols:
            select_cols = []
            for c in ["device_key","stream_key","network","station","location","channel","component_key","component_axis","start_unix","end_unix","seq_no","packet_len","sampling_rate","npts","recv_unix"]:
                if c in cols: select_cols.append(c)
            if select_cols:
                rows = con.execute(f"SELECT {', '.join(select_cols)} FROM packets ORDER BY start_unix DESC LIMIT 20").fetchall()
                with (out / f"{safe_name}.packets_sample.csv").open("w", newline="") as f2:
                    w2 = csv.writer(f2)
                    w2.writerow(select_cols)
                    for r in rows:
                        w2.writerow([r[c] for c in select_cols])
        con.close()
    except Exception as e:
        (out / f"{safe_name}.error.txt").write_text(str(e))
PY

echo "[6/8] Collect logs and runtime status..."
mkdir -p "$OUTDIR/logs" "$OUTDIR/status"
for unit in mseed-web-portal mseed-tcp-server mseed-alert-worker mseed-device-sync mseed-backup nginx; do
  systemctl status "$unit" --no-pager > "$OUTDIR/status/${unit}.status.txt" 2>&1 || true
  journalctl -u "$unit" -n 500 --no-pager > "$OUTDIR/logs/${unit}.journal.txt" 2>&1 || true
done

systemctl list-timers 'mseed-*' --no-pager > "$OUTDIR/status/mseed_timers.txt" 2>&1 || true
ss -lntp > "$OUTDIR/status/ss_lntp.txt" 2>&1 || true
df -h > "$OUTDIR/status/df_h.txt" 2>&1 || true
free -h > "$OUTDIR/status/free_h.txt" 2>&1 || true
ps aux | grep -E 'mseed|uvicorn|nginx|frp' | grep -v grep > "$OUTDIR/status/processes.txt" 2>&1 || true

echo "[7/8] Collect versions and file tree..."
{
  echo "date: $(date -Is)"
  echo "hostname: $(hostname)"
  echo "uname: $(uname -a)"
  echo
  echo "python:"
  /opt/miniforge3/envs/mseed-web/bin/python --version 2>&1 || true
  python3 --version 2>&1 || true
  echo
  echo "pip freeze:"
  /opt/miniforge3/envs/mseed-web/bin/python -m pip freeze 2>&1 || true
  echo
  echo "nginx:"
  nginx -v 2>&1 || true
} > "$OUTDIR/status/versions.txt"

if [ -d /opt/mseed-web-portal ]; then
  find /opt/mseed-web-portal -maxdepth 5 -type f \
    ! -path '*/__pycache__/*' \
    ! -name '*.pyc' \
    ! -name '*.bak_*' \
    -printf '%p\n' | sort > "$OUTDIR/status/program_file_tree.txt"
fi

echo "[8/8] Create archive..."
tar -C /tmp -czf "$ARCHIVE" "$(basename "$OUTDIR")"

echo
echo "Done."
echo "Archive:"
echo "$ARCHIVE"
echo
echo "Size:"
du -h "$ARCHIVE"
echo
echo "Before sending it out, you can inspect contents with:"
echo "tar -tzf $ARCHIVE | less"
echo
echo "This package excludes raw miniSEED BLOB data and masks config secrets, but you should still review it before sharing."
