"""
Multi-Agent Orchestrator driving the Finite State Machine (FSM)
between Tenant Agent, Owner Agent, and Admin Agent.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional

from src.agents.gemini_client import GeminiClient
from src.agents.tenant_agent import TenantAgent
from src.agents.owner_agent import OwnerAgent
from src.agents.admin_agent import AdminAgent
from src.database import (
    create_shift_request,
    get_shift_request_by_id,
    update_shift_request_status,
    get_flat_by_id,
    release_lift_hold
)

class ShiftOrchestrator:
    def __init__(self):
        self.gemini = GeminiClient()
        self.tenant_agent = TenantAgent(self.gemini)
        self.owner_agent = OwnerAgent(self.gemini)
        self.admin_agent = AdminAgent(self.gemini)

    async def run_pipeline(
        self,
        request_id: str,
        flat_id: str,
        resident_id: str,
        move_type: str,
        shift_date: str,
        slot_window: str,
        vehicle_type: str,
        mover_details: str,
        driver_phone: str = "+91-9876500000",
        vehicle_no: str = "KA-01-MJ-4040"
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Runs the full multi-agent pipeline and yields progress events
        for Server-Sent Events (SSE) streaming to the web UI.
        """
        # Step 0: Create Request in DB
        yield {
            "step": "INIT",
            "state": "REQUEST_SUBMITTED",
            "message": f"Submitting {move_type} request for Flat {flat_id} on {shift_date}...",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        await create_shift_request(
            request_id=request_id,
            flat_id=flat_id,
            resident_id=resident_id,
            move_type=move_type,
            shift_date=shift_date,
            slot_window=slot_window,
            vehicle_type=vehicle_type,
            mover_details=mover_details,
            status="REQUEST_SUBMITTED"
        )

        # Step 1: Tenant Agent (Bylaw Check & Service Lift Hold)
        yield {
            "step": "TENANT_AGENT",
            "state": "BYLAW_EVALUATION",
            "message": "Tenant Agent checking society bylaws (allowed days, hours, vehicle limits)...",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        tenant_res = await self.tenant_agent.process_shift_request(
            request_id=request_id,
            flat_id=flat_id,
            move_type=move_type,
            shift_date=shift_date,
            slot_window=slot_window,
            vehicle_type=vehicle_type
        )

        for event in tenant_res.get("events", []):
            yield {
                "step": "TOOL_CALL",
                "agent": event["agent"],
                "action": event["action"],
                "payload": event["payload"],
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        if not tenant_res["success"]:
            await update_shift_request_status(
                request_id=request_id,
                status=tenant_res["status"],
                notes=tenant_res["explanation"]
            )
            yield {
                "step": "FAILED",
                "state": tenant_res["status"],
                "message": tenant_res["explanation"],
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            return

        await update_shift_request_status(
            request_id=request_id,
            status="LIFT_HELD",
            notes=tenant_res["explanation"]
        )

        yield {
            "step": "TENANT_AGENT_DONE",
            "state": "LIFT_HELD",
            "message": tenant_res["explanation"],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        # Step 2: Owner Agent (Tenancy Verification & Maintenance Dues)
        yield {
            "step": "OWNER_AGENT",
            "state": "OWNER_NOC_PENDING",
            "message": "Owner Agent reviewing tenancy agreement and financial dues status...",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        owner_res = await self.owner_agent.verify_and_sign_noc(
            request_id=request_id,
            flat_id=flat_id,
            move_type=move_type
        )

        for event in owner_res.get("events", []):
            yield {
                "step": "TOOL_CALL",
                "agent": event["agent"],
                "action": event["action"],
                "payload": event["payload"],
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        if not owner_res["success"]:
            await release_lift_hold(request_id)
            yield {
                "step": "FAILED",
                "state": owner_res["status"],
                "message": owner_res["explanation"],
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            return

        yield {
            "step": "OWNER_AGENT_DONE",
            "state": "OWNER_NOC_APPROVED",
            "message": owner_res["explanation"],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        # Step 3: Admin Agent (Bylaws Clearance & Digital Gate Pass Issuance)
        yield {
            "step": "ADMIN_AGENT",
            "state": "ADMIN_APPROVAL",
            "message": "Society Admin Agent validating compliance dossier and generating Gate Pass...",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        admin_res = await self.admin_agent.approve_and_issue_gate_pass(
            request_id=request_id,
            mover_details=mover_details,
            vehicle_no=vehicle_no,
            driver_phone=driver_phone
        )

        for event in admin_res.get("events", []):
            yield {
                "step": "TOOL_CALL",
                "agent": event["agent"],
                "action": event["action"],
                "payload": event["payload"],
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        if not admin_res["success"]:
            await release_lift_hold(request_id)
            yield {
                "step": "FAILED",
                "state": admin_res["status"],
                "message": admin_res["explanation"],
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            return

        yield {
            "step": "COMPLETED",
            "state": "GATE_PASS_ISSUED",
            "message": admin_res["explanation"],
            "gate_pass": admin_res["gate_pass"],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
