from __future__ import annotations

import logging
import os
import time
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import app_db
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
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    max_age=settings.session_max_age_seconds,
    same_site="lax",
    https_only=False,
)
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
    return templates.TemplateResponse("login.html", template_context(request, error=None))


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    user = app_db.authenticate_user(settings.app_db, username.strip(), password)
    if not user:
        return templates.TemplateResponse("login.html", template_context(request, error="用户名或密码错误。"), status_code=401)
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
    return templates.TemplateResponse("dashboard.html", template_context(request, cards=cards))


@app.get("/live", response_class=HTMLResponse)
def live_page(request: Request, device_id: int | None = None, user: dict[str, Any] = Depends(current_user)):
    devices = app_db.list_devices(settings.app_db, user_id=int(user["id"]), admin=is_admin(user))
    return templates.TemplateResponse("live.html", template_context(request, devices=[dict(d) for d in devices], selected_device_id=device_id))


@app.get("/history", response_class=HTMLResponse)
def history_page(request: Request, device_id: int | None = None, user: dict[str, Any] = Depends(current_user)):
    devices = app_db.list_devices(settings.app_db, user_id=int(user["id"]), admin=is_admin(user))
    return templates.TemplateResponse("history.html", template_context(request, devices=[dict(d) for d in devices], selected_device_id=device_id))


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, user: dict[str, Any] = Depends(admin_user)):
    users = app_db.list_users(settings.app_db)
    devices = app_db.list_devices(settings.app_db, admin=True)
    assigned = {int(u["id"]): app_db.user_device_ids(settings.app_db, int(u["id"])) for u in users}
    return templates.TemplateResponse(
        "admin.html",
        template_context(request, users=[dict(u) for u in users], devices=[dict(d) for d in devices], assigned=assigned),
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


@app.post("/admin/users")
def admin_create_user(
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


@app.post("/admin/grant")
def admin_grant(user_id: int = Form(...), device_id: int = Form(...), user: dict[str, Any] = Depends(admin_user)):
    app_db.grant_device(settings.app_db, user_id, device_id)
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/revoke")
def admin_revoke(user_id: int = Form(...), device_id: int = Form(...), user: dict[str, Any] = Depends(admin_user)):
    app_db.revoke_device(settings.app_db, user_id, device_id)
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


if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, workers=settings.workers)
