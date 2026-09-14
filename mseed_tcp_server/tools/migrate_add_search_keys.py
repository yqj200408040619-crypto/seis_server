#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3


SEARCH_COLUMNS = {
    "packets": {
        "instrument_type": "TEXT",
        "instrument_serial": "TEXT",
        "component_key": "TEXT",
        "component_axis": "TEXT",
        "device_key": "TEXT",
        "stream_key": "TEXT",
    },
    "stream_state": {
        "instrument_type": "TEXT",
        "instrument_serial": "TEXT",
        "component_key": "TEXT",
        "component_axis": "TEXT",
        "device_key": "TEXT",
    },
    "gaps": {
        "instrument_type": "TEXT",
        "instrument_serial": "TEXT",
        "component_key": "TEXT",
        "device_key": "TEXT",
    },
    "events": {
        "instrument_type": "TEXT",
        "instrument_serial": "TEXT",
        "component_key": "TEXT",
        "device_key": "TEXT",
        "stream_key": "TEXT",
    },
}


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def add_column(conn: sqlite3.Connection, table: str, column: str, coltype: str) -> None:
    if table_exists(conn, table) and column not in columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def migrate_db(db_path: Path) -> None:
    with sqlite3.connect(db_path, timeout=60) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        for table, cols in SEARCH_COLUMNS.items():
            if table_exists(conn, table):
                for column, coltype in cols.items():
                    add_column(conn, table, column, coltype)

        if table_exists(conn, "packets"):
            conn.execute("UPDATE packets SET instrument_type = COALESCE(NULLIF(instrument_type, ''), network) WHERE instrument_type IS NULL OR instrument_type = ''")
            conn.execute("UPDATE packets SET instrument_serial = COALESCE(NULLIF(instrument_serial, ''), station) WHERE instrument_serial IS NULL OR instrument_serial = ''")
            conn.execute("UPDATE packets SET component_key = COALESCE(NULLIF(component_key, ''), channel) WHERE component_key IS NULL OR component_key = ''")
            conn.execute("UPDATE packets SET component_axis = substr(component_key, length(component_key), 1) WHERE component_axis IS NULL OR component_axis = ''")
            conn.execute("UPDATE packets SET device_key = COALESCE(NULLIF(device_key, ''), COALESCE(instrument_type, '') || '_' || COALESCE(instrument_serial, '')) WHERE device_key IS NULL OR device_key = ''")
            conn.execute("UPDATE packets SET stream_key = COALESCE(NULLIF(stream_key, ''), COALESCE(network, '') || '.' || COALESCE(station, '') || '.' || COALESCE(location, '') || '.' || COALESCE(channel, '')) WHERE stream_key IS NULL OR stream_key = ''")

            conn.execute("CREATE INDEX IF NOT EXISTS idx_packets_device_key ON packets(device_key)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_packets_component_key ON packets(component_key)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_packets_device_component_time ON packets(device_key, component_key, start_unix)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_packets_serial_component_time ON packets(instrument_serial, component_key, start_unix)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_packets_type_serial_time ON packets(instrument_type, instrument_serial, start_unix)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_packets_stream_key_time ON packets(stream_key, start_unix)")

            conn.execute(
                """
                CREATE VIEW IF NOT EXISTS packet_index AS
                SELECT
                    id, start_unix, end_unix, seq_no,
                    instrument_type, instrument_serial, component_key, component_axis,
                    device_key, stream_key, packet_len, record_length, sha256,
                    recv_unix, client_ip, client_port, server_port,
                    network, station, location, channel, quality,
                    sampling_rate, npts, created_at
                FROM packets
                """
            )

        if table_exists(conn, "stream_state"):
            conn.execute("UPDATE stream_state SET instrument_type = COALESCE(NULLIF(instrument_type, ''), network) WHERE instrument_type IS NULL OR instrument_type = ''")
            conn.execute("UPDATE stream_state SET instrument_serial = COALESCE(NULLIF(instrument_serial, ''), station) WHERE instrument_serial IS NULL OR instrument_serial = ''")
            conn.execute("UPDATE stream_state SET component_key = COALESCE(NULLIF(component_key, ''), channel) WHERE component_key IS NULL OR component_key = ''")
            conn.execute("UPDATE stream_state SET component_axis = substr(component_key, length(component_key), 1) WHERE component_axis IS NULL OR component_axis = ''")
            conn.execute("UPDATE stream_state SET device_key = COALESCE(NULLIF(device_key, ''), COALESCE(instrument_type, '') || '_' || COALESCE(instrument_serial, '')) WHERE device_key IS NULL OR device_key = ''")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_stream_state_device ON stream_state(device_key, component_key)")

        if table_exists(conn, "gaps"):
            conn.execute("CREATE INDEX IF NOT EXISTS idx_gaps_device_component ON gaps(device_key, component_key, created_unix)")

        conn.commit()

    print(f"migrated: {db_path}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Add future retrieval search keys to mseed-tcp-server SQLite databases")
    ap.add_argument("path", nargs="?", default="/var/lib/mseed-tcp-server/devices", help="DB file or directory containing *.db files")
    args = ap.parse_args()
    path = Path(args.path)

    if path.is_file():
        dbs = [path]
    else:
        dbs = sorted(path.glob("*.db"))

    if not dbs:
        print(f"No .db files found under {path}")
        return 1

    for db in dbs:
        migrate_db(db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
