#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3


def main() -> int:
    ap = argparse.ArgumentParser(description="Export raw miniSEED packets from one device database")
    ap.add_argument("db", help="Path to device .db")
    ap.add_argument("output", help="Output .mseed file")
    ap.add_argument("--stream", help="Optional stream key: NET.STA.LOC.CHA")
    ap.add_argument("--start", type=float, help="UNIX start time inclusive")
    ap.add_argument("--end", type=float, help="UNIX end time exclusive")
    args = ap.parse_args()

    where = []
    params: list[object] = []
    if args.stream:
        parts = args.stream.split(".")
        if len(parts) != 4:
            raise SystemExit("--stream must be NET.STA.LOC.CHA")
        where.append("network=? AND station=? AND location=? AND channel=?")
        params.extend(parts)
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
    with sqlite3.connect(args.db) as conn, open(out, "wb") as f:
        for (blob,) in conn.execute(sql, params):
            f.write(blob)
            count += 1
    print(f"exported {count} packets to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
