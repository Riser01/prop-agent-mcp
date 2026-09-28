"""
Pytest configuration and test isolation fixture.
Guarantees clean database state for every test case.
"""
import pytest
import json
from src.database import init_db, get_db_connection

@pytest.fixture(autouse=True)
async def reset_database_state():
    """Resets database tables to clean default seed before each test."""
    await init_db()
    conn = await get_db_connection()
    try:
        await conn.execute("DELETE FROM gate_passes;")
        await conn.execute("DELETE FROM lift_reservations;")
        await conn.execute("DELETE FROM shift_requests;")

        # Reset default bylaws
        default_days = json.dumps(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"])
        await conn.execute(
            """
            UPDATE society_bylaws SET
                allowed_days = ?,
                start_time = '09:00',
                end_time = '18:00',
                slot_duration_hours = 4,
                max_concurrent_moves = 1,
                advance_notice_hours = 24,
                move_in_fee = 2000.0,
                move_out_fee = 1000.0,
                lift_deposit = 5000.0,
                require_owner_noc = 1
            WHERE id = 1
            """,
            (default_days,)
        )

        # Reset flat occupancy & dues
        await conn.execute("UPDATE flats SET current_tenant_id = NULL, status = 'VACANT', maintenance_dues = 0.0 WHERE id = 'T1-101'")
        await conn.execute("UPDATE flats SET current_tenant_id = 'res-tenant-102', status = 'OCCUPIED_TENANT', maintenance_dues = 0.0 WHERE id = 'T1-102'")
        await conn.execute("UPDATE flats SET current_tenant_id = NULL, status = 'OCCUPIED_OWNER', maintenance_dues = 1500.0 WHERE id = 'T2-201'")
        await conn.commit()
    finally:
        await conn.close()
