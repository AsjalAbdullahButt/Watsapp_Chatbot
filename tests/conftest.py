import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import ProviderUnavailable
from app.core.security import sign_body
from app.llm.base import LLMProvider, LLMResponse, Message, ToolCall
from app.main import create_app

ROOT = Path(__file__).resolve().parents[1]
SECRET = "test-app-secret"
VERIFY = "test-verify-token"
ALI = "923001234567"
SANA = "923217654321"


class ScriptedLLM(LLMProvider):
    """Returns pre-set responses in order and records what it was sent."""

    name = "scripted"

    def __init__(self, script: list[LLMResponse | Exception]) -> None:
        self.script = list(script)
        self.calls: list[tuple[list[Message], list[dict[str, Any]]]] = []

    async def chat(self, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse:
        self.calls.append((list(messages), tools))
        if not self.script:
            return LLMResponse(content="(no more script)")
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def call(name: str, args: dict[str, Any] | str, cid: str = "c1") -> LLMResponse:
    raw = args if isinstance(args, str) else json.dumps(args)
    return LLMResponse(content=None, tool_calls=[ToolCall(cid, name, raw)])


def say(text: str) -> LLMResponse:
    return LLMResponse(content=text)


class RecordingSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_text(self, to: str, body: str) -> None:
        self.sent.append((to, body))


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="dev",
        meta_app_secret=SECRET,
        whatsapp_verify_token=VERIFY,
        groq_api_key="unused",
        data_file=str(ROOT / "data" / "sample_data.json"),
    )


@pytest.fixture
def sender() -> RecordingSender:
    return RecordingSender()


@pytest.fixture
def make_client(settings: Settings, sender: RecordingSender) -> Iterator[Any]:
    clients: list[TestClient] = []

    def _make(script: list[LLMResponse | Exception]) -> tuple[TestClient, ScriptedLLM]:
        llm = ScriptedLLM(script)
        client = TestClient(create_app(settings, llm=llm, sender=sender))
        clients.append(client)
        return client, llm

    yield _make
    for c in clients:
        c.close()


def webhook_body(message_id: str, phone: str = ALI, text: str = "hi", kind: str = "text") -> bytes:
    msg: dict[str, Any] = {"from": phone, "id": message_id, "timestamp": "1759800000", "type": kind}
    if kind == "text":
        msg["text"] = {"body": text}
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "WABA", "changes": [{"field": "messages", "value": {"messaging_product": "whatsapp", "messages": [msg]}}]}],
    }
    return json.dumps(payload).encode()


def post_signed(client: TestClient, body: bytes, secret: str = SECRET):  # type: ignore[no-untyped-def]
    return client.post(
        "/webhook", content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sign_body(body, secret)},
    )


__all__ = ["ALI", "SANA", "SECRET", "VERIFY", "ProviderUnavailable", "call", "post_signed", "say", "webhook_body"]
