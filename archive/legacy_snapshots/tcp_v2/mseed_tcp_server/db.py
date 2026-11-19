from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any

from .config import AppConfig
from .mseed import MSeedHeader, get_sequence_number
from .util import safe_name

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClientInfo:
    client_ip: str
    client_port: int
    server_port: int


@dataclass(frozen=True)
class InsertResult:
    db_path: Path
    device_id: str
    inserted: bool
    duplicate: bool
    gap_events: list[str]


class DeviceDatabaseManager:
    """
    One SQLite database per physical instrument.

    The database stores both the original MiniSEED identifiers
    (network/station/location/channel) and explicit SQL search keys:

    - instrument_type: network code, e.g. SS or QS
    - instrument_serial: station code, e.g. 02003
    - component_key: channel/component, e.g. BHZ, BHN, BHE
    - component_axis: last character of channel, e.g. Z/N/E
    - device_key: instrument_type + '_' + instrument_serial, e.g. SS_02003
    - stream_key: network.station.location.channel, e.g. SS.02003.00.BHZ

    These explicit keys make later queries independent of MiniSEED terminology.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.db_root = config.storage.base_dir / config.storage.db_dir_name
        self.db_root.mkdir(parents=True, exist_ok=True)
        self._locks_guard = threading.Lock()
        self._locks: dict[Path, threading.Lock] = {}

    def _lock_for(self, db_path: Path) -> threading.Lock:
        with self._locks_guard:
            lock = self._locks.get(db_path)
            if lock is None:
                lock = threading.Lock()
                self._locks[db_path] = lock
            return lock

    @staticmethod
    def _clean(value: str | None, default: str = "") -> str:
        text = (value or "").strip()
        return text if text else default

    def _keys(self, header: MSeedHeader) -> dict[str, str]:
        instrument_type = self._clean(header.network, "NN")
        instrument_serial = self._clean(header.station, "UNKNOWN")
        component_key = self._clean(header.channel, "UNKNOWN")
        component_axis = component_key[-1:] if component_key else ""
        device_key = safe_name(f"{instrument_type}_{instrument_serial}")
        stream_key = ".".join([
            self._clean(header.network),
            self._clean(header.station),
            self._clean(header.location),
            self._clean(header.channel),
        ])
        return {
            "instrument_type": instrument_type,
            "instrument_serial": instrument_serial,
            "component_key": component_key,
            "component_axis": component_axis,
            "device_key": device_key,
            "stream_key": stream_key,
        }

    def device_id(self, client: ClientInfo, header: MSeedHeader) -> str:
        # One database per instrument. IP/server_port makes NAT/tenant separation explicit;
        # type/serial makes reconnects stable even if client source port changes.
        keys = self._keys(header)
        return safe_name(f"{client.client_ip}_{client.server_port}_{keys['device_key']}")

    def db_path(self, device_id: str) -> Path:
        return self.db_root / f"{safe_name(device_id)}.db"

    @staticmethod
    def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
        try:
            return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        except sqlite3.OperationalError:
            return set()

    @staticmethod
    def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl_type: str) -> None:
        cols = DeviceDatabaseManager._table_columns(conn, table)
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")

    def _migrate_existing_schema(self, conn: sqlite3.Connection) -> None:
        """Add search-key columns and backfill older databases in place."""
        # packets search keys
        if "packets" in {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
            for col in ("instrument_type", "instrument_serial", "component_key", "component_axis", "device_key", "stream_key"):
                self._add_column_if_missing(conn, "packets", col, "TEXT")

            conn.execute("UPDATE packets SET instrument_type = COALESCE(NULLIF(instrument_type, ''), network) WHERE instrument_type IS NULL OR instrument_type = ''")
            conn.execute("UPDATE packets SET instrument_serial = COALESCE(NULLIF(instrument_serial, ''), station) WHERE instrument_serial IS NULL OR instrument_serial = ''")
            conn.execute("UPDATE packets SET component_key = COALESCE(NULLIF(component_key, ''), channel) WHERE component_key IS NULL OR component_key = ''")
            conn.execute("UPDATE packets SET component_axis = substr(component_key, length(component_key), 1) WHERE component_axis IS NULL OR component_axis = ''")
            conn.execute(
                """
                UPDATE packets
                SET device_key = COALESCE(NULLIF(device_key, ''), COALESCE(instrument_type, '') || '_' || COALESCE(instrument_serial, ''))
                WHERE device_key IS NULL OR device_key = ''
                """
            )
            conn.execute(
                """
                UPDATE packets
                SET stream_key = COALESCE(NULLIF(stream_key, ''),
                    COALESCE(network, '') || '.' || COALESCE(station, '') || '.' || COALESCE(location, '') || '.' || COALESCE(channel, '')
                )
                WHERE stream_key IS NULL OR stream_key = ''
                """
            )

        # stream_state search keys
        if "stream_state" in {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
            for col in ("instrument_type", "instrument_serial", "component_key", "component_axis", "device_key"):
                self._add_column_if_missing(conn, "stream_state", col, "TEXT")

            conn.execute("UPDATE stream_state SET instrument_type = COALESCE(NULLIF(instrument_type, ''), network) WHERE instrument_type IS NULL OR instrument_type = ''")
            conn.execute("UPDATE stream_state SET instrument_serial = COALESCE(NULLIF(instrument_serial, ''), station) WHERE instrument_serial IS NULL OR instrument_serial = ''")
            conn.execute("UPDATE stream_state SET component_key = COALESCE(NULLIF(component_key, ''), channel) WHERE component_key IS NULL OR component_key = ''")
            conn.execute("UPDATE stream_state SET component_axis = substr(component_key, length(component_key), 1) WHERE component_axis IS NULL OR component_axis = ''")
            conn.execute(
                """
                UPDATE stream_state
                SET device_key = COALESCE(NULLIF(device_key, ''), COALESCE(instrument_type, '') || '_' || COALESCE(instrument_serial, ''))
                WHERE device_key IS NULL OR device_key = ''
                """
            )

        # gaps search keys
        if "gaps" in {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
            for col in ("instrument_type", "instrument_serial", "component_key", "device_key"):
                self._add_column_if_missing(conn, "gaps", col, "TEXT")

        # events search keys
        if "events" in {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
            for col in ("instrument_type", "instrument_serial", "component_key", "device_key", "stream_key"):
                self._add_column_if_missing(conn, "events", col, "TEXT")

    def initialize_db(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path, timeout=30) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS packets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    start_unix REAL NOT NULL,
                    end_unix REAL,
                    seq_no INTEGER NOT NULL,

                    -- Explicit SQL search keys for later retrieval.
                    instrument_type TEXT,      -- e.g. SS, QS
                    instrument_serial TEXT,    -- e.g. 02003
                    component_key TEXT,        -- e.g. BHZ, BHN, BHE
                    component_axis TEXT,       -- e.g. Z, N, E
                    device_key TEXT,           -- e.g. SS_02003
                    stream_key TEXT,           -- e.g. SS.02003.00.BHZ

                    raw_mseed BLOB NOT NULL,
                    packet_len INTEGER NOT NULL,
                    record_length INTEGER NOT NULL,
                    sha256 TEXT NOT NULL UNIQUE,
                    recv_unix REAL NOT NULL,
                    client_ip TEXT NOT NULL,
                    client_port INTEGER NOT NULL,
                    server_port INTEGER NOT NULL,
                    network TEXT,
                    station TEXT,
                    location TEXT,
                    channel TEXT,
                    quality TEXT,
                    sampling_rate REAL,
                    npts INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(network, station, location, channel, start_unix, seq_no)
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS stream_state (
                    stream_key TEXT PRIMARY KEY,
                    instrument_type TEXT,
                    instrument_serial TEXT,
                    component_key TEXT,
                    component_axis TEXT,
                    device_key TEXT,
                    network TEXT,
                    station TEXT,
                    location TEXT,
                    channel TEXT,
                    last_start_unix REAL,
                    last_end_unix REAL,
                    last_seq_no INTEGER,
                    last_sampling_rate REAL,
                    last_npts INTEGER,
                    last_sha256 TEXT,
                    updated_unix REAL NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS gaps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stream_key TEXT NOT NULL,
                    instrument_type TEXT,
                    instrument_serial TEXT,
                    component_key TEXT,
                    device_key TEXT,
                    gap_type TEXT NOT NULL,
                    previous_seq_no INTEGER,
                    current_seq_no INTEGER,
                    previous_start_unix REAL,
                    current_start_unix REAL,
                    previous_end_unix REAL,
                    expected_start_unix REAL,
                    delta_sec REAL,
                    message TEXT NOT NULL,
                    created_unix REAL NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_unix REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    client_ip TEXT,
                    client_port INTEGER,
                    server_port INTEGER,
                    instrument_type TEXT,
                    instrument_serial TEXT,
                    component_key TEXT,
                    device_key TEXT,
                    stream_key TEXT,
                    message TEXT NOT NULL
                );
                """
            )

            self._migrate_existing_schema(conn)

            # General time/indexes.
            conn.execute("CREATE INDEX IF NOT EXISTS idx_packets_start_unix ON packets(start_unix);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_packets_stream ON packets(network, station, location, channel);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_packets_recv_unix ON packets(recv_unix);")

            # Search-key indexes for future retrieval.
            conn.execute("CREATE INDEX IF NOT EXISTS idx_packets_device_key ON packets(device_key);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_packets_component_key ON packets(component_key);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_packets_device_component_time ON packets(device_key, component_key, start_unix);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_packets_serial_component_time ON packets(instrument_serial, component_key, start_unix);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_packets_type_serial_time ON packets(instrument_type, instrument_serial, start_unix);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_packets_stream_key_time ON packets(stream_key, start_unix);")

            conn.execute("CREATE INDEX IF NOT EXISTS idx_gaps_stream ON gaps(stream_key, created_unix);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_gaps_device_component ON gaps(device_key, component_key, created_unix);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_stream_state_device ON stream_state(device_key, component_key);")

            # Lightweight view for retrieval without reading raw_mseed BLOBs.
            conn.execute(
                """
                CREATE VIEW IF NOT EXISTS packet_index AS
                SELECT
                    id,
                    start_unix,
                    end_unix,
                    seq_no,
                    instrument_type,
                    instrument_serial,
                    component_key,
                    component_axis,
                    device_key,
                    stream_key,
                    packet_len,
                    record_length,
                    sha256,
                    recv_unix,
                    client_ip,
                    client_port,
                    server_port,
                    network,
                    station,
                    location,
                    channel,
                    quality,
                    sampling_rate,
                    npts,
                    created_at
                FROM packets;
                """
            )
            conn.commit()

    def log_event(self, db_path: Path, event_type: str, client: ClientInfo, message: str) -> None:
        lock = self._lock_for(db_path)
        with lock:
            self.initialize_db(db_path)
            with sqlite3.connect(db_path, timeout=30) as conn:
                conn.execute(
                    """
                    INSERT INTO events(event_unix, event_type, client_ip, client_port, server_port, message)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (time.time(), event_type, client.client_ip, client.client_port, client.server_port, message),
                )
                conn.commit()

    def _stream_key(self, header: MSeedHeader) -> str:
        return self._keys(header)["stream_key"]

    def insert_packet(self, client: ClientInfo, packet: bytes, header: MSeedHeader) -> InsertResult:
        device_id = self.device_id(client, header)
        db_path = self.db_path(device_id)
        lock = self._lock_for(db_path)
        gap_messages: list[str] = []

        with lock:
            self.initialize_db(db_path)
            with sqlite3.connect(db_path, timeout=30) as conn:
                conn.execute("PRAGMA foreign_keys=ON;")
                keys = self._keys(header)
                stream_key = keys["stream_key"]
                seq_no = get_sequence_number(packet)
                recv_unix = time.time()

                prev = conn.execute(
                    """
                    SELECT last_seq_no, last_start_unix, last_end_unix, last_sampling_rate, last_npts
                    FROM stream_state WHERE stream_key = ?
                    """,
                    (stream_key,),
                ).fetchone()

                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO packets(
                        start_unix, end_unix, seq_no,
                        instrument_type, instrument_serial, component_key, component_axis, device_key, stream_key,
                        raw_mseed, packet_len, record_length, sha256,
                        recv_unix, client_ip, client_port, server_port,
                        network, station, location, channel, quality, sampling_rate, npts
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        header.start_unix,
                        header.end_unix,
                        seq_no,
                        keys["instrument_type"],
                        keys["instrument_serial"],
                        keys["component_key"],
                        keys["component_axis"],
                        keys["device_key"],
                        keys["stream_key"],
                        sqlite3.Binary(packet),
                        len(packet),
                        header.record_length,
                        header.sha256,
                        recv_unix,
                        client.client_ip,
                        client.client_port,
                        client.server_port,
                        header.network,
                        header.station,
                        header.location,
                        header.channel,
                        header.quality,
                        header.sampling_rate,
                        header.npts,
                    ),
                )

                inserted = cur.rowcount == 1
                duplicate = not inserted

                if inserted:
                    gap_messages = self._detect_and_store_gaps(conn, stream_key, keys, prev, seq_no, header)
                    self._upsert_stream_state(conn, stream_key, keys, seq_no, header)
                else:
                    conn.execute(
                        """
                        INSERT INTO events(
                            event_unix, event_type, client_ip, client_port, server_port,
                            instrument_type, instrument_serial, component_key, device_key, stream_key, message
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            recv_unix,
                            "duplicate_packet",
                            client.client_ip,
                            client.client_port,
                            client.server_port,
                            keys["instrument_type"],
                            keys["instrument_serial"],
                            keys["component_key"],
                            keys["device_key"],
                            keys["stream_key"],
                            f"Duplicate ignored: stream={stream_key}, seq={seq_no}, start={header.start_unix}, sha256={header.sha256}",
                        ),
                    )

                conn.commit()

        return InsertResult(
            db_path=db_path,
            device_id=device_id,
            inserted=inserted,
            duplicate=duplicate,
            gap_events=gap_messages,
        )

    def _detect_and_store_gaps(
        self,
        conn: sqlite3.Connection,
        stream_key: str,
        keys: dict[str, str],
        prev: Any,
        seq_no: int,
        header: MSeedHeader,
    ) -> list[str]:
        messages: list[str] = []
        if prev is None:
            return messages

        last_seq_no, last_start, last_end, last_sr, last_npts = prev
        created = time.time()

        def insert_gap(gap_type: str, msg: str, expected_start_unix: float | None, delta_sec: float | None) -> None:
            conn.execute(
                """
                INSERT INTO gaps(
                    stream_key, instrument_type, instrument_serial, component_key, device_key,
                    gap_type, previous_seq_no, current_seq_no,
                    previous_start_unix, current_start_unix, previous_end_unix,
                    expected_start_unix, delta_sec, message, created_unix
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stream_key,
                    keys["instrument_type"],
                    keys["instrument_serial"],
                    keys["component_key"],
                    keys["device_key"],
                    gap_type,
                    last_seq_no,
                    seq_no,
                    last_start,
                    header.start_unix,
                    last_end,
                    expected_start_unix,
                    delta_sec,
                    msg,
                    created,
                ),
            )

        if last_seq_no is not None and last_seq_no >= 0 and seq_no >= 0:
            expected = (int(last_seq_no) + 1) % 1000000
            if seq_no != expected:
                msg = f"Sequence discontinuity: previous={last_seq_no}, expected={expected}, current={seq_no}"
                messages.append(msg)
                insert_gap("sequence_gap", msg, None, None)

        if last_end is not None and header.start_unix >= 0 and header.sampling_rate:
            sr = float(header.sampling_rate)
            tolerance = self.config.parser.time_gap_tolerance_samples / sr
            delta = float(header.start_unix) - float(last_end)
            if delta > tolerance:
                msg = f"Time gap: previous_end={last_end:.6f}, current_start={header.start_unix:.6f}, gap={delta:.6f}s"
                messages.append(msg)
                insert_gap("time_gap", msg, float(last_end), delta)
            elif delta < -tolerance:
                msg = f"Time overlap/replay: previous_end={last_end:.6f}, current_start={header.start_unix:.6f}, delta={delta:.6f}s"
                messages.append(msg)
                insert_gap("time_overlap", msg, float(last_end), delta)

        return messages

    def _upsert_stream_state(self, conn: sqlite3.Connection, stream_key: str, keys: dict[str, str], seq_no: int, header: MSeedHeader) -> None:
        # Only move state forward for validated chronological data. This prevents an old replayed packet
        # from overwriting the latest checkpoint after a reconnect.
        current = conn.execute(
            "SELECT last_start_unix FROM stream_state WHERE stream_key = ?",
            (stream_key,),
        ).fetchone()
        if current is not None and current[0] is not None and header.start_unix < float(current[0]):
            return

        conn.execute(
            """
            INSERT INTO stream_state(
                stream_key, instrument_type, instrument_serial, component_key, component_axis, device_key,
                network, station, location, channel,
                last_start_unix, last_end_unix, last_seq_no,
                last_sampling_rate, last_npts, last_sha256, updated_unix
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(stream_key) DO UPDATE SET
                instrument_type=excluded.instrument_type,
                instrument_serial=excluded.instrument_serial,
                component_key=excluded.component_key,
                component_axis=excluded.component_axis,
                device_key=excluded.device_key,
                network=excluded.network,
                station=excluded.station,
                location=excluded.location,
                channel=excluded.channel,
                last_start_unix=excluded.last_start_unix,
                last_end_unix=excluded.last_end_unix,
                last_seq_no=excluded.last_seq_no,
                last_sampling_rate=excluded.last_sampling_rate,
                last_npts=excluded.last_npts,
                last_sha256=excluded.last_sha256,
                updated_unix=excluded.updated_unix
            """,
            (
                stream_key,
                keys["instrument_type"],
                keys["instrument_serial"],
                keys["component_key"],
                keys["component_axis"],
                keys["device_key"],
                header.network,
                header.station,
                header.location,
                header.channel,
                header.start_unix,
                header.end_unix,
                seq_no,
                header.sampling_rate,
                header.npts,
                header.sha256,
                time.time(),
            ),
        )
