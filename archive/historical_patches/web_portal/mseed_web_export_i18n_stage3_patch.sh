#!/usr/bin/env bash
set -euo pipefail

BASE="/opt/mseed-web-portal"
APP="$BASE/app"
TEMPLATES="$APP/templates"
STATIC_JS="$APP/static/js"
PY="/opt/miniforge3/envs/mseed-web/bin/python"
TS="$(date +%Y%m%d_%H%M%S)"

if [ ! -d "$APP" ]; then
  echo "ERROR: $APP not found" >&2
  exit 1
fi
if [ ! -x "$PY" ]; then
  echo "ERROR: $PY not found" >&2
  exit 1
fi

sudo mkdir -p "$TEMPLATES" "$STATIC_JS"

sudo cp "$APP/main.py" "$APP/main.py.bak_export_i18n_stage3_$TS"
sudo cp "$APP/data_reader.py" "$APP/data_reader.py.bak_export_i18n_stage3_$TS"
[ -f "$TEMPLATES/export.html" ] && sudo cp "$TEMPLATES/export.html" "$TEMPLATES/export.html.bak_export_i18n_stage3_$TS" || true
[ -f "$STATIC_JS/i18n_stage3.js" ] && sudo cp "$STATIC_JS/i18n_stage3.js" "$STATIC_JS/i18n_stage3.js.bak_export_i18n_stage3_$TS" || true

# ---------------------------------------------------------------------------
# 1) Add robust export helpers. These do not modify raw receiver databases.
# ---------------------------------------------------------------------------
if ! grep -q "STAGE3_EXPORT_HELPERS" "$APP/data_reader.py"; then
sudo tee -a "$APP/data_reader.py" > /dev/null <<'PYCODE'

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
PYCODE
fi

# ---------------------------------------------------------------------------
# 2) Add new export API/routes under unique paths, avoiding conflicts with old routes.
# ---------------------------------------------------------------------------
if ! grep -q "STAGE3_EXPORT_ROUTES" "$APP/main.py"; then
sudo tee -a "$APP/main.py" > /dev/null <<'PYCODE'

# STAGE3_EXPORT_ROUTES

def _stage3_components_param(value: str | None) -> list[str] | None:
    comps = [c.strip() for c in (value or "").split(",") if c.strip()]
    return comps or None


def _stage3_allowed_devices(user: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(d) for d in app_db.list_devices(settings.app_db, user_id=int(user["id"]), admin=is_admin(user))]


def _stage3_get_allowed_device(device_id: int, user: dict[str, Any]) -> dict[str, Any]:
    d = app_db.get_device_for_user(settings.app_db, device_id, int(user["id"]), admin=is_admin(user))
    if not d:
        raise HTTPException(status_code=404, detail="Device not found or not authorized")
    return dict(d)


def _stage3_html_message(title: str, message: str, status_code: int = 400):
    from fastapi.responses import HTMLResponse
    body = f"""<!doctype html><html><head><meta charset='utf-8'><title>{title}</title>
    <style>body{{font-family:Arial,sans-serif;background:#0f172a;color:#e5e7eb;padding:40px}}.box{{max-width:760px;margin:auto;background:#111827;border:1px solid #334155;border-radius:18px;padding:28px}}a{{color:#60a5fa}}</style>
    </head><body><div class='box'><h1>{title}</h1><p>{message}</p><p><a href='/export'>Back to export page</a></p></div></body></html>"""
    return HTMLResponse(body, status_code=status_code)


@app.get("/api/export/default-window3")
def api_export_default_window3(device_id: int = Query(...), minutes: int = Query(30), user: dict[str, Any] = Depends(current_user)):
    d = _stage3_get_allowed_device(device_id, user)
    from .data_reader import export_latest_window_stage3 as _latest_window
    safe_path = safe_receiver_db_path(settings.receiver_db_dir, d["db_path"])
    return _latest_window(safe_path, device_key=d["device_key"], minutes=max(1, min(minutes, 24 * 60)))


