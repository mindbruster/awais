"""
Drawing a piece, from a description and optionally photographs of others.

The workshop's real need is narrow and worth stating, because it decides the
shape of everything here: a customer describes a piece, or points at two rings
in a tray and asks for something between them, and somebody has to show them a
picture before any gold is cut. That is a reference-guided drawing, not stock
photography, so the references are the important half of the request.

Three rules, all of which follow from this being an *illustration*:

* It is never load-bearing. Nothing in the shop stops working if this is
  unconfigured, rate-limited or down. A design proceeds from a sketch on paper
  exactly as it always did.
* It is never automatic. Every call costs cents rather than the fractions of a
  cent the text models cost, so an image is drawn only when a person asks for
  one. Nothing here runs on save, on view, or on a schedule.
* What it produces is a proposal, not a record. A generated picture is attached
  to a product only when somebody chooses to attach it, and it never overwrites
  a photograph of the actual finished piece without that being the explicit act.

OpenRouter only. Anthropic's models do not draw, and pretending otherwise would
turn "wrong provider" into a failed HTTP call that the operator has to decode.
"""
from __future__ import annotations

import base64
import binascii
import logging
from dataclasses import dataclass

import httpx
from fastapi import HTTPException, status

from app.core.ai_config import OPENROUTER_BASE_URL, AISettings, get_ai_settings

log = logging.getLogger(__name__)

# Generous: a drawing model thinks for longer than a narrator does, and the
# alternative to waiting is a timeout on work already paid for.
_TIMEOUT_S = 120.0

# What a reference may be. Matches the product upload endpoint's list, so a
# photograph that can be stored can also be used to guide a drawing.
ALLOWED_REFERENCE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_REFERENCE_BYTES = 5 * 1024 * 1024
# Each reference is re-encoded into the prompt as base64, so they are bounded
# for the request's sake as much as the model's.
MAX_REFERENCES = 4

# Prepended to whatever the counter types. Without it the models drift towards
# fashion photography — hands, faces, models wearing the piece — which is
# useless to a workshop that needs to see the article itself.
_STYLE_PREAMBLE = (
    "A single piece of fine jewellery photographed on its own for a jeweller's "
    "catalogue. Plain seamless background, no hands, no models, no packaging. "
    "Even studio lighting, sharp focus across the whole piece, true metal colour, "
    "stones rendered with realistic brilliance. The piece fills the frame."
)


@dataclass(frozen=True)
class GeneratedImage:
    data: bytes
    media_type: str
    model: str

    @property
    def extension(self) -> str:
        return {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/webp": ".webp",
            "image/gif": ".gif",
        }.get(self.media_type, ".png")


def images_available() -> bool:
    return get_ai_settings().images_configured


def require_images() -> AISettings:
    """
    503 with instructions, in the shape `ai.require_provider` uses.

    Separate from the text check because the two fail for different reasons and
    the operator needs to be told which: a shop can have narration working
    perfectly and images unavailable, purely by being on Anthropic.
    """
    cfg = get_ai_settings()
    if cfg.images_configured:
        return cfg
    if cfg.provider == "anthropic":
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Image generation runs through OpenRouter, and this shop is configured for "
            "Anthropic, whose models do not draw. Set AI_PROVIDER=openrouter with "
            "OPENROUTER_API_KEY in backend/.env to use it. Everything else keeps working.",
        )
    raise HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        cfg.unconfigured_reason
        or "Image generation is not configured. Set AI_PROVIDER=openrouter with "
        "OPENROUTER_API_KEY in backend/.env.",
    )


def _data_url(data: bytes, media_type: str) -> str:
    return f"data:{media_type};base64,{base64.b64encode(data).decode()}"


def _decode_image_url(url: str) -> tuple[bytes, str] | None:
    """Pull the bytes back out of a `data:` URL the model returned."""
    if not url.startswith("data:"):
        return None
    try:
        header, payload = url.split(",", 1)
        media_type = header[5:].split(";", 1)[0] or "image/png"
        return base64.b64decode(payload), media_type
    except (ValueError, binascii.Error):
        return None


