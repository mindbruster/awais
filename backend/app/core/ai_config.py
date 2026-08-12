"""
Settings for the AI layer, kept out of `core/config.py`.

They live here rather than on `Settings` for two reasons. One is ownership —
`core/config.py` is edited by everything and this is a self-contained optional
subsystem. The other is that these settings must be readable without the
application's settings object having validated successfully: the whole point of
the AI layer is that it can be absent, and a config import error is a worse
failure than a missing API key.

Reads the process environment, falling back to the same `backend/.env` the rest
of the app loads — an operator who puts the key next to DATABASE_URL has done
the reasonable thing and should not get an unexplained 503.

Two providers. `anthropic` talks to the Claude API directly. `openrouter` is a
single gateway in front of most other vendors, including Z.AI's GLM family, and
is the cheaper route: GLM 4.7 Flash costs roughly a thousandth of a frontier
model per token, which for narrating a handful of report rows is close enough to
free. Both go through the same code path, because the shop must never depend on
which one is switched on.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# backend/app/core/ai_config.py -> backend/.env
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

PROVIDERS = ("none", "anthropic", "openrouter")

DEFAULT_MODELS = {
    "anthropic": "claude-opus-5",
    # The cheapest GLM on OpenRouter. Note that despite the name, none of the
    # GLM models are on OpenRouter's free tier — the ":free" catalogue rotates
    # and currently carries none of them. This one is inexpensive rather than
    # free; see docs/AI_SETUP.md for genuinely free alternatives.
    "openrouter": "z-ai/glm-4.7-flash",
}

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Drawing a piece is a different job from writing a sentence about one, and no
# text model can do it. Kept as its own setting so switching the narrator to a
# cheaper model cannot silently break image generation, and so a shop that wants
# the prose but not the pictures simply leaves it unset.
#
# Images cost real money per call — cents, not the fractions of a cent the text
# models cost — so nothing generates one without somebody asking for it.
DEFAULT_IMAGE_MODEL = "google/gemini-2.5-flash-image-preview"

SETUP_INSTRUCTIONS = (
    "AI features are not configured. Either set AI_PROVIDER=openrouter with "
    "OPENROUTER_API_KEY (optionally AI_MODEL, default "
    f"'{DEFAULT_MODELS['openrouter']}'), or AI_PROVIDER=anthropic with "
    f"ANTHROPIC_API_KEY (default '{DEFAULT_MODELS['anthropic']}'), in "
    "backend/.env or the environment, then restart the API. Every other figure "
    "on this page is computed without a model and keeps working regardless."
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
    provider: str  # one of PROVIDERS
    anthropic_api_key: str | None
    openrouter_api_key: str | None
    model: str
    # Sent as HTTP-Referer / X-Title on OpenRouter so usage is attributable in
    # their dashboard. Optional and cosmetic; requests work without them.
    app_url: str | None
    app_name: str
    image_model: str

    @property
    def api_key(self) -> str | None:
        if self.provider == "anthropic":
            return self.anthropic_api_key
        if self.provider == "openrouter":
            return self.openrouter_api_key
        return None

    @property
    def configured(self) -> bool:
        """True only when a call could actually be made."""
        return self.provider in ("anthropic", "openrouter") and bool(self.api_key)

    @property
    def images_configured(self) -> bool:
        """
        Image generation goes through OpenRouter only. Anthropic's models do not
        draw, so a shop configured for Anthropic gets a clear "not available
        on this provider" rather than a failed call it has to interpret.
        """
        return self.provider == "openrouter" and bool(self.api_key)

    @property
    def unconfigured_reason(self) -> str | None:
        if self.provider == "none":
            return SETUP_INSTRUCTIONS
        if self.provider not in PROVIDERS:
            return (
                f"Unknown AI_PROVIDER '{self.provider}'. Supported: "
                f"{', '.join(PROVIDERS)}. " + SETUP_INSTRUCTIONS
            )
        if not self.api_key:
            key_name = "ANTHROPIC_API_KEY" if self.provider == "anthropic" else "OPENROUTER_API_KEY"
            return f"AI_PROVIDER={self.provider} but {key_name} is empty. " + SETUP_INSTRUCTIONS
        return None


def get_ai_settings() -> AISettings:
    provider = (_env("AI_PROVIDER") or "none").lower()
    return AISettings(
        provider=provider,
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        openrouter_api_key=_env("OPENROUTER_API_KEY"),
        # The default follows the provider, so switching provider doesn't leave
        # a model name from the other one behind and fail with "unknown model".
        model=_env("AI_MODEL") or DEFAULT_MODELS.get(provider, DEFAULT_MODELS["openrouter"]),
        app_url=_env("AI_APP_URL"),
        app_name=_env("AI_APP_NAME") or "Jewelry ERP",
        image_model=_env("AI_IMAGE_MODEL") or DEFAULT_IMAGE_MODEL,
    )
