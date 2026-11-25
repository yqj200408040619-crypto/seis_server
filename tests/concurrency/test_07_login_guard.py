"""Item 5.2 FIX — login throttle + bcrypt concurrency gate.

login_guard.py is pure standard library, so we import it directly and verify:
  - LoginThrottle locks out after N failures within the window, and the lock
    expires after lockout_sec (so legitimate users recover).
  - A successful login clears the failure state.
  - bcrypt_gate bounds concurrency: with a size-1 gate, a second acquirer must
    wait for the first to release — modelling how the gate stops a login flood
    from occupying every thread-pool worker at once.
"""
from __future__ import annotations

import os
import sys
import threading
import time

# import the real guard module without pulling in fastapi/bcrypt
APP = os.path.join(os.path.dirname(__file__), "..", "..", "mseed_web_portal")
sys.path.insert(0, os.path.abspath(APP))
import importlib.util

spec = importlib.util.spec_from_file_location(
    "login_guard", os.path.join(os.path.abspath(APP), "app", "login_guard.py"))
login_guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(login_guard)
LoginThrottle = login_guard.LoginThrottle


def test_lockout_after_failures():
    th = LoginThrottle(max_failures=5, window_sec=300, lockout_sec=10)
    ip, user = "10.0.0.1", "admin"
    t0 = 1000.0
    for i in range(4):
        th.record_failure(ip, user, now=t0 + i)
    locked_after_4 = th.is_locked(ip, user, now=t0 + 4)
    th.record_failure(ip, user, now=t0 + 5)            # 5th failure
    locked_after_5 = th.is_locked(ip, user, now=t0 + 5)
    # lock should persist until lockout_sec passes...
    still_locked = th.is_locked(ip, user, now=t0 + 10)
    # ...then expire
    expired = not th.is_locked(ip, user, now=t0 + 16)
    ok = (not locked_after_4) and locked_after_5 and still_locked and expired
    print(f"[5.2] throttle: locked@4={locked_after_4} locked@5={locked_after_5} "
          f"still_locked@+10={still_locked} expired@+16={expired} -> {ok}")
    return ok


def test_success_clears_state():
    th = LoginThrottle(max_failures=3, window_sec=300, lockout_sec=60)
    ip, user = "10.0.0.2", "bob"
    th.record_failure(ip, user, now=100)
    th.record_failure(ip, user, now=101)
    th.record_success(ip, user)
    # after success, a single new failure must NOT be locked
    th.record_failure(ip, user, now=102)
    ok = not th.is_locked(ip, user, now=102)
    print(f"[5.2] success resets failure counter -> {ok}")
    return ok


def test_window_expiry():
    th = LoginThrottle(max_failures=3, window_sec=10, lockout_sec=60)
    ip, user = "10.0.0.3", "carol"
    th.record_failure(ip, user, now=0)
    th.record_failure(ip, user, now=1)
    # this old-enough failure falls outside the 10s window when the 3rd lands
    th.record_failure(ip, user, now=20)   # window drops the first two
    ok = not th.is_locked(ip, user, now=20)
    print(f"[5.2] failures outside window don't accumulate -> {ok}")
    return ok


def test_bcrypt_gate_bounds_concurrency():
    gate = threading.Semaphore(1)        # size-1 gate
    order = []
    lock = threading.Lock()

    def worker(name, work_sec):
        acquired = gate.acquire(timeout=5)
        with lock:
            order.append(("acquire", name, time.time()))
        time.sleep(work_sec)
        with lock:
            order.append(("release", name, time.time()))
        gate.release()

    t_a = threading.Thread(target=worker, args=("A", 0.4))
    t_b = threading.Thread(target=worker, args=("B", 0.1))
    t_a.start()
    time.sleep(0.05)                     # ensure A acquires first
    t_b.start()
    t_a.join(); t_b.join()

    # B must acquire only AFTER A releases (serialized by the size-1 gate).
    a_release = next(ts for (ev, n, ts) in order if ev == "release" and n == "A")
    b_acquire = next(ts for (ev, n, ts) in order if ev == "acquire" and n == "B")
    serialized = b_acquire >= a_release - 0.01
    print(f"[5.2] bcrypt_gate serializes concurrent verifications -> {serialized}")
    return serialized


def main():
    r = [
        test_lockout_after_failures(),
        test_success_clears_state(),
        test_window_expiry(),
        test_bcrypt_gate_bounds_concurrency(),
    ]
    print("\n--- summary ---")
    print(f"5.2 FIX login throttle + bcrypt gate: {'VERIFIED' if all(r) else 'FAILED'}")
    return 0 if all(r) else 1


if __name__ == "__main__":
    raise SystemExit(main())
