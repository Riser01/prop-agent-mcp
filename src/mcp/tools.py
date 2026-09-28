"""
Model Context Protocol (MCP) Tool Registry and Authoritative Handlers.
Exposes standard MCP tool schemas and pure Python async execution functions.
Includes strict dispatch-level Role-Based Access Control (RBAC),
cryptographically secure OTP generation, and robust time window validation.
"""
from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.database import (
    get_society_bylaws,
    update_society_bylaws as db_update_bylaws,
    get_flat_by_id,
    acquire_lift_hold,
    confirm_lift_booking,
    create_gate_pass,
    verify_gate_pass_at_security,
    sync_resident_directory as db_sync_directory,
    get_shift_request_by_id,
    update_shift_request_status
)

# ── Role-Based Access Control (RBAC) Allow-lists ─────────────────────

ROLE_TOOL_ALLOWLIST = {
    "TENANT": {
        "eval_shift_bylaws",
        "reserve_service_lift"
    },
    "OWNER": {
        "verify_dues_and_fees",
        "submit_owner_noc"
    },
    "ADMIN": {
        "eval_shift_bylaws",
        "reserve_service_lift",
        "verify_dues_and_fees",
        "submit_owner_noc",
        "generate_gate_pass",
        "validate_gate_pass_at_security",
        "sync_resident_directory",
        "update_society_bylaws"
    }
}

# ── Authoritative MCP Tool Schemas (JSON-Schema format) ──────────────

