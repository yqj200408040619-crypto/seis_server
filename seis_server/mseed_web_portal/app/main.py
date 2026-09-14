from __future__ import annotations

import logging
import os
import time
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen
import json

import uvicorn
from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import app_db
from .upstream_identity import acquire_identity
from .config import DEFAULT_CONFIG_PATH, load_settings
from .data_reader import (
    device_summary,
    discover_devices,
    list_components,
    parse_datetime_or_unix,
    read_waveform,
    safe_receiver_db_path,
)

settings = load_settings()
os.makedirs(settings.log_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(settings.log_dir, "web.log")),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("mseed_web_portal")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

app = FastAPI(title="miniSEED Web Portal", version="1.0.0")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


def template_context(request: Request, **kwargs: Any) -> dict[str, Any]:
    ctx = {
        "request": request,
        "brand": settings.brand,
        "user": request.state.user,
        "refresh_seconds": settings.refresh_seconds,
        "latest_default_seconds": settings.latest_default_seconds,
    }
    ctx.update(kwargs)
    return ctx


@app.on_event("startup")
def startup() -> None:
    app_db.init_db(settings.app_db)
    log.info("mseed web portal started config=%s app_db=%s receiver_db_dir=%s", DEFAULT_CONFIG_PATH, settings.app_db, settings.receiver_db_dir)


@app.middleware("http")
async def load_user(request: Request, call_next):
    user_id = request.session.get("user_id")
    request.state.user = None
    if user_id:
        user = app_db.get_user_by_id(settings.app_db, int(user_id))
        request.state.user = dict(user) if user else None
    return await call_next(request)


# Important:
# SessionMiddleware must be added after the custom load_user middleware is registered.
# Otherwise request.session may not be initialized when load_user runs.


def current_user(request: Request) -> dict[str, Any]:
    user = request.state.user
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


def admin_user(request: Request) -> dict[str, Any]:
    user = current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


def is_admin(user: dict[str, Any]) -> bool:
    return user.get("role") == "admin"


def receiver_preview_records(device: dict[str, Any], component: str | None, seconds: int, max_points: int) -> list[dict[str, Any]]:
    """Read the receiver's loopback-only transient decoded-record feed."""
    device_id = f"{device['client_ip']}_{device['server_port']}_{device['device_key']}"
    params = {"device_id": device_id, "seconds": min(seconds, 300), "max_points": max_points}
    if component:
        params["component"] = component
    try:
        with urlopen(f"{settings.receiver_preview_url}?{urlencode(params)}", timeout=0.75) as response:
            payload = json.loads(response.read().decode("utf-8"))
        records = payload.get("records", [])
        return records if isinstance(records, list) else []
    except Exception as exc:
        # Preview is optional: HDF5-backed live monitoring continues when the
        # receiver is restarting or the local preview endpoint is unavailable.
        log.debug("receiver preview unavailable device=%s: %s", device_id, exc)
        return []


