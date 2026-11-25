#!/usr/bin/env python3
"""Concurrent load driver for the web portal (checklist 5.x).

Three scenarios, each measuring latency distribution and errors:

  --scenario login    : login flood -> exercises 5.2 (bcrypt + throttle + gate).
                        Expect HTTP 429/503 once the throttle/gate engage.
  --scenario export   : concurrent large /export/download -> exercises 5.1
                        (streaming + admission gate). Expect some HTTP 503 when
                        concurrency exceeds the export gate; successful ones
                        should stream without exhausting memory.
  --scenario waveform : concurrent /api/waveform big windows -> 5.3/5.4 load.
  --scenario mixed    : a few slow exports in parallel with many cheap page
                        hits -> shows whether cheap requests still respond
                        (validates that the gate/throttle protect the pool).

Standard library only. Point it at a RUNNING portal; it does not start one.

Usage:
    python loadtest_portal.py --base http://127.0.0.1:8000 \\
        --scenario login --concurrency 50 --requests 200 \\
        --username admin --password wrong-password
"""
from __future__ import annotations

import argparse
import http.client
import statistics
import threading
import time
import urllib.parse
from urllib.parse import urlparse


def _conn(base: str) -> http.client.HTTPConnection:
    u = urlparse(base)
    if u.scheme == "https":
        return http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=60)
    return http.client.HTTPConnection(u.hostname, u.port or 80, timeout=60)


def _request(base, method, path, body=None, headers=None):
    c = _conn(base)
    t0 = time.time()
    try:
        c.request(method, path, body=body, headers=headers or {})
        resp = c.getresponse()
        # Drain body so the connection/thread is fully released; count bytes.
        n = 0
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            n += len(chunk)
        return resp.status, n, time.time() - t0, ""
    except Exception as exc:  # noqa: BLE001
        return 0, 0, time.time() - t0, f"{type(exc).__name__}: {exc}"
    finally:
        c.close()


def run_scenario(make_request, concurrency, total):
    results = []
    lock = threading.Lock()
    sem = threading.Semaphore(concurrency)
    counter = {"i": 0}

    def worker():
        with sem:
            r = make_request()
            with lock:
                results.append(r)

    threads = []
    t_start = time.time()
    for _ in range(total):
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    wall = time.time() - t_start
    return results, wall


def summarize(name, results, wall):
    statuses = {}
    lat = []
    bytes_total = 0
    errs = []
    for status, nbytes, dt, err in results:
        statuses[status] = statuses.get(status, 0) + 1
        lat.append(dt)
        bytes_total += nbytes
        if err:
            errs.append(err)
    lat.sort()

    def pct(p):
        if not lat:
            return 0.0
        return lat[min(len(lat) - 1, int(len(lat) * p))]

    print(f"\n=== portal load: {name} ===")
    print(f"requests          : {len(results)}  wall={wall:.1f}s  "
          f"rps~{len(results)/max(wall,1e-9):.1f}")
    print(f"status codes      : {dict(sorted(statuses.items()))}")
    print(f"data received     : {bytes_total/1e6:.1f} MB")
    if lat:
        print(f"latency ms        : p50={pct(0.5)*1000:.0f} p90={pct(0.9)*1000:.0f} "
              f"p99={pct(0.99)*1000:.0f} max={max(lat)*1000:.0f}")
    if errs:
        print(f"transport errors  : {len(errs)} (first: {errs[0]})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--scenario", choices=["login", "export", "waveform", "mixed"], required=True)
    ap.add_argument("--concurrency", type=int, default=50)
    ap.add_argument("--requests", type=int, default=200)
    ap.add_argument("--username", default="admin")
    ap.add_argument("--password", default="wrong-password")
    ap.add_argument("--device-id", type=int, default=1)
    ap.add_argument("--start", default="", help="export/waveform start (unix or ISO)")
    ap.add_argument("--end", default="", help="export/waveform end (unix or ISO)")
    args = ap.parse_args()

    if args.scenario == "login":
        form = urllib.parse.urlencode({"username": args.username, "password": args.password})
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        make = lambda: _request(args.base, "POST", "/login", form, headers)  # noqa: E731
        results, wall = run_scenario(make, args.concurrency, args.requests)
        summarize("login flood (expect 401 then 429/503)", results, wall)

    elif args.scenario == "export":
        qs = urllib.parse.urlencode({"device_id": args.device_id, "start": args.start, "end": args.end})
        make = lambda: _request(args.base, "GET", f"/export/download?{qs}")  # noqa: E731
        results, wall = run_scenario(make, args.concurrency, args.requests)
        summarize("concurrent large exports (expect some 503 from the gate)", results, wall)

    elif args.scenario == "waveform":
        qs = urllib.parse.urlencode({"device_id": args.device_id, "start": args.start,
                                     "end": args.end, "max_points": 4000})
        make = lambda: _request(args.base, "GET", f"/api/waveform?{qs}")  # noqa: E731
        results, wall = run_scenario(make, args.concurrency, args.requests)
        summarize("concurrent waveform queries", results, wall)

    else:  # mixed
        export_qs = urllib.parse.urlencode({"device_id": args.device_id, "start": args.start, "end": args.end})
        exports = []
        for _ in range(min(5, args.concurrency)):
            t = threading.Thread(
                target=lambda: exports.append(_request(args.base, "GET", f"/export/download?{export_qs}")),
                daemon=True)
            t.start()
        time.sleep(0.2)  # let slow exports occupy the pool
        make = lambda: _request(args.base, "GET", "/login")  # cheap page  # noqa: E731
        results, wall = run_scenario(make, args.concurrency, args.requests)
        summarize("cheap requests while 5 exports run (should stay responsive)", results, wall)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
