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

# STAGE1_PRODUCT_PATCH_DATA_READER

def _stage1_has_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
    return col in columns(conn, table)


def _stage1_now() -> float:
    return time.time()


def device_summary(db_path: str, device_key: str | None = None) -> dict[str, Any]:  # overrides earlier definition
    comps = list_components(db_path, device_key)
    now = _stage1_now()
    total_packets = sum(int(c.get("packets") or 0) for c in comps)
    last_start = max((float(c["last_start"]) for c in comps if c.get("last_start") is not None), default=None)
    one_hour_packets = 0
    last_recv = None
    first_start = None
    gap_count = 0
    duplicate_count = 0
    bad_packet_count = 0
    component_status: list[dict[str, Any]] = []
    with connect_receiver_db(db_path, readonly=True) as conn:
        if table_exists(conn, "packets"):
            cols = columns(conn, "packets")
            where = []
            args: list[Any] = []
            if device_key and "device_key" in cols:
                where.append("device_key = ?")
                args.append(device_key)
            elif device_key and "network" in cols and "station" in cols and "_" in device_key:
                a, b = device_key.split("_", 1)
                where.extend(["network = ?", "station = ?"])
                args.extend([a, b])
            wc = " AND ".join(where) if where else "1=1"
            row = conn.execute(f"SELECT COUNT(*) AS n, MIN(start_unix) AS first_start, MAX(start_unix) AS last_start FROM packets WHERE {wc}", args).fetchone()
            if row:
                total_packets = int(row["n"] or total_packets)
                first_start = float(row["first_start"]) if row["first_start"] is not None else None
                last_start = float(row["last_start"]) if row["last_start"] is not None else last_start
            if "recv_unix" in cols:
                row = conn.execute(f"SELECT MAX(recv_unix) AS last_recv, COUNT(*) AS n1h FROM packets WHERE {wc} AND recv_unix >= ?", args + [now - 3600]).fetchone()
                if row:
                    last_recv = float(row["last_recv"]) if row["last_recv"] is not None else None
                    one_hour_packets = int(row["n1h"] or 0)
            else:
                row = conn.execute(f"SELECT COUNT(*) AS n1h FROM packets WHERE {wc} AND start_unix >= ?", args + [now - 3600]).fetchone()
                one_hour_packets = int(row["n1h"] or 0) if row else 0
            comp_col = "component_key" if "component_key" in cols else "channel"
            if comp_col in cols:
                rows = conn.execute(f"SELECT {comp_col} AS component, COUNT(*) AS packets, MAX(start_unix) AS last_start" + (", MAX(recv_unix) AS last_recv" if "recv_unix" in cols else ", NULL AS last_recv") + f" FROM packets WHERE {wc} GROUP BY {comp_col} ORDER BY {comp_col}", args).fetchall()
                for r in rows:
                    c_last_recv = float(r["last_recv"]) if r["last_recv"] is not None else None
                    c_last_start = float(r["last_start"]) if r["last_start"] is not None else None
                    c_ref = c_last_recv if c_last_recv is not None else c_last_start
                    c_age = now - c_ref if c_ref is not None else None
                    component_status.append({
                        "component": r["component"],
                        "packets": int(r["packets"] or 0),
                        "last_start": c_last_start,
                        "last_recv": c_last_recv,
                        "age_seconds": c_age,
                        "status": "online" if c_age is not None and c_age <= 300 else ("stale" if c_age is not None and c_age <= 3600 else "offline"),
                    })
        # Quality tables are optional and depend on receiver version.
        if table_exists(conn, "gaps"):
            try:
                gap_count = int(conn.execute("SELECT COUNT(*) AS n FROM gaps").fetchone()["n"] or 0)
            except Exception:
                gap_count = 0
        if table_exists(conn, "duplicates"):
            try:
                duplicate_count = int(conn.execute("SELECT COUNT(*) AS n FROM duplicates").fetchone()["n"] or 0)
            except Exception:
                duplicate_count = 0
        if table_exists(conn, "bad_packets"):
            try:
                bad_packet_count = int(conn.execute("SELECT COUNT(*) AS n FROM bad_packets").fetchone()["n"] or 0)
            except Exception:
                bad_packet_count = 0
    ref_time = last_recv if last_recv is not None else last_start
    age_seconds = now - ref_time if ref_time is not None else None
    status = "online" if age_seconds is not None and age_seconds <= 300 else ("stale" if age_seconds is not None and age_seconds <= 3600 else "offline")
    expected = {"BHZ", "BHN", "BHE"}
    got = {str(c.get("component")) for c in component_status or comps}
    missing_components = sorted(expected - got)
    return {
        "components": comps,
        "component_status": component_status,
        "total_packets": total_packets,
        "one_hour_packets": one_hour_packets,
        "first_start": first_start,
        "last_start": last_start,
        "last_recv": last_recv,
        "age_seconds": age_seconds,
        "status": status,
        "missing_components": missing_components,
        "gap_count": gap_count,
        "duplicate_count": duplicate_count,
        "bad_packet_count": bad_packet_count,
    }


