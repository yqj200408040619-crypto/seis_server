#!/usr/bin/env python3
"""Concurrent TCP load driver for the miniSEED receiver.

Opens many simultaneous connections and streams the generated .mseed fixtures,
one connection per file (so each maps to a distinct device). Exercises checklist
items 1.x (connection concurrency / reaper), 2.x (write pipeline backpressure)
and, by producing large HDF5 files, sets up 3.x.

Only the Python standard library is used here; no project deps needed to RUN
the driver (the receiver it talks to does need its deps).

Usage:
    python loadtest_tcp.py --fixtures /tmp/mseed_fixtures \\
        --host 127.0.0.1 --port 18000 --connections 64 --chunk 1500 --rate-mb 0
"""
from __future__ import annotations

import argparse
import glob
import os
import socket
import threading
import time


def send_file(path: str, host: str, port: int, chunk: int, inter_chunk_delay: float,
              stats: dict, lock: threading.Lock) -> None:
    data = open(path, "rb").read()
    sent = 0
    t0 = time.time()
    try:
        with socket.create_connection((host, port), timeout=15) as s:
            for i in range(0, len(data), chunk):
                s.sendall(data[i:i + chunk])
                sent += min(chunk, len(data) - i)
                if inter_chunk_delay:
                    time.sleep(inter_chunk_delay)
        ok = True
        err = ""
    except Exception as exc:  # noqa: BLE001
        ok = False
        err = f"{type(exc).__name__}: {exc}"
    dt = time.time() - t0
    with lock:
        stats["files"] += 1
        stats["bytes"] += sent
        stats["time"] = max(stats["time"], dt)
        if ok:
            stats["ok"] += 1
        else:
            stats["failed"] += 1
            stats["errors"].append((os.path.basename(path), err))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fixtures", required=True, help="dir of .mseed files from gen_mseed.py")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=18000)
    ap.add_argument("--connections", type=int, default=64, help="max concurrent connections")
    ap.add_argument("--chunk", type=int, default=1500, help="TCP send chunk size (bytes)")
    ap.add_argument("--inter-chunk-delay", type=float, default=0.0,
                    help="seconds between chunks (simulate slow/real-time feeds)")
    ap.add_argument("--repeat", type=int, default=1, help="send each fixture N times")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.fixtures, "*.mseed"))) * args.repeat
    if not files:
        print(f"ERROR: no .mseed files in {args.fixtures}; run gen_mseed.py first")
        return 2

    stats = {"files": 0, "bytes": 0, "ok": 0, "failed": 0, "time": 0.0, "errors": []}
    lock = threading.Lock()
    sem = threading.Semaphore(args.connections)
    threads: list[threading.Thread] = []

    def worker(p):
        with sem:
            send_file(p, args.host, args.port, args.chunk, args.inter_chunk_delay, stats, lock)

    print(f"streaming {len(files)} fixtures to {args.host}:{args.port} "
          f"(<= {args.connections} concurrent connections)")
    t_start = time.time()
    for p in files:
        t = threading.Thread(target=worker, args=(p,), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    elapsed = time.time() - t_start

    mb = stats["bytes"] / 1e6
    print("\n=== TCP load results ===")
    print(f"connections cap   : {args.connections}")
    print(f"files sent        : {stats['files']}  ok={stats['ok']} failed={stats['failed']}")
    print(f"bytes sent        : {mb:.1f} MB")
    print(f"wall time         : {elapsed:.1f}s   throughput ~ {mb/max(elapsed,1e-9):.1f} MB/s")
    if stats["errors"]:
        print(f"errors ({len(stats['errors'])}): showing first 5")
        for name, err in stats["errors"][:5]:
            print(f"  {name}: {err}")
    # Some refusals are EXPECTED when connections > receiver max_clients (that
    # is checklist item 1.1 in action), so failures are reported, not fatal.
    print("\nNOTE: connection refusals above the receiver's max_clients are expected (item 1.1).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
