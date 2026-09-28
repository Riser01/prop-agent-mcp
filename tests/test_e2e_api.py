"""
End-to-End Smoke and API Contract Tests for PropAgent MCP.
Includes positive flows, negative edge cases, and admin approvals.
"""
import pytest
from fastapi.testclient import TestClient
from src.main import app

def test_static_html_served():
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "PropAgent" in resp.text
    assert "Tenant Portal" in resp.text
    assert "Admin Config Page" in resp.text

def test_bylaws_api_lifecycle():
    client = TestClient(app)
    get_res = client.get("/api/bylaws")
    assert get_res.status_code == 200
    cfg = get_res.json()
    assert "allowed_days" in cfg
    assert cfg["start_time"] == "09:00"

    # Update bylaws via API
    update_res = client.post("/api/bylaws", json={
        "allowed_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"],
        "start_time": "08:30",
        "end_time": "18:30",
        "slot_duration_hours": 4,
        "max_concurrent_moves": 2,
        "advance_notice_hours": 12,
        "move_in_fee": 2500.0,
        "move_out_fee": 1200.0,
        "lift_deposit": 6000.0,
        "require_owner_noc": True
    })
    assert update_res.status_code == 200
    updated_cfg = update_res.json()["bylaws"]
    assert updated_cfg["start_time"] == "08:30"
    assert updated_cfg["move_in_fee"] == 2500.0

def test_full_e2e_move_in_and_guard_check_in():
    client = TestClient(app)
    # 1. Submit valid move-in request
    shift_res = client.post("/api/shift-requests", json={
        "flat_id": "T1-101",
        "resident_id": "res-tenant-new",
        "move_type": "MOVE_IN",
        "shift_date": "2026-11-28",  # Saturday
        "slot_window": "09:00-13:00",
        "vehicle_type": "VAN",
        "mover_details": "City Logistics",
        "vehicle_no": "KA-05-MM-9999",
        "driver_phone": "+91-9111122223"
    })
    assert shift_res.status_code == 200
    data = shift_res.json()
    assert data["final_state"] == "GATE_PASS_ISSUED"
    gate_pass = data["gate_pass"]
    otp = gate_pass["otp_code"]

    # 2. Security guard verifies gate pass OTP
    sec_res = client.post("/api/security/verify", json={"pass_code": otp})
    assert sec_res.status_code == 200
    sec_data = sec_res.json()
    assert sec_data["success"] is True
    assert sec_data["move_type"] == "MOVE_IN"

    # 3. Directory reflects activated tenant
    dir_res = client.get("/api/directory")
    assert dir_res.status_code == 200
    flats = dir_res.json()["flats"]
    flat_101 = next(f for f in flats if f["id"] == "T1-101")
    assert flat_101["status"] == "OCCUPIED_TENANT"

def test_negative_api_validations():
    client = TestClient(app)

    # 1. 404 on missing request
    r_404 = client.get("/api/requests/NON_EXISTENT_REQ")
    assert r_404.status_code == 404

    # 2. 422 on invalid move_type enum
    r_invalid_type = client.post("/api/shift-requests", json={
        "flat_id": "T1-101",
        "resident_id": "res-tenant-new",
        "move_type": "INVALID_MOVE_TYPE",
        "shift_date": "2026-10-03",
        "slot_window": "09:00-13:00",
        "vehicle_type": "VAN",
        "mover_details": "Test"
    })
    assert r_invalid_type.status_code == 422

    # 3. 422 on malformed slot window regex
    r_invalid_slot = client.post("/api/shift-requests", json={
        "flat_id": "T1-101",
        "resident_id": "res-tenant-new",
        "move_type": "MOVE_IN",
        "shift_date": "2026-10-03",
        "slot_window": "9am-1pm",
        "vehicle_type": "VAN",
        "mover_details": "Test"
    })
    assert r_invalid_slot.status_code == 422

    # 4. Security verification with invalid OTP
    r_bad_otp = client.post("/api/security/verify", json={"pass_code": "000000"})
    assert r_bad_otp.status_code == 200
    assert r_bad_otp.json()["success"] is False
    assert "Invalid or expired" in r_bad_otp.json()["error"]
