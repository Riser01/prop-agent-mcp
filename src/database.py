"""
Database layer for PropAgent MCP.
Uses aiosqlite with Write-Ahead Logging (WAL) and non-blocking asynchronous execution.
Includes concurrency mutex, atomic lift reservations, and role-aware directory state transitions.
"""
from __future__ import annotations

import asyncio
import json
import os
import aiosqlite
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

# Database path resolution: local to project or override via env
DB_PATH = os.environ.get(
    "PROP_AGENT_DB_PATH", 
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data.db")
)

# Concurrency mutex protecting simultaneous slot hold acquisitions
_lift_lock = asyncio.Lock()

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS residents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('OWNER', 'TENANT', 'ADMIN')),
    flat_id TEXT,
    lease_start TEXT,
    lease_end TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE', 'PENDING', 'ARCHIVED'))
);

CREATE TABLE IF NOT EXISTS flats (
    id TEXT PRIMARY KEY,
    tower TEXT NOT NULL,
    flat_number TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    current_tenant_id TEXT,
    status TEXT NOT NULL DEFAULT 'OCCUPIED_OWNER' CHECK(status IN ('OCCUPIED_OWNER', 'OCCUPIED_TENANT', 'VACANT')),
    maintenance_dues REAL NOT NULL DEFAULT 0.0,
    FOREIGN KEY(owner_id) REFERENCES residents(id),
    FOREIGN KEY(current_tenant_id) REFERENCES residents(id)
);

