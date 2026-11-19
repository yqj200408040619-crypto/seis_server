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
