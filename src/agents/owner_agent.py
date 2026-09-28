"""
Property Owner Representative Agent for PropAgent.
Verifies flat records, checks outstanding dues, and issues Owner NOC.
Integrates with Gemini for natural language sign-off reasoning with deterministic fallback.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List
from src.agents.gemini_client import GeminiClient
from src.mcp.tools import execute_mcp_tool, MCP_TOOL_DEFINITIONS

OWNER_SYSTEM_PROMPT = """
You are the Owner Representative Agent.
Your responsibility is protecting the landlord's interest and verifying tenancy terms:
1. Verify flat records and assess financial ledger status using `verify_dues_and_fees`.
2. For Move-Out: Ensure zero maintenance and utility arrears. If dues exist, refuse NOC until settled.
3. For Move-In: Verify lease term and issue Owner No-Objection Certificate (NOC) using `submit_owner_noc`.
4. Tone: formal, rigorous, financial-minded.
"""

class OwnerAgent:
    def __init__(self, gemini_client: GeminiClient):
        self.gemini = gemini_client
        self.role = "OWNER"
        self.tools = [t for t in MCP_TOOL_DEFINITIONS if t["name"] in ("verify_dues_and_fees", "submit_owner_noc")]

    async def verify_and_sign_noc(
        self,
        request_id: str,
        flat_id: str,
        move_type: str,
        auto_sign: bool = True
    ) -> Dict[str, Any]:
        """
        Executes step 2 of the FSM: Financial verification and Owner NOC decision.
        """
        events: List[Dict[str, Any]] = []

        # 1. MCP Tool: verify_dues_and_fees
        dues_result = await execute_mcp_tool(
            tool_name="verify_dues_and_fees",
            arguments={
                "flat_id": flat_id,
                "move_type": move_type
            },
            agent_role=self.role
        )
        events.append({
            "agent": "OwnerAgent",
            "action": "verify_dues_and_fees",
            "payload": dues_result
        })

        if not dues_result.get("dues_cleared"):
            dues_amt = dues_result.get("maintenance_dues", 0.0)
            explanation = (
                f"Owner NOC Denied: Outstanding maintenance dues of ₹{dues_amt:.2f} must be settled "
                f"before move-out clearance can be granted."
            )
            # Record NOC rejection
            await execute_mcp_tool(
                tool_name="submit_owner_noc",
                arguments={
                    "request_id": request_id,
                    "flat_id": flat_id,
                    "move_type": move_type,
                    "sign_off_status": "REJECTED",
                    "remarks": f"Pending dues ₹{dues_amt:.2f}"
                },
                agent_role=self.role
            )
            return {
                "success": False,
                "status": "DUES_PENDING",
                "explanation": explanation,
                "dues_result": dues_result,
                "events": events
            }

        # 2. Grant Owner NOC
        noc_result = await execute_mcp_tool(
            tool_name="submit_owner_noc",
            arguments={
                "request_id": request_id,
                "flat_id": flat_id,
                "move_type": move_type,
                "sign_off_status": "APPROVED",
                "remarks": "Tenancy records verified and financial dues cleared."
            },
            agent_role=self.role
        )
        events.append({
            "agent": "OwnerAgent",
            "action": "submit_owner_noc",
            "payload": noc_result
        })

        # Gemini Natural Language Sign-Off
        gemini_summary = await self.gemini.generate_content(
            system_instruction=OWNER_SYSTEM_PROMPT,
            prompt=(
                f"Owner verified {move_type} for Flat {flat_id}. "
                f"All maintenance dues are clear. Summarize owner consent in 1 concise sentence."
            )
        )
        text = gemini_summary.get("text", "")
        if text and not text.startswith("Evaluated with") and not text.startswith("Gemini API key"):
            explanation = text
        else:
            explanation = (
                f"Owner verification complete. Tenancy terms and zero-dues validated. "
                f"Owner NOC granted for {move_type} on Flat {flat_id}."
            )

        return {
            "success": True,
            "status": "OWNER_NOC_APPROVED",
            "explanation": explanation,
            "noc_result": noc_result,
            "events": events
        }
