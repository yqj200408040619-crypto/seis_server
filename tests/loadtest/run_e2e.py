#!/usr/bin/env python3
"""One-shot end-to-end load test orchestrator.

Preconditions (must run in an environment WITH the project dependencies, e.g.
staging — NOT the INTEGRATIONS_ONLY sandbox where h5py/obspy/fastapi/bcrypt
cannot be installed):

    pip install -r mseed_tcp_server/requirements.txt
    pip install -r mseed_web_portal/requirements.txt

What it does:
  1. Verifies required modules import; if not, prints install hints and EXITS
     non-zero (it never pretends to pass).
  2. Generates miniSEED fixtures (gen_mseed.py) into a temp dir.
  3. Starts the TCP receiver and the FastAPI portal as subprocesses, pointed at
     a throwaway data directory, with small limits so effects show quickly.
  4. Runs the TCP load driver, waits for writes to land, then runs the portal
     login/export/mixed drivers.
  5. Tears everything down and prints where logs/data are.

This is intentionally a thin orchestrator: each driver is runnable on its own
against already-running services (see README).

Usage:
    python run_e2e.py                 # defaults
    python run_e2e.py --connections 600 --records 4000   # push harder
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
TCP_PKG = os.path.join(REPO, "mseed_tcp_server")
PORTAL_PKG = os.path.join(REPO, "mseed_web_portal")


def check_deps() -> list[str]:
    missing = []
    for mod, hint in [("h5py", "mseed_tcp_server/requirements.txt"),
                      ("numpy", "mseed_tcp_server/requirements.txt"),
                      ("obspy", "mseed_tcp_server/requirements.txt"),
                      ("fastapi", "mseed_web_portal/requirements.txt"),
                      ("uvicorn", "mseed_web_portal/requirements.txt"),
                      ("bcrypt", "mseed_web_portal/requirements.txt")]:
        try:
            __import__(mod)
        except ImportError:
            missing.append(f"{mod} (pip install -r {hint})")
    return missing


def wait_port(host: str, port: int, timeout: float) -> bool:
    import socket
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tcp-port", type=int, default=18000)
    ap.add_argument("--portal-port", type=int, default=8000)
    ap.add_argument("--stations", type=int, default=8)
    ap.add_argument("--channels", type=int, default=3)
    ap.add_argument("--records", type=int, default=2000)
    ap.add_argument("--connections", type=int, default=64)
    ap.add_argument("--keep", action="store_true", help="keep temp data dir on exit")
    args = ap.parse_args()

    missing = check_deps()
    if missing:
        print("ERROR: end-to-end load test requires the project dependencies, which are")
        print("missing in this environment. Run it in staging / a venv with:")
        for m in missing:
            print(f"  - {m}")
        print("\n(The INTEGRATIONS_ONLY sandbox cannot install these; that is expected.)")
        return 2

    work = tempfile.mkdtemp(prefix="seis_e2e_")
    fixtures = os.path.join(work, "fixtures")
    data_base = os.path.join(work, "data")
    logs = os.path.join(work, "logs")
    os.makedirs(data_base, exist_ok=True)
    os.makedirs(logs, exist_ok=True)
    print(f"work dir: {work}")

    # 1) fixtures
    rc = subprocess.call([sys.executable, os.path.join(HERE, "gen_mseed.py"),
                          "--out", fixtures, "--stations", str(args.stations),
                          "--channels", str(args.channels), "--records", str(args.records)])
    if rc != 0:
        print("fixture generation failed")
        return rc

    procs = []
    try:
        # 2) start receiver (writes HDF5 under data_base/devices)
        tcp_env = dict(os.environ, PYTHONPATH=TCP_PKG)
        tcp_log = open(os.path.join(logs, "receiver.log"), "wb")
        # The receiver reads an INI; we pass overrides via a tiny generated file.
        ini = os.path.join(work, "receiver.ini")
        with open(ini, "w") as fh:
            fh.write(f"[server]\nport={args.tcp_port}\nmax_clients=512\n"
                                 f"idle_no_record_sec=600\n"
                                 f"[storage]\nbase_dir={data_base}\n"
                                 f"log_dir={logs}\n"
                                 f"sha256_cache_max_per_stream=20000\ndevice_cache_ttl_sec=86400\n")
        procs.append(subprocess.Popen(
            [sys.executable, "-m", "mseed_tcp_server", "--config", ini],
            cwd=TCP_PKG, env=tcp_env, stdout=tcp_log, stderr=subprocess.STDOUT))
        if not wait_port("127.0.0.1", args.tcp_port, 20):
            print("ERROR: receiver did not open its port; see", tcp_log.name)
            return 3
        print(f"receiver up on :{args.tcp_port}")

        # 3) TCP load
        subprocess.call([sys.executable, os.path.join(HERE, "loadtest_tcp.py"),
                         "--fixtures", fixtures, "--port", str(args.tcp_port),
                         "--connections", str(args.connections)])
        time.sleep(3)  # let the write pipeline drain to HDF5

        # 4) start portal (reads the HDF5 the receiver wrote). The portal loads
        # its config from the file named by MSEED_WEB_CONFIG at import time, so
        # we must write a valid portal.ini pointing at this run's data dir.
        portal_ini = os.path.join(work, "portal.ini")
        app_db_path = os.path.join(data_base, "app.db")
        with open(portal_ini, "w") as fh:
            fh.write(
                f"[server]\nhost=127.0.0.1\nport={args.portal_port}\nworkers=1\n"
                f"[paths]\n"
                f"receiver_db_dir={os.path.join(data_base, 'devices')}\n"
                f"app_db={app_db_path}\n"
                f"log_dir={logs}\n"
                f"[security]\nsecret_key=e2e-loadtest-not-a-secret\nsession_max_age_seconds=86400\n"
            )
        portal_env = dict(os.environ, PYTHONPATH=PORTAL_PKG,
                          MSEED_WEB_CONFIG=portal_ini,
                          MSEED_MAX_CONCURRENT_EXPORTS="2",
                          MSEED_MAX_CONCURRENT_LOGINS=str(os.cpu_count() or 2))
        portal_log = open(os.path.join(logs, "portal.log"), "wb")
        procs.append(subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", str(args.portal_port), "--workers", "1"],
            cwd=PORTAL_PKG, env=portal_env, stdout=portal_log, stderr=subprocess.STDOUT))
        if not wait_port("127.0.0.1", args.portal_port, 30):
            print("ERROR: portal did not open its port; see", portal_log.name)
            return 4
        print(f"portal up on :{args.portal_port}")

        base = f"http://127.0.0.1:{args.portal_port}"
        # 5) portal drivers
        subprocess.call([sys.executable, os.path.join(HERE, "loadtest_portal.py"),
                         "--base", base, "--scenario", "login",
                         "--concurrency", "50", "--requests", "200"])
        subprocess.call([sys.executable, os.path.join(HERE, "loadtest_portal.py"),
                         "--base", base, "--scenario", "mixed",
                         "--concurrency", "50", "--requests", "200",
                         "--device-id", "1", "--start", "1704067200", "--end", "1704070800"])

        print("\nE2E run complete.")
        print(f"logs: {logs}")
        return 0
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        if args.keep:
            print(f"(kept work dir {work})")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
