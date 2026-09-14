#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, "/opt/mseed-web-portal")

from app import app_db  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.data_reader import discover_devices, discover_obn_devices  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan receiver HDF5 (.h5) files and register devices in the web portal app database.")
    parser.add_argument("--config", default=os.environ.get("MSEED_WEB_CONFIG", "/etc/mseed-web-portal/portal.ini"))
    args = parser.parse_args()

    settings = load_settings(args.config)
    app_db.init_db(settings.app_db)
    if hasattr(app_db, "migrate_customer_device_rules"):
        app_db.migrate_customer_device_rules(settings.app_db)
    obn_dir = os.path.join(os.path.dirname(settings.receiver_db_dir), "obn_devices")
    found = discover_devices(settings.receiver_db_dir)
    if os.path.isdir(obn_dir):
        found.extend(discover_obn_devices(obn_dir))
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
    if hasattr(app_db, "deactivate_missing_receiver_devices"):
        deactivated = app_db.deactivate_missing_receiver_devices(
            settings.app_db,
            receiver_db_dir=settings.receiver_db_dir,
            active_paths={d.db_path for d in found},
        )
        print(f"deactivated-missing: {deactivated}")
    if hasattr(app_db, "apply_customer_device_rules_to_existing"):
        changed = app_db.apply_customer_device_rules_to_existing(settings.app_db)
        print(f"access-rule-updated: {changed}")
    print(f"total: {len(found)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