def merge_preview_waveforms(data: dict[str, Any], records: list[dict[str, Any]], start_unix: float, end_unix: float) -> None:
    """Merge transient records into portal traces, preferring preview points.

    Timestamp de-duplication prevents a record from being drawn twice after
    its normal HDF5 commit becomes visible to the portal.
    """
    by_stream: dict[str, dict[str, Any]] = {}
    for trace in data.get("traces", []):
        key = str(trace.get("stream_key", ""))
        target = by_stream.setdefault(key, {"stream_key": key, "component": trace.get("component", ""), "sampling_rate": trace.get("sampling_rate", 0.0), "npts_original": 0, "points": []})
        target["points"].extend(trace.get("points", []))
        target["npts_original"] += int(trace.get("npts_original", 0))
    for record in records:
        try:
            sr = float(record["sampling_rate"])
            start = float(record["start_unix"])
            step = max(1, int(record.get("sample_step", 1)))
            samples = record.get("samples", [])
            if sr <= 0 or not isinstance(samples, list):
                continue
        except (KeyError, TypeError, ValueError):
            continue
        key = str(record.get("stream_key", ""))
        target = by_stream.setdefault(key, {"stream_key": key, "component": record.get("component", ""), "sampling_rate": sr, "npts_original": 0, "points": []})
        for idx, sample in enumerate(samples):
            timestamp = start + (idx * step / sr)
            if start_unix <= timestamp <= end_unix:
                target["points"].append({"t": timestamp, "y": float(sample)})
                target["npts_original"] += step
    merged = []
    for trace in by_stream.values():
        unique = {round(float(point["t"]), 9): point for point in trace["points"]}
        trace["points"] = [unique[key] for key in sorted(unique)]
        if trace["points"]:
            merged.append(trace)
    data["traces"] = merged
    data["points"] = merged[0]["points"] if len(merged) == 1 else []
    data["point_count"] = sum(len(trace["points"]) for trace in merged)
    data["preview_packet_count"] = len(records)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        return RedirectResponse(url="/login", status_code=303)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    if request.state.user:
        return RedirectResponse(url="/dashboard", status_code=303)
    return RedirectResponse(url="/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if request.state.user:
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse(request, "login.html", template_context(request, error=None))


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    user = app_db.get_user_by_username(settings.app_db, "admin") if username.strip().lower() == "admin" else None
    if not user:
        try:
            identity = acquire_identity("http://58.17.148.43:9000", username.strip(), password)
            import requests
            response = requests.get("http://58.17.148.43:9000/prod-api/earthquake/app/getMyDeviceList", headers={"Authorization": f"Bearer {identity.access_token}"}, timeout=15)
            rows = (response.json().get("rows") or []) if response.ok else []
            uid = app_db.create_or_update_user(settings.app_db, username.strip(), password=password, display_name=identity.username, role="user")
            with app_db.connect(settings.app_db) as conn:
                conn.execute("DELETE FROM user_devices WHERE user_id = ?", (uid,))
                devices = conn.execute("SELECT id,device_key,instrument_serial FROM devices WHERE is_active=1").fetchall()
            wanted = {str(x.get("deviceNo") or x.get("device_key") or "").strip() for x in rows}
            for x in rows:
                topic=(x.get("topicInfo") or {}).get("dataTopic", "")
                if topic.startswith("wt_"): wanted.add(topic[3:])
            for d in devices:
                if str(d["device_key"]) in wanted or str(d["instrument_serial"]) in wanted: app_db.grant_device(settings.app_db, uid, int(d["id"]))
            user = app_db.get_user_by_id(settings.app_db, uid)
        except Exception as exc:
            log.warning("upstream login failed for user=%s: %s", username, exc)
    if not user:
        return templates.TemplateResponse(request, "login.html", template_context(request, error="用户名或密码错误。"), status_code=401)
    request.session.clear()
    request.session["user_id"] = int(user["id"])
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user: dict[str, Any] = Depends(current_user)):
    devices = app_db.list_devices(settings.app_db, user_id=int(user["id"]), admin=is_admin(user))
    cards = []
    for d in devices:
        summary = {"components": [], "total_packets": 0, "last_start": None}
        try:
            safe_path = safe_receiver_db_path(settings.receiver_db_dir, d["db_path"])
            summary = device_summary(safe_path, d["device_key"])
        except Exception as exc:
            log.warning("failed to summarize device id=%s: %s", d["id"], exc)
        cards.append({"device": dict(d), "summary": summary})
    return templates.TemplateResponse(request, "dashboard.html", template_context(request, cards=cards))


@app.get("/live", response_class=HTMLResponse)
def live_page(request: Request, device_id: int | None = None, user: dict[str, Any] = Depends(current_user)):
    devices = app_db.list_devices(settings.app_db, user_id=int(user["id"]), admin=is_admin(user))
    return templates.TemplateResponse(request, "live.html", template_context(request, devices=[dict(d) for d in devices], selected_device_id=device_id))


@app.get("/history", response_class=HTMLResponse)
def history_page(request: Request, device_id: int | None = None, user: dict[str, Any] = Depends(current_user)):
    devices = app_db.list_devices(settings.app_db, user_id=int(user["id"]), admin=is_admin(user))
    return templates.TemplateResponse(request, "history.html", template_context(request, devices=[dict(d) for d in devices], selected_device_id=device_id))


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, user: dict[str, Any] = Depends(admin_user)):
    users = app_db.list_users(settings.app_db)
    devices = app_db.list_devices(settings.app_db, admin=True)
    customers = app_db.list_customers(settings.app_db)
    access_rules = app_db.list_customer_device_rules(settings.app_db) if hasattr(app_db, "list_customer_device_rules") else []
    assigned = {int(u["id"]): app_db.user_device_ids(settings.app_db, int(u["id"])) for u in users}
    return templates.TemplateResponse(request, "admin.html",
        template_context(request, users=[dict(u) for u in users], devices=[dict(d) for d in devices], assigned=assigned, customers=[dict(c) for c in customers], access_rules=[dict(r) for r in access_rules]),
    )


