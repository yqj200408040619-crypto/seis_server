from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import hashlib
import logging
import struct
from typing import Optional

from .config import ParserConfig

LOG = logging.getLogger(__name__)

QUALITY_CODES = {ord("D"), ord("R"), ord("Q"), ord("M"), ord(" ")}


@dataclass(frozen=True)
class RecordLengthInfo:
    length: int
    endian: str
    exponent: Optional[int]
    blockette_offset: Optional[int]
    source: str


@dataclass(frozen=True)
class MSeedHeader:
    start_unix: float
    end_unix: float | None
    network: str
    station: str
    location: str
    channel: str
    sampling_rate: float | None
    npts: int | None
    quality: str
    record_length: int
    sha256: str


def _ascii_strip(raw: bytes) -> str:
    return raw.decode("ascii", errors="ignore").strip()


def get_sequence_number(packet: bytes) -> int:
    raw = packet[0:6]
    try:
        return int(raw.decode("ascii").strip())
    except Exception:
        return -1


def packet_sha256(packet: bytes) -> str:
    return hashlib.sha256(packet).hexdigest()


def is_plausible_record_start(buf: bytes, offset: int = 0) -> bool:
    if len(buf) - offset < 48:
        return False

    head = buf[offset:offset + 48]
    if not all(48 <= c <= 57 or c == 32 for c in head[0:6]):
        return False
    if head[6] not in QUALITY_CODES:
        return False

    # Station/location/channel/network fields should normally be printable ASCII.
    for start, end in ((8, 13), (13, 15), (15, 18), (18, 20)):
        part = head[start:end]
        if not all(32 <= c <= 126 for c in part):
            return False

    # First blockette offset is normally 48 or larger if blockettes exist.
    offsets = []
    for endian in (">", "<"):
        try:
            offsets.append(struct.unpack(endian + "H", head[46:48])[0])
        except Exception:
            pass
    if not any(o == 0 or 48 <= o <= 8192 for o in offsets):
        return False

    return True


def find_next_record_start(buf: bytes, scan_limit: int) -> int | None:
    max_i = min(len(buf) - 48, scan_limit)
    for i in range(1, max_i + 1):
        if is_plausible_record_start(buf, i):
            return i
    return None


def _read_first_blockette_offset(buf: bytes, endian: str) -> int:
    return struct.unpack(endian + "H", buf[46:48])[0]


def get_record_length(buf: bytes, cfg: ParserConfig) -> RecordLengthInfo | None:
    """
    Return miniSEED record length if enough header/blockette bytes are available.

    miniSEED 2.x usually stores record length in Blockette 1000 as an exponent:
    record_length = 2 ** exponent. If cfg.fixed_record_length is set, the fixed
    length is used only after the start looks plausible.
    """
    if len(buf) < 48:
        return None

    if not is_plausible_record_start(buf, 0):
        raise ValueError("buffer does not start with a plausible miniSEED record header")

    if cfg.fixed_record_length > 0:
        length = cfg.fixed_record_length
        if length < cfg.min_record_length or length > cfg.max_record_length:
            raise ValueError(f"fixed_record_length out of allowed range: {length}")
        if length & (length - 1) != 0:
            raise ValueError(f"fixed_record_length is not a power of two: {length}")
        return RecordLengthInfo(length=length, endian="?", exponent=None, blockette_offset=None, source="fixed")

    last_need_more = False
    for endian in (">", "<"):
        try:
            first_offset = _read_first_blockette_offset(buf, endian)
            if first_offset == 0:
                continue
            if first_offset < 48 or first_offset > cfg.max_record_length:
                continue
            if len(buf) < first_offset + 8:
                last_need_more = True
                continue

            offset = first_offset
            visited = 0
            while visited < 32:
                if offset + 8 > len(buf):
                    last_need_more = True
                    break

                blockette_type, next_offset = struct.unpack(endian + "HH", buf[offset:offset + 4])

                if blockette_type == 1000:
                    exponent = buf[offset + 6]
                    length = 1 << exponent
                    if length < cfg.min_record_length or length > cfg.max_record_length:
                        raise ValueError(f"invalid miniSEED record length exponent={exponent}, length={length}")
                    if length & (length - 1) != 0:
                        raise ValueError(f"miniSEED record length is not power of two: {length}")
                    return RecordLengthInfo(
                        length=length,
                        endian=endian,
                        exponent=exponent,
                        blockette_offset=offset,
                        source="blockette1000",
                    )

                if next_offset == 0:
                    break
                if next_offset <= offset:
                    break
                if next_offset > cfg.max_record_length:
                    break
                if len(buf) < next_offset + 8:
                    last_need_more = True
                    break

                offset = next_offset
                visited += 1
        except ValueError:
            raise
        except Exception:
            continue

    if last_need_more:
        return None

    raise ValueError("Blockette 1000 not found; cannot determine miniSEED record length")


def parse_header_with_obspy(packet: bytes, record_length: int) -> MSeedHeader:
    """Validate and parse one complete miniSEED record with ObsPy."""
    try:
        from obspy import read  # imported lazily so startup errors are clearer
    except Exception as exc:
        raise RuntimeError("ObsPy is required but cannot be imported") from exc

    try:
        st = read(BytesIO(packet), format="MSEED", headonly=True)
        if len(st) < 1:
            raise ValueError("ObsPy returned an empty Stream")
        tr = st[0]
        stats = tr.stats
        start_unix = float(stats.starttime.timestamp)
        npts = int(stats.npts) if getattr(stats, "npts", None) is not None else None
        sr = float(stats.sampling_rate) if getattr(stats, "sampling_rate", None) else None
        end_unix = None
        if sr and npts is not None and npts > 0:
            # The next record should usually start around start + npts / sampling_rate.
            end_unix = start_unix + (npts / sr)

        return MSeedHeader(
            start_unix=start_unix,
            end_unix=end_unix,
            network=str(getattr(stats, "network", "") or "").strip(),
            station=str(getattr(stats, "station", "") or "").strip(),
            location=str(getattr(stats, "location", "") or "").strip(),
            channel=str(getattr(stats, "channel", "") or "").strip(),
            sampling_rate=sr,
            npts=npts,
            quality=chr(packet[6]) if len(packet) > 6 else "",
            record_length=record_length,
            sha256=packet_sha256(packet),
        )
    except Exception as exc:
        raise ValueError(f"ObsPy miniSEED validation failed: {exc}") from exc


def parse_header_fallback(packet: bytes, record_length: int) -> MSeedHeader:
    """
    Minimal non-ObsPy fallback. It does not decode start time reliably; use only
    if store_unvalidated_packets=true. Validated deployment should use ObsPy.
    """
    return MSeedHeader(
        start_unix=-1.0,
        end_unix=None,
        network=_ascii_strip(packet[18:20]),
        station=_ascii_strip(packet[8:13]),
        location=_ascii_strip(packet[13:15]),
        channel=_ascii_strip(packet[15:18]),
        sampling_rate=None,
        npts=None,
        quality=chr(packet[6]) if len(packet) > 6 else "",
        record_length=record_length,
        sha256=packet_sha256(packet),
    )


def parse_and_validate_packet(packet: bytes, record_length: int, cfg: ParserConfig) -> MSeedHeader:
    if cfg.validate_with_obspy:
        try:
            return parse_header_with_obspy(packet, record_length)
        except Exception:
            if not cfg.store_unvalidated_packets:
                raise
            LOG.exception("ObsPy validation failed; storing packet with fallback header because store_unvalidated_packets=true")
            return parse_header_fallback(packet, record_length)
    return parse_header_fallback(packet, record_length)
