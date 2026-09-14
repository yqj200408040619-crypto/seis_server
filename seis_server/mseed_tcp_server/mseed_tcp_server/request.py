from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re

import h5py


class RequestError(ValueError):
    """A client supplied a malformed or unsatisfiable data request."""


@dataclass(frozen=True)
class DataRequest:
    start_unix: float
    end_unix: float
    device_number: str


def parse_request(data: bytes | str) -> DataRequest:
    if isinstance(data, bytes):
        try:
            text = data.decode("ascii")
        except UnicodeDecodeError as exc:
            raise RequestError("request must be ASCII") from exc
    else:
        text = data
    parts = text.rstrip("\r\n").split(",")
    if len(parts) != 5 or parts[0] != "START" or parts[4] != "END" or any(not part for part in parts):
        raise RequestError("expected START,YYYYMMDDHHMMSS,YYYYMMDDHHMMSS,DDDDD,END")
    try:
        start = datetime.strptime(parts[1], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).timestamp()
        end = datetime.strptime(parts[2], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).timestamp()
    except ValueError as exc:
        raise RequestError("times must use UTC format YYYYMMDDHHMMSS") from exc
    if end <= start:
        raise RequestError("end time must be greater than start time")
    device = parts[3]
    if re.fullmatch(r"\d{5}", device) is None:
        raise RequestError("device_number must be exactly five digits")
    return DataRequest(start, end, device)


def _attr_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace").rstrip("\x00")
    return str(value)


def resolve_device(h5_root: Path, device_number: str) -> Path:
    paths = sorted(h5_root.glob("*.h5"))
    if not paths:
        raise RequestError("no devices available")
    for path in paths:
        if path.stem == device_number or path.stem.endswith("_SS_" + device_number) or path.stem.endswith("_" + device_number):
            return path
        try:
            with h5py.File(path, "r", libver="latest", swmr=True) as f:
                values = (f.attrs.get("device_id"), f.attrs.get("device_key"), f.attrs.get("instrument_serial"))
                if any(_attr_text(v) == device_number for v in values if v is not None):
                    return path
        except OSError:
            continue
    for path in paths:
        try:
            with h5py.File(path, "r", libver="latest", swmr=True) as f:
                if _attr_text(f.attrs.get("instrument_serial", "")) == device_number:
                    return path
        except OSError:
            continue
    raise RequestError(f"unknown device_number: {device_number}")


def export_mseed(h5_root: Path, request: DataRequest) -> bytes:
    """Return raw miniSEED records overlapping the requested interval."""
    path = resolve_device(h5_root, request.device_number)
    try:
        source = h5py.File(path, "r", libver="latest", swmr=True)
    except OSError:
        source = h5py.File(path, "r")
    records: list[tuple[float, int, bytes]] = []
    with source:
        for stream_key in sorted(source.keys()):
            group = source[stream_key]
            if not isinstance(group, h5py.Group):
                continue
            for name in sorted(group.keys()):
                dataset = group[name]
                if not isinstance(dataset, h5py.Dataset):
                    continue
                start = float(dataset.attrs.get("start_unix", -1.0))
                end = float(dataset.attrs.get("end_unix", start))
                if start < request.end_unix and end > request.start_unix:
                    raw = dataset.attrs.get("raw_mseed")
                    if raw is not None:
                        packet = bytes(raw)
                        if packet:
                            records.append((start, int(dataset.attrs.get("seq_no", -1)), packet))
    records.sort(key=lambda item: (item[0], item[1]))
    return b"".join(packet for _, _, packet in records)
