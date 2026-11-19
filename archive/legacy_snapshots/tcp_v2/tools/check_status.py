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


def print_db_status(db_path: Path) -> None:
    print(f"\n== {db_path.name} ==")
    with sqlite3.connect(db_path) as conn:
        try:
            packets = conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0]
            gaps = conn.execute("SELECT COUNT(*) FROM gaps").fetchone()[0]
            dup = conn.execute("SELECT COUNT(*) FROM events WHERE event_type='duplicate_packet'").fetchone()[0]
        except sqlite3.OperationalError as exc:
            print(f"not a valid receiver DB: {exc}")
            return

        print(f"packets: {packets}")
        print(f"gaps:    {gaps}")
        print(f"dups:    {dup}")

        if has_column(conn, "packets", "device_key"):
            print("devices/components:")
            for row in conn.execute(
                """
                SELECT
                    COALESCE(device_key, network || '_' || station) AS device_key,
                    COALESCE(instrument_type, network) AS instrument_type,
                    COALESCE(instrument_serial, station) AS instrument_serial,
                    COALESCE(component_key, channel) AS component_key,
                    COUNT(*) AS packets,
                    MIN(start_unix) AS first_start,
                    MAX(start_unix) AS last_start
                FROM packets
                GROUP BY device_key, instrument_type, instrument_serial, component_key
                ORDER BY device_key, component_key
                """
            ):
                print(
                    "  device=%s type=%s serial=%s component=%s packets=%s first=%s last=%s"
                    % row
                )

        print("streams:")
        if has_column(conn, "stream_state", "device_key"):
            query = """
                SELECT device_key, component_key, stream_key, last_start_unix, last_end_unix,
                       last_seq_no, last_sampling_rate, last_npts, updated_unix
                FROM stream_state ORDER BY device_key, component_key, stream_key
            """
            for row in conn.execute(query):
                print(
                    "  device=%-12s component=%-4s stream=%-18s last_start=%s last_end=%s last_seq=%s sr=%s npts=%s updated=%s"
                    % row
                )
        else:
            for row in conn.execute(
                """
                SELECT stream_key, last_start_unix, last_end_unix, last_seq_no,
                       last_sampling_rate, last_npts, updated_unix
                FROM stream_state ORDER BY stream_key
                """
            ):
                print("  %-24s last_start=%s last_end=%s last_seq=%s sr=%s npts=%s updated=%s" % row)

        if gaps:
            print("recent gaps:")
            if has_column(conn, "gaps", "device_key"):
                for row in conn.execute(
                    """
                    SELECT gap_type, device_key, component_key, stream_key,
                           previous_seq_no, current_seq_no, delta_sec, message
                    FROM gaps ORDER BY id DESC LIMIT 10
                    """
                ):
                    print("  %s device=%s component=%s stream=%s prev=%s cur=%s delta=%s %s" % row)
            else:
                for row in conn.execute(
                    """
                    SELECT gap_type, stream_key, previous_seq_no, current_seq_no, delta_sec, message
                    FROM gaps ORDER BY id DESC LIMIT 10
                    """
                ):
                    print("  %s %-24s prev=%s cur=%s delta=%s %s" % row)


def main() -> int:
    ap = argparse.ArgumentParser(description="Show mseed-tcp-server database status")
    ap.add_argument("db_dir", nargs="?", default="/var/lib/mseed-tcp-server/devices", help="Device database directory")
    args = ap.parse_args()
    db_dir = Path(args.db_dir)
    dbs = sorted(db_dir.glob("*.db"))
    if not dbs:
        print(f"No .db files found in {db_dir}")
        return 1
    for db in dbs:
        print_db_status(db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
