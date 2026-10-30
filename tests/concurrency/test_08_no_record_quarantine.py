"""Item 1.5 (regression) — no-record timeout must LOG and QUARANTINE cleanly.

Gap found by running the suite: test_02 proves a slow-trickle connection is
*reaped* by the no-record guard, but it only observes that the handler thread
disappears. It never checks the code the guard runs *before* closing:

    LOG.warning("no-record timeout: ... %.0fs (received %d bytes) ...",
                self.client_ip, self.client_port, now - last_record_unix, ...)
    if buffer:
        self._quarantine(buffer, "no_record_timeout_partial_buffer")

The original fix referenced a BARE `last_record_unix` (the attribute is
`self.last_record_unix`), so this branch raised `NameError` at that log call.
The handler still "disappears" (the thread dies on the exception), so test_02
passed — but the exception aborts the handler BEFORE `self._quarantine(...)`
runs, so the slow-trickle peer's partial buffer is silently lost instead of
quarantined, and the operator never gets the intended warning log.

This test exercises the real handle() loop and asserts the OBSERVABLE
side effect of that code path: a quarantine file written with reason
`no_record_timeout_partial_buffer`. It FAILS against the NameError bug and
PASSES once the log statement uses `self.last_record_unix`.
"""
from __future__ import annotations

import socket
import threading
import time
import shutil
from pathlib import Path

import conftest_env as env
import _stubs

server_mod = env.load_server()
cfg_mod = env.make_config(server_mod)

STORE = Path("/tmp/seis_test_store_norecord")


def build_server(idle: int, sock_to: int, no_record: int, max_clients: int = 8):
    cfg = cfg_mod.AppConfig(
        server=cfg_mod.ServerConfig(
            host="127.0.0.1", port=0, max_clients=max_clients,
            idle_timeout_sec=idle, socket_timeout_sec=sock_to,
            idle_no_record_sec=no_record,
            writer_threads=1, write_queue_max_packets=16,
        ),
        storage=cfg_mod.StorageConfig(base_dir=STORE),
        parser=cfg_mod.ParserConfig(),
    )
    db = __import__("sys").modules["mseed_tcp_server.db"].DeviceDatabaseManager()
    srv = server_mod.MSeedTCPServer((cfg.server.host, cfg.server.port),
                                    server_mod.MSeedRequestHandler, cfg, db)
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    t.start()
    return srv, cfg


def live_handlers():
    return [t for t in threading.enumerate() if t.name.startswith("client-")]


def find_no_record_quarantine(base: Path) -> list[Path]:
    """Any quarantine.bin written under the quarantine dir with content."""
    qroot = base / "quarantine"
    if not qroot.exists():
        return []
    return [p for p in qroot.rglob("quarantine.bin") if p.stat().st_size > 0]


def test_no_record_path_logs_and_quarantines():
    # clean slate so we only observe this test's quarantine output
    if STORE.exists():
        shutil.rmtree(STORE, ignore_errors=True)

    # byte-idle=100s (byte-idle reaper won't fire), socket_timeout=1s,
    # no-record guard=3s. Trickle partial (non-record) bytes every ~1.5s:
    # keeps byte-idle fresh, never forms a complete record -> no-record guard
    # must fire AND must leave a quarantined partial buffer behind.
    srv, cfg = build_server(idle=100, sock_to=1, no_record=3)
    addr = srv.server_address
    s = socket.create_connection(addr, timeout=2)

    stop = threading.Event()

    def trickle():
        # send a partial prefix of the magic so bytes accumulate in buffer
        # but never complete a 64-byte record
        while not stop.is_set():
            try:
                s.sendall(b"M")      # 1 partial byte, never a full record
            except OSError:
                return
            stop.wait(1.5)

    th = threading.Thread(target=trickle, daemon=True)
    th.start()

    reaped = False
    for _ in range(12):              # up to 12s
        time.sleep(1.0)
        if len(live_handlers()) == 0:
            reaped = True
            break
    stop.set()
    time.sleep(0.3)                  # allow quarantine write to flush
    try:
        s.close()
    except OSError:
        pass

    q = find_no_record_quarantine(STORE)
    quarantined = len(q) > 0

    srv.shutdown(); srv.server_close()

    print(f"[1.5-regression] slow-trickle reaped by no-record guard = {reaped}")
    print(f"[1.5-regression] partial buffer quarantined (log path ran, no NameError) = {quarantined}")
    if q:
        print(f"                 quarantine file(s): {[str(p) for p in q]}")
    else:
        print("                 NO quarantine file written -> no-record log path "
              "crashed before _quarantine() (NameError on last_record_unix)")

    return reaped and quarantined


def main():
    ok = test_no_record_path_logs_and_quarantines()
    print("\n--- summary ---")
    print(f"1.5 no-record path logs & quarantines cleanly : {'VERIFIED' if ok else 'FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
