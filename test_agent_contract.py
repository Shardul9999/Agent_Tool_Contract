import time
import unittest
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
            tool_name="slow_tool",
            code=ErrorCode.INTERNAL_ERROR,
            message="Completed after delay",
        )


class TestAgentToolContract(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.sandbox_dir = Path(__file__).parent / "sandbox"
        cls.sandbox_dir.mkdir(exist_ok=True)
        cls.sample_log = cls.sandbox_dir / "service.log"
        if not cls.sample_log.exists():
            cls.sample_log.write_text(
                "2026-11-02 10:00:01 INFO [main] Server starting\n"
                "2026-11-02 10:02:30 WARN [cache] Redis miss\n"
                "2026-11-02 10:03:10 ERROR [payment] Signature failed\n"
                "2026-11-02 10:05:22 ERROR [worker] Task failed\n"
                "2026-11-02 10:06:00 INFO [http] GET /api 200 OK\n"
            )

    def setUp(self):
        self.tool = DocumentInspectorTool(sandbox_root=self.sandbox_dir)
        self.loop = BoundedAgentLoop(
            max_steps=4,
            step_timeout_seconds=0.5,
            detect_duplicates=True,
        )
        self.loop.register_tool("inspect_document", self.tool)

    def test_scenario_1_successful_execution(self):
        call = ToolCall(
            tool_name="inspect_document",
            arguments={"file_path": "service.log", "query": "ERROR", "max_lines": 10},
        )
        result = self.loop.execute_step(call)

        self.assertEqual(result.status, "success")
        self.assertIsNotNone(result.data)
        self.assertIsNone(result.error)
        self.assertEqual(result.data.total_matches, 2)
        self.assertEqual(len(result.data.lines), 2)
        self.assertTrue(all("ERROR" in line.content for line in result.data.lines))
        self.assertGreaterEqual(result.meta.bytes_read, 1)
        self.assertGreater(result.meta.latency_ms, 0)

    def test_scenario_2_malformed_arguments(self):
        call_invalid_max = ToolCall(
            tool_name="inspect_document",
            arguments={"file_path": "service.log", "max_lines": 500},
        )
        result = self.loop.execute_step(call_invalid_max)
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error.code, ErrorCode.MALFORMED_ARGUMENTS)

        call_empty_path = ToolCall(
            tool_name="inspect_document",
            arguments={"file_path": "   "},
        )
        result2 = self.loop.execute_step(call_empty_path)
        self.assertEqual(result2.status, "error")
        self.assertEqual(result2.error.code, ErrorCode.MALFORMED_ARGUMENTS)

    def test_scenario_3_unknown_tool(self):
        call = ToolCall(
            tool_name="execute_bash_command",
            arguments={"cmd": "whoami"},
        )
        result = self.loop.execute_step(call)
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error.code, ErrorCode.UNKNOWN_TOOL)
        self.assertIn("execute_bash_command", result.error.message)
        self.assertIn("inspect_document", result.error.details["available_tools"])

    def test_scenario_4_timeout_protection(self):
        hanging_tool = MockHangingTool(delay_seconds=1.5)
        self.loop.register_tool("slow_tool", hanging_tool)

        call = ToolCall(tool_name="slow_tool", arguments={})
        start = time.perf_counter()
        result = self.loop.execute_step(call)
        elapsed = time.perf_counter() - start

        self.assertEqual(result.status, "error")
        self.assertEqual(result.error.code, ErrorCode.TIMEOUT)
        self.assertLess(elapsed, 1.2)
        self.assertIn("timed out", result.error.message)

    def test_scenario_5_duplicate_call_detection(self):
        call = ToolCall(
            tool_name="inspect_document",
            arguments={"file_path": "service.log", "query": "WARN"},
        )
        res1 = self.loop.execute_step(call)
        self.assertEqual(res1.status, "success")

        res2 = self.loop.execute_step(call)
        self.assertEqual(res2.status, "error")
        self.assertEqual(res2.error.code, ErrorCode.DUPLICATE_CALL)

    def test_scenario_6_authorization_denial(self):
        traversal_attempts = [
            "../../etc/passwd",
            "../contract.py",
            "../../../../etc/shadow",
        ]
        for path in traversal_attempts:
            call = ToolCall(
                tool_name="inspect_document",
                arguments={"file_path": path},
            )
            result = self.loop.execute_step(call)
            self.assertEqual(result.status, "error")
            self.assertEqual(result.error.code, ErrorCode.PERMISSION_DENIED)
            self.assertIn("Access denied", result.error.message)

    def test_scenario_7_step_budget_exhaustion(self):
        for i in range(4):
            call = ToolCall(
                tool_name="inspect_document",
                arguments={"file_path": "service.log", "offset": i},
            )
            res = self.loop.execute_step(call)
            self.assertEqual(res.status, "success")

        call_step_5 = ToolCall(
            tool_name="inspect_document",
            arguments={"file_path": "service.log", "offset": 10},
        )
        res5 = self.loop.execute_step(call_step_5)
        self.assertEqual(res5.status, "error")
        self.assertEqual(res5.error.code, ErrorCode.STEP_BUDGET_EXHAUSTED)
        self.assertIn("exceeded maximum step budget", res5.error.message)

    def test_resource_not_found(self):
        call = ToolCall(
            tool_name="inspect_document",
            arguments={"file_path": "non_existent_file.log"},
        )
        result = self.loop.execute_step(call)
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error.code, ErrorCode.RESOURCE_NOT_FOUND)

    def test_pagination_bounds(self):
        call = ToolCall(
            tool_name="inspect_document",
            arguments={"file_path": "service.log", "max_lines": 2, "offset": 0},
        )
        result = self.loop.execute_step(call)
        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.data.lines), 2)
        self.assertTrue(result.data.has_more)
        self.assertEqual(result.data.next_offset, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
