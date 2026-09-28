"""
FastAPI application for PropAgent MCP.
Provides REST API, Server-Sent Events (SSE) streaming, and serves the zero-build web frontend.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any, Dict, List, Literal, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.database import (
    init_db,
    get_society_bylaws,
    update_society_bylaws,
    get_directory_data,
    list_shift_requests,
    get_shift_request_by_id,
    get_flat_by_id,
    sync_resident_directory,
    create_shift_request,
    update_shift_request_status,
    extend_lift_hold,
    release_lift_hold
)
from src.mcp.tools import execute_mcp_tool, MCP_TOOL_DEFINITIONS
from src.agents.orchestrator import ShiftOrchestrator
from src.agents.tenant_agent import TenantChatEngine

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize SQLite database and seed defaults on startup
    await init_db()
    yield

app = FastAPI(
    title="PropAgent MCP - Property Management Multi-Agent System",
    description="Multi-Agent move-in/move-out management powered by Gemini and Model Context Protocol",
    version="1.0.0",
    lifespan=lifespan
)

orchestrator = ShiftOrchestrator()
chat_engine = TenantChatEngine(orchestrator.tenant_agent)

# ── Pydantic Request Models ──────────────────────────────────────────

class BylawsUpdateRequest(BaseModel):
    allowed_days: List[str] = Field(..., example=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"])
    start_time: str = Field(..., example="09:00")
    end_time: str = Field(..., example="18:00")
    slot_duration_hours: int = Field(4, example=4)
    max_concurrent_moves: int = Field(1, example=1)
    advance_notice_hours: int = Field(24, example=24)
    move_in_fee: float = Field(2000.0, example=2000.0)
    move_out_fee: float = Field(1000.0, example=1000.0)
    lift_deposit: float = Field(5000.0, example=5000.0)
    require_owner_noc: bool = Field(True, example=True)

class ShiftRequestInput(BaseModel):
    flat_id: str = Field(..., example="T1-101")
    resident_id: Optional[str] = Field("res-tenant-new", example="res-tenant-new")
    move_type: Literal["MOVE_IN", "MOVE_OUT"] = Field(..., example="MOVE_IN")
    shift_date: str = Field(..., example="2026-10-03")
    slot_window: str = Field(..., pattern=r"^\d{2}:\d{2}-\d{2}:\d{2}$", example="09:00-13:00")
    vehicle_type: Literal["VAN", "14FT_TRUCK", "CONTAINER"] = Field(..., example="14FT_TRUCK")
    mover_details: str = Field("Agarwal Packers & Movers", example="Agarwal Packers & Movers")
    driver_phone: Optional[str] = Field("+91-9876543210")
    vehicle_no: Optional[str] = Field("KA-01-AB-1234")
    mode: Optional[Literal["auto", "step"]] = Field("auto", example="auto")

class TenantChatInput(BaseModel):
    message: str = Field(..., example="I want to move in to T1-101 this Saturday at 9am with 14ft truck")
    session_id: Optional[str] = Field(None, example="sess-123")

class SecurityVerifyInput(BaseModel):
    pass_code: str = Field(..., example="541979")

class OwnerNocInput(BaseModel):
    request_id: str
    flat_id: str
    move_type: Literal["MOVE_IN", "MOVE_OUT"]
    sign_off_status: Literal["APPROVED", "REJECTED"]
    remarks: Optional[str] = ""

class DirectorySyncInput(BaseModel):
    flat_id: Optional[str] = None
    action: Literal["ACTIVATE", "ARCHIVE", "REFRESH"] = "REFRESH"
    tenant_details: Optional[Dict[str, Any]] = None

# ── API Endpoints ───────────────────────────────────────────────────

@app.get("/api/bylaws")
async def api_get_bylaws():
    """Returns active society bylaws and move-in/out policies."""
    bylaws = await get_society_bylaws()
    return bylaws

@app.post("/api/bylaws")
async def api_update_bylaws(payload: BylawsUpdateRequest):
    """Admin configuration endpoint: updates allowed days, hours, concurrency, and fees."""
    updated = await update_society_bylaws(payload.model_dump())
    return {"status": "success", "bylaws": updated}

@app.get("/api/directory")
async def api_get_directory():
    """Returns flat and resident directory."""
    data = await get_directory_data()
    return data

@app.post("/api/directory/sync")
async def api_sync_directory(payload: DirectorySyncInput):
    """Admin action: triggers directory refresh ('refresh these people') or updates tenant assignment."""
    res = await execute_mcp_tool(
        tool_name="sync_resident_directory",
        arguments={
            "action": payload.action,
            "flat_id": payload.flat_id,
            "tenant_details": payload.tenant_details
        },
        agent_role="ADMIN"
    )
    return res

@app.get("/api/requests")
async def api_list_requests():
    """Lists all historical and active shift requests."""
    return await list_shift_requests()

@app.get("/api/requests/{request_id}")
async def api_get_request(request_id: str):
    req = await get_shift_request_by_id(request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Shift request not found")
    return req

@app.post("/api/chat/tenant")
async def api_tenant_chat(payload: TenantChatInput):
    """Conversational intake endpoint with Tenant Agent."""
    return await chat_engine.handle_message(payload.message, payload.session_id)

@app.get("/api/notifications")
async def api_get_notifications(owner_id: str = "res-owner-101"):
    """Returns pending approval counts strictly scoped by role for live badge alerts."""
    all_reqs = await list_shift_requests()
    owner_pending = 0
    admin_pending = 0
    for r in all_reqs:
        if r.get("owner_noc_status") == "PENDING" and r.get("status") in ("LIFT_HELD", "REQUEST_SUBMITTED"):
            flat = await get_flat_by_id(r["flat_id"])
            if flat and (flat.get("owner_id") == owner_id or not owner_id):
                owner_pending += 1
        elif r.get("status") == "OWNER_NOC_APPROVED":
            admin_pending += 1

    return {
        "owner_pending": owner_pending,
        "owner_pending_noc": owner_pending,
        "admin_pending": admin_pending,
        "admin_pending_clearance": admin_pending,
        "total": owner_pending + admin_pending
    }

@app.post("/api/shift-requests")
async def api_create_shift_request(payload: ShiftRequestInput):
    """
    Submits a new shift request.
    Supports mode='auto' (full headless pipeline) and mode='step' (interactive human-in-the-loop).
    """
    flat = await get_flat_by_id(payload.flat_id)
    if not flat:
        raise HTTPException(status_code=404, detail=f"Flat {payload.flat_id} not found in society records")

    req_id = f"REQ-{uuid.uuid4().hex[:8].upper()}"

    # Step-by-Step Mode (for interactive demo)
    if payload.mode == "step":
        # 1. Bylaw evaluation
        bylaws_eval = await execute_mcp_tool(
            "eval_shift_bylaws",
            {
                "move_type": payload.move_type,
                "shift_date": payload.shift_date,
                "slot_window": payload.slot_window,
                "vehicle_type": payload.vehicle_type
            },
            agent_role="TENANT"
        )
        if not bylaws_eval.get("is_compliant"):
            violations = bylaws_eval.get("violations", [])
            raise HTTPException(status_code=400, detail="; ".join(violations))

        # 2. Create request record in database first (to satisfy FOREIGN KEY constraint for lift hold)
        await create_shift_request(
            request_id=req_id,
            flat_id=payload.flat_id,
            resident_id=payload.resident_id,
            move_type=payload.move_type,
            shift_date=payload.shift_date,
            slot_window=payload.slot_window,
            vehicle_type=payload.vehicle_type,
            mover_details=payload.mover_details,
            status="REQUEST_SUBMITTED",
            notes="Submitted via Tenant Portal; holding lift."
        )

        # 3. Acquire lift hold with 24-hour demo hold
        lift_res = await execute_mcp_tool(
            "reserve_service_lift",
            {
                "request_id": req_id,
                "flat_id": payload.flat_id,
                "shift_date": payload.shift_date,
                "slot_window": payload.slot_window,
                "direction": "UP" if payload.move_type == "MOVE_IN" else "DOWN"
            },
            agent_role="TENANT"
        )
        if not lift_res.get("success"):
            await update_shift_request_status(req_id, "LIFT_CONFLICT", notes=lift_res.get("error", "Elevator booked"))
            raise HTTPException(status_code=409, detail=lift_res.get("error", "Service elevator already booked."))

        # 4. Update request record in LIFT_HELD status
        await update_shift_request_status(req_id, "LIFT_HELD", notes="Lift hold confirmed; awaiting Owner NOC.")
        # Extend hold to accommodate async demo review
        await extend_lift_hold(req_id, 1440)

        req_data = await get_shift_request_by_id(req_id)
        return {
            "request_id": req_id,
            "request": req_data,
            "final_state": "LIFT_HELD",
            "status": "LIFT_HELD",
            "message": f"Service elevator reserved for {payload.shift_date} ({payload.slot_window}). Awaiting Owner NOC approval.",
            "gate_pass": None,
            "events": [
                {"step": "INIT", "state": "REQUEST_SUBMITTED", "message": "Request submitted."},
                {"step": "TENANT_AGENT_DONE", "state": "LIFT_HELD", "message": "Bylaws verified & elevator locked."}
            ]
        }

    # Auto Mode (full pipeline for automated tests)
    events = []
    final_event = None

    async for ev in orchestrator.run_pipeline(
        request_id=req_id,
        flat_id=payload.flat_id,
        resident_id=payload.resident_id,
        move_type=payload.move_type,
        shift_date=payload.shift_date,
        slot_window=payload.slot_window,
        vehicle_type=payload.vehicle_type,
        mover_details=payload.mover_details,
        driver_phone=payload.driver_phone or "+91-9876543210",
        vehicle_no=payload.vehicle_no or "KA-01-AB-1234"
    ):
        events.append(ev)
        if ev["step"] in ("COMPLETED", "FAILED"):
            final_event = ev

    req_data = await get_shift_request_by_id(req_id)
    return {
        "request_id": req_id,
        "request": req_data,
        "final_state": final_event.get("state") if final_event else "UNKNOWN",
        "message": final_event.get("message") if final_event else "",
        "gate_pass": final_event.get("gate_pass") if final_event else None,
        "events": events
    }

@app.get("/api/shift-requests/{request_id}/stream")
async def api_stream_shift_request(request_id: str):
    """
    Server-Sent Events (SSE) streaming endpoint for live agent workflow visualization.
    """
    req = await get_shift_request_by_id(request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    async def event_generator():
        yield f"data: {json.dumps({'step': 'STATUS', 'state': req['status'], 'notes': req.get('notes')})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/api/owner-noc")
async def api_submit_owner_noc(payload: OwnerNocInput):
    """Direct or agentic Owner NOC sign-off with financial dues guard."""
    flat = await get_flat_by_id(payload.flat_id)
    if not flat:
        raise HTTPException(status_code=404, detail="Flat not found")

    # Guard: for move-out, ensure dues are 0 before owner approval
    if payload.move_type == "MOVE_OUT" and payload.sign_off_status == "APPROVED":
        if flat.get("maintenance_dues", 0.0) > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot grant Owner NOC: Outstanding maintenance dues of ₹{flat['maintenance_dues']:.2f} must be settled first."
            )

    res = await execute_mcp_tool(
        tool_name="submit_owner_noc",
        arguments=payload.model_dump(),
        agent_role="OWNER"
    )

    if payload.sign_off_status == "APPROVED":
        await extend_lift_hold(payload.request_id, 1440)
        await update_shift_request_status(payload.request_id, "OWNER_NOC_APPROVED", owner_noc_status="APPROVED")
    else:
        await release_lift_hold(payload.request_id)
        await update_shift_request_status(payload.request_id, "REJECTED_BY_OWNER", owner_noc_status="REJECTED")

    return res

@app.post("/api/requests/{request_id}/approve")
async def api_admin_approve_request(request_id: str):
    """Admin endpoint to finalize an approved request and issue the Gate Pass."""
    req = await get_shift_request_by_id(request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    res = await execute_mcp_tool(
        tool_name="generate_gate_pass",
        arguments={
            "request_id": request_id,
            "mover_details": req["mover_details"],
            "vehicle_no": req.get("vehicle_type", "14FT_TRUCK"),
            "driver_phone": "+91-9876543210"
        },
        agent_role="ADMIN"
    )
    return res

@app.post("/api/requests/{request_id}/reject")
async def api_admin_reject_request(request_id: str, reason: str = "Rejected by society administration"):
    """Admin endpoint to reject a request and immediately release elevator hold."""
    req = await get_shift_request_by_id(request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    await release_lift_hold(request_id)
    updated = await update_shift_request_status(request_id, "REJECTED_BY_ADMIN", notes=reason)
    return {"success": True, "request_id": request_id, "status": "REJECTED_BY_ADMIN"}

@app.post("/api/security/verify")
async def api_security_verify(payload: SecurityVerifyInput):
    """Security Guard Gate check-in verification using 6-digit OTP or QR token."""
    res = await execute_mcp_tool(
        tool_name="validate_gate_pass_at_security",
        arguments={"pass_code": payload.pass_code},
        agent_role="ADMIN"
    )
    return res

@app.get("/api/mcp/tools")
async def api_list_mcp_tools():
    """Returns official MCP tool definitions for inspection."""
    return {"tools": MCP_TOOL_DEFINITIONS}

# ── Static UI Mounting ──────────────────────────────────────────────

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h2>PropAgent MCP is running. Static frontend ready.</h2>")
