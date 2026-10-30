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

server_mod = env.load_server()
cfg_mod = env.make_config(server_mod)


def build_server(idle: int, sock_to: int, max_clients: int = 8):
    cfg = cfg_mod.AppConfig(
        server=cfg_mod.ServerConfig(
            host="127.0.0.1", port=0, max_clients=max_clients,
            idle_timeout_sec=idle, socket_timeout_sec=sock_to,
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


def test_slow_trickle_bypasses_reaper():
    # idle=2s, socket_timeout=1s. Trickle one byte every ~1.2s (< idle).
    srv = build_server(idle=2, sock_to=1)
    addr = srv.server_address
    s = socket.create_connection(addr, timeout=2)

    stop = threading.Event()

    def trickle():
        while not stop.is_set():
            try:
                s.sendall(b"\x00")
            except OSError:
                return
            # refresh interval shorter than idle(2s) -> keeps last_data_unix fresh
            stop.wait(1.2)

    th = threading.Thread(target=trickle, daemon=True)
    th.start()

    # Observe for 8 seconds = 4x the idle timeout. A correct "minimum useful
    # throughput" guard would reap this near-idle connection; the current
    # reaper does not, because ANY byte resets the idle clock.
    survived = True
    for _ in range(8):
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
    print(f"[1.5] slow-trickle connection survived 4x idle_timeout = {survived} "
          f"(True => reaper BYPASSED, defect confirmed)")
    return survived


def main():
    r14 = test_reaper_fires()
    r15 = test_slow_trickle_bypasses_reaper()
    print("\n--- summary ---")
    print(f"1.4 reaper fires on silent conn : {'PASS' if r14 else 'FAIL'}")
    print(f"1.5 slow-trickle bypasses reaper: {'CONFIRMED DEFECT' if r15 else 'not reproduced'}")
    # script exit 0 when both observations match expectation
    return 0 if (r14 and r15) else 1


if __name__ == "__main__":
    raise SystemExit(main())
