from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


class ErrorCode(str, Enum):
    MALFORMED_ARGUMENTS = "MALFORMED_ARGUMENTS"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    TIMEOUT = "TIMEOUT"
    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    DUPLICATE_CALL = "DUPLICATE_CALL"
    STEP_BUDGET_EXHAUSTED = "STEP_BUDGET_EXHAUSTED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class InspectDocumentInput(BaseModel):
    file_path: str = Field(
        ...,
        min_length=1,
        description="Relative path of the target file inside the sandbox root.",
    )
    query: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Optional case-insensitive substring to filter lines.",
    )
    max_lines: int = Field(
        default=50,
        ge=1,
        le=200,
        description="Maximum lines to return per call (1 to 200).",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Line offset for pagination (0-indexed).",
    )

    @field_validator("file_path")
    @classmethod
    def reject_empty_or_whitespace(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("file_path cannot be empty or whitespace.")
        return cleaned


class LineEntry(BaseModel):
    line_number: int
    content: str


class InspectDocumentData(BaseModel):
    file_path: str
    lines: List[LineEntry]
    total_matches: int
    has_more: bool
    next_offset: Optional[int]


class ExecutionMeta(BaseModel):
    tool_name: str
    latency_ms: float
    bytes_read: int = 0


class ToolError(BaseModel):
    code: ErrorCode
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    status: Literal["success", "error"]
    data: Optional[InspectDocumentData] = None
    error: Optional[ToolError] = None
    meta: ExecutionMeta

    @classmethod
    def success(
        cls,
        tool_name: str,
        data: InspectDocumentData,
        latency_ms: float,
        bytes_read: int = 0,
    ) -> "ToolResult":
        return cls(
            status="success",
            data=data,
            error=None,
            meta=ExecutionMeta(
                tool_name=tool_name,
                latency_ms=round(latency_ms, 2),
                bytes_read=bytes_read,
            ),
        )

    @classmethod
    def fail(
        cls,
        tool_name: str,
        code: ErrorCode,
        message: str,
        latency_ms: float = 0.0,
        details: Optional[Dict[str, Any]] = None,
    ) -> "ToolResult":
        return cls(
            status="error",
            data=None,
            error=ToolError(code=code, message=message, details=details or {}),
            meta=ExecutionMeta(
                tool_name=tool_name,
                latency_ms=round(latency_ms, 2),
                bytes_read=0,
            ),
        )
