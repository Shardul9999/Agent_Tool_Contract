from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict

from contract import (
    ErrorCode,
    InspectDocumentData,
    InspectDocumentInput,
    LineEntry,
    ToolResult,
)


class DocumentInspectorTool:
    def __init__(self, sandbox_root: Path | str):
        self.sandbox_root = Path(sandbox_root).resolve()

    def _resolve_safe_path(self, relative_path: str) -> Path:
        clean_rel = relative_path.lstrip("/\\")
        candidate = (self.sandbox_root / clean_rel).resolve()

        if not candidate.is_relative_to(self.sandbox_root):
            raise PermissionError(
                f"Access denied: path '{relative_path}' traverses outside the sandbox root."
            )
        return candidate

    def execute(self, raw_args: Dict[str, Any]) -> ToolResult:
        start_time = time.perf_counter()
        tool_name = "inspect_document"

        try:
            validated_input = InspectDocumentInput(**raw_args)
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            return ToolResult.fail(
                tool_name=tool_name,
                code=ErrorCode.MALFORMED_ARGUMENTS,
                message="Input validation failed against schema.",
                latency_ms=latency_ms,
                details={"errors": str(e)},
            )

        try:
            target_file = self._resolve_safe_path(validated_input.file_path)
        except PermissionError as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            return ToolResult.fail(
                tool_name=tool_name,
                code=ErrorCode.PERMISSION_DENIED,
                message=str(e),
                latency_ms=latency_ms,
                details={"attempted_path": validated_input.file_path},
            )

        if not target_file.is_file():
            latency_ms = (time.perf_counter() - start_time) * 1000
            return ToolResult.fail(
                tool_name=tool_name,
                code=ErrorCode.RESOURCE_NOT_FOUND,
                message=f"File not found: '{validated_input.file_path}'",
                latency_ms=latency_ms,
                details={"resolved_path": str(target_file)},
            )

        try:
            with open(target_file, "r", encoding="utf-8", errors="replace") as f:
                raw_lines = f.readlines()

            bytes_read = sum(len(line.encode("utf-8")) for line in raw_lines)

            matched_entries: list[LineEntry] = []
            if validated_input.query:
                query_lower = validated_input.query.lower()
            else:
                query_lower = None

            for idx, line in enumerate(raw_lines, start=1):
                clean_text = line.rstrip("\r\n")
                if query_lower is None or query_lower in clean_text.lower():
                    matched_entries.append(
                        LineEntry(line_number=idx, content=clean_text)
                    )

            total_matches = len(matched_entries)

            start_idx = validated_input.offset
            end_idx = start_idx + validated_input.max_lines
            page_slice = matched_entries[start_idx:end_idx]

            has_more = end_idx < total_matches
            next_offset = end_idx if has_more else None

            data = InspectDocumentData(
                file_path=validated_input.file_path,
                lines=page_slice,
                total_matches=total_matches,
                has_more=has_more,
                next_offset=next_offset,
            )

            latency_ms = (time.perf_counter() - start_time) * 1000
            return ToolResult.success(
                tool_name=tool_name,
                data=data,
                latency_ms=latency_ms,
                bytes_read=bytes_read,
            )

        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            return ToolResult.fail(
                tool_name=tool_name,
                code=ErrorCode.INTERNAL_ERROR,
                message=f"Error reading file: {str(e)}",
                latency_ms=latency_ms,
            )
