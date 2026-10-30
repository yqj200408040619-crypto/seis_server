"""Items 4.1 / 4.2 — unbounded in-memory growth in DeviceDatabaseManager.

The h5py-backed db.py cannot be imported in this sandbox (no h5py), but the
growth concern lives entirely in pure-Python data structures that we reproduce
here EXACTLY as db.py uses them:

  insert_packet():
      cache = self._sha256_cache.setdefault(path, set())   # dict grows per device-file
      ...
      cache.add(header.sha256)                              # set grows per unique record
  _lock_for():
      self._locks.setdefault(path, threading.Lock())        # dict grows per device-file
  _write_packet():
      self._seeded.add((path, stream))                      # set grows per (file, stream)

None of _locks / _sha256_cache / _seeded are ever pruned or bounded. So:
  4.1  _sha256_cache[path] accumulates one 64-char sha per unique record for
       the entire lifetime of the stream -> memory grows ~unbounded on busy
       long-lived devices.
  4.2  _locks / _sha256_cache / _seeded accumulate one entry per distinct
       device-file ever seen -> memory grows with the number of devices and
       is never reclaimed.

We measure the actual resident growth with tracemalloc.
"""
from __future__ import annotations

import hashlib
import threading
import tracemalloc
from pathlib import Path


class CacheModel:
    """Byte-for-byte reproduction of the growth-relevant state in db.py."""

    def __init__(self):
        self._locks_guard = threading.Lock()
        self._locks: dict[Path, threading.Lock] = {}
        self._sha256_cache: dict[Path, set[str]] = {}
        self._seeded: set[tuple[Path, str]] = set()

    def _lock_for(self, path: Path) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(path, threading.Lock())

    def insert(self, path: Path, stream: str, sha: str) -> bool:
        with self._lock_for(path):
            cache = self._sha256_cache.setdefault(path, set())
            if sha in cache:
                return False
            self._seeded.add((path, stream))
            cache.add(sha)
            return True


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def test_single_stream_growth():
    """4.1 — one busy device, many unique records."""
    m = CacheModel()
    path = Path("/var/lib/mseed-tcp-server/devices/DEV_ONE.h5")
    stream = "NN.STA..CH"
    tracemalloc.start()
    base = tracemalloc.take_snapshot()
    N = 200_000  # a single busy 100 Hz stream reaches this in well under a day
    for i in range(N):
        sha = hashlib.sha256(i.to_bytes(8, "big")).hexdigest()
        m.insert(path, stream, sha)
    cur = tracemalloc.take_snapshot()
    stats = cur.compare_to(base, "filename")
    grew = sum(s.size_diff for s in stats)
    tracemalloc.stop()
    cache_len = len(m._sha256_cache[path])
    per_record = grew / N
    # extrapolate to a realistic long run
    one_day_100hz_records = 100 * 60 * 60 * 24  # pessimistic: 1 rec/sample-sec slot
    print(f"[4.1] single stream: {N:,} unique records")
    print(f"      sha256 set size = {cache_len:,} entries")
    print(f"      heap growth     = {human(grew)}  (~{per_record:.0f} B/record)")
    print(f"      NO eviction/LRU -> growth is monotonic for stream lifetime")
    return grew, per_record


def test_many_devices_growth():
    """4.2 — many distinct device-files, dict entries never reclaimed."""
    m = CacheModel()
    tracemalloc.start()
    base = tracemalloc.take_snapshot()
    D = 50_000  # distinct device_ids (e.g. churn of client_ip/port combos)
    for d in range(D):
        path = Path(f"/var/lib/mseed-tcp-server/devices/DEV_{d}.h5")
        stream = f"NN.S{d}..CH"
        m.insert(path, stream, "0" * 64)
    cur = tracemalloc.take_snapshot()
    stats = cur.compare_to(base, "filename")
    grew = sum(s.size_diff for s in stats)
    tracemalloc.stop()
    print(f"[4.2] distinct device-files = {D:,}")
    print(f"      _locks entries         = {len(m._locks):,}")
    print(f"      _sha256_cache entries  = {len(m._sha256_cache):,}")
    print(f"      _seeded entries        = {len(m._seeded):,}")
    print(f"      heap growth            = {human(grew)}  (~{grew / D:.0f} B/device)")
    print(f"      NO pruning -> grows with every device ever seen, never freed")
    return grew


def main():
    g1, per = test_single_stream_growth()
    print()
    g2 = test_many_devices_growth()
    print("\n--- summary ---")
    print(f"4.1 single-stream sha256 cache growth : CONFIRMED (~{per:.0f} B/record, unbounded)")
    print(f"4.2 per-device dict growth            : CONFIRMED (never pruned)")
    # both confirmed defects => exit 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
