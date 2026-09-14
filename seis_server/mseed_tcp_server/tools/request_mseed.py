#!/usr/bin/env python3
"""Request raw miniSEED data from an mseed-tcp-server."""
from __future__ import annotations

import argparse
import socket
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("start_time", help="UTC YYYYMMDDHHMMSS")
    parser.add_argument("end_time", help="UTC YYYYMMDDHHMMSS")
    parser.add_argument("device_number")
    parser.add_argument("output", type=Path)
    parser.add_argument("--port", type=int, default=20000)
    args = parser.parse_args()
    request = f"START,{args.start_time},{args.end_time},{args.device_number},END\n".encode("ascii")
    with socket.create_connection((args.host, args.port)) as sock, args.output.open("wb") as output:
        sock.sendall(request)
        data = bytearray()
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            data.extend(chunk)
        if data.startswith(b"ERR "):
            raise SystemExit(bytes(data).decode("ascii", "replace").strip())
        output.write(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
