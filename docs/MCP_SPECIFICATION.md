# Model Context Protocol (MCP) Specification: Residential Property Management

## 1. Overview & Protocol Standard
This document specifies the Model Context Protocol (MCP) tool contract and architecture for multi-agent residential move-in/move-out workflows. The system complies with MCP standard version `2024-11-05` and supports both in-process agent execution and standard I/O (stdio) JSON-RPC 2.0 communication for external MCP hosts.

## 2. Architecture & Role-Based Access Control (RBAC)
Agents operate under strictly partitioned role allowlists to prevent privilege escalation:

| Agent Role | Authorized MCP Tools |
|---|---|
| **TENANT** | `eval_shift_bylaws`, `reserve_service_lift` |
| **OWNER** | `verify_dues_and_fees`, `submit_owner_noc` |
| **ADMIN** | `eval_shift_bylaws`, `reserve_service_lift`, `verify_dues_and_fees`, `submit_owner_noc`, `generate_gate_pass`, `validate_gate_pass_at_security`, `sync_resident_directory`, `update_society_bylaws` |

---

## 3. Tool Specifications & JSON Schemas

### 3.1 `eval_shift_bylaws`
- **Description**: Evaluates proposed move-in/move-out date, shifting hours, advance notice, and vehicle size against community bylaws.
- **Role**: `TENANT`, `ADMIN`
- **Parameters**:
  ```json
  {
    "type": "object",
    "properties": {
      "move_type": { "type": "string", "enum": ["MOVE_IN", "MOVE_OUT"] },
      "shift_date": { "type": "string", "description": "Date in YYYY-MM-DD" },
      "slot_window": { "type": "string", "description": "Slot window e.g. '09:00-13:00'" },
      "vehicle_type": { "type": "string", "enum": ["VAN", "14FT_TRUCK", "CONTAINER"] }
    },
    "required": ["move_type", "shift_date", "slot_window", "vehicle_type"]
  }
  ```

### 3.2 `reserve_service_lift`
- **Description**: Atomically acquires a 15-minute lazy-TTL hold on the designated tower freight/service elevator.
- **Role**: `TENANT`, `ADMIN`
- **Parameters**:
  ```json
  {
    "type": "object",
    "properties": {
      "request_id": { "type": "string" },
      "flat_id": { "type": "string" },
      "shift_date": { "type": "string" },
      "slot_window": { "type": "string" },
      "direction": { "type": "string", "enum": ["UP", "DOWN", "BIDIRECTIONAL"] }
    },
    "required": ["request_id", "flat_id", "shift_date", "slot_window"]
  }
  ```

### 3.3 `verify_dues_and_fees`
- **Description**: Verifies flat maintenance ledger balance and calculates shifting fees and elevator security deposit.
- **Role**: `OWNER`, `ADMIN`
- **Parameters**:
  ```json
  {
    "type": "object",
    "properties": {
      "flat_id": { "type": "string" },
      "move_type": { "type": "string", "enum": ["MOVE_IN", "MOVE_OUT"] }
    },
    "required": ["flat_id", "move_type"]
  }
  ```

### 3.4 `submit_owner_noc`
- **Description**: Issues or denies landlord No-Objection Certificate (NOC) for move-in or move-out.
- **Role**: `OWNER`, `ADMIN`
- **Parameters**:
  ```json
  {
    "type": "object",
    "properties": {
      "request_id": { "type": "string" },
      "flat_id": { "type": "string" },
      "move_type": { "type": "string", "enum": ["MOVE_IN", "MOVE_OUT"] },
      "sign_off_status": { "type": "string", "enum": ["APPROVED", "REJECTED"] },
      "remarks": { "type": "string" }
    },
    "required": ["request_id", "flat_id", "move_type", "sign_off_status"]
  }
  ```

### 3.5 `generate_gate_pass`
- **Description**: Issues an authenticated digital gate pass with a cryptographically secure 6-digit numeric OTP and QR token upon final committee/admin approval.
- **Role**: `ADMIN`
- **Parameters**:
  ```json
  {
    "type": "object",
    "properties": {
      "request_id": { "type": "string" },
      "mover_details": { "type": "string" },
      "vehicle_no": { "type": "string" },
      "driver_phone": { "type": "string" }
    },
    "required": ["request_id", "mover_details", "vehicle_no", "driver_phone"]
  }
  ```

### 3.6 `validate_gate_pass_at_security`
- **Description**: Checkpoint verification terminal for security guards; validates 6-digit OTP and logs vehicle arrival.
- **Role**: `ADMIN`
- **Parameters**:
  ```json
  {
    "type": "object",
    "properties": {
      "pass_code": { "type": "string", "description": "6-digit OTP code or QR UUID" }
    },
    "required": ["pass_code"]
  }
  ```

### 3.7 `sync_resident_directory`
- **Description**: Updates flat tenancy occupancy records (`ACTIVATE` for move-in, `ARCHIVE` for move-out) or triggers a global directory refresh ("refresher").
- **Role**: `ADMIN`
- **Parameters**:
  ```json
  {
    "type": "object",
    "properties": {
      "action": { "type": "string", "enum": ["ACTIVATE", "ARCHIVE", "REFRESH"] },
      "flat_id": { "type": "string", "description": "Target flat ID (optional for REFRESH)" },
      "tenant_details": { "type": "object" }
    },
    "required": ["action"]
  }
  ```

### 3.8 `update_society_bylaws`
- **Description**: Configures shifting hours, allowed days of week, fee structures, and lift concurrency limits.
- **Role**: `ADMIN`
- **Parameters**:
  ```json
  {
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
  ```

---

## 4. Running the Stdio Server
External MCP hosts can spawn the stdio runner:
```bash
python -m src.mcp.server
```
Example JSON-RPC 2.0 handshake:
```json
{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
{"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
{"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "eval_shift_bylaws", "arguments": {"move_type": "MOVE_IN", "shift_date": "2026-10-03", "slot_window": "09:00-13:00", "vehicle_type": "14FT_TRUCK"}, "role": "TENANT"}}
```
