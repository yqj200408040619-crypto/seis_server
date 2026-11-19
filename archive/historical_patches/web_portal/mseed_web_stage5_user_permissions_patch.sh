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

sudo mkdir -p "$STATIC_JS" "$TEMPLATES"

for f in "$APP/main.py" "$APP/app_db.py" "$TEMPLATES/base.html"; do
  [ -f "$f" ] && sudo cp "$f" "$f.bak_permissions_stage5_$TS" || true
done

# ---------------------------------------------------------------------------
# 1) Backend hard gate:
#    /admin and /system are accessible only to admin users.
#    This is enforced by middleware, so it protects routes even if a link is
#    manually typed into the browser.
# ---------------------------------------------------------------------------
if ! grep -q "STAGE5_PERMISSION_GATE" "$APP/main.py"; then
sudo tee -a "$APP/main.py" > /dev/null <<'PYCODE'

# STAGE5_PERMISSION_GATE

def _stage5_user_from_session(request: Request) -> dict[str, Any] | None:
    try:
        user_id = request.session.get("user_id")
    except Exception:
        return None
    if not user_id:
        return None
    try:
        user = app_db.get_user_by_id(settings.app_db, int(user_id))
        return dict(user) if user else None
    except Exception:
        return None


@app.middleware("http")
async def stage5_admin_path_gate(request: Request, call_next):
    """Hard security gate for administrator-only sections.

    UI hiding is not enough. This middleware blocks direct access to
    /admin and /system for every non-admin user.
    """
    path = request.url.path.rstrip("/") or "/"
    admin_only_prefixes = ("/admin", "/system", "/api/system")
    if path == "/admin" or path.startswith("/admin/") or path == "/system" or path.startswith("/system/") or path.startswith("/api/system"):
        user = _stage5_user_from_session(request)
        if not user:
            return RedirectResponse(url="/login", status_code=303)
        if user.get("role") != "admin":
            return JSONResponse(status_code=403, content={"detail": "Admin access required"})
    return await call_next(request)


@app.get("/api/me")
def api_me_stage5(request: Request):
    user = _stage5_user_from_session(request)
    if not user:
        return {"authenticated": False, "role": None, "username": None}
    return {
        "authenticated": True,
        "id": user.get("id"),
        "username": user.get("username"),
        "role": user.get("role"),
        "customer_id": user.get("customer_id"),
    }
PYCODE
fi

# ---------------------------------------------------------------------------
# 2) Add permission-safe alert helpers if possible.
#    This creates user-visible filtered alert endpoints. Existing pages can use
#    them immediately; the frontend helper below will prefer these endpoints.
# ---------------------------------------------------------------------------
if ! grep -q "STAGE5_ALERT_FILTER_ROUTES" "$APP/main.py"; then
sudo tee -a "$APP/main.py" > /dev/null <<'PYCODE'

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
PYCODE
fi

# ---------------------------------------------------------------------------
# 3) Mark body with current user role in templates if possible.
# ---------------------------------------------------------------------------
if [ -f "$TEMPLATES/base.html" ]; then
  if ! grep -q "data-user-role" "$TEMPLATES/base.html"; then
    # Replace the first <body ...> tag by adding a data-user-role attribute.
    sudo "$PY" - <<'PYCODE'
from pathlib import Path
import re
p = Path("/opt/mseed-web-portal/app/templates/base.html")
s = p.read_text()
def repl(m):
    tag = m.group(0)
    if "data-user-role" in tag:
        return tag
    return tag[:-1] + ' data-user-role="{{ user.role if user else \'\'}">'
s2 = re.sub(r"<body([^>]*)>", repl, s, count=1)
p.write_text(s2)
print("patched base body role")
PYCODE
  fi
  if ! grep -q "permissions_stage5.js" "$TEMPLATES/base.html"; then
    sudo sed -i 's#</body>#<script src="/static/js/permissions_stage5.js"></script>\n</body>#' "$TEMPLATES/base.html"
  fi
fi

# ---------------------------------------------------------------------------
# 4) Frontend UI enforcement:
#    Hide System/Admin navigation for non-admin users.
#    Does not replace backend security; only cleans up the UI.
# ---------------------------------------------------------------------------
sudo tee "$STATIC_JS/permissions_stage5.js" > /dev/null <<'JSCODE'
(function(){
  function isAdminRole(role){ return String(role||'').toLowerCase() === 'admin'; }
  function hideAdminLinks(role){
    if(isAdminRole(role)) return;
    const adminPathRe = /^\/(admin|system)(\/|$)/i;
    document.querySelectorAll('a,button').forEach(el=>{
      const href = el.getAttribute('href') || '';
      const text = (el.textContent || '').trim().toLowerCase();
      if(adminPathRe.test(href) || text === 'admin' || text === '管理' || text === 'system' || text === '系统'){
        el.style.display = 'none';
        el.setAttribute('aria-hidden','true');
      }
    });
    // Remove nav separators or empty wrappers if the theme has them.
    document.querySelectorAll('nav, .navbar, .topbar').forEach(nav=>{
      nav.querySelectorAll('li').forEach(li=>{
        const visible = Array.from(li.children).some(c=>getComputedStyle(c).display !== 'none');
        if(!visible && /admin|管理|system|系统/i.test(li.textContent||'')) li.style.display='none';
      });
    });
  }
  async function loadRole(){
    const bodyRole = document.body ? document.body.getAttribute('data-user-role') : '';
    if(bodyRole) return bodyRole;
    try{
      const r = await fetch('/api/me', {credentials:'same-origin'});
      if(r.ok){ const j = await r.json(); return j.role || ''; }
    }catch(e){}
    return '';
  }
  document.addEventListener('DOMContentLoaded', async ()=>{
    const role = await loadRole();
    hideAdminLinks(role);
    // Repeat once after dynamic i18n/nav scripts finish.
    setTimeout(()=>hideAdminLinks(role), 300);
    setTimeout(()=>hideAdminLinks(role), 1200);
  });
})();
JSCODE

# ---------------------------------------------------------------------------
# 5) Optional: tighten admin templates by wrapping known links server-side.
#    This is best-effort; if a template has different markup, middleware still
#    enforces the permission.
# ---------------------------------------------------------------------------
if [ -f "$TEMPLATES/base.html" ] && ! grep -q "STAGE5_ADMIN_NAV_GUARD" "$TEMPLATES/base.html"; then
sudo tee -a "$TEMPLATES/base.html" >/dev/null <<'HTMLCOMMENT'
<!-- STAGE5_ADMIN_NAV_GUARD: backend middleware + permissions_stage5.js enforce admin-only /admin and /system -->
HTMLCOMMENT
fi

# ---------------------------------------------------------------------------
# 6) Restart services.
# ---------------------------------------------------------------------------
sudo "$PY" -m py_compile "$APP/main.py"

if command -v systemctl >/dev/null 2>&1; then
  sudo systemctl restart mseed-web-portal || true
  sudo systemctl restart nginx || true
fi

echo "Stage5 permission patch applied."
echo "Check as admin: /admin and /system should be visible."
echo "Check as normal user: /admin and /system links should be hidden; direct access returns 403."
