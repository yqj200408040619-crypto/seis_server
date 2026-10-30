#!/usr/bin/env python3
"""Portal OOM regression — legacy rec_* metadata cache (needs h5py/numpy/obspy).

Root cause found in production: old receiver files store one HDF5 dataset per
record. device_summary()/list_components() read the attributes of every such
dataset on every dashboard or /api/devices request. On the 1.1 GB SS_02003
file (67k datasets) one call took ~2 min and ~250 MB, and overlapping calls
(each refresh adds one) multiplied that until the kernel OOM-killed the portal
(5 times between Aug and Oct).

data_reader now builds the per-stream legacy metadata once (single-flight) and
caches it, keyed on file inode + group member count. This test checks:
  1. cached results equal an uncached scan (count, last_start, one-hour count,
     waveform/export record selection);
  2. N concurrent callers trigger exactly ONE build per stream;
  3. adding a dataset to the group invalidates the cache.

Run with the portal interpreter, e.g.:
    /opt/mseed-web-portal/.venv/bin/python tests/loadtest/test_portal_legacy_cache.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.path.abspath(os.path.join(HERE, "..", "..", "mseed_web_portal"))


def main() -> int:
    try:
        import h5py
        import numpy as np
    except ImportError as exc:
        print(f"ERROR: needs h5py/numpy ({exc}); run with the portal venv. Not pretending to pass.")
        return 2
    os.environ.setdefault("MSEED_WEB_CONFIG", os.devnull)
    sys.path.insert(0, PORTAL)
    try:
        from app import data_reader as dr
    except ImportError as exc:
        print(f"ERROR: cannot import portal data_reader ({exc}). Not pretending to pass.")
        return 2

    work = tempfile.mkdtemp(prefix="portal_legacy_cache_")
    path = os.path.join(work, "127.0.0.1_18000_SS_TEST.h5")
    now = time.time()
    n = 3000
    with h5py.File(path, "w") as f:
        for comp in ("BHE", "BHN", "BHZ"):
            g = f.create_group(f"SS.TEST.00.{comp}")
            for i in range(n):
                d = g.create_dataset(f"rec_{i:06d}", data=np.arange(10, dtype=np.int32))
                s = now - 7200 + i
                d.attrs["start_unix"] = s
                d.attrs["end_unix"] = s + 0.5
                d.attrs["recv_unix"] = s
                d.attrs["sampling_rate"] = 20.0

    # Count builds by wrapping the builder.
    builds = {"n": 0}
    real_build = dr._build_legacy_meta

    def counting_build(grp):
        builds["n"] += 1
        time.sleep(0.2)  # widen the race window
        return real_build(grp)

    dr._build_legacy_meta = counting_build
    dr._LEGACY_CACHE.clear()

    # 1) equality vs uncached scan
    with h5py.File(path, "r", locking=False) as f:
        g = f["SS.TEST.00.BHZ"]
        expect_names = sorted(dr._scan_legacy_record_datasets(g))
        expect_last = max(float(g[x].attrs["start_unix"]) for x in expect_names)
        expect_hour = sum(1 for x in expect_names if float(g[x].attrs["recv_unix"]) >= now - 3600)
    summary = dr.device_summary(path, None)
    comp = next(c for c in summary["components"] if c["component"] == "BHZ")
    eq_count = comp["packets"] == len(expect_names) == n
    eq_last = abs(comp["last_start"] - expect_last) < 1e-6
    eq_hour = summary["one_hour_packets"] == 3 * expect_hour
    with h5py.File(path, "r", locking=False) as f:
        got = list(dr._iter_stream_records(f["SS.TEST.00.BHZ"], "SS.TEST.00.BHZ",
                                           now - 7200 + 100, now - 7200 + 149, 10_000))
    eq_window = len(got) == 50 and abs(got[0][2]["start_unix"] - (now - 7200 + 100)) < 1e-6
    print(f"[1] equality: count={eq_count} last_start={eq_last} one_hour={eq_hour} window={eq_window}")

    # 2) single-flight under concurrency
    dr._LEGACY_CACHE.clear(); builds["n"] = 0
    ts = [threading.Thread(target=dr.device_summary, args=(path, None)) for _ in range(16)]
    [t.start() for t in ts]; [t.join() for t in ts]
    single = builds["n"] == 3  # one build per stream, not 16 x 3
    print(f"[2] 16 concurrent summaries -> builds={builds['n']} (expect 3) single_flight={single}")

    # 3) invalidation when the group gains a dataset
    builds["n"] = 0
    with h5py.File(path, "a") as f:
        d = f["SS.TEST.00.BHZ"].create_dataset("rec_999999", data=np.arange(3, dtype=np.int32))
        d.attrs["start_unix"] = now; d.attrs["end_unix"] = now + 0.5; d.attrs["recv_unix"] = now
    s2 = dr.device_summary(path, None)
    c2 = next(c for c in s2["components"] if c["component"] == "BHZ")
    invalidated = c2["packets"] == n + 1 and builds["n"] == 1
    print(f"[3] after adding a dataset: packets={c2['packets']} rebuilds={builds['n']} invalidated={invalidated}")

    dr._build_legacy_meta = real_build
    import shutil
    shutil.rmtree(work, ignore_errors=True)
    ok = eq_count and eq_last and eq_hour and eq_window and single and invalidated
    print(f"\nportal legacy-metadata cache: {'VERIFIED' if ok else 'FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