@app.post("/admin/sync-devices")
def admin_sync_devices(user: dict[str, Any] = Depends(admin_user)):
    found = discover_devices(settings.receiver_db_dir)
    count = 0
    for d in found:
        app_db.upsert_device(
            settings.app_db,
            label=d.label,
            db_path=d.db_path,
            device_key=d.device_key,
            instrument_type=d.instrument_type,
            instrument_serial=d.instrument_serial,
            client_ip=d.client_ip,
            server_port=d.server_port,
        )
        count += 1
    log.info("admin sync devices count=%s user=%s", count, user["username"])
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/users_old_disabled_stage5")
def admin_create_user_old_disabled_stage5(
    username: str = Form(...),
    password: str = Form(...),
    display_name: str = Form(""),
    role: str = Form("user"),
    user: dict[str, Any] = Depends(admin_user),
):
    role = "admin" if role == "admin" else "user"
    app_db.create_or_update_user(settings.app_db, username=username.strip(), password=password, display_name=display_name.strip() or username.strip(), role=role)
    log.info("admin created/updated user=%s by=%s", username, user["username"])
    return RedirectResponse(url="/admin", status_code=303)



# STAGE5_FIX_SAVE_USER_ROUTE
@app.post("/admin/users")
def admin_create_user_stage5_safe(
    username: str = Form(...),
    password: str = Form(""),
    display_name: str = Form(""),
    role: str = Form("user"),
    customer_id: str = Form(""),
    email: str = Form(""),
    is_active: str = Form("1"),
    user: dict[str, Any] = Depends(admin_user),
):
    try:
        from . import app_db as _app_db
        cid = None
        if str(customer_id).strip():
            try:
                cid = int(str(customer_id).strip())
            except Exception:
                cid = None
        active = 0 if str(is_active).lower() in ("0", "false", "off", "no") else 1
        _app_db.stage5_create_or_update_user_safe(
            settings.app_db,
            username=username.strip(),
            password=password or None,
            display_name=display_name.strip() or username.strip(),
            role=role,
            customer_id=cid,
            email=email.strip() or None,
            is_active=active,
        )
        log.info("admin saved user=%s by=%s", username, user.get("username"))
    except Exception as exc:
        log.exception("admin save user failed")
        from fastapi.responses import HTMLResponse
        html = "<!doctype html><html><head><meta charset='utf-8'><title>Save user failed</title></head><body style='font-family:Arial;background:#0f172a;color:#e5e7eb;padding:40px'><div style='max-width:820px;margin:auto;background:#111827;border:1px solid #334155;border-radius:18px;padding:28px'><h1>Save user failed</h1><p>The user was not saved.</p><pre style='white-space:pre-wrap;color:#fca5a5'>" + str(exc) + "</pre><p><a style='color:#60a5fa' href='/admin'>Back to Admin</a></p></div></body></html>"
        return HTMLResponse(html, status_code=400)
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/grant")
def admin_grant(user_id: int = Form(...), device_id: int = Form(...), user: dict[str, Any] = Depends(admin_user)):
    app_db.grant_device(settings.app_db, user_id, device_id)
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/revoke")
def admin_revoke(user_id: int = Form(...), device_id: int = Form(...), user: dict[str, Any] = Depends(admin_user)):
    app_db.revoke_device(settings.app_db, user_id, device_id)
    return RedirectResponse(url="/admin", status_code=303)




# BULK_CUSTOMER_DEVICE_RULES_MAIN
@app.post("/admin/access-rules")
def admin_access_rules(
    customer_id: int = Form(...),
    instrument_type: str = Form(...),
    serial_start: str = Form(...),
    serial_end: str = Form(...),
    device_key_prefix: str = Form(""),
    notes: str = Form(""),
    user: dict[str, Any] = Depends(admin_user),
):
    def serial_to_int(v: str) -> int:
        digits = "".join(ch for ch in str(v) if ch.isdigit())
        if not digits:
            raise HTTPException(status_code=400, detail="Invalid serial range")
        return int(digits)
    app_db.upsert_customer_device_rule(
        settings.app_db,
        customer_id=customer_id,
        instrument_type=instrument_type.strip().upper(),
        serial_start=serial_to_int(serial_start),
        serial_end=serial_to_int(serial_end),
        device_key_prefix=device_key_prefix.strip() or f"{instrument_type.strip().upper()}_",
        notes=notes.strip(),
    )
    app_db.apply_customer_device_rules_to_existing(settings.app_db)
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/access-rules/delete")
def admin_delete_access_rule(
    rule_id: int = Form(...),
    user: dict[str, Any] = Depends(admin_user),
):
    app_db.delete_customer_device_rule(settings.app_db, rule_id)
    return RedirectResponse(url="/admin", status_code=303)


