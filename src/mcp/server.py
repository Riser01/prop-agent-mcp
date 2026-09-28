"""
Standalone Model Context Protocol (MCP) Server for PropAgent.
Supports JSON-RPC 2.0 over standard I/O (stdio) per the official MCP specification.
Includes role-based authorization in tool call requests.
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Dict

from src.database import init_db
from src.mcp.tools import MCP_TOOL_DEFINITIONS, execute_mcp_tool

async def handle_rpc_message(msg: Dict[str, Any]) -> Dict[str, Any]:
    method = msg.get("method")
    msg_id = msg.get("id")

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "tools": MCP_TOOL_DEFINITIONS
            }
        }
    elif method == "tools/call":
        params = msg.get("params", {})
        name = params.get("name")
        arguments = params.get("arguments", {})
        # Support explicit role context from caller or default to ADMIN if not specified
        role = params.get("role", "ADMIN")
        result = await execute_mcp_tool(name, arguments, agent_role=role)
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, indent=2)
                    }
                ]
            }
        }
    elif method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "prop-agent-mcp-server",
                    "version": "1.0.0"
                }
            }
        }
    else:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {
                "code": -32601,
                "message": f"Method '{method}' not found"
            }
        }

async def main():
    await init_db()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    loop = asyncio.get_running_loop()
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        line = await reader.readline()
        if not line:
            break
        text = line.decode().strip()
        if not text:
            continue
        try:
            req = json.loads(text)
            resp = await handle_rpc_message(req)
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
        except Exception as e:
            sys.stderr.write(f"Error handling MCP RPC: {e}\n")
            sys.stderr.flush()

if __name__ == "__main__":
    asyncio.run(main())
