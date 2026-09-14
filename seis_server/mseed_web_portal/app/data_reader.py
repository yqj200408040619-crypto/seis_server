from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import glob
from contextlib import contextmanager
from io import BytesIO
import math
import os
import re
import time
from typing import Any

import h5py
import numpy as np
from obspy import Stream, Trace, UTCDateTime, read

BEIJING_TZ = ZoneInfo("Asia/Shanghai")

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
          text = value.strip()

          # Explicit UTC or offset-aware input
          if text.endswith("Z") or re.search(r"[+-]\d\d:\d\d$", text):
              return float(UTCDateTime(text).timestamp)

          # Timezone-less input is Beijing local time
          dt = datetime.fromisoformat(text)
          dt = dt.replace(tzinfo=BEIJING_TZ)
          return dt.astimezone(timezone.utc).timestamp
      except Exception as exc:
          raise ValueError(f"Invalid time value: {value}") from exc


@contextmanager
def open_h5_read(path: str):
    """Open a receiver file with SWMR and short retries during writer flushes."""
    last_error: OSError | None = None
    for _ in range(3):
        try:
            f = h5py.File(path, "r", libver="latest", swmr=True)
        except OSError as exc:
            last_error = exc
            time.sleep(0.05)
            continue
        try:
            yield f
        finally:
            f.close()
        return
    try:
        f = h5py.File(path, "r")
    except OSError:
        if last_error is not None:
            raise last_error
        raise
    try:
        yield f
    finally:
        f.close()

# ---------- 通用类与工具 ----------
class DiscoveredDevice:
    def __init__(self, label: str, db_path: str, device_key: str,
                 instrument_type: str | None, instrument_serial: str | None,
                 client_ip: str | None, server_port: int | None):
        self.label = label
        self.db_path = db_path
        self.device_key = device_key
        self.instrument_type = instrument_type
        self.instrument_serial = instrument_serial
        self.client_ip = client_ip
        self.server_port = server_port


# 支持 .h5 和 .db 的旧正则（兼容）
DB_NAME_RE = re.compile(
    r"^(?P<client_ip>.+)_(?P<server_port>\d+)_(?P<instrument_type>[^_]+)_(?P<instrument_serial>[^_]+)\.(db|h5)$"
)


def safe_receiver_db_path(receiver_db_dir: str, db_path: str) -> str:
    base = os.path.realpath(receiver_db_dir)
    target = os.path.realpath(db_path)
    # OBN data is a deliberate sibling of the MiniSEED devices directory.
    obn_base = os.path.realpath(os.path.join(base, os.pardir, "obn_devices"))
    def is_within(root: str) -> bool:
        try:
            return os.path.commonpath((root, target)) == root
        except ValueError:
            return False
    if not any(is_within(root) for root in (base, obn_base)):
        raise PermissionError("Database path is outside receiver database directory.")
    if not target.endswith(".h5"):
        raise ValueError("Only HDF5 (.h5) receiver databases are allowed.")
    return target


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


# ---------- 设备发现 ----------
def discover_devices(receiver_db_dir: str) -> list[DiscoveredDevice]:
    devices: list[DiscoveredDevice] = []
    for h5_path in sorted(glob.glob(os.path.join(receiver_db_dir, "*.h5"))):
        try:
            meta = infer_from_filename(h5_path)
            with open_h5_read(h5_path) as f:
                device_key = f.attrs.get("device_key", meta["device_key"])
                instrument_type = f.attrs.get("instrument_type", meta["instrument_type"])
                instrument_serial = f.attrs.get("instrument_serial", meta["instrument_serial"])
            label = f"{instrument_type or 'DEV'}-{instrument_serial or device_key}"
            devices.append(DiscoveredDevice(
                label=label,
                db_path=h5_path,
                device_key=str(device_key),
                instrument_type=str(instrument_type) if instrument_type else None,
                instrument_serial=str(instrument_serial) if instrument_serial else None,
                client_ip=meta["client_ip"],
                server_port=meta["server_port"],
            ))
        except Exception:
            continue
    return devices