@app.get("/api/devices")
def api_devices(user: dict[str, Any] = Depends(current_user)):
    devices = app_db.list_devices(settings.app_db, user_id=int(user["id"]), admin=is_admin(user))
    payload = []
    for d in devices:
        components = []
        summary = {"total_packets": 0, "last_start": None}
        try:
            safe_path = safe_receiver_db_path(settings.receiver_db_dir, d["db_path"])
            components = list_components(safe_path, d["device_key"])
            summary = device_summary(safe_path, d["device_key"])
        except Exception as exc:
            log.warning("failed to list components device id=%s: %s", d["id"], exc)
        payload.append({
            "id": d["id"],
            "label": d["label"],
            "device_key": d["device_key"],
            "instrument_type": d["instrument_type"],
            "instrument_serial": d["instrument_serial"],
            "client_ip": d["client_ip"],
            "server_port": d["server_port"],
            "components": components,
            "summary": summary,
        })
    return {"devices": payload, "generated_at": time.time()}


@app.get("/api/components")
def api_components(device_id: int = Query(...), user: dict[str, Any] = Depends(current_user)):
    d = app_db.get_device_for_user(settings.app_db, device_id, int(user["id"]), admin=is_admin(user))
    if not d:
        raise HTTPException(status_code=404, detail="Device not found")
    safe_path = safe_receiver_db_path(settings.receiver_db_dir, d["db_path"])
    return {"device_id": device_id, "components": list_components(safe_path, d["device_key"])}


@app.get("/api/waveform")
def api_waveform(
    device_id: int = Query(...),
    component: str | None = Query(None),
    start: str | None = Query(None),
    end: str | None = Query(None),
    seconds: int = Query(settings.latest_default_seconds, ge=1, le=86400),
    max_points: int = Query(settings.max_plot_points, ge=200, le=50000),
    user: dict[str, Any] = Depends(current_user),
):
    d = app_db.get_device_for_user(settings.app_db, device_id, int(user["id"]), admin=is_admin(user))
    if not d:
        raise HTTPException(status_code=404, detail="Device not found")
    now = time.time()
    end_unix = parse_datetime_or_unix(end, default=now)
    start_unix = parse_datetime_or_unix(start, default=end_unix - seconds)
    safe_path = safe_receiver_db_path(settings.receiver_db_dir, d["db_path"])
    try:
        data = read_waveform(
            safe_path,
            device_key=d["device_key"],
            component=component,
            start_unix=start_unix,
            end_unix=end_unix,
            max_points=max_points,
            max_records=settings.max_query_records,
        )
    except Exception as exc:
        log.exception("waveform query failed")
        raise HTTPException(status_code=500, detail=str(exc))
    preview = receiver_preview_records(d, component, seconds, max_points)
    merge_preview_waveforms(data, preview, start_unix, end_unix)
    data.update({
        "device": {
            "id": d["id"],
            "label": d["label"],
            "device_key": d["device_key"],
            "instrument_type": d["instrument_type"],
            "instrument_serial": d["instrument_serial"],
        },
        "component": component,
        "start_unix": start_unix,
        "end_unix": end_unix,
    })
    return data


@app.get("/api/health")
def api_health():
    return {"ok": True, "time": time.time(), "brand": settings.brand}



# SessionMiddleware must be added after custom HTTP middlewares.
# Starlette executes the last-added middleware first, so this keeps
# request.session available inside permission middleware.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    max_age=settings.session_max_age_seconds,
    same_site="lax",
    https_only=False,
)

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, workers=settings.workers)

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


# STAGE2_ALERT_BACKUP_ROUTES
from . import stage2 as _stage2

@app.on_event("startup")
def stage2_startup() -> None:
    _stage2.init_stage2(settings.app_db)

