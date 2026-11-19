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
    """Send an alert email using SMTP.

    Supported configuration in /etc/mseed-web-portal/alerts.ini:
      [smtp]
      enabled = true
      host = smtp.larksuite.com
      port = 465
      security = ssl        # ssl | starttls | none
      username = WebPortal@geoplusgmbh.de
      password = ...
      from_addr = WebPortal@geoplusgmbh.de
      to_addrs = user1@example.com,user2@example.com
      timeout_seconds = 20

    For compatibility with the earlier Stage 2 config, use_tls=true is still
    accepted and maps to security=starttls unless port=465.
    """
    if not config.getboolean("smtp", "enabled", fallback=False):
        return False

    import ssl

    host = config.get("smtp", "host", fallback="").strip()
    port = config.getint("smtp", "port", fallback=587)
    username = config.get("smtp", "username", fallback="").strip()
    password = config.get("smtp", "password", fallback="")
    from_addr = config.get("smtp", "from_addr", fallback=username).strip() or username
    to_addrs = [x.strip() for x in config.get("smtp", "to_addrs", fallback="").split(",") if x.strip()]
    timeout_seconds = config.getint("smtp", "timeout_seconds", fallback=20)

    security = config.get("smtp", "security", fallback="").strip().lower()
    if not security:
        # Backward compatibility for old use_tls field.
        use_tls = config.getboolean("smtp", "use_tls", fallback=True)
        security = "ssl" if port == 465 else ("starttls" if use_tls else "none")
    if security == "tls":
        security = "starttls"
    if security not in {"ssl", "starttls", "none"}:
        raise ValueError(f"Invalid smtp.security={security!r}. Use ssl, starttls, or none.")

    prefix = config.get("email", "subject_prefix", fallback="[Seismic Portal]").strip()
    if not host or not from_addr or not to_addrs:
        raise ValueError("SMTP host, from_addr, and to_addrs must be configured.")

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)
    msg["Subject"] = f"{prefix} {title}"
    msg.set_content(message)

    context = ssl.create_default_context()
    if security == "ssl":
        with smtplib.SMTP_SSL(host, port, timeout=timeout_seconds, context=context) as smtp:
            if username:
                smtp.login(username, password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=timeout_seconds) as smtp:
            smtp.ehlo()
            if security == "starttls":
                smtp.starttls(context=context)
                smtp.ehlo()
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