def quality_summary(db_path: str, device_key: str | None = None, limit: int = 100) -> dict[str, Any]:
    result: dict[str, Any] = {
        "gaps": [], "duplicates": [], "bad_packets": [],
        "gap_count": 0, "duplicate_count": 0, "bad_packet_count": 0,
        "generated_at": time.time(),
    }
    with connect_receiver_db(db_path, readonly=True) as conn:
        if table_exists(conn, "gaps"):
            cols = columns(conn, "gaps")
            order_col = "detected_unix" if "detected_unix" in cols else ("created_at" if "created_at" in cols else "rowid")
            rows = conn.execute(f"SELECT * FROM gaps ORDER BY {order_col} DESC LIMIT ?", (limit,)).fetchall()
            result["gaps"] = [dict(r) for r in rows]
            result["gap_count"] = int(conn.execute("SELECT COUNT(*) AS n FROM gaps").fetchone()["n"] or 0)
        if table_exists(conn, "duplicates"):
            cols = columns(conn, "duplicates")
            order_col = "detected_unix" if "detected_unix" in cols else ("created_at" if "created_at" in cols else "rowid")
            rows = conn.execute(f"SELECT * FROM duplicates ORDER BY {order_col} DESC LIMIT ?", (limit,)).fetchall()
            result["duplicates"] = [dict(r) for r in rows]
            result["duplicate_count"] = int(conn.execute("SELECT COUNT(*) AS n FROM duplicates").fetchone()["n"] or 0)
        if table_exists(conn, "bad_packets"):
            cols = columns(conn, "bad_packets")
            order_col = "recv_unix" if "recv_unix" in cols else ("created_at" if "created_at" in cols else "rowid")
            rows = conn.execute(f"SELECT * FROM bad_packets ORDER BY {order_col} DESC LIMIT ?", (limit,)).fetchall()
            result["bad_packets"] = [dict(r) for r in rows]
            result["bad_packet_count"] = int(conn.execute("SELECT COUNT(*) AS n FROM bad_packets").fetchone()["n"] or 0)
    return result


def export_mseed_bytes(
    db_path: str,
    *,
    device_key: str,
    components: list[str] | None,
    start_unix: float,
    end_unix: float,
    max_records: int = 200000,
) -> tuple[bytes, int]:
    if end_unix <= start_unix:
        raise ValueError("End time must be greater than start time")
    chunks: list[bytes] = []
    count = 0
    with connect_receiver_db(db_path, readonly=True) as conn:
        cols = columns(conn, "packets")
        where: list[str] = []
        args: list[Any] = []
        if "device_key" in cols:
            where.append("device_key = ?")
            args.append(device_key)
        elif "_" in device_key and "network" in cols and "station" in cols:
            a, b = device_key.split("_", 1)
            where.extend(["network = ?", "station = ?"])
            args.extend([a, b])
        if components:
            comp_col = "component_key" if "component_key" in cols else "channel"
            placeholders = ",".join("?" for _ in components)
            where.append(f"{comp_col} IN ({placeholders})")
            args.extend(components)
        if "end_unix" in cols:
            where.append("start_unix <= ?")
            where.append("end_unix >= ?")
            args.extend([end_unix, start_unix])
        else:
            where.append("start_unix BETWEEN ? AND ?")
            args.extend([start_unix - 10, end_unix + 10])
        wc = " AND ".join(where) if where else "1=1"
        order = "start_unix, seq_no" if "seq_no" in cols else "start_unix"
        sql = f"SELECT raw_mseed FROM packets WHERE {wc} ORDER BY {order} LIMIT ?"
        args.append(max_records)
        for row in conn.execute(sql, args):
            chunks.append(bytes(row["raw_mseed"]))
            count += 1
    return b"".join(chunks), count