CREATE TABLE IF NOT EXISTS society_bylaws (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    allowed_days TEXT NOT NULL, -- JSON array of strings
    start_time TEXT NOT NULL,    -- '09:00'
    end_time TEXT NOT NULL,      -- '18:00'
    slot_duration_hours INTEGER NOT NULL DEFAULT 4,
    max_concurrent_moves INTEGER NOT NULL DEFAULT 1,
    advance_notice_hours INTEGER NOT NULL DEFAULT 24,
    move_in_fee REAL NOT NULL DEFAULT 2000.0,
    move_out_fee REAL NOT NULL DEFAULT 1000.0,
    lift_deposit REAL NOT NULL DEFAULT 5000.0,
    require_owner_noc INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS shift_requests (
    id TEXT PRIMARY KEY,
    flat_id TEXT NOT NULL,
    resident_id TEXT NOT NULL,
    move_type TEXT NOT NULL CHECK(move_type IN ('MOVE_IN', 'MOVE_OUT')),
    shift_date TEXT NOT NULL,
    slot_window TEXT NOT NULL,
    vehicle_type TEXT NOT NULL,
    mover_details TEXT NOT NULL,
    status TEXT NOT NULL,
    owner_noc_status TEXT NOT NULL DEFAULT 'PENDING' CHECK(owner_noc_status IN ('PENDING', 'APPROVED', 'REJECTED')),
    dues_cleared INTEGER NOT NULL DEFAULT 0,
    fees_paid INTEGER NOT NULL DEFAULT 0,
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(flat_id) REFERENCES flats(id),
    FOREIGN KEY(resident_id) REFERENCES residents(id)
);

CREATE TABLE IF NOT EXISTS lift_reservations (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    tower TEXT NOT NULL,
    lift_type TEXT NOT NULL DEFAULT 'SERVICE_FREIGHT',
    shift_date TEXT NOT NULL,
    slot_window TEXT NOT NULL,
    hold_expires_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'HELD' CHECK(status IN ('HELD', 'CONFIRMED', 'RELEASED')),
    FOREIGN KEY(request_id) REFERENCES shift_requests(id)
);

CREATE TABLE IF NOT EXISTS gate_passes (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL UNIQUE,
    otp_code TEXT NOT NULL,
    qr_token TEXT NOT NULL,
    valid_date TEXT NOT NULL,
    valid_slot TEXT NOT NULL,
    vehicle_no TEXT NOT NULL,
    driver_phone TEXT NOT NULL,
    check_in_at TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE', 'CHECKED_IN', 'EXPIRED')),
    FOREIGN KEY(request_id) REFERENCES shift_requests(id)
);
"""

async def get_db_connection() -> aiosqlite.Connection:
    """Returns an active SQLite connection configured with WAL, 60s timeout, and Row factory."""
    conn = await aiosqlite.connect(DB_PATH, timeout=60.0)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA busy_timeout = 60000;")
    await conn.execute("PRAGMA foreign_keys = ON;")
    return conn

async def init_db() -> None:
    """Initializes tables and seeds default records if empty."""
    conn = await get_db_connection()
    try:
        await conn.executescript(SCHEMA_SQL)
        await conn.commit()

        # Check if bylaws exist; if not, seed defaults
        async with conn.execute("SELECT COUNT(*) as cnt FROM society_bylaws WHERE id = 1") as cursor:
            row = await cursor.fetchone()
            if row["cnt"] == 0:
                default_days = json.dumps(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"])
                await conn.execute(
                    """
                    INSERT INTO society_bylaws (
                        id, allowed_days, start_time, end_time, slot_duration_hours,
                        max_concurrent_moves, advance_notice_hours, move_in_fee,
                        move_out_fee, lift_deposit, require_owner_noc
                    ) VALUES (1, ?, '09:00', '18:00', 4, 1, 24, 2000.0, 1000.0, 5000.0, 1)
                    """,
                    (default_days,)
                )
                await conn.commit()

        # Check if initial residents/flats exist; if not, seed realistic sample dataset
        async with conn.execute("SELECT COUNT(*) as cnt FROM residents") as cursor:
            row = await cursor.fetchone()
            if row["cnt"] == 0:
                residents_data = [
                    ("res-admin-01", "Society Admin Desk", "admin@example.com", "+91-9876543210", "ADMIN", None, None, None, "ACTIVE"),
                    ("res-owner-101", "Vikram Malhotra", "vikram.m@example.com", "+91-9123456780", "OWNER", "T1-101", None, None, "ACTIVE"),
                    ("res-owner-102", "Ananya Sharma", "ananya.s@example.com", "+91-9123456781", "OWNER", "T1-102", None, None, "ACTIVE"),
                    ("res-owner-201", "Rajesh Nambiar", "rajesh.n@example.com", "+91-9123456782", "OWNER", "T2-201", None, None, "ACTIVE"),
                    ("res-tenant-102", "David Chen", "david.chen@example.com", "+91-9888877771", "TENANT", "T1-102", "2025-01-01", "2026-12-31", "ACTIVE"),
                    ("res-tenant-new", "Priya Nair", "priya.nair@example.com", "+91-9999911112", "TENANT", "T1-101", "2026-10-01", "2027-09-30", "PENDING"),
                ]
                await conn.executemany(
                    """
                    INSERT INTO residents (id, name, email, phone, role, flat_id, lease_start, lease_end, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    residents_data
                )

                flats_data = [
                    ("T1-101", "Tower-1", "101", "res-owner-101", None, "VACANT", 0.0),
                    ("T1-102", "Tower-1", "102", "res-owner-102", "res-tenant-102", "OCCUPIED_TENANT", 0.0),
                    ("T2-201", "Tower-2", "201", "res-owner-201", None, "OCCUPIED_OWNER", 1500.0),
                ]
                await conn.executemany(
                    """
                    INSERT INTO flats (id, tower, flat_number, owner_id, current_tenant_id, status, maintenance_dues)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    flats_data
                )
                await conn.commit()
    finally:
        await conn.close()

# ── Helper Query Functions ──────────────────────────────────────────

async def get_society_bylaws() -> Dict[str, Any]:
    """Retrieves active society bylaws configuration."""
    conn = await get_db_connection()
    try:
        async with conn.execute("SELECT * FROM society_bylaws WHERE id = 1") as cursor:
            row = await cursor.fetchone()
            if not row:
                raise RuntimeError("Bylaws configuration not found")
            data = dict(row)
            data["allowed_days"] = json.loads(data["allowed_days"])
            return data
    finally:
        await conn.close()

async def update_society_bylaws(updates: Dict[str, Any]) -> Dict[str, Any]:
    """Updates society bylaws and returns the updated config."""
    conn = await get_db_connection()
    try:
        allowed_days_json = json.dumps(updates.get("allowed_days", ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]))
        await conn.execute(
            """
            UPDATE society_bylaws
            SET allowed_days = ?,
                start_time = ?,
                end_time = ?,
                slot_duration_hours = ?,
                max_concurrent_moves = ?,
                advance_notice_hours = ?,
                move_in_fee = ?,
                move_out_fee = ?,
                lift_deposit = ?,
                require_owner_noc = ?
            WHERE id = 1
            """,
            (
                allowed_days_json,
                updates.get("start_time", "09:00"),
                updates.get("end_time", "18:00"),
                int(updates.get("slot_duration_hours", 4)),
                int(updates.get("max_concurrent_moves", 1)),
                int(updates.get("advance_notice_hours", 24)),
                float(updates.get("move_in_fee", 2000.0)),
                float(updates.get("move_out_fee", 1000.0)),
                float(updates.get("lift_deposit", 5000.0)),
                1 if updates.get("require_owner_noc", True) else 0,
            )
        )
        await conn.commit()
    finally:
        await conn.close()

    return await get_society_bylaws()

async def get_directory_data() -> Dict[str, Any]:
    """Retrieves full directory of flats and residents for Admin management."""
    conn = await get_db_connection()
    try:
        async with conn.execute(
            """
            SELECT f.*, 
                   o.name as owner_name, o.email as owner_email, o.phone as owner_phone,
                   t.name as tenant_name, t.email as tenant_email, t.phone as tenant_phone,
                   t.status as tenant_status, t.lease_start, t.lease_end
            FROM flats f
            LEFT JOIN residents o ON f.owner_id = o.id
            LEFT JOIN residents t ON f.current_tenant_id = t.id
            ORDER BY f.tower, f.flat_number
            """
        ) as cursor:
            flats = [dict(r) for r in await cursor.fetchall()]

        async with conn.execute("SELECT * FROM residents ORDER BY name") as cursor:
            residents = [dict(r) for r in await cursor.fetchall()]

        return {"flats": flats, "residents": residents}
    finally:
        await conn.close()

async def get_flat_by_id(flat_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves a flat record with its associated owner and tenant details."""
    conn = await get_db_connection()
    try:
        async with conn.execute(
            """
            SELECT f.*, 
                   o.name as owner_name, o.email as owner_email, o.phone as owner_phone,
                   t.name as tenant_name, t.email as tenant_email, t.phone as tenant_phone
            FROM flats f
            LEFT JOIN residents o ON f.owner_id = o.id
            LEFT JOIN residents t ON f.current_tenant_id = t.id
            WHERE f.id = ?
            """,
            (flat_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None
    finally:
        await conn.close()

async def create_shift_request(
    request_id: str,
    flat_id: str,
    resident_id: str,
    move_type: str,
    shift_date: str,
    slot_window: str,
    vehicle_type: str,
    mover_details: str,
    status: str = "REQUEST_SUBMITTED",
    notes: str = ""
) -> Dict[str, Any]:
    """Creates a new move-in/move-out shift request record."""
    conn = await get_db_connection()
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        await conn.execute(
            """
            INSERT OR REPLACE INTO shift_requests (
                id, flat_id, resident_id, move_type, shift_date, slot_window,
                vehicle_type, mover_details, status, owner_noc_status, dues_cleared,
                fees_paid, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 0, 0, ?, ?, ?)
            """,
            (request_id, flat_id, resident_id, move_type, shift_date, slot_window,
             vehicle_type, mover_details, status, notes, now_iso, now_iso)
        )
        await conn.commit()
    finally:
        await conn.close()

    res = await get_shift_request_by_id(request_id)
    return res or {}

async def get_shift_request_by_id(request_id: str) -> Optional[Dict[str, Any]]:
    """Fetches a shift request by ID, joining flat and resident info."""
    conn = await get_db_connection()
    try:
        async with conn.execute(
            """
            SELECT r.*, f.tower, f.flat_number, f.owner_id,
                   res.name as resident_name, res.email as resident_email, res.phone as resident_phone
            FROM shift_requests r
            JOIN flats f ON r.flat_id = f.id
            JOIN residents res ON r.resident_id = res.id
            WHERE r.id = ?
            """,
            (request_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None
    finally:
        await conn.close()

async def list_shift_requests() -> List[Dict[str, Any]]:
    """Returns all shift requests ordered chronologically descending."""
    conn = await get_db_connection()
    try:
        async with conn.execute(
            """
            SELECT r.*, f.tower, f.flat_number,
                   res.name as resident_name, res.role as resident_role,
                   gp.otp_code, gp.status as gate_pass_status
            FROM shift_requests r
            JOIN flats f ON r.flat_id = f.id
            JOIN residents res ON r.resident_id = res.id
            LEFT JOIN gate_passes gp ON r.id = gp.request_id
            ORDER BY r.created_at DESC
            """
        ) as cursor:
            return [dict(r) for r in await cursor.fetchall()]
    finally:
        await conn.close()

async def update_shift_request_status(
    request_id: str,
    status: str,
    owner_noc_status: Optional[str] = None,
    dues_cleared: Optional[int] = None,
    fees_paid: Optional[int] = None,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """Updates status and tracking flags for a shift request."""
    conn = await get_db_connection()
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        updates = ["status = ?", "updated_at = ?"]
        params = [status, now_iso]

        if owner_noc_status is not None:
            updates.append("owner_noc_status = ?")
            params.append(owner_noc_status)
        if dues_cleared is not None:
            updates.append("dues_cleared = ?")
            params.append(dues_cleared)
        if fees_paid is not None:
            updates.append("fees_paid = ?")
            params.append(fees_paid)
        if notes is not None:
            updates.append("notes = ?")
            params.append(notes)

        params.append(request_id)
        sql = f"UPDATE shift_requests SET {', '.join(updates)} WHERE id = ?"
        await conn.execute(sql, params)
        await conn.commit()
    finally:
        await conn.close()

    res = await get_shift_request_by_id(request_id)
    return res or {}

# ── Atomic Lazy-TTL Lift Reservation Functions ───────────────────────

async def check_lift_slot_availability(
    tower: str,
    shift_date: str,
    slot_window: str,
    exclude_request_id: Optional[str] = None
) -> bool:
    """
    Checks if a service lift slot in a tower is free.
    Applies lazy TTL expiration: a HELD reservation whose hold_expires_at <= NOW is considered expired.
    Excludes active hold for exclude_request_id to prevent self-lockout on retry.
    """
    conn = await get_db_connection()
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        sql = """
            SELECT COUNT(*) as cnt FROM lift_reservations
            WHERE tower = ? AND shift_date = ? AND slot_window = ?
              AND (
                status = 'CONFIRMED'
                OR (status = 'HELD' AND hold_expires_at > ?)
              )
        """
        params = [tower, shift_date, slot_window, now_iso]
        if exclude_request_id:
            sql += " AND request_id != ?"
            params.append(exclude_request_id)

        async with conn.execute(sql, params) as cursor:
            row = await cursor.fetchone()
            cnt = row["cnt"]
    finally:
        await conn.close()

    bylaws = await get_society_bylaws()
    max_concurrent = bylaws.get("max_concurrent_moves", 1)
    return cnt < max_concurrent

async def acquire_lift_hold(
    request_id: str,
    tower: str,
    shift_date: str,
    slot_window: str,
    ttl_minutes: int = 15
) -> Optional[Dict[str, Any]]:
    """
    Atomically acquires a 15-minute lazy-TTL hold on the service elevator.
    Guarded by asyncio.Lock to eliminate TOCTOU race conditions under high concurrency.
    """
    async with _lift_lock:
        # Check availability with current request_id excluded from conflicting holds
        is_free = await check_lift_slot_availability(
            tower, shift_date, slot_window, exclude_request_id=request_id
        )
        if not is_free:
            return None

        conn = await get_db_connection()
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(minutes=ttl_minutes)).isoformat()
        res_id = f"LIFT-{tower}-{shift_date.replace('-', '')}-{slot_window[:2]}-{request_id[-4:]}"
        try:
            # Clean any previous hold for this specific request
            await conn.execute("DELETE FROM lift_reservations WHERE request_id = ?", (request_id,))
            await conn.execute(
                """
                INSERT INTO lift_reservations (id, request_id, tower, lift_type, shift_date, slot_window, hold_expires_at, status)
                VALUES (?, ?, ?, 'SERVICE_FREIGHT', ?, ?, ?, 'HELD')
                """,
                (res_id, request_id, tower, shift_date, slot_window, expires_at)
            )
            await conn.commit()

            async with conn.execute("SELECT * FROM lift_reservations WHERE id = ?", (res_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
        finally:
            await conn.close()

async def confirm_lift_booking(request_id: str) -> bool:
    """Confirms a held lift booking upon final approval."""
    async with _lift_lock:
        conn = await get_db_connection()
        try:
            await conn.execute(
                "UPDATE lift_reservations SET status = 'CONFIRMED' WHERE request_id = ? AND status = 'HELD'",
                (request_id,)
            )
            await conn.commit()
            return True
        finally:
            await conn.close()

async def extend_lift_hold(request_id: str, minutes: int = 1440) -> bool:
    """Extends the hold duration for an active lift reservation during human review."""
    async with _lift_lock:
        conn = await get_db_connection()
        now = datetime.now(timezone.utc)
        new_expires = (now + timedelta(minutes=minutes)).isoformat()
        try:
            await conn.execute(
                "UPDATE lift_reservations SET hold_expires_at = ? WHERE request_id = ? AND status = 'HELD'",
                (new_expires, request_id)
            )
            await conn.commit()
            return True
        finally:
            await conn.close()


async def release_lift_hold(request_id: str) -> bool:
    """Releases a held lift booking if a request fails or is rejected."""
    conn = await get_db_connection()
    try:
        await conn.execute(
            "UPDATE lift_reservations SET status = 'RELEASED' WHERE request_id = ? AND status = 'HELD'",
            (request_id,)
        )
        await conn.commit()
        return True
    finally:
        await conn.close()


# ── Gate Pass & Security Verification ───────────────────────────────

async def create_gate_pass(
    request_id: str,
    otp_code: str,
    qr_token: str,
    valid_date: str,
    valid_slot: str,
    vehicle_no: str,
    driver_phone: str
) -> Dict[str, Any]:
    """Creates or updates a Gate Pass record with 6-digit OTP and QR token."""
    conn = await get_db_connection()
    pass_id = f"GP-{request_id[-7:]}"
    try:
        await conn.execute(
            """
            INSERT INTO gate_passes (id, request_id, otp_code, qr_token, valid_date, valid_slot, vehicle_no, driver_phone, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE')
            ON CONFLICT(request_id) DO UPDATE SET
                otp_code = excluded.otp_code,
                qr_token = excluded.qr_token,
                valid_date = excluded.valid_date,
                valid_slot = excluded.valid_slot,
                vehicle_no = excluded.vehicle_no,
                driver_phone = excluded.driver_phone,
                status = 'ACTIVE'
            """,
            (pass_id, request_id, otp_code, qr_token, valid_date, valid_slot, vehicle_no, driver_phone)
        )
        await conn.commit()

        async with conn.execute("SELECT * FROM gate_passes WHERE id = ?", (pass_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else {}
    finally:
        await conn.close()

async def verify_gate_pass_at_security(otp_or_token: str) -> Optional[Dict[str, Any]]:
    """Validates 6-digit OTP or QR token and records security guard check-in."""
    conn = await get_db_connection()
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        async with conn.execute(
            """
            SELECT gp.*, r.flat_id, r.move_type, r.resident_id, res.name as resident_name, res.role as resident_role
            FROM gate_passes gp
            JOIN shift_requests r ON gp.request_id = r.id
            JOIN residents res ON r.resident_id = res.id
            WHERE (gp.otp_code = ? OR gp.qr_token = ?) AND gp.status = 'ACTIVE'
            """,
            (otp_or_token, otp_or_token)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            pass_data = dict(row)

        await conn.execute(
            "UPDATE gate_passes SET status = 'CHECKED_IN', check_in_at = ? WHERE id = ?",
            (now_iso, pass_data["id"])
        )
        await conn.execute(
            "UPDATE shift_requests SET status = 'GATE_CHECK_IN_COMPLETED', updated_at = ? WHERE id = ?",
            (now_iso, pass_data["request_id"])
        )
        await conn.commit()
        pass_data["status"] = "CHECKED_IN"
        pass_data["check_in_at"] = now_iso
        return pass_data
    finally:
        await conn.close()

# ── Resident Directory Sync & Refresh ───────────────────────────────

async def sync_resident_directory(
    flat_id: Optional[str] = None,
    action: str = "REFRESH",
    tenant_id: Optional[str] = None,
    tenant_details: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Executes tenancy state transition or directory refresh.
    - If action == 'REFRESH': returns updated directory snapshot.
    - If action == 'ACTIVATE':
        * If resident role is OWNER: marks flat OCCUPIED_OWNER, current_tenant_id = NULL.
        * If resident role is TENANT: marks flat OCCUPIED_TENANT, sets current_tenant_id.
    - If action == 'ARCHIVE':
        * Marks outgoing tenant ARCHIVED, marks flat VACANT.
    """
    if action == "REFRESH":
        return await get_directory_data()

    if not flat_id:
        raise ValueError("flat_id is required for ACTIVATE or ARCHIVE actions")

    flat = await get_flat_by_id(flat_id)
    if not flat:
        raise ValueError(f"Flat {flat_id} not found")

    conn = await get_db_connection()
    try:
        # Determine resident role
        target_res_id = tenant_id or flat.get("current_tenant_id")
        res_role = "TENANT"
        if target_res_id:
            async with conn.execute("SELECT role FROM residents WHERE id = ?", (target_res_id,)) as cur:
                r_row = await cur.fetchone()
                if r_row:
                    res_role = r_row["role"]

        if action == "ACTIVATE":
            if res_role == "OWNER":
                await conn.execute(
                    "UPDATE flats SET current_tenant_id = NULL, status = 'OCCUPIED_OWNER' WHERE id = ?",
                    (flat_id,)
                )
            else:
                if not tenant_id and tenant_details:
                    tenant_id = f"res-tenant-{int(datetime.now().timestamp())}"
                    await conn.execute(
                        """
                        INSERT INTO residents (id, name, email, phone, role, flat_id, lease_start, lease_end, status)
                        VALUES (?, ?, ?, ?, 'TENANT', ?, ?, ?, 'ACTIVE')
                        """,
                        (tenant_id, tenant_details.get("name", "New Tenant"),
                         tenant_details.get("email", ""), tenant_details.get("phone", ""),
                         flat_id, tenant_details.get("lease_start"), tenant_details.get("lease_end"))
                    )
                else:
                    await conn.execute(
                        "UPDATE residents SET status = 'ACTIVE', flat_id = ? WHERE id = ?",
                        (flat_id, tenant_id)
                    )

                await conn.execute(
                    "UPDATE flats SET current_tenant_id = ?, status = 'OCCUPIED_TENANT' WHERE id = ?",
                    (tenant_id, flat_id)
                )

        elif action == "ARCHIVE":
            if target_res_id:
                await conn.execute(
                    "UPDATE residents SET status = 'ARCHIVED' WHERE id = ?",
                    (target_res_id,)
                )
            await conn.execute(
                "UPDATE flats SET current_tenant_id = NULL, status = 'VACANT' WHERE id = ?",
                (flat_id,)
            )

        await conn.commit()
    finally:
        await conn.close()

    return await get_directory_data()
