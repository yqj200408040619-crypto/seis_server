from __future__ import annotations

import logging
import socket
import socketserver
import threading
import time
from pathlib import Path

from .config import AppConfig
from .db import ClientInfo, DeviceDatabaseManager
from .mseed import (
    find_next_record_start,
    get_record_length,
    is_plausible_record_start,
    parse_and_validate_packet,
)
from .util import quarantine_path, safe_name

LOG = logging.getLogger(__name__)


class MSeedTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, RequestHandlerClass, config: AppConfig, db_manager: DeviceDatabaseManager):
        self.config = config
        self.db_manager = db_manager
        self.client_semaphore = threading.BoundedSemaphore(config.server.max_clients)
        super().__init__(server_address, RequestHandlerClass, bind_and_activate=False)
        self.request_queue_size = config.server.backlog
        self.server_bind()
        self.server_activate()


def set_socket_options(sock: socket.socket, cfg: AppConfig) -> None:
    sock.settimeout(cfg.server.socket_timeout_sec)
    if cfg.server.tcp_keepalive:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        # Linux-specific keepalive tuning. Ignore silently on other systems.
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
                # Keep idle TCP connections open; TCP keepalive detects dead peers.
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
                    # Keep a short suffix in case the next recv completes a header candidate.
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
                header = parse_and_validate_packet(packet, length_info.length, cfg.parser)
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

            try:
                result = self.server.db_manager.insert_packet(self.client, packet, header)
            except Exception as exc:
                LOG.exception(
                    "database write failed from %s:%s stream=%s.%s.%s.%s start=%s seq=? error=%s",
                    self.client_ip,
                    self.client_port,
                    header.network,
                    header.station,
                    header.location,
                    header.channel,
                    header.start_unix,
                    exc,
                )
                # Keep the validated packet for manual replay instead of dropping it silently.
                self._quarantine(packet, f"db_write_failed: {exc}")
                continue

            self.packet_count += 1
            if result.inserted:
                LOG.info(
                    "stored device=%s stream=%s.%s.%s.%s start=%.6f seq=%s len=%d db=%s",
                    result.device_id,
                    header.network,
                    header.station,
                    header.location,
                    header.channel,
                    header.start_unix,
                    packet[:6].decode("ascii", errors="ignore").strip(),
                    len(packet),
                    result.db_path,
                )
                for msg in result.gap_events:
                    LOG.warning("gap detected device=%s %s", result.device_id, msg)
            else:
                LOG.info(
                    "duplicate ignored device=%s stream=%s.%s.%s.%s start=%.6f sha=%s",
                    result.device_id,
                    header.network,
                    header.station,
                    header.location,
                    header.channel,
                    header.start_unix,
                    header.sha256[:12],
                )

        return buffer

    def _quarantine(self, data: bytes, reason: str) -> None:
        if not data:
            return
        cfg = self.server.config
        qdir = cfg.storage.base_dir / cfg.storage.quarantine_dir_name / safe_name(f"{self.client_ip}_{self.client_port}")
        path = quarantine_path(qdir, prefix="quarantine")
        marker = (
            f"\n-- MSEED_TCP_SERVER_QUARANTINE -- time={time.time():.6f} "
            f"client={self.client_ip}:{self.client_port} reason={reason} length={len(data)} --\n"
        ).encode("utf-8", errors="replace")
        try:
            with open(path, "ab") as f:
                f.write(marker)
                f.write(data)
                f.write(b"\n-- END_QUARANTINE_RECORD --\n")
            LOG.warning("quarantined %d bytes from %s:%s reason=%s path=%s", len(data), self.client_ip, self.client_port, reason, path)
        except Exception:
            LOG.exception("failed to write quarantine file")


def run_server(config: AppConfig) -> None:
    db_manager = DeviceDatabaseManager(config)
    address = (config.server.host, config.server.port)
    with MSeedTCPServer(address, MSeedRequestHandler, config, db_manager) as srv:
        LOG.info("mseed TCP server listening on %s:%s", config.server.host, config.server.port)
        try:
            srv.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            LOG.info("keyboard interrupt; shutting down")
        finally:
            srv.shutdown()
