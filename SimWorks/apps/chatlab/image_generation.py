"""Provider adapter for ChatLab clinical image generation."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from io import BytesIO
import os

import httpx
from openai import OpenAI
from PIL import Image

from orchestrai.utils.env_utils import get_api_key


class ImageGenerationError(RuntimeError):
    """Raised when image generation fails."""


@dataclass(slots=True)
class GeneratedImage:
    image_bytes: bytes
    mime_type: str
    provider_id: str | None = None


def _detect_mime_type(image_bytes: bytes) -> str:
    try:
        with Image.open(BytesIO(image_bytes)) as img:
            fmt = (img.format or "").upper()
    except Exception:
        return "image/png"

    mime_map = {
        "PNG": "image/png",
        "JPEG": "image/jpeg",
        "JPG": "image/jpeg",
        "WEBP": "image/webp",
        "GIF": "image/gif",
    }
    return mime_map.get(fmt, "image/png")


def _extract_openai_image(response) -> tuple[bytes, str | None]:
    payload = response.model_dump() if hasattr(response, "model_dump") else response
    if not isinstance(payload, dict):
        raise ImageGenerationError("Unexpected image provider response shape")

    data = payload.get("data") or []
    if not data:
        raise ImageGenerationError("Image provider returned no data")

    first = data[0] or {}
    provider_id = first.get("id") or payload.get("id")

    b64_json = first.get("b64_json")
    if b64_json:
        return base64.b64decode(b64_json), provider_id

    image_url = first.get("url")
    if image_url:
        response = httpx.get(image_url, timeout=30.0)
        response.raise_for_status()
        return response.content, provider_id

    raise ImageGenerationError("Image provider response missing both b64_json and url")


def generate_patient_image(
    *,
    prompt: str,
    model: str | None = None,
    size: str | None = None,
) -> GeneratedImage:
    """Generate an image using OpenAI and return bytes + metadata."""
    api_key = get_api_key("openai")
    if not api_key:
        raise ImageGenerationError("OpenAI API key is not configured")

    model_name = model or os.getenv("ORCA_IMAGE_MODEL", "gpt-image-1")
    image_size = size or os.getenv("ORCA_IMAGE_SIZE", "1024x1024")
    client = OpenAI(api_key=api_key)

    try:
        response = client.images.generate(
            model=model_name,
            prompt=prompt,
            size=image_size,
            response_format="b64_json",
        )
    except TypeError:
        # Older/newer SDK compatibility fallback.
        response = client.images.generate(
            model=model_name,
            prompt=prompt,
            size=image_size,
        )
    except Exception as exc:
        raise ImageGenerationError(str(exc)) from exc

    image_bytes, provider_id = _extract_openai_image(response)
    mime_type = _detect_mime_type(image_bytes)
    return GeneratedImage(
        image_bytes=image_bytes,
        mime_type=mime_type,
        provider_id=provider_id,
    )
