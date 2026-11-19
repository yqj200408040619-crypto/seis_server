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