@app.get("/api/export/preview3")
def api_export_preview3(
    device_id: int = Query(...),
    components: str = Query(""),
    start: str = Query(...),
    end: str = Query(...),
    user: dict[str, Any] = Depends(current_user),
):
    d = _stage3_get_allowed_device(device_id, user)
    from .data_reader import export_preview_stage3 as _preview
    comps = _stage3_components_param(components)
    start_unix = parse_datetime_or_unix(start)
    end_unix = parse_datetime_or_unix(end)
    safe_path = safe_receiver_db_path(settings.receiver_db_dir, d["db_path"])
    return {"device": d, "preview": _preview(safe_path, device_key=d["device_key"], components=comps, start_unix=start_unix, end_unix=end_unix)}


@app.get("/api/export/devices3")
def api_export_devices3(user: dict[str, Any] = Depends(current_user)):
    devices = _stage3_allowed_devices(user)
    return {"devices": devices, "generated_at": time.time()}


@app.get("/export/download3")
def export_download3(
    device_id: int = Query(...),
    components: str = Query(""),
    start: str = Query(...),
    end: str = Query(...),
    user: dict[str, Any] = Depends(current_user),
):
    from fastapi.responses import Response
    from .data_reader import export_mseed_bytes_stage3 as _export
    d = _stage3_get_allowed_device(device_id, user)
    comps = _stage3_components_param(components)
    start_unix = parse_datetime_or_unix(start)
    end_unix = parse_datetime_or_unix(end)
    safe_path = safe_receiver_db_path(settings.receiver_db_dir, d["db_path"])
    result = _export(safe_path, device_key=d["device_key"], components=comps, start_unix=start_unix, end_unix=end_unix, max_records=500000)
    if not result["blob"]:
        return _stage3_html_message(
            "No records found",
            "No miniSEED records were found in the selected time range. Use 'Jump to latest data' or 'Preview range' to confirm available data before exporting.",
            status_code=404,
        )
    comp_part = "ALL" if not comps else "-".join(comps)
    filename = f"{d['device_key']}_{comp_part}_{int(start_unix)}_{int(end_unix)}.mseed"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-miniSEED-Record-Count": str(result["record_count"]),
    }
    return Response(content=result["blob"], media_type="application/vnd.fdsn.mseed", headers=headers)


@app.get("/export/batch3")
def export_batch3(
    device_ids: str = Query(""),
    customer_id: str = Query(""),
    all_visible: int = Query(0),
    components: str = Query(""),
    start: str = Query(...),
    end: str = Query(...),
    user: dict[str, Any] = Depends(current_user),
):
    from fastapi.responses import Response
    import csv, io, zipfile, json
    from .data_reader import export_mseed_bytes_stage3 as _export, export_gaps_stage3 as _gaps

    visible = _stage3_allowed_devices(user)
    selected_ids = {int(x) for x in device_ids.split(",") if x.strip().isdigit()}
    if all_visible:
        selected = visible
    elif customer_id.strip():
        selected = [d for d in visible if str(d.get("customer_id") or "") == customer_id.strip()]
    elif selected_ids:
        selected = [d for d in visible if int(d["id"]) in selected_ids]
    else:
        return _stage3_html_message("No devices selected", "Select at least one device for batch export.", status_code=400)

    comps = _stage3_components_param(components)
    start_unix = parse_datetime_or_unix(start)
    end_unix = parse_datetime_or_unix(end)
    if end_unix <= start_unix:
        return _stage3_html_message("Invalid time range", "End time must be greater than start time.", status_code=400)

    buf = io.BytesIO()
    manifest_io = io.StringIO()
    manifest = csv.writer(manifest_io)
    manifest.writerow(["device_id", "device_key", "label", "component_filter", "record_count", "bytes", "first_start_utc", "last_start_utc", "truncated", "file"])

    gaps_io = io.StringIO()
    gaps_csv = csv.writer(gaps_io)
    gaps_csv.writerow(["device_key", "label", "gap_json"])

    total_records = 0
    total_files = 0
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        for d in selected:
            try:
                safe_path = safe_receiver_db_path(settings.receiver_db_dir, d["db_path"])
                result = _export(safe_path, device_key=d["device_key"], components=comps, start_unix=start_unix, end_unix=end_unix, max_records=500000)
                comp_part = "ALL" if not comps else "-".join(comps)
                file_name = f"{d['device_key']}/{d['device_key']}_{comp_part}_{int(start_unix)}_{int(end_unix)}.mseed"
                if result["record_count"] > 0:
                    zf.writestr(file_name, result["blob"])
                    total_files += 1
                    total_records += int(result["record_count"])
                manifest.writerow([d.get("id"), d.get("device_key"), d.get("alias") or d.get("label"), comp_part, result["record_count"], result["raw_bytes"], result["first_start_iso"], result["last_start_iso"], result["truncated"], file_name if result["record_count"] > 0 else ""])
                gaps = _gaps(safe_path, device_key=d["device_key"], start_unix=start_unix, end_unix=end_unix, limit=500)
                for g in gaps:
                    gaps_csv.writerow([d.get("device_key"), d.get("alias") or d.get("label"), json.dumps(g, ensure_ascii=False, default=str)])
            except Exception as exc:
                manifest.writerow([d.get("id"), d.get("device_key"), d.get("alias") or d.get("label"), "ERROR", 0, 0, "", "", "", str(exc)])
        zf.writestr("manifest.csv", manifest_io.getvalue())
        zf.writestr("gaps.csv", gaps_io.getvalue())
        zf.writestr("README.txt", "This ZIP contains raw miniSEED records exported from the selected devices and interval. Data gaps do not block export; missing intervals are listed in gaps.csv when detected. If a device has no records in the selected range, it appears in manifest.csv with record_count=0.\n")

    if total_files == 0:
        return _stage3_html_message("No records found", "No selected devices had miniSEED records in this time range. Use Preview range or Jump to latest data first.", status_code=404)

    filename = f"mseed_batch_{int(start_unix)}_{int(end_unix)}_{len(selected)}devices.zip"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-miniSEED-Total-Records": str(total_records),
        "X-miniSEED-File-Count": str(total_files),
    }
    return Response(content=buf.getvalue(), media_type="application/zip", headers=headers)
