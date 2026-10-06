"""Provider-neutral LLM contract. Business code depends on this, never on Groq types."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

# Messages use the widely supported chat format:
# {"role": "system"|"user"|"assistant"|"tool", "content": ..., "tool_calls"?: [...], "tool_call_id"?: ...}
Message = dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON text from the model; validated by the registry


@dataclass(frozen=True)
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def chat(self, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse:
        """Return the model's next step. Raise ProviderUnavailable on outage."""
