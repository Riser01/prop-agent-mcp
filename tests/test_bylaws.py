"""
Unit and Contract Tests for Society Bylaws Evaluation.
"""
import pytest
from src.database import init_db, update_society_bylaws
from src.mcp.tools import execute_mcp_tool

@pytest.mark.asyncio
async def test_sunday_shifting_prohibited():
    await init_db()
    res = await execute_mcp_tool(
        "eval_shift_bylaws",
        {
            "move_type": "MOVE_IN",
            "shift_date": "2026-09-27",  # Sunday
            "slot_window": "09:00-13:00",
            "vehicle_type": "14FT_TRUCK"
        },
        agent_role="TENANT"
    )
    assert res["is_compliant"] is False
    assert any("Sunday is prohibited" in v for v in res["violations"])

@pytest.mark.asyncio
async def test_weekday_shifting_allowed():
    await init_db()
    res = await execute_mcp_tool(
        "eval_shift_bylaws",
        {
            "move_type": "MOVE_IN",
            "shift_date": "2026-10-02",  # Friday
            "slot_window": "09:00-13:00",
            "vehicle_type": "14FT_TRUCK"
        },
        agent_role="TENANT"
    )
    assert res["is_compliant"] is True
    assert len(res["violations"]) == 0

@pytest.mark.asyncio
async def test_outside_hours_prohibited():
    await init_db()
    res = await execute_mcp_tool(
        "eval_shift_bylaws",
        {
            "move_type": "MOVE_IN",
            "shift_date": "2026-10-02",
            "slot_window": "19:00-22:00",  # Night
            "vehicle_type": "14FT_TRUCK"
        },
        agent_role="TENANT"
    )
    assert res["is_compliant"] is False
    assert any("outside allowed shifting hours" in v for v in res["violations"])

@pytest.mark.asyncio
async def test_container_truck_prohibited():
    await init_db()
    res = await execute_mcp_tool(
        "eval_shift_bylaws",
        {
            "move_type": "MOVE_IN",
            "shift_date": "2026-10-02",
            "slot_window": "09:00-13:00",
            "vehicle_type": "CONTAINER"  # Oversized
        },
        agent_role="TENANT"
    )
    assert res["is_compliant"] is False
    assert any("Large container trucks" in v for v in res["violations"])

@pytest.mark.asyncio
async def test_admin_config_dynamically_changes_rules():
    await init_db()
    # Admin updates allowed days to include Sunday
    await execute_mcp_tool(
        "update_society_bylaws",
        {
            "config_payload": {
                "allowed_days": ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
            }
        },
        agent_role="ADMIN"
    )

    # Now Sunday should be compliant
    res = await execute_mcp_tool(
        "eval_shift_bylaws",
        {
            "move_type": "MOVE_IN",
            "shift_date": "2026-09-27",  # Sunday
            "slot_window": "09:00-13:00",
            "vehicle_type": "VAN"
        },
        agent_role="TENANT"
    )
    assert res["is_compliant"] is True

    # Revert to standard defaults for other tests
    await execute_mcp_tool(
        "update_society_bylaws",
        {
            "config_payload": {
                "allowed_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
            }
        },
        agent_role="ADMIN"
    )
