"""
Tests for Model Context Protocol (MCP) Tool Contract and Dispatch RBAC.
"""
import pytest
from src.database import init_db
from src.mcp.tools import (
    MCP_TOOL_DEFINITIONS,
    ROLE_TOOL_ALLOWLIST,
    execute_mcp_tool
)

def test_mcp_tool_schema_completeness():
    assert len(MCP_TOOL_DEFINITIONS) >= 8
    expected_tools = {
        "eval_shift_bylaws",
        "reserve_service_lift",
        "verify_dues_and_fees",
        "submit_owner_noc",
        "generate_gate_pass",
        "validate_gate_pass_at_security",
        "sync_resident_directory",
        "update_society_bylaws"
    }
    registered_tools = {t["name"] for t in MCP_TOOL_DEFINITIONS}
    assert expected_tools.issubset(registered_tools)

    for tool in MCP_TOOL_DEFINITIONS:
        assert "name" in tool
        assert "description" in tool
        assert "parameters" in tool
        assert tool["parameters"]["type"] == "object"
        assert "properties" in tool["parameters"]

@pytest.mark.asyncio
async def test_rbac_dispatch_boundaries():
    await init_db()

    # Tenant calling unauthorized admin tool -> Must be blocked
    res_tenant = await execute_mcp_tool(
        tool_name="update_society_bylaws",
        arguments={"config_payload": {}},
        agent_role="TENANT"
    )
    assert res_tenant["success"] is False
    assert "RBAC Denied" in res_tenant["error"]

    # Owner calling unauthorized admin tool -> Must be blocked
    res_owner = await execute_mcp_tool(
        tool_name="generate_gate_pass",
        arguments={
            "request_id": "REQ-123",
            "mover_details": "Test",
            "vehicle_no": "KA-01",
            "driver_phone": "123"
        },
        agent_role="OWNER"
    )
    assert res_owner["success"] is False
    assert "RBAC Denied" in res_owner["error"]

    # Admin role is authorized
    res_admin = await execute_mcp_tool(
        tool_name="sync_resident_directory",
        arguments={"flat_id": "T1-101", "action": "REFRESH"},
        agent_role="ADMIN"
    )
    assert res_admin["success"] is True
