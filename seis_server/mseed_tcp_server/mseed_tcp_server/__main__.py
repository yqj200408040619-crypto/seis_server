from __future__ import annotations

import argparse
import logging
import sys

from .config import ensure_directories, load_config
from .logging_setup import setup_logging
from .server import run_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TCP miniSEED receiver for seismic instruments")
    parser.add_argument("--config", default="/etc/mseed-tcp-server/server.ini", help="Path to server.ini")
    parser.add_argument("--log-level", default="INFO", help="DEBUG, INFO, WARNING, ERROR")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    ensure_directories(config)
    setup_logging(config.storage.log_dir, args.log_level)

    logging.getLogger(__name__).info("loaded config from %s", args.config)
    run_server(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
