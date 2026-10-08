"""Application factory. All dependencies are wired here, so tests can swap the LLM and sender."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.agent.agent import Agent, ConversationMemory
from app.api import dev, webhook
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.data.source import JsonDataSource
from app.llm.base import LLMProvider
from app.llm.groq_provider import GroqProvider
from app.tools.catalog import build_registry
from app.whatsapp.client import ConsoleSender, MessageSender, WhatsAppClient
from app.whatsapp.inbound import ConversationLocks, DedupStore, RateLimiter

log = logging.getLogger("app")


def create_app(
    settings: Settings | None = None,
    llm: LLMProvider | None = None,
    sender: MessageSender | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    source = JsonDataSource(settings.data_file)
    registry = build_registry(source)
    llm = llm or GroqProvider(
        settings.groq_api_key, settings.groq_model, settings.llm_timeout_seconds, settings.llm_max_retries
    )
    if sender is None:
        if settings.whatsapp_access_token and settings.whatsapp_phone_number_id:
            sender = WhatsAppClient(
                settings.whatsapp_access_token, settings.whatsapp_phone_number_id, settings.whatsapp_api_version
            )
        else:
            sender = ConsoleSender()

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        log.info("startup", extra={"data": {"env": settings.app_env, "llm": llm.name, "sender": type(sender).__name__}})
        yield
        for closable in (llm, sender):
            close = getattr(closable, "aclose", None)
            if close:
                await close()

    app = FastAPI(
        title="WhatsApp Agent (check build)",
        lifespan=lifespan,
        docs_url="/docs" if settings.dev_endpoints_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.dev_endpoints_enabled else None,
    )
    app.state.settings = settings
    app.state.source = source
    app.state.registry = registry
    app.state.agent = Agent(llm, registry, source, ConversationMemory(settings.history_messages, settings.max_tracked_phones), settings.max_tool_steps)
    app.state.sender = sender
    app.state.dedup = DedupStore(settings.dedup_ttl_seconds)
    app.state.locks = ConversationLocks(settings.max_tracked_phones)
    app.state.limiter = RateLimiter(
        settings.rate_limit_messages, settings.rate_limit_window_seconds, settings.max_tracked_phones
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    app.include_router(webhook.router)
    if settings.dev_endpoints_enabled:
        app.include_router(dev.router)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready() -> JSONResponse:
        checks = {
            "data": bool(source.list_products()),
            "webhook_secret": bool(settings.meta_app_secret and settings.whatsapp_verify_token),
        }
        ok = all(checks.values())
        return JSONResponse({"status": "ok" if ok else "not_ready", "checks": checks}, status_code=200 if ok else 503)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error")
        return JSONResponse({"detail": "Internal error"}, status_code=500)

    return app
