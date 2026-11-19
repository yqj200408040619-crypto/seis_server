from __future__ import annotations

import glob
import math
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import numpy as np
from obspy import Stream, UTCDateTime, read


DB_NAME_RE = re.compile(r"^(?P<client_ip>.+)_(?P<server_port>\d+)_(?P<instrument_type>[^_]+)_(?P<instrument_serial>[^_]+)\.db$")


@dataclass
class DiscoveredDevice:
    label: str
    db_path: str
    device_key: str
    instrument_type: str | None
    instrument_serial: str | None
    client_ip: str | None
    server_port: int | None


def safe_receiver_db_path(receiver_db_dir: str, db_path: str) -> str:
    base = os.path.realpath(receiver_db_dir)
    target = os.path.realpath(db_path)
    if not target.startswith(base + os.sep):
        raise PermissionError("Database path is outside receiver database directory.")
    if not target.endswith(".db"):
        raise ValueError("Only .db receiver databases are allowed.")
    return target


def connect_receiver_db(db_path: str, readonly: bool = True) -> sqlite3.Connection:
    if readonly:
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=10)
    else:
        conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table_name})")}


def infer_from_filename(db_path: str) -> dict[str, Any]:
    name = os.path.basename(db_path)
    match = DB_NAME_RE.match(name)
    if not match:
        return {
            "client_ip": None,
            "server_port": None,
            "instrument_type": None,
            "instrument_serial": None,
            "device_key": os.path.splitext(name)[0],
        }
    d = match.groupdict()
    return {
        "client_ip": d["client_ip"],
        "server_port": int(d["server_port"]),
        "instrument_type": d["instrument_type"],
        "instrument_serial": d["instrument_serial"],
        "device_key": f"{d['instrument_type']}_{d['instrument_serial']}",
    }


def discover_devices(receiver_db_dir: str) -> list[DiscoveredDevice]:
    devices: list[DiscoveredDevice] = []
    for db_path in sorted(glob.glob(os.path.join(receiver_db_dir, "*.db"))):
        try:
            meta = infer_from_filename(db_path)
            with connect_receiver_db(db_path, readonly=True) as conn:
                if not table_exists(conn, "packets"):
                    continue
                packet_cols = columns(conn, "packets")
                if "device_key" in packet_cols:
                    rows = conn.execute(
                        """
                        SELECT DISTINCT device_key, instrument_type, instrument_serial
                        FROM packets
                        WHERE device_key IS NOT NULL
                        ORDER BY device_key
                        """
                    ).fetchall()
                    if rows:
                        for r in rows:
                            device_key = r["device_key"] or meta["device_key"]
                            instrument_type = r["instrument_type"] or meta["instrument_type"]
                            instrument_serial = r["instrument_serial"] or meta["instrument_serial"]
                            label = f"{instrument_type or 'DEV'}-{instrument_serial or device_key}"
                            devices.append(DiscoveredDevice(
                                label=label,
                                db_path=db_path,
                                device_key=device_key,
                                instrument_type=instrument_type,
                                instrument_serial=instrument_serial,
                                client_ip=meta["client_ip"],
                                server_port=meta["server_port"],
                            ))
                        continue
                rows = conn.execute(
                    "SELECT DISTINCT network, station FROM packets WHERE network IS NOT NULL AND station IS NOT NULL ORDER BY network, station"
                ).fetchall()
                if rows:
                    for r in rows:
                        instrument_type = r["network"] or meta["instrument_type"]
                        instrument_serial = r["station"] or meta["instrument_serial"]
                        device_key = f"{instrument_type}_{instrument_serial}"
                        devices.append(DiscoveredDevice(
                            label=f"{instrument_type}-{instrument_serial}",
                            db_path=db_path,
                            device_key=device_key,
                            instrument_type=instrument_type,
                            instrument_serial=instrument_serial,
                            client_ip=meta["client_ip"],
                            server_port=meta["server_port"],
                        ))
                else:
                    devices.append(DiscoveredDevice(
                        label=str(meta["device_key"]),
                        db_path=db_path,
                        device_key=str(meta["device_key"]),
                        instrument_type=meta["instrument_type"],
                        instrument_serial=meta["instrument_serial"],
                        client_ip=meta["client_ip"],
                        server_port=meta["server_port"],
                    ))
        except Exception:
            continue
    return devices


def list_components(db_path: str, device_key: str | None = None) -> list[dict[str, Any]]:
    with connect_receiver_db(db_path, readonly=True) as conn:
        if not table_exists(conn, "packets"):
            return []
        cols = columns(conn, "packets")
        if "component_key" in cols:
            where = "WHERE component_key IS NOT NULL"
            args: list[Any] = []
            if device_key and "device_key" in cols:
                where += " AND device_key = ?"
                args.append(device_key)
            sql = f"""
                SELECT component_key AS component, stream_key AS stream_key,
                       COUNT(*) AS packets, MAX(start_unix) AS last_start
                FROM packets
                {where}
                GROUP BY component_key, stream_key
                ORDER BY component_key
            """
            return [dict(r) for r in conn.execute(sql, args)]
        where = "WHERE channel IS NOT NULL"
        args = []
        if device_key:
            parts = device_key.split("_", 1)
            if len(parts) == 2:
                where += " AND network = ? AND station = ?"
                args.extend(parts)
        sql = f"""
            SELECT channel AS component,
                   (network || '.' || station || '.' || location || '.' || channel) AS stream_key,
                   COUNT(*) AS packets, MAX(start_unix) AS last_start
            FROM packets
            {where}
            GROUP BY network, station, location, channel
            ORDER BY channel
        """
        return [dict(r) for r in conn.execute(sql, args)]


