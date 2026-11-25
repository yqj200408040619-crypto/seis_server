from __future__ import annotations

from collections import OrderedDict
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


class BoundedShaCache:
    """An LRU set of sha256 strings with an optional size cap.

    The receiver only needs to dedup the *recent* retransmits that follow a
    reconnect/restart, not a stream's entire history, so the full-history set
    that this replaces grew without bound (~155 B per unique record). This keeps
    at most ``max_size`` most-recently-touched hashes; older ones are evicted.
    ``max_size == 0`` disables the bound (keeps every entry, legacy behaviour).
    All access is under the owning per-file lock, so no internal lock is needed.
    """

    __slots__ = ("_od", "max_size")

    def __init__(self, max_size: int):
        self._od: "OrderedDict[str, None]" = OrderedDict()
        self.max_size = max(0, int(max_size))

    def __contains__(self, sha: str) -> bool:
        if sha in self._od:
            self._od.move_to_end(sha)  # refresh recency on hit
            return True
        return False

    def add(self, sha: str) -> None:
        if not sha:
            return
        if sha in self._od:
            self._od.move_to_end(sha)
            return
        self._od[sha] = None
        if self.max_size and len(self._od) > self.max_size:
            self._od.popitem(last=False)  # evict oldest

    def __len__(self) -> int:
        return len(self._od)


