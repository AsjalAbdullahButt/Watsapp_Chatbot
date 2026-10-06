"""Parsing of Meta webhook payloads, duplicate protection and per-conversation ordering."""

import asyncio
import time
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InboundMessage:
    message_id: str
    phone: str
    kind: str          # "text", "interactive", or another WhatsApp type
    text: str | None   # None for types this build does not read (image, audio, ...)


def extract_messages(payload: dict[str, Any]) -> list[InboundMessage]:
    """Return customer messages; delivery/read statuses and other events are ignored."""
    found: list[InboundMessage] = []
    if payload.get("object") != "whatsapp_business_account":
        return found
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            for msg in value.get("messages") or []:
                msg_id, phone, kind = msg.get("id"), msg.get("from"), msg.get("type", "")
                if not msg_id or not phone:
                    continue
                text: str | None = None
                if kind == "text":
                    text = (msg.get("text") or {}).get("body")
                elif kind == "interactive":
                    inter = msg.get("interactive") or {}
                    reply = inter.get("button_reply") or inter.get("list_reply") or {}
                    text = reply.get("title")
                found.append(InboundMessage(str(msg_id), str(phone), kind, text))
    return found


class DedupStore:
    """Remembers message IDs for a TTL. In-process for this build; Redis + SQL unique key later."""

    def __init__(self, ttl_seconds: int, max_items: int = 100_000) -> None:
        self._ttl = ttl_seconds
        self._max = max_items
        self._seen: OrderedDict[str, float] = OrderedDict()

    def first_time(self, message_id: str) -> bool:
        now = time.monotonic()
        while self._seen and next(iter(self._seen.values())) < now - self._ttl:
            self._seen.popitem(last=False)
        if message_id in self._seen:
            return False
        self._seen[message_id] = now
        if len(self._seen) > self._max:
            self._seen.popitem(last=False)
        return True


class ConversationLocks:
    """One lock per phone, so two quick messages from one customer are answered in order."""

    def __init__(self) -> None:
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def for_phone(self, phone: str) -> asyncio.Lock:
        return self._locks[phone]
