from __future__ import annotations

from dataclasses import dataclass
import logging
import queue
import socket
import socketserver
import threading
import time
import zlib
from pathlib import Path

from .config import AppConfig
from .db import ClientInfo, DeviceDatabaseManager  # 这里引用的是你新的 h5py 版 db.py
from .mseed import (
    find_next_record_start,
    get_record_length,
    is_plausible_record_start,
    parse_full_packet,          # 重点：从 parse_and_validate_packet 换成 parse_full_packet
)
from .util import quarantine_path, safe_name

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class MSeedWriteTask:
    client: ClientInfo
    packet: bytes
    header: object
    waveform: object


def quarantine_packet(config: AppConfig, client: ClientInfo, data: bytes, reason: str) -> None:
    """Persist a rejected packet even when the receiving handler has exited."""
    if not data:
        return
    qdir = config.storage.base_dir / config.storage.quarantine_dir_name / safe_name(f"{client.client_ip}_{client.client_port}")
    path = quarantine_path(qdir, prefix="quarantine")
    marker = (
        f"\n-- MSEED_TCP_SERVER_QUARANTINE -- time={time.time():.6f} "
        f"client={client.client_ip}:{client.client_port} reason={reason} length={len(data)} --\n"
    ).encode("utf-8", errors="replace")
    try:
        with open(path, "ab") as f:
            f.write(marker)
            f.write(data)
            f.write(b"\n-- END_QUARANTINE_RECORD --\n")
        LOG.warning("quarantined %d bytes from %s:%s reason=%s path=%s", len(data), client.client_ip, client.client_port, reason, path)
    except Exception:
        LOG.exception("failed to write quarantine file")


class MSeedWritePipeline:
    """Bounded device-sharded HDF5 writer pipeline.

    Each device always maps to one FIFO worker, which keeps gap detection and
    on-disk record order correct.  Devices mapped to different shards are not
    delayed by each other's HDF5 I/O.  A full shard waits instead of discarding
    data, letting TCP backpressure slow only the affected sender.
    """

    def __init__(self, config: AppConfig, db_manager: DeviceDatabaseManager):
        self.config = config
        self.db_manager = db_manager
        self.worker_count = max(1, config.server.writer_threads)
        per_shard = max(1, (max(1, config.server.write_queue_max_packets) + self.worker_count - 1) // self.worker_count)
        self.queues: list[queue.Queue[MSeedWriteTask | None]] = [queue.Queue(maxsize=per_shard) for _ in range(self.worker_count)]
        self.stopping = threading.Event()
        self.workers = [threading.Thread(target=self._worker, args=(index,), name=f"mseed-writer-{index}", daemon=True)
                        for index in range(self.worker_count)]

    def start(self) -> None:
        for worker in self.workers:
            worker.start()
        LOG.info("miniSEED write pipeline started: workers=%d queue_capacity=%d", self.worker_count, sum(q.maxsize for q in self.queues))

    def submit(self, task: MSeedWriteTask) -> bool:
        device_id = self.db_manager.device_id(task.client, task.header)
        work_queue = self.queues[zlib.crc32(device_id.encode("utf-8")) % self.worker_count]
        while not self.stopping.is_set():
            try:
                work_queue.put(task, timeout=1.0)
                return True
            except queue.Full:
                LOG.warning("miniSEED write queue full; applying TCP backpressure device=%s peer=%s:%s queued=%d",
                            device_id, task.client.client_ip, task.client.client_port, work_queue.qsize())
        return False

    def _worker(self, index: int) -> None:
        work_queue = self.queues[index]
        while True:
            task = work_queue.get()
            try:
                if task is None:
                    return
                try:
                    result = self.db_manager.insert_packet(task.client, task.packet, task.header, task.waveform)
                except Exception as exc:
                    LOG.exception("database write failed peer=%s:%s stream=%s.%s.%s.%s start=%s error=%s",
                                  task.client.client_ip, task.client.client_port, task.header.network, task.header.station,
                                  task.header.location, task.header.channel, task.header.start_unix, exc)
                    quarantine_packet(self.config, task.client, task.packet, f"db_write_failed: {exc}")
                    continue
                if result.inserted:
                    LOG.info("stored device=%s stream=%s.%s.%s.%s start=%.6f seq=%s len=%d db=%s",
                             result.device_id, task.header.network, task.header.station, task.header.location,
                             task.header.channel, task.header.start_unix,
                             task.packet[:6].decode("ascii", errors="ignore").strip(), len(task.packet), result.db_path)
                    for msg in result.gap_events:
                        LOG.warning("gap detected device=%s %s", result.device_id, msg)
                else:
                    LOG.info("duplicate ignored device=%s stream=%s.%s.%s.%s start=%.6f sha=%s",
                             result.device_id, task.header.network, task.header.station, task.header.location,
                             task.header.channel, task.header.start_unix, task.header.sha256[:12])
            finally:
                work_queue.task_done()

    def close(self, drain_timeout_sec: float = 30.0) -> None:
        self.stopping.set()
        deadline = time.monotonic() + drain_timeout_sec
        for work_queue in self.queues:
            while work_queue.unfinished_tasks and time.monotonic() < deadline:
                time.sleep(0.05)
            if work_queue.unfinished_tasks:
                LOG.warning("miniSEED shutdown drain timeout; %d queued packets remain", work_queue.qsize())
        for index, work_queue in enumerate(self.queues):
            while time.monotonic() < deadline:
                try:
                    work_queue.put(None, timeout=0.1)
                    break
                except queue.Full:
                    pass
            else:
                LOG.warning("miniSEED worker %d could not be sent its shutdown marker", index)
        for worker in self.workers:
            worker.join(timeout=max(0.0, deadline - time.monotonic()))
        self.db_manager.close()


class MSeedTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, RequestHandlerClass, config: AppConfig, db_manager: DeviceDatabaseManager):
        self.config = config
        self.db_manager = db_manager
        self.pipeline = MSeedWritePipeline(config, db_manager)
        self.client_semaphore = threading.BoundedSemaphore(config.server.max_clients)
        super().__init__(server_address, RequestHandlerClass, bind_and_activate=False)
        self.request_queue_size = config.server.backlog
        self.server_bind()
        self.server_activate()
        self.pipeline.start()

    def server_close(self) -> None:
        self.pipeline.close()
        super().server_close()


