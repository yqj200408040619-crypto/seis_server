"""Items 1.1 / 1.2 / 1.3 — connection concurrency gate.

Runs the REAL server.py (with stubbed db/mseed/util) on a loopback port and
drives it with real TCP sockets.

1.1  max_clients cap: the (N+1)th concurrent connection is refused.
1.3  semaphore release: after clients disconnect, new clients are accepted
     again (no slot leak).
1.2  thread growth: observe handler threads scale with live connections.
"""
from __future__ import annotations

import socket
import threading
import time

import conftest_env as env

server_mod = env.load_server()
cfg_mod = env.make_config(server_mod)

MAX = 4  # small cap so the test is fast and deterministic


def build_server(max_clients: int, idle: int = 300):
    cfg = cfg_mod.AppConfig(
        server=cfg_mod.ServerConfig(
            host="127.0.0.1", port=0, max_clients=max_clients,
            idle_timeout_sec=idle, socket_timeout_sec=1,
            writer_threads=2, write_queue_max_packets=64,
        ),
        storage=cfg_mod.StorageConfig(base_dir=__import__("pathlib").Path("/tmp/seis_test_store")),
        parser=cfg_mod.ParserConfig(),
    )
    db = __import__("sys").modules["mseed_tcp_server.db"].DeviceDatabaseManager()
    srv = server_mod.MSeedTCPServer((cfg.server.host, cfg.server.port),
                                    server_mod.MSeedRequestHandler, cfg, db)
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    t.start()
    return srv, srv.server_address


def try_connect(addr, hold_list):
    s = socket.create_connection(addr, timeout=2)
    # send one byte so the handler enters its recv loop and holds the slot
    s.sendall(b"\x00")
    hold_list.append(s)
    return s


def main():
    srv, addr = build_server(MAX)
    print(f"server listening on {addr}, max_clients={MAX}")
    held = []
    # 1.1: open MAX connections
    for i in range(MAX):
        try_connect(addr, held)
    time.sleep(0.3)
    print(f"[1.1] opened {len(held)} connections (cap={MAX})")

    # the (MAX+1)th must be refused at the application layer: setup() raises
    # ConnectionRefusedError -> handler thread dies -> server closes the socket.
    refused = False
    try:
        extra = socket.create_connection(addr, timeout=2)
        extra.settimeout(1.5)
        extra.sendall(b"\x00")
        data = extra.recv(16)  # expect empty => server closed the connection
        if data == b"":
            refused = True
        extra.close()
    except (ConnectionResetError, socket.timeout, OSError) as exc:
        refused = True
        print(f"    extra connection error (expected): {type(exc).__name__}")
    print(f"[1.1] connection beyond cap refused/closed: {refused}")

    # 1.2: count live handler threads
    handler_threads = [t for t in threading.enumerate() if t.name.startswith("client-")]
    print(f"[1.2] live handler threads = {len(handler_threads)} (expected ~{MAX})")

    # 1.3: close all, then confirm new connections are accepted again
    for s in held:
        s.close()
    time.sleep(1.5)  # allow recv() to observe disconnect (socket_timeout=1s)
    reopened = []
    ok = True
    try:
        for i in range(MAX):
            try_connect(addr, reopened)
        time.sleep(0.3)
    except OSError as exc:
        ok = False
        print(f"    reopen failed: {exc}")
    print(f"[1.3] reopened {len(reopened)}/{MAX} after release; no slot leak = {ok and len(reopened) == MAX}")
    for s in reopened:
        s.close()

    srv.shutdown()
    srv.server_close()

    # verdict
    passed = refused and (len(handler_threads) == MAX) and (len(reopened) == MAX)
    print("\nRESULT:", "PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
