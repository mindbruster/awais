from functools import lru_cache
from typing import Annotated, List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Jewelry ERP"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    debug: bool = True

    # NoDecode skips pydantic-settings' default JSON-parse of complex types so our
    # comma-separated env value reaches the field_validator below as a raw string.
    cors_origins: Annotated[List[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    database_url: str

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480

    seed_admin_email: str = "admin@jewelryerp.com"
    seed_admin_password: str = "admin123"
    seed_admin_name: str = "System Admin"

    # Phase 9 — WhatsApp (optional). When credentials are missing the
    # send-whatsapp endpoint returns 503 instead of trying to send.
    whatsapp_provider: str = "none"  # "none" | "twilio"
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    # Twilio sandbox or business sender — must include 'whatsapp:' prefix.
    twilio_whatsapp_from: str | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
