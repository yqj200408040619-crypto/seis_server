"""Items 1.4 / 1.5 — idle-connection reaper.

Runs the REAL handle() loop in server.py.

1.4  A fully silent (half-open) connection is reaped after idle_timeout_sec,
     freeing the semaphore slot. Verified with a short idle timeout.

1.5  SLOW-TRICKLE BYPASS (suspected defect): a peer that sends a single byte
     slightly more often than socket_timeout_sec keeps last_data_unix fresh,
     so the idle condition (now - last_data_unix >= idle) NEVER becomes true
     and the reaper never fires — even though the peer delivers essentially no
     useful data. We prove the connection survives far past idle_timeout_sec.
"""
from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import conftest_env as env
import _stubs

server_mod = env.load_server()
cfg_mod = env.make_config(server_mod)


def build_server(idle: int, sock_to: int, max_clients: int = 8, no_record: int = 0):
    cfg = cfg_mod.AppConfig(
        server=cfg_mod.ServerConfig(
            host="127.0.0.1", port=0, max_clients=max_clients,
            idle_timeout_sec=idle, socket_timeout_sec=sock_to,
            idle_no_record_sec=no_record,
            writer_threads=1, write_queue_max_packets=16,
        ),
        storage=cfg_mod.StorageConfig(base_dir=Path("/tmp/seis_test_store2")),
        parser=cfg_mod.ParserConfig(),
    )
    db = __import__("sys").modules["mseed_tcp_server.db"].DeviceDatabaseManager()
    srv = server_mod.MSeedTCPServer((cfg.server.host, cfg.server.port),
                                    server_mod.MSeedRequestHandler, cfg, db)
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    t.start()
    return srv


def live_handlers():
    return [t for t in threading.enumerate() if t.name.startswith("client-")]


def test_reaper_fires():
    # socket_timeout=1s so recv() unblocks quickly; idle=2s.
    srv = build_server(idle=2, sock_to=1)
    addr = srv.server_address
    s = socket.create_connection(addr, timeout=2)
    s.sendall(b"\x00")           # one byte, then go completely silent
    time.sleep(0.5)
    assert len(live_handlers()) == 1, "handler should be live"
    # wait past idle timeout (2s) + a socket_timeout tick (1s) margin
    deadline = time.time() + 6
    reaped = False
    while time.time() < deadline:
        if len(live_handlers()) == 0:
            reaped = True
            break
        time.sleep(0.2)
    elapsed_ok = reaped
    print(f"[1.4] silent half-open connection reaped = {reaped}")
    try:
        s.close()
    except OSError:
        pass
    srv.shutdown(); srv.server_close()
    return elapsed_ok


def test_slow_trickle_reaped_by_no_record_guard():
    # byte-idle=100s (so the byte-idle reaper never fires during the test),
    # socket_timeout=1s, no-record guard=3s. Trickle one byte every ~1.0s:
    # it keeps the byte-idle clock fresh but never forms a complete record,
    # so the FIX (idle_no_record_sec) must reap it.
    # socket_timeout=1s so recv() unblocks and the reaper checks run. Trickle
    # a byte every ~1.5s: it refreshes the byte-idle clock often enough that the
    # byte-idle(100s) reaper never fires, yet each recv still times out so the
    # no-record check is evaluated. The bytes never form a complete record.
    srv = build_server(idle=100, sock_to=1, no_record=3)
    addr = srv.server_address
    s = socket.create_connection(addr, timeout=2)

    stop = threading.Event()

    def trickle():
        while not stop.is_set():
            try:
                s.sendall(b"\x00")   # a byte, but never a full stub record
            except OSError:
                return
            stop.wait(1.5)           # > socket_timeout so recv times out, < byte-idle

    th = threading.Thread(target=trickle, daemon=True)
    th.start()

    # The no-record guard (3s) should reap within ~ guard + a socket_timeout.
    reaped = False
    for _ in range(12):              # up to 12s
        time.sleep(1.0)
        if len(live_handlers()) == 0:
            reaped = True
            break
    stop.set()
    try:
        s.close()
    except OSError:
        pass
    srv.shutdown(); srv.server_close()
    print(f"[1.5] slow-trickle connection reaped by no-record guard = {reaped} "
          f"(True => FIX works; byte-idle reaper alone would NOT have reaped it)")
    return reaped


def test_valid_low_rate_not_reaped():
    # A legitimate low-rate peer that DOES send complete records periodically
    # must NOT be reaped by the no-record guard. Send one full stub record
    # every ~1s with a 3s guard; it should stay alive.
    # Send a full record every ~2s: recv still times out between records (so the
    # no-record check runs), but a complete record arrives within the 3s guard,
    # refreshing last_record_unix. The connection must survive.
    srv = build_server(idle=100, sock_to=1, no_record=3)
    addr = srv.server_address
    s = socket.create_connection(addr, timeout=2)
    rec = _stubs.make_record("LOWRATE")

    stop = threading.Event()

    def sender():
        while not stop.is_set():
            try:
                s.sendall(rec)
            except OSError:
                return
            stop.wait(2.0)

    th = threading.Thread(target=sender, daemon=True)
    th.start()
    survived = True
    for _ in range(7):               # 7s > guard(3s): must still be alive
        time.sleep(1.0)
        if len(live_handlers()) == 0:
            survived = False
            break
    stop.set()
    try:
        s.close()
    except OSError:
        pass
    srv.shutdown(); srv.server_close()
    print(f"[1.5] legitimate low-rate (sends full records) NOT reaped = {survived}")
    return survived


def main():
    r14 = test_reaper_fires()
    r15 = test_slow_trickle_reaped_by_no_record_guard()
    r15b = test_valid_low_rate_not_reaped()
    print("\n--- summary ---")
    print(f"1.4 reaper fires on silent conn            : {'PASS' if r14 else 'FAIL'}")
    print(f"1.5 FIX slow-trickle reaped by no-record   : {'VERIFIED' if r15 else 'FAILED'}")
    print(f"1.5 FIX legitimate low-rate NOT reaped     : {'VERIFIED' if r15b else 'FAILED'}")
    return 0 if (r14 and r15 and r15b) else 1


if __name__ == "__main__":
    raise SystemExit(main())
