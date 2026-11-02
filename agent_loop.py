from __future__ import annotations

import concurrent.futures
import json
import time
from typing import Any, Dict, List
from pydantic import BaseModel, Field

from contract import ErrorCode, ToolResult


class ToolCall(BaseModel):
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)

    def fingerprint(self) -> str:
        serialized_args = json.dumps(self.arguments, sort_keys=True)
        return f"{self.tool_name}:{serialized_args}"


class StepRecord(BaseModel):
    step_number: int
    call: ToolCall
    result: ToolResult
    timestamp: float


class BoundedAgentLoop:
    def __init__(
        self,
        max_steps: int = 5,
        step_timeout_seconds: float = 2.0,
        detect_duplicates: bool = True,
    ):
        self.max_steps = max_steps
        self.step_timeout_seconds = step_timeout_seconds
        self.detect_duplicates = detect_duplicates

        self.registry: Dict[str, Any] = {}
        self.history: List[StepRecord] = []
        self._seen_calls: set[str] = set()
        self.current_step: int = 0

    def register_tool(self, name: str, tool_instance: Any) -> None:
        self.registry[name] = tool_instance

    def execute_step(self, call: ToolCall) -> ToolResult:
        self.current_step += 1
        step_num = self.current_step
        start_time = time.perf_counter()

        if step_num > self.max_steps:
            result = ToolResult.fail(
                tool_name=call.tool_name,
                code=ErrorCode.STEP_BUDGET_EXHAUSTED,
                message=f"Agent exceeded maximum step budget of {self.max_steps} steps.",
                details={"step": step_num, "max_steps": self.max_steps},
            )
            self._record_step(step_num, call, result)
            return result

        if call.tool_name not in self.registry:
            latency_ms = (time.perf_counter() - start_time) * 1000
            result = ToolResult.fail(
                tool_name=call.tool_name,
                code=ErrorCode.UNKNOWN_TOOL,
                message=f"Tool '{call.tool_name}' is not registered.",
                latency_ms=latency_ms,
                details={"available_tools": list(self.registry.keys())},
            )
            self._record_step(step_num, call, result)
            return result

        fp = call.fingerprint()
        if self.detect_duplicates and fp in self._seen_calls:
            latency_ms = (time.perf_counter() - start_time) * 1000
            result = ToolResult.fail(
                tool_name=call.tool_name,
                code=ErrorCode.DUPLICATE_CALL,
                message="Duplicate tool call detected with identical arguments.",
                latency_ms=latency_ms,
                details={"fingerprint": fp},
            )
            self._record_step(step_num, call, result)
            return result

        self._seen_calls.add(fp)

        tool = self.registry[call.tool_name]
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(tool.execute, call.arguments)
            result = future.result(timeout=self.step_timeout_seconds)
            executor.shutdown(wait=False)
        except concurrent.futures.TimeoutError:
            executor.shutdown(wait=False, cancel_futures=True)
            latency_ms = (time.perf_counter() - start_time) * 1000
            result = ToolResult.fail(
                tool_name=call.tool_name,
                code=ErrorCode.TIMEOUT,
                message=f"Tool execution timed out after {self.step_timeout_seconds}s.",
                latency_ms=latency_ms,
            )
        except Exception as e:
            executor.shutdown(wait=False)
            latency_ms = (time.perf_counter() - start_time) * 1000
            result = ToolResult.fail(
                tool_name=call.tool_name,
                code=ErrorCode.INTERNAL_ERROR,
                message=f"Unexpected error in agent loop: {str(e)}",
                latency_ms=latency_ms,
            )

        self._record_step(step_num, call, result)
        return result

    def _record_step(self, step_number: int, call: ToolCall, result: ToolResult) -> None:
        self.history.append(
            StepRecord(
                step_number=step_number,
                call=call,
                result=result,
                timestamp=time.time(),
            )
        )

    def print_audit_trail(self) -> None:
        print(f"\n{'=' * 60}\nAGENT AUDIT TRAIL (Total Steps: {len(self.history)})\n{'=' * 60}")
        for record in self.history:
            status_symbol = "✓" if record.result.status == "success" else "✗"
            print(
                f"Step {record.step_number} "
                f"[{status_symbol} {record.result.status.upper()}]: {record.call.tool_name}"
            )
            if record.result.status == "error" and record.result.error:
                print(f"   Code   : {record.result.error.code.value}")
                print(f"   Message: {record.result.error.message}")
            elif record.result.data:
                print(f"   File   : {record.result.data.file_path}")
                print(
                    f"   Matches: {record.result.data.total_matches} "
                    f"(Returned: {len(record.result.data.lines)})"
                )
            print(f"   Latency: {record.result.meta.latency_ms:.2f} ms\n")
