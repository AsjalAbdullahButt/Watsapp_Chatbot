"""Centralized configuration. Values come from environment variables or a local .env file."""

from functools import lru_cache
from typing import Literal

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

    @property
    def dev_endpoints_enabled(self) -> bool:
        return self.app_env == "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()