# STAGE3_EXPORT_HELPERS

def _stage3_iso_utc(ts: float | None) -> str:
    if ts is None:
        return ""
    try:
        return UTCDateTime(float(ts)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-3] + "Z"
    except Exception:
        return str(ts)


def _stage3_packet_where(conn: sqlite3.Connection, device_key: str, components: list[str] | None, start_unix: float, end_unix: float) -> tuple[str, list[Any]]:
    cols = columns(conn, "packets")
    where: list[str] = []
    args: list[Any] = []

    if "device_key" in cols:
        where.append("device_key = ?")
        args.append(device_key)
    elif "_" in device_key and "network" in cols and "station" in cols:
        a, b = device_key.split("_", 1)
        where.extend(["network = ?", "station = ?"])
        args.extend([a, b])

    if components:
        comp_col = "component_key" if "component_key" in cols else "channel"
        placeholders = ",".join("?" for _ in components)
        where.append(f"{comp_col} IN ({placeholders})")
        args.extend(components)

    # Select all packets that overlap the requested interval.
    if "end_unix" in cols:
        where.append("start_unix <= ?")
        where.append("end_unix >= ?")
        args.extend([end_unix, start_unix])
    else:
        where.append("start_unix BETWEEN ? AND ?")
        args.extend([start_unix - 10, end_unix + 10])

    return (" AND ".join(where) if where else "1=1"), args


def export_mseed_bytes_stage3(
    db_path: str,
    *,
    device_key: str,
    components: list[str] | None,
    start_unix: float,
    end_unix: float,
    max_records: int = 500000,
) -> dict[str, Any]:
    """Return raw miniSEED bytes and a compact manifest.

    Gaps do not block export. Existing packets in the requested interval are
    concatenated in time/order. Downstream tools such as ObsPy will see a
    discontinuous stream if data is missing.
    """
    if end_unix <= start_unix:
        raise ValueError("End time must be greater than start time")

    chunks: list[bytes] = []
    count = 0
    raw_bytes = 0
    first_start = None
    last_start = None
    component_counts: dict[str, int] = {}
    truncated = False

    with connect_receiver_db(db_path, readonly=True) as conn:
        cols = columns(conn, "packets")
        wc, args = _stage3_packet_where(conn, device_key, components, start_unix, end_unix)
        comp_col = "component_key" if "component_key" in cols else "channel"
        order_cols = "start_unix, seq_no" if "seq_no" in cols else "start_unix"
        sql = f"SELECT raw_mseed, start_unix, {comp_col} AS component FROM packets WHERE {wc} ORDER BY {order_cols} LIMIT ?"
        qargs = list(args) + [max_records + 1]
        for row in conn.execute(sql, qargs):
            if count >= max_records:
                truncated = True
                break
            raw = bytes(row["raw_mseed"])
            chunks.append(raw)
            raw_bytes += len(raw)
            count += 1
            comp = str(row["component"] or "UNKNOWN")
            component_counts[comp] = component_counts.get(comp, 0) + 1
            st = float(row["start_unix"])
            first_start = st if first_start is None else min(first_start, st)
            last_start = st if last_start is None else max(last_start, st)

    return {
        "blob": b"".join(chunks),
        "record_count": count,
        "raw_bytes": raw_bytes,
        "component_counts": component_counts,
        "first_start": first_start,
        "last_start": last_start,
        "first_start_iso": _stage3_iso_utc(first_start),
        "last_start_iso": _stage3_iso_utc(last_start),
        "truncated": truncated,
    }


