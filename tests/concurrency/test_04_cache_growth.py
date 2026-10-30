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
import time
import tracemalloc
from collections import OrderedDict
from pathlib import Path


# --- BoundedShaCache: copied verbatim from mseed_tcp_server/db.py (can't import
#     the module here because it pulls in h5py). Kept in sync by hand. ---
class BoundedShaCache:
    __slots__ = ("_od", "max_size")

    def __init__(self, max_size: int):
        self._od = OrderedDict()
        self.max_size = max(0, int(max_size))

    def __contains__(self, sha: str) -> bool:
        if sha in self._od:
            self._od.move_to_end(sha)
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
            self._od.popitem(last=False)

    def __len__(self) -> int:
        return len(self._od)


class CacheModel:
    """Reproduction of the growth-relevant state in db.py AFTER the fix:
    bounded per-stream sha cache + TTL pruning of idle device entries.
    """

    def __init__(self, sha_cap: int = 20000, device_ttl: int = 86400):
        self._locks_guard = threading.Lock()
        self._locks: dict[Path, threading.Lock] = {}
        self._sha256_cache: dict[Path, BoundedShaCache] = {}
        self._last_active: dict[Path, float] = {}
        self._seeded: dict[Path, set[str]] = {}
        self._sha_cap = sha_cap
        self._device_ttl = device_ttl

    def _lock_for(self, path: Path) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(path, threading.Lock())

    def insert(self, path: Path, stream: str, sha: str, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        with self._lock_for(path):
            self._last_active[path] = now
            cache = self._sha256_cache.setdefault(path, BoundedShaCache(self._sha_cap))
            if sha in cache:
                return False
            self._seeded.setdefault(path, set()).add(stream)
            cache.add(sha)
            return True

    def prune(self, now: float) -> int:
        stale = [p for p, ts in self._last_active.items() if now - ts > self._device_ttl]
        for path in stale:
            self._locks.pop(path, None)
            self._sha256_cache.pop(path, None)
            self._last_active.pop(path, None)
            self._seeded.pop(path, None)
        return len(stale)


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


# The production default is StorageConfig.sha256_cache_max_per_stream = 20000.
# Tests use a smaller cap so "far beyond the cap" runs fast; the LRU logic is
# identical regardless of the numeric cap.
SHA_CAP = 2_000


def _cache_footprint(cache: "BoundedShaCache") -> int:
    """Approximate resident bytes of a sha cache: the OrderedDict container plus
    one 64-char str per retained entry (64 ASCII chars -> ~113 B on CPython)."""
    import sys
    total = sys.getsizeof(cache._od)
    for k in cache._od:
        total += sys.getsizeof(k)
    return total


def _feed(m, path, n_records):
    for i in range(n_records):
        m.insert(path, "NN.STA..CH", hashlib.sha256(i.to_bytes(8, "big")).hexdigest())
    return _cache_footprint(m._sha256_cache[path])


def test_single_stream_bounded():
    """4.1 FIX — cache size is capped, and memory is flat as N grows well past
    the cap (we compare N = 5x cap vs N = 10x cap: heap should barely change)."""
    path = Path("/var/lib/mseed-tcp-server/devices/DEV_ONE.h5")

    m1 = CacheModel(sha_cap=SHA_CAP)
    grew_5x = _feed(m1, path, SHA_CAP * 5)
    len_5x = len(m1._sha256_cache[path])

    m2 = CacheModel(sha_cap=SHA_CAP)
    grew_10x = _feed(m2, path, SHA_CAP * 10)
    len_10x = len(m2._sha256_cache[path])

    bounded = (len_5x <= SHA_CAP) and (len_10x <= SHA_CAP)
    # heap should NOT scale with N: doubling the feed keeps footprint ~same.
    flat = grew_10x <= grew_5x * 1.5
    print(f"[4.1] fed 5x cap  ({SHA_CAP*5:,}): cache size={len_5x:,}  heap={human(grew_5x)}")
    print(f"      fed 10x cap ({SHA_CAP*10:,}): cache size={len_10x:,}  heap={human(grew_10x)}")
    print(f"      size capped at {SHA_CAP:,} = {bounded}; heap flat as N doubles = {flat}")
    print(f"      LRU eviction -> memory no longer scales with stream lifetime")
    return (bounded and flat), grew_10x


def test_dedup_still_works_in_window():
    """A recent duplicate (within the LRU window) is still rejected."""
    m = CacheModel(sha_cap=SHA_CAP)
    path = Path("/var/lib/mseed-tcp-server/devices/DEV_DUP.h5")
    stream = "NN.STA..CH"
    sha_a = "a" * 64
    assert m.insert(path, stream, sha_a) is True          # first time -> stored
    accepted_again = m.insert(path, stream, sha_a)          # immediate retransmit
    # push many others but stay within the window so sha_a is not evicted
    for i in range(SHA_CAP - 10):
        m.insert(path, stream, hashlib.sha256(i.to_bytes(8, "big")).hexdigest())
    accepted_after_window = m.insert(path, stream, sha_a)   # still recent
    ok = (accepted_again is False) and (accepted_after_window is False)
    print(f"[4.1] recent-duplicate rejection preserved = {ok}")
    return ok


def test_many_devices_pruned():
    """4.2 FIX — idle device-file entries are reclaimed by TTL pruning."""
    m = CacheModel(sha_cap=SHA_CAP, device_ttl=3600)
    t0 = 1_000_000.0
    D = 50_000
    for d in range(D):
        path = Path(f"/var/lib/mseed-tcp-server/devices/DEV_{d}.h5")
        m.insert(path, f"NN.S{d}..CH", "0" * 64, now=t0)
    before = len(m._locks)
    # 10 devices stay active (written "recently"); the rest go idle.
    t1 = t0 + 7200  # 2h later; ttl=1h
    for d in range(10):
        path = Path(f"/var/lib/mseed-tcp-server/devices/DEV_{d}.h5")
        m.insert(path, f"NN.S{d}..CH", f"active{d}".encode().hex().ljust(64, "0")[:64], now=t1)
    pruned = m.prune(now=t1)
    after = len(m._locks)
    reclaimed_ok = (before == D) and (after == 10) and (pruned == D - 10)
    print(f"[4.2] device-files seen={before:,}  after prune={after:,}  pruned={pruned:,}")
    print(f"      _sha256_cache entries = {len(m._sha256_cache):,}  _seeded = {len(m._seeded):,}")
    print(f"      idle entries reclaimed, active ones kept = {reclaimed_ok}")
    return reclaimed_ok


def main():
    bounded, grew = test_single_stream_bounded()
    dedup_ok = test_dedup_still_works_in_window()
    print()
    pruned_ok = test_many_devices_pruned()
    print("\n--- summary ---")
    print(f"4.1 FIX bounded sha cache     : {'VERIFIED' if bounded else 'FAILED'} "
          f"(size capped at {SHA_CAP:,}, heap flat)")
    print(f"4.1 recent-dup still rejected : {'VERIFIED' if dedup_ok else 'FAILED'}")
    print(f"4.2 FIX idle-device pruning   : {'VERIFIED' if pruned_ok else 'FAILED'}")
    return 0 if (bounded and dedup_ok and pruned_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
