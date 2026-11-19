#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/mseed-web-portal"
PY="/opt/miniforge3/envs/mseed-web/bin/python"
TS="$(date +%Y%m%d_%H%M%S)"

if [ ! -d "$APP_DIR/app" ]; then
  echo "ERROR: $APP_DIR/app not found"
  exit 1
fi
if [ ! -x "$PY" ]; then
  echo "ERROR: Python not found at $PY"
  exit 1
fi

mkdir -p "$APP_DIR/app/templates" "$APP_DIR/app/static/css"
cp "$APP_DIR/app/main.py" "$APP_DIR/app/main.py.bak_stage1_$TS"
cp "$APP_DIR/app/app_db.py" "$APP_DIR/app/app_db.py.bak_stage1_$TS"
cp "$APP_DIR/app/data_reader.py" "$APP_DIR/app/data_reader.py.bak_stage1_$TS"
[ -f "$APP_DIR/app/templates/base.html" ] && cp "$APP_DIR/app/templates/base.html" "$APP_DIR/app/templates/base.html.bak_stage1_$TS" || true
[ -f "$APP_DIR/app/templates/dashboard.html" ] && cp "$APP_DIR/app/templates/dashboard.html" "$APP_DIR/app/templates/dashboard.html.bak_stage1_$TS" || true
[ -f "$APP_DIR/app/templates/admin.html" ] && cp "$APP_DIR/app/templates/admin.html" "$APP_DIR/app/templates/admin.html.bak_stage1_$TS" || true
[ -f "$APP_DIR/app/static/css/app.css" ] && cp "$APP_DIR/app/static/css/app.css" "$APP_DIR/app/static/css/app.css.bak_stage1_$TS" || true

# 1) Extend app_db.py with customers, aliases, site metadata and helpers.
if ! grep -q "STAGE1_PRODUCT_PATCH_APP_DB" "$APP_DIR/app/app_db.py"; then
cat >> "$APP_DIR/app/app_db.py" <<'PYCODE'

# STAGE1_PRODUCT_PATCH_APP_DB

