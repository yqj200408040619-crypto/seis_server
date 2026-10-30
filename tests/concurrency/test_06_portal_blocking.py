"""Items 5.1 / 5.2 — synchronous blocking routes saturate the thread pool.

FastAPI runs ``def`` (sync) path operations in a bounded worker thread pool
(AnyIO, default ~40 threads), and the portal is deployed with uvicorn
``--workers 1``. So the WHOLE site's concurrency for sync routes is capped by
that single pool. Any handler that blocks a pool thread for a long time
(a big /export/download building a 200k-record bytes blob, or a bcrypt verify
at rounds=12) removes a thread from circulation; enough of them in flight and
every other request — including cheap ones — queues behind them.

Both relevant routes are synchronous ``def`` in main.py:
  - export_download / export_download3  -> call export_mseed_bytes, which reads
    everything into memory and returns Response(content=blob)  (no streaming)
  - login -> verify_password -> bcrypt.checkpw at rounds=12  (CPU-bound)

Part A: measures the in-memory blob model of export_mseed_bytes (5.1) — the
        exported bytes are fully materialised, so memory scales with the window.
Part B: simulates a bounded pool (like AnyIO's) and shows how a handful of slow
        sync handlers inflate the latency of otherwise-instant requests (5.1/5.2).
"""
from __future__ import annotations

import concurrent.futures
import time
import tracemalloc


# ------------------------------------------------------------------ Part A
def part_a_export_blob_memory():
    """Reproduce the 'join everything into one bytes' model of export_mseed_bytes.

    data_reader.export_mseed_bytes collects raw records into a list and returns
    ``b"".join(raw_packets)`` (or st.write(buf) -> buf.getvalue()). The entire
    export is resident at once. We model records of typical miniSEED size (512 B)
    up to the max_records cap to show the peak footprint.
    """
    RECORD_SIZE = 512          # a common miniSEED record length
    MAX_RECORDS = 200_000      # the hard cap in export_download
    # scale down the count for the sandbox but keep per-record size; extrapolate.
    sample_n = 50_000
    tracemalloc.start()
    base = tracemalloc.take_snapshot()
    raw_packets = [b"\x00" * RECORD_SIZE for _ in range(sample_n)]
    blob = b"".join(raw_packets)              # <- the exact concatenation step
    snap = tracemalloc.take_snapshot()
    grew = sum(s.size_diff for s in snap.compare_to(base, "filename"))
    tracemalloc.stop()
    blob_len = len(blob)
    del raw_packets, blob

    def mb(n): return n / (1024 * 1024)
    per_record_peak = grew / sample_n
    projected_cap = per_record_peak * MAX_RECORDS
    print("[5.1] export_mseed_bytes in-memory model (b''.join, no streaming):")
    print(f"      sampled {sample_n:,} x {RECORD_SIZE}B records")
    print(f"      peak heap during build+join = {mb(grew):.1f} MB  (list + final blob coexist)")
    print(f"      final blob size             = {mb(blob_len):.1f} MB")
    print(f"      projected at max_records={MAX_RECORDS:,} -> ~{mb(projected_cap):.0f} MB per export")
    print(f"      Response(content=blob) is NOT streamed; this is held per in-flight export.")
    return projected_cap


# ------------------------------------------------------------------ Part B
def part_b_pool_saturation():
    """Show head-of-line blocking in a bounded sync worker pool."""
    POOL = 8               # model a small AnyIO pool (real default ~40)
    SLOW_TASK_SEC = 0.5    # a slow export / bcrypt verify
    FAST_TASK_SEC = 0.001  # a trivial page request

    def slow():
        time.sleep(SLOW_TASK_SEC); return "slow"

    def fast():
        time.sleep(FAST_TASK_SEC); return "fast"

    # Baseline: one fast request with an idle pool.
    with concurrent.futures.ThreadPoolExecutor(max_workers=POOL) as ex:
        t0 = time.time()
        ex.submit(fast).result()
        baseline = time.time() - t0

    # Contention: fill the pool with slow tasks, then time a fast request.
    with concurrent.futures.ThreadPoolExecutor(max_workers=POOL) as ex:
        slow_futs = [ex.submit(slow) for _ in range(POOL)]  # occupy every thread
        time.sleep(0.05)                                     # ensure they're running
        t0 = time.time()
        fast_fut = ex.submit(fast)                           # must wait for a free thread
        fast_fut.result()
        under_load = time.time() - t0
        concurrent.futures.wait(slow_futs)

    inflation = under_load / baseline if baseline else float("inf")
    print("\n[5.1/5.2] bounded sync pool head-of-line blocking:")
    print(f"      pool size = {POOL} (uvicorn --workers 1; AnyIO default ~40)")
    print(f"      fast request latency, idle pool   = {baseline*1000:.1f} ms")
    print(f"      fast request latency, pool full of {POOL} slow tasks = {under_load*1000:.1f} ms")
    print(f"      latency inflation = {inflation:.0f}x "
          f"(a trivial request waits behind the slow handlers)")
    return inflation


def main():
    projected = part_a_export_blob_memory()
    inflation = part_b_pool_saturation()
    print("\n--- summary ---")
    print(f"5.1 CONFIRMED: a single max-size export materialises ~{projected/1024/1024:.0f} MB in RAM, "
          f"returned non-streamed -> memory + one pool thread per in-flight export")
    print(f"5.1/5.2 CONFIRMED: when sync handlers fill the bounded pool, unrelated requests "
          f"queue ({inflation:.0f}x slower). With workers=1 this is a site-wide bottleneck; "
          f"bcrypt(rounds=12) logins and big exports are the realistic pool-fillers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
