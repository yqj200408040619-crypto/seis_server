"""Lightweight stubs that let the real server.py run without h5py/obspy/numpy.

The sandbox has INTEGRATIONS_ONLY networking, so third-party wheels (h5py,
obspy, numpy, fastapi) cannot be installed. The *connection* logic in
``server.py`` (BoundedSemaphore gate, idle reaper, write-queue backpressure,
graceful drain) is pure standard library, and only reaches into ``db``,
``mseed`` and ``util`` for a handful of symbols. We replace those three
modules with faithful minimal stand-ins injected into ``sys.modules`` BEFORE
``server`` is imported, so the genuine server code path executes unmodified.

The stubbed miniSEED framing uses a trivial fixed 64-byte "record":

    b"MS" + device_id(16 bytes, space-padded) + payload(46 bytes)

That is enough for ``_process_buffer`` to cut records out of the TCP byte
stream and hand them to the (fake) write pipeline, which is all the connection
tests need. It is NOT a real miniSEED record and is only used in-process.
"""
from __future__ import annotations

import sys
import threading
import types
from dataclasses import dataclass, field
from pathlib import Path

RECORD_LEN = 64
MAGIC = b"MS"


def make_record(device_id: str, payload: bytes = b"") -> bytes:
    dev = device_id.encode("ascii", "replace")[:16].ljust(16, b" ")
    body = (payload or b"x" * 46)[:46].ljust(46, b"\x00")
    rec = MAGIC + dev + body
    assert len(rec) == RECORD_LEN, len(rec)
    return rec


# --------------------------------------------------------------------------
# stub: util
# --------------------------------------------------------------------------
def _install_util() -> types.ModuleType:
    mod = types.ModuleType("mseed_tcp_server.util")

    def safe_name(value: str, fallback: str = "unknown") -> str:
        out = "".join(c if (c.isalnum() or c in "._-") else "_" for c in (value or ""))
        return out or fallback

    def quarantine_path(base_dir: Path, prefix: str = "bad") -> Path:
        base_dir.mkdir(parents=True, exist_ok=True)
        return base_dir / f"{prefix}.bin"

    mod.safe_name = safe_name
    mod.quarantine_path = quarantine_path
    sys.modules["mseed_tcp_server.util"] = mod
    return mod


# --------------------------------------------------------------------------
# stub: mseed
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class StubHeader:
    network: str = "NN"
    station: str = "STA"
    location: str = ""
    channel: str = "CH"
    start_unix: float = 0.0
    end_unix: float = 0.0
    sampling_rate: float = 100.0
    npts: int = 1
    record_length: int = RECORD_LEN
    sha256: str = "0" * 64
    quality: str = "D"
    device_tag: str = ""


@dataclass
class StubLenInfo:
    length: int = RECORD_LEN


def _install_mseed() -> types.ModuleType:
    mod = types.ModuleType("mseed_tcp_server.mseed")

    def is_plausible_record_start(buf: bytes, offset: int = 0) -> bool:
        return buf[offset:offset + 2] == MAGIC

    def find_next_record_start(buf: bytes, scan_limit: int) -> int | None:
        idx = buf.find(MAGIC, 1)
        return idx if idx != -1 else None

    def get_record_length(buf: bytes, cfg) -> StubLenInfo | None:
        return StubLenInfo(RECORD_LEN)

    def get_sequence_number(packet: bytes) -> int:
        return 0

    def parse_full_packet(packet: bytes, record_length: int, cfg):
        dev = packet[2:18].decode("ascii", "replace").strip()
        return StubHeader(device_tag=dev), b""

    mod.MSeedHeader = StubHeader
    mod.is_plausible_record_start = is_plausible_record_start
    mod.find_next_record_start = find_next_record_start
    mod.get_record_length = get_record_length
    mod.get_sequence_number = get_sequence_number
    mod.parse_full_packet = parse_full_packet
    sys.modules["mseed_tcp_server.mseed"] = mod
    return mod


# --------------------------------------------------------------------------
# stub: db
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ClientInfo:
    client_ip: str
    client_port: int
    server_port: int


@dataclass(frozen=True)
class InsertResult:
    db_path: object
    device_id: str
    inserted: bool
    duplicate: bool
    gap_events: list


@dataclass
class FakeDB:
    """Records every insert; optional artificial write delay to force backpressure."""
    write_delay_sec: float = 0.0
    inserted: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def device_id(self, client: ClientInfo, header) -> str:
        return getattr(header, "device_tag", "") or f"{client.client_ip}:{client.client_port}"

    def insert_packet(self, client, packet, header, waveform) -> InsertResult:
        if self.write_delay_sec:
            import time
            time.sleep(self.write_delay_sec)
        with self._lock:
            self.inserted += 1
        return InsertResult(Path("/tmp/fake.h5"), self.device_id(client, header),
                            True, False, [])

    def close(self) -> None:
        pass


def _install_db() -> types.ModuleType:
    mod = types.ModuleType("mseed_tcp_server.db")
    mod.ClientInfo = ClientInfo
    mod.InsertResult = InsertResult
    mod.DeviceDatabaseManager = FakeDB
    sys.modules["mseed_tcp_server.db"] = mod
    return mod


def install_all() -> None:
    """Install all stubs. Must be called before importing server."""
    # Ensure a real package object exists for the dotted imports.
    pkg_name = "mseed_tcp_server"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = []  # namespace-ish; submodules provided via sys.modules
        sys.modules[pkg_name] = pkg
    _install_util()
    _install_mseed()
    _install_db()
