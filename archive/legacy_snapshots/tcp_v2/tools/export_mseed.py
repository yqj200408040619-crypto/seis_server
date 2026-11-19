#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3


def has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    try:
        return column in {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.OperationalError:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Export raw miniSEED packets from one device database")
    ap.add_argument("db", help="Path to device .db")
    ap.add_argument("output", help="Output .mseed file")
    ap.add_argument("--stream", help="Optional stream key: NET.STA.LOC.CHA, e.g. SS.02003.00.BHZ")
    ap.add_argument("--device-key", help="Optional device key, e.g. SS_02003")
    ap.add_argument("--instrument-type", help="Optional instrument type, e.g. SS or QS")
    ap.add_argument("--serial", dest="instrument_serial", help="Optional instrument serial, e.g. 02003")
    ap.add_argument("--component", dest="component_key", help="Optional component/channel key, e.g. BHZ, BHN, BHE")
    ap.add_argument("--start", type=float, help="UNIX start time inclusive")
    ap.add_argument("--end", type=float, help="UNIX end time exclusive")
    args = ap.parse_args()

    where = []
    params: list[object] = []

    with sqlite3.connect(args.db) as conn:
        supports_keys = has_column(conn, "packets", "device_key")

        if args.stream:
            if supports_keys:
                where.append("stream_key=?")
                params.append(args.stream)
            else:
                parts = args.stream.split(".")
                if len(parts) != 4:
                    raise SystemExit("--stream must be NET.STA.LOC.CHA")
                where.append("network=? AND station=? AND location=? AND channel=?")
                params.extend(parts)

        if args.device_key:
            if not supports_keys:
                raise SystemExit("This DB has no device_key column. Run migrate_add_search_keys.py first.")
            where.append("device_key=?")
            params.append(args.device_key)

        if args.instrument_type:
            if not supports_keys:
                raise SystemExit("This DB has no instrument_type column. Run migrate_add_search_keys.py first.")
            where.append("instrument_type=?")
            params.append(args.instrument_type)

        if args.instrument_serial:
            if not supports_keys:
                raise SystemExit("This DB has no instrument_serial column. Run migrate_add_search_keys.py first.")
            where.append("instrument_serial=?")
            params.append(args.instrument_serial)

        if args.component_key:
            if supports_keys:
                where.append("component_key=?")
            else:
                where.append("channel=?")
            params.append(args.component_key)

        if args.start is not None:
            where.append("start_unix >= ?")
            params.append(args.start)
        if args.end is not None:
            where.append("start_unix < ?")
            params.append(args.end)

        sql = "SELECT raw_mseed FROM packets"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY start_unix, seq_no, id"

        out = Path(args.output)
        count = 0
        with open(out, "wb") as f:
            for (blob,) in conn.execute(sql, params):
                f.write(blob)
                count += 1

    print(f"exported {count} packets to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