@app.get("/alerts", response_class=HTMLResponse)
def alerts_page(request: Request, user: dict[str, Any] = Depends(current_user)):
    devices = app_db.list_devices(settings.app_db, user_id=int(user["id"]), admin=is_admin(user))
    device_ids = None if is_admin(user) else [int(d["id"]) for d in devices]
    alerts = _stage2.list_alerts(settings.app_db, device_ids=device_ids, limit=300)
    counts = {
        "open": sum(1 for a in alerts if a.get("status") == "open"),
        "resolved": sum(1 for a in alerts if a.get("status") == "resolved"),
        "critical": sum(1 for a in alerts if a.get("status") == "open" and a.get("severity") == "critical"),
        "warning": sum(1 for a in alerts if a.get("status") == "open" and a.get("severity") == "warning"),
    }
    return templates.TemplateResponse(request, "alerts.html", template_context(request, alerts=alerts, counts=counts))

@app.post("/alerts/check-now")
def alerts_check_now(user: dict[str, Any] = Depends(admin_user)):
    devices = app_db.list_devices(settings.app_db, admin=True)
    _stage2.check_devices_once(settings.app_db, settings.receiver_db_dir, devices, send_email=False)
    return RedirectResponse(url="/alerts", status_code=303)

@app.post("/alerts/{alert_id}/ack")
def alerts_ack(alert_id: int, user: dict[str, Any] = Depends(current_user)):
    alert = _stage2.get_alert_by_id(settings.app_db, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    if not is_admin(user):
        allowed = {int(d["id"]) for d in app_db.list_devices(settings.app_db, user_id=int(user["id"]), admin=False)}
        if alert["device_id"] not in allowed:
            raise HTTPException(status_code=403, detail="No access to this alert")
    _stage2.ack_alert(settings.app_db, alert_id, user.get("username", "user"))
    return RedirectResponse(url="/alerts", status_code=303)

@app.get("/system", response_class=HTMLResponse)
def system_page(request: Request, user: dict[str, Any] = Depends(admin_user)):
    info = _stage2.system_status(settings.app_db, settings.receiver_db_dir)
    return templates.TemplateResponse(request, "system.html", template_context(request, info=info))

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

# STAGE4_SEGMENTED_EXPORT
@app.get("/export/batch-window4")
def export_batch_window4(
    device_ids: str = Query(""),
    all_visible: int = Query(0),
    components: str = Query(""),
    start: str = Query(...),
    end: str = Query(...),
    segment_minutes: int = Query(30, ge=1, le=1440),
    user: dict[str, Any] = Depends(current_user),
):
    from fastapi.responses import Response
    import csv, io, zipfile, math, json
    from .data_reader import export_mseed_bytes_stage3 as _export, export_gaps_stage3 as _gaps, _stage3_iso_utc as _iso

    visible = [dict(d) for d in app_db.list_devices(settings.app_db, user_id=int(user["id"]), admin=is_admin(user))]
    selected_ids = {int(x) for x in device_ids.split(",") if x.strip().isdigit()}
    if all_visible:
        selected = visible
    elif selected_ids:
        selected = [d for d in visible if int(d["id"]) in selected_ids]
    else:
        raise HTTPException(status_code=400, detail="No devices selected")

    start_unix = parse_datetime_or_unix(start)
    end_unix = parse_datetime_or_unix(end)
    if end_unix <= start_unix:
        raise HTTPException(status_code=400, detail="Invalid time range")
    comps = [c.strip() for c in (components or "").split(",") if c.strip()]
    seg_seconds = int(segment_minutes) * 60
    total_segments = int(math.ceil((end_unix - start_unix) / seg_seconds))

    buf = io.BytesIO()
    manifest_io = io.StringIO()
    manifest = csv.writer(manifest_io)
    manifest.writerow(["device_id","device_key","segment_index","segment_start_utc","segment_end_utc","component_filter","record_count","bytes","file"])
    gaps_io = io.StringIO()
    gaps_csv = csv.writer(gaps_io)
    gaps_csv.writerow(["device_key","segment_index","gap_json"])

    files_written = 0
    records_written = 0
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        for d in selected:
            safe_path = safe_receiver_db_path(settings.receiver_db_dir, d["db_path"])
            for idx in range(total_segments):
                seg_start = start_unix + idx * seg_seconds
                seg_end = min(end_unix, seg_start + seg_seconds)
                try:
                    result = _export(safe_path, device_key=d["device_key"], components=comps or None, start_unix=seg_start, end_unix=seg_end, max_records=500000)
                except Exception as exc:
                    manifest.writerow([d.get("id"), d.get("device_key"), idx + 1, _iso(seg_start), _iso(seg_end), ",".join(comps) if comps else "ALL", 0, 0, f"ERROR: {exc}"])
                    continue
                file_rel = ""
                if result.get("record_count", 0) > 0:
                    comp_part = "ALL" if not comps else "-".join(comps)
                    file_rel = f"{d['device_key']}/{d['device_key']}_{comp_part}_{idx+1:04d}_{int(seg_start)}_{int(seg_end)}.mseed"
                    zf.writestr(file_rel, result["blob"])
                    files_written += 1
                    records_written += int(result["record_count"])
                manifest.writerow([d.get("id"), d.get("device_key"), idx + 1, _iso(seg_start), _iso(seg_end), ",".join(comps) if comps else "ALL", result.get("record_count", 0), result.get("raw_bytes", 0), file_rel])
                try:
                    gaps = _gaps(safe_path, device_key=d["device_key"], start_unix=seg_start, end_unix=seg_end, limit=500)
                    for g in gaps:
                        gaps_csv.writerow([d.get("device_key"), idx + 1, json.dumps(g, ensure_ascii=False, default=str)])
                except Exception:
                    pass
        zf.writestr("manifest.csv", manifest_io.getvalue())
        zf.writestr("gaps.csv", gaps_io.getvalue())
        zf.writestr("README.txt", "Segmented batch export. Each miniSEED file contains one time window of one device. Missing data does not block export; see gaps.csv and manifest.csv.\n")

    if files_written == 0:
        raise HTTPException(status_code=404, detail="No records found in the requested range")

    filename = f"mseed_segmented_batch_{int(start_unix)}_{int(end_unix)}_{len(selected)}devices_{segment_minutes}min.zip"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-miniSEED-File-Count": str(files_written),
        "X-miniSEED-Record-Count": str(records_written),
    }
    return Response(content=buf.getvalue(), media_type="application/zip", headers=headers)


