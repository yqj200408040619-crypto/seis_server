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

    def device_id(self, client: ClientInfo, header: MSeedHeader) -> str:
        # One database per instrument. IP/server_port makes NAT/tenant separation explicit;
        # station/network makes reconnects stable even if client source port changes.
        network = safe_name(header.network or "NN")
        station = safe_name(header.station or "UNKNOWN")
        return safe_name(f"{client.client_ip}_{client.server_port}_{network}_{station}")

    def db_path(self, device_id: str) -> Path:
        return self.db_root / f"{safe_name(device_id)}.db"

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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_packets_start_unix ON packets(start_unix);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_packets_stream ON packets(network, station, location, channel);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_packets_recv_unix ON packets(recv_unix);")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS stream_state (
                    stream_key TEXT PRIMARY KEY,
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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_gaps_stream ON gaps(stream_key, created_unix);")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_unix REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    client_ip TEXT,
                    client_port INTEGER,
                    server_port INTEGER,
                    message TEXT NOT NULL
                );
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
        return ".".join([
            header.network or "",
            header.station or "",
            header.location or "",
            header.channel or "",
        ])

    def insert_packet(self, client: ClientInfo, packet: bytes, header: MSeedHeader) -> InsertResult:
        device_id = self.device_id(client, header)
        db_path = self.db_path(device_id)
        lock = self._lock_for(db_path)
        gap_messages: list[str] = []

        with lock:
            self.initialize_db(db_path)
            with sqlite3.connect(db_path, timeout=30) as conn:
                conn.execute("PRAGMA foreign_keys=ON;")
                stream_key = self._stream_key(header)
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
                        start_unix, end_unix, seq_no, raw_mseed, packet_len, record_length, sha256,
                        recv_unix, client_ip, client_port, server_port,
                        network, station, location, channel, quality, sampling_rate, npts
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        header.start_unix,
                        header.end_unix,
                        seq_no,
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
                    gap_messages = self._detect_and_store_gaps(conn, stream_key, prev, seq_no, header)
                    self._upsert_stream_state(conn, stream_key, seq_no, header)
                else:
                    conn.execute(
                        """
                        INSERT INTO events(event_unix, event_type, client_ip, client_port, server_port, message)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            recv_unix,
                            "duplicate_packet",
                            client.client_ip,
                            client.client_port,
                            client.server_port,
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
        prev: Any,
        seq_no: int,
        header: MSeedHeader,
    ) -> list[str]:
        messages: list[str] = []
        if prev is None:
            return messages

        last_seq_no, last_start, last_end, last_sr, last_npts = prev
        created = time.time()

        if last_seq_no is not None and last_seq_no >= 0 and seq_no >= 0:
            expected = (int(last_seq_no) + 1) % 1000000
            if seq_no != expected:
                msg = f"Sequence discontinuity: previous={last_seq_no}, expected={expected}, current={seq_no}"
                messages.append(msg)
                conn.execute(
                    """
                    INSERT INTO gaps(
                        stream_key, gap_type, previous_seq_no, current_seq_no,
                        previous_start_unix, current_start_unix, previous_end_unix,
                        expected_start_unix, delta_sec, message, created_unix
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        stream_key,
                        "sequence_gap",
                        last_seq_no,
                        seq_no,
                        last_start,
                        header.start_unix,
                        last_end,
                        None,
                        None,
                        msg,
                        created,
                    ),
                )

        if last_end is not None and header.start_unix >= 0 and header.sampling_rate:
            sr = float(header.sampling_rate)
            tolerance = self.config.parser.time_gap_tolerance_samples / sr
            delta = float(header.start_unix) - float(last_end)
            if delta > tolerance:
                msg = f"Time gap: previous_end={last_end:.6f}, current_start={header.start_unix:.6f}, gap={delta:.6f}s"
                messages.append(msg)
                conn.execute(
                    """
                    INSERT INTO gaps(
                        stream_key, gap_type, previous_seq_no, current_seq_no,
                        previous_start_unix, current_start_unix, previous_end_unix,
                        expected_start_unix, delta_sec, message, created_unix
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        stream_key,
                        "time_gap",
                        last_seq_no,
                        seq_no,
                        last_start,
                        header.start_unix,
                        last_end,
                        last_end,
                        delta,
                        msg,
                        created,
                    ),
                )
            elif delta < -tolerance:
                msg = f"Time overlap/replay: previous_end={last_end:.6f}, current_start={header.start_unix:.6f}, delta={delta:.6f}s"
                messages.append(msg)
                conn.execute(
                    """
                    INSERT INTO gaps(
                        stream_key, gap_type, previous_seq_no, current_seq_no,
                        previous_start_unix, current_start_unix, previous_end_unix,
                        expected_start_unix, delta_sec, message, created_unix
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        stream_key,
                        "time_overlap",
                        last_seq_no,
                        seq_no,
                        last_start,
                        header.start_unix,
                        last_end,
                        last_end,
                        delta,
                        msg,
                        created,
                    ),
                )

        return messages

    def _upsert_stream_state(self, conn: sqlite3.Connection, stream_key: str, seq_no: int, header: MSeedHeader) -> None:
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
                stream_key, network, station, location, channel,
                last_start_unix, last_end_unix, last_seq_no,
                last_sampling_rate, last_npts, last_sha256, updated_unix
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(stream_key) DO UPDATE SET
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
