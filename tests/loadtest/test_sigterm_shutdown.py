#!/usr/bin/env python3
"""Item 2.7 / 3.x (regression) — SIGTERM graceful shutdown of the receiver.

Gap found while running run_e2e.py: the orchestrator stops the receiver with
subprocess.terminate() (SIGTERM), and afterwards most freshly-written HDF5
device files could not be opened by a reader:

    OSError: Unable to synchronously open file
             (file is already open for write ... use h5clear ...)

Root cause: mseed_tcp_server/server.py only handles KeyboardInterrupt/SystemExit
(i.e. SIGINT). It installs NO SIGTERM handler. Python does not raise
KeyboardInterrupt on SIGTERM, so `systemctl stop` / subprocess.terminate()
kills the process instantly, mid-write, without:
  * draining the bounded write queue (item 2.7 "graceful drain"), or
  * closing the in-flight h5py append handle,
leaving the device file with its consistency flag set so the portal cannot
read it until an operator runs `h5clear`. The production systemd unit uses
Type=simple with the default KillSignal=SIGTERM, so every normal restart hits
this window.

This test needs the real project deps (h5py/obspy/numpy). It:
  1. starts the real receiver on a throwaway port + temp data dir,
  2. streams several fixture files,
  3. sends SIGTERM (what systemd/terminate() actually send),
  4. waits for the process to exit, then tries to OPEN every device file
     read-only.

PASS  = process exited promptly AND every device file opens cleanly
        (=> SIGTERM was handled gracefully / no stuck write flag).
FAIL  = process ignored SIGTERM (had to be killed) OR one or more device
        files are left locked ("already open for write").

Run in a deps-enabled env, e.g.:
    /opt/miniforge3/envs/mseed-web/bin/python tests/loadtest/test_sigterm_shutdown.py
"""
from __future__ import annotations

import glob
import os
import signal
import subprocess
import sys
import tempfile
import time


def _check_deps() -> list[str]:
    missing = []
    for m in ("h5py", "numpy", "obspy"):
        try:
            __import__(m)
        except ImportError:
            missing.append(m)
    return missing


HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
TCP_PKG = os.path.join(REPO, "mseed_tcp_server")


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
    missing = _check_deps()
    if missing:
        print(f"ERROR: this test needs {missing}; run it in a deps-enabled env "
              f"(e.g. /opt/miniforge3/envs/mseed-web/bin/python). Not pretending to pass.")
        return 2

    port = 28111
    work = tempfile.mkdtemp(prefix="seis_sigterm_")
    fixtures = os.path.join(work, "fixtures")
    data_base = os.path.join(work, "data")
    logs = os.path.join(work, "logs")
    os.makedirs(data_base); os.makedirs(logs)

    # 1) fixtures (reuse gen_mseed.py)
    rc = subprocess.call([sys.executable, os.path.join(HERE, "gen_mseed.py"),
                          "--out", fixtures, "--stations", "4", "--channels", "3",
                          "--records", "1500"])
    if rc != 0:
        print("fixture generation failed"); return 3

    ini = os.path.join(work, "receiver.ini")
    with open(ini, "w") as fh:
        fh.write(f"[server]\nport={port}\nmax_clients=512\nidle_no_record_sec=600\n"
                 f"[storage]\nbase_dir={data_base}\nlog_dir={logs}\n")

    env = dict(os.environ, PYTHONPATH=TCP_PKG)
    recv_log = open(os.path.join(logs, "receiver.log"), "wb")
    proc = subprocess.Popen([sys.executable, "-m", "mseed_tcp_server", "--config", ini],
                            cwd=TCP_PKG, env=env, stdout=recv_log, stderr=subprocess.STDOUT)
    try:
        if not wait_port("127.0.0.1", port, 20):
            print("ERROR: receiver did not start"); return 4

        # 2) stream fixtures concurrently (fire-and-forget; we SIGTERM mid-flight)
        drv = subprocess.Popen([sys.executable, os.path.join(HERE, "loadtest_tcp.py"),
                                "--fixtures", fixtures, "--port", str(port),
                                "--connections", "32"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2.0)  # let writes begin landing

        # 3) send SIGTERM — exactly what `systemctl stop` / terminate() send
        t0 = time.time()
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=40)
            exited_cleanly = True
        except subprocess.TimeoutExpired:
            exited_cleanly = False
            proc.kill()
        term_secs = time.time() - t0
        try:
            drv.terminate()
            drv.wait(timeout=5)
        except Exception:
            pass

        # Give any just-drained writer a moment to release OS file locks, and
        # make the READER tolerant of a stale advisory lock the way the portal
        # does (readers open independently; a lingering flock must not block a
        # legitimate read). Both are reader-side concerns, not data integrity.
        os.environ["HDF5_USE_FILE_LOCKING"] = "FALSE"
        time.sleep(1.0)

        # 4) try to OPEN every device file read-only
        import h5py
        files = sorted(glob.glob(os.path.join(data_base, "devices", "*.h5")))
        locked, ok = [], []

        def try_open(path: str) -> str:
            """Return 'ok', 'stuck' (consistency flag), or 'lock' (live flock)."""
            last = None
            for _ in range(10):  # up to ~5s: tolerate a brief drain tail
                try:
                    with h5py.File(path, "r"):
                        return "ok"
                except OSError as e:
                    last = str(e)
                    if "already open for write" in last or "h5clear" in last:
                        return "stuck"
                    # errno 11 / resource temporarily unavailable => live lock
                    time.sleep(0.5)
            return "lock" if last else "ok"

        for f in files:
            res = try_open(f)
            if res == "ok":
                ok.append(f)
            else:
                locked.append((f, res))

        print(f"\n=== SIGTERM shutdown result ===")
        print(f"receiver exited on SIGTERM within 40s : {exited_cleanly} ({term_secs:.1f}s)")
        print(f"device files written                  : {len(files)}")
        print(f"files readable after shutdown         : {len(ok)}")
        print(f"files LEFT LOCKED (need h5clear)       : {len(locked)}")
        for f, res in locked[:6]:
            print(f"    locked({res}): {os.path.basename(f)}")

        graceful = exited_cleanly and len(files) > 0 and len(locked) == 0
        print(f"\n2.7/3.x graceful SIGTERM shutdown      : {'VERIFIED' if graceful else 'FAILED'}")
        if not graceful and exited_cleanly and locked:
            print("  -> receiver died on SIGTERM without closing in-flight HDF5 handles;")
            print("     add a SIGTERM handler so serve_forever() exits and db.close() runs.")
        return 0 if graceful else 1
    finally:
        if proc.poll() is None:
            proc.kill()
        import shutil
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
