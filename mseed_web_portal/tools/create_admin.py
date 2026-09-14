#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import os
import sys

sys.path.insert(0, "/opt/mseed-web-portal")

from app.app_db import create_or_update_user, init_db  # noqa: E402
from app.config import load_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or update a web portal user.")
    parser.add_argument("--config", default=os.environ.get("MSEED_WEB_CONFIG", "/etc/mseed-web-portal/portal.ini"))
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name", default=None)
    parser.add_argument("--role", choices=["admin", "user"], default="admin")
    parser.add_argument("--password", default=None)
    args = parser.parse_args()

    settings = load_settings(args.config)
    init_db(settings.app_db)
    password = args.password or getpass.getpass("Password: ")
    user_id = create_or_update_user(
        settings.app_db,
        username=args.username,
        password=password,
        display_name=args.display_name or args.username,
        role=args.role,
    )
    print(f"user saved: id={user_id} username={args.username} role={args.role}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