PYCODE
fi

# ---------------------------------------------------------------------------
# 3) Replace export.html with a safer export UI: latest data, preview, batch ZIP.
# ---------------------------------------------------------------------------
sudo tee "$TEMPLATES/export.html" > /dev/null <<'HTML'
{% extends "base.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-end mb-4 flex-wrap gap-3">
  <div>
    <div class="portal-pill mb-2">Data export</div>
    <h1 class="h3 fw-bold mb-1">数据导出</h1>
    <p class="text-secondary mb-0">按设备、客户、三分量和 UTC 时间范围导出原始 miniSEED 数据。数据有中断时，导出仍会包含已有数据，并在批量导出的 gaps.csv 中列出缺口。</p>
  </div>
</div>

<div class="row g-4">
  <div class="col-12 col-xl-6">
    <div class="control-panel h-100">
      <h2 class="h5 fw-bold mb-3">单台设备导出</h2>
      <form id="singleExportForm" method="get" action="/export/download3" class="row g-3 align-items-end">
        <div class="col-12">
          <label class="form-label">设备</label>
          <select id="deviceSelect" name="device_id" class="form-select">
            {% for d in devices %}
            <option value="{{ d.id }}" {% if selected_device_id and selected_device_id == d.id %}selected{% endif %}>{{ d.alias or d.label }} / {{ d.device_key }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="col-12 col-md-6">
          <label class="form-label">开始时间 UTC</label>
          <input id="startInput" name="start" class="form-control" placeholder="2026-06-30T15:30:00Z" required>
        </div>
        <div class="col-12 col-md-6">
          <label class="form-label">结束时间 UTC</label>
          <input id="endInput" name="end" class="form-control" placeholder="2026-06-30T15:35:00Z" required>
        </div>
        <div class="col-12">
          <label class="form-label">分量</label>
          <div id="exportComponentChecks" class="component-checks"></div>
          <input type="hidden" id="componentsInput" name="components" value="">
        </div>
        <div class="col-12 d-flex flex-wrap gap-2">
          <button type="button" id="latestBtn" class="btn btn-outline-light">跳到最新数据</button>
          <button type="button" id="previewBtn" class="btn btn-outline-light">预览范围</button>
          <button class="btn btn-primary">导出 miniSEED</button>
        </div>
      </form>
      <div id="exportPreview" class="mt-4 text-secondary small"></div>
    </div>
  </div>

  <div class="col-12 col-xl-6">
    <div class="control-panel h-100">
      <h2 class="h5 fw-bold mb-3">批量导出</h2>
      <form id="batchExportForm" method="get" action="/export/batch3" class="row g-3 align-items-end">
        <input type="hidden" id="batchStart" name="start" value="">
        <input type="hidden" id="batchEnd" name="end" value="">
        <input type="hidden" id="batchComponents" name="components" value="">
        <input type="hidden" id="batchDeviceIds" name="device_ids" value="">
        <div class="col-12 col-md-6">
          <label class="form-label">客户过滤</label>
          <select id="customerFilter" name="customer_id" class="form-select">
            <option value="">全部可见设备</option>
          </select>
        </div>
        <div class="col-12 col-md-6">
          <label class="form-label">导出方式</label>
          <select id="batchMode" name="all_visible" class="form-select">
            <option value="0">导出勾选设备</option>
            <option value="1">导出全部可见设备</option>
          </select>
        </div>
        <div class="col-12">
          <label class="form-label">设备列表</label>
          <div id="batchDeviceList" class="batch-device-list"></div>
        </div>
        <div class="col-12 d-flex flex-wrap gap-2">
          <button type="button" id="selectAllDevices" class="btn btn-outline-light">全选</button>
          <button type="button" id="clearAllDevices" class="btn btn-outline-light">清空</button>
          <button class="btn btn-primary">批量导出 ZIP</button>
        </div>
      </form>
      <div class="mt-4 small text-secondary">
        <p class="mb-2"><strong>说明：</strong>批量导出会生成 ZIP 文件，包含每台设备的 miniSEED 文件、manifest.csv 和 gaps.csv。</p>
        <p class="mb-0">如果数据中断，导出不会失败；文件只包含实际存在的记录，缺口会保存在 gaps.csv 供后续检查。</p>
      </div>
    </div>
  </div>
</div>

<div class="device-card mt-4">
  <h2 class="h6 fw-bold mb-2">导出行为说明</h2>
  <ul class="text-secondary mb-0">
    <li>导出的是数据库中保存的原始 raw_mseed 记录，不会重新采样或修改波形。</li>
    <li>如果所选时间段没有记录，系统会显示友好提示，而不是直接返回 JSON 错误。</li>
    <li>如果时间段内存在数据中断，miniSEED 文件仍然可用；ObsPy 等工具会识别为不连续数据段。</li>
  </ul>
</div>

<style>
.batch-device-list{max-height:260px;overflow:auto;border:1px solid rgba(148,163,184,.22);border-radius:14px;padding:12px;background:rgba(15,23,42,.35)}
.batch-device-row{display:flex;align-items:center;gap:10px;padding:8px;border-bottom:1px solid rgba(148,163,184,.12)}
.batch-device-row:last-child{border-bottom:0}.export-preview-table{width:100%;border-collapse:collapse}.export-preview-table td,.export-preview-table th{padding:6px 8px;border-bottom:1px solid rgba(148,163,184,.15)}
</style>

<script>
const devicesFromServer = {{ devices|tojson }};
function isoNoMs(d){ return d.toISOString().replace('.000Z','Z'); }
async function fetchJSON(url){ const r = await fetch(url, {credentials:'same-origin'}); if(!r.ok) throw new Error(await r.text()); return await r.json(); }
function selectedComponents(){ return Array.from(document.querySelectorAll('.export-comp:checked')).map(x=>x.value); }
function updateComponentInputs(){ const v = selectedComponents().join(','); document.getElementById('componentsInput').value = v; document.getElementById('batchComponents').value = v; }
async function loadLatestWindow(){
  const id = document.getElementById('deviceSelect')?.value; if(!id) return;
  try{
    const j = await fetchJSON('/api/export/default-window3?device_id=' + encodeURIComponent(id) + '&minutes=30');
    document.getElementById('startInput').value = j.start_iso;
    document.getElementById('endInput').value = j.end_iso;
    syncBatchTimes();
  }catch(e){
    const end = new Date(); const start = new Date(end.getTime()-30*60*1000);
    document.getElementById('startInput').value = isoNoMs(start);
    document.getElementById('endInput').value = isoNoMs(end);
    syncBatchTimes();
  }
}
async function loadExportComponents(){
  const sel = document.getElementById('deviceSelect'); if(!sel || !sel.value) return;
  const box = document.getElementById('exportComponentChecks'); box.innerHTML = '';
  const p = await fetchJSON('/api/components?device_id=' + encodeURIComponent(sel.value));
  const comps = (p.components || []).map(c=>c.component).sort((a,b)=>{
    const order = {'BHZ':0,'BHN':1,'BHE':2,'EHZ':0,'EHN':1,'EHE':2}; return (order[a]??9)-(order[b]??9) || String(a).localeCompare(String(b));
  });
  comps.forEach((c, idx) => {
    const lab = document.createElement('label'); lab.className = 'component-badge';
    lab.innerHTML = `<input class="form-check-input mt-0 export-comp" type="checkbox" value="${c}" ${idx < 3 ? 'checked' : ''}> ${c}`;
    box.appendChild(lab);
  });
  updateComponentInputs();
}
function syncBatchTimes(){ document.getElementById('batchStart').value = document.getElementById('startInput').value; document.getElementById('batchEnd').value = document.getElementById('endInput').value; }
async function previewRange(){
  updateComponentInputs(); syncBatchTimes();
  const box = document.getElementById('exportPreview'); box.innerHTML = '加载中...';
  const q = new URLSearchParams({device_id: document.getElementById('deviceSelect').value, components: document.getElementById('componentsInput').value, start: document.getElementById('startInput').value, end: document.getElementById('endInput').value});
  try{
    const j = await fetchJSON('/api/export/preview3?' + q.toString()); const p = j.preview;
    if(!p.has_records){ box.innerHTML = '<div class="alert alert-warning">所选时间段没有记录。请点击“跳到最新数据”后重试，或检查历史波形中的最新时间。</div>'; return; }
    let html = `<table class="export-preview-table"><thead><tr><th>分量</th><th>记录数</th><th>字节</th><th>首条时间</th><th>最后时间</th></tr></thead><tbody>`;
    for(const c of p.components){ html += `<tr><td>${c.component}</td><td>${c.records}</td><td>${c.bytes}</td><td>${c.first_start_iso}</td><td>${c.last_start_iso}</td></tr>`; }
    html += `</tbody></table><div class="mt-2">总记录数：${p.total_records}，数据缺口：${p.gap_count}</div>`;
    if(p.gap_count > 0) html += '<div class="alert alert-warning mt-2">该时间段存在数据中断。导出不会失败，但文件中会缺少对应时间段的数据。</div>';
    box.innerHTML = html;
  }catch(e){ box.innerHTML = '<div class="alert alert-danger">预览失败：' + e.message + '</div>'; }
}
function uniqueCustomers(){
  const m = new Map();
  for(const d of devicesFromServer){ const cid = d.customer_id || ''; const name = d.customer_name || d.customer || (cid ? ('Customer ' + cid) : '未分组'); if(cid) m.set(String(cid), name); }
  return Array.from(m.entries()).sort((a,b)=>a[1].localeCompare(b[1]));
}
function renderCustomerFilter(){
  const sel = document.getElementById('customerFilter'); if(!sel) return;
  for(const [id,name] of uniqueCustomers()){ const opt=document.createElement('option'); opt.value=id; opt.textContent=name; sel.appendChild(opt); }
}
function renderBatchDeviceList(){
  const cid = document.getElementById('customerFilter').value;
  const list = document.getElementById('batchDeviceList'); list.innerHTML = '';
  const filtered = devicesFromServer.filter(d => !cid || String(d.customer_id || '') === cid);
  for(const d of filtered){
    const row=document.createElement('label'); row.className='batch-device-row';
    row.innerHTML = `<input class="form-check-input batch-dev" type="checkbox" value="${d.id}" checked> <span><strong>${d.alias || d.label}</strong> <span class="text-secondary">${d.device_key || ''}</span></span>`;
    list.appendChild(row);
  }
  updateBatchDeviceIds();
}
function updateBatchDeviceIds(){ document.getElementById('batchDeviceIds').value = Array.from(document.querySelectorAll('.batch-dev:checked')).map(x=>x.value).join(','); }
document.addEventListener('DOMContentLoaded', async () => {
  renderCustomerFilter(); renderBatchDeviceList();
  await loadExportComponents().catch(console.error); await loadLatestWindow();
  document.getElementById('deviceSelect')?.addEventListener('change', async () => { await loadExportComponents().catch(console.error); await loadLatestWindow(); });
  document.getElementById('latestBtn')?.addEventListener('click', loadLatestWindow);
  document.getElementById('previewBtn')?.addEventListener('click', previewRange);
  document.getElementById('exportComponentChecks')?.addEventListener('change', updateComponentInputs);
  document.getElementById('startInput')?.addEventListener('change', syncBatchTimes);
  document.getElementById('endInput')?.addEventListener('change', syncBatchTimes);
  document.getElementById('customerFilter')?.addEventListener('change', renderBatchDeviceList);
  document.getElementById('batchDeviceList')?.addEventListener('change', updateBatchDeviceIds);
  document.getElementById('selectAllDevices')?.addEventListener('click',()=>{document.querySelectorAll('.batch-dev').forEach(x=>x.checked=true);updateBatchDeviceIds();});
  document.getElementById('clearAllDevices')?.addEventListener('click',()=>{document.querySelectorAll('.batch-dev').forEach(x=>x.checked=false);updateBatchDeviceIds();});
  document.getElementById('singleExportForm')?.addEventListener('submit',()=>{updateComponentInputs();syncBatchTimes();});
  document.getElementById('batchExportForm')?.addEventListener('submit',()=>{updateComponentInputs();syncBatchTimes();updateBatchDeviceIds();});
});
</script>
{% endblock %}
HTML

# ---------------------------------------------------------------------------
# 4) Add an i18n hardening overlay for remaining Chinese/English leftovers.
# ---------------------------------------------------------------------------
sudo tee "$STATIC_JS/i18n_stage3.js" > /dev/null <<'JS'
(function(){
  'use strict';
  const KEY='mseed.portal.lang';
  const zhToEn={
    '总览':'Overview','概览':'Overview','实时波形':'Live waveform','历史波形':'Historical waveform','数据质量':'Data quality','数据导出':'Data export','管理':'Admin','退出':'Log out','登录':'Log in',
    '数据导出':'Data export','单台设备导出':'Single-device export','批量导出':'Batch export','客户过滤':'Customer filter','全部可见设备':'All visible devices','导出方式':'Export mode','导出勾选设备':'Export selected devices','导出全部可见设备':'Export all visible devices','设备列表':'Device list','全选':'Select all','清空':'Clear','批量导出 ZIP':'Batch export ZIP','导出行为说明':'Export behavior','跳到最新数据':'Jump to latest data','预览范围':'Preview range','导出 miniSEED':'Export miniSEED','开始时间 UTC':'Start time UTC','结束时间 UTC':'End time UTC','分量':'Channels','设备':'Device','记录数':'Records','字节':'Bytes','首条时间':'First time','最后时间':'Last time','总记录数':'Total records','数据缺口':'Data gaps','缺口':'Gaps','重复包':'Duplicates','异常包':'Bad packets','最新数据':'Last data','最后接收':'Last received','离线':'offline','在线':'online','延迟':'delayed','未分组':'Unassigned','说明':'Notes','客户':'Customer','操作':'Actions','保存':'Save','同步设备':'Sync devices',
    '按设备、客户、三分量和 UTC 时间范围导出原始 miniSEED 数据。数据有中断时，导出仍会包含已有数据，并在批量导出的 gaps.csv 中列出缺口。':'Export raw miniSEED by device, customer, channels, and UTC time range. If data is interrupted, the export still contains available records and lists gaps in gaps.csv for batch exports.',
    '批量导出会生成 ZIP 文件，包含每台设备的 miniSEED 文件、manifest.csv 和 gaps.csv。':'Batch export generates a ZIP file containing miniSEED files, manifest.csv, and gaps.csv.',
    '如果数据中断，导出不会失败；文件只包含实际存在的记录，缺口会保存在 gaps.csv 供后续检查。':'If data is interrupted, export does not fail. Files contain only existing records and gaps are written to gaps.csv for review.',
    '导出的是数据库中保存的原始 raw_mseed 记录，不会重新采样或修改波形。':'Export uses raw_mseed records stored in the database. It does not resample or modify waveforms.',
    '如果所选时间段没有记录，系统会显示友好提示，而不是直接返回 JSON 错误。':'If no records exist in the selected range, the system shows a readable message instead of raw JSON.',
    '如果时间段内存在数据中断，miniSEED 文件仍然可用；ObsPy 等工具会识别为不连续数据段。':'If the selected range contains gaps, the miniSEED file is still valid; tools such as ObsPy will read it as discontinuous data segments.'
  };
  const enToZh={}; Object.entries(zhToEn).forEach(([zh,en])=>{ if(!enToZh[en]) enToZh[en]=zh; });
  Object.assign(enToZh, {'offline':'离线','online':'在线','delayed':'延迟','Last data':'最新数据','Duplicates':'重复包','Bad packets':'异常包','Data gaps':'数据缺口','Records':'记录数','Bytes':'字节','Unassigned':'未分组'});
  function lang(){return localStorage.getItem(KEY)||'en';}
  function tr(s){ if(!s) return s; const lead=(s.match(/^\s*/)||[''])[0], trail=(s.match(/\s*$/)||[''])[0]; let t=s.trim().replace(/\s+/g,' '); if(!t) return s; const d=lang()==='zh'?enToZh:zhToEn; if(d[t]) return lead+d[t]+trail; if(lang()==='zh'){ t=t.replace(/\boffline\b/g,'离线').replace(/\bonline\b/g,'在线').replace(/\bdelayed\b/g,'延迟').replace(/\bDuplicates\b/g,'重复包').replace(/\bLast data\b/g,'最新数据').replace(/\bBad packets\b/g,'异常包').replace(/\bUnassigned\b/g,'未分组'); } else { t=t.replace(/离线/g,'offline').replace(/在线/g,'online').replace(/延迟/g,'delayed').replace(/重复包/g,'Duplicates').replace(/最新数据/g,'Last data').replace(/异常包/g,'Bad packets').replace(/未分组/g,'Unassigned'); } return lead+t+trail; }
  function skip(el){return !el||['SCRIPT','STYLE','CODE','PRE','TEXTAREA','CANVAS','SVG'].includes(el.nodeName)||el.closest('[data-no-i18n]')||el.closest('.js-plotly-plot');}
  function apply(root=document.body){
    const w=document.createTreeWalker(root,NodeFilter.SHOW_TEXT,{acceptNode(n){return n.parentElement&&!skip(n.parentElement)&&n.nodeValue.trim()?NodeFilter.FILTER_ACCEPT:NodeFilter.FILTER_REJECT;}}); const ns=[]; while(w.nextNode()) ns.push(w.currentNode); ns.forEach(n=>{const x=tr(n.nodeValue); if(x!==n.nodeValue)n.nodeValue=x;});
    root.querySelectorAll('*').forEach(el=>{ if(skip(el)) return; ['placeholder','title','aria-label','value'].forEach(a=>{ if(!el.hasAttribute(a)) return; if(a==='value'&&!['button','submit','reset'].includes((el.getAttribute('type')||'').toLowerCase())) return; const v=el.getAttribute(a), x=tr(v); if(x!==v) el.setAttribute(a,x); }); });
  }
  document.addEventListener('DOMContentLoaded',()=>{apply(); const mo=new MutationObserver(()=>apply()); mo.observe(document.body,{childList:true,subtree:true,characterData:true});});
  window.addEventListener('storage',apply);
})();
JS

# Ensure i18n_stage3.js is loaded after existing i18n scripts.
BASE_HTML="$TEMPLATES/base.html"
if [ -f "$BASE_HTML" ] && ! grep -q "i18n_stage3.js" "$BASE_HTML"; then
  sudo cp "$BASE_HTML" "$BASE_HTML.bak_export_i18n_stage3_$TS"
  sudo "$PY" - <<'PY'
from pathlib import Path
p=Path('/opt/mseed-web-portal/app/templates/base.html')
s=p.read_text()
tag='<script src="/static/js/i18n_stage3.js?v=3"></script>'
if '</body>' in s:
    s=s.replace('</body>', tag+'\n</body>')
else:
    s += '\n' + tag + '\n'
p.write_text(s)
print('patched base.html with i18n_stage3')
PY
fi

# Syntax check and restart.
sudo PYTHONPATH="$BASE" MSEED_WEB_CONFIG=/etc/mseed-web-portal/portal.ini "$PY" -m py_compile "$APP/main.py" "$APP/data_reader.py"
sudo systemctl restart mseed-web-portal
sudo systemctl restart nginx

echo "Stage3 export/i18n patch installed. Open /export and press Ctrl+F5."
