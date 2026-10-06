"""Groq implementation of LLMProvider (OpenAI-compatible chat completions API)."""

import asyncio
import logging
from typing import Any

import httpx

from app.core.errors import ProviderUnavailable
from app.llm.base import LLMProvider, LLMResponse, Message, ToolCall

log = logging.getLogger("llm.groq")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(self, api_key: str, model: str, timeout: float, max_retries: int) -> None:
        if not api_key:
            raise ValueError("GROQ_API_KEY is not set")
        self._model = model
        self._max_retries = max_retries
        self._client = httpx.AsyncClient(
            timeout=timeout, headers={"Authorization": f"Bearer {api_key}"}
        )

    async def chat(self, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse:
        body: dict[str, Any] = {"model": self._model, "messages": messages, "temperature": 0.2}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        # Generating a reply has no side effects, so bounded retries are safe here.
        # Tool execution happens outside this call and is never repeated by it.
        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._client.post(GROQ_URL, json=body)
            except httpx.TransportError as exc:
                log.warning("groq_transport_error", extra={"data": {"attempt": attempt, "error": type(exc).__name__}})
            else:
                if resp.status_code == 200:
                    return self._parse(resp.json())
                if resp.status_code not in _RETRYABLE_STATUS:
                    log.error("groq_rejected", extra={"data": {"status": resp.status_code, "body": resp.text[:300]}})
                    raise ProviderUnavailable(f"Groq returned {resp.status_code}")
                log.warning("groq_retryable", extra={"data": {"attempt": attempt, "status": resp.status_code}})
            if attempt < self._max_retries:
                await asyncio.sleep(0.5 * 2**attempt)
        raise ProviderUnavailable("Groq unavailable after retries")

    def _parse(self, payload: dict[str, Any]) -> LLMResponse:
        message = payload["choices"][0]["message"]
        calls = [
            ToolCall(id=c["id"], name=c["function"]["name"], arguments=c["function"].get("arguments") or "{}")
            for c in message.get("tool_calls") or []
        ]
        return LLMResponse(content=message.get("content"), tool_calls=calls, model=payload.get("model", self._model))

    async def aclose(self) -> None:
        await self._client.aclose()