def discover_obn_devices(obn_dir: str) -> list[DiscoveredDevice]:
    devices: list[DiscoveredDevice] = []
    for h5_path in sorted(glob.glob(os.path.join(obn_dir, "*.h5"))):
        try:
            name = os.path.basename(h5_path)
            instrument_id = os.path.splitext(name)[0]
            with open_h5_read(h5_path) as f:
                if "metadata" in f:
                    instrument_id = f["metadata"].attrs.get("instrument_id", instrument_id)
            devices.append(DiscoveredDevice(
                label=instrument_id,
                db_path=h5_path,
                device_key=instrument_id,
                instrument_type="OBN",
                instrument_serial=instrument_id,
                client_ip=None,
                server_port=18001,
            ))
        except Exception:
            continue
    return devices


# ---------- OBN 专用解析 ----------
def is_obn_h5(db_path: str) -> bool:
    try:
        with open_h5_read(db_path) as f:
            return "samples" in f and "packet_time_us" in f
    except Exception:
        return False


def export_obn_raw_packets(
    db_path: str,
    *,
    start_unix: float,
    end_unix: float,
    max_packets: int = 200000,
) -> tuple[bytes, int]:
    """Return original OBN wire packets stored by the receiver for a time range."""
    if end_unix <= start_unix:
        raise ValueError("End time must be greater than start time")
    with open_h5_read(db_path) as f:
        if "raw_packets" not in f:
            return b"", 0
        times = f["packet_time_us"][:]
        raw_packets = f["raw_packets"]
        start_index = int(np.searchsorted(times, int(start_unix * 1_000_000)))
        end_index = int(np.searchsorted(times, int(end_unix * 1_000_000), side="right"))
        end_index = min(end_index, start_index + max_packets)
        packets = [bytes(packet) for packet in raw_packets[start_index:end_index] if len(packet)]
    return b"".join(packets), len(packets)


def list_components_obn(db_path: str) -> list[dict[str, Any]]:
    with open_h5_read(db_path) as f:
        packets = len(f["packet_time_us"])
        last_start_us = max(f["packet_time_us"]) if packets > 0 else None
        last_start = last_start_us / 1_000_000.0 if last_start_us else None
        return [{
            "component": "OBN",
            "stream_key": "OBN",
            "packets": packets,
            "last_start": last_start,
        }]


def device_summary_obn(db_path: str) -> dict[str, Any]:
    comps = list_components_obn(db_path)
    total = comps[0]["packets"] if comps else 0
    last = comps[0]["last_start"] if comps else None
    now = time.time()
    age = now - last if last else None
    status = "online" if age and age <= 600 else ("stale" if age and age <= 3600 else "offline")
    return {
        "components": comps,
        "component_status": [{**c, "age_seconds": age, "status": status} for c in comps],
        "total_packets": total,
        "last_start": last,
        "age_seconds": age,
        "status": status,
        "one_hour_packets": total,
        "gap_count": 0,
        "duplicate_count": 0,
        "bad_packet_count": 0,
    }


def read_obn_waveform(db_path: str, start_unix: float, end_unix: float,
                      max_points: int, max_records: int) -> dict[str, Any]:
    start_us = int(start_unix * 1_000_000)
    end_us = int(end_unix * 1_000_000)

    with open_h5_read(db_path) as f:
        packet_times = f["packet_time_us"][:]
        samples = f["samples"][:]  # (N, 4, 1023)

    if len(packet_times) == 0:
        return {"points": [], "traces": [], "packet_count": 0, "raw_bytes": 0,
                "truncated_records": False, "generated_at": time.time()}

    idx = np.searchsorted(packet_times, start_us)
    if idx == len(packet_times):
        return {"points": [], "traces": [], "packet_count": 0, "raw_bytes": 0,
                "truncated_records": False, "generated_at": time.time()}

    max_packets = min(max_records, len(packet_times) - idx)
    end_idx = idx + max_packets

    # 读取第一通道（X轴）的数据，如需其他通道可修改索引 [:, 0, :]
    selected_packets = samples[idx:end_idx, 0, :]  # (N, 1023)
    selected_times = packet_times[idx:end_idx]

    flat_data = selected_packets.flatten()
    total_samples = len(flat_data)

    dt = 1.0 / 1000.0  # 1000 Hz -> 1ms
    flat_times = []
    for p_time_us in selected_times:
        base_time = p_time_us / 1_000_000.0
        flat_times.extend(base_time + s_idx * dt for s_idx in range(1023))
    flat_times = np.array(flat_times)

    mask = (flat_times >= start_unix) & (flat_times <= end_unix)
    if not np.any(mask):
        return {"points": [], "traces": [], "packet_count": max_packets,
                "raw_bytes": total_samples * 4, "truncated_records": max_packets >= max_records,
                "generated_at": time.time()}

    final_t = flat_times[mask]
    final_y = flat_data[mask].astype(np.float64)
    final_t, final_y = minmax_downsample(final_t, final_y, max_points)

    points = [{"t": float(t), "y": float(y)} for t, y in zip(final_t, final_y)]

    return {
        "points": points,
        "traces": [{
            "stream_key": "OBN",
            "component": "OBN",
            "sampling_rate": 1000.0,
            "npts_original": int(np.sum(mask)),
            "points": points
        }],
        "packet_count": max_packets,
        "raw_bytes": total_samples * 4,
        "point_count": len(points),
        "truncated_records": max_packets >= max_records,
        "generated_at": time.time(),
    }


