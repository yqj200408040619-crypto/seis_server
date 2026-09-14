#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, "/opt/mseed-web-portal")

from app import app_db  # noqa: E402
from app.config import load_settings  # noqa: E402


def parse_serial(v: str) -> int:
    digits = "".join(ch for ch in str(v) if ch.isdigit())
    if not digits:
        raise argparse.ArgumentTypeError(f"Invalid serial number: {v}")
    return int(digits)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a customer device auto-access rule, e.g. SS_01000-02000.")
    parser.add_argument("--config", default=os.environ.get("MSEED_WEB_CONFIG", "/etc/mseed-web-portal/portal.ini"))
    parser.add_argument("--customer", required=True, help="Customer id, name, or code.")
    parser.add_argument("--instrument-type", "--type", dest="instrument_type", required=True, help="Instrument type, e.g. SS or QS.")
    parser.add_argument("--from", dest="serial_start", required=True, type=parse_serial, help="Start serial, e.g. 01000.")
    parser.add_argument("--to", dest="serial_end", required=True, type=parse_serial, help="End serial, e.g. 02000.")
    parser.add_argument("--prefix", default="", help="Optional device_key prefix. Defaults to '<TYPE>_'.")
    parser.add_argument("--notes", default="")
    parser.add_argument("--apply-existing", action="store_true", help="Apply rules to existing devices immediately.")
    args = parser.parse_args()

    settings = load_settings(args.config)
    app_db.init_db(settings.app_db)
    app_db.migrate_customer_device_rules(settings.app_db)
    cid = app_db.find_customer_id(settings.app_db, args.customer)
    if cid is None:
        raise SystemExit(f"Customer not found: {args.customer}. Create it in /admin first or use tools/create_customer through the UI.")
    rule_id = app_db.upsert_customer_device_rule(
        settings.app_db,
        customer_id=cid,
        instrument_type=args.instrument_type,
        serial_start=args.serial_start,
        serial_end=args.serial_end,
        device_key_prefix=args.prefix or f"{args.instrument_type.upper()}_",
        notes=args.notes,
    )
    changed = 0
    if args.apply_existing:
        changed = app_db.apply_customer_device_rules_to_existing(settings.app_db)
    print(f"rule id={rule_id} customer_id={cid} type={args.instrument_type.upper()} range={args.serial_start:05d}-{args.serial_end:05d} changed_existing={changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
