#!/usr/bin/env bash
set -euo pipefail

BASE="/opt/mseed-web-portal"
APP="$BASE/app"
PY="/opt/miniforge3/envs/mseed-web/bin/python"
TS="$(date +%Y%m%d_%H%M%S)"

if [ ! -d "$APP" ]; then echo "ERROR: $APP not found" >&2; exit 1; fi
if [ ! -x "$PY" ]; then echo "ERROR: $PY not found" >&2; exit 1; fi

sudo cp "$APP/main.py" "$APP/main.py.bak_fix_save_user_$TS"
sudo cp "$APP/app_db.py" "$APP/app_db.py.bak_fix_save_user_$TS"

if ! grep -q "STAGE5_FIX_SAVE_USER" "$APP/app_db.py"; then
sudo tee -a "$APP/app_db.py" >/dev/null <<'PYCODE'

# STAGE5_FIX_SAVE_USER

def stage5_fix_user_schema(db_path: str) -> None:
    import sqlite3
    with sqlite3.connect(db_path) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "is_active" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN is_active INTEGER DEFAULT 1")
        if "customer_id" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN customer_id INTEGER")
        if "email" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
        conn.commit()


def stage5_create_or_update_user_safe(
    db_path: str,
    *,
    username: str,
    password: str | None = None,
    display_name: str | None = None,
    role: str = "user",
    customer_id: int | None = None,
    email: str | None = None,
    is_active: int = 1,
) -> int:
    import sqlite3, time

    stage5_fix_user_schema(db_path)
    username = (username or "").strip()
    if not username:
        raise ValueError("username is required")
    role = "admin" if role == "admin" else "user"
    display_name = (display_name or username).strip() or username
    email = (email or "").strip() or None
    try:
        customer_id = int(customer_id) if customer_id not in (None, "", "None", "null") else None
    except Exception:
        customer_id = None

    now = time.time()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        existing = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}

        def make_hash(pw: str) -> str:
            try:
                return get_password_hash(pw)
            except NameError:
                try:
                    from .security import get_password_hash as _h
                    return _h(pw)
                except Exception:
                    from .security import hash_password as _h
                    return _h(pw)

        if existing:
            sets = []
            args = []
            for col, val in (
                ("display_name", display_name),
                ("role", role),
                ("customer_id", customer_id),
                ("email", email),
                ("is_active", int(is_active)),
                ("updated_at", now),
            ):
                if col in cols:
                    sets.append(f"{col} = ?")
                    args.append(val)
            if password:
                hashed = make_hash(password)
                if "password_hash" in cols:
                    sets.append("password_hash = ?")
                    args.append(hashed)
                elif "hashed_password" in cols:
                    sets.append("hashed_password = ?")
                    args.append(hashed)
            if sets:
                args.append(int(existing["id"]))
                conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", args)
            conn.commit()
            return int(existing["id"])

        if not password:
            raise ValueError("password is required when creating a new user")

        hashed = make_hash(password)
        insert_cols = ["username"]
        vals = [username]
        for col, val in (
            ("password_hash", hashed),
            ("hashed_password", hashed),
            ("display_name", display_name),
            ("role", role),
            ("customer_id", customer_id),
            ("email", email),
            ("is_active", int(is_active)),
            ("created_at", now),
            ("updated_at", now),
        ):
            if col in cols:
                insert_cols.append(col)
                vals.append(val)
        placeholders = ",".join("?" for _ in insert_cols)
        cur = conn.execute(f"INSERT INTO users ({', '.join(insert_cols)}) VALUES ({placeholders})", vals)
        conn.commit()
        return int(cur.lastrowid)
PYCODE
fi

sudo "$PY" - <<'PYCODE'
from pathlib import Path
import re

p = Path("/opt/mseed-web-portal/app/main.py")
s = p.read_text()

# Disable the original /admin/users route if it is still present.
s = re.sub(
    r'@app\.post\("/admin/users"\)\s*\ndef admin_create_user\(',
    '@app.post("/admin/users_old_disabled_stage5")\ndef admin_create_user_old_disabled_stage5(',
    s,
    count=1,
)

if "STAGE5_FIX_SAVE_USER_ROUTE" not in s:
    insert = '''
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
'''
    marker = '@app.post("/admin/grant")'
    if marker in s:
        s = s.replace(marker, insert + "\n\n" + marker, 1)
    else:
        s += "\n" + insert + "\n"

p.write_text(s)
PYCODE

sudo PYTHONPATH="$BASE" "$PY" - <<'PYCODE'
from app.config import load_settings
from app import app_db
s = load_settings()
app_db.stage5_fix_user_schema(s.app_db)
print("user schema checked:", s.app_db)
PYCODE

sudo "$PY" -m py_compile "$APP/main.py" "$APP/app_db.py"

if command -v systemctl >/dev/null 2>&1; then
  sudo systemctl restart mseed-web-portal
  sudo systemctl restart nginx || true
fi

echo "Save-user fix applied."
echo "Open /admin, reload with Ctrl+F5, then try Save user again."