# ---------- MiniSEED 解析（适配新 HDF5 结构） ----------
def list_components(db_path: str, device_key: str | None = None) -> list[dict[str, Any]]:
    if is_obn_h5(db_path):
        return list_components_obn(db_path)

    components: list[dict[str, Any]] = []
    with open_h5_read(db_path) as f:
        for stream_key in f.keys():
            grp = f[stream_key]
            if not isinstance(grp, h5py.Group):
                continue
            parts = stream_key.split(".")
            component = parts[-1] if len(parts) >= 4 else stream_key
            datasets = [item for item in grp.values() if isinstance(item, h5py.Dataset)]
            count = len(datasets)
            last_start = None
            for dset in datasets:
                st = dset.attrs.get("start_unix")
                if st is not None and (last_start is None or st > last_start):
                    last_start = float(st)
            components.append({
                "component": component,
                "stream_key": stream_key,
                "packets": count,
                "last_start": last_start,
            })
    return sorted(components, key=lambda item: (str(item["component"]), str(item["stream_key"])))


def device_summary(db_path: str, device_key: str | None = None) -> dict[str, Any]:
    if is_obn_h5(db_path):
        return device_summary_obn(db_path)

    comps = list_components(db_path, device_key)
    total_packets = sum(int(c.get("packets") or 0) for c in comps)
    last_start = max((float(c["last_start"]) for c in comps if c.get("last_start") is not None), default=None)
    now = time.time()
    age_seconds = now - last_start if last_start is not None else None
    status = "online" if age_seconds and age_seconds <= 600 else ("stale" if age_seconds and age_seconds <= 3600 else "offline")
    component_status = []
    for comp in comps:
        comp_last = comp.get("last_start")
        comp_age = now - float(comp_last) if comp_last is not None else None
        component_status.append({**comp, "age_seconds": comp_age,
            "status": "online" if comp_age is not None and comp_age <= 600 else ("stale" if comp_age is not None and comp_age <= 3600 else "offline")})
    quality = quality_summary(db_path, device_key, limit=1)
    one_hour_start = now - 3600
    one_hour_packets = 0
    with open_h5_read(db_path) as f:
        for grp in f.values():
            if not isinstance(grp, h5py.Group):
                continue
            for dset in grp.values():
                if isinstance(dset, h5py.Dataset) and float(dset.attrs.get("recv_unix", 0.0)) >= one_hour_start:
                    one_hour_packets += 1
    return {
        "components": comps,
        "total_packets": total_packets,
        "last_start": last_start,
        "age_seconds": age_seconds,
        "status": status,
        "one_hour_packets": one_hour_packets,
        "component_status": component_status,
        "gap_count": quality["gap_count"],
        "duplicate_count": quality["duplicate_count"],
        "bad_packet_count": quality["bad_packet_count"],
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


# ---------- 统一的 read_waveform ----------
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

    if is_obn_h5(db_path):
        return read_obn_waveform(db_path, start_unix, end_unix, max_points, max_records)

    # ---------- MiniSEED 读取 ----------
    packet_count = 0
    raw_bytes = 0
    st = Stream()

    with open_h5_read(db_path) as f:
        for stream_key in f.keys():
            grp = f[stream_key]
            if not isinstance(grp, h5py.Group):
                continue
            if component and stream_key.rsplit(".", 1)[-1] != component:
                continue
            for ds_name in sorted(grp.keys()):
                if packet_count >= max_records:
                    break
                dset = grp[ds_name]
                if not isinstance(dset, h5py.Dataset):
                    continue
                dset_start = dset.attrs.get("start_unix")
                dset_end = dset.attrs.get("end_unix", -1.0)
                if dset_start is None:
                    continue
                if dset_end != -1.0 and (dset_end < start_unix or dset_start > end_unix):
                    continue
                raw_packet = dset.attrs.get("raw_mseed")
                if raw_packet is not None:
                    raw = bytes(raw_packet)
                    if raw:
                        try:
                            st += read(BytesIO(raw), format="MSEED")
                        except Exception:
                            # Legacy or manually-created HDF5 records may carry a
                            # non-miniSEED raw attribute; use their samples instead.
                            pass
                        else:
                            packet_count += 1
                            raw_bytes += len(raw)
                            continue
                data = dset[()]
                sr = dset.attrs.get("sampling_rate", 1.0)
                npts = len(data)
                tr = Trace(data=data)
                tr.stats.network = dset.attrs.get("network", "")
                tr.stats.station = dset.attrs.get("station", "")
                tr.stats.location = dset.attrs.get("location", "")
                tr.stats.channel = dset.attrs.get("channel", "")
                tr.stats.sampling_rate = sr if sr and sr > 0 else 1.0
                tr.stats.starttime = UTCDateTime(dset_start)
                st.append(tr)
                packet_count += 1
                raw_bytes += int(np.asarray(data).nbytes)

    if packet_count == 0 or len(st) == 0:
        return {
            "points": [],
            "traces": [],
            "packet_count": 0,
            "raw_bytes": 0,
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


# ---------- 保持与旧版导出等兼容 ----------
def quality_summary(db_path: str, device_key: str | None = None, limit: int = 100) -> dict[str, Any]:
    if is_obn_h5(db_path):
        return {"gaps": [], "duplicates": [], "bad_packets": [], "gap_count": 0,
                "duplicate_count": 0, "bad_packet_count": 0, "generated_at": time.time()}
    def decode(value: Any) -> Any:
        return value.decode("utf-8", "replace").rstrip("\x00") if isinstance(value, bytes) else value.item() if isinstance(value, np.generic) else value
    gaps: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    bad_packets: list[dict[str, Any]] = []
    with open_h5_read(db_path) as f:
        if "gaps" in f:
            ds = f["gaps"]
            for row in ds[max(0, len(ds) - limit):]:
                gaps.append({name: decode(row[name]) for name in ds.dtype.names})
        if "events" in f:
            ds = f["events"]
            for row in ds[max(0, len(ds) - limit):]:
                item = {name: decode(row[name]) for name in ds.dtype.names}
                event_type = str(item.get("event_type", ""))
                if "duplicate" in event_type: duplicates.append(item)
                if "bad" in event_type or "validation" in event_type or "write_failed" in event_type: bad_packets.append(item)
    return {"gaps": list(reversed(gaps)), "duplicates": list(reversed(duplicates)), "bad_packets": list(reversed(bad_packets)),
            "gap_count": len(gaps), "duplicate_count": len(duplicates), "bad_packet_count": len(bad_packets), "generated_at": time.time()}


def export_mseed_bytes(
    db_path: str,
    *,
    device_key: str,
    components: list[str] | None,
    start_unix: float,
    end_unix: float,
    max_records: int = 200000,
) -> tuple[bytes, int]:
    # 如果是 OBN 格式，不支持直接导出为 MiniSEED（因为没有原始包），这里返回空
    if is_obn_h5(db_path):
        return b"", 0

    if end_unix <= start_unix:
        raise ValueError("End time must be greater than start time")

    st = Stream()
    raw_packets: list[bytes] = []
    count = 0
    with open_h5_read(db_path) as f:
        for stream_key in f.keys():
            if count >= max_records:
                break
            grp = f[stream_key]
            if not isinstance(grp, h5py.Group):
                continue
            if components:
                comp_match = False
                for comp in components:
                    if stream_key.rsplit(".", 1)[-1] == comp:
                        comp_match = True
                        break
                if not comp_match:
                    continue
            for ds_name in sorted(grp.keys()):
                if count >= max_records:
                    break
                dset = grp[ds_name]
                if not isinstance(dset, h5py.Dataset):
                    continue
                dset_start = dset.attrs.get("start_unix")
                dset_end = dset.attrs.get("end_unix", -1.0)
                if dset_start is None:
                    continue
                if dset_end != -1.0 and (dset_end < start_unix or dset_start > end_unix):
                    continue
                raw_packet = dset.attrs.get("raw_mseed")
                if raw_packet is not None:
                    raw = bytes(raw_packet)
                    if raw:
                        try:
                            read(BytesIO(raw), format="MSEED", headonly=True)
                        except Exception:
                            pass
                        else:
                            raw_packets.append(raw)
                            count += 1
                            continue
                data = dset[()]
                tr = Trace(data=data)
                tr.stats.network = dset.attrs.get("network", "")
                tr.stats.station = dset.attrs.get("station", "")
                tr.stats.location = dset.attrs.get("location", "")
                tr.stats.channel = dset.attrs.get("channel", "")
                tr.stats.sampling_rate = dset.attrs.get("sampling_rate", 1.0)
                tr.stats.starttime = UTCDateTime(dset_start)
                st.append(tr)
                count += 1

    if count == 0:
        return b"", 0
    if raw_packets:
        # New receiver files retain the exact TCP record.  Do not re-encode it.
        # Mixed legacy/new files fall back to re-encoding only when necessary.
        if len(raw_packets) == count:
            return b"".join(raw_packets), count
        for raw in raw_packets:
            st += read(BytesIO(raw), format="MSEED")
    buf = BytesIO()
    st.write(buf, format="MSEED")
    return buf.getvalue(), count


def export_latest_window_stage3(db_path: str, *, device_key: str, minutes: int = 30) -> dict[str, Any]:
    summary = device_summary(db_path, device_key)
    last = summary.get("last_start")
    if last is None:
        last = time.time()
    end = float(last) + 60.0
    start = end - float(minutes) * 60.0
    return {
        "start_unix": start,
        "end_unix": end,
        "start_iso": UTCDateTime(start).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-3] + "Z",
        "end_iso": UTCDateTime(end).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-3] + "Z",
        "last_data_unix": float(last),
        "last_data_iso": UTCDateTime(last).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-3] + "Z",
    }


