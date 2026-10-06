"""Outbound WhatsApp Cloud API client."""

import asyncio
import logging
from typing import Protocol

import httpx

from app.core.errors import WhatsAppSendFailed

log = logging.getLogger("whatsapp")

MAX_TEXT_CHARS = 4096  # WhatsApp text message body limit


class MessageSender(Protocol):
    async def send_text(self, to: str, body: str) -> None: ...


class WhatsAppClient:
    def __init__(self, access_token: str, phone_number_id: str, api_version: str, timeout: float = 10.0) -> None:
        self._url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
        self._client = httpx.AsyncClient(timeout=timeout, headers={"Authorization": f"Bearer {access_token}"})

    async def send_text(self, to: str, body: str) -> None:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": body[:MAX_TEXT_CHARS]},
        }
        # Retry only on transport errors, where the request most likely never arrived.
        # A received-but-failed request is not retried, to avoid duplicate customer messages.
        for attempt in range(3):
            try:
                resp = await self._client.post(self._url, json=payload)
            except httpx.TransportError as exc:
                log.warning("whatsapp_transport_error", extra={"data": {"attempt": attempt, "error": type(exc).__name__}})
                await asyncio.sleep(0.5 * 2**attempt)
                continue
            if resp.status_code >= 400:
                log.error("whatsapp_send_rejected", extra={"data": {"status": resp.status_code, "body": resp.text[:300]}})
                raise WhatsAppSendFailed(f"WhatsApp returned {resp.status_code}")
            return
        raise WhatsAppSendFailed("WhatsApp unreachable after retries")

    async def aclose(self) -> None:
        await self._client.aclose()


class ConsoleSender:
    """Used when WhatsApp credentials are not configured: logs replies instead of sending."""

    async def send_text(self, to: str, body: str) -> None:
        log.info("console_reply", extra={"data": {"to": to, "body": body}})