def _stage1_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def migrate_stage1(app_db_path: str) -> None:
    """Add customer grouping and device metadata fields without losing data."""
    now = time.time()
    with connect(app_db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                code TEXT,
                contact TEXT,
                notes TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        user_cols = _stage1_columns(conn, "users")
        if "customer_id" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN customer_id INTEGER")
        dev_cols = _stage1_columns(conn, "devices")
        for col, typ in [
            ("customer_id", "INTEGER"),
            ("alias", "TEXT"),
            ("site_name", "TEXT"),
            ("location_note", "TEXT"),
            ("latitude", "REAL"),
            ("longitude", "REAL"),
            ("install_date", "TEXT"),
        ]:
            if col not in dev_cols:
                conn.execute(f"ALTER TABLE devices ADD COLUMN {col} {typ}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_devices_customer ON devices(customer_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_customer ON users(customer_id)")
        # Ensure an internal default customer exists for grouping unassigned devices later.
        conn.execute(
            "INSERT OR IGNORE INTO customers (name, code, contact, notes, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
            ("Unassigned", "UNASSIGNED", "", "Default group for devices and users without a customer.", now, now),
        )
        conn.commit()


def list_customers(app_db_path: str) -> list[sqlite3.Row]:
    migrate_stage1(app_db_path)
    with connect(app_db_path) as conn:
        return list(conn.execute("SELECT * FROM customers WHERE is_active = 1 ORDER BY name"))


def upsert_customer(app_db_path: str, *, name: str, code: str = "", contact: str = "", notes: str = "") -> int:
    migrate_stage1(app_db_path)
    now = time.time()
    name = name.strip()
    if not name:
        raise ValueError("Customer name is required")
    with connect(app_db_path) as conn:
        row = conn.execute("SELECT id FROM customers WHERE name = ?", (name,)).fetchone()
        if row:
            conn.execute(
                "UPDATE customers SET code = ?, contact = ?, notes = ?, is_active = 1, updated_at = ? WHERE id = ?",
                (code.strip(), contact.strip(), notes.strip(), now, row["id"]),
            )
            conn.commit()
            return int(row["id"])
        cur = conn.execute(
            "INSERT INTO customers (name, code, contact, notes, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
            (name, code.strip(), contact.strip(), notes.strip(), now, now),
        )
        conn.commit()
        return int(cur.lastrowid)


def assign_user_customer(app_db_path: str, user_id: int, customer_id: int | None) -> None:
    migrate_stage1(app_db_path)
    with connect(app_db_path) as conn:
        conn.execute("UPDATE users SET customer_id = ? WHERE id = ?", (customer_id, user_id))
        conn.commit()


def update_device_metadata(
    app_db_path: str,
    *,
    device_id: int,
    label: str | None = None,
    alias: str | None = None,
    customer_id: int | None = None,
    site_name: str | None = None,
    location_note: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    install_date: str | None = None,
) -> None:
    migrate_stage1(app_db_path)
    fields: list[str] = []
    args: list[Any] = []
    for k, v in [
        ("label", label),
        ("alias", alias),
        ("customer_id", customer_id),
        ("site_name", site_name),
        ("location_note", location_note),
        ("latitude", latitude),
        ("longitude", longitude),
        ("install_date", install_date),
    ]:
        fields.append(f"{k} = ?")
        args.append(v)
    fields.append("updated_at = ?")
    args.append(time.time())
    args.append(device_id)
    with connect(app_db_path) as conn:
        conn.execute(f"UPDATE devices SET {', '.join(fields)} WHERE id = ?", args)
        conn.commit()


def customer_map(app_db_path: str) -> dict[int, sqlite3.Row]:
    return {int(c["id"]): c for c in list_customers(app_db_path)}

def list_users(app_db_path: str) -> list[sqlite3.Row]:  # overrides earlier definition with customer_id
    migrate_stage1(app_db_path)
    with connect(app_db_path) as conn:
        return list(conn.execute("SELECT id, username, display_name, role, is_active, created_at, last_login_at, customer_id FROM users ORDER BY username"))

PYCODE
fi

# 2) Extend data_reader.py with richer summaries, quality stats and raw miniSEED export.
if ! grep -q "STAGE1_PRODUCT_PATCH_DATA_READER" "$APP_DIR/app/data_reader.py"; then
cat >> "$APP_DIR/app/data_reader.py" <<'PYCODE'

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
PYCODE
fi

# 3) Patch main.py to add migration, routes and data export.
if ! grep -q "STAGE1_PRODUCT_PATCH_MAIN" "$APP_DIR/app/main.py"; then
cat >> "$APP_DIR/app/main.py" <<'PYCODE'

# STAGE1_PRODUCT_PATCH_MAIN

@app.on_event("startup")
def startup_stage1_product_features() -> None:
    try:
        app_db.migrate_stage1(settings.app_db)
        log.info("stage1 product features migrated")
    except Exception:
        log.exception("failed to migrate stage1 product features")


@app.get("/quality", response_class=HTMLResponse)
def quality_page(request: Request, user: dict[str, Any] = Depends(current_user)):
    devices = app_db.list_devices(settings.app_db, user_id=int(user["id"]), admin=is_admin(user))
    cards = []
    from .data_reader import quality_summary as _quality_summary
    for d in devices:
        summary = {"status": "offline", "gap_count": 0, "duplicate_count": 0, "bad_packet_count": 0, "component_status": []}
        quality = {"gaps": [], "duplicates": [], "bad_packets": [], "gap_count": 0, "duplicate_count": 0, "bad_packet_count": 0}
        try:
            safe_path = safe_receiver_db_path(settings.receiver_db_dir, d["db_path"])
            summary = device_summary(safe_path, d["device_key"])
            quality = _quality_summary(safe_path, d["device_key"], limit=20)
        except Exception as exc:
            log.warning("quality summary failed device id=%s: %s", d["id"], exc)
        cards.append({"device": dict(d), "summary": summary, "quality": quality})
    return templates.TemplateResponse(request, "quality.html", template_context(request, cards=cards))


@app.get("/export", response_class=HTMLResponse)
def export_page(request: Request, device_id: int | None = None, user: dict[str, Any] = Depends(current_user)):
    devices = app_db.list_devices(settings.app_db, user_id=int(user["id"]), admin=is_admin(user))
    return templates.TemplateResponse(request, "export.html", template_context(request, devices=[dict(d) for d in devices], selected_device_id=device_id))


@app.get("/api/quality")
def api_quality(device_id: int = Query(...), user: dict[str, Any] = Depends(current_user)):
    d = app_db.get_device_for_user(settings.app_db, device_id, int(user["id"]), admin=is_admin(user))
    if not d:
        raise HTTPException(status_code=404, detail="Device not found")
    from .data_reader import quality_summary as _quality_summary
    safe_path = safe_receiver_db_path(settings.receiver_db_dir, d["db_path"])
    summary = device_summary(safe_path, d["device_key"])
    quality = _quality_summary(safe_path, d["device_key"], limit=100)
    return {"device": dict(d), "summary": summary, "quality": quality}


@app.get("/export/download")
def export_download(
    device_id: int = Query(...),
    components: str = Query(""),
    start: str = Query(...),
    end: str = Query(...),
    user: dict[str, Any] = Depends(current_user),
):
    from fastapi.responses import Response
    from .data_reader import export_mseed_bytes as _export_mseed_bytes
    d = app_db.get_device_for_user(settings.app_db, device_id, int(user["id"]), admin=is_admin(user))
    if not d:
        raise HTTPException(status_code=404, detail="Device not found")
    comps = [c.strip() for c in components.split(",") if c.strip()]
    start_unix = parse_datetime_or_unix(start)
    end_unix = parse_datetime_or_unix(end)
    safe_path = safe_receiver_db_path(settings.receiver_db_dir, d["db_path"])
    blob, record_count = _export_mseed_bytes(
        safe_path,
        device_key=d["device_key"],
        components=comps or None,
        start_unix=start_unix,
        end_unix=end_unix,
        max_records=200000,
    )
    if not blob:
        raise HTTPException(status_code=404, detail="No records found in the requested range")
    comp_part = "ALL" if not comps else "-".join(comps)
    serial = d.get("device_key") if hasattr(d, "get") else d["device_key"]
    filename = f"{serial}_{comp_part}_{int(start_unix)}_{int(end_unix)}.mseed"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-miniSEED-Record-Count": str(record_count),
    }
    return Response(content=blob, media_type="application/vnd.fdsn.mseed", headers=headers)


