#!/usr/bin/env python3
from __future__ import annotations

import argparse
import configparser
import gzip
import h5py
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/mseed-web-portal")

from app import app_db, stage2  # noqa: E402
from app.config import load_settings  # noqa: E402


def backup_hdf5_database(source: str, destination: str, *, compress_level: int) -> int:
    """Create a readable HDF5 snapshot and gzip it for retention."""
    temporary = destination.removesuffix(".gz") + ".tmp"
    try:
        with h5py.File(source, "r") as src, h5py.File(temporary, "w") as dst:
            for key, value in src.attrs.items():
                dst.attrs[key] = value
            for name in src:
                src.copy(name, dst)
        with open(temporary, "rb") as raw, gzip.open(destination, "wb", compresslevel=compress_level) as compressed:
            shutil.copyfileobj(raw, compressed)
        return os.path.getsize(destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description="Back up portal SQLite metadata and receiver HDF5 files.")
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
            if not src.endswith(".h5"):
                continue
            dst = os.path.join(out_dir, f"receiver_{label}_{stamp}.h5.gz")
            total += backup_hdf5_database(src, dst, compress_level=compress_level)
            files.append(dst)

        removed = stage2.cleanup_old_backups(backup_dir, retention_days)
        msg = f"backed up {len(files)} files, removed {removed} old backup files"
        stage2.record_backup_run(settings.app_db, status="ok", started_at=started, message=msg, backup_dir=out_dir, files_count=len(files), total_bytes=total)
        print(msg)
        return 0
    except Exception as exc:
        stage2.record_backup_run(settings.app_db, status="error", started_at=started, message=str(exc), backup_dir=out_dir, files_count=len(files), total_bytes=total)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
