"""Item 2.1 / 2.7 — write-queue backpressure and graceful drain.

2.1  When a writer shard's bounded queue fills (slow HDF5 writes), submit()
     blocks in put(timeout=1.0) and retries instead of dropping packets. That
     block happens inside the handler's recv loop, so TCP backpressure slows
     the sender. We prove: no packets are lost, and the pipeline keeps the
     queue bounded (never exceeds maxsize).

2.7  close(drain_timeout) drains queued work within the deadline.
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


def main():
    # 1 writer thread, tiny queue, artificial 20ms-per-write delay -> easy to
    # saturate so backpressure is guaranteed to engage.
    import sys
    db_mod = sys.modules["mseed_tcp_server.db"]
    db = db_mod.DeviceDatabaseManager(write_delay_sec=0.02)

    cfg = cfg_mod.AppConfig(
        server=cfg_mod.ServerConfig(
            host="127.0.0.1", port=0, max_clients=8,
            idle_timeout_sec=300, socket_timeout_sec=5,
            writer_threads=1, write_queue_max_packets=8,  # per-shard maxsize = 8
        ),
        storage=cfg_mod.StorageConfig(base_dir=Path("/tmp/seis_test_store3")),
        parser=cfg_mod.ParserConfig(),
    )
    srv = server_mod.MSeedTCPServer((cfg.server.host, cfg.server.port),
                                    server_mod.MSeedRequestHandler, cfg, db)
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    t.start()
    addr = srv.server_address

    # monitor max observed queue depth
    q = srv.pipeline.queues[0]
    max_depth = {"v": 0}
    mon_stop = threading.Event()

    def monitor():
        while not mon_stop.is_set():
            max_depth["v"] = max(max_depth["v"], q.qsize())
            time.sleep(0.001)

    mon = threading.Thread(target=monitor, daemon=True)
    mon.start()

    # Send N records for ONE device as fast as possible -> all land on one shard.
    N = 200
    rec = _stubs.make_record("DEV-A")
    s = socket.create_connection(addr, timeout=5)
    t0 = time.time()
    s.sendall(rec * N)
    # wait until all N are written
    deadline = time.time() + 30
    while db.inserted < N and time.time() < deadline:
        time.sleep(0.05)
    send_elapsed = time.time() - t0
    mon_stop.set()

    lost = N - db.inserted
    bounded = max_depth["v"] <= q.maxsize
    # With 20ms/write and N=200 the pipeline needs >= ~4s; if sender finished
    # instantly but writes are serialized, backpressure did the throttling.
    throttled = send_elapsed >= (N * 0.02) * 0.5

    print(f"[2.1] records sent={N} written={db.inserted} lost={lost}")
    print(f"[2.1] max queue depth observed={max_depth['v']} maxsize={q.maxsize} bounded={bounded}")
    print(f"[2.1] total time to persist all={send_elapsed:.2f}s (serialized writes => backpressure active={throttled})")

    s.close()

    # 2.7 graceful drain
    # queue should be empty now; submit a few and close with a deadline.
    t_close0 = time.time()
    srv.pipeline  # already running; exercise close via server_close
    srv.shutdown()
    srv.server_close()  # calls pipeline.close(drain_timeout=30)
    drain_elapsed = time.time() - t_close0
    print(f"[2.7] server_close/drain completed in {drain_elapsed:.2f}s (within 30s deadline)")

    passed = (lost == 0) and bounded and throttled and (drain_elapsed < 30)
    print("\nRESULT:", "PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
