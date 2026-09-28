"""
Tests for Human-in-the-Loop Conversational Chat & Multi-Persona Approval Flow.
Verifies:
1. Conversational Tenant Chat Engine (slot checking, missing parameter inquiry, Sunday curfew alternative).
2. Step-by-step state progression:
   Tenant Submission (mode="step") -> Lift Hold -> Owner NOC -> Admin Sign-off & Gate Pass -> Security OTP Scan.
3. Rejection lifecycle with instant elevator hold release.
4. Notifications API scoping.
"""
import pytest
from fastapi.testclient import TestClient
from src.main import app
from src.database import get_db_connection, init_db

def test_tenant_chat_engine_inquiry_and_alternatives():
    client = TestClient(app)
    sess_id = "test-sess-chat-01"

    # 1. Underspecified message - agent asks follow-up questions
    r1 = client.post("/api/chat/tenant", json={
        "session_id": sess_id,
        "message": "Hi, I want to move in soon"
    })
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["ready_to_submit"] is False
    assert len(d1["missing_fields"]) > 0
    assert "T1-101" in d1["reply"] or "flat" in d1["reply"].lower()

    # 2. Inquire about prohibited Sunday - agent explains curfew and offers alternatives
    r2 = client.post("/api/chat/tenant", json={
        "session_id": sess_id,
        "message": "Can I move in to T1-101 this Sunday at 10 AM?"
    })
    assert r2.status_code == 200
    d2 = r2.json()
    assert "sunday" in d2["reply"].lower()
    assert "saturday" in d2["reply"].lower() or "monday" in d2["reply"].lower()

    # 3. Complete valid specification - agent validates and builds shift dossier
    r3 = client.post("/api/chat/tenant", json={
        "session_id": sess_id,
        "message": "I will shift into Flat T1-101 on 2026-10-10 at 09:00 with a 14ft truck vehicle KA-04-AB-1234"
    })
    assert r3.status_code == 200
    d3 = r3.json()
    assert d3["ready_to_submit"] is True
    assert d3["dossier"] is not None
    assert d3["dossier"]["flat_id"] == "T1-101"
    assert d3["dossier"]["shift_date"] == "2026-10-10"

@pytest.mark.asyncio
async def test_human_in_the_loop_multi_persona_step_flow():
    await init_db()
    client = TestClient(app)

    # Clean initial notifications
    init_notif = client.get("/api/notifications?owner_id=res-owner-101").json()
    init_owner_count = init_notif["owner_pending_noc"]
    init_admin_count = init_notif["admin_pending_clearance"]

    # Step 1: Tenant submits request in "step" mode
    req_res = client.post("/api/shift-requests", json={
        "flat_id": "T1-101",
        "resident_id": "res-tenant-new",
        "move_type": "MOVE_IN",
        "shift_date": "2026-10-17",  # Saturday
        "slot_window": "09:00-13:00",
        "vehicle_type": "14FT_TRUCK",
        "vehicle_no": "KA-01-EE-7788",
        "mover_details": "Safe Cargo Logistics",
        "mode": "step"
    })
    assert req_res.status_code == 200
    req_data = req_res.json()
    assert req_data["final_state"] in ("LIFT_HELD", "PENDING_OWNER_NOC")
    req_id = req_data["request_id"]
    assert req_id is not None

    # Verify elevator hold exists
    conn = await get_db_connection()
    try:
        cur = await conn.execute("SELECT * FROM lift_reservations WHERE request_id = ? AND status = 'HELD'", (req_id,))
        holds = await cur.fetchall()
        assert len(holds) == 1
    finally:
        await conn.close()

    # Step 2: Owner notification count increased
    notif1 = client.get("/api/notifications?owner_id=res-owner-101").json()
    assert notif1["owner_pending_noc"] == init_owner_count + 1

    # Step 3: Owner grants NOC
    noc_res = client.post("/api/owner-noc", json={
        "request_id": req_id,
        "flat_id": "T1-101",
        "move_type": "MOVE_IN",
        "sign_off_status": "APPROVED",
        "remarks": "Lease verified, 0 dues confirmed"
    })
    assert noc_res.status_code == 200
    assert noc_res.json()["status"] == "APPROVED"

    # Step 4: Admin notification count increased
    notif2 = client.get("/api/notifications?owner_id=res-owner-101").json()
    assert notif2["admin_pending_clearance"] == init_admin_count + 1

    # Step 5: Admin issues Gate Pass
    admin_res = client.post(f"/api/requests/{req_id}/approve")
    assert admin_res.status_code == 200
    admin_data = admin_res.json()
    assert admin_data["success"] is True
    otp_code = admin_data["otp_code"]
    assert len(otp_code) == 6

    # Step 6: Security Guard scans OTP at the gate
    sec_res = client.post("/api/security/verify", json={"pass_code": otp_code})
    assert sec_res.status_code == 200
    sec_data = sec_res.json()
    assert sec_data["success"] is True
    assert sec_data["flat_id"] == "T1-101"

    # Verify directory updated
    dir_res = client.get("/api/directory")
    flats = dir_res.json()["flats"]
    t1_101 = next(f for f in flats if f["id"] == "T1-101")
    assert t1_101["status"] == "OCCUPIED_TENANT"

@pytest.mark.asyncio
async def test_request_rejection_releases_elevator_hold():
    await init_db()
    client = TestClient(app)

    # 1. Create a step request
    req_res = client.post("/api/shift-requests", json={
        "flat_id": "T1-101",
        "resident_id": "res-tenant-new",
        "move_type": "MOVE_IN",
        "shift_date": "2026-10-24",  # Saturday
        "slot_window": "09:00-13:00",
        "vehicle_type": "VAN",
        "vehicle_no": "KA-02-ZZ-3344",
        "mover_details": "Local Movers",
        "mode": "step"
    })
    assert req_res.status_code == 200
    req_id = req_res.json()["request_id"]

    # Verify lift is held
    conn = await get_db_connection()
    try:
        cur = await conn.execute("SELECT * FROM lift_reservations WHERE request_id = ? AND status = 'HELD'", (req_id,))
        active_holds = await cur.fetchall()
        assert len(active_holds) == 1
    finally:
        await conn.close()

    # 2. Reject request
    rej_res = client.post(f"/api/requests/{req_id}/reject", json={"reason": "Lease documentation incomplete"})
    assert rej_res.status_code == 200
    assert rej_res.json()["success"] is True

    # 3. Verify lift hold is released (status = 'RELEASED')
    conn2 = await get_db_connection()
    try:
        cur = await conn2.execute("SELECT * FROM lift_reservations WHERE request_id = ? AND status = 'HELD'", (req_id,))
        active_holds_after = await cur.fetchall()
        assert len(active_holds_after) == 0

        cur2 = await conn2.execute("SELECT * FROM lift_reservations WHERE request_id = ? AND status = 'RELEASED'", (req_id,))
        released_holds = await cur2.fetchall()
        assert len(released_holds) == 1
    finally:
        await conn2.close()

    # 4. Verify request status is updated
    req_check = client.get(f"/api/requests/{req_id}")
    assert req_check.status_code == 200
    assert "REJECTED" in req_check.json()["status"]