def device_summary(db_path: str, device_key: str | None = None) -> dict[str, Any]:
    comps = list_components(db_path, device_key)
    total_packets = sum(int(c.get("packets") or 0) for c in comps)
    last_start = max((float(c["last_start"]) for c in comps if c.get("last_start") is not None), default=None)
    return {
        "components": comps,
        "total_packets": total_packets,
        "last_start": last_start,
    }


def _build_packet_query(conn: sqlite3.Connection, device_key: str, component: str | None, start_unix: float, end_unix: float, limit: int) -> tuple[str, list[Any]]:
    cols = columns(conn, "packets")
    where = []
    args: list[Any] = []

    if "device_key" in cols:
        where.append("device_key = ?")
        args.append(device_key)
    else:
        parts = device_key.split("_", 1)
        if len(parts) == 2 and "network" in cols and "station" in cols:
            where.append("network = ?")
            where.append("station = ?")
            args.extend(parts)

    if component:
        if "component_key" in cols:
            where.append("component_key = ?")
        else:
            where.append("channel = ?")
        args.append(component)

    if "end_unix" in cols:
        where.append("start_unix <= ?")
        where.append("end_unix >= ?")
        args.extend([end_unix, start_unix])
    else:
        where.append("start_unix BETWEEN ? AND ?")
        args.extend([start_unix - 10, end_unix + 10])

    where_clause = " AND ".join(where) if where else "1=1"
    sql = f"""
        SELECT raw_mseed, start_unix, seq_no, packet_len, network, station, location, channel
        FROM packets
        WHERE {where_clause}
        ORDER BY start_unix, seq_no
        LIMIT ?
    """
    args.append(limit)
    return sql, args


def minmax_downsample(times: np.ndarray, values: np.ndarray, max_points: int) -> tuple[np.ndarray, np.ndarray]:
    if len(values) <= max_points:
        return times, values
    if max_points < 100:
        max_points = 100
    bucket_size = int(math.ceil(len(values) / max(1, max_points // 2)))
    out_t: list[float] = []
    out_y: list[float] = []
    for start in range(0, len(values), bucket_size):
        end = min(start + bucket_size, len(values))
        chunk = values[start:end]
        if len(chunk) == 0:
            continue
        local_min = int(np.nanargmin(chunk))
        local_max = int(np.nanargmax(chunk))
        idx_min = start + local_min
        idx_max = start + local_max
        if idx_min <= idx_max:
            indices = [idx_min, idx_max]
        else:
            indices = [idx_max, idx_min]
        for idx in indices:
            out_t.append(float(times[idx]))
            out_y.append(float(values[idx]))
    return np.asarray(out_t), np.asarray(out_y)


def read_waveform(
    db_path: str,
    *,
    device_key: str,
    component: str | None,
    start_unix: float,
    end_unix: float,
    max_points: int,
    max_records: int,
) -> dict[str, Any]:
    if end_unix <= start_unix:
        raise ValueError("end_unix must be greater than start_unix")
    packet_count = 0
    raw_bytes = 0
    st = Stream()
    with connect_receiver_db(db_path, readonly=True) as conn:
        sql, args = _build_packet_query(conn, device_key, component, start_unix, end_unix, max_records)
        for row in conn.execute(sql, args):
            raw = bytes(row["raw_mseed"])
            raw_bytes += len(raw)
            packet_count += 1
            try:
                st += read(BytesIO(raw), format="MSEED")
            except Exception:
                continue

    if packet_count == 0 or len(st) == 0:
        return {
            "points": [],
            "traces": [],
            "packet_count": packet_count,
            "raw_bytes": raw_bytes,
            "truncated_records": False,
            "generated_at": time.time(),
        }

    try:
        st.merge(method=1, fill_value="interpolate")
    except Exception:
        pass

    traces_payload: list[dict[str, Any]] = []
    total_points = 0
    for tr in st:
        sr = float(tr.stats.sampling_rate)
        npts = int(tr.stats.npts)
        if npts <= 0 or sr <= 0:
            continue
        trace_start = float(tr.stats.starttime.timestamp)
        t = trace_start + np.arange(npts, dtype=np.float64) / sr
        y = np.asarray(tr.data, dtype=np.float64)
        mask = (t >= start_unix) & (t <= end_unix)
        if not np.any(mask):
            continue
        t = t[mask]
        y = y[mask]
        t, y = minmax_downsample(t, y, max_points)
        points = [{"t": float(tt), "y": float(yy)} for tt, yy in zip(t, y)]
        total_points += len(points)
        stream_key = f"{tr.stats.network}.{tr.stats.station}.{tr.stats.location}.{tr.stats.channel}"
        traces_payload.append({
            "stream_key": stream_key,
            "component": tr.stats.channel,
            "sampling_rate": sr,
            "npts_original": npts,
            "points": points,
        })

    return {
        "points": traces_payload[0]["points"] if len(traces_payload) == 1 else [],
        "traces": traces_payload,
        "packet_count": packet_count,
        "raw_bytes": raw_bytes,
        "point_count": total_points,
        "truncated_records": packet_count >= max_records,
        "generated_at": time.time(),
    }


def parse_datetime_or_unix(value: str | None, default: float | None = None) -> float:
    if value is None or value == "":
        if default is None:
            raise ValueError("Missing time value")
        return default
    try:
        return float(value)
    except ValueError:
        pass
    try:
        return float(UTCDateTime(value).timestamp)
    except Exception as exc:
        raise ValueError(f"Invalid time value: {value}") from exc
