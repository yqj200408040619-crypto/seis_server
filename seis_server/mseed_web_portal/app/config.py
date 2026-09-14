from __future__ import annotations

import configparser
import os
from dataclasses import dataclass


DEFAULT_CONFIG_PATH = os.environ.get("MSEED_WEB_CONFIG", "/etc/mseed-web-portal/portal.ini")


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    workers: int
    receiver_db_dir: str
    app_db: str
    log_dir: str
    secret_key: str
    session_max_age_seconds: int
    brand: str
    refresh_seconds: int
    latest_default_seconds: int
    max_plot_points: int
    max_query_records: int
    receiver_preview_url: str


def load_settings(path: str = DEFAULT_CONFIG_PATH) -> Settings:
    parser = configparser.ConfigParser()
    read_files = parser.read(path)
    if not read_files:
        raise FileNotFoundError(f"Configuration file not found: {path}")

    return Settings(
        host=parser.get("server", "host", fallback="127.0.0.1"),
        port=parser.getint("server", "port", fallback=8080),
        workers=parser.getint("server", "workers", fallback=1),
        receiver_db_dir=os.path.abspath(parser.get("paths", "receiver_db_dir", fallback="/var/lib/mseed-tcp-server/devices")),
        app_db=os.path.abspath(parser.get("paths", "app_db", fallback="/var/lib/mseed-web-portal/app.db")),
        log_dir=os.path.abspath(parser.get("paths", "log_dir", fallback="/var/log/mseed-web-portal")),
        secret_key=parser.get("security", "secret_key", fallback="CHANGE_ME"),
        session_max_age_seconds=parser.getint("security", "session_max_age_seconds", fallback=86400),
        brand=parser.get("ui", "brand", fallback="Seismic Data Portal"),
        refresh_seconds=parser.getint("ui", "refresh_seconds", fallback=2),
        latest_default_seconds=parser.getint("ui", "latest_default_seconds", fallback=120),
        max_plot_points=parser.getint("ui", "max_plot_points", fallback=6000),
        max_query_records=parser.getint("ui", "max_query_records", fallback=20000),
        receiver_preview_url=parser.get("receiver", "preview_url", fallback="http://127.0.0.1:20001/preview"),
    )
