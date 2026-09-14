#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

sys.path.insert(0, "/opt/mseed-web-portal")

from app import app_db  # noqa: E402
from app.config import load_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Grant a user access to a registered device.")
    parser.add_argument("--config", default=os.environ.get("MSEED_WEB_CONFIG", "/etc/mseed-web-portal/portal.ini"))
    parser.add_argument("--username", required=True)
    parser.add_argument("--device-key", required=True)
    args = parser.parse_args()

    settings = load_settings(args.config)
    with app_db.connect(settings.app_db) as conn:
        user = conn.execute("SELECT id FROM users WHERE username = ?", (args.username,)).fetchone()
        if not user:
            raise SystemExit(f"user not found: {args.username}")
        devices = conn.execute("SELECT id, label, device_key FROM devices WHERE device_key = ?", (args.device_key,)).fetchall()
        if not devices:
            raise SystemExit(f"device not found: {args.device_key}. Run sync_devices.py first.")
        for d in devices:
            app_db.grant_device(settings.app_db, int(user["id"]), int(d["id"]))
            print(f"granted user={args.username} device_id={d['id']} key={d['device_key']} label={d['label']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
