"""In-memory login throttling and a bcrypt concurrency gate.

Why: the login route calls bcrypt (rounds=12), a deliberately CPU-expensive
operation. Under ``uvicorn --workers 1`` all synchronous routes share one
bounded AnyIO thread pool, so a burst of login attempts can occupy every pool
thread computing bcrypt and stall the whole site (a cheap DoS). Two defences:

1. ``LoginThrottle`` — per (ip, username) sliding-window failure counter with a
   temporary lockout. Repeated bad attempts are rejected *before* bcrypt runs,
   so an attacker cannot keep spending CPU.
2. ``bcrypt_gate`` — a Semaphore limiting how many password verifications run
   at once (default = CPU count). Excess logins wait briefly for a permit
   instead of all piling into the thread pool simultaneously.

Pure standard library; no external dependencies, so it is unit-testable in any
environment.
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque


class LoginThrottle:
    def __init__(self, max_failures: int = 5, window_sec: float = 300.0,
                 lockout_sec: float = 300.0):
        self.max_failures = max_failures
        self.window_sec = window_sec
        self.lockout_sec = lockout_sec
        self._lock = threading.Lock()
        self._failures: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._locked_until: dict[tuple[str, str], float] = {}

    def _key(self, ip: str, username: str) -> tuple[str, str]:
        return (ip or "?", (username or "").lower())

    def is_locked(self, ip: str, username: str, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        key = self._key(ip, username)
        with self._lock:
            until = self._locked_until.get(key)
            if until is None:
                return False
            if now >= until:
                # lockout expired; clear state so the user can try again
                self._locked_until.pop(key, None)
                self._failures.pop(key, None)
                return False
            return True

    def retry_after(self, ip: str, username: str, now: float | None = None) -> float:
        now = now if now is not None else time.time()
        key = self._key(ip, username)
        with self._lock:
            until = self._locked_until.get(key, now)
            return max(0.0, until - now)

    def record_failure(self, ip: str, username: str, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        key = self._key(ip, username)
        with self._lock:
            dq = self._failures[key]
            dq.append(now)
            while dq and now - dq[0] > self.window_sec:
                dq.popleft()
            if len(dq) >= self.max_failures:
                self._locked_until[key] = now + self.lockout_sec

    def record_success(self, ip: str, username: str) -> None:
        key = self._key(ip, username)
        with self._lock:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)


def _default_gate_size() -> int:
    env = os.environ.get("MSEED_MAX_CONCURRENT_LOGINS")
    if env:
        try:
            return max(1, int(env))
        except ValueError:
            pass
    return max(1, os.cpu_count() or 2)


# Shared singletons used by the login route.
login_throttle = LoginThrottle()
bcrypt_gate = threading.Semaphore(_default_gate_size())