def export_preview_stage3(
    db_path: str,
    *,
    device_key: str,
    components: list[str] | None,
    start_unix: float,
    end_unix: float,
) -> dict[str, Any]:
    if end_unix <= start_unix:
        raise ValueError("End time must be greater than start time")
    with connect_receiver_db(db_path, readonly=True) as conn:
        cols = columns(conn, "packets")
        wc, args = _stage3_packet_where(conn, device_key, components, start_unix, end_unix)
        comp_col = "component_key" if "component_key" in cols else "channel"
        rows = conn.execute(
            f"""
            SELECT {comp_col} AS component,
                   COUNT(*) AS records,
                   SUM(packet_len) AS packet_bytes,
                   MIN(start_unix) AS first_start,
                   MAX(start_unix) AS last_start
            FROM packets
            WHERE {wc}
            GROUP BY {comp_col}
            ORDER BY {comp_col}
            """,
            args,
        ).fetchall()
        comps = []
        for r in rows:
            comps.append({
                "component": r["component"],
                "records": int(r["records"] or 0),
                "bytes": int(r["packet_bytes"] or 0),
                "first_start": float(r["first_start"]) if r["first_start"] is not None else None,
                "last_start": float(r["last_start"]) if r["last_start"] is not None else None,
                "first_start_iso": _stage3_iso_utc(r["first_start"]),
                "last_start_iso": _stage3_iso_utc(r["last_start"]),
            })
        total_records = sum(c["records"] for c in comps)
        total_bytes = sum(c["bytes"] for c in comps)
        gaps = export_gaps_stage3(db_path, device_key=device_key, start_unix=start_unix, end_unix=end_unix, limit=200)
        return {
            "components": comps,
            "total_records": total_records,
            "total_bytes": total_bytes,
            "has_records": total_records > 0,
            "gap_count": len(gaps),
            "gaps": gaps,
            "start_unix": start_unix,
            "end_unix": end_unix,
            "start_iso": _stage3_iso_utc(start_unix),
            "end_iso": _stage3_iso_utc(end_unix),
        }


def export_gaps_stage3(db_path: str, *, device_key: str, start_unix: float, end_unix: float, limit: int = 500) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        with connect_receiver_db(db_path, readonly=True) as conn:
            if not table_exists(conn, "gaps"):
                return out
            cols = columns(conn, "gaps")
            # Gaps tables differ between receiver versions. Select all and filter defensively in Python.
            order_col = "detected_unix" if "detected_unix" in cols else ("created_at" if "created_at" in cols else "rowid")
            rows = conn.execute(f"SELECT * FROM gaps ORDER BY {order_col} DESC LIMIT ?", (limit,)).fetchall()
            for r in rows:
                d = dict(r)
                # Find a plausible start/end pair.
                gs = d.get("gap_start_unix", d.get("expected_start_unix", d.get("prev_end_unix", d.get("start_unix"))))
                ge = d.get("gap_end_unix", d.get("actual_start_unix", d.get("next_start_unix", d.get("end_unix"))))
                try:
                    gs_f = float(gs) if gs is not None else None
                    ge_f = float(ge) if ge is not None else None
                except Exception:
                    gs_f = ge_f = None
                if gs_f is not None and ge_f is not None:
                    if ge_f < start_unix or gs_f > end_unix:
                        continue
                stream = str(d.get("stream_key") or d.get("stream") or d.get("channel") or d.get("component_key") or "")
                if device_key and device_key not in stream and d.get("device_key") not in (None, device_key):
                    continue
                d["gap_start_iso"] = _stage3_iso_utc(gs_f)
                d["gap_end_iso"] = _stage3_iso_utc(ge_f)
                out.append(d)
    except Exception:
        return out
    return out


def export_latest_window_stage3(db_path: str, *, device_key: str, minutes: int = 30) -> dict[str, Any]:
    summary = device_summary(db_path, device_key)
    last = summary.get("last_end") or summary.get("last_start")
    if last is None:
        # Fall back to now only if the device has no data at all.
        last = time.time()
    end = float(last) + 60.0
    start = end - float(minutes) * 60.0
    return {
        "start_unix": start,
        "end_unix": end,
        "start_iso": _stage3_iso_utc(start),
        "end_iso": _stage3_iso_utc(end),
        "last_data_unix": float(last),
        "last_data_iso": _stage3_iso_utc(float(last)),
    }
