#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/mseed-web-portal"
CONFIG_DIR="/etc/mseed-web-portal"
APP_DB="/var/lib/mseed-web-portal/app.db"
LOG_DIR="/var/log/mseed-web-portal"
BACKUP_DIR="/var/backups/mseed-web"
PY=""
TS="$(date +%Y%m%d_%H%M%S)"

if [ -x "/opt/miniforge3/envs/mseed-web/bin/python" ]; then
  PY="/opt/miniforge3/envs/mseed-web/bin/python"
elif [ -x "$APP_DIR/.venv/bin/python" ]; then
  PY="$APP_DIR/.venv/bin/python"
else
  echo "ERROR: Python environment not found. Expected /opt/miniforge3/envs/mseed-web/bin/python or $APP_DIR/.venv/bin/python" >&2
  exit 1
fi

if [ ! -d "$APP_DIR/app" ]; then
  echo "ERROR: $APP_DIR/app not found. Is the Web Portal installed?" >&2
  exit 1
fi

mkdir -p "$CONFIG_DIR" "$LOG_DIR" "$BACKUP_DIR" "$APP_DIR/tools" "$APP_DIR/app/templates" "$APP_DIR/app/static/js"

echo "== Stage 2 patch: alerts + backup foundation + resource controls =="
echo "Python: $PY"

# Backups of source files.
cp -a "$APP_DIR/app/main.py" "$APP_DIR/app/main.py.bak_stage2_$TS" || true
cp -a "$APP_DIR/app/templates/base.html" "$APP_DIR/app/templates/base.html.bak_stage2_$TS" || true

# -----------------------------------------------------------------------------
# Alerts config
# -----------------------------------------------------------------------------
if [ ! -f "$CONFIG_DIR/alerts.ini" ]; then
cat > "$CONFIG_DIR/alerts.ini" <<'INICONF'
[thresholds]
# A device is offline if no packet has been received for this many seconds.
offline_seconds = 600

# A component is missing if BHZ/BHN/BHE has no recent data for this many seconds.
channel_missing_seconds = 600

# Receiver-side gap rows are promoted to alerts when gap duration is >= this value.
gap_min_seconds = 1.0

# Avoid sending the same open alert by email more frequently than this.
repeat_silence_seconds = 3600

# Components expected for normal three-component seismic instruments.
expected_components = BHZ,BHN,BHE

[smtp]
# Keep disabled until the real SMTP account is configured.
enabled = false
host = smtp.example.com
port = 587
username =
password =
from_addr = seismic-portal@example.com
# Comma-separated recipients used when a customer/device does not have a dedicated email yet.
to_addrs = admin@example.com
use_tls = true

[email]
subject_prefix = [Seismic Portal]
INICONF
  chmod 600 "$CONFIG_DIR/alerts.ini"
fi

if [ ! -f "$CONFIG_DIR/backup.ini" ]; then
cat > "$CONFIG_DIR/backup.ini" <<'INICONF'
[backup]
backup_dir = /var/backups/mseed-web
retention_days = 14
compress_level = 6

# Default: database-level backup only. This is resource-efficient and WAL-safe.
# Enable miniSEED archive later only if long-term daily file archives are required.
archive_mseed_enabled = false
archive_dir = /var/lib/mseed-archive
INICONF
  chmod 644 "$CONFIG_DIR/backup.ini"
fi

# -----------------------------------------------------------------------------
# app/stage2.py
# -----------------------------------------------------------------------------
cat > "$APP_DIR/app/stage2.py" <<'PYCODE'
from __future__ import annotations

import configparser
import gzip
import hashlib
import json
import os
import shutil
import smtplib
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Iterable

from .data_reader import connect_receiver_db, safe_receiver_db_path, table_exists, columns

DEFAULT_ALERT_CONFIG = "/etc/mseed-web-portal/alerts.ini"
DEFAULT_BACKUP_CONFIG = "/etc/mseed-web-portal/backup.ini"

SCHEMA_STAGE2 = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER,
    device_key TEXT,
    component TEXT,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    fingerprint TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'open',
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    last_sent_at REAL,
    resolved_at REAL,
    acked_at REAL,
    acked_by TEXT,
    count INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);
CREATE INDEX IF NOT EXISTS idx_alerts_device ON alerts(device_id);
CREATE INDEX IF NOT EXISTS idx_alerts_last_seen ON alerts(last_seen);
CREATE INDEX IF NOT EXISTS idx_alerts_fingerprint ON alerts(fingerprint);

CREATE TABLE IF NOT EXISTS backup_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at REAL NOT NULL,
    finished_at REAL,
    status TEXT NOT NULL,
    message TEXT,
    backup_dir TEXT,
    files_count INTEGER NOT NULL DEFAULT 0,
    total_bytes INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_backup_runs_started ON backup_runs(started_at);
