#!/usr/bin/env python3
from __future__ import annotations

import argparse
import socket
import time
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Send a miniSEED file to the TCP receiver for testing")
    ap.add_argument("file", help="Input .mseed file")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=18000)
    ap.add_argument("--chunk", type=int, default=1500, help="TCP send chunk size")
    ap.add_argument("--delay", type=float, default=0.0, help="Delay between chunks in seconds")
    args = ap.parse_args()

    data = Path(args.file).read_bytes()
    sent = 0
    with socket.create_connection((args.host, args.port), timeout=10) as s:
        for i in range(0, len(data), args.chunk):
            part = data[i:i + args.chunk]
            s.sendall(part)
            sent += len(part)
            if args.delay > 0:
                time.sleep(args.delay)
    print(f"sent {sent} bytes to {args.host}:{args.port}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
