#!/usr/bin/env python3
"""Generate synthetic miniSEED test data for end-to-end load testing.

Requires obspy (same version the project already depends on). Produces one
.mseed file per (station, channel) with a configurable number of 512-byte
records, which the TCP load driver streams to the receiver.

Usage:
    python gen_mseed.py --out /tmp/mseed_fixtures \\
        --stations 8 --channels 3 --records 2000 --rate 100
"""
from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, help="output directory for .mseed files")
    ap.add_argument("--network", default="XX")
    ap.add_argument("--stations", type=int, default=8)
    ap.add_argument("--channels", type=int, default=3, help="channels per station (EHZ/EHN/EHE...)")
    ap.add_argument("--records", type=int, default=2000, help="records per channel")
    ap.add_argument("--rate", type=float, default=100.0, help="sampling rate Hz")
    ap.add_argument("--reclen", type=int, default=512, help="miniSEED record length bytes")
    args = ap.parse_args()

    try:
        import numpy as np
        from obspy import Stream, Trace, UTCDateTime
    except ImportError as exc:
        print(f"ERROR: obspy/numpy required to generate fixtures: {exc}", file=sys.stderr)
        print("Install project deps first: pip install -r mseed_tcp_server/requirements.txt", file=sys.stderr)
        return 2

    os.makedirs(args.out, exist_ok=True)
    chan_codes = ["EHZ", "EHN", "EHE", "HHZ", "HHN", "HHE"][: args.channels]
    # samples per 512-byte Steim2 record is ~ (reclen-64)*... ; we just make
    # each Trace long enough to span many records at the chosen reclen.
    samples_per_record = max(1, (args.reclen - 64) * 2)
    total_samples = samples_per_record * args.records

    t0 = UTCDateTime(2024, 1, 1)
    made = 0
    for s in range(args.stations):
        station = f"ST{s:03d}"
        for cha in chan_codes:
            data = (np.random.default_rng(s * 17 + hash(cha) % 97)
                    .integers(-10000, 10000, size=total_samples)).astype(np.int32)
            tr = Trace(data=data)
            tr.stats.network = args.network
            tr.stats.station = station
            tr.stats.location = ""
            tr.stats.channel = cha
            tr.stats.sampling_rate = args.rate
            tr.stats.starttime = t0
            st = Stream([tr])
            path = os.path.join(args.out, f"{args.network}_{station}_{cha}.mseed")
            st.write(path, format="MSEED", reclen=args.reclen, encoding="STEIM2")
            made += 1

    total_bytes = args.stations * len(chan_codes) * args.records * args.reclen
    print(f"generated {made} files in {args.out} "
          f"(~{total_bytes/1e6:.1f} MB, {args.stations} stations x {len(chan_codes)} channels "
          f"x {args.records} records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
