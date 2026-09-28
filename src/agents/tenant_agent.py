"""
Tenant Representative Agent for PropAgent.
Handles intake, bylaw verification, slot negotiation, and lift reservation.
Integrates with Gemini 2.0 Flash for natural language reasoning with deterministic fallback.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple
from src.agents.gemini_client import GeminiClient
from src.mcp.tools import execute_mcp_tool, MCP_TOOL_DEFINITIONS

TENANT_SYSTEM_PROMPT = """
You are the Tenant Representative Agent in a gated residential community.
Your objective is to help incoming and outgoing tenants schedule move-in or move-out shifting requests smoothly.
You must:
1. Evaluate proposed shift dates, times, and vehicle types against society bylaws using `eval_shift_bylaws`.
2. If the proposed date or time violates society rules (e.g., shifting on Sunday or outside allowed 09:00-18:00 hours), explain the policy violation politely and offer compliant alternatives (such as the preceding Saturday or following Monday).
3. If compliant, reserve the tower freight/service elevator using `reserve_service_lift`.
4. Tone: professional, helpful, accurate, and concise. Never hallucinate approvals.
"""

class TenantAgent:
    def __init__(self, gemini_client: GeminiClient):
        self.gemini = gemini_client
        self.role = "TENANT"
        self.tools = [t for t in MCP_TOOL_DEFINITIONS if t["name"] in ("eval_shift_bylaws", "reserve_service_lift")]

    async def process_shift_request(
        self,
        request_id: str,
        flat_id: str,
        move_type: str,
        shift_date: str,
        slot_window: str,
        vehicle_type: str
    ) -> Dict[str, Any]:
        """
        Executes step 1 of the FSM: Bylaw evaluation and lift hold acquisition.
        """
        events: List[Dict[str, Any]] = []

        # 1. MCP Tool: eval_shift_bylaws
        eval_result = await execute_mcp_tool(
            tool_name="eval_shift_bylaws",
            arguments={
                "move_type": move_type,
                "shift_date": shift_date,
                "slot_window": slot_window,
                "vehicle_type": vehicle_type
            },
            agent_role=self.role
        )
        events.append({
            "agent": "TenantAgent",
            "action": "eval_shift_bylaws",
            "payload": eval_result
        })

        if not eval_result.get("is_compliant"):
            violations = eval_result.get("violations", [])
            explanation = (
                f"Your requested move on {shift_date} ({slot_window}) cannot be submitted: "
                + " ".join(violations)
                + " Allowed shifting hours are " + eval_result.get("shifting_hours", "09:00 - 18:00")
                + f" on {', '.join(eval_result.get('allowed_days', []))}."
            )
            return {
                "success": False,
                "status": "POLICY_VIOLATION",
                "explanation": explanation,
                "violations": violations,
                "events": events
            }

        # 2. MCP Tool: reserve_service_lift
        lift_result = await execute_mcp_tool(
            tool_name="reserve_service_lift",
            arguments={
                "request_id": request_id,
                "flat_id": flat_id,
                "shift_date": shift_date,
                "slot_window": slot_window,
                "direction": "UP" if move_type == "MOVE_IN" else "DOWN"
            },
            agent_role=self.role
        )
        events.append({
            "agent": "TenantAgent",
            "action": "reserve_service_lift",
            "payload": lift_result
        })

        if not lift_result.get("success"):
            return {
                "success": False,
                "status": "LIFT_CONFLICT",
                "explanation": lift_result.get("error", "Service elevator unavailable."),
                "events": events
            }

        # Gemini Natural Language Summary with Fallback
        gemini_summary = await self.gemini.generate_content(
            system_instruction=TENANT_SYSTEM_PROMPT,
            prompt=(
                f"Resident requested {move_type} for Flat {flat_id} on {shift_date} ({slot_window}). "
                f"Bylaws passed and lift hold #{lift_result.get('reservation_id')} acquired. "
                "Provide a 1-sentence confirmation for the tenant."
            )
        )
        text = gemini_summary.get("text", "")
        if text and not text.startswith("Evaluated with") and not text.startswith("Gemini API key"):
            message = text
        else:
            message = (
                f"Bylaw checks passed! Service elevator locked for {shift_date} ({slot_window}) "
                f"with a 15-minute reservation hold. Ready for owner tenancy verification."
            )

        return {
            "success": True,
            "status": "LIFT_HELD",
            "explanation": message,
            "lift_reservation": lift_result,
            "events": events
        }


# ── Conversational Intake & Bylaws Negotiation Engine ────────────────

import re
import uuid
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

class TenantChatEngine:
    """
    Maintains conversational session state and negotiates shift requests
    with real-time bylaw guidance and polite concierge alternatives.
    """
    def __init__(self, tenant_agent: TenantAgent, max_sessions: int = 100):
        self.agent = tenant_agent
        self.gemini = tenant_agent.gemini
        self.max_sessions = max_sessions
        self.sessions: OrderedDict[str, Dict[str, Any]] = OrderedDict()

    def _get_or_create_session(self, session_id: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
        if not session_id or session_id not in self.sessions:
            if len(self.sessions) >= self.max_sessions:
                self.sessions.popitem(last=False)  # Evict oldest
            session_id = session_id or str(uuid.uuid4())
            self.sessions[session_id] = {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "history": [],
                "params": {
                    "flat_id": None,
                    "resident_id": "res-tenant-new",
                    "move_type": None,
                    "shift_date": None,
                    "slot_window": None,
                    "vehicle_type": None,
                    "mover_details": "Self / Mover Truck",
                    "driver_phone": "+91-9876500000",
                    "vehicle_no": "KA-01-MJ-5566"
                }
            }
        else:
            self.sessions.move_to_end(session_id)
        return session_id, self.sessions[session_id]

    def _extract_heuristic_params(self, text: str, params: Dict[str, Any]) -> None:
        """Rule & regex based parameter extractor for deterministic offline resilience."""
        lower = text.lower()

        # Flat ID: T1-101, T1-102, T2-201 or flat 101
        flat_match = re.search(r'\b(t[12]-[12]0[12])\b', lower)
        if flat_match:
            params["flat_id"] = flat_match.group(1).upper()
        elif re.search(r'\b101\b', lower):
            params["flat_id"] = "T1-101"
        elif re.search(r'\b102\b', lower):
            params["flat_id"] = "T1-102"
        elif re.search(r'\b201\b', lower):
            params["flat_id"] = "T2-201"

        # Move Type
        if "move in" in lower or "moving in" in lower or "shift in" in lower or "shifting in" in lower:
            params["move_type"] = "MOVE_IN"
        elif "move out" in lower or "moving out" in lower or "vacat" in lower or "shift out" in lower:
            params["move_type"] = "MOVE_OUT"

        # Vehicle Type
        if "container" in lower:
            params["vehicle_type"] = "CONTAINER_40FT"
        elif "14ft" in lower or "14 ft" in lower or "truck" in lower:
            params["vehicle_type"] = "14FT_TRUCK"
        elif "van" in lower or "tempo" in lower or "pickup" in lower:
            params["vehicle_type"] = "VAN"

        # Slot Window
        if "09:00-13:00" in lower or "9 to 1" in lower or "morning" in lower or "9 am" in lower or "9am" in lower or "10 am" in lower:
            params["slot_window"] = "09:00-13:00"
        elif "14:00-18:00" in lower or "2 to 6" in lower or "afternoon" in lower or "2 pm" in lower or "2pm" in lower:
            params["slot_window"] = "14:00-18:00"
        elif re.search(r'\b(\d{2}:\d{2}\s*-\s*\d{2}:\d{2})\b', text):
            slot_match = re.search(r'\b(\d{2}:\d{2}\s*-\s*\d{2}:\d{2})\b', text)
            params["slot_window"] = slot_match.group(1).replace(" ", "")

        # Specific ISO Date YYYY-MM-DD
        date_match = re.search(r'\b(\d{4}-\d{2}-\d{2})\b', text)
        if date_match:
            params["shift_date"] = date_match.group(1)
        else:
            # Handle relative weekday references
            today = datetime.now()
            days_of_week = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
            for day_name, day_idx in days_of_week.items():
                if day_name in lower:
                    days_ahead = day_idx - today.weekday()
                    if days_ahead <= 0:
                        days_ahead += 7
                    target_dt = today + timedelta(days=days_ahead)
                    params["shift_date"] = target_dt.strftime("%Y-%m-%d")
                    break

        # Mover details
        if "agarwal" in lower:
            params["mover_details"] = "Agarwal Packers & Movers"
        elif "leo" in lower:
            params["mover_details"] = "Leo Packers"

    async def handle_message(self, message: str, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Processes an incoming tenant message conversationally with bylaw checks."""
        session_id, session_data = self._get_or_create_session(session_id)
        params = session_data["params"]
        session_data["history"].append({"role": "user", "content": message})

        # 1. Extract parameters heuristics
        self._extract_heuristic_params(message, params)

        # 2. Check if a date / slot / vehicle has been extracted to evaluate bylaws
        bylaw_result = None
        if params.get("shift_date") or params.get("vehicle_type") or params.get("slot_window"):
            bylaw_result = await execute_mcp_tool(
                "eval_shift_bylaws",
                {
                    "move_type": params.get("move_type") or "MOVE_IN",
                    "shift_date": params.get("shift_date") or "2026-10-03",
                    "slot_window": params.get("slot_window") or "09:00-13:00",
                    "vehicle_type": params.get("vehicle_type") or "VAN"
                },
                agent_role="TENANT"
            )

        # 3. Detect Violations & Generate Concierge Response
        reply = ""
        is_complete = False

        if bylaw_result and not bylaw_result.get("is_compliant"):
            violations = bylaw_result.get("violations", [])
            # Sunday violation concierge alternative
            if any("Sunday" in v for v in violations):
                params["shift_date"] = None  # Reset invalid date
                reply = (
                    "⚠️ **Sunday Curfew Policy**: Shifting on Sundays is strictly prohibited under Society Bylaw #4 "
                    "to preserve quiet hours for families.\n\n"
                    "💡 **Suggested Alternatives**:\n"
                    "• **Saturday (09:00 - 13:00)** — Recommended weekend slot\n"
                    "• **Monday (09:00 - 13:00 or 14:00 - 18:00)** — Weekday shifting\n\n"
                    "Would Saturday morning work for your schedule?"
                )
            # Vehicle container violation concierge alternative
            elif any("container" in v.lower() for v in violations):
                params["vehicle_type"] = None
                reply = (
                    "⚠️ **Basement Vehicle Limit**: Large container trucks (>14ft) cannot enter our basement due to "
                    "overhead fire sprinkler pipes and turning radius limits.\n\n"
                    "💡 **Permitted Vehicles**:\n"
                    "• **14FT Truck (14FT_TRUCK)** — Standard moving truck\n"
                    "• **Tempo / Pickup Van (VAN)** — Light carrier\n\n"
                    "Can your moving crew bring a 14ft truck or van?"
                )
            # Hours violation
            elif any("outside allowed" in v.lower() for v in violations):
                params["slot_window"] = None
                reply = (
                    "⚠️ **Quiet Hours Restriction**: Shifting outside 09:00 - 18:00 is not permitted.\n\n"
                    "💡 **Available Shifting Slots**:\n"
                    "• Slot 1: **09:00 - 13:00** (Morning)\n"
                    "• Slot 2: **14:00 - 18:00** (Afternoon)\n\n"
                    "Which time slot would you like to reserve?"
                )
            else:
                reply = f"⚠️ Please note: {'; '.join(violations)}. Could you please select an alternative time or vehicle?"

        # If compliant or still gathering parameters
        elif not params.get("flat_id"):
            reply = "Hello! I am your Tenant Representative Assistant. Which flat are you moving into or out of? (e.g. **T1-101**, **T1-102**, or **T2-201**)"
        elif not params.get("move_type"):
            reply = f"Got it for Flat **{params['flat_id']}**! Is this for moving in (**MOVE_IN**) or vacating/moving out (**MOVE_OUT**)?"
        elif not params.get("shift_date"):
            reply = f"Great! What date are you planning to shift into Flat **{params['flat_id']}**? (Society shifting days are Monday through Saturday, 09:00 to 18:00)."
        elif not params.get("slot_window"):
            reply = f"For **{params['shift_date']}**, which slot would you prefer?\n• **09:00 - 13:00** (Morning)\n• **14:00 - 18:00** (Afternoon)"
        elif not params.get("vehicle_type"):
            reply = "What vehicle will your movers bring? We permit **14FT_TRUCK** (standard 14-foot truck) or **VAN** (tempo/van). Large containers cannot enter the basement."
        else:
            # All parameters complete and valid!
            is_complete = True
            reply = (
                f"✅ **All details verified & bylaw-compliant!**\n\n"
                f"• **Flat**: {params['flat_id']}\n"
                f"• **Type**: {params['move_type']}\n"
                f"• **Date**: {params['shift_date']}\n"
                f"• **Slot**: {params['slot_window']}\n"
                f"• **Vehicle**: {params['vehicle_type']}\n"
                f"• **Movers**: {params['mover_details']}\n\n"
                f"Click **'Submit Move Request'** below to lock your freight elevator slot and submit for Owner NOC."
            )

        session_data["history"].append({"role": "assistant", "content": reply})
        missing = [k for k, v in params.items() if not v and k in ("flat_id", "move_type", "shift_date", "slot_window", "vehicle_type")]
        return {
            "session_id": session_id,
            "reply": reply,
            "extracted_params": params,
            "is_complete": is_complete,
            "ready_to_submit": is_complete,
            "dossier": params if is_complete else None,
            "missing_fields": missing,
            "bylaw_status": bylaw_result or {"is_compliant": True}
        }

