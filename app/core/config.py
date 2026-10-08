"""Centralized configuration. Values come from environment variables or a local .env file."""

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["dev", "staging", "prod"] = "dev"
    log_level: str = "INFO"

    # Meta WhatsApp Cloud API
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = ""
    meta_app_secret: str = ""
    whatsapp_api_version: str = "v21.0"

    # LLM
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    llm_timeout_seconds: float = 20.0
    llm_max_retries: int = 2

    # Agent
    max_tool_steps: int = 3
    history_messages: int = 10

    # Data source for this check build (replace with your data file)
    data_file: str = "data/sample_data.json"

    # Duplicate-message window
    dedup_ttl_seconds: int = 24 * 60 * 60

    # Abuse protection: messages allowed per phone in a rolling window
    rate_limit_messages: int = 10
    rate_limit_window_seconds: int = 60

    # Bound on per-phone in-memory state (history, locks, rate-limit counters)
    max_tracked_phones: int = 10_000

    @model_validator(mode="after")
    def _require_secrets_outside_dev(self) -> "Settings":
        if self.app_env != "dev":
            required = ("meta_app_secret", "whatsapp_verify_token", "whatsapp_access_token",
                        "whatsapp_phone_number_id", "groq_api_key")
            missing = [name for name in required if not getattr(self, name)]
            if missing:
                raise ValueError(f"missing required settings for {self.app_env}: {', '.join(missing)}")
        return self

    @property
    def dev_endpoints_enabled(self) -> bool:
        return self.app_env == "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()
