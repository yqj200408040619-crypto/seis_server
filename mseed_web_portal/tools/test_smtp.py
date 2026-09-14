#!/usr/bin/env python3
from __future__ import annotations

import argparse
import configparser
import sys
import time

sys.path.insert(0, "/opt/mseed-web-portal")

from app import stage2  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Send a test SMTP email using alerts.ini.")
    ap.add_argument("--config", default="/etc/mseed-web-portal/alerts.ini")
    ap.add_argument("--to", default=None, help="Override to_addrs for this test only.")
    ap.add_argument("--title", default="SMTP test")
    ap.add_argument("--message", default=None)
    args = ap.parse_args()

    c = configparser.ConfigParser()
    c.read(args.config)
    if args.to:
        if not c.has_section("smtp"):
            c.add_section("smtp")
        c.set("smtp", "to_addrs", args.to)
    msg = args.message or f"This is a test email from Seismic Data Portal. Time: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}"
    ok = stage2.send_alert_email(c, title=args.title, message=msg)
    print("SMTP test sent" if ok else "SMTP disabled or not sent")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
