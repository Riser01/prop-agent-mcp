"""
Society Admin / Property Management Agent for PropAgent.
Enforces community rules, validates NOCs, and generates digital Gate Passes.
Integrates with Gemini for official approval reasoning with deterministic fallback.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List
from src.agents.gemini_client import GeminiClient
from src.mcp.tools import execute_mcp_tool, MCP_TOOL_DEFINITIONS

ADMIN_SYSTEM_PROMPT = """
You are the Society Administrator / Property Management Agent.
You represent the Resident Welfare Association (RWA) / Management Committee.
Your responsibilities:
1. Review overall compliance: bylaw adherence, lift slot hold, and owner NOC.
2. Confirm service lift allocation and permanently secure the slot.
3. Issue the official Digital Gate Pass with a 6-digit OTP and QR token via `generate_gate_pass`.
4. Tone: authoritative, welcoming, safety-oriented.
"""

class AdminAgent:
    def __init__(self, gemini_client: GeminiClient):
        self.gemini = gemini_client
        self.role = "ADMIN"
        self.tools = [t for t in MCP_TOOL_DEFINITIONS if t["name"] in ("generate_gate_pass", "update_society_bylaws", "sync_resident_directory")]

    async def approve_and_issue_gate_pass(
        self,
        request_id: str,
        mover_details: str,
        vehicle_no: str,
        driver_phone: str
    ) -> Dict[str, Any]:
        """
        Executes step 3 of the FSM: Final society approval and Gate Pass issuance.
        """
        events: List[Dict[str, Any]] = []

        pass_result = await execute_mcp_tool(
            tool_name="generate_gate_pass",
            arguments={
                "request_id": request_id,
                "mover_details": mover_details,
                "vehicle_no": vehicle_no,
                "driver_phone": driver_phone
            },
            agent_role=self.role
        )
        events.append({
            "agent": "AdminAgent",
            "action": "generate_gate_pass",
            "payload": pass_result
        })

        if not pass_result.get("success"):
            return {
                "success": False,
                "status": "APPROVAL_FAILED",
                "explanation": pass_result.get("error", "Failed to generate gate pass."),
                "events": events
            }

        # Gemini Natural Language Gate Pass Issuance
        gemini_summary = await self.gemini.generate_content(
            system_instruction=ADMIN_SYSTEM_PROMPT,
            prompt=(
                f"Society management approved move request {request_id}. "
                f"Gate Pass #{pass_result['gate_pass_id']} issued with OTP {pass_result['otp_code']}. "
                "Provide an official society welcome in 1 sentence."
            )
        )
        text = gemini_summary.get("text", "")
        if text and not text.startswith("Evaluated with") and not text.startswith("Gemini API key"):
            explanation = text
        else:
            explanation = (
                f"Move-in/out dossier approved by Society Administration! "
                f"Service elevator permanently reserved. Digital Gate Pass #{pass_result['gate_pass_id']} issued "
                f"with security OTP: {pass_result['otp_code']}."
            )

        return {
            "success": True,
            "status": "GATE_PASS_ISSUED",
            "explanation": explanation,
            "gate_pass": pass_result,
            "events": events
        }
