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

mkdir -p "$APP_DIR/tools"
cp "$APP_DIR/app/app_db.py" "$APP_DIR/app/app_db.py.bak_bulk_access_$TS"
cp "$APP_DIR/app/main.py" "$APP_DIR/app/main.py.bak_bulk_access_$TS"
[ -f "$APP_DIR/app/templates/admin.html" ] && cp "$APP_DIR/app/templates/admin.html" "$APP_DIR/app/templates/admin.html.bak_bulk_access_$TS" || true
[ -f "$APP_DIR/tools/sync_devices.py" ] && cp "$APP_DIR/tools/sync_devices.py" "$APP_DIR/tools/sync_devices.py.bak_bulk_access_$TS" || true

# -----------------------------------------------------------------------------
# 1) Extend app_db.py: customer range rules, same-device metadata inheritance,
#    customer-level visibility, and explicit rule application.
# -----------------------------------------------------------------------------
if ! grep -q "BULK_CUSTOMER_DEVICE_RULES_PATCH" "$APP_DIR/app/app_db.py"; then
cat >> "$APP_DIR/app/app_db.py" <<'PYCODE'

# BULK_CUSTOMER_DEVICE_RULES_PATCH

def _bulk_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    except Exception:
        return set()


def migrate_customer_device_rules(app_db_path: str) -> None:
    """Add customer device range rules and ensure stage-1 columns exist."""
    # Stage-1 customer/device metadata may already exist. If the helper exists, run it.
    try:
        migrate_stage1(app_db_path)  # type: ignore[name-defined]
    except NameError:
        pass
    now = time.time()
    with connect(app_db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS customer_device_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                instrument_type TEXT NOT NULL,
                serial_start INTEGER NOT NULL,
                serial_end INTEGER NOT NULL,
                device_key_prefix TEXT,
                notes TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_customer_device_rules_customer ON customer_device_rules(customer_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_customer_device_rules_type_range ON customer_device_rules(instrument_type, serial_start, serial_end)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_devices_device_key ON devices(device_key)")
        dev_cols = _bulk_columns(conn, "devices")
        # If stage-1 did not run for some reason, add minimum customer_id column.
        if "customer_id" not in dev_cols:
            conn.execute("ALTER TABLE devices ADD COLUMN customer_id INTEGER")
        user_cols = _bulk_columns(conn, "users")
        if "customer_id" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN customer_id INTEGER")
        # Remove placeholder Unassigned rows if they exist; NULL is the canonical unassigned state.
        try:
            rows = conn.execute("SELECT id FROM customers WHERE UPPER(name) = 'UNASSIGNED' OR UPPER(code) = 'UNASSIGNED'").fetchall()
            for r in rows:
                cid = int(r["id"])
                conn.execute("UPDATE users SET customer_id = NULL WHERE customer_id = ?", (cid,))
                conn.execute("UPDATE devices SET customer_id = NULL WHERE customer_id = ?", (cid,))
                conn.execute("DELETE FROM customers WHERE id = ?", (cid,))
        except Exception:
            pass
        conn.commit()


def _serial_to_int(value: str | int | None) -> int | None:
    if value is None:
        return None
    s = str(value).strip()
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except Exception:
        return None


def list_customer_device_rules(app_db_path: str) -> list[sqlite3.Row]:
    migrate_customer_device_rules(app_db_path)
    with connect(app_db_path) as conn:
        return list(conn.execute("""
            SELECT r.*, c.name AS customer_name, c.code AS customer_code
            FROM customer_device_rules r
            JOIN customers c ON c.id = r.customer_id
            WHERE r.is_active = 1
            ORDER BY c.name, r.instrument_type, r.serial_start, r.serial_end
        """))


def upsert_customer_device_rule(
    app_db_path: str,
    *,
    customer_id: int,
    instrument_type: str,
    serial_start: int,
    serial_end: int,
    device_key_prefix: str | None = None,
    notes: str | None = None,
) -> int:
    migrate_customer_device_rules(app_db_path)
    now = time.time()
    instrument_type = (instrument_type or "").strip().upper()
    if not instrument_type:
        raise ValueError("instrument_type is required")
    a = int(serial_start)
    b = int(serial_end)
    if a > b:
        a, b = b, a
    prefix = (device_key_prefix or f"{instrument_type}_").strip()
    with connect(app_db_path) as conn:
        cust = conn.execute("SELECT id FROM customers WHERE id = ? AND is_active = 1", (customer_id,)).fetchone()
        if not cust:
            raise ValueError(f"Customer not found: {customer_id}")
        row = conn.execute(
            """
            SELECT id FROM customer_device_rules
            WHERE customer_id = ? AND instrument_type = ? AND serial_start = ? AND serial_end = ? AND COALESCE(device_key_prefix, '') = COALESCE(?, '')
            """,
            (customer_id, instrument_type, a, b, prefix),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE customer_device_rules SET notes = ?, is_active = 1, updated_at = ? WHERE id = ?",
                ((notes or "").strip(), now, row["id"]),
            )
            conn.commit()
            return int(row["id"])
        cur = conn.execute(
            """
            INSERT INTO customer_device_rules
            (customer_id, instrument_type, serial_start, serial_end, device_key_prefix, notes, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (customer_id, instrument_type, a, b, prefix, (notes or "").strip(), now, now),
        )
        conn.commit()
        return int(cur.lastrowid)


def delete_customer_device_rule(app_db_path: str, rule_id: int) -> None:
    migrate_customer_device_rules(app_db_path)
    with connect(app_db_path) as conn:
        conn.execute("UPDATE customer_device_rules SET is_active = 0, updated_at = ? WHERE id = ?", (time.time(), rule_id))
        conn.commit()


def _matching_customer_rule(conn: sqlite3.Connection, *, instrument_type: str | None, instrument_serial: str | None, device_key: str | None) -> sqlite3.Row | None:
    it = (instrument_type or "").strip().upper()
    serial_i = _serial_to_int(instrument_serial)
    if not it or serial_i is None:
        return None
    candidates = conn.execute(
        """
        SELECT r.*, c.name AS customer_name FROM customer_device_rules r
        JOIN customers c ON c.id = r.customer_id
        WHERE r.is_active = 1
          AND r.instrument_type = ?
          AND ? BETWEEN r.serial_start AND r.serial_end
        ORDER BY r.updated_at DESC, r.id DESC
        """,
        (it, serial_i),
    ).fetchall()
    for r in candidates:
        prefix = (r["device_key_prefix"] or "").strip()
        if not prefix or (device_key or "").startswith(prefix):
            return r
    return None


def auto_apply_device_customer_rules(app_db_path: str, device_id: int) -> None:
    """Assign customer and metadata by same device_key or by range rules.

    Priority:
    1. If another active device with the same device_key already has customer/alias/site metadata, inherit it.
    2. If still unassigned, apply matching customer range rules, e.g. SS 01000-02000.
    """
    migrate_customer_device_rules(app_db_path)
    with connect(app_db_path) as conn:
        d = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
        if not d:
            return
        dev_cols = _bulk_columns(conn, "devices")
        updates: dict[str, Any] = {}
        # Inherit from same device_key, if a previous IP/db produced another device record.
        same = conn.execute(
            """
            SELECT * FROM devices
            WHERE id != ? AND is_active = 1 AND device_key = ?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (device_id, d["device_key"]),
        ).fetchone()
        if same:
            for col in ["customer_id", "alias", "site_name", "location_note", "latitude", "longitude", "install_date"]:
                if col in dev_cols:
                    try:
                        if (d[col] is None or d[col] == "") and same[col] not in (None, ""):
                            updates[col] = same[col]
                    except Exception:
                        pass
        # Apply a customer range rule if still no customer_id.
        current_customer = updates.get("customer_id") if "customer_id" in updates else (d["customer_id"] if "customer_id" in dev_cols else None)
        if current_customer in (None, "", 0):
            rule = _matching_customer_rule(
                conn,
                instrument_type=d["instrument_type"],
                instrument_serial=d["instrument_serial"],
                device_key=d["device_key"],
            )
            if rule:
                updates["customer_id"] = int(rule["customer_id"])
        if not updates:
            return
        fields = []
        args: list[Any] = []
        for k, v in updates.items():
            if k in dev_cols:
                fields.append(f"{k} = ?")
                args.append(v)
        if not fields:
            return
        fields.append("updated_at = ?")
        args.append(time.time())
        args.append(device_id)
        conn.execute(f"UPDATE devices SET {', '.join(fields)} WHERE id = ?", args)
        conn.commit()


def apply_customer_device_rules_to_existing(app_db_path: str) -> int:
    """Apply same-device inheritance and active customer range rules to all known devices."""
    migrate_customer_device_rules(app_db_path)
    changed = 0
    with connect(app_db_path) as conn:
        ids = [int(r["id"]) for r in conn.execute("SELECT id FROM devices WHERE is_active = 1 ORDER BY id")]
    for did in ids:
        before = None
        after = None
        try:
            with connect(app_db_path) as conn:
                before = conn.execute("SELECT customer_id, alias, site_name FROM devices WHERE id = ?", (did,)).fetchone()
            auto_apply_device_customer_rules(app_db_path, did)
            with connect(app_db_path) as conn:
                after = conn.execute("SELECT customer_id, alias, site_name FROM devices WHERE id = ?", (did,)).fetchone()
            if before and after and tuple(before) != tuple(after):
                changed += 1
        except Exception:
            continue
    return changed


def find_customer_id(app_db_path: str, customer: str) -> int | None:
    migrate_customer_device_rules(app_db_path)
    c = (customer or "").strip()
    if not c:
        return None
    with connect(app_db_path) as conn:
        if c.isdigit():
            row = conn.execute("SELECT id FROM customers WHERE id = ? AND is_active = 1", (int(c),)).fetchone()
            if row:
                return int(row["id"])
        row = conn.execute(
            """
            SELECT id FROM customers
            WHERE is_active = 1 AND (name = ? OR code = ?)
            ORDER BY id LIMIT 1
            """,
            (c, c),
        ).fetchone()
        return int(row["id"]) if row else None


# Override upsert_device so sync_devices automatically applies inheritance and range rules.
def upsert_device(
    app_db_path: str,
    *,
    label: str,
    db_path: str,
    device_key: str,
    instrument_type: str | None,
    instrument_serial: str | None,
    client_ip: str | None,
    server_port: int | None,
) -> int:
    migrate_customer_device_rules(app_db_path)
    now = time.time()
    with connect(app_db_path) as conn:
        cols = _bulk_columns(conn, "devices")
        row = conn.execute("SELECT id FROM devices WHERE db_path = ? AND device_key = ?", (db_path, device_key)).fetchone()
        if row:
            conn.execute(
                """
                UPDATE devices
                SET label = ?, instrument_type = ?, instrument_serial = ?, client_ip = ?,
                    server_port = ?, is_active = 1, updated_at = ?
                WHERE id = ?
                """,
                (label, instrument_type, instrument_serial, client_ip, server_port, now, row["id"]),
            )
            conn.commit()
            device_id = int(row["id"])
        else:
            cur = conn.execute(
                """
                INSERT INTO devices
                (label, db_path, device_key, instrument_type, instrument_serial, client_ip, server_port, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (label, db_path, device_key, instrument_type, instrument_serial, client_ip, server_port, now, now),
            )
            conn.commit()
            device_id = int(cur.lastrowid)
    auto_apply_device_customer_rules(app_db_path, device_id)
    return device_id


# Override customer-aware visibility: explicit grants OR same customer_id.
def list_devices(app_db_path: str, user_id: int | None = None, admin: bool = False) -> list[sqlite3.Row]:
    migrate_customer_device_rules(app_db_path)
    with connect(app_db_path) as conn:
        if admin or user_id is None:
            return list(conn.execute("SELECT * FROM devices WHERE is_active = 1 ORDER BY COALESCE(alias, label), label"))
        user = conn.execute("SELECT id, customer_id FROM users WHERE id = ? AND is_active = 1", (user_id,)).fetchone()
        customer_id = user["customer_id"] if user and "customer_id" in user.keys() else None
        if customer_id:
            return list(conn.execute(
                """
                SELECT DISTINCT d.* FROM devices d
                LEFT JOIN user_devices ud ON ud.device_id = d.id AND ud.user_id = ?
                WHERE d.is_active = 1 AND (ud.user_id IS NOT NULL OR d.customer_id = ?)
                ORDER BY COALESCE(d.alias, d.label), d.label
                """,
                (user_id, customer_id),
            ))
        return list(conn.execute(
            """
            SELECT d.* FROM devices d
            JOIN user_devices ud ON ud.device_id = d.id
            WHERE d.is_active = 1 AND ud.user_id = ?
            ORDER BY COALESCE(d.alias, d.label), d.label
            """,
            (user_id,),
        ))


def get_device_for_user(app_db_path: str, device_id: int, user_id: int, admin: bool = False) -> sqlite3.Row | None:
    migrate_customer_device_rules(app_db_path)
    with connect(app_db_path) as conn:
        if admin:
            return conn.execute("SELECT * FROM devices WHERE id = ? AND is_active = 1", (device_id,)).fetchone()
        user = conn.execute("SELECT id, customer_id FROM users WHERE id = ? AND is_active = 1", (user_id,)).fetchone()
        customer_id = user["customer_id"] if user and "customer_id" in user.keys() else None
        if customer_id:
            return conn.execute(
                """
                SELECT DISTINCT d.* FROM devices d
                LEFT JOIN user_devices ud ON ud.device_id = d.id AND ud.user_id = ?
                WHERE d.id = ? AND d.is_active = 1 AND (ud.user_id IS NOT NULL OR d.customer_id = ?)
                """,
                (user_id, device_id, customer_id),
            ).fetchone()
        return conn.execute(
            """
            SELECT d.* FROM devices d
            JOIN user_devices ud ON ud.device_id = d.id
            WHERE d.id = ? AND ud.user_id = ? AND d.is_active = 1
            """,
            (device_id, user_id),
        ).fetchone()

PYCODE
fi

# -----------------------------------------------------------------------------
# 2) Add CLI tool for bulk customer device rules.
# -----------------------------------------------------------------------------
cat > "$APP_DIR/tools/add_customer_device_rule.py" <<'PYCODE'
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, "/opt/mseed-web-portal")

from app import app_db  # noqa: E402
from app.config import load_settings  # noqa: E402


def parse_serial(v: str) -> int:
    digits = "".join(ch for ch in str(v) if ch.isdigit())
    if not digits:
        raise argparse.ArgumentTypeError(f"Invalid serial number: {v}")
    return int(digits)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a customer device auto-access rule, e.g. SS_01000-02000.")
    parser.add_argument("--config", default=os.environ.get("MSEED_WEB_CONFIG", "/etc/mseed-web-portal/portal.ini"))
    parser.add_argument("--customer", required=True, help="Customer id, name, or code.")
    parser.add_argument("--instrument-type", "--type", dest="instrument_type", required=True, help="Instrument type, e.g. SS or QS.")
    parser.add_argument("--from", dest="serial_start", required=True, type=parse_serial, help="Start serial, e.g. 01000.")
    parser.add_argument("--to", dest="serial_end", required=True, type=parse_serial, help="End serial, e.g. 02000.")
    parser.add_argument("--prefix", default="", help="Optional device_key prefix. Defaults to '<TYPE>_'.")
    parser.add_argument("--notes", default="")
    parser.add_argument("--apply-existing", action="store_true", help="Apply rules to existing devices immediately.")
    args = parser.parse_args()

    settings = load_settings(args.config)
    app_db.init_db(settings.app_db)
    app_db.migrate_customer_device_rules(settings.app_db)
    cid = app_db.find_customer_id(settings.app_db, args.customer)
    if cid is None:
        raise SystemExit(f"Customer not found: {args.customer}. Create it in /admin first or use tools/create_customer through the UI.")
    rule_id = app_db.upsert_customer_device_rule(
        settings.app_db,
        customer_id=cid,
        instrument_type=args.instrument_type,
        serial_start=args.serial_start,
        serial_end=args.serial_end,
        device_key_prefix=args.prefix or f"{args.instrument_type.upper()}_",
        notes=args.notes,
    )
    changed = 0
    if args.apply_existing:
        changed = app_db.apply_customer_device_rules_to_existing(settings.app_db)
    print(f"rule id={rule_id} customer_id={cid} type={args.instrument_type.upper()} range={args.serial_start:05d}-{args.serial_end:05d} changed_existing={changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PYCODE
chmod +x "$APP_DIR/tools/add_customer_device_rule.py"

cat > "$APP_DIR/tools/apply_device_access_rules.py" <<'PYCODE'
#!/usr/bin/env python3
from __future__ import annotations
import os
import sys
sys.path.insert(0, "/opt/mseed-web-portal")
from app import app_db  # noqa: E402
from app.config import load_settings  # noqa: E402

settings = load_settings(os.environ.get("MSEED_WEB_CONFIG", "/etc/mseed-web-portal/portal.ini"))
app_db.init_db(settings.app_db)
changed = app_db.apply_customer_device_rules_to_existing(settings.app_db)
print(f"applied access rules, changed devices={changed}")
PYCODE
chmod +x "$APP_DIR/tools/apply_device_access_rules.py"

# -----------------------------------------------------------------------------
# 3) Patch sync_devices.py to ensure migrated rule table and rule application.
# -----------------------------------------------------------------------------
$PY <<'PY'
from pathlib import Path
p = Path('/opt/mseed-web-portal/tools/sync_devices.py')
s = p.read_text()
if 'migrate_customer_device_rules' not in s:
    s = s.replace('    app_db.init_db(settings.app_db)\n', '    app_db.init_db(settings.app_db)\n    if hasattr(app_db, "migrate_customer_device_rules"):\n        app_db.migrate_customer_device_rules(settings.app_db)\n', 1)
# upsert_device now auto applies, but applying at the end makes the script idempotent and fixes existing devices.
if 'apply_customer_device_rules_to_existing' not in s:
    s = s.replace('    print(f"total: {len(found)}")\n', '    if hasattr(app_db, "apply_customer_device_rules_to_existing"):\n        changed = app_db.apply_customer_device_rules_to_existing(settings.app_db)\n        print(f"access-rule-updated: {changed}")\n    print(f"total: {len(found)}")\n', 1)
p.write_text(s)
PY

# -----------------------------------------------------------------------------
# 4) Patch main.py: pass rules to admin page and add admin POST endpoints.
# -----------------------------------------------------------------------------
$PY <<'PY'
from pathlib import Path
p = Path('/opt/mseed-web-portal/app/main.py')
s = p.read_text()
# Admin page: ensure access_rules variable exists after customers/devices.
if 'access_rules = app_db.list_customer_device_rules(settings.app_db)' not in s:
    if '    customers = app_db.list_customers(settings.app_db)\n' in s:
        s = s.replace('    customers = app_db.list_customers(settings.app_db)\n', '    customers = app_db.list_customers(settings.app_db)\n    access_rules = app_db.list_customer_device_rules(settings.app_db) if hasattr(app_db, "list_customer_device_rules") else []\n', 1)
    elif '    devices = app_db.list_devices(settings.app_db, admin=True)\n' in s:
        s = s.replace('    devices = app_db.list_devices(settings.app_db, admin=True)\n', '    devices = app_db.list_devices(settings.app_db, admin=True)\n    customers = app_db.list_customers(settings.app_db) if hasattr(app_db, "list_customers") else []\n    access_rules = app_db.list_customer_device_rules(settings.app_db) if hasattr(app_db, "list_customer_device_rules") else []\n', 1)
# Add access_rules to template context.
if 'access_rules=[dict(r) for r in access_rules]' not in s:
    s = s.replace('customers=[dict(c) for c in customers])', 'customers=[dict(c) for c in customers], access_rules=[dict(r) for r in access_rules])', 1)
    s = s.replace('customers=[dict(c) for c in customers],)', 'customers=[dict(c) for c in customers], access_rules=[dict(r) for r in access_rules],)', 1)

if 'BULK_CUSTOMER_DEVICE_RULES_MAIN' not in s:
    insert = r'''

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
'''
    marker = '@app.get("/api/devices")'
    if marker in s:
        s = s.replace(marker, insert + '\n\n' + marker, 1)
    else:
        s += insert
p.write_text(s)
PY

# -----------------------------------------------------------------------------
# 5) Patch admin.html: add range rule card. This is best-effort and safe.
# -----------------------------------------------------------------------------
$PY <<'PY'
from pathlib import Path
p = Path('/opt/mseed-web-portal/app/templates/admin.html')
s = p.read_text()
if 'BULK_CUSTOMER_DEVICE_RULES_ADMIN_HTML' not in s:
    card = r'''
    <!-- BULK_CUSTOMER_DEVICE_RULES_ADMIN_HTML -->
    <div class="device-card mt-4">
      <h2 class="h6 fw-bold mb-3">批量客户设备规则</h2>
      <p class="text-secondary small mb-3">例如 SS 01000–02000：当范围内的新设备被识别后，会自动归入所选客户；该客户下的用户会自动看到这些设备。</p>
      <form method="post" action="/admin/access-rules" class="row g-2 align-items-end mb-3">
        <div class="col-12">
          <label class="form-label">客户</label>
          <select class="form-select form-select-sm" name="customer_id" required>
            {% for c in customers|default([]) %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}
          </select>
        </div>
        <div class="col-4">
          <label class="form-label">类型</label>
          <input class="form-control form-control-sm" name="instrument_type" value="SS" placeholder="SS / QS" required>
        </div>
        <div class="col-4">
          <label class="form-label">起始序号</label>
          <input class="form-control form-control-sm" name="serial_start" placeholder="01000" required>
        </div>
        <div class="col-4">
          <label class="form-label">结束序号</label>
          <input class="form-control form-control-sm" name="serial_end" placeholder="02000" required>
        </div>
        <div class="col-6">
          <label class="form-label">Key 前缀</label>
          <input class="form-control form-control-sm" name="device_key_prefix" placeholder="SS_">
        </div>
        <div class="col-6">
          <label class="form-label">备注</label>
          <input class="form-control form-control-sm" name="notes" placeholder="SS_01000-02000 for customer A">
        </div>
        <div class="col-12"><button class="btn btn-sm btn-primary w-100">保存并应用规则</button></div>
      </form>

      <div class="table-responsive">
        <table class="table table-dark table-sm align-middle">
          <thead><tr><th>客户</th><th>范围</th><th>前缀</th><th>备注</th><th>操作</th></tr></thead>
          <tbody>
          {% for r in access_rules|default([]) %}
          <tr>
            <td>{{ r.customer_name }}</td>
            <td>{{ r.instrument_type }}_{{ "%05d"|format(r.serial_start) }}–{{ "%05d"|format(r.serial_end) }}</td>
            <td>{{ r.device_key_prefix or '' }}</td>
            <td class="text-secondary small">{{ r.notes or '' }}</td>
            <td>
              <form method="post" action="/admin/access-rules/delete" onsubmit="return confirm('Delete this rule?')">
                <input type="hidden" name="rule_id" value="{{ r.id }}">
                <button class="btn btn-sm btn-outline-danger">删除</button>
              </form>
            </td>
          </tr>
          {% endfor %}
          {% if not access_rules %}<tr><td colspan="5" class="text-secondary">暂无批量规则。</td></tr>{% endif %}
          </tbody>
        </table>
      </div>
    </div>
'''
    marker = '    <div class="device-card">\n      <h2 class="h6 fw-bold mb-3">创建 / 更新客户分组</h2>'
    # Add after customer card if possible.
    end_customer = '        <button class="btn btn-primary w-100">保存客户</button>\n      </form>\n    </div>\n  </div>\n\n  <div class="col-12 col-xl-8">'
    if end_customer in s:
        s = s.replace(end_customer, '        <button class="btn btn-primary w-100">保存客户</button>\n      </form>\n    </div>\n' + card + '\n  </div>\n\n  <div class="col-12 col-xl-8">', 1)
    else:
        # Fallback: insert before endblock.
        s = s.replace('{% endblock %}', card + '\n{% endblock %}', 1)
p.write_text(s)
PY

# -----------------------------------------------------------------------------
# 6) Install automatic sync timer with resource limits.
# -----------------------------------------------------------------------------
cat > /etc/systemd/system/mseed-device-sync.service <<'EOF'
[Unit]
Description=Sync miniSEED device database index and apply customer device rules

[Service]
Type=oneshot
User=root
Group=root
WorkingDirectory=/opt/mseed-web-portal
Environment=PYTHONPATH=/opt/mseed-web-portal
Environment=MSEED_WEB_CONFIG=/etc/mseed-web-portal/portal.ini
ExecStart=/opt/miniforge3/envs/mseed-web/bin/python /opt/mseed-web-portal/tools/sync_devices.py
Nice=10
IOSchedulingClass=idle
CPUQuota=20%
MemoryMax=200M
EOF

cat > /etc/systemd/system/mseed-device-sync.timer <<'EOF'
[Unit]
Description=Run miniSEED device sync periodically

[Timer]
OnBootSec=30s
OnUnitActiveSec=60s
AccuracySec=10s
Persistent=true
Unit=mseed-device-sync.service

[Install]
WantedBy=timers.target
EOF

# -----------------------------------------------------------------------------
# 7) Compile, migrate, apply existing devices, restart.
# -----------------------------------------------------------------------------
PYTHONPATH="$APP_DIR" "$PY" -m py_compile "$APP_DIR/app/app_db.py" "$APP_DIR/app/main.py" "$APP_DIR/tools/sync_devices.py" "$APP_DIR/tools/add_customer_device_rule.py" "$APP_DIR/tools/apply_device_access_rules.py"
PYTHONPATH="$APP_DIR" MSEED_WEB_CONFIG="/etc/mseed-web-portal/portal.ini" "$PY" - <<'PY'
from app.config import load_settings
from app import app_db
s = load_settings()
app_db.init_db(s.app_db)
app_db.migrate_customer_device_rules(s.app_db)
changed = app_db.apply_customer_device_rules_to_existing(s.app_db)
print('migrated bulk customer access rules:', s.app_db, 'changed_existing=', changed)
PY

systemctl daemon-reload
systemctl enable --now mseed-device-sync.timer
systemctl restart mseed-device-sync.service || true
systemctl restart mseed-web-portal
systemctl restart nginx || true

echo "OK: automatic device sync + bulk customer device rules installed."
echo "Open /admin to create rules, or use tools/add_customer_device_rule.py."