# STAGE5_ALERT_FILTER_ROUTES

def _stage5_allowed_device_keys(user: dict[str, Any]) -> set[str]:
    try:
        devices = app_db.list_devices(settings.app_db, user_id=int(user["id"]), admin=is_admin(user))
        return {str(d["device_key"]) for d in devices}
    except Exception:
        return set()


def _stage5_filter_alert_row(row: dict[str, Any], allowed_keys: set[str], admin: bool) -> bool:
    if admin:
        return True
    if not allowed_keys:
        return False
    candidates = []
    for key in ("device_key", "device", "device_label", "label"):
        if row.get(key) is not None:
            candidates.append(str(row.get(key)))
    detail = " ".join(str(row.get(k) or "") for k in ("details", "message", "title", "description"))
    candidates.append(detail)
    text = " ".join(candidates)
    return any(k and k in text for k in allowed_keys)


@app.get("/api/alerts/visible5")
def api_alerts_visible5(user: dict[str, Any] = Depends(current_user)):
    """Return alerts filtered to the current user's authorized devices.

    Admins get all alerts. Ordinary users get only alerts that can be matched
    to one of their authorized device_key values.
    """
    import sqlite3
    allowed = _stage5_allowed_device_keys(user)
    admin = is_admin(user)
    rows = []
    try:
        conn = sqlite3.connect(settings.app_db)
        conn.row_factory = sqlite3.Row
        table_rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('alerts','alert_events')").fetchall()
        if not table_rows:
            return {"alerts": [], "count": 0, "filtered": not admin}
        table = table_rows[0]["name"]
        # Avoid loading huge history for ordinary page views.
        sql = f"SELECT * FROM {table} ORDER BY id DESC LIMIT 500"
        for r in conn.execute(sql):
            d = dict(r)
            if _stage5_filter_alert_row(d, allowed, admin):
                rows.append(d)
        conn.close()
    except Exception as exc:
        log.warning("stage5 alert filtering failed: %s", exc)
        return {"alerts": [], "count": 0, "filtered": not admin, "error": str(exc)}
    return {"alerts": rows, "count": len(rows), "filtered": not admin}


@app.get("/api/alerts/count5")
def api_alerts_count5(user: dict[str, Any] = Depends(current_user)):
    data = api_alerts_visible5(user)
    return {"count": data.get("count", 0), "filtered": data.get("filtered", True)}