MCP_TOOL_DEFINITIONS = [
    {
        "name": "eval_shift_bylaws",
        "description": "Evaluates a proposed move-in or move-out request against society bylaws including allowed days, shifting hours, advance notice, and vehicle restrictions.",
        "parameters": {
            "type": "object",
            "properties": {
                "move_type": {
                    "type": "string",
                    "enum": ["MOVE_IN", "MOVE_OUT"],
                    "description": "Whether resident is moving into or out of the flat"
                },
                "shift_date": {
                    "type": "string",
                    "description": "Requested date in YYYY-MM-DD format"
                },
                "slot_window": {
                    "type": "string",
                    "description": "Time slot window (e.g. '09:00-13:00' or '14:00-18:00')"
                },
                "vehicle_type": {
                    "type": "string",
                    "enum": ["VAN", "14FT_TRUCK", "CONTAINER"],
                    "description": "Moving truck size category"
                }
            },
            "required": ["move_type", "shift_date", "slot_window", "vehicle_type"]
        }
    },
    {
        "name": "reserve_service_lift",
        "description": "Acquires an atomic 15-minute lazy-TTL reservation hold on the designated tower freight/service elevator.",
        "parameters": {
            "type": "object",
            "properties": {
                "request_id": { "type": "string", "description": "Associated shift request ID" },
                "flat_id": { "type": "string", "description": "Target flat ID (e.g. 'T1-101')" },
                "shift_date": { "type": "string", "description": "Date in YYYY-MM-DD format" },
                "slot_window": { "type": "string", "description": "Slot window e.g. '09:00-13:00'" },
                "direction": { "type": "string", "enum": ["UP", "DOWN", "BIDIRECTIONAL"] }
            },
            "required": ["request_id", "flat_id", "shift_date", "slot_window"]
        }
    },
    {
        "name": "verify_dues_and_fees",
        "description": "Checks outstanding flat maintenance dues and calculates society shifting fees and lift security deposit.",
        "parameters": {
            "type": "object",
            "properties": {
                "flat_id": { "type": "string", "description": "Flat identifier e.g. 'T1-102'" },
                "move_type": { "type": "string", "enum": ["MOVE_IN", "MOVE_OUT"] }
            },
            "required": ["flat_id", "move_type"]
        }
    },
    {
        "name": "submit_owner_noc",
        "description": "Allows the property owner agent to issue or reject a No-Objection Certificate (NOC) for move-in or move-out.",
        "parameters": {
            "type": "object",
            "properties": {
                "request_id": { "type": "string", "description": "Shift request ID" },
                "flat_id": { "type": "string", "description": "Flat identifier" },
                "move_type": { "type": "string", "enum": ["MOVE_IN", "MOVE_OUT"] },
                "sign_off_status": {
                    "type": "string",
                    "enum": ["APPROVED", "REJECTED"],
                    "description": "Owner sign-off decision"
                },
                "remarks": { "type": "string", "description": "Reason or condition remarks" }
            },
            "required": ["request_id", "flat_id", "move_type", "sign_off_status"]
        }
    },
    {
        "name": "generate_gate_pass",
        "description": "Issues an authenticated digital gate pass with a 6-digit security OTP and QR token upon final committee/admin approval.",
        "parameters": {
            "type": "object",
            "properties": {
                "request_id": { "type": "string", "description": "Shift request ID" },
                "mover_details": { "type": "string", "description": "Mover agency name or contact" },
                "vehicle_no": { "type": "string", "description": "Moving truck registration number" },
                "driver_phone": { "type": "string", "description": "Lead driver contact number" }
            },
            "required": ["request_id", "mover_details", "vehicle_no", "driver_phone"]
        }
    },
    {
        "name": "validate_gate_pass_at_security",
        "description": "Security guard checkpoint scanner that verifies the 6-digit OTP or QR token and logs arrival.",
        "parameters": {
            "type": "object",
            "properties": {
                "pass_code": { "type": "string", "description": "6-digit OTP or digital QR token UUID" }
            },
            "required": ["pass_code"]
        }
    },
    {
        "name": "sync_resident_directory",
        "description": "Transitions flat occupancy records upon completed move (ACTIVATE for move-in, ARCHIVE for move-out) or refreshes directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": { "type": "string", "enum": ["ACTIVATE", "ARCHIVE", "REFRESH"] },
                "flat_id": { "type": "string", "description": "Flat identifier (required for ACTIVATE or ARCHIVE)" },
                "tenant_details": {
                    "type": "object",
                    "description": "Tenant name, email, phone, lease dates (required for ACTIVATE)"
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "update_society_bylaws",
        "description": "Allows society administrator to configure shifting hours, allowed days of week, fee amounts, and concurrency limits.",
        "parameters": {
            "type": "object",
            "properties": {
                "allowed_days": { "type": "array", "items": { "type": "string" } },
                "start_time": { "type": "string" },
                "end_time": { "type": "string" },
                "slot_duration_hours": { "type": "integer" },
                "max_concurrent_moves": { "type": "integer" },
                "advance_notice_hours": { "type": "integer" },
                "move_in_fee": { "type": "number" },
                "move_out_fee": { "type": "number" },
                "lift_deposit": { "type": "number" },
                "require_owner_noc": { "type": "boolean" }
            }
        }
    }
]

# ── Tool Execution Implementation ───────────────────────────────────

async def handle_eval_shift_bylaws(
    move_type: str,
    shift_date: str,
    slot_window: str,
    vehicle_type: str
) -> Dict[str, Any]:
    bylaws = await get_society_bylaws()
    violations: List[str] = []

    # Check Day of Week
    try:
        dt = datetime.strptime(shift_date, "%Y-%m-%d")
        day_name = dt.strftime("%A")
        if day_name not in bylaws["allowed_days"]:
            violations.append(
                f"Shifting on {day_name} is prohibited by society bylaws. Allowed days: {', '.join(bylaws['allowed_days'])}."
            )
    except ValueError:
        violations.append("Invalid date format. Expected YYYY-MM-DD.")

    # Check Slot Hours using robust time parsing (handles non-padded and padded formats)
    try:
        slot_parts = slot_window.split("-")
        slot_start_t = datetime.strptime(slot_parts[0].strip(), "%H:%M").time()
        slot_end_t = datetime.strptime(slot_parts[1].strip(), "%H:%M").time()
        bylaw_start_t = datetime.strptime(bylaws["start_time"].strip(), "%H:%M").time()
        bylaw_end_t = datetime.strptime(bylaws["end_time"].strip(), "%H:%M").time()

        if slot_start_t < bylaw_start_t or slot_end_t > bylaw_end_t:
            violations.append(
                f"Requested slot {slot_window} outside allowed shifting hours ({bylaws['start_time']} - {bylaws['end_time']})."
            )
    except Exception:
        violations.append("Invalid slot_window format. Expected 'HH:MM-HH:MM'.")

    # Check Vehicle Size
    v_upper = (vehicle_type or "VAN").upper()
    if "CONTAINER" in v_upper or v_upper not in ("VAN", "14FT_TRUCK"):
        violations.append(
            f"Vehicle type '{vehicle_type}' prohibited: Large container trucks (>14ft) cannot enter society basement. Permitted vehicles: 14ft truck (14FT_TRUCK) or van (VAN)."
        )

    is_compliant = len(violations) == 0
    return {
        "is_compliant": is_compliant,
        "violations": violations,
        "allowed_days": bylaws["allowed_days"],
        "shifting_hours": f"{bylaws['start_time']} - {bylaws['end_time']}",
        "max_concurrent_moves": bylaws["max_concurrent_moves"]
    }

async def handle_reserve_service_lift(
    request_id: str,
    flat_id: str,
    shift_date: str,
    slot_window: str,
    direction: str = "BIDIRECTIONAL"
) -> Dict[str, Any]:
    flat = await get_flat_by_id(flat_id)
    if not flat:
        return {"success": False, "error": f"Flat {flat_id} not found in directory"}

    tower = flat["tower"]
    reservation = await acquire_lift_hold(
        request_id=request_id,
        tower=tower,
        shift_date=shift_date,
        slot_window=slot_window,
        ttl_minutes=15
    )

    if not reservation:
        return {
            "success": False,
            "error": f"Service elevator in {tower} is fully booked for {shift_date} {slot_window}. Please select another slot."
        }

    return {
        "success": True,
        "reservation_id": reservation["id"],
        "tower": tower,
        "lift_type": "SERVICE_FREIGHT",
        "slot_window": slot_window,
        "hold_expires_at": reservation["hold_expires_at"],
        "status": "HELD_15_MIN_TTL"
    }

async def handle_verify_dues_and_fees(flat_id: str, move_type: str) -> Dict[str, Any]:
    flat = await get_flat_by_id(flat_id)
    if not flat:
        return {"success": False, "error": f"Flat {flat_id} not found"}

    bylaws = await get_society_bylaws()
    maintenance_dues = float(flat.get("maintenance_dues", 0.0))

    if move_type == "MOVE_IN":
        fee = bylaws.get("move_in_fee", 2000.0)
        deposit = bylaws.get("lift_deposit", 5000.0)
        can_proceed = True
        notes = f"Move-in fee: ₹{fee:.0f}, Lift security deposit: ₹{deposit:.0f}."
    else:  # MOVE_OUT
        fee = bylaws.get("move_out_fee", 1000.0)
        deposit = 0.0
        can_proceed = (maintenance_dues == 0.0)
        notes = (
            f"Zero maintenance dues verified."
            if can_proceed
            else f"BLOCKED: Outstanding maintenance dues ₹{maintenance_dues:.2f} must be settled before move-out NOC."
        )

    return {
        "flat_id": flat_id,
        "move_type": move_type,
        "maintenance_dues": maintenance_dues,
        "shifting_fee": fee,
        "lift_deposit": deposit,
        "dues_cleared": can_proceed,
        "notes": notes
    }

async def handle_submit_owner_noc(
    request_id: str,
    flat_id: str,
    move_type: str,
    sign_off_status: str,
    remarks: str = ""
) -> Dict[str, Any]:
    req = await get_shift_request_by_id(request_id)
    if not req:
        return {"success": False, "error": f"Request {request_id} not found"}

    updated = await update_shift_request_status(
        request_id=request_id,
        status="OWNER_NOC_APPROVED" if sign_off_status == "APPROVED" else "REJECTED_BY_OWNER",
        owner_noc_status=sign_off_status,
        notes=f"Owner sign-off: {sign_off_status}. Remarks: {remarks}"
    )

    return {
        "success": True,
        "request_id": request_id,
        "owner_noc_status": sign_off_status,
        "status": sign_off_status,
        "new_request_status": updated["status"],
        "remarks": remarks
    }

async def handle_generate_gate_pass(
    request_id: str,
    mover_details: str,
    vehicle_no: str,
    driver_phone: str
) -> Dict[str, Any]:
    req = await get_shift_request_by_id(request_id)
    if not req:
        return {"success": False, "error": f"Request {request_id} not found"}

    # Confirm lift booking permanently
    await confirm_lift_booking(request_id)

    # Cryptographically secure 6-digit numeric OTP and QR token
    otp_code = f"{secrets.randbelow(900000) + 100000}"
    qr_token = str(uuid.uuid4())

    gate_pass = await create_gate_pass(
        request_id=request_id,
        otp_code=otp_code,
        qr_token=qr_token,
        valid_date=req["shift_date"],
        valid_slot=req["slot_window"],
        vehicle_no=vehicle_no,
        driver_phone=driver_phone
    )

    await update_shift_request_status(
        request_id=request_id,
        status="GATE_PASS_ISSUED",
        fees_paid=1,
        dues_cleared=1
    )

    return {
        "success": True,
        "gate_pass_id": gate_pass["id"],
        "otp_code": otp_code,
        "qr_token": qr_token,
        "valid_date": req["shift_date"],
        "valid_slot": req["slot_window"],
        "vehicle_no": vehicle_no,
        "driver_phone": driver_phone,
        "instructions": "Present 6-digit OTP or digital QR code to Society Main Security Gate."
    }

async def handle_validate_gate_pass_at_security(pass_code: str) -> Dict[str, Any]:
    verified = await verify_gate_pass_at_security(pass_code)
    if not verified:
        return {
            "success": False,
            "error": "Invalid or expired Gate Pass OTP/QR token. Entry denied by security."
        }

    # Automatically trigger Directory Transition
    flat_id = verified["flat_id"]
    move_type = verified["move_type"]
    action = "ACTIVATE" if move_type == "MOVE_IN" else "ARCHIVE"
    await db_sync_directory(flat_id=flat_id, action=action, tenant_id=verified["resident_id"])

    return {
        "success": True,
        "gate_pass_id": verified["id"],
        "flat_id": flat_id,
        "resident_name": verified["resident_name"],
        "move_type": move_type,
        "check_in_at": verified["check_in_at"],
        "directory_updated": f"Tenant {action} completed for Flat {flat_id}."
    }

async def handle_sync_resident_directory(
    action: str = "REFRESH",
    flat_id: Optional[str] = None,
    tenant_details: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    if action == "REFRESH":
        from src.database import get_directory_data
        data = await get_directory_data()
        return {"success": True, "action": "REFRESH", "flats_count": len(data["flats"])}

    result = await db_sync_directory(flat_id=flat_id, action=action, tenant_details=tenant_details)
    return {
        "success": True,
        "flat_id": flat_id,
        "action": action,
        "directory": result
    }

async def handle_update_society_bylaws(
    config_payload: Optional[Dict[str, Any]] = None,
    **kwargs
) -> Dict[str, Any]:
    payload = config_payload if config_payload is not None else kwargs
    updated = await db_update_bylaws(payload)
    return {"success": True, "bylaws": updated}

# ── Dispatcher with RBAC ─────────────────────────────────────────────

TOOL_DISPATCH_MAP = {
    "eval_shift_bylaws": handle_eval_shift_bylaws,
    "reserve_service_lift": handle_reserve_service_lift,
    "verify_dues_and_fees": handle_verify_dues_and_fees,
    "submit_owner_noc": handle_submit_owner_noc,
    "generate_gate_pass": handle_generate_gate_pass,
    "validate_gate_pass_at_security": handle_validate_gate_pass_at_security,
    "sync_resident_directory": handle_sync_resident_directory,
    "update_society_bylaws": handle_update_society_bylaws,
}

async def execute_mcp_tool(tool_name: str, arguments: Dict[str, Any], agent_role: str = "ADMIN") -> Dict[str, Any]:
    """
    Executes an MCP tool with role-based access control.
    Raises PermissionError if the role does not have authorization for this tool.
    """
    allowed_tools = ROLE_TOOL_ALLOWLIST.get(agent_role.upper(), set())
    if tool_name not in allowed_tools:
        return {
            "success": False,
            "error": f"RBAC Denied: Role '{agent_role}' is not authorized to execute tool '{tool_name}'."
        }

    handler = TOOL_DISPATCH_MAP.get(tool_name)
    if not handler:
        return {"success": False, "error": f"Tool '{tool_name}' is not recognized."}

    try:
        return await handler(**arguments)
    except Exception as exc:
        return {"success": False, "error": f"Tool execution failed: {str(exc)}"}