@app.post("/admin/customers")
def admin_upsert_customer(
    name: str = Form(...),
    code: str = Form(""),
    contact: str = Form(""),
    notes: str = Form(""),
    user: dict[str, Any] = Depends(admin_user),
):
    app_db.upsert_customer(settings.app_db, name=name, code=code, contact=contact, notes=notes)
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/user-customer")
def admin_user_customer(
    user_id: int = Form(...),
    customer_id: int = Form(0),
    user: dict[str, Any] = Depends(admin_user),
):
    app_db.assign_user_customer(settings.app_db, user_id, customer_id if customer_id > 0 else None)
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/device-metadata")
def admin_device_metadata(
    device_id: int = Form(...),
    label: str = Form(""),
    alias: str = Form(""),
    customer_id: int = Form(0),
    site_name: str = Form(""),
    location_note: str = Form(""),
    latitude: str = Form(""),
    longitude: str = Form(""),
    install_date: str = Form(""),
    user: dict[str, Any] = Depends(admin_user),
):
    def to_float(v: str):
        v = (v or "").strip()
        return float(v) if v else None
    app_db.update_device_metadata(
        settings.app_db,
        device_id=device_id,
        label=label.strip() or None,
        alias=alias.strip() or None,
        customer_id=customer_id if customer_id > 0 else None,
        site_name=site_name.strip() or None,
        location_note=location_note.strip() or None,
        latitude=to_float(latitude),
        longitude=to_float(longitude),
        install_date=install_date.strip() or None,
    )
    return RedirectResponse(url="/admin", status_code=303)
PYCODE
fi

# 4) Patch existing admin_page to pass customers if possible.
"$PY" - <<'PY'
from pathlib import Path
p = Path('/opt/mseed-web-portal/app/main.py')
s = p.read_text()
if 'customers = app_db.list_customers(settings.app_db)' not in s:
    target = '    devices = app_db.list_devices(settings.app_db, admin=True)\n'
    if target in s:
        s = s.replace(target, target + '    customers = app_db.list_customers(settings.app_db)\n', 1)
