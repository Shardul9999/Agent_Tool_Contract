# Tool Contract & Bounded Agent Orchestration: `inspect_document`

> **Phase 3 / Week 18:** AI Agents, Tool Use & Orchestration  
> **Study Plan:** Day 001 — AI Foundations Section  
> **Repository / Standalone Project:** `agent_tool_contract`

---

## 1. Purpose
Provides an AI agent with bounded, read-only inspection and keyword searching of text and log files within a strictly authorized sandbox folder.

## 2. Permissions and Security Policy
- **Read-Only**: Zero write, delete, or modify permissions.
- **Strict Sandbox**: All paths resolve inside `allowed_root_dir`. Traversal attacks (`../`) and external symlinks are strictly rejected.
- **Bounded Ingestion**: Hard limit of maximum 200 lines per call to protect the LLM context window from blowing up.

## 3. Input Schema
- `file_path` (string, required): Relative path inside sandbox. Must not be empty or whitespace.
- `query` (string, optional): Case-insensitive substring filter.
- `max_lines` (int, default=50, min=1, max=200): Maximum lines returned per call.
- `offset` (int, default=0, min=0): Line offset for pagination (0-indexed).

## 4. Result Envelopes
- **Success Envelope**:
  - `status`: `"success"`
  - `data`: `{ file_path, lines: [{line_number, content}], total_matches, has_more, next_offset }`
  - `meta`: `{ tool_name, latency_ms, bytes_read }`

- **Error Envelope**:
  - `status`: `"error"`
  - `error`: `{ code, message, details }`
  - `meta`: `{ tool_name, latency_ms, bytes_read }`

## 5. Three Primary Failure Cases
1. `PERMISSION_DENIED`: Path attempts to escape sandbox root (e.g. `../../etc/passwd`).
2. `MALFORMED_ARGUMENTS`: Invalid parameters (e.g. missing `file_path` or `max_lines = 999` or `offset = -1`).
3. `RESOURCE_NOT_FOUND`: Target file does not exist within the sandbox.

---

## 6. Architecture & Core Files

- [`contract.py`](file:///home/ssh/Documents/agent_tool_contract/contract.py): Pydantic v2 data models for input validation (`InspectDocumentInput`), pagination payloads (`InspectDocumentData`), execution metadata (`ExecutionMeta`), error envelopes (`ToolError`), and standard error codes (`ErrorCode` enum).
- [`tools.py`](file:///home/ssh/Documents/agent_tool_contract/tools.py): Implementation of `DocumentInspectorTool` with canonical path resolution (`is_relative_to`), encoding fallback, substring filtering, and windowed pagination.
- [`agent_loop.py`](file:///home/ssh/Documents/agent_tool_contract/agent_loop.py): `BoundedAgentLoop` orchestrator enforcing:
  - Step budget exhaustion checks (`max_steps`)
  - Duplicate tool call detection via deterministic argument fingerprinting
  - Preemptive timeouts via non-blocking thread execution
  - Audit trail history (`StepRecord`)
- [`run_scenarios.py`](file:///home/ssh/Documents/agent_tool_contract/run_scenarios.py): Runnable script demonstrating the 7 core curriculum scenarios.
- [`test_agent_contract.py`](file:///home/ssh/Documents/agent_tool_contract/test_agent_contract.py): Comprehensive `unittest` test suite covering schema, sandbox boundaries, timeouts, and orchestrator limits.

---

## 7. Demonstration Scenarios (Phase 3 Week 18 Requirements)

| # | Scenario | Trigger / Input | Expected Result Envelope |
|---|----------|-----------------|--------------------------|
| 1 | **Successful Execution** | `file_path="service.log", query="ERROR", max_lines=5` | `status="success"`, filtered lines, total matches, pagination metadata |
| 2 | **Malformed Arguments** | `max_lines=999` (> 200 limit) | `status="error"`, `code="MALFORMED_ARGUMENTS"` |
| 3 | **Unknown Tool** | Tool `delete_database_cluster` | `status="error"`, `code="UNKNOWN_TOOL"` |
| 4 | **Timeout Protection** | Hanging task > 0.6s step timeout | `status="error"`, `code="TIMEOUT"` |
| 5 | **Duplicate Call** | Repeating identical tool call arguments | `status="error"`, `code="DUPLICATE_CALL"` |
| 6 | **Authorization Denial** | `file_path="../../etc/passwd"` | `status="error"`, `code="PERMISSION_DENIED"` |
| 7 | **Step-Budget Exhaustion**| Exceeding `max_steps=6` | `status="error"`, `code="STEP_BUDGET_EXHAUSTED"` |

---

## 8. Running the Code

### Run the Interactive Scenario Demonstration:
```bash
python3 run_scenarios.py
```

### Run Unit Tests:
```bash
python3 test_agent_contract.py
```

---

## 9. Evaluation & Curriculum Notes (Day 1 Finishing Check)

- **Observed Result**: All 7 failure and success modes are handled deterministically at the orchestrator level, ensuring the agent runtime never crashes, never leaks host files, and cannot loop infinitely.
- **One Limitation**: Line-based streaming and regex queries are memory-bound if scanning multi-gigabyte log files. Production agents require block/chunk streaming or external indexing (e.g. Elasticsearch/ripgrep).
- **Design Tradeoff**: We chose an isolated sandbox directory model with path resolution rather than full OS containerization (Docker) to keep latency low (<1ms) for local agent inspections while still guaranteeing path containment.
