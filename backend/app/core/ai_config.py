"""
Settings for the AI layer, kept out of `core/config.py`.

They live here rather than on `Settings` for two reasons. One is ownership —
`core/config.py` is edited by everything and this is a self-contained optional
subsystem. The other is that these settings must be readable without the
application's settings object having validated successfully: the whole point of
the AI layer is that it can be absent, and a config import error is a worse
failure than a missing API key.

Reads the process environment, falling back to the same `backend/.env` the rest
of the app loads — an operator who puts ANTHROPIC_API_KEY next to DATABASE_URL
has done the reasonable thing and should not get an unexplained 503.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# backend/app/core/ai_config.py -> backend/.env
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

DEFAULT_MODEL = "claude-opus-5"

SETUP_INSTRUCTIONS = (
    "AI features are not configured. Set AI_PROVIDER=anthropic and "
    "ANTHROPIC_API_KEY (optionally AI_MODEL, default "
    f"'{DEFAULT_MODEL}') in backend/.env or the environment, install the SDK "
    "with `pip install anthropic`, and restart the API. Every other figure on "
    "this page is computed without a model and keeps working regardless."
)


@lru_cache
def _dotenv() -> dict[str, str]:
    """
    Parse `backend/.env` once, if it exists.

    Deliberately naive — it only has to read `KEY=value` lines that
    pydantic-settings already reads for the rest of the app.
    """
    values: dict[str, str] = {}
    try:
        text = _ENV_FILE.read_text(encoding="utf-8")
    except OSError:
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip().upper()] = value.strip().strip("'\"")
    return values


def _env(name: str) -> str | None:
    value = os.environ.get(name) or _dotenv().get(name)
    return value.strip() or None if value else None


@dataclass(frozen=True)
class AISettings:
    provider: str  # "none" | "anthropic"
    anthropic_api_key: str | None
    model: str

    @property
    def configured(self) -> bool:
        """True only when a call could actually be made."""
        if self.provider == "anthropic":
            return bool(self.anthropic_api_key)
        return False

    @property
    def unconfigured_reason(self) -> str | None:
        if self.provider == "none":
            return SETUP_INSTRUCTIONS
        if self.provider == "anthropic" and not self.anthropic_api_key:
            return (
                "AI_PROVIDER=anthropic but ANTHROPIC_API_KEY is empty. "
                + SETUP_INSTRUCTIONS
            )
        if self.provider not in ("none", "anthropic"):
            return (
                f"Unknown AI_PROVIDER '{self.provider}'. Supported: none, anthropic. "
                + SETUP_INSTRUCTIONS
            )
        return None


def get_ai_settings() -> AISettings:
    return AISettings(
        provider=(_env("AI_PROVIDER") or "none").lower(),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        model=_env("AI_MODEL") or DEFAULT_MODEL,
    )