if 'customers=[dict(c) for c in customers]' not in s:
    old = 'template_context(request, users=[dict(u) for u in users], devices=[dict(d) for d in devices], assigned=assigned)'
    new = 'template_context(request, users=[dict(u) for u in users], devices=[dict(d) for d in devices], assigned=assigned, customers=[dict(c) for c in customers])'
    if old in s:
        s = s.replace(old, new, 1)
p.write_text(s)
PY

# 5) Base navigation: preserve existing language switch if present; only add links.
"$PY" - <<'PY'
from pathlib import Path
p = Path('/opt/mseed-web-portal/app/templates/base.html')
s = p.read_text()
if 'href="/quality"' not in s:
    anchor = '<li class="nav-item"><a class="nav-link" href="/history">历史波形</a></li>'
    if anchor in s:
        s = s.replace(anchor, anchor + '\n        <li class="nav-item"><a class="nav-link" href="/quality">数据质量</a></li>\n        <li class="nav-item"><a class="nav-link" href="/export">数据导出</a></li>', 1)
    else:
        # Fallback: insert before admin nav.
        marker = "{% if user.role == 'admin' %}"
        s = s.replace(marker, '<li class="nav-item"><a class="nav-link" href="/quality">数据质量</a></li>\n        <li class="nav-item"><a class="nav-link" href="/export">数据导出</a></li>\n        ' + marker, 1)
p.write_text(s)
PY