def _extract_image(message: dict) -> tuple[bytes, str] | None:
    """
    Find the picture in a chat-completions response.

    Image models answer through the same endpoint as text ones and there is no
    single agreed field: some return `message.images[].image_url.url`, others
    put an image part in the content list. Both are read rather than one, so a
    model swap does not turn into an empty-looking failure.
    """
    for img in message.get("images") or []:
        url = (img or {}).get("image_url", {}).get("url") or (img or {}).get("url")
        if isinstance(url, str) and (found := _decode_image_url(url)):
            return found

    content = message.get("content")
    if isinstance(content, list):
        for part in content:
            if not isinstance(part, dict):
                continue
            url = part.get("image_url", {}).get("url") if isinstance(part.get("image_url"), dict) else None
            if isinstance(url, str) and (found := _decode_image_url(url)):
                return found
            if part.get("type") in ("image", "output_image") and isinstance(part.get("data"), str):
                try:
                    return base64.b64decode(part["data"]), part.get("media_type", "image/png")
                except binascii.Error:
                    continue
    return None


async def generate(
    prompt: str,
    *,
    references: list[tuple[bytes, str]] | None = None,
) -> GeneratedImage:
    """
    Draw a piece. `references` are (bytes, media_type) photographs to steer it.

    Raises rather than returning None, unlike `ai.narrate_*`: the caller here
    asked for a picture and there is nothing sensible to show without one. The
    provider's own message is passed through, because "you have no credit" and
    "that model does not exist" need different actions from the operator and
    collapsing them into "generation failed" strands them.
    """
    cfg = require_images()
    refs = references or []
    if len(refs) > MAX_REFERENCES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"At most {MAX_REFERENCES} reference images.",
        )

    parts: list[dict] = [{"type": "text", "text": f"{_STYLE_PREAMBLE}\n\n{prompt.strip()}"}]
    if refs:
        parts[0]["text"] += (
            f"\n\nUse the {len(refs)} attached photograph(s) as the reference for style, "
            "proportion and finish. Draw one new piece in keeping with them — do not "
            "reproduce any of them exactly and do not combine them into a collage."
        )
        for data, media_type in refs:
            parts.append({"type": "image_url", "image_url": {"url": _data_url(data, media_type)}})

    headers = {
        "Authorization": f"Bearer {cfg.api_key}",
        "Content-Type": "application/json",
    }
    if cfg.app_url:
        headers["HTTP-Referer"] = cfg.app_url
    if cfg.app_name:
        headers["X-Title"] = cfg.app_name

    body = {
        "model": cfg.image_model,
        "messages": [{"role": "user", "content": parts}],
        "modalities": ["image", "text"],
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions", headers=headers, json=body
            )
    except httpx.HTTPError as exc:
        # The key is in `headers`, so the exception is logged without it and the
        # caller is told only what happened.
        log.warning("image generation transport error: %s", type(exc).__name__)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Could not reach the image provider. Nothing was charged; try again.",
        ) from None

    if resp.status_code >= 400:
        detail = resp.text[:300]
        log.warning("image generation failed: %s", resp.status_code)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"The image provider refused the request ({resp.status_code}). {detail}",
        )

    payload = resp.json()
    choices = payload.get("choices") or []
    message = (choices[0] or {}).get("message", {}) if choices else {}
    found = _extract_image(message)
    if found is None:
        # Worth its own message: a text model named in AI_IMAGE_MODEL answers
        # this request perfectly happily, in words, and the operator otherwise
        # sees a blank failure with no hint that the model is the problem.
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"'{cfg.image_model}' returned no image. Check AI_IMAGE_MODEL names a model "
            "that can draw — a text-only model will answer this request in words.",
        )

    data, media_type = found
    return GeneratedImage(data=data, media_type=media_type, model=cfg.image_model)
