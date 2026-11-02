import time
from pathlib import Path
from contract import ErrorCode, ToolResult
from tools import DocumentInspectorTool
from agent_loop import BoundedAgentLoop, ToolCall


class MockHangingTool:
    def __init__(self, delay_seconds: float = 2.0):
        self.delay_seconds = delay_seconds

    def execute(self, raw_args: dict) -> ToolResult:
        time.sleep(self.delay_seconds)
        return ToolResult.fail(
            tool_name="slow_service",
            code=ErrorCode.INTERNAL_ERROR,
            message="Slow query completed after delay.",
        )


def run_all_scenarios():
    sandbox_dir = Path(__file__).parent / "sandbox"
    sandbox_dir.mkdir(exist_ok=True)
    sample_file = sandbox_dir / "service.log"

    print("=" * 70)
    print("AGENT TOOL CONTRACT DEMONSTRATION")
    print("Phase 3 / Week 18 — Tool Design & Agent Orchestration")
    print(f"Sandbox Root: {sandbox_dir.resolve()}")
    print("=" * 70)

    loop = BoundedAgentLoop(
        max_steps=6,
        step_timeout_seconds=0.6,
        detect_duplicates=True,
    )
    doc_tool = DocumentInspectorTool(sandbox_root=sandbox_dir)
    slow_tool = MockHangingTool(delay_seconds=1.5)

    loop.register_tool("inspect_document", doc_tool)
    loop.register_tool("slow_service", slow_tool)

    scenarios = [
        (
            "Scenario 1: Successful Execution (Filter 'ERROR')",
            ToolCall(
                tool_name="inspect_document",
                arguments={"file_path": "service.log", "query": "ERROR", "max_lines": 5},
            ),
        ),
        (
            "Scenario 2: Malformed Arguments (max_lines > 200)",
            ToolCall(
                tool_name="inspect_document",
                arguments={"file_path": "service.log", "max_lines": 999},
            ),
        ),
        (
            "Scenario 3: Unknown Tool (unregistered action)",
            ToolCall(
                tool_name="delete_database_cluster",
                arguments={"force": True},
            ),
        ),
        (
            "Scenario 4: Timeout Protection (hanging call > 0.6s)",
            ToolCall(
                tool_name="slow_service",
                arguments={"simulate_delay": 1.5},
            ),
        ),
        (
            "Scenario 5: Duplicate Call Detection (repeating Scenario 1)",
            ToolCall(
                tool_name="inspect_document",
                arguments={"file_path": "service.log", "query": "ERROR", "max_lines": 5},
            ),
        ),
        (
            "Scenario 6: Authorization Denial (Path Traversal '../../etc/passwd')",
            ToolCall(
                tool_name="inspect_document",
                arguments={"file_path": "../../etc/passwd"},
            ),
        ),
        (
            "Scenario 7: Step-Budget Exhaustion (Exceeding max_steps=6)",
            ToolCall(
                tool_name="inspect_document",
                arguments={"file_path": "service.log", "offset": 1},
            ),
        ),
    ]

    for title, call in scenarios:
        print(f"\n>>> Running {title}...")
        res = loop.execute_step(call)
        status_label = "SUCCESS" if res.status == "success" else f"ERROR ({res.error.code.value})"
        print(f"    Status : {status_label}")
        if res.error:
            print(f"    Message: {res.error.message}")
            if res.error.details:
                print(f"    Details: {res.error.details}")
        elif res.data:
            print(f"    Matches: {res.data.total_matches} (Returned {len(res.data.lines)} lines)")
            for line in res.data.lines[:2]:
                print(f"      L{line.line_number}: {line.content}")
        print(f"    Latency: {res.meta.latency_ms:.2f} ms")

    loop.print_audit_trail()


if __name__ == "__main__":
    run_all_scenarios()