class DeviceDatabaseManager:
    """One HDF5 file per MiniSEED device, compatible with mseed-web-portal."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.h5_root = config.storage.base_dir / config.storage.db_dir_name
        self.h5_root.mkdir(parents=True, exist_ok=True)
        self._locks_guard = threading.Lock()
        self._locks: dict[Path, threading.Lock] = {}
        self._sha256_cache: dict[Path, BoundedShaCache] = {}
        # Last time each device-file was written, used to prune idle entries so
        # the maps below do not grow with every device ever seen.
        self._last_active: dict[Path, float] = {}
        self._sha_cap = int(config.storage.sha256_cache_max_per_stream)
        self._device_ttl = int(config.storage.device_cache_ttl_sec)
        self._last_prune = time.time()
        # Files are opened in plain append mode per write and closed again
        # immediately (see _open_for_write). SWMR write mode is intentionally
        # NOT used: the receiver mutates file structure (new groups, attrs and
        # a dataset per record) on nearly every packet, which SWMR forbids and
        # which previously corrupted handles and left stuck consistency flags.
        # _files stays empty under normal operation; close()/_evict_handle keep
        # it only as a safety net for any stray cached handle.
        self._files: dict[Path, h5py.File] = {}
        # Tracks, per device-file, which stream keys have had their sha256 cache
        # seeded from the on-disk rolling index, so we only pay that scan once
        # per stream. Keyed by path so pruning a device is O(1), not O(all
        # streams ever seen).
        self._seeded: dict[Path, set[str]] = {}

    def _lock_for(self, path: Path) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(path, threading.Lock())

    def _prune_idle_devices(self, now: float) -> None:
        """Drop in-memory lock/cache/seeded entries for long-idle device files.

        Without this, _locks / _sha256_cache / _seeded / _last_active grow
        monotonically with the number of distinct device files ever seen (e.g.
        client_ip/port churn) and are never reclaimed. Throttled so the scan
        runs at most once a minute, never on the per-packet hot path in full.
        Only prunes a file whose lock is not currently held, so an in-flight
        write is never disturbed; a pruned device simply reseeds on its next
        packet. Must NOT be called while holding a per-file lock.
        """
        ttl = self._device_ttl
        if not ttl:
            return
        if now - self._last_prune < 60.0:
            return
        with self._locks_guard:
            self._last_prune = now
            stale = [p for p, ts in self._last_active.items() if now - ts > ttl]
            for path in stale:
                lock = self._locks.get(path)
                # Skip if a write currently holds this file's lock.
                if lock is not None and not lock.acquire(blocking=False):
                    continue
                try:
                    self._locks.pop(path, None)
                    self._sha256_cache.pop(path, None)
                    self._last_active.pop(path, None)
                    self._seeded.pop(path, None)
                finally:
                    if lock is not None:
                        lock.release()
            if stale:
                LOG.info("pruned %d idle device cache entries (ttl=%ss)", len(stale), ttl)

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
        """Append one synthetic zero-valued span covering a time gap.

        Stored as a normal record row in the rolling ``index`` with
        ``synthetic_zero=1`` so the reader can treat it like any other segment.
        """
        npts = int(round((end - start) * sampling_rate))
        if npts <= 0:
            return 0
        zeros = np.zeros(npts, dtype=dtype)
        sample_offset = self._extend(grp["samples"], zeros)
        index = grp["index"]
        row = int(index.shape[0])
        index.resize(row + 1, axis=0)
        index[row] = (
            start, end, now, -1, sampling_rate, npts,
            sample_offset, 0, 0, 0, 0,
            b"", b"D", 1,
        )
        return npts

    # Index dtype for the rolling per-stream record index.  One row per stored
    # record.  ``sample_offset``/``npts`` point into the stream's ``samples``
    # array; ``raw_offset``/``raw_len`` point into ``raw_blob``.  Keeping the
    # waveform in a few big arrays (instead of one dataset per record) keeps the
    # number of HDF5 objects ~constant, which is what makes huge files fast.
    INDEX_DTYPE = np.dtype([
        ("start_unix", "f8"), ("end_unix", "f8"), ("recv_unix", "f8"),
        ("seq_no", "i8"), ("sampling_rate", "f8"), ("npts", "i8"),
        ("sample_offset", "i8"), ("raw_offset", "i8"), ("raw_len", "i8"),
        ("packet_len", "i8"), ("record_length", "i8"),
        ("sha256", "S64"), ("quality", "S4"), ("synthetic_zero", "i1"),
    ])

    def _stream_options(self) -> dict[str, object]:
        options: dict[str, object] = {"chunks": True}
        if self.config.storage.hdf5_compression:
            options["compression"] = self.config.storage.hdf5_compression
            if self.config.storage.hdf5_compression == "gzip":
                options["compression_opts"] = self.config.storage.hdf5_compression_opts
        return options

    def _ensure_stream_arrays(self, grp: h5py.Group, sample_dtype: np.dtype) -> None:
        """Create the rolling ``samples``/``raw_blob``/``index`` arrays once.

        ``grp.attrs['layout'] == 2`` marks the new rolling-array format so the
        portal reader can distinguish it from the legacy ``rec_*``
        one-dataset-per-record layout (both remain readable).
        """
        if grp.attrs.get("layout", 0) == 2 and "index" in grp:
            return
        opts = self._stream_options()
        if "samples" not in grp:
            grp.create_dataset("samples", shape=(0,), maxshape=(None,),
                               dtype=sample_dtype, **opts)
        if "raw_blob" not in grp:
            grp.create_dataset("raw_blob", shape=(0,), maxshape=(None,),
                               dtype=np.uint8, **opts)
        if "index" not in grp:
            grp.create_dataset("index", shape=(0,), maxshape=(None,),
                               dtype=self.INDEX_DTYPE, chunks=True)
        grp.attrs["layout"] = 2

    @staticmethod
    def _extend(dset: h5py.Dataset, data: np.ndarray) -> int:
        """Append ``data`` to a 1-D extensible dataset; return the start offset."""
        offset = int(dset.shape[0])
        dset.resize(offset + len(data), axis=0)
        if len(data):
            dset[offset:] = data
        return offset

    def _append_record(self, grp: h5py.Group, waveform: np.ndarray, packet: bytes,
                        header: MSeedHeader, seq: int, now: float,
                        synthetic_zero: int = 0) -> None:
        wf = np.asarray(waveform)
        sample_offset = self._extend(grp["samples"], wf)
        raw_arr = np.frombuffer(packet, dtype=np.uint8) if packet else np.empty(0, np.uint8)
        raw_offset = self._extend(grp["raw_blob"], raw_arr)
        index = grp["index"]
        row = int(index.shape[0])
        index.resize(row + 1, axis=0)
        index[row] = (
            header.start_unix,
            header.end_unix if header.end_unix is not None else -1.0,
            now, seq, header.sampling_rate or 0.0,
            int(header.npts or len(wf)),
            sample_offset, raw_offset, len(raw_arr),
            len(packet), header.record_length,
            header.sha256.encode("ascii", "replace")[:64],
            (header.quality or "").encode("ascii", "replace")[:4],
            int(synthetic_zero),
        )

    def _open_for_write(self, path: Path, device_id: str, keys: dict[str, str]) -> tuple[h5py.File, bool]:
        """Open the device file for a single write and always close afterwards.

        The receiver mutates file structure on essentially every packet: it may
        create new stream groups, add/update group attributes and create a new
        dataset per record. HDF5 SWMR *write* mode forbids all of these metadata
        changes after it is enabled ("Parent entry isn't pinned or protected"),
        which corrupts the handle, makes close() fail and leaves a stuck
        "open for SWMR write" consistency flag on disk that blocks every later
        open. We therefore use plain append mode and close after each write:
        structure changes are always legal and the SWMR flag is never set.
        Readers (the portal) open independently in SWMR-read mode.
        """
        f = h5py.File(path, "a", libver="latest")
        self._initialize_h5(f, device_id, keys)
        return f, False

    def _evict_handle(self, path: Path) -> None:
        """Drop and close a cached SWMR writer handle.

        After a write/flush error the HDF5 handle can be left in an
        inconsistent state (e.g. "slist already enabled"). If it stays in
        ``self._files`` every subsequent packet for the device reuses the same
        broken handle and fails forever. Removing it here forces the next
        packet to reopen the file from disk, which recovers the stream.
        Must be called while holding ``self._lock_for(path)``.
        """
        with self._locks_guard:
            f = self._files.pop(path, None)
        if f is None:
            return
        try:
            f.close()
        except Exception:
            LOG.exception("failed to close broken HDF5 writer %s", path)

    def close(self) -> None:
        """Flush and close any stray writer handles at shutdown (normally none)."""
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
        # Opportunistically reclaim memory for devices that have gone idle.
        # Throttled internally; safe to call outside the per-file lock.
        self._prune_idle_devices(time.time())
        with self._lock_for(path):
            self._last_active[path] = time.time()
            cache = self._sha256_cache.setdefault(path, BoundedShaCache(self._sha_cap))
            if header.sha256 in cache:
                return InsertResult(path, device_id, False, True, [])
            try:
                return self._write_packet(client, packet, header, waveform, device_id, path, keys, cache)
            except Exception:
                # A write failure can leave an HDF5 handle in a broken state.
                # Evict any stray handle so a fresh file is opened, then retry
                # once. Only if the retry also fails does the caller quarantine
                # the packet, so a single transient fault no longer permanently
                # stalls the device's stream.
                LOG.warning("HDF5 write failed for %s; evicting handle and retrying once", path)
                self._evict_handle(path)
                return self._write_packet(client, packet, header, waveform, device_id, path, keys, cache)

    def _write_packet(self, client: ClientInfo, packet: bytes, header: MSeedHeader, waveform: np.ndarray,
                       device_id: str, path: Path, keys: dict[str, str], cache: set[str]) -> InsertResult:
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
            # Create the rolling arrays up front, before any gap-fill or record
            # append touches them.  _write_zero_gap and _append_record both index
            # grp["samples"]/["index"], so the arrays must exist first; otherwise
            # a time gap on the very first packet to a group (or any legacy rec_*
            # group being upgraded) raises KeyError: 'samples' doesn't exist.
            self._ensure_stream_arrays(grp, np.asarray(waveform).dtype)
            # The dataset name is deterministic.  Check it before gap detection so
            # a retransmitted packet after a receiver restart neither gets stored
            # again nor creates a false discontinuity event.
            # Duplicate detection now uses the per-stream sha256 cache instead
            # of probing for a dataset name.  Seed the cache from the rolling
            # index on first touch so retransmits after a receiver restart are
            # still recognised and neither re-stored nor flagged as gaps.
            if "index" in grp and stream not in self._seeded.get(path, ()):
                try:
                    # Only seed the most recent entries. Dedup exists to catch
                    # retransmits right after a reconnect, so a bounded recent
                    # window is sufficient; reading the whole history here would
                    # defeat the bounded cache and reload megabytes on first
                    # touch of a long-lived stream.
                    sha_ds = grp["index"]["sha256"]
                    n = len(sha_ds)
                    seed_n = n if self._sha_cap <= 0 else min(n, self._sha_cap)
                    shas = sha_ds[n - seed_n:] if seed_n else sha_ds[:0]
                    for s in shas:
                        sv = s.decode("ascii", "replace").rstrip("\x00") if isinstance(s, (bytes, np.bytes_)) else str(s)
                        if sv:
                            cache.add(sv)
                except Exception:
                    pass
                self._seeded.setdefault(path, set()).add(stream)
            if header.sha256 in cache:
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
            # Rolling-array layout: append waveform + raw bytes + one index row,
            # instead of creating a dataset per record (which exploded the HDF5
            # object count on long-lived streams and slowed every open/scan).
            # Arrays were already ensured right after require_group above.
            self._append_record(grp, waveform, packet, header, seq, now)
            if header.start_unix > last_start:
                grp.attrs.update({"last_seq": seq, "last_start": header.start_unix, "last_end": header.end_unix if header.end_unix is not None else -1.0,
                    "last_sampling_rate": header.sampling_rate or 0.0, "last_npts": header.npts or len(waveform), "last_sha256": header.sha256, "updated_unix": now})
            f.flush()
        finally:
            if not keep_open:
                f.close()
        cache.add(header.sha256)
        return InsertResult(path, device_id, True, False, messages)