# 6) Templates.
cat > "$APP_DIR/app/templates/dashboard.html" <<'HTML'
{% extends "base.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-end mb-4 flex-wrap gap-3">
  <div>
    <div class="portal-pill mb-2">Overview</div>
    <h1 class="h3 fw-bold mb-1">设备总览</h1>
    <p class="text-secondary mb-0">显示设备在线状态、最新数据时间、三分量状态和最近一小时入库量。</p>
  </div>
  <div class="text-secondary small">在线阈值：最近 5 分钟内收到数据</div>
</div>

{% if not cards %}
<div class="empty-state">当前账号还没有分配设备。请联系管理员分配仪器权限。</div>
{% endif %}

<div class="row g-4">
  {% for card in cards %}
  {% set d = card.device %}
  {% set s = card.summary %}
  {% set st = s.status or 'offline' %}
  <div class="col-12 col-md-6 col-xl-4">
    <div class="device-card h-100 status-card status-{{ st }}">
      <div class="d-flex justify-content-between align-items-start mb-3">
        <div>
          <div class="text-secondary small">{{ d.instrument_type or 'DEV' }} / {{ d.instrument_serial or d.device_key }}</div>
          <h2 class="h5 fw-bold mb-1">{{ d.alias or d.label }}</h2>
          <div class="small text-secondary">{{ d.site_name or d.label }} · {{ d.client_ip or 'unknown IP' }}:{{ d.server_port or '-' }}</div>
        </div>
        <span class="status-pill status-{{ st }}">{{ '在线' if st == 'online' else ('延迟' if st == 'stale' else '离线') }}</span>
      </div>
      <div class="metric-grid mb-3">
        <div><span>总包数</span><strong>{{ s.total_packets }}</strong></div>
        <div><span>最近 1 小时</span><strong>{{ s.one_hour_packets or 0 }}</strong></div>
        <div><span>最新数据时间</span><strong class="unix-time" data-unix="{{ s.last_start or '' }}">-</strong></div>
        <div><span>最后接收时间</span><strong class="unix-time" data-unix="{{ s.last_recv or '' }}">-</strong></div>
      </div>
      <div class="component-row mb-3">
        {% for c in s.component_status %}
        <span class="component-badge component-{{ c.status }}">{{ c.component }} <small>{{ c.status }}</small></span>
        {% endfor %}
        {% for m in s.missing_components %}
        <span class="component-badge component-missing">{{ m }} <small>missing</small></span>
        {% endfor %}
      </div>
      <div class="quality-mini mb-4">
        <span>Gaps: <strong>{{ s.gap_count }}</strong></span>
        <span>Duplicates: <strong>{{ s.duplicate_count }}</strong></span>
        <span>Bad: <strong>{{ s.bad_packet_count }}</strong></span>
      </div>
      <div class="d-flex flex-wrap gap-2">
        <a class="btn btn-sm btn-primary" href="/live?device_id={{ d.id }}">实时波形</a>
        <a class="btn btn-sm btn-outline-light" href="/history?device_id={{ d.id }}">历史查询</a>
        <a class="btn btn-sm btn-outline-light" href="/quality?device_id={{ d.id }}">数据质量</a>
        <a class="btn btn-sm btn-outline-light" href="/export?device_id={{ d.id }}">导出</a>
      </div>
    </div>
  </div>
  {% endfor %}
</div>
<script src="/static/js/time.js"></script>
{% endblock %}
HTML

cat > "$APP_DIR/app/templates/quality.html" <<'HTML'
{% extends "base.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-end mb-4 flex-wrap gap-3">
  <div>
    <div class="portal-pill mb-2">Data quality</div>
    <h1 class="h3 fw-bold mb-1">数据质量</h1>
    <p class="text-secondary mb-0">查看设备断流、重复包、异常包和三分量完整性。</p>
  </div>
</div>

<div class="row g-4">
{% for card in cards %}
  {% set d = card.device %}
  {% set s = card.summary %}
  {% set q = card.quality %}
  <div class="col-12 col-xl-6">
    <div class="device-card h-100">
      <div class="d-flex justify-content-between align-items-start mb-3">
        <div>
          <h2 class="h5 fw-bold mb-1">{{ d.alias or d.label }}</h2>
          <div class="small text-secondary">{{ d.device_key }} · {{ d.site_name or '' }}</div>
        </div>
        <span class="status-pill status-{{ s.status }}">{{ s.status }}</span>
      </div>
      <div class="metric-grid mb-3">
        <div><span>Gaps</span><strong>{{ q.gap_count }}</strong></div>
        <div><span>Duplicates</span><strong>{{ q.duplicate_count }}</strong></div>
        <div><span>Bad packets</span><strong>{{ q.bad_packet_count }}</strong></div>
        <div><span>Last data</span><strong class="unix-time" data-unix="{{ s.last_start or '' }}">-</strong></div>
      </div>
      <div class="component-row mb-3">
        {% for c in s.component_status %}
        <span class="component-badge component-{{ c.status }}">{{ c.component }} <small>{{ c.status }}</small></span>
        {% endfor %}
        {% for m in s.missing_components %}
        <span class="component-badge component-missing">{{ m }} <small>missing</small></span>
        {% endfor %}
      </div>
      <details class="quality-details">
        <summary>最近质量事件</summary>
        <div class="table-responsive mt-3">
          <table class="table table-dark table-sm align-middle">
            <thead><tr><th>类别</th><th>详情</th></tr></thead>
            <tbody>
              {% for row in q.gaps[:8] %}<tr><td>gap</td><td><code>{{ row }}</code></td></tr>{% endfor %}
              {% for row in q.duplicates[:8] %}<tr><td>duplicate</td><td><code>{{ row }}</code></td></tr>{% endfor %}
              {% for row in q.bad_packets[:8] %}<tr><td>bad</td><td><code>{{ row }}</code></td></tr>{% endfor %}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  </div>
{% endfor %}
</div>
<script src="/static/js/time.js"></script>
{% endblock %}
HTML

cat > "$APP_DIR/app/templates/export.html" <<'HTML'
{% extends "base.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-end mb-4 flex-wrap gap-3">
  <div>
    <div class="portal-pill mb-2">Data export</div>
    <h1 class="h3 fw-bold mb-1">数据导出</h1>
    <p class="text-secondary mb-0">按设备、三分量和 UTC 时间范围导出原始 miniSEED 数据。</p>
  </div>
</div>

<div class="control-panel mb-4">
  <form id="exportForm" method="get" action="/export/download" class="row g-3 align-items-end">
    <div class="col-12 col-lg-3">
      <label class="form-label">设备</label>
      <select id="deviceSelect" name="device_id" class="form-select">
        {% for d in devices %}
        <option value="{{ d.id }}" {% if selected_device_id and selected_device_id == d.id %}selected{% endif %}>{{ d.alias or d.label }} / {{ d.device_key }}</option>
        {% endfor %}
      </select>
    </div>
    <div class="col-12 col-lg-3">
      <label class="form-label">开始时间 UTC</label>
      <input id="startInput" name="start" class="form-control" placeholder="2026-06-30T15:30:00Z" required>
    </div>
    <div class="col-12 col-lg-3">
      <label class="form-label">结束时间 UTC</label>
      <input id="endInput" name="end" class="form-control" placeholder="2026-06-30T15:35:00Z" required>
    </div>
    <div class="col-12 col-lg-3">
      <label class="form-label">分量</label>
      <div id="exportComponentChecks" class="component-checks"></div>
      <input type="hidden" id="componentsInput" name="components" value="">
    </div>
    <div class="col-12 d-flex gap-2">
      <button type="button" id="latestBtn" class="btn btn-outline-light">最近 30 分钟</button>
      <button class="btn btn-primary">导出 miniSEED</button>
    </div>
  </form>
</div>

<div class="device-card">
  <h2 class="h6 fw-bold mb-2">说明</h2>
  <p class="text-secondary mb-0">导出的文件直接由数据库中的 <code>raw_mseed</code> 拼接生成，适合后续用 ObsPy、SeisComP、SAC 转换工具或科研软件继续处理。</p>
</div>

<script>
function isoNoMs(d){ return d.toISOString().replace('.000Z','Z'); }
async function fetchJSON(url){ const r = await fetch(url, {credentials:'same-origin'}); if(!r.ok) throw new Error(await r.text()); return await r.json(); }
function setLatestWindow(){ const end = new Date(); const start = new Date(end.getTime() - 30*60*1000); document.getElementById('startInput').value = isoNoMs(start); document.getElementById('endInput').value = isoNoMs(end); }
async function loadExportComponents(){
  const sel = document.getElementById('deviceSelect'); if(!sel || !sel.value) return;
  const box = document.getElementById('exportComponentChecks'); box.innerHTML = '';
  const p = await fetchJSON('/api/components?device_id=' + encodeURIComponent(sel.value));
  (p.components || []).forEach((c, idx) => {
    const lab = document.createElement('label'); lab.className = 'component-badge';
    lab.innerHTML = `<input class="form-check-input mt-0 export-comp" type="checkbox" value="${c.component}" ${idx < 3 ? 'checked' : ''}> ${c.component}`;
    box.appendChild(lab);
  });
  updateComponentInput();
}
function updateComponentInput(){ document.getElementById('componentsInput').value = Array.from(document.querySelectorAll('.export-comp:checked')).map(x=>x.value).join(','); }
document.addEventListener('DOMContentLoaded', () => {
  setLatestWindow();
  loadExportComponents().catch(err => console.error(err));
  document.getElementById('deviceSelect')?.addEventListener('change', () => loadExportComponents().catch(console.error));
  document.getElementById('exportComponentChecks')?.addEventListener('change', updateComponentInput);
  document.getElementById('latestBtn')?.addEventListener('click', setLatestWindow);
  document.getElementById('exportForm')?.addEventListener('submit', updateComponentInput);
});
</script>
{% endblock %}
HTML

cat > "$APP_DIR/app/templates/admin.html" <<'HTML'
{% extends "base.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-end mb-4 flex-wrap gap-3">
  <div>
    <div class="portal-pill mb-2">Admin</div>
    <h1 class="h3 fw-bold mb-1">账号、客户与设备权限</h1>
    <p class="text-secondary mb-0">同步接收端数据库，创建客户账号，维护客户分组、设备别名和设备权限。</p>
  </div>
  <form method="post" action="/admin/sync-devices"><button class="btn btn-primary">同步设备</button></form>
</div>

<div class="row g-4">
  <div class="col-12 col-xl-4">
    <div class="device-card mb-4">
      <h2 class="h6 fw-bold mb-3">创建 / 更新用户</h2>
      <form method="post" action="/admin/users">
        <label class="form-label">账号</label><input class="form-control mb-3" name="username" required>
        <label class="form-label">显示名称</label><input class="form-control mb-3" name="display_name">
        <label class="form-label">密码</label><input class="form-control mb-3" type="password" name="password" required>
        <label class="form-label">角色</label><select class="form-select mb-3" name="role"><option value="user">user</option><option value="admin">admin</option></select>
        <button class="btn btn-primary w-100">保存用户</button>
      </form>
    </div>
    <div class="device-card">
      <h2 class="h6 fw-bold mb-3">创建 / 更新客户分组</h2>
      <form method="post" action="/admin/customers">
        <label class="form-label">客户名称</label><input class="form-control mb-3" name="name" required>
        <label class="form-label">客户代码</label><input class="form-control mb-3" name="code" placeholder="ACME / TUM / DEMO">
        <label class="form-label">联系人</label><input class="form-control mb-3" name="contact">
        <label class="form-label">备注</label><input class="form-control mb-3" name="notes">
        <button class="btn btn-primary w-100">保存客户</button>
      </form>
    </div>
  </div>

  <div class="col-12 col-xl-8">
    <div class="device-card mb-4">
      <h2 class="h6 fw-bold mb-3">设备别名与客户分组</h2>
      <div class="table-responsive">
        <table class="table table-dark table-sm align-middle">
          <thead><tr><th>ID</th><th>设备</th><th>别名 / 站点</th><th>客户</th><th>操作</th></tr></thead>
          <tbody>
          {% for d in devices %}
          <tr>
            <td>{{ d.id }}</td>
            <td><div class="fw-semibold">{{ d.device_key }}</div><div class="small text-secondary">{{ d.instrument_type }} / {{ d.instrument_serial }}</div></td>
            <td style="min-width:260px;">
              <form method="post" action="/admin/device-metadata" class="row g-2">
                <input type="hidden" name="device_id" value="{{ d.id }}">
                <div class="col-12"><input class="form-control form-control-sm" name="label" value="{{ d.label }}" placeholder="显示标签"></div>
                <div class="col-6"><input class="form-control form-control-sm" name="alias" value="{{ d.alias or '' }}" placeholder="客户可读别名"></div>
                <div class="col-6"><input class="form-control form-control-sm" name="site_name" value="{{ d.site_name or '' }}" placeholder="站点名称"></div>
                <div class="col-12"><input class="form-control form-control-sm" name="location_note" value="{{ d.location_note or '' }}" placeholder="安装位置说明"></div>
                <div class="col-4"><input class="form-control form-control-sm" name="latitude" value="{{ d.latitude or '' }}" placeholder="Lat"></div>
                <div class="col-4"><input class="form-control form-control-sm" name="longitude" value="{{ d.longitude or '' }}" placeholder="Lon"></div>
                <div class="col-4"><input class="form-control form-control-sm" name="install_date" value="{{ d.install_date or '' }}" placeholder="安装日期"></div>
            </td>
            <td style="min-width:180px;">
                <select class="form-select form-select-sm" name="customer_id">
                  <option value="0">未分组</option>
                  {% for c in customers|default([]) %}<option value="{{ c.id }}" {% if d.customer_id and d.customer_id == c.id %}selected{% endif %}>{{ c.name }}</option>{% endfor %}
                </select>
            </td>
            <td><button class="btn btn-sm btn-primary">保存</button></form></td>
          </tr>
          {% endfor %}
          </tbody>
        </table>
      </div>
    </div>

    <div class="device-card mb-4">
      <h2 class="h6 fw-bold mb-3">用户列表与客户归属</h2>
      <div class="table-responsive">
        <table class="table table-dark table-sm align-middle">
          <thead><tr><th>ID</th><th>账号</th><th>显示名称</th><th>角色</th><th>客户分组</th></tr></thead>
          <tbody>
          {% for u in users %}
          <tr>
            <td>{{ u.id }}</td><td>{{ u.username }}</td><td>{{ u.display_name }}</td><td>{{ u.role }}</td>
            <td>
              <form method="post" action="/admin/user-customer" class="d-flex gap-2">
                <input type="hidden" name="user_id" value="{{ u.id }}">
                <select class="form-select form-select-sm" name="customer_id">
                  <option value="0">未分组</option>
                  {% for c in customers|default([]) %}<option value="{{ c.id }}" {% if u.customer_id and u.customer_id == c.id %}selected{% endif %}>{{ c.name }}</option>{% endfor %}
                </select>
                <button class="btn btn-sm btn-outline-light">保存</button>
              </form>
            </td>
          </tr>
          {% endfor %}
          </tbody>
        </table>
      </div>
    </div>

    <div class="device-card">
      <h2 class="h6 fw-bold mb-3">设备权限</h2>
      <div class="table-responsive">
        <table class="table table-dark table-sm align-middle">
          <thead><tr><th>用户</th><th>已授权设备</th><th>授权新设备</th></tr></thead>
          <tbody>
          {% for u in users %}
          <tr>
            <td>{{ u.username }}</td>
            <td>
              {% for d in devices %}
                {% if d.id in assigned[u.id] %}
                <form method="post" action="/admin/revoke" class="d-inline">
                  <input type="hidden" name="user_id" value="{{ u.id }}"><input type="hidden" name="device_id" value="{{ d.id }}">
                  <button class="btn btn-sm btn-outline-light mb-1">{{ d.alias or d.label }} ×</button>
                </form>
                {% endif %}
              {% endfor %}
            </td>
            <td>
              <form method="post" action="/admin/grant" class="d-flex gap-2">
                <input type="hidden" name="user_id" value="{{ u.id }}">
                <select class="form-select form-select-sm" name="device_id">
                  {% for d in devices %}<option value="{{ d.id }}">{{ d.alias or d.label }} / {{ d.device_key }}</option>{% endfor %}
                </select>
                <button class="btn btn-sm btn-primary">授权</button>
              </form>
            </td>
          </tr>
          {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </div>
</div>
{% endblock %}
HTML

# 7) CSS additions.
if ! grep -q "STAGE1_PRODUCT_PATCH_CSS" "$APP_DIR/app/static/css/app.css"; then
cat >> "$APP_DIR/app/static/css/app.css" <<'CSS'

/* STAGE1_PRODUCT_PATCH_CSS */
.status-card { position: relative; overflow: hidden; }
.status-card::before { content:""; position:absolute; inset:0 0 auto 0; height:4px; background: rgba(255,255,255,.18); }
.status-card.status-online::before { background: linear-gradient(90deg,#5ee6a8,#35d399); }
.status-card.status-stale::before { background: linear-gradient(90deg,#fbbf24,#f59e0b); }
.status-card.status-offline::before { background: linear-gradient(90deg,#ef4444,#b91c1c); }
.status-pill { display:inline-flex; align-items:center; border-radius:999px; padding:5px 10px; font-size:12px; border:1px solid rgba(255,255,255,.18); background:rgba(255,255,255,.08); }
.status-pill.status-online { color:#c8ffe5; border-color:rgba(94,230,168,.35); background:rgba(94,230,168,.10); }
.status-pill.status-stale { color:#fde68a; border-color:rgba(251,191,36,.35); background:rgba(251,191,36,.10); }
.status-pill.status-offline { color:#fecaca; border-color:rgba(239,68,68,.35); background:rgba(239,68,68,.10); }
.component-online { background:rgba(94,230,168,.10); border-color:rgba(94,230,168,.24); color:#c8ffe5; }
.component-stale { background:rgba(251,191,36,.10); border-color:rgba(251,191,36,.24); color:#fde68a; }
.component-offline, .component-missing { background:rgba(239,68,68,.10); border-color:rgba(239,68,68,.24); color:#fecaca; }
.quality-mini { display:flex; flex-wrap:wrap; gap:8px; color:var(--muted); font-size:12px; }
.quality-mini span { background:var(--panel-2); border-radius:999px; padding:5px 9px; }
.quality-details summary { cursor:pointer; color:#b9cdfd; }
.quality-details code { color:#dbeafe; white-space:pre-wrap; word-break:break-word; }
.table input.form-control-sm, .table select.form-select-sm { min-width: 0; }
CSS
fi

# 8) Compile and migrate app database.
"$PY" -m py_compile "$APP_DIR/app/main.py" "$APP_DIR/app/app_db.py" "$APP_DIR/app/data_reader.py"
MSEED_WEB_CONFIG="/etc/mseed-web-portal/portal.ini" "$PY" - <<'PY'
from app.config import load_settings
from app import app_db
s = load_settings()
app_db.init_db(s.app_db)
app_db.migrate_stage1(s.app_db)
print('migrated:', s.app_db)
PY

# 9) Restart services.
systemctl restart mseed-web-portal
systemctl restart nginx || true

echo "OK: Stage-1 product patch installed."
echo "Open: /dashboard, /quality, /export, /admin. Press Ctrl+F5 in the browser."
