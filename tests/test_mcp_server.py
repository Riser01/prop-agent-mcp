"""
Unit tests for MCP JSON-RPC Stdio Server message handler.
"""
import json
import pytest
from src.database import init_db
from src.mcp.server import handle_rpc_message

@pytest.mark.asyncio
async def test_mcp_server_initialize():
    await init_db()
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {}
    }
    resp = await handle_rpc_message(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    assert "result" in resp
    assert resp["result"]["serverInfo"]["name"] == "prop-agent-mcp-server"

@pytest.mark.asyncio
async def test_mcp_server_tools_list():
    await init_db()
    req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {}
    }
    resp = await handle_rpc_message(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 2
    tools = resp["result"]["tools"]
    assert len(tools) >= 8
    names = [t["name"] for t in tools]
    assert "eval_shift_bylaws" in names
    assert "generate_gate_pass" in names

@pytest.mark.asyncio
async def test_mcp_server_tools_call_success_and_rbac():
    await init_db()
    # 1. Valid call as TENANT
    req1 = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "eval_shift_bylaws",
            "arguments": {
                "move_type": "MOVE_IN",
                "shift_date": "2026-10-03",
                "slot_window": "09:00-13:00",
                "vehicle_type": "VAN"
            },
            "role": "TENANT"
        }
    }
    resp1 = await handle_rpc_message(req1)
    content1 = json.loads(resp1["result"]["content"][0]["text"])
    assert content1["is_compliant"] is True

    # 2. RBAC Denied: TENANT calling update_society_bylaws
    req2 = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "update_society_bylaws",
            "arguments": {"start_time": "08:00"},
            "role": "TENANT"
        }
    }
    resp2 = await handle_rpc_message(req2)
    content2 = json.loads(resp2["result"]["content"][0]["text"])
    assert content2["success"] is False
    assert "RBAC Denied" in content2["error"]

@pytest.mark.asyncio
async def test_mcp_server_method_not_found():
    req = {
        "jsonrpc": "2.0",
        "id": 99,
        "method": "non_existent_method"
    }
    resp = await handle_rpc_message(req)
    assert resp["error"]["code"] == -32601
    assert "not found" in resp["error"]["message"]
