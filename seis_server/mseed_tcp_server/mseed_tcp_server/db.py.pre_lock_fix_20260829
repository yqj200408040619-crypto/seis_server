from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import threading
import time

import h5py
import numpy as np

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
    """One HDF5 file per MiniSEED device, compatible with mseed-web-portal."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.h5_root = config.storage.base_dir / config.storage.db_dir_name
        self.h5_root.mkdir(parents=True, exist_ok=True)
        self._locks_guard = threading.Lock()
        self._locks: dict[Path, threading.Lock] = {}
        self._sha256_cache: dict[Path, set[str]] = {}
        # New files remain open in SWMR write mode. This removes one HDF5
        # open/close cycle per packet and lets the portal read flushed data
        # while instruments continue streaming. Old HDF5 files whose
        # superblock predates SWMR retain the previous open/write/close path.
        self._files: dict[Path, h5py.File] = {}
        self._legacy_paths: set[Path] = set()

    def _lock_for(self, path: Path) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(path, threading.Lock())

    @staticmethod
    def _clean(value: str | None, default: str = "") -> str:
        return (value or "").strip() or default

    def _keys(self, header: MSeedHeader) -> dict[str, str]:
        network = self._clean(header.network, "NN")
        station = self._clean(header.station, "UNKNOWN")
        channel = self._clean(header.channel, "UNKNOWN")
        return {
            "instrument_type": network,
            "instrument_serial": station,
            "component_key": channel,
            "device_key": safe_name(f"{network}_{station}"),
            "stream_key": ".".join((network, station, self._clean(header.location), channel)),
        }

    def device_id(self, client: ClientInfo, header: MSeedHeader) -> str:
        return safe_name(f"{client.client_ip}_{client.server_port}_{self._keys(header)['device_key']}")

    def db_path(self, device_id: str) -> Path:
        return self.h5_root / f"{safe_name(device_id)}.h5"

    def _initialize_h5(self, f: h5py.File, device_id: str, keys: dict[str, str] | None = None) -> None:
        if "device_id" not in f.attrs:
            f.attrs["device_id"] = device_id
            f.attrs["created_at"] = time.time()
        if keys:
            # These root attributes are consumed by Portal device discovery.
            for name in ("device_key", "instrument_type", "instrument_serial"):
                f.attrs[name] = keys[name]
        if "gaps" not in f:
            f.create_dataset("gaps", shape=(0,), maxshape=(None,), chunks=True, dtype=np.dtype([
                ("stream_key", "S100"), ("gap_type", "S20"), ("previous_seq", "i4"),
                ("current_seq", "i4"), ("previous_start", "f8"), ("current_start", "f8"),
                ("previous_end", "f8"), ("expected_start", "f8"), ("delta_sec", "f8"),
                ("message", "S512"), ("created_unix", "f8"),
            ]))
        if "events" not in f:
            f.create_dataset("events", shape=(0,), maxshape=(None,), chunks=True, dtype=np.dtype([
                ("event_unix", "f8"), ("event_type", "S32"), ("client_ip", "S64"),
                ("client_port", "i4"), ("server_port", "i4"), ("instrument_type", "S32"),
                ("instrument_serial", "S32"), ("component_key", "S32"), ("device_key", "S32"),
                ("stream_key", "S100"), ("message", "S512"),
            ]))

    @staticmethod
    def _append(f: h5py.File, name: str, row: dict[str, object]) -> None:
        ds = f[name]
        ds.resize(ds.shape[0] + 1, axis=0)
        ds[-1] = tuple((v.encode("utf-8", "replace") if isinstance(v, str) else v) for v in (row.get(k) for k in ds.dtype.names))

    def _gap(self, f: h5py.File, messages: list[str], stream: str, kind: str, last_seq: int, seq: int, last_start: float, start: float, last_end: float, expected: float, delta: float, now: float, message: str) -> None:
        messages.append(message)
        self._append(f, "gaps", {"stream_key": stream, "gap_type": kind, "previous_seq": last_seq,
            "current_seq": seq, "previous_start": last_start, "current_start": start,
            "previous_end": last_end, "expected_start": expected, "delta_sec": delta,
            "message": message, "created_unix": now})

    def _write_zero_gap(self, grp: h5py.Group, start: float, end: float, sampling_rate: float,
                        dtype: np.dtype, options: dict[str, object], now: float, seq: int) -> int:
        """Write one synthetic zero-valued dataset covering a time gap."""
        npts = int(round((end - start) * sampling_rate))
        if npts <= 0:
            return 0
        name = f"gap_{int(start * 1_000_000_000):019d}_{int(end * 1_000_000_000):019d}_{seq:06d}"
        if name in grp:
            return 0
        dset = grp.create_dataset(name, data=np.zeros(npts, dtype=dtype), **options)
        dset.attrs.update({"start_unix": start, "end_unix": end, "sampling_rate": sampling_rate,
                           "npts": npts, "seq_no": -1, "synthetic_zero": 1,
                           "gap_start_unix": start, "gap_end_unix": end, "recv_unix": now,
                           "quality": "D"})
        return npts

    def _open_for_write(self, path: Path, device_id: str, keys: dict[str, str]) -> tuple[h5py.File, bool]:
        """Return a writer file and whether it may remain open after a write."""
        existing = self._files.get(path)
        if existing is not None:
            return existing, True

        f = h5py.File(path, "a", libver="latest")
        self._initialize_h5(f, device_id, keys)
        f.flush()
        try:
            f.swmr_mode = True
        except RuntimeError:
            # HDF5 cannot upgrade an existing pre-SWMR superblock in place.
            # Closing this handle after each write preserves legacy portal
            # access instead of leaving the file permanently locked.
            self._legacy_paths.add(path)
            return f, False

        self._files[path] = f
        return f, True

    def close(self) -> None:
        """Flush and close persistent SWMR writer handles during shutdown."""
        with self._locks_guard:
            files = list(self._files.items())
            self._files.clear()
        for path, f in files:
            try:
                f.flush()
                f.close()
            except Exception:
                LOG.exception("failed to close HDF5 writer %s", path)

    def insert_packet(self, client: ClientInfo, packet: bytes, header: MSeedHeader, waveform: np.ndarray) -> InsertResult:
        device_id = self.device_id(client, header)
        path = self.db_path(device_id)
        keys = self._keys(header)
        with self._lock_for(path):
            cache = self._sha256_cache.setdefault(path, set())
            if header.sha256 in cache:
                return InsertResult(path, device_id, False, True, [])
            now, seq, stream = time.time(), get_sequence_number(packet), keys["stream_key"]
            messages: list[str] = []
            f, keep_open = self._open_for_write(path, device_id, keys)
            try:
                grp = f.require_group(stream)
                for k, v in keys.items():
                    grp.attrs[k] = v
                for k, v in {"last_seq": -1, "last_start": -1.0, "last_end": -1.0,
                             "last_sampling_rate": -1.0, "last_npts": -1, "last_sha256": "", "updated_unix": now}.items():
                    if k not in grp.attrs:
                        grp.attrs[k] = v
                # The dataset name is deterministic.  Check it before gap detection so
                # a retransmitted packet after a receiver restart neither gets stored
                # again nor creates a false discontinuity event.
                name = f"rec_{int(header.start_unix * 1_000_000_000):019d}_{seq:06d}_{header.sha256[:12]}"
                if name in grp:
                    cache.add(header.sha256)
                    return InsertResult(path, device_id, False, True, [])
                last_seq, last_start, last_end = int(grp.attrs["last_seq"]), float(grp.attrs["last_start"]), float(grp.attrs["last_end"])
                if last_seq >= 0:
                    expected_seq = (last_seq + 1) % 1_000_000
                    if seq != expected_seq:
                        self._gap(f, messages, stream, "sequence_gap", last_seq, seq, last_start, header.start_unix, last_end, -1.0, -1.0, now, f"Sequence discontinuity: prev={last_seq}, exp={expected_seq}, cur={seq}")
                    if header.sampling_rate and header.sampling_rate > 0 and last_end > 0:
                        delta = header.start_unix - last_end
                        tolerance = self.config.parser.time_gap_tolerance_samples / header.sampling_rate
                        if abs(delta) > tolerance:
                            kind = "time_gap" if delta > 0 else "time_overlap"
                            self._gap(f, messages, stream, kind, last_seq, seq, last_start, header.start_unix, last_end, last_end, delta, now, f"Time {'gap' if delta > 0 else 'overlap'}: delta={delta:.6f}s")
                            if delta > tolerance and header.sampling_rate > 0:
                                self._write_zero_gap(
                                    grp, last_end, header.start_unix, header.sampling_rate,
                                    np.asarray(waveform).dtype, {"chunks": True}, now, seq)
                # Sequence numbers wrap; use time + SHA as the persistent unique dataset name.
                options: dict[str, object] = {"chunks": True}
                if self.config.storage.hdf5_compression:
                    options["compression"] = self.config.storage.hdf5_compression
                    if self.config.storage.hdf5_compression == "gzip":
                        options["compression_opts"] = self.config.storage.hdf5_compression_opts
                dset = grp.create_dataset(name, data=np.asarray(waveform), **options)
                for key, value in {"start_unix": header.start_unix, "end_unix": header.end_unix if header.end_unix is not None else -1.0,
                    "seq_no": seq, "sha256": header.sha256, "packet_len": len(packet), "record_length": header.record_length,
                    "recv_unix": now, "client_ip": client.client_ip, "client_port": client.client_port, "server_port": client.server_port,
                    "network": header.network, "station": header.station, "location": header.location, "channel": header.channel,
                    "quality": header.quality, "sampling_rate": header.sampling_rate or 0.0, "npts": header.npts or len(waveform)}.items():
                    dset.attrs[key] = value
                # Preserve the exact incoming miniSEED record for faithful raw
                # export; waveform data above remains optimized for plotting.
                dset.attrs["raw_mseed"] = np.void(packet)
                if header.start_unix > last_start:
                    grp.attrs.update({"last_seq": seq, "last_start": header.start_unix, "last_end": header.end_unix if header.end_unix is not None else -1.0,
                        "last_sampling_rate": header.sampling_rate or 0.0, "last_npts": header.npts or len(waveform), "last_sha256": header.sha256, "updated_unix": now})
                f.flush()
            finally:
                if not keep_open:
                    f.close()
            cache.add(header.sha256)
        return InsertResult(path, device_id, True, False, messages)
