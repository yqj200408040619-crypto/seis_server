#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, "/opt/mseed-web-portal")

from app import app_db  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.data_reader import discover_devices  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan receiver SQLite databases and register devices in the web portal app database.")
    parser.add_argument("--config", default=os.environ.get("MSEED_WEB_CONFIG", "/etc/mseed-web-portal/portal.ini"))
    args = parser.parse_args()

    settings = load_settings(args.config)
    app_db.init_db(settings.app_db)
    found = discover_devices(settings.receiver_db_dir)
    for d in found:
        device_id = app_db.upsert_device(
            settings.app_db,
            label=d.label,
            db_path=d.db_path,
            device_key=d.device_key,
            instrument_type=d.instrument_type,
            instrument_serial=d.instrument_serial,
            client_ip=d.client_ip,
            server_port=d.server_port,
        )
        print(f"device id={device_id} label={d.label} key={d.device_key} db={d.db_path}")
    print(f"total: {len(found)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
