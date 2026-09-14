from __future__ import annotations

import os
import sqlite3
import time
from typing import Any

from .security import hash_password, verify_password


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    role TEXT NOT NULL DEFAULT 'user',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    last_login_at REAL
);

CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    db_path TEXT NOT NULL,
    device_key TEXT NOT NULL,
    instrument_type TEXT,
    instrument_serial TEXT,
    client_ip TEXT,
    server_port INTEGER,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(db_path, device_key)
);

CREATE TABLE IF NOT EXISTS user_devices (
    user_id INTEGER NOT NULL,
    device_id INTEGER NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (user_id, device_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_devices_key ON devices(device_key);
CREATE INDEX IF NOT EXISTS idx_devices_serial ON devices(instrument_serial);
CREATE INDEX IF NOT EXISTS idx_user_devices_user ON user_devices(user_id);
"""


def connect(app_db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(app_db_path), exist_ok=True)
    conn = sqlite3.connect(app_db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(app_db_path: str) -> None:
    with connect(app_db_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def get_user_by_username(app_db_path: str, username: str) -> sqlite3.Row | None:
    with connect(app_db_path) as conn:
        return conn.execute(
            "SELECT * FROM users WHERE username = ? AND is_active = 1",
            (username,),
        ).fetchone()


def get_user_by_id(app_db_path: str, user_id: int) -> sqlite3.Row | None:
    with connect(app_db_path) as conn:
        return conn.execute(
            "SELECT * FROM users WHERE id = ? AND is_active = 1",
            (user_id,),
        ).fetchone()


def authenticate_user(app_db_path: str, username: str, password: str) -> sqlite3.Row | None:
    user = get_user_by_username(app_db_path, username)
    if user is None:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    with connect(app_db_path) as conn:
        conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (time.time(), user["id"]))
        conn.commit()
    return user


def create_or_update_user(
    app_db_path: str,
    username: str,
    password: str | None = None,
    display_name: str | None = None,
    role: str = "user",
    is_active: bool = True,
) -> int:
    now = time.time()
    with connect(app_db_path) as conn:
        existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if existing:
            fields: list[str] = ["display_name = ?", "role = ?", "is_active = ?"]
            args: list[Any] = [display_name or username, role, 1 if is_active else 0]
            if password:
                fields.append("password_hash = ?")
                args.append(hash_password(password))
            args.append(existing["id"])
            conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", args)
            conn.commit()
            return int(existing["id"])
        if not password:
            raise ValueError("Password is required for a new user.")
        cur = conn.execute(
            """
            INSERT INTO users (username, password_hash, display_name, role, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (username, hash_password(password), display_name or username, role, 1 if is_active else 0, now),
        )
        conn.commit()
        return int(cur.lastrowid)


def list_users(app_db_path: str) -> list[sqlite3.Row]:
    with connect(app_db_path) as conn:
        return list(conn.execute("SELECT id, username, display_name, role, is_active, created_at, last_login_at FROM users ORDER BY username"))


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
    now = time.time()
    with connect(app_db_path) as conn:
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
            return int(row["id"])
        cur = conn.execute(
            """
            INSERT INTO devices
            (label, db_path, device_key, instrument_type, instrument_serial, client_ip, server_port, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (label, db_path, device_key, instrument_type, instrument_serial, client_ip, server_port, now, now),
        )
        conn.commit()
        return int(cur.lastrowid)


def list_devices(app_db_path: str, user_id: int | None = None, admin: bool = False) -> list[sqlite3.Row]:
    with connect(app_db_path) as conn:
        if admin or user_id is None:
            return list(conn.execute("SELECT * FROM devices WHERE is_active = 1 ORDER BY label"))
        return list(conn.execute(
            """
            SELECT d.* FROM devices d
            JOIN user_devices ud ON ud.device_id = d.id
            WHERE d.is_active = 1 AND ud.user_id = ?
            ORDER BY d.label
            """,
            (user_id,),
        ))


def get_device_for_user(app_db_path: str, device_id: int, user_id: int, admin: bool = False) -> sqlite3.Row | None:
    with connect(app_db_path) as conn:
        if admin:
            return conn.execute("SELECT * FROM devices WHERE id = ? AND is_active = 1", (device_id,)).fetchone()
        return conn.execute(
            """
            SELECT d.* FROM devices d
            JOIN user_devices ud ON ud.device_id = d.id
            WHERE d.id = ? AND ud.user_id = ? AND d.is_active = 1
            """,
            (device_id, user_id),
        ).fetchone()


def grant_device(app_db_path: str, user_id: int, device_id: int) -> None:
    with connect(app_db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO user_devices (user_id, device_id, created_at) VALUES (?, ?, ?)",
            (user_id, device_id, time.time()),
        )
        conn.commit()


def revoke_device(app_db_path: str, user_id: int, device_id: int) -> None:
    with connect(app_db_path) as conn:
        conn.execute("DELETE FROM user_devices WHERE user_id = ? AND device_id = ?", (user_id, device_id))
        conn.commit()


def user_device_ids(app_db_path: str, user_id: int) -> set[int]:
    with connect(app_db_path) as conn:
        return {int(r["device_id"]) for r in conn.execute("SELECT device_id FROM user_devices WHERE user_id = ?", (user_id,))}

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


def deactivate_missing_receiver_devices(
    app_db_path: str,
    *,
    receiver_db_dir: str,
    active_paths: set[str],
) -> int:
    """Hide indexed receiver files that no longer exist on disk.

    Device records are retained for audit and permissions, but inactive records do
    not appear in the portal and therefore cannot cause HDF5 read errors.
    """
    receiver_root = os.path.realpath(receiver_db_dir)
    obn_root = os.path.realpath(os.path.join(receiver_root, os.pardir, "obn_devices"))
    active = {os.path.realpath(path) for path in active_paths}
    changed = 0
    with connect(app_db_path) as conn:
        rows = conn.execute("SELECT id, db_path FROM devices WHERE is_active = 1").fetchall()
        for row in rows:
            path = os.path.realpath(str(row["db_path"] or ""))
            try:
                managed = os.path.commonpath((receiver_root, path)) == receiver_root or os.path.commonpath((obn_root, path)) == obn_root
            except ValueError:
                managed = False
            if managed and path not in active:
                conn.execute("UPDATE devices SET is_active = 0, updated_at = ? WHERE id = ?", (time.time(), row["id"]))
                changed += 1
        conn.commit()
    return changed


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
