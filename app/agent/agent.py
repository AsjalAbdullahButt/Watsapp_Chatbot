"""Agent loop: ask the model, run only registered tools, answer from verified results."""

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field

from app.agent.prompts import FALLBACK_INCOMPLETE, FALLBACK_UNAVAILABLE, PROMPT_VERSION, SYSTEM_PROMPT
from app.core.errors import ProviderUnavailable
from app.data.source import BusinessDataSource
from app.llm.base import LLMProvider, Message
from app.tools.registry import ToolContext, ToolRegistry

log = logging.getLogger("agent")

MAX_INBOUND_CHARS = 1000


@dataclass
class ToolTrace:
    tool: str
    arguments: str
    status: str


@dataclass
class AgentReply:
    text: str
    tools: list[ToolTrace] = field(default_factory=list)
    fallback: bool = False


class ConversationMemory:
    """Bounded in-process history per phone. Replace with Redis + SQL in the full build."""

    def __init__(self, max_messages: int) -> None:
        self._store: dict[str, deque[Message]] = defaultdict(lambda: deque(maxlen=max_messages))

    def history(self, phone: str) -> list[Message]:
        return list(self._store[phone])

    def add(self, phone: str, role: str, content: str) -> None:
        self._store[phone].append({"role": role, "content": content})


class Agent:
    def __init__(
        self,
        llm: LLMProvider,
        registry: ToolRegistry,
        source: BusinessDataSource,
        memory: ConversationMemory,
        max_tool_steps: int,
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._source = source
        self._memory = memory
        self._max_steps = max_tool_steps

    async def reply(self, phone: str, text: str) -> AgentReply:
        text = text.strip()[:MAX_INBOUND_CHARS]
        ctx = ToolContext(phone=phone, customer=self._source.find_customer_by_phone(phone))
        messages: list[Message] = [
            {"role": "system", "content": SYSTEM_PROMPT + self._customer_note(ctx)},
            *self._memory.history(phone),
            {"role": "user", "content": text},
        ]
        traces: list[ToolTrace] = []

        try:
            for step in range(self._max_steps + 1):
                tools = self._registry.schemas() if step < self._max_steps else []
                response = await self._llm.chat(messages, tools)
                if not response.tool_calls:
                    answer = (response.content or "").strip()
                    if not answer:
                        break
                    self._remember(phone, text, answer)
                    log.info("agent_reply", extra={"data": {"steps": step, "tools": [t.tool for t in traces], "prompt": PROMPT_VERSION}})
                    return AgentReply(answer, traces)

                messages.append({
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": [
                        {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                        for c in response.tool_calls
                    ],
                })
                for call in response.tool_calls:
                    result = self._registry.execute(call.name, call.arguments, ctx)
                    traces.append(ToolTrace(call.name, call.arguments, result.status.value))
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": result.to_model_payload()})
        except ProviderUnavailable:
            log.warning("agent_provider_unavailable")
            return AgentReply(FALLBACK_UNAVAILABLE, traces, fallback=True)

        log.warning("agent_incomplete", extra={"data": {"tools": [t.tool for t in traces]}})
        return AgentReply(FALLBACK_INCOMPLETE, traces, fallback=True)

    def _remember(self, phone: str, user_text: str, answer: str) -> None:
        self._memory.add(phone, "user", user_text)
        self._memory.add(phone, "assistant", answer)

    @staticmethod
    def _customer_note(ctx: ToolContext) -> str:
        if ctx.customer is None:
            return "\nThis number is not linked to a customer account; order lookups will not work."
        return f"\nThe customer's first name is {ctx.customer.name.split()[0]}."
