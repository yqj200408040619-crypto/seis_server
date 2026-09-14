from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import configparser


@dataclass(frozen=True)
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 18000
    request_port: int = 20000
    backlog: int = 128
    recv_size: int = 8192
    socket_timeout_sec: int = 120
    tcp_keepalive: bool = True
    # 100+ instruments commonly keep long-lived TCP sessions. Leave capacity
    # for reconnect storms without accepting an unbounded number of handlers.
    max_clients: int = 512
    # Parsed records are queued before HDF5 writes.  The packet limit is split
    # over writer shards, each of which preserves device order.
    writer_threads: int = 8
    write_queue_max_packets: int = 32768
    # Loopback-only decoded-record feed for the web portal.
    preview_host: str = "127.0.0.1"
    preview_port: int = 20001
    preview_retention_sec: int = 30
    preview_max_records: int = 4096


@dataclass(frozen=True)
class StorageConfig:
    base_dir: Path = Path("/var/lib/mseed-tcp-server")
    log_dir: Path = Path("/var/log/mseed-tcp-server")
    db_dir_name: str = "devices"
    quarantine_dir_name: str = "quarantine"
    commit_every_packets: int = 1
    # ---- 新增 HDF5 配置 ----
    hdf5_compression: str = "gzip"
    hdf5_compression_opts: int = 6
    hdf5_chunk_size: int = 1024 * 1024


@dataclass(frozen=True)
class ParserConfig:
    min_record_length: int = 256
    max_record_length: int = 131072
    max_buffer_bytes: int = 1048576
    resync_scan_limit: int = 1048576
    validate_with_obspy: bool = True
    store_unvalidated_packets: bool = False
    time_gap_tolerance_samples: float = 1.5
    fixed_record_length: int = 0


@dataclass(frozen=True)
class AppConfig:
    server: ServerConfig
    storage: StorageConfig
    parser: ParserConfig


def _get_bool(cp: configparser.ConfigParser, section: str, key: str, default: bool) -> bool:
    if cp.has_option(section, key):
        return cp.getboolean(section, key)
    return default


def _get_int(cp: configparser.ConfigParser, section: str, key: str, default: int) -> int:
    if cp.has_option(section, key):
        return cp.getint(section, key)
    return default


def _get_float(cp: configparser.ConfigParser, section: str, key: str, default: float) -> float:
    if cp.has_option(section, key):
        return cp.getfloat(section, key)
    return default


def _get_str(cp: configparser.ConfigParser, section: str, key: str, default: str) -> str:
    if cp.has_option(section, key):
        return cp.get(section, key)
    return default


def load_config(path: str | Path | None) -> AppConfig:
    cp = configparser.ConfigParser()
    if path:
        cp.read(path)

    server = ServerConfig(
        host=_get_str(cp, "server", "host", ServerConfig.host),
        port=_get_int(cp, "server", "port", ServerConfig.port),
        request_port=_get_int(cp, "server", "request_port", ServerConfig.request_port),
        backlog=_get_int(cp, "server", "backlog", ServerConfig.backlog),
        recv_size=_get_int(cp, "server", "recv_size", ServerConfig.recv_size),
        socket_timeout_sec=_get_int(cp, "server", "socket_timeout_sec", ServerConfig.socket_timeout_sec),
        tcp_keepalive=_get_bool(cp, "server", "tcp_keepalive", ServerConfig.tcp_keepalive),
        max_clients=_get_int(cp, "server", "max_clients", ServerConfig.max_clients),
        writer_threads=_get_int(cp, "server", "writer_threads", ServerConfig.writer_threads),
        write_queue_max_packets=_get_int(cp, "server", "write_queue_max_packets", ServerConfig.write_queue_max_packets),
        preview_host=_get_str(cp, "server", "preview_host", ServerConfig.preview_host),
        preview_port=_get_int(cp, "server", "preview_port", ServerConfig.preview_port),
        preview_retention_sec=_get_int(cp, "server", "preview_retention_sec", ServerConfig.preview_retention_sec),
        preview_max_records=_get_int(cp, "server", "preview_max_records", ServerConfig.preview_max_records),
    )

    storage = StorageConfig(
        base_dir=Path(_get_str(cp, "storage", "base_dir", str(StorageConfig.base_dir))),
        log_dir=Path(_get_str(cp, "storage", "log_dir", str(StorageConfig.log_dir))),
        db_dir_name=_get_str(cp, "storage", "db_dir_name", StorageConfig.db_dir_name),
        quarantine_dir_name=_get_str(cp, "storage", "quarantine_dir_name", StorageConfig.quarantine_dir_name),
        commit_every_packets=_get_int(cp, "storage", "commit_every_packets", StorageConfig.commit_every_packets),
        # ---- 新增读取 ----
        hdf5_compression=_get_str(cp, "storage", "hdf5_compression", StorageConfig.hdf5_compression),
        hdf5_compression_opts=_get_int(cp, "storage", "hdf5_compression_opts", StorageConfig.hdf5_compression_opts),
        hdf5_chunk_size=_get_int(cp, "storage", "hdf5_chunk_size", StorageConfig.hdf5_chunk_size),
    )

    parser = ParserConfig(
        min_record_length=_get_int(cp, "parser", "min_record_length", ParserConfig.min_record_length),
        max_record_length=_get_int(cp, "parser", "max_record_length", ParserConfig.max_record_length),
        max_buffer_bytes=_get_int(cp, "parser", "max_buffer_bytes", ParserConfig.max_buffer_bytes),
        resync_scan_limit=_get_int(cp, "parser", "resync_scan_limit", ParserConfig.resync_scan_limit),
        validate_with_obspy=_get_bool(cp, "parser", "validate_with_obspy", ParserConfig.validate_with_obspy),
        store_unvalidated_packets=_get_bool(cp, "parser", "store_unvalidated_packets", ParserConfig.store_unvalidated_packets),
        time_gap_tolerance_samples=_get_float(cp, "parser", "time_gap_tolerance_samples", ParserConfig.time_gap_tolerance_samples),
        fixed_record_length=_get_int(cp, "parser", "fixed_record_length", ParserConfig.fixed_record_length),
    )

    return AppConfig(server=server, storage=storage, parser=parser)


def ensure_directories(config: AppConfig) -> None:
    config.storage.base_dir.mkdir(parents=True, exist_ok=True)
    config.storage.log_dir.mkdir(parents=True, exist_ok=True)
    (config.storage.base_dir / config.storage.db_dir_name).mkdir(parents=True, exist_ok=True)
    (config.storage.base_dir / config.storage.quarantine_dir_name).mkdir(parents=True, exist_ok=True)
