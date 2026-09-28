# PropAgent MCP — System Guide

## Layer 1: The Big Picture (2 minutes to read)

Moving into or out of an apartment complex is usually chaotic. Moving vans block driveways, multiple families fight for the service elevator, tenants vacate before paying past dues, and security guards stop trucks at the gate because no paperwork exists.

PropAgent solves this by replacing chaotic phone calls and paper forms with an automated coordination system. When a resident wants to move, the system automatically checks society bylaws (such as quiet hours and allowed days), reserves the freight elevator, verifies with the property owner that rent and dues are clear, alerts society administration for final sign-off, and sends a digital pass with a 6-digit code directly to security at the gate.

The entire process takes seconds instead of days, ensures rules are followed without arguments, and keeps the society directory synchronized the moment the moving truck passes the gate.

---

## Layer 2: How It Works — Step by Step (5 minutes to read)

Here is a concrete walk-through of an incoming tenant moving into Apartment T1-101 on Saturday, October 3rd:

1. **Intake & Bylaw Check**:
   Tenant Priya Nair submits a request to move into Flat T1-101 on Saturday from 09:00 to 13:00 with a 14-foot truck. The system checks the society rulebook. Saturday is an approved moving day, 09:00-13:00 is within the allowed 09:00-18:00 window, and the truck size meets parking limits.

2. **Elevator Hold**:
   The system places a 15-minute temporary hold on Tower 1's service elevator. No other resident can book that elevator for that morning while approvals are pending.

3. **Owner NOC & Dues Check**:
   The system contacts Flat T1-101's owner (Rajesh Sharma). It verifies that previous utility bills and maintenance dues are zero. Rajesh grants the Owner No Objection Certificate (NOC).

4. **Society Sign-Off & Gate Pass Issuance**:
   Society administration signs off. The elevator hold converts into a permanent reservation. A digital gate pass is issued with a secure 6-digit code (`244882`).

5. **Security Checkpoint & Directory Refresh**:
   On moving morning, the truck arrives at the main gate. The security guard enters `244882` into the checkpoint terminal. The gate barrier opens. Flat T1-101 is automatically updated from "Vacant" to "Occupied by Tenant: Priya Nair" across the society directory.

If Priya had picked Sunday instead of Saturday, the system would have immediately blocked the submission, citing Society Rule 4.2 ("No shifting permitted on Sundays to protect resident quiet hours"), and suggested the nearest available Saturday slot.

---

## Layer 3: Architecture & Design Decisions (10 minutes to read)

### Architecture Overview

```
┌────────────────────────────────────────────────────────┐
│               Responsive Web Dashboard                 │
│  (Tenant Portal · Owner Desk · Admin Hub · Gate App)   │
└───────────────────────────┬────────────────────────────┘
                            │ REST / SSE Stream
                            ▼
┌────────────────────────────────────────────────────────┐
│                   FastAPI Application                  │
│               (Single-Process Orchestrator)            │
└───────────────┬────────────────────────┬───────────────┘
                │                        │
                ▼                        ▼
┌──────────────────────────────┐  ┌──────────────────────┐
│  FSM Supervisor Orchestrator │  │ SQLite WAL Database  │
│  ├── Tenant Agent            │  │ ├── Society Bylaws   │
│  ├── Owner Agent             │  │ ├── Resident Registry│
│  └── Admin Agent             │  │ ├── Lift Lock Mutex  │
└───────────────┬──────────────┘  │ └── Gate Passes      │
                │                 └──────────────────────┘
                ▼
┌────────────────────────────────────────────────────────┐
│           Model Context Protocol (MCP) Registry        │
│  eval_shift_bylaws        reserve_service_lift         │
│  verify_dues_and_fees     submit_owner_noc             │
│  generate_gate_pass       validate_gate_pass_at_security│
│  sync_resident_directory  update_society_bylaws        │
└────────────────────────────────────────────────────────┘
```

### Key Tradeoffs & Decisions

