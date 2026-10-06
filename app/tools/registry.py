"""Strict tool registry.

The model can only reach code through this class. Every call is checked in order:
tool exists -> tool enabled -> arguments match schema -> handler runs with a
backend-built context (never model-supplied identity) -> result is recorded.
"""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ValidationError

from app.data.source import Customer

log = logging.getLogger("tools")


class ToolStatus(StrEnum):
    OK = "OK"
    NOT_FOUND = "NOT_FOUND"
    CUSTOMER_NOT_LINKED = "CUSTOMER_NOT_LINKED"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    TOOL_DISABLED = "TOOL_DISABLED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


@dataclass(frozen=True)
class ToolContext:
    """Identity comes from the WhatsApp sender, resolved by the backend."""

    phone: str
    customer: Customer | None


@dataclass
class ToolResult:
    status: ToolStatus
    data: Any = None
    message: str = ""

    def to_model_payload(self) -> str:
        return json.dumps(
            {"status": self.status.value, "data": self.data, "message": self.message},
            ensure_ascii=False,
        )


Handler = Callable[[Any, ToolContext], ToolResult]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Handler


@dataclass
class ToolRegistry:
    tools: dict[str, Tool] = field(default_factory=dict)
    disabled: set[str] = field(default_factory=set)

    def register(self, tool: Tool) -> None:
        if tool.name in self.tools:
            raise ValueError(f"duplicate tool name: {tool.name}")
        self.tools[tool.name] = tool

    def set_enabled(self, name: str, enabled: bool) -> None:
        if name not in self.tools:
            raise KeyError(name)
        (self.disabled.discard if enabled else self.disabled.add)(name)

    def schemas(self) -> list[dict[str, Any]]:
        """Only enabled tools are ever shown to the model."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.args_model.model_json_schema(),
                },
            }
            for t in self.tools.values()
            if t.name not in self.disabled
        ]

    def execute(self, name: str, raw_arguments: str, ctx: ToolContext) -> ToolResult:
        started = time.perf_counter()
        result = self._run(name, raw_arguments, ctx)
        log.info(
            "tool_call",
            extra={
                "data": {
                    "tool": name,
                    "status": result.status.value,
                    "customer_id": ctx.customer.customer_id if ctx.customer else None,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                }
            },
        )
        return result

    def _run(self, name: str, raw_arguments: str, ctx: ToolContext) -> ToolResult:
        tool = self.tools.get(name)
        if tool is None:
            return ToolResult(ToolStatus.UNKNOWN_TOOL, message=f"No tool named '{name}' exists. Do not retry it.")
        if name in self.disabled:
            return ToolResult(ToolStatus.TOOL_DISABLED, message="This capability is currently unavailable.")
        try:
            args = tool.args_model.model_validate_json(raw_arguments or "{}")
        except ValidationError as exc:
            fields = sorted({".".join(str(p) for p in e["loc"]) or "arguments" for e in exc.errors()})
            return ToolResult(ToolStatus.INVALID_ARGUMENTS, message=f"Invalid arguments: {', '.join(fields)}")
        return tool.handler(args, ctx)