def export_mseed_bytes_stage3(
    db_path: str,
    *,
    device_key: str,
    components: list[str] | None,
    start_unix: float,
    end_unix: float,
    max_records: int = 500000,
) -> dict[str, Any]:
    blob, count = export_mseed_bytes(db_path, device_key=device_key, components=components,
                                     start_unix=start_unix, end_unix=end_unix, max_records=max_records)
    return {
        "blob": blob,
        "record_count": count,
        "raw_bytes": len(blob),
        "component_counts": {},
        "first_start": None,
        "last_start": None,
        "first_start_iso": "",
        "last_start_iso": "",
        "truncated": count >= max_records,
    }


def export_preview_stage3(db_path: str, *, device_key: str, components: list[str] | None,
                          start_unix: float, end_unix: float) -> dict[str, Any]:
    comps = list_components(db_path, device_key)
    total_records = sum(c["packets"] for c in comps)
    return {
        "components": comps,
        "total_records": total_records,
        "total_bytes": 0,
        "has_records": total_records > 0,
        "gap_count": 0,
        "gaps": [],
        "start_unix": start_unix,
        "end_unix": end_unix,
        "start_iso": UTCDateTime(start_unix).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-3] + "Z",
        "end_iso": UTCDateTime(end_unix).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-3] + "Z",
    }


def export_gaps_stage3(db_path: str, *, device_key: str, start_unix: float, end_unix: float,
                       limit: int = 500) -> list[dict[str, Any]]:
    result = quality_summary(db_path, device_key, limit=limit)
    return [gap for gap in result["gaps"] if start_unix <= float(gap.get("current_start", -1)) <= end_unix]
