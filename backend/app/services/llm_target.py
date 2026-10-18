"""Which language model answers a call: Bitdeer (GLM) or Qwen3.8 on the GPU server.

Each language-model role has a model setting and a provider setting (Settings page):

| model setting             | provider setting            |
| ------------------------- | --------------------------- |
| `llm_model`               | `llm_provider`              |
| `description_llm_model`   | `description_llm_provider`  |
| `image_prompt_llm_model`  | `image_prompt_llm_provider` |

A job calls `resolve` once, when it starts, and then builds its request and makes its calls
through the returned `LlmTarget`. It builds the same OpenAI-style request body whichever
provider is chosen. `complete` sends it to the right place and returns the same
`llm.ChatResult` either way.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.core.urls import docker_mapped, join_url
from app.providers import llm, qwen38

LLM_URL_KEY: Final = "llm_base_url"
GPU_URL_KEY: Final = "gpu_api_base_url"

_PROVIDER_KEY_OF_MODEL_KEY: Final[dict[str, str]] = {
    "llm_model": settings_service.LLM_PROVIDER_KEY,
    "description_llm_model": settings_service.DESCRIPTION_PROVIDER_KEY,
    "image_prompt_llm_model": settings_service.IMAGE_PROMPT_PROVIDER_KEY,
}
MODEL_KEYS: Final = tuple(_PROVIDER_KEY_OF_MODEL_KEY)


@dataclass(frozen=True)
class LlmTarget:
    """Where one call goes. `provider` is `bitdeer` or `qwen38`."""

    provider: str
    base_url: str
    model: str

    @property
    def is_qwen38(self) -> bool:
        return self.provider == settings_service.PROVIDER_QWEN38


async def provider_of(session: AsyncSession, model_key: str) -> str:
    """`bitdeer` or `qwen38`: the provider set now for the role whose model setting is
    `model_key`.
    """
    return await settings_service.get_str(session, _PROVIDER_KEY_OF_MODEL_KEY[model_key])


async def resolve(session: AsyncSession, model_key: str) -> LlmTarget:
    """The provider, address and model for the role whose model setting is `model_key`."""
    provider = await provider_of(session, model_key)
    if provider == settings_service.PROVIDER_QWEN38:
        return LlmTarget(
            provider=provider,
            base_url=await settings_service.get_str(session, GPU_URL_KEY),
            model=qwen38.MODEL_ID,
        )
    return LlmTarget(
        provider=settings_service.PROVIDER_BITDEER,
        base_url=await settings_service.get_str(session, LLM_URL_KEY),
        model=await settings_service.get_str(session, model_key),
    )


def endpoint(target: LlmTarget) -> str:
    """The path called on the target's server."""
    return qwen38.GENERATE_PATH if target.is_qwen38 else llm.CHAT_PATH


def call_url(target: LlmTarget) -> str:
    """The address a call goes to, after Docker mapping. It is part of the request hash."""
    return docker_mapped(join_url(target.base_url, endpoint(target)))


async def complete(
    target: LlmTarget, body: dict[str, Any], *, timeout_s: float, idle_timeout_s: float
) -> llm.ChatResult:
    """Sends one request to the target and returns the model's text.

    Raises `llm.LlmCallError`, with the same kinds for both providers.
    """
    if target.is_qwen38:
        return await qwen38.complete(target.base_url, body, timeout_s=timeout_s)
    return await llm.complete(
        target.base_url, body, timeout_s=timeout_s, idle_timeout_s=idle_timeout_s
    )
