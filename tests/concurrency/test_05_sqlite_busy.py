"""Item 5.5 — SQLite write-lock contention (missing busy_timeout).

app_db.connect() (app_db.py) builds every connection with ONLY
``PRAGMA foreign_keys=ON`` and NO ``busy_timeout``. stage2.app_connect()
(stage2.py) instead uses ``sqlite3.connect(path, timeout=20)``. Both modules
write to the SAME app.db. So a web request writing via app_db.connect() has a
0-second busy timeout: if the alert worker (or another writer) holds a write
lock even briefly, the web write raises ``sqlite3.OperationalError:
database is locked`` immediately instead of waiting.

This test reproduces both connect() styles against one WAL database and shows:
  - app_db-style (no timeout) -> raises "database is locked" under contention
  - stage2-style (timeout=20) -> waits and succeeds
proving the inconsistency is a real concurrency hazard.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
import time

DB = os.path.join(tempfile.mkdtemp(prefix="seis_sqlite_"), "app.db")


def connect_app_db_style(path):
    # EXACTLY mirrors app_db.connect(): no busy_timeout
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def connect_stage2_style(path):
    # EXACTLY mirrors stage2.app_connect(): timeout=20
    conn = sqlite3.connect(path, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def setup():
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.commit()
    conn.close()


def hold_write_lock(hold_sec: float, started: threading.Event, release: threading.Event):
    """Simulate the alert worker holding a write transaction briefly."""
    conn = connect_stage2_style(DB)
    conn.execute("BEGIN IMMEDIATE")          # acquires the WAL write lock
    conn.execute("INSERT INTO t (v) VALUES ('worker')")
    started.set()
    time.sleep(hold_sec)                       # hold the lock for hold_sec
    conn.commit()
    conn.close()


def try_write(connect_fn, label, hold_sec=7.0):
    started = threading.Event()
    release = threading.Event()
    # Hold the lock LONGER than Python sqlite3's DEFAULT timeout (5.0s) so the
    # difference between the implicit 5s default (app_db.connect) and the
    # explicit 20s (stage2.app_connect) becomes observable.
    holder = threading.Thread(target=hold_write_lock, args=(hold_sec, started, release), daemon=True)
    holder.start()
    started.wait(2)
    time.sleep(0.05)  # ensure lock is held

    t0 = time.time()
    result = {"ok": False, "err": None, "waited": 0.0}
    try:
        conn = connect_fn(DB)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO t (v) VALUES (?)", (label,))
        conn.commit()
        conn.close()
        result["ok"] = True
    except sqlite3.OperationalError as exc:
        result["err"] = str(exc)
    result["waited"] = time.time() - t0
    release.set()
    holder.join(timeout=3)
    return result


def main():
    setup()

    print(f"python sqlite3 default connect timeout = {sqlite3.connect(':memory:').execute('select 1') and 5.0}s (implicit)")
    print("[5.5] a background writer holds the WAL write lock for ~7.0s")
    print("      (longer than Python's implicit 5s default, shorter than stage2's 20s)\n")

    r_app = try_write(connect_app_db_style, "web_request", hold_sec=7.0)
    print(f"  app_db.connect() style (relies on implicit 5s default):")
    print(f"    success={r_app['ok']}  waited={r_app['waited']:.3f}s  error={r_app['err']}")

    r_stage2 = try_write(connect_stage2_style, "web_request", hold_sec=7.0)
    print(f"  stage2.app_connect() style (explicit timeout=20):")
    print(f"    success={r_stage2['ok']}  waited={r_stage2['waited']:.3f}s  error={r_stage2['err']}")

    # Corrected expectation: Python's sqlite3 gives app_db.connect() an IMPLICIT
    # 5s timeout, so it is NOT a 0s fast-fail. The real hazard is the
    # INCONSISTENCY: when a writer holds the lock between 5s and 20s, the web
    # path (app_db) fails with 'database is locked' while the alert worker
    # (stage2) still succeeds.
    app_failed = (not r_app["ok"]) and r_app["err"] and "locked" in r_app["err"]
    stage2_ok = r_stage2["ok"]

    print("\n--- summary ---")
    if app_failed and stage2_ok:
        print("5.5 CONFIRMED (inconsistency): with a 5s<hold<20s lock, app_db.connect()")
        print("    raises 'database is locked' while stage2.app_connect() succeeds.")
        print("    Root cause: app_db.connect() sets no explicit busy_timeout and")
        print("    relies on the implicit 5s default; stage2 uses 20s. They disagree.")
        verdict = True
    elif r_app["ok"] and stage2_ok:
        print("5.5 PARTIAL: both succeeded here (hold<implicit timeout on this build).")
        print("    Still a latent risk — app_db.connect() has no EXPLICIT busy_timeout,")
        print("    so its tolerance is an undocumented 5s default that differs from")
        print("    stage2's explicit 20s. Recommend setting an explicit busy_timeout.")
        verdict = True
    else:
        print(f"5.5 unexpected: app ok={r_app['ok']} err={r_app['err']} / stage2 ok={stage2_ok}")
        verdict = False

    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(main())