def set_socket_options(sock: socket.socket, cfg: AppConfig) -> None:
    sock.settimeout(cfg.server.socket_timeout_sec)
    if cfg.server.tcp_keepalive:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        for opt_name, value in (
            ("TCP_KEEPIDLE", 60),
            ("TCP_KEEPINTVL", 30),
            ("TCP_KEEPCNT", 5),
        ):
            opt = getattr(socket, opt_name, None)
            if opt is not None:
                try:
                    sock.setsockopt(socket.IPPROTO_TCP, opt, value)
                except OSError:
                    pass


class MSeedRequestHandler(socketserver.BaseRequestHandler):
    server: MSeedTCPServer

    def setup(self) -> None:
        acquired = self.server.client_semaphore.acquire(blocking=False)
        if not acquired:
            raise ConnectionRefusedError("too many concurrent clients")
        set_socket_options(self.request, self.server.config)
        self.client_ip, self.client_port = self.client_address
        self.server_port = self.server.server_address[1]
        self.client = ClientInfo(self.client_ip, int(self.client_port), int(self.server_port))
        self.packet_count = 0
        self.byte_count = 0
        self.started_unix = time.time()
        threading.current_thread().name = f"client-{self.client_ip}:{self.client_port}"
        LOG.info("connection accepted from %s:%s", self.client_ip, self.client_port)

    def finish(self) -> None:
        elapsed = time.time() - getattr(self, "started_unix", time.time())
        LOG.info(
            "connection closed from %s:%s packets=%s bytes=%s elapsed=%.1fs",
            getattr(self, "client_ip", "?"),
            getattr(self, "client_port", "?"),
            getattr(self, "packet_count", 0),
            getattr(self, "byte_count", 0),
            elapsed,
        )
        try:
            self.server.client_semaphore.release()
        except Exception:
            pass

    def handle(self) -> None:
        cfg = self.server.config
        buffer = b""

        while True:
            try:
                chunk = self.request.recv(cfg.server.recv_size)
            except socket.timeout:
                continue
            except ConnectionResetError:
                LOG.warning("connection reset by peer %s:%s", self.client_ip, self.client_port)
                if buffer:
                    self._quarantine(buffer, "connection_reset_partial_buffer")
                break
            except OSError as exc:
                LOG.warning("socket error from %s:%s: %s", self.client_ip, self.client_port, exc)
                if buffer:
                    self._quarantine(buffer, "socket_error_partial_buffer")
                break

            if not chunk:
                if buffer:
                    self._quarantine(buffer, "disconnect_partial_buffer")
                break

            self.byte_count += len(chunk)
            buffer += chunk

            if len(buffer) > cfg.parser.max_buffer_bytes:
                LOG.warning(
                    "buffer overflow from %s:%s; size=%d, attempting resync",
                    self.client_ip,
                    self.client_port,
                    len(buffer),
                )
                next_start = find_next_record_start(buffer, cfg.parser.resync_scan_limit)
                if next_start is not None:
                    self._quarantine(buffer[:next_start], "buffer_overflow_discard_before_resync")
                    buffer = buffer[next_start:]
                else:
                    keep = buffer[-47:] if len(buffer) >= 47 else buffer
                    self._quarantine(buffer[:-len(keep)] if keep else buffer, "buffer_overflow_no_header_found")
                    buffer = keep

            buffer = self._process_buffer(buffer)

    def _process_buffer(self, buffer: bytes) -> bytes:
        cfg = self.server.config

        while True:
            if len(buffer) < 48:
                return buffer

            if not is_plausible_record_start(buffer, 0):
                next_start = find_next_record_start(buffer, cfg.parser.resync_scan_limit)
                if next_start is None:
                    if len(buffer) > 48:
                        self._quarantine(buffer[:-47], "bad_prefix_no_resync")
                        return buffer[-47:]
                    return buffer
                self._quarantine(buffer[:next_start], "bad_prefix_resynced")
                buffer = buffer[next_start:]
                continue

            try:
                length_info = get_record_length(buffer, cfg.parser)
            except ValueError as exc:
                LOG.warning("bad miniSEED header from %s:%s: %s", self.client_ip, self.client_port, exc)
                next_start = find_next_record_start(buffer[1:], cfg.parser.resync_scan_limit)
                if next_start is None:
                    self._quarantine(buffer[:1], f"bad_header_drop_one: {exc}")
                    buffer = buffer[1:]
                else:
                    drop = next_start + 1
                    self._quarantine(buffer[:drop], f"bad_header_resync: {exc}")
                    buffer = buffer[drop:]
                continue

            if length_info is None:
                return buffer

            if len(buffer) < length_info.length:
                return buffer

            packet = buffer[:length_info.length]
            buffer = buffer[length_info.length:]

            try:
                # ---- 核心修改：解析完整波形 ----
                header, waveform = parse_full_packet(packet, length_info.length, cfg.parser)
            except Exception as exc:
                LOG.warning(
                    "miniSEED validation failed from %s:%s len=%s: %s",
                    self.client_ip,
                    self.client_port,
                    len(packet),
                    exc,
                )
                self._quarantine(packet, f"validation_failed: {exc}")
                continue

            if not self.server.pipeline.submit(MSeedWriteTask(self.client, packet, header, waveform)):
                LOG.warning("miniSEED receiver is stopping; discarded unfinished input peer=%s:%s", self.client_ip, self.client_port)
                return buffer
            self.packet_count += 1

        return buffer

    def _quarantine(self, data: bytes, reason: str) -> None:
        quarantine_packet(self.server.config, self.client, data, reason)


def run_server(config: AppConfig) -> None:
    db_manager = DeviceDatabaseManager(config)
    address = (config.server.host, config.server.port)
    
    # Outer try ensures logging is performed even if SystemExit is raised inside the with block
    try:
        with MSeedTCPServer(address, MSeedRequestHandler, config, db_manager) as srv:
            LOG.info("mseed TCP server listening on %s:%s", config.server.host, config.server.port)
            try:
                srv.serve_forever(poll_interval=0.5)
            except (KeyboardInterrupt, SystemExit):
                LOG.info("Received interrupt signal (KeyboardInterrupt/SystemExit), shutting down gracefully...")
                # The 'with' statement will automatically call srv.shutdown() and __exit__ upon leaving.
                # Since db.py uses 'with h5py.File(...)' for every write, f.close() is already called automatically.
                # Re-raise to let the outer layers handle the exit.
                raise
            except Exception as e:
                LOG.exception("Unexpected error during server loop: %s", e)
                raise
            finally:
                LOG.info("Server stopped. All HDF5 file handles have been closed automatically.")
    except Exception as e:
        LOG.exception("Fatal error during server startup or runtime: %s", e)
        raise
