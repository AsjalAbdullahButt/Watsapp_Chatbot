"""Meta webhook endpoints. The POST handler verifies, deduplicates, schedules work and returns fast."""

import hmac
import json
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Response

from app.core.errors import InvalidSignature, WhatsAppSendFailed
from app.core.logging import correlation_id, new_correlation_id
from app.core.security import verify_meta_signature
from app.whatsapp.inbound import InboundMessage, extract_messages, sanitize_text

log = logging.getLogger("webhook")
router = APIRouter()

MAX_BODY_BYTES = 256 * 1024
RATE_LIMITED_REPLY = (
    "You are sending messages too quickly. Please wait a minute and try again.\n"
    "Aap bohat tezi se messages bhej rahe hain. Ek minute baad dobara koshish karein."
)
UNSUPPORTED_TYPE_REPLY = (
    "For now I can only read text messages. Please type your question.\n"
    "Abhi main sirf text messages parh sakta hoon. Apna sawal likh kar bhejein."
)


@router.get("/webhook")
async def verify_subscription(
    request: Request,
    mode: str = Query("", alias="hub.mode"),
    token: str = Query("", alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
) -> Response:
    expected = request.app.state.settings.whatsapp_verify_token
    if mode == "subscribe" and expected and hmac.compare_digest(token.encode(), expected.encode()):
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/webhook")
async def receive(request: Request, background: BackgroundTasks) -> dict[str, str]:
    new_correlation_id()
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")
    try:
        verify_meta_signature(raw, request.headers.get("X-Hub-Signature-256"), request.app.state.settings.meta_app_secret)
    except InvalidSignature as exc:
        log.warning("webhook_signature_rejected", extra={"data": {"reason": str(exc)}})
        raise HTTPException(status_code=401, detail="Invalid signature") from None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Malformed JSON") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Malformed payload")

    state = request.app.state
    for msg in extract_messages(payload):
        if not state.dedup.first_time(msg.message_id):
            log.info("webhook_duplicate_skipped", extra={"data": {"message_id": msg.message_id}})
            continue
        log.info("webhook_message_accepted", extra={"data": {"message_id": msg.message_id, "kind": msg.kind}})
        background.add_task(handle_message, request.app, msg, correlation_id.get())
    return {"status": "ok"}


async def handle_message(app, msg: InboundMessage, cid: str) -> None:  # type: ignore[no-untyped-def]
    """Runs after the 200 is sent. In the full build this becomes a Celery task."""
    correlation_id.set(cid)
    state = app.state
    async with state.locks.for_phone(msg.phone):
        if not state.limiter.allow(msg.phone):
            log.warning("rate_limited", extra={"data": {"message_id": msg.message_id}})
            reply_text = RATE_LIMITED_REPLY
        elif not msg.text:
            reply_text = UNSUPPORTED_TYPE_REPLY
        else:
            reply = await state.agent.reply(msg.phone, sanitize_text(msg.text))
            reply_text = reply.text
        try:
            await state.sender.send_text(msg.phone, reply_text)
        except WhatsAppSendFailed:
            log.error("reply_not_delivered", extra={"data": {"message_id": msg.message_id}})
