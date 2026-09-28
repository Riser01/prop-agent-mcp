"""
State Machine (FSM) Integration Tests across Tenant, Owner, and Admin Agents.
"""
import pytest
from src.database import init_db, get_shift_request_by_id
from src.agents.orchestrator import ShiftOrchestrator

@pytest.mark.asyncio
async def test_full_move_in_pipeline_success():
    await init_db()
    orch = ShiftOrchestrator()
    req_id = "REQ-FSM-MOVEIN-01"

    events = []
    async for ev in orch.run_pipeline(
        request_id=req_id,
        flat_id="T1-101",
        resident_id="res-tenant-new",
        move_type="MOVE_IN",
        shift_date="2026-11-20",  # Friday
        slot_window="09:00-13:00",
        vehicle_type="14FT_TRUCK",
        mover_details="Professional Relocations Ltd"
    ):
        events.append(ev)

    last = events[-1]
    assert last["step"] == "COMPLETED"
    assert last["state"] == "GATE_PASS_ISSUED"
    assert "gate_pass" in last
    assert len(last["gate_pass"]["otp_code"]) == 6

    # Verify database state
    req = await get_shift_request_by_id(req_id)
    assert req["status"] == "GATE_PASS_ISSUED"
    assert req["dues_cleared"] == 1
    assert req["fees_paid"] == 1

@pytest.mark.asyncio
async def test_move_out_blocked_by_dues():
    await init_db()
    orch = ShiftOrchestrator()
    req_id = "REQ-FSM-MOVEOUT-DUES"

    # Flat T2-201 has ₹1500 outstanding dues
    events = []
    async for ev in orch.run_pipeline(
        request_id=req_id,
        flat_id="T2-201",
        resident_id="res-owner-201",
        move_type="MOVE_OUT",
        shift_date="2026-11-21",  # Saturday
        slot_window="09:00-13:00",
        vehicle_type="14FT_TRUCK",
        mover_details="Test Mover"
    ):
        events.append(ev)

    last = events[-1]
    assert last["step"] == "FAILED"
    assert last["state"] == "DUES_PENDING"
    assert "1500" in last["message"]
