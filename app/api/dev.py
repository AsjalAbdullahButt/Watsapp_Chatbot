"""Local test chat. Only mounted when APP_ENV=dev; never exposed in staging or production."""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.core.logging import new_correlation_id

router = APIRouter(prefix="/dev")


class ChatIn(BaseModel):
    phone: str = Field(default="923001234567", description="Pretend WhatsApp number of the sender")
    message: str = Field(min_length=1, max_length=1000)


@router.post("/chat")
async def chat(body: ChatIn, request: Request) -> dict[str, object]:
    new_correlation_id()
    reply = await request.app.state.agent.reply(body.phone, body.message)
    return {
        "reply": reply.text,
        "fallback": reply.fallback,
        "tools": [t.__dict__ for t in reply.tools],
    }
