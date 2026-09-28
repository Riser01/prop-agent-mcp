"""
Unit and Concurrency Tests for Service Lift Locking and Lazy-TTL Expiration.
"""
import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from src.database import (
    init_db,
    create_shift_request,
    acquire_lift_hold,
    check_lift_slot_availability,
    update_society_bylaws,
    get_db_connection
)

@pytest.mark.asyncio
async def test_lift_concurrency_lock():
    await init_db()
    await update_society_bylaws({"max_concurrent_moves": 1})
    tower = "Tower-99"
    date = "2026-11-15"
    slot = "09:00-13:00"

    # Pre-create valid parent shift requests for foreign key integrity
    await create_shift_request("REQ-LOCK-1", "T1-101", "res-tenant-new", "MOVE_IN", date, slot, "VAN", "Mover 1")
    await create_shift_request("REQ-LOCK-2", "T1-102", "res-tenant-102", "MOVE_IN", date, slot, "VAN", "Mover 2")

    # Request 1 acquires hold
    res1 = await acquire_lift_hold("REQ-LOCK-1", tower, date, slot, ttl_minutes=15)
    assert res1 is not None
    assert res1["status"] == "HELD"

    # Request 2 attempting to book identical slot in same tower is blocked
    res2 = await acquire_lift_hold("REQ-LOCK-2", tower, date, slot, ttl_minutes=15)
    assert res2 is None

    # Availability check reports unavailable
    available = await check_lift_slot_availability(tower, date, slot)
    assert available is False

@pytest.mark.asyncio
async def test_parallel_lift_concurrency_race_condition():
    """
    Stress test for TOCTOU race condition:
    Fires 10 simultaneous coroutines trying to acquire the same elevator slot.
    Asserts that under atomic locking, exactly 1 reservation succeeds and 9 fail.
    """
    await init_db()
    await update_society_bylaws({"max_concurrent_moves": 1})
    tower = "Tower-RACE"
    date = "2026-12-01"
    slot = "09:00-13:00"

    # Pre-create 10 requests
    req_ids = [f"REQ-RACE-{i}" for i in range(10)]
    for req_id in req_ids:
        await create_shift_request(req_id, "T1-101", "res-tenant-new", "MOVE_IN", date, slot, "VAN", "Stress Mover")

    # Launch 10 simultaneous tasks
    results = await asyncio.gather(*[
        acquire_lift_hold(req_id, tower, date, slot, ttl_minutes=15)
        for req_id in req_ids
    ])

    successes = [r for r in results if r is not None]
    failures = [r for r in results if r is None]

    assert len(successes) == 1, f"Expected exactly 1 successful hold, got {len(successes)}"
    assert len(failures) == 9, f"Expected exactly 9 rejected holds, got {len(failures)}"

@pytest.mark.asyncio
async def test_lazy_ttl_expiration():
    await init_db()
    tower = "Tower-99"
    date = "2026-11-16"
    slot = "09:00-13:00"

    await create_shift_request("REQ-EXPIRED", "T1-101", "res-tenant-new", "MOVE_IN", date, slot, "VAN", "Mover Expired")
    await create_shift_request("REQ-NEW", "T1-102", "res-tenant-102", "MOVE_IN", date, slot, "VAN", "Mover New")

    # Insert an expired hold (expired 5 minutes ago)
    conn = await get_db_connection()
    past_iso = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    await conn.execute(
        """
        INSERT OR REPLACE INTO lift_reservations (id, request_id, tower, lift_type, shift_date, slot_window, hold_expires_at, status)
        VALUES ('LIFT-EXPIRED', 'REQ-EXPIRED', ?, 'SERVICE_FREIGHT', ?, ?, ?, 'HELD')
        """,
        (tower, date, slot, past_iso)
    )
    await conn.commit()
    await conn.close()

    # Querying availability should ignore the expired hold and report slot available
    available = await check_lift_slot_availability(tower, date, slot)
    assert available is True

    # A new request can successfully acquire the slot
    new_res = await acquire_lift_hold("REQ-NEW", tower, date, slot, ttl_minutes=15)
    assert new_res is not None
    assert new_res["request_id"] == "REQ-NEW"