"""


def app_connect(app_db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(app_db_path), exist_ok=True)
    conn = sqlite3.connect(app_db_path, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_stage2(app_db_path: str) -> None:
    with app_connect(app_db_path) as conn:
        conn.executescript(SCHEMA_STAGE2)
        conn.commit()


def read_alert_config(path: str = DEFAULT_ALERT_CONFIG) -> configparser.ConfigParser:
    p = configparser.ConfigParser()
    p.read(path)
    return p


def expected_components(config: configparser.ConfigParser | None = None) -> list[str]:
    config = config or read_alert_config()
    raw = config.get("thresholds", "expected_components", fallback="BHZ,BHN,BHE")
    return [x.strip().upper() for x in raw.split(",") if x.strip()]


def _device_display(d: sqlite3.Row | dict[str, Any]) -> str:
    if isinstance(d, sqlite3.Row):
        try:
            alias = d["alias"]
        except Exception:
            alias = None
        try:
            label = d["label"]
        except Exception:
            label = None
        try:
            key = d["device_key"]
        except Exception:
            key = None
    else:
        alias = d.get("alias")
        label = d.get("label")
        key = d.get("device_key")
    return str(alias or label or key or "device")


def receiver_basic_summary(receiver_db_dir: str, device: sqlite3.Row) -> dict[str, Any]:
    db_path = safe_receiver_db_path(receiver_db_dir, device["db_path"])
    device_key = device["device_key"]
    now = time.time()
    result: dict[str, Any] = {
        "total_packets": 0,
        "last_start": None,
        "last_recv": None,
        "age_seconds": None,
        "components": [],
        "component_status": [],
        "gap_recent": [],
        "gap_count": 0,
        "duplicate_count": 0,
        "bad_packet_count": 0,
    }
    with connect_receiver_db(db_path, readonly=True) as conn:
        if not table_exists(conn, "packets"):
            return result
        cols = columns(conn, "packets")
        args: list[Any] = []
        where = "1=1"
        if "device_key" in cols:
            where += " AND device_key = ?"
            args.append(device_key)
        elif "network" in cols and "station" in cols and "_" in device_key:
            a, b = device_key.split("_", 1)
            where += " AND network = ? AND station = ?"
            args.extend([a, b])
        recv_expr = "MAX(recv_unix)" if "recv_unix" in cols else "NULL"
        row = conn.execute(f"SELECT COUNT(*) n, MAX(start_unix) last_start, {recv_expr} last_recv FROM packets WHERE {where}", args).fetchone()
        if row:
            result["total_packets"] = int(row["n"] or 0)
            result["last_start"] = float(row["last_start"]) if row["last_start"] is not None else None
            result["last_recv"] = float(row["last_recv"]) if row["last_recv"] is not None else None
        ref = result["last_recv"] if result["last_recv"] is not None else result["last_start"]
        result["age_seconds"] = now - ref if ref is not None else None

        comp_col = "component_key" if "component_key" in cols else ("channel" if "channel" in cols else None)
        if comp_col:
            recv_expr2 = "MAX(recv_unix)" if "recv_unix" in cols else "NULL"
            rows = conn.execute(
                f"SELECT {comp_col} component, COUNT(*) packets, MAX(start_unix) last_start, {recv_expr2} last_recv "
                f"FROM packets WHERE {where} GROUP BY {comp_col}",
                args,
            ).fetchall()
            for r in rows:
                ref2 = float(r["last_recv"]) if r["last_recv"] is not None else (float(r["last_start"]) if r["last_start"] is not None else None)
                age = now - ref2 if ref2 is not None else None
                result["component_status"].append({
                    "component": str(r["component"]),
                    "packets": int(r["packets"] or 0),
                    "last_start": float(r["last_start"]) if r["last_start"] is not None else None,
                    "last_recv": float(r["last_recv"]) if r["last_recv"] is not None else None,
                    "age_seconds": age,
                })
        if table_exists(conn, "gaps"):
            try:
                result["gap_count"] = int(conn.execute("SELECT COUNT(*) n FROM gaps").fetchone()["n"] or 0)
                result["gap_recent"] = [dict(r) for r in conn.execute("SELECT rowid AS rowid, * FROM gaps ORDER BY rowid DESC LIMIT 20").fetchall()]
            except Exception:
                pass
        if table_exists(conn, "duplicates"):
            try:
                result["duplicate_count"] = int(conn.execute("SELECT COUNT(*) n FROM duplicates").fetchone()["n"] or 0)
            except Exception:
                pass
        if table_exists(conn, "bad_packets"):
            try:
                result["bad_packet_count"] = int(conn.execute("SELECT COUNT(*) n FROM bad_packets").fetchone()["n"] or 0)
            except Exception:
                pass
    return result


def fingerprint(*parts: Any) -> str:
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()


def upsert_alert(
    app_db_path: str,
    *,
    device_id: int | None,
    device_key: str | None,
    component: str | None,
    alert_type: str,
    severity: str,
    title: str,
    message: str,
    fp: str,
) -> tuple[int, bool]:
    now = time.time()
    init_stage2(app_db_path)
    with app_connect(app_db_path) as conn:
        row = conn.execute("SELECT id, status FROM alerts WHERE fingerprint = ?", (fp,)).fetchone()
        if row:
            conn.execute(
                """
                UPDATE alerts
                SET last_seen = ?, count = count + 1,
                    status = 'open', resolved_at = NULL,
                    severity = ?, title = ?, message = ?
                WHERE fingerprint = ?
                """,
                (now, severity, title, message, fp),
            )
            conn.commit()
            return int(row["id"]), False
        cur = conn.execute(
            """
            INSERT INTO alerts
            (device_id, device_key, component, alert_type, severity, title, message, fingerprint, status, first_seen, last_seen, count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, 1)
            """,
            (device_id, device_key, component, alert_type, severity, title, message, fp, now, now),
        )
        conn.commit()
        return int(cur.lastrowid), True


def resolve_alert(app_db_path: str, fp: str) -> None:
    now = time.time()
    init_stage2(app_db_path)
    with app_connect(app_db_path) as conn:
        conn.execute("UPDATE alerts SET status = 'resolved', resolved_at = ? WHERE fingerprint = ? AND status = 'open'", (now, fp))
        conn.commit()


def mark_sent(app_db_path: str, alert_id: int) -> None:
    with app_connect(app_db_path) as conn:
        conn.execute("UPDATE alerts SET last_sent_at = ? WHERE id = ?", (time.time(), alert_id))
        conn.commit()


def get_alert_by_id(app_db_path: str, alert_id: int) -> sqlite3.Row | None:
    init_stage2(app_db_path)
    with app_connect(app_db_path) as conn:
        return conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()


def ack_alert(app_db_path: str, alert_id: int, username: str) -> None:
    init_stage2(app_db_path)
    with app_connect(app_db_path) as conn:
        conn.execute("UPDATE alerts SET acked_at = ?, acked_by = ? WHERE id = ?", (time.time(), username, alert_id))
        conn.commit()


def list_alerts(app_db_path: str, *, device_ids: Iterable[int] | None = None, limit: int = 300) -> list[dict[str, Any]]:
    init_stage2(app_db_path)
    with app_connect(app_db_path) as conn:
        params: list[Any] = []
        where = "1=1"
        if device_ids is not None:
            ids = list(device_ids)
            if not ids:
                return []
            where += " AND device_id IN (%s)" % ",".join("?" for _ in ids)
            params.extend(ids)
        rows = conn.execute(
            f"SELECT * FROM alerts WHERE {where} ORDER BY CASE status WHEN 'open' THEN 0 ELSE 1 END, last_seen DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        return [dict(r) for r in rows]


def should_send_email(app_db_path: str, alert_id: int, repeat_silence_seconds: int) -> bool:
    with app_connect(app_db_path) as conn:
        row = conn.execute("SELECT last_sent_at FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        if not row or row["last_sent_at"] is None:
            return True
        return time.time() - float(row["last_sent_at"]) >= repeat_silence_seconds


def send_alert_email(config: configparser.ConfigParser, *, title: str, message: str) -> bool:
    if not config.getboolean("smtp", "enabled", fallback=False):
        return False
    host = config.get("smtp", "host", fallback="")
    port = config.getint("smtp", "port", fallback=587)
    username = config.get("smtp", "username", fallback="")
    password = config.get("smtp", "password", fallback="")
    from_addr = config.get("smtp", "from_addr", fallback=username)
    to_addrs = [x.strip() for x in config.get("smtp", "to_addrs", fallback="").split(",") if x.strip()]
    use_tls = config.getboolean("smtp", "use_tls", fallback=True)
    prefix = config.get("email", "subject_prefix", fallback="[Seismic Portal]")
    if not host or not from_addr or not to_addrs:
        return False
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)
    msg["Subject"] = f"{prefix} {title}"
    msg.set_content(message)
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        if use_tls:
            smtp.starttls()
        if username:
            smtp.login(username, password)
        smtp.send_message(msg)
    return True


def check_devices_once(app_db_path: str, receiver_db_dir: str, devices: list[sqlite3.Row], *, send_email: bool = True) -> dict[str, Any]:
    init_stage2(app_db_path)
    cfg = read_alert_config()
    offline_seconds = cfg.getint("thresholds", "offline_seconds", fallback=600)
    channel_missing_seconds = cfg.getint("thresholds", "channel_missing_seconds", fallback=600)
    gap_min_seconds = cfg.getfloat("thresholds", "gap_min_seconds", fallback=1.0)
    repeat_silence_seconds = cfg.getint("thresholds", "repeat_silence_seconds", fallback=3600)
    expected = expected_components(cfg)
    created = 0
    updated = 0
    resolved = 0
    emailed = 0
    errors: list[str] = []

    for d in devices:
        try:
            summary = receiver_basic_summary(receiver_db_dir, d)
            display = _device_display(d)
            age = summary.get("age_seconds")
            offline_fp = fingerprint("offline", d["id"], d["device_key"])
            if age is None or age > offline_seconds:
                title = f"Device offline: {display}"
                msg = f"Device {display} ({d['device_key']}) has no recent data. Last data age: {age:.0f}s." if age is not None else f"Device {display} ({d['device_key']}) has no data."
                alert_id, is_new = upsert_alert(app_db_path, device_id=int(d["id"]), device_key=d["device_key"], component=None, alert_type="device_offline", severity="critical", title=title, message=msg, fp=offline_fp)
                created += int(is_new); updated += int(not is_new)
                if send_email and should_send_email(app_db_path, alert_id, repeat_silence_seconds):
                    if send_alert_email(cfg, title=title, message=msg):
                        mark_sent(app_db_path, alert_id); emailed += 1
            else:
                resolve_alert(app_db_path, offline_fp); resolved += 1

            comp_map = {str(c.get("component", "")).upper(): c for c in summary.get("component_status", [])}
            for comp in expected:
                c = comp_map.get(comp)
                c_age = c.get("age_seconds") if c else None
                ch_fp = fingerprint("channel_missing", d["id"], d["device_key"], comp)
                if c_age is None or c_age > channel_missing_seconds:
                    title = f"Channel missing: {display} {comp}"
                    msg = f"Component {comp} on {display} has no recent data. Last component age: {c_age:.0f}s." if c_age is not None else f"Component {comp} on {display} has no data."
                    alert_id, is_new = upsert_alert(app_db_path, device_id=int(d["id"]), device_key=d["device_key"], component=comp, alert_type="channel_missing", severity="warning", title=title, message=msg, fp=ch_fp)
                    created += int(is_new); updated += int(not is_new)
                    if send_email and should_send_email(app_db_path, alert_id, repeat_silence_seconds):
                        if send_alert_email(cfg, title=title, message=msg):
                            mark_sent(app_db_path, alert_id); emailed += 1
                else:
                    resolve_alert(app_db_path, ch_fp); resolved += 1

            for gap in summary.get("gap_recent", [])[:20]:
                # Receiver gap schemas differ. Promote recent rows without expensive parsing.
                gap_seconds = None
                for key in ("gap_seconds", "duration", "duration_seconds", "gap"):
                    if key in gap and gap[key] is not None:
                        try:
                            gap_seconds = float(gap[key]); break
                        except Exception:
                            pass
                if gap_seconds is not None and gap_seconds < gap_min_seconds:
                    continue
                gap_fp = fingerprint("gap", d["id"], d["device_key"], json.dumps(gap, sort_keys=True, default=str))
                title = f"Data gap detected: {display}"
                msg = f"Receiver reported a data gap for {display}: {json.dumps(gap, default=str, ensure_ascii=False)[:800]}"
                alert_id, is_new = upsert_alert(app_db_path, device_id=int(d["id"]), device_key=d["device_key"], component=str(gap.get("component_key") or gap.get("channel") or "") or None, alert_type="data_gap", severity="warning", title=title, message=msg, fp=gap_fp)
                created += int(is_new); updated += int(not is_new)
                if send_email and should_send_email(app_db_path, alert_id, repeat_silence_seconds):
                    if send_alert_email(cfg, title=title, message=msg):
                        mark_sent(app_db_path, alert_id); emailed += 1
        except Exception as exc:
            errors.append(f"{d['device_key']}: {exc}")

    return {"created": created, "updated": updated, "resolved": resolved, "emailed": emailed, "errors": errors, "checked": len(devices)}


def backup_sqlite_database(src_path: str, dst_gz_path: str, compress_level: int = 6) -> int:
    os.makedirs(os.path.dirname(dst_gz_path), exist_ok=True)
    tmp_db = dst_gz_path + ".tmp.db"
    tmp_gz = dst_gz_path + ".tmp"
    if os.path.exists(tmp_db):
        os.unlink(tmp_db)
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True, timeout=30)
    try:
        dst = sqlite3.connect(tmp_db, timeout=30)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    with open(tmp_db, "rb") as f_in, gzip.open(tmp_gz, "wb", compresslevel=compress_level) as f_out:
        shutil.copyfileobj(f_in, f_out, length=1024 * 1024)
    os.replace(tmp_gz, dst_gz_path)
    os.unlink(tmp_db)
    return os.path.getsize(dst_gz_path)


def record_backup_run(app_db_path: str, *, status: str, started_at: float, message: str, backup_dir: str, files_count: int, total_bytes: int) -> None:
    init_stage2(app_db_path)
    with app_connect(app_db_path) as conn:
        conn.execute(
            "INSERT INTO backup_runs (started_at, finished_at, status, message, backup_dir, files_count, total_bytes) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (started_at, time.time(), status, message, backup_dir, files_count, total_bytes),
        )
        conn.commit()


def list_backup_runs(app_db_path: str, limit: int = 20) -> list[dict[str, Any]]:
    init_stage2(app_db_path)
    with app_connect(app_db_path) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM backup_runs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()]


def cleanup_old_backups(backup_dir: str, retention_days: int) -> int:
    cutoff = time.time() - retention_days * 86400
    removed = 0
    root = Path(backup_dir)
    if not root.exists():
        return 0
    for p in root.rglob("*.gz"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink(); removed += 1
        except Exception:
            pass
    return removed


def system_status(app_db_path: str, receiver_db_dir: str) -> dict[str, Any]:
    def service(name: str) -> str:
        try:
            r = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=3)
            return r.stdout.strip() or r.stderr.strip() or "unknown"
        except Exception:
            return "unknown"
    def dir_size(path: str) -> int:
        total = 0
        try:
            for root, _, files in os.walk(path):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except Exception:
                        pass
        except Exception:
            pass
        return total
    usage = shutil.disk_usage(receiver_db_dir if os.path.exists(receiver_db_dir) else "/")
    return {
        "generated_at": time.time(),
        "services": {
            "mseed-tcp-server": service("mseed-tcp-server"),
            "mseed-web-portal": service("mseed-web-portal"),
            "nginx": service("nginx"),
            "mseed-alert-worker.timer": service("mseed-alert-worker.timer"),
            "mseed-backup.timer": service("mseed-backup.timer"),
        },
        "disk": {"total": usage.total, "used": usage.used, "free": usage.free, "percent": usage.used / usage.total * 100 if usage.total else 0},
        "sizes": {
            "receiver_db_dir": dir_size(receiver_db_dir),
            "app_db": os.path.getsize(app_db_path) if os.path.exists(app_db_path) else 0,
        },
        "backup_runs": list_backup_runs(app_db_path, limit=10),
    }
PYCODE

# -----------------------------------------------------------------------------
# Tools
# -----------------------------------------------------------------------------
cat > "$APP_DIR/tools/check_alerts.py" <<'PYCODE'
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, "/opt/mseed-web-portal")

from app import app_db, stage2  # noqa: E402
from app.config import load_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one resource-light alert check for receiver databases.")
    parser.add_argument("--config", default=os.environ.get("MSEED_WEB_CONFIG", "/etc/mseed-web-portal/portal.ini"))
    parser.add_argument("--no-email", action="store_true", help="Do not send email even if SMTP is enabled.")
    args = parser.parse_args()

    settings = load_settings(args.config)
    app_db.init_db(settings.app_db)
    stage2.init_stage2(settings.app_db)
    devices = app_db.list_devices(settings.app_db, admin=True)
    result = stage2.check_devices_once(settings.app_db, settings.receiver_db_dir, devices, send_email=not args.no_email)
    print(result)
    return 1 if result.get("errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
PYCODE
chmod +x "$APP_DIR/tools/check_alerts.py"

cat > "$APP_DIR/tools/backup_databases.py" <<'PYCODE'
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import configparser
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/mseed-web-portal")

from app import app_db, stage2  # noqa: E402
from app.config import load_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="WAL-safe SQLite backups for the miniSEED web portal and receiver databases.")
    parser.add_argument("--config", default=os.environ.get("MSEED_WEB_CONFIG", "/etc/mseed-web-portal/portal.ini"))
    parser.add_argument("--backup-config", default="/etc/mseed-web-portal/backup.ini")
    args = parser.parse_args()

    started = time.time()
    settings = load_settings(args.config)
    app_db.init_db(settings.app_db)
    stage2.init_stage2(settings.app_db)

    c = configparser.ConfigParser()
    c.read(args.backup_config)
    backup_dir = c.get("backup", "backup_dir", fallback="/var/backups/mseed-web")
    retention_days = c.getint("backup", "retention_days", fallback=14)
    compress_level = c.getint("backup", "compress_level", fallback=6)
    day = time.strftime("%Y-%m-%d", time.gmtime())
    stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    out_dir = os.path.join(backup_dir, day)
    os.makedirs(out_dir, exist_ok=True)

    files = []
    total = 0
    try:
        app_dst = os.path.join(out_dir, f"app_{stamp}.db.gz")
        total += stage2.backup_sqlite_database(settings.app_db, app_dst, compress_level=compress_level)
        files.append(app_dst)

        for d in app_db.list_devices(settings.app_db, admin=True):
            src = d["db_path"]
            if not src or not os.path.exists(src):
                continue
            label = str(d["device_key"] or d["label"] or Path(src).stem).replace("/", "_")
            dst = os.path.join(out_dir, f"receiver_{label}_{stamp}.db.gz")
            total += stage2.backup_sqlite_database(src, dst, compress_level=compress_level)
            files.append(dst)

        removed = stage2.cleanup_old_backups(backup_dir, retention_days)
        msg = f"backed up {len(files)} databases, removed {removed} old backup files"
        stage2.record_backup_run(settings.app_db, status="ok", started_at=started, message=msg, backup_dir=out_dir, files_count=len(files), total_bytes=total)
        print(msg)
        return 0
    except Exception as exc:
        stage2.record_backup_run(settings.app_db, status="error", started_at=started, message=str(exc), backup_dir=out_dir, files_count=len(files), total_bytes=total)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
PYCODE
chmod +x "$APP_DIR/tools/backup_databases.py"

# -----------------------------------------------------------------------------
# Templates
# -----------------------------------------------------------------------------
cat > "$APP_DIR/app/templates/alerts.html" <<'HTML'
{% extends "base.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-end mb-4">
  <div>
    <div class="portal-pill mb-2">Alerts</div>
    <h1 class="h3 fw-bold mb-1">告警中心</h1>
    <p class="text-secondary mb-0">设备离线、通道缺失和数据断流会在这里汇总。后台检查默认每分钟运行一次。</p>
  </div>
  <form method="post" action="/alerts/check-now" class="m-0">
    <button class="btn btn-primary">立即检查</button>
  </form>
</div>

<div class="row g-3 mb-4">
  <div class="col-md-3"><div class="metric-card"><span>Open alerts</span><strong>{{ counts.open }}</strong></div></div>
  <div class="col-md-3"><div class="metric-card"><span>Critical</span><strong>{{ counts.critical }}</strong></div></div>
  <div class="col-md-3"><div class="metric-card"><span>Warning</span><strong>{{ counts.warning }}</strong></div></div>
  <div class="col-md-3"><div class="metric-card"><span>Resolved</span><strong>{{ counts.resolved }}</strong></div></div>
</div>

<div class="portal-card">
  {% if not alerts %}
  <div class="empty-state">当前没有告警。</div>
  {% endif %}
  <div class="table-responsive">
    <table class="table table-dark table-hover align-middle mb-0">
      <thead><tr><th>Status</th><th>Severity</th><th>Device</th><th>Component</th><th>Type</th><th>Message</th><th>Last seen</th><th>Action</th></tr></thead>
      <tbody>
      {% for a in alerts %}
      <tr>
        <td><span class="badge {{ 'bg-danger' if a.status == 'open' else 'bg-secondary' }}">{{ a.status }}</span></td>
        <td><span class="badge {{ 'bg-danger' if a.severity == 'critical' else 'bg-warning text-dark' }}">{{ a.severity }}</span></td>
        <td>{{ a.device_key or '-' }}</td>
        <td>{{ a.component or '-' }}</td>
        <td>{{ a.alert_type }}</td>
        <td><strong>{{ a.title }}</strong><br><span class="text-secondary small">{{ a.message }}</span></td>
        <td><span class="unix-time" data-unix="{{ a.last_seen }}">-</span></td>
        <td>
          {% if a.status == 'open' %}
          <form method="post" action="/alerts/{{ a.id }}/ack" class="m-0"><button class="btn btn-sm btn-outline-light">确认</button></form>
          {% else %}-{% endif %}
        </td>
      </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
</div>
<script src="/static/js/time.js"></script>
{% endblock %}
HTML

cat > "$APP_DIR/app/templates/system.html" <<'HTML'
{% extends "base.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-end mb-4">
  <div>
    <div class="portal-pill mb-2">System</div>
    <h1 class="h3 fw-bold mb-1">系统状态</h1>
    <p class="text-secondary mb-0">仅管理员可见，用于检查服务、磁盘、备份和数据库体积。</p>
  </div>
</div>

<div class="row g-3 mb-4">
  {% for name, status in info.services.items() %}
  <div class="col-md-3"><div class="metric-card"><span>{{ name }}</span><strong>{{ status }}</strong></div></div>
  {% endfor %}
</div>

<div class="row g-3 mb-4">
  <div class="col-md-4"><div class="metric-card"><span>Disk used</span><strong>{{ '%.1f'|format(info.disk.percent) }}%</strong></div></div>
  <div class="col-md-4"><div class="metric-card"><span>Disk free</span><strong>{{ (info.disk.free / 1024 / 1024 / 1024)|round(1) }} GB</strong></div></div>
  <div class="col-md-4"><div class="metric-card"><span>Receiver DB size</span><strong>{{ (info.sizes.receiver_db_dir / 1024 / 1024)|round(1) }} MB</strong></div></div>
</div>

<div class="portal-card">
  <h2 class="h5 mb-3">Recent backups</h2>
  {% if not info.backup_runs %}<div class="empty-state">暂无备份记录。</div>{% endif %}
  <div class="table-responsive">
    <table class="table table-dark table-hover align-middle mb-0">
      <thead><tr><th>Started</th><th>Status</th><th>Files</th><th>Size</th><th>Message</th></tr></thead>
      <tbody>
      {% for r in info.backup_runs %}
      <tr>
        <td><span class="unix-time" data-unix="{{ r.started_at }}">-</span></td>
        <td>{{ r.status }}</td>
        <td>{{ r.files_count }}</td>
        <td>{{ (r.total_bytes / 1024 / 1024)|round(1) }} MB</td>
        <td>{{ r.message }}</td>
      </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
</div>
<script src="/static/js/time.js"></script>
{% endblock %}
HTML

# -----------------------------------------------------------------------------
# Patch main.py routes, idempotently.
# -----------------------------------------------------------------------------
PYTHONPATH="$APP_DIR" "$PY" - <<'PYCODE'
from pathlib import Path
p = Path("/opt/mseed-web-portal/app/main.py")
s = p.read_text()
if "STAGE2_ALERT_BACKUP_ROUTES" not in s:
    s += r'''

# STAGE2_ALERT_BACKUP_ROUTES
from . import stage2 as _stage2

@app.on_event("startup")
def stage2_startup() -> None:
    _stage2.init_stage2(settings.app_db)

@app.get("/alerts", response_class=HTMLResponse)
def alerts_page(request: Request, user: dict[str, Any] = Depends(current_user)):
    devices = app_db.list_devices(settings.app_db, user_id=int(user["id"]), admin=is_admin(user))
    device_ids = None if is_admin(user) else [int(d["id"]) for d in devices]
    alerts = _stage2.list_alerts(settings.app_db, device_ids=device_ids, limit=300)
    counts = {
        "open": sum(1 for a in alerts if a.get("status") == "open"),
        "resolved": sum(1 for a in alerts if a.get("status") == "resolved"),
        "critical": sum(1 for a in alerts if a.get("status") == "open" and a.get("severity") == "critical"),
        "warning": sum(1 for a in alerts if a.get("status") == "open" and a.get("severity") == "warning"),
    }
    return templates.TemplateResponse(request, "alerts.html", template_context(request, alerts=alerts, counts=counts))

@app.post("/alerts/check-now")
def alerts_check_now(user: dict[str, Any] = Depends(admin_user)):
    devices = app_db.list_devices(settings.app_db, admin=True)
    _stage2.check_devices_once(settings.app_db, settings.receiver_db_dir, devices, send_email=False)
    return RedirectResponse(url="/alerts", status_code=303)

@app.post("/alerts/{alert_id}/ack")
def alerts_ack(alert_id: int, user: dict[str, Any] = Depends(current_user)):
    alert = _stage2.get_alert_by_id(settings.app_db, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    if not is_admin(user):
        allowed = {int(d["id"]) for d in app_db.list_devices(settings.app_db, user_id=int(user["id"]), admin=False)}
        if alert["device_id"] not in allowed:
            raise HTTPException(status_code=403, detail="No access to this alert")
    _stage2.ack_alert(settings.app_db, alert_id, user.get("username", "user"))
    return RedirectResponse(url="/alerts", status_code=303)

@app.get("/system", response_class=HTMLResponse)
def system_page(request: Request, user: dict[str, Any] = Depends(admin_user)):
    info = _stage2.system_status(settings.app_db, settings.receiver_db_dir)
    return templates.TemplateResponse(request, "system.html", template_context(request, info=info))
'''
    p.write_text(s)
    print("patched main.py stage2 routes")
else:
    print("main.py already contains stage2 routes")
PYCODE

# -----------------------------------------------------------------------------
# Patch navigation. Keep it tolerant to prior Chinese/English/i18n patches.
# -----------------------------------------------------------------------------
PYTHONPATH="$APP_DIR" "$PY" - <<'PYCODE'
from pathlib import Path
p = Path("/opt/mseed-web-portal/app/templates/base.html")
if not p.exists():
    raise SystemExit(0)
s = p.read_text()
if 'href="/alerts"' not in s:
    if 'href="/quality"' in s:
        s = s.replace('</a></li>\n        <li class="nav-item"><a class="nav-link" href="/export"', '</a></li>\n        <li class="nav-item"><a class="nav-link" href="/alerts" data-i18n="nav.alerts">告警</a></li>\n        <li class="nav-item"><a class="nav-link" href="/export"', 1)
    elif 'href="/history"' in s:
        s = s.replace('<li class="nav-item"><a class="nav-link" href="/history">历史波形</a></li>', '<li class="nav-item"><a class="nav-link" href="/history">历史波形</a></li>\n        <li class="nav-item"><a class="nav-link" href="/alerts" data-i18n="nav.alerts">告警</a></li>')
if 'href="/system"' not in s:
    if 'href="/admin"' in s:
        s = s.replace('<li class="nav-item"><a class="nav-link" href="/admin"', '<li class="nav-item"><a class="nav-link" href="/system" data-i18n="nav.system">系统</a></li>\n        <li class="nav-item"><a class="nav-link" href="/admin"', 1)
p.write_text(s)
print("patched base nav")
PYCODE

# Add a small i18n extension if i18n exists.
cat > "$APP_DIR/app/static/js/i18n_stage2.js" <<'JSCODE'
(function(){
  const dict = {
    zh: {
      "nav.alerts":"告警", "nav.system":"系统",
      "Alerts":"告警", "System":"系统", "Open alerts":"当前告警", "Critical":"严重", "Warning":"警告", "Resolved":"已恢复",
      "Status":"状态", "Severity":"级别", "Device":"设备", "Component":"分量", "Type":"类型", "Message":"详情", "Last seen":"最后出现", "Action":"操作",
      "Acknowledge":"确认", "Disk used":"磁盘使用率", "Disk free":"磁盘剩余", "Receiver DB size":"接收数据库大小", "Recent backups":"最近备份"
    },
    en: {
      "告警":"Alerts", "系统":"System", "告警中心":"Alert center", "立即检查":"Check now", "确认":"Acknowledge",
      "系统状态":"System status", "暂无备份记录。":"No backup records yet.", "当前没有告警。":"No alerts."
    }
  };
  function lang(){ return localStorage.getItem('portal_lang') || 'zh'; }
  function apply(){
    const d = dict[lang()] || dict.zh;
    document.querySelectorAll('[data-i18n]').forEach(el => { const k = el.getAttribute('data-i18n'); if (d[k]) el.textContent = d[k]; });
    document.querySelectorAll('body *').forEach(el => {
      if (el.children.length || !el.textContent) return;
      const t = el.textContent.trim();
      if (d[t]) el.textContent = el.textContent.replace(t, d[t]);
    });
  }
  document.addEventListener('DOMContentLoaded', apply);
  window.addEventListener('storage', apply);
})();
JSCODE
if ! grep -q "i18n_stage2.js" "$APP_DIR/app/templates/base.html"; then
  sed -i 's#</body>#<script src="/static/js/i18n_stage2.js"></script>\n</body>#' "$APP_DIR/app/templates/base.html"
fi

# -----------------------------------------------------------------------------
# Systemd services and timers. Resource-limited one-shot workers.
# -----------------------------------------------------------------------------
cat > /etc/systemd/system/mseed-alert-worker.service <<EOF2
[Unit]
Description=miniSEED Alert Worker
After=network.target mseed-web-portal.service

[Service]
Type=oneshot
User=root
Group=root
WorkingDirectory=$APP_DIR
Environment=MSEED_WEB_CONFIG=$CONFIG_DIR/portal.ini
ExecStart=$PY $APP_DIR/tools/check_alerts.py
Nice=5
IOSchedulingClass=best-effort
IOSchedulingPriority=7
CPUQuota=30%
MemoryMax=300M
EOF2

cat > /etc/systemd/system/mseed-alert-worker.timer <<'EOF2'
[Unit]
Description=Run miniSEED Alert Worker every minute

[Timer]
OnBootSec=2min
OnUnitActiveSec=60s
AccuracySec=10s
RandomizedDelaySec=10s
Persistent=true

[Install]
WantedBy=timers.target
EOF2

cat > /etc/systemd/system/mseed-backup.service <<EOF2
[Unit]
Description=miniSEED Web Portal Database Backup
After=network.target mseed-tcp-server.service

[Service]
Type=oneshot
User=root
Group=root
WorkingDirectory=$APP_DIR
Environment=MSEED_WEB_CONFIG=$CONFIG_DIR/portal.ini
ExecStart=$PY $APP_DIR/tools/backup_databases.py
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
CPUQuota=50%
MemoryMax=600M
EOF2

cat > /etc/systemd/system/mseed-backup.timer <<'EOF2'
[Unit]
Description=Daily miniSEED database backup

[Timer]
OnCalendar=*-*-* 03:15:00
RandomizedDelaySec=30min
Persistent=true

[Install]
WantedBy=timers.target
EOF2

# -----------------------------------------------------------------------------
# Initialize DB, compile, restart.
# -----------------------------------------------------------------------------
PYTHONPATH="$APP_DIR" MSEED_WEB_CONFIG="$CONFIG_DIR/portal.ini" "$PY" - <<'PYCODE'
from app.config import load_settings
from app import stage2
s = load_settings()
stage2.init_stage2(s.app_db)
print("stage2 db initialized:", s.app_db)
PYCODE

PYTHONPATH="$APP_DIR" "$PY" -m py_compile \
  "$APP_DIR/app/main.py" \
  "$APP_DIR/app/stage2.py" \
  "$APP_DIR/tools/check_alerts.py" \
  "$APP_DIR/tools/backup_databases.py"

systemctl daemon-reload
systemctl enable --now mseed-alert-worker.timer
systemctl enable --now mseed-backup.timer
systemctl restart mseed-web-portal
systemctl restart nginx || true

echo "== Stage 2 installed =="
echo "Alerts page: http://SERVER/alerts"
echo "System page: http://SERVER/system"
echo "Run manual alert check: sudo $PY $APP_DIR/tools/check_alerts.py --no-email"
echo "Run manual backup: sudo $PY $APP_DIR/tools/backup_databases.py"
echo "Configure SMTP: sudo nano $CONFIG_DIR/alerts.ini"
echo "Check timers: systemctl list-timers 'mseed-*'"
