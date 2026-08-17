import os
from functools import lru_cache
from typing import Annotated, List

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Jewelry ERP"
    # The shop's own timezone, which is what "today" means everywhere in the
    # system: today's gold rate, today's takings, whether a memo is overdue.
    # Timestamps are still stored in UTC — this only decides where a day
    # begins. See app/core/clock.py for why it cannot be left to the server's.
    shop_timezone: str = "Asia/Karachi"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    debug: bool = True

    # Four eyes on a metal write-off: the person who submitted a stock count
    # may not be the one who posts it.
    #
    # Off by default, and that is deliberate rather than lax. A shop with a
    # single admin would otherwise be unable to post a count at all — the
    # control would not make them safer, it would make the feature unusable and
    # push the reconciliation back onto paper, which is strictly worse. A shop
    # with two or more people turns it on.
    require_two_person_approval: bool = False

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

    @field_validator("database_url", mode="before")
    @classmethod
    def normalise_db_driver(cls, v):
        """
        Managed Postgres providers (Railway, Heroku, Render) hand out
        `postgres://` or `postgresql://` URLs. This app talks to the database
        over SQLAlchemy's async engine, which needs the asyncpg driver named
        explicitly — otherwise startup dies on an opaque driver error that
        looks nothing like "your connection string is fine but under-specified".
        """
        if isinstance(v, str):
            if v.startswith("postgres://"):
                v = "postgresql://" + v[len("postgres://"):]
            if v.startswith("postgresql://"):
                v = "postgresql+asyncpg://" + v[len("postgresql://"):]
        return v

    @model_validator(mode="after")
    def require_production_secrets(self):
        """
        Refuse to start a non-development deployment on the shipped defaults.
        These are convenient locally and dangerous anywhere reachable, and the
        failure mode of forgetting them is a public admin login with a password
        that is published in the README.
        """
        if self.environment.lower() in ("development", "test", "ci"):
            return self

        insecure: list[str] = []
        if self.jwt_secret.startswith("change-me") or self.jwt_secret == "ci-secret-not-for-prod-use-only":
            insecure.append("JWT_SECRET (still set to a placeholder)")
        elif len(self.jwt_secret) < 32:
            insecure.append("JWT_SECRET (must be at least 32 characters)")
        if self.seed_admin_password == "admin123":
            insecure.append("SEED_ADMIN_PASSWORD")
        if self.debug:
            insecure.append("DEBUG (must be false outside development)")

        # Local-disk storage on a platform with an ephemeral filesystem deletes
        # every product photograph on each redeploy, silently and permanently.
        # It is the one production misconfiguration that destroys data the shop
        # cannot recreate, and it gives no signal at all — so it fails at boot
        # rather than at the next deploy. Set STORAGE_BACKEND=local explicitly
        # if the deployment genuinely has a persistent volume mounted.
        storage = os.getenv("STORAGE_BACKEND", "").strip().lower()
        if not storage:
            insecure.append(
                "STORAGE_BACKEND (set 's3' for object storage, or 'local' only if a "
                "persistent volume is mounted at UPLOAD_DIR — the default loses every "
                "uploaded photo on redeploy)"
            )
        elif storage == "s3":
            missing = [
                name
                for name in ("S3_ENDPOINT", "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY")
                if not os.getenv(name)
            ]
            if missing:
                insecure.append(f"STORAGE_BACKEND=s3 but {', '.join(missing)} not set")

        if insecure:
            raise ValueError(
                f"Refusing to start in environment '{self.environment}' with insecure "
                f"settings: {', '.join(insecure)}. Set these to real values."
            )
        return self

    # Phase 9 — WhatsApp (optional). When credentials are missing the
    # send-whatsapp endpoint returns 503 instead of trying to send.
    whatsapp_provider: str = "none"  # "none" | "twilio"
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    # Twilio sandbox or business sender — must include 'whatsapp:' prefix.
    twilio_whatsapp_from: str | None = None

    # Live metal rates from goldpricez.com (optional). Without a key the live
    # tab says so rather than failing: the rate the shop *sets* drives every
    # calculation, and this feed is never allowed near pricing.
    goldpricez_api_key: str | None = None

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