| Decision | Chosen Approach | Alternative Considered | Rationale |
|---|---|---|---|
| **Coordination** | Deterministic Finite State Machine (FSM) | Freeform Multi-Agent Chat | Freeform agent chatter risks hallucinated approvals and infinite loops. An FSM guarantees strict, predictable business state transitions. |
| **Tool Interface** | Model Context Protocol (MCP) | Direct database queries in prompt | MCP decouples agent reasoning from data structures and enforces strict Role-Based Access Control (RBAC). |
| **Concurrency** | SQLite WAL + Python `asyncio.Lock` | Redis / RabbitMQ / Celery | An MVP does not need distributed queue infrastructure. SQLite WAL with an async in-process lock handles concurrent elevator holds cleanly without operational overhead. |
| **Frontend** | Single-Process Vanilla JS + Tailwind CDN | React / Next.js with npm build | Avoids Node.js dependencies, dual development servers, and packaging bloat. The application runs immediately with a single Python command. |
| **AI Inference** | Gemini 2.0 Flash with local fallback | Local LLM (Ollama) or Pro models | Gemini 2.0 Flash offers sub-second latency and zero cost on the free tier. The offline deterministic fallback ensures the system functions even without an active internet connection. |

---

## Layer 4: Implementation Details (for engineers)

### 1. Elevator Slot Concurrency with Lazy TTL

Elevator double-booking is prevented using an in-memory lock combined with database lazy-TTL queries in `src/database.py`:

```python
_lift_lock = asyncio.Lock()

async def reserve_lift_slot(request_id: str, tower: str, shift_date: str, slot_window: str):
    async with _lift_lock:
        async with get_db() as db:
            # Lazy expiration: slots held longer than 15 mins are treated as free
            query = """
                SELECT id FROM lift_reservations
                WHERE tower = ? AND shift_date = ? AND slot_window = ?
                  AND (status = 'CONFIRMED' OR (status = 'HELD' AND hold_expires_at > CURRENT_TIMESTAMP))
            """
            cursor = await db.execute(query, (tower, shift_date, slot_window))
            if await cursor.fetchone():
                return {"success": False, "reason": "Elevator already booked for this slot"}
            
            # Insert 15-minute reservation hold
            ...
```

### 2. MCP Tool Registry & RBAC Dispatcher

Tools defined in `src/mcp/tools.py` enforce strict Role-Based Access Control. A Tenant Agent cannot invoke `submit_owner_noc` or `generate_gate_pass`:

```python
MCP_ROLE_PERMISSIONS = {
    "TENANT": ["eval_shift_bylaws", "reserve_service_lift"],
    "OWNER": ["verify_dues_and_fees", "submit_owner_noc"],
    "ADMIN": ["eval_shift_bylaws", "reserve_service_lift", "verify_dues_and_fees", 
              "submit_owner_noc", "generate_gate_pass", "sync_resident_directory", 
              "update_society_bylaws"],
    "SECURITY": ["validate_gate_pass_at_security"]
}
```

### 3. Environment & Configuration

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | None (triggers fallback) | Google Gemini API key for live inference |
| `GOOGLE_API_KEY` | None (triggers fallback) | Alternative Google API key name |
| `PROP_AGENT_DB` | `data.db` | Path to SQLite database file |

### 4. Known Edge Cases Handled

- **Sunday Curfew**: Bylaw evaluation automatically checks day-of-week strings and rejects weekend curfew violations before reserving resources.
- **Abandoned Requests**: A reservation hold automatically expires after 15 minutes via SQLite `CURRENT_TIMESTAMP` comparisons without requiring background cron worker threads.
- **Tenant vs Owner Occupancy**: Directory updates distinguish between owner-occupiers (`OCCUPIED_OWNER`) and tenants (`OCCUPIED_TENANT`), ensuring flat ownership records remain intact when tenants move out.

---

## Layer 5: Extending This Project

### Adding a New Workflow (e.g. Renovation / Interior Work Permits)
1. Add an `INTERIOR_WORK` shift request type to `src/database.py`.
2. Implement an MCP tool `issue_debris_clearance_permit()` in `src/mcp/tools.py` with the appropriate schema.
3. Grant permissions in `MCP_ROLE_PERMISSIONS` and add the state transition into `src/agents/orchestrator.py`.

### Swapping the LLM Provider
- The `GeminiClient` in `src/agents/gemini_client.py` uses standard JSON function calling semantics. To swap to an alternative model provider, implement a matching `generate_content()` signature yielding `{"text": ..., "tool_calls": [...]}`.

### Scaling to 10x (100,000 Flats across Multiple Societies)
1. **Database**: Swap `aiosqlite` with PostgreSQL using connection pooling (`asyncpg`). The SQL queries and table schemas translate directly.
2. **Elevator Locks**: Replace the Python in-process `asyncio.Lock` with Redis distributed locks (`Redlock`) using key format `lock:lift:{society_id}:{tower}:{date}:{slot}`.
3. **Event Broker**: Decouple the FSM orchestrator using Celery or Kafka so approvals and webhooks process asynchronously across background worker nodes.
