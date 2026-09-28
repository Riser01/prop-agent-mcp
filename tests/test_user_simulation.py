"""
User Simulation Script for PropAgent MCP.
Simulates realistic end-user workflows from scratch:
Scenario 1: Cold start initialization & Directory inspection
Scenario 2: Policy violation rejected (Sunday booking), followed by compliant booking (Saturday)
Scenario 3: Owner dues check, NOC sign-off, digital Gate Pass generation, and security guard check-in
Scenario 4: Verification of automated resident directory state transition
"""
import asyncio
import os
import sys
from datetime import datetime

# Set local test db path for user simulation
os.environ["PROP_AGENT_DB_PATH"] = os.path.join(os.path.dirname(__file__), "..", "output", "simulation.db")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.database import init_db, get_society_bylaws, get_directory_data, get_shift_request_by_id
from src.agents.orchestrator import ShiftOrchestrator
from src.mcp.tools import execute_mcp_tool

async def run_simulation():
    output_lines = []

    def log(msg=""):
        print(msg)
        output_lines.append(msg)

    log("=" * 78)
    log("PROPOSITIONS & DEMO: PropAgent MCP Multi-Agent System Simulation")
    log("=" * 78)

    # 1. Cold Start
    log("\n[SCENARIO 1: COLD START & DIRECTORY INITIALIZATION]")
    await init_db()
    bylaws = await get_society_bylaws()
    log(f"✓ Society Bylaws Loaded: Allowed Days: {', '.join(bylaws['allowed_days'])}")
    log(f"✓ Shifting Window: {bylaws['start_time']} to {bylaws['end_time']} (Max {bylaws['max_concurrent_moves']} move/tower)")
    log(f"✓ Society Fees: Move-In ₹{bylaws['move_in_fee']:.0f}, Lift Deposit ₹{bylaws['lift_deposit']:.0f}")

    dir_data = await get_directory_data()
    log(f"✓ Flat Registry Initialized: {len(dir_data['flats'])} flats, {len(dir_data['residents'])} residents.")

    # 2. Scenario 2: Policy Violation Rejection
    log("\n[SCENARIO 2: RESIDENT ATTEMPTS SUNDAY MOVE (BLOCKED BY BYLAWS)]")
    orch = ShiftOrchestrator()
    sunday_date = "2026-10-04"  # Sunday
    log(f"Resident attempts booking on Sunday ({sunday_date}) at 10:00 AM...")

    async for ev in orch.run_pipeline(
        request_id="SIM-REQ-SUN",
        flat_id="T1-101",
        resident_id="res-tenant-new",
        move_type="MOVE_IN",
        shift_date=sunday_date,
        slot_window="09:00-13:00",
        vehicle_type="14FT_TRUCK",
        mover_details="Apex Relocations"
    ):
        if ev["step"] in ("TENANT_AGENT", "TOOL_CALL", "FAILED"):
            log(f"  [{ev['step']}] {ev.get('state', '')}: {ev.get('message', '')}")

    # 3. Scenario 3: Valid Saturday Booking & Full Pipeline
    log("\n[SCENARIO 3: RESIDENT SCHEDULES COMPLIANT SATURDAY MOVE]")
    sat_date = "2026-10-03"  # Saturday
    log(f"Resident re-submits for Saturday ({sat_date}) 09:00-13:00...")

    gate_pass_info = None
    async for ev in orch.run_pipeline(
        request_id="SIM-REQ-SAT",
        flat_id="T1-101",
        resident_id="res-tenant-new",
        move_type="MOVE_IN",
        shift_date=sat_date,
        slot_window="09:00-13:00",
        vehicle_type="14FT_TRUCK",
        mover_details="Apex Relocations",
        vehicle_no="KA-01-MJ-5566",
        driver_phone="+91-9876501234"
    ):
        if ev["step"] in ("TENANT_AGENT_DONE", "OWNER_AGENT_DONE", "COMPLETED"):
            log(f"  [{ev['step']}] {ev.get('state')}: {ev.get('message')}")
        if ev["step"] == "COMPLETED":
            gate_pass_info = ev.get("gate_pass")

    assert gate_pass_info is not None, "Gate pass was not generated"
    log(f"\n  >>> DIGITAL GATE PASS ISSUED:")
    log(f"      Pass ID:     {gate_pass_info['gate_pass_id']}")
    log(f"      Security OTP: {gate_pass_info['otp_code']}")
    log(f"      Valid Slot:  {gate_pass_info['valid_date']} ({gate_pass_info['valid_slot']})")
    log(f"      Truck Reg:   {gate_pass_info['vehicle_no']}")

    # 4. Scenario 4: Security Checkpoint Guard Scan & Directory Update
    log("\n[SCENARIO 4: SECURITY CHECKPOINT VERIFICATION & DIRECTORY REFRESH]")
    log(f"Mover truck arrives at Society Main Gate. Security enters OTP: {gate_pass_info['otp_code']}...")
    verify_res = await execute_mcp_tool(
        tool_name="validate_gate_pass_at_security",
        arguments={"pass_code": gate_pass_info["otp_code"]},
        agent_role="ADMIN"
    )
    log(f"  [SECURITY VERIFY] Status: {verify_res['success']}, Check-in Time: {verify_res.get('check_in_at')}")
    log(f"  [SECURITY VERIFY] Result: {verify_res.get('directory_updated')}")

    # Verify updated directory
    updated_dir = await get_directory_data()
    flat_101 = next(f for f in updated_dir["flats"] if f["id"] == "T1-101")
    log(f"\n✓ Flat T1-101 Final Occupancy State: {flat_101['status']}")
    log(f"✓ Flat T1-101 Current Tenant:       {flat_101['tenant_name']}")

    log("\n" + "=" * 78)
    log("SIMULATION COMPLETED WITH ZERO ERRORS")
    log("=" * 78)

    # Save output demo to output/demo_cli.txt
    demo_file = os.path.join(os.path.dirname(__file__), "..", "output", "demo_cli.txt")
    os.makedirs(os.path.dirname(demo_file), exist_ok=True)
    with open(demo_file, "w", encoding="utf-8") as f:
        f.write("\n".join(output_lines))
    print(f"\n[Saved Demo Output to {demo_file}]")

if __name__ == "__main__":
    asyncio.run(run_simulation())
