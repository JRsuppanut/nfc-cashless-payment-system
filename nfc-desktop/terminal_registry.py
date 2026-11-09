"""Shared terminal registration and local workstation settings."""

import json
import os
import re
from contextlib import closing
from pathlib import Path
from tempfile import NamedTemporaryFile

import database


CONFIG_DIR = Path(os.getenv("LOCALAPPDATA") or Path.home()) / "FoodCourt"
ROLE_SETTINGS = {
    "cashier": ("CASHIER_ID", "CASHIER-01"),
    "stall": ("STALL_ID", "STALL-01"),
}


def profile(role):
    """Read the workstation binding saved by the Admin application."""
    try:
        return json.loads((CONFIG_DIR / f"{role}.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def terminal_id(role):
    variable, default = ROLE_SETTINGS[role]
    return os.getenv(variable) or profile(role).get("id") or default


def reader_port(role, default):
    return os.getenv("NFC_PORT") or profile(role).get("port") or default


def require_cashier(cursor, station_id):
    """Keep pre-Admin installations usable until the registry is initialized."""
    cursor.execute("SELECT to_regclass('cashier_terminals')")
    if cursor.fetchone()[0] is None:
        return
    cursor.execute("SELECT 1 FROM cashier_terminals WHERE terminal_id=%s AND is_active", (station_id,))
    if not cursor.fetchone():
        raise ValueError(f"จุด {station_id} ยังไม่ได้ลงทะเบียนหรือถูกปิดใช้งาน")


def initialize():
    database.initialize_database()
    with closing(database.get_connection()) as connection, connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cashier_terminals (
                    terminal_id TEXT PRIMARY KEY, terminal_name TEXT NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE
                )
            """)
            cursor.execute("""
                INSERT INTO cashier_terminals(terminal_id, terminal_name)
                VALUES ('CASHIER-01', 'Cashier 01') ON CONFLICT DO NOTHING
            """)


def list_terminals():
    with closing(database.get_connection()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT 'cashier', terminal_id, terminal_name, is_active FROM cashier_terminals
                UNION ALL
                SELECT 'stall', stall_id, stall_name, is_active=1 FROM stalls
                ORDER BY 1, 2
            """)
            return cursor.fetchall()


def save_terminal(role, station_id, name, active, *, create):
    """Create or edit an entry without changing its ID or transaction history."""
    prefix = "CASHIER" if role == "cashier" else "STALL"
    if not re.fullmatch(prefix + r"-[A-Z0-9-]{1,24}", station_id):
        raise ValueError(f"ใช้รหัสรูปแบบ {prefix}-01")
    if not name or len(name) > 100:
        raise ValueError("กรอกชื่อความยาว 1–100 ตัวอักษร")

    with closing(database.get_connection()) as connection, connection:
        with connection.cursor() as cursor:
            if role == "cashier":
                if create:
                    cursor.execute("""
                        INSERT INTO cashier_terminals(terminal_id, terminal_name, is_active)
                        VALUES (%s,%s,%s)
                    """, (station_id, name, active))
                else:
                    cursor.execute("""
                        UPDATE cashier_terminals SET terminal_name=%s,is_active=%s WHERE terminal_id=%s
                    """, (name, active, station_id))
            elif create:
                cursor.execute("""
                    INSERT INTO stalls(stall_id,stall_name,is_active,created_at,updated_at)
                    VALUES (%s,%s,%s,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
                """, (station_id, name, int(active)))
            else:
                cursor.execute("""
                    UPDATE stalls SET stall_name=%s,is_active=%s,updated_at=CURRENT_TIMESTAMP WHERE stall_id=%s
                """, (name, int(active), station_id))
            if cursor.rowcount != 1:
                raise ValueError("ไม่พบจุดหรือร้านที่เลือก")


def bind(role, station_id, port):
    """Save one local profile per application so it can start without PowerShell."""
    if not re.fullmatch(r"COM[1-9][0-9]*", port):
        raise ValueError("กรอกพอร์ตเครื่องอ่าน เช่น COM4")
    if not any(row[0] == role and row[1] == station_id and row[3] for row in list_terminals()):
        raise ValueError("เลือกจุดหรือร้านที่เปิดใช้งานก่อน")

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # Replace the old profile only after the complete JSON has been written.
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=CONFIG_DIR, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump({"id": station_id, "port": port}, stream)
    try:
        temporary.replace(CONFIG_DIR / f"{role}.json")
    finally:
        temporary.unlink(missing_ok=True)
