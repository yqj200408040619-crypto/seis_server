#!/usr/bin/env python3
"""OBN TCP receiver with a bounded, per-instrument ordered write pipeline.

Network threads only frame packets and enqueue them.  HDF5 parsing/writes happen
in a small set of worker threads so a slow disk (or one busy instrument file)
does not stop other instruments from being read from their TCP sockets.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import queue
import socketserver
import threading
import time
import zlib
import h5py
import numpy as np

from .obn_config import *
from .raw_parser import parse_packet

OBN_STORAGE_DIR = "/var/lib/mseed-tcp-server/obn_devices"
_locks: dict[str, threading.Lock] = {}
_lock_guard = threading.Lock()
LOG = logging.getLogger(__name__)

# These can be tuned in the service Environment without changing code.  The
# queue limit is a *total* packet limit, divided between the worker shards.
DEFAULT_WRITER_THREADS = 4
DEFAULT_QUEUE_MAX_PACKETS = 2048
QUEUE_PUT_TIMEOUT_SEC = 1.0


@dataclass(frozen=True)
class PacketTask:
    instrument_id: str
    client_ip: str
    raw: bytes


class OBNWritePipeline:
    """Bounded queues sharded by instrument ID.

    A stable shard selection means packets for one instrument always reach the
    same worker and are written in arrival order.  Different instruments can be
    parsed and flushed concurrently.  When a shard fills, ``submit`` waits;
    this deliberately lets TCP backpressure reach only the affected producer
    instead of silently losing waveform packets.
    """

    def __init__(self, writer_threads: int, queue_max_packets: int, storage_dir: str):
        self.writer_threads = max(1, writer_threads)
        self.storage_dir = storage_dir
        per_shard = max(1, (max(1, queue_max_packets) + self.writer_threads - 1) // self.writer_threads)
        self.queues: list[queue.Queue[PacketTask | None]] = [queue.Queue(maxsize=per_shard) for _ in range(self.writer_threads)]
        self._stopping = threading.Event()
        self._workers = [threading.Thread(target=self._worker, args=(index,), name=f"obn-writer-{index}", daemon=True)
                         for index in range(self.writer_threads)]

    def start(self) -> None:
        for worker in self._workers:
            worker.start()
        LOG.info("OBN write pipeline started: workers=%d queue_capacity=%d", self.writer_threads, sum(q.maxsize for q in self.queues))

    def _queue_for(self, instrument_id: str) -> queue.Queue[PacketTask | None]:
        # Unlike Python's randomized hash(), crc32 selects the same shard after
        # a restart, which also makes diagnostics repeatable.
        index = zlib.crc32(instrument_id.encode("utf-8")) % self.writer_threads
        return self.queues[index]

    def submit(self, task: PacketTask) -> bool:
        work_queue = self._queue_for(task.instrument_id)
        while not self._stopping.is_set():
            try:
                work_queue.put(task, timeout=QUEUE_PUT_TIMEOUT_SEC)
                return True
            except queue.Full:
                LOG.warning("OBN write queue full; applying TCP backpressure instrument=%s peer=%s queued=%d",
                            task.instrument_id, task.client_ip, work_queue.qsize())
        return False

    def _worker(self, index: int) -> None:
        work_queue = self.queues[index]
        while True:
            task = work_queue.get()
            try:
                if task is None:
                    return
                try:
                    append_packet(task.instrument_id, parse_packet(task.raw, 0), task.raw, storage_dir=self.storage_dir)
                except Exception:
                    # A malformed packet or one failed HDF5 write must not kill
                    # the worker; subsequent packets and other instruments keep
                    # flowing.  The raw bytes are included only as metadata here.
                    LOG.exception("OBN packet processing failed instrument=%s peer=%s bytes=%d",
                                  task.instrument_id, task.client_ip, len(task.raw))
            finally:
                work_queue.task_done()

    def close(self, drain_timeout_sec: float = 30.0) -> None:
        """Stop accepting work, drain queued packets, then stop workers."""
        self._stopping.set()
        deadline = time.monotonic() + drain_timeout_sec
        for work_queue in self.queues:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                LOG.warning("OBN shutdown drain timeout; %d queued packets remain", work_queue.qsize())
                break
            # Queue.join has no timeout; poll unfinished_tasks so shutdown is bounded.
            while work_queue.unfinished_tasks and time.monotonic() < deadline:
                time.sleep(0.05)
            if work_queue.unfinished_tasks:
                LOG.warning("OBN shutdown drain timeout; %d queued packets remain", work_queue.qsize())
        for work_queue in self.queues:
            # Do not let shutdown hang forever if a filesystem operation is
            # stuck.  Workers are daemons, so systemd can still terminate us
            # after its configured stop timeout.
            while True:
                try:
                    work_queue.put(None, timeout=0.1)
                    break
                except queue.Full:
                    if time.monotonic() >= deadline:
                        LOG.warning("OBN worker %d could not be sent its shutdown marker", self.queues.index(work_queue))
                        break
        for worker in self._workers:
            worker.join(timeout=max(0.0, deadline - time.monotonic()))

def get_lock(instrument_id: str) -> threading.Lock:
    with _lock_guard:
        return _locks.setdefault(instrument_id, threading.Lock())

def append_packet(instrument_id: str, packet_data: dict, raw_packet: bytes | None = None, *, storage_dir: str = OBN_STORAGE_DIR) -> None:
    """Append decoded OBN samples and, when supplied, the original wire packet."""
    os.makedirs(storage_dir, exist_ok=True)
    path = os.path.join(storage_dir, f"{instrument_id}.h5")
    with get_lock(instrument_id), h5py.File(path, "a") as h5:
        if "metadata" not in h5:
            meta = h5.create_group("metadata")
            for key, value in {"instrument_id": instrument_id, "sample_rate": SAMPLE_RATE, "sample_interval_us": DT_US,
                "channels": CHNL_NUM, "samples_per_packet": SAMP_BUF_NUM, "raw_endian": DATA_DTYPE.byteorder,
                "time_basis": "UTC", "timestamp_align": TIMESTAMP_ALIGN, "year_is_offset": YEAR_IS_OFFSET,
                "channel_names": CHANNEL_NAMES}.items(): meta.attrs[key] = value
            h5.create_dataset("samples", shape=(0, CHNL_NUM, SAMP_BUF_NUM), maxshape=(None, CHNL_NUM, SAMP_BUF_NUM), dtype=DATA_DTYPE, chunks=H5_CHUNK_SHAPE, compression=H5_COMPRESSION, shuffle=H5_SHUFFLE)
            for name, dtype in (("packet_time_us", np.int64), ("packet_no", np.uint16), ("packet_flags", np.uint16)):
                h5.create_dataset(name, shape=(0,), maxshape=(None,), dtype=dtype, chunks=(1024,))
        if "raw_packets" not in h5:
            h5.create_dataset("raw_packets", shape=(0,), maxshape=(None,),
                dtype=h5py.vlen_dtype(np.dtype("uint8")), chunks=(128,))
        idx = h5["samples"].shape[0]
        h5["samples"].resize(idx + 1, axis=0); h5["samples"][idx] = packet_data["samples"]
        for name, value in (("packet_time_us", packet_data["timestamp_us"]), ("packet_no", packet_data["no"]), ("packet_flags", 0)):
            h5[name].resize(idx + 1, axis=0); h5[name][idx] = value
        # Old HDF5 files remain readable; raw download starts with packets stored
        # after this schema addition.
        if "raw_packets" in h5:
            h5["raw_packets"].resize(idx + 1, axis=0)
            h5["raw_packets"][idx] = np.frombuffer(raw_packet or b"", dtype=np.uint8)
        h5.flush()

class OBNRequestHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        client_ip = self.client_address[0]
        instrument_id = f"OBN_{client_ip.replace('.', '_')}"
        buffer = bytearray()
        while True:
            try:
                chunk = self.request.recv(65536)
            except OSError as exc:
                LOG.info("OBN connection read ended peer=%s error=%s", client_ip, exc)
                break
            if not chunk:
                break
            buffer.extend(chunk)
            while len(buffer) >= PACKET_SIZE:
                raw = bytes(buffer[:PACKET_SIZE])
                del buffer[:PACKET_SIZE]
                if not self.server.pipeline.submit(PacketTask(instrument_id, client_ip, raw)):
                    LOG.warning("OBN receiver is stopping; discarded unfinished input peer=%s", client_ip)
                    return
        if buffer:
            LOG.warning("OBN peer disconnected with incomplete packet peer=%s bytes=%d", client_ip, len(buffer))

class OBNServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, handler_class, *, writer_threads: int, queue_max_packets: int, storage_dir: str):
        self.pipeline = OBNWritePipeline(writer_threads, queue_max_packets, storage_dir)
        super().__init__(server_address, handler_class)
        self.pipeline.start()

    def server_close(self) -> None:
        self.pipeline.close()
        super().server_close()

def run_obn_server(host: str = "0.0.0.0", port: int = 18001, *, writer_threads: int | None = None,
                   queue_max_packets: int | None = None, storage_dir: str = OBN_STORAGE_DIR) -> None:
    writer_threads = writer_threads if writer_threads is not None else int(os.environ.get("OBN_WRITER_THREADS", DEFAULT_WRITER_THREADS))
    queue_max_packets = queue_max_packets if queue_max_packets is not None else int(os.environ.get("OBN_QUEUE_MAX_PACKETS", DEFAULT_QUEUE_MAX_PACKETS))
    with OBNServer((host, port), OBNRequestHandler, writer_threads=writer_threads,
                   queue_max_packets=queue_max_packets, storage_dir=storage_dir) as server:
        LOG.info("OBN TCP server listening on %s:%s", host, port)
        server.serve_forever()

if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("OBN_LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run_obn_server()
