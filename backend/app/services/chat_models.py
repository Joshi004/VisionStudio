"""The models the Text lab (the chat) can talk to, and the limits of each.

The list is fixed in code. It follows the Bitdeer model catalog (the text models) plus the
Qwen3.8 model on the GPU server. A model setting on the Settings page is a role (story,
descriptions, ...); the chat is different: the user picks the model for every message, so the
model is part of the request and this module says which ones are allowed.

Each model has:

- `provider`: `bitdeer` (the paid API, the answer streams in) or `qwen38` (a job on the GPU
  server, the answer arrives in one piece, and a stopped server takes 3 to 10 minutes to start).
- `max_tokens`: the limit asked of the model. For a reasoning model it includes the thinking.
- `max_history_chars`: how much of the earlier chat is sent. When the chat is longer, the oldest
  messages are left out (see `jobs/write_chat_reply.py`). The Qwen3.8 server refuses more than
  `qwen38.MESSAGES_MAX_CHARS` characters in total, so that is its limit. For Bitdeer models it is
  a safe size well inside each model's context window.
- `reasoning_effort`: whether the request carries `reasoning_effort`. Only the GLM-5.3 models are
  known to take it. For the others it is left out until the owner has checked that the model
  accepts it (see the owner checks in the plan).

The Bitdeer model list and the context sizes come from Bitdeer's public documentation read in
November 2026. A model that Bitdeer retires or renames has to be changed here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.providers import llm, qwen38
from app.services.llm_target import GPU_URL_KEY, LLM_URL_KEY, LlmTarget

PROVIDER_BITDEER: Final = settings_service.PROVIDER_BITDEER
PROVIDER_QWEN38: Final = settings_service.PROVIDER_QWEN38

# The model id of the GPU server's Qwen3.8. It is not Bitdeer's model id, so the two can be told
# apart in the list.
GPU_QWEN38_ID: Final = "gpu/qwen3.8-27b"


@dataclass(frozen=True)
class ChatModel:
    id: str
    label: str
    provider: str
    max_tokens: int
    max_history_chars: int
    reasoning_effort: bool
    note: str | None = None

    @property
    def is_qwen38(self) -> bool:
        return self.provider == PROVIDER_QWEN38


MODELS: Final[tuple[ChatModel, ...]] = (
    ChatModel(
        id="zai-org/GLM-5.3",
        label="GLM-5.3 (Bitdeer)",
        provider=PROVIDER_BITDEER,
        max_tokens=32_000,
        max_history_chars=400_000,
        reasoning_effort=True,
    ),
    ChatModel(
        id="zai-org/GLM-5.3-Flash",
        label="GLM-5.3 Flash (Bitdeer)",
        provider=PROVIDER_BITDEER,
        max_tokens=16_000,
        max_history_chars=200_000,
        reasoning_effort=True,
    ),
    ChatModel(
        id="Qwen/Qwen3.8-27B",
        label="Qwen3.8 27B (Bitdeer)",
        provider=PROVIDER_BITDEER,
        max_tokens=16_000,
        max_history_chars=120_000,
        reasoning_effort=False,
    ),
    ChatModel(
        id="deepseek-ai/DeepSeek-V4.1-Flash-1017",
        label="DeepSeek V4.1 Flash (Bitdeer)",
        provider=PROVIDER_BITDEER,
        max_tokens=16_000,
        max_history_chars=120_000,
        reasoning_effort=False,
    ),
    ChatModel(
        id="nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B",
        label="Nemotron 3.5 Super VL 120B (Bitdeer)",
        provider=PROVIDER_BITDEER,
        max_tokens=16_000,
        max_history_chars=120_000,
        reasoning_effort=False,
    ),
    ChatModel(
        id=GPU_QWEN38_ID,
        label="Qwen3.8 27B (remote server)",
        provider=PROVIDER_QWEN38,
        max_tokens=qwen38.MAX_TOKENS_CAP,
        max_history_chars=qwen38.MESSAGES_MAX_CHARS,
        reasoning_effort=False,
        note=(
            "Runs on the remote GPU server. The answer arrives in one piece, and a stopped "
            "server can take 3 to 10 minutes to start."
        ),
    ),
)

DEFAULT_MODEL_ID: Final = MODELS[0].id


def get(model_id: str) -> ChatModel | None:
    """The model with this id, or None when it is not in the list."""
    return next((model for model in MODELS if model.id == model_id), None)


async def target_for(session: AsyncSession, model: ChatModel) -> LlmTarget:
    """Where a call to this model goes: the Bitdeer address, or the GPU server's."""
    if model.is_qwen38:
        return LlmTarget(
            provider=PROVIDER_QWEN38,
            base_url=await settings_service.get_str(session, GPU_URL_KEY),
            model=qwen38.MODEL_ID,
        )
    return LlmTarget(
        provider=PROVIDER_BITDEER,
        base_url=await settings_service.get_str(session, LLM_URL_KEY),
        model=model.id,
    )


def endpoint_of(model: ChatModel) -> str:
    """The path a call to this model uses on its server. The pools read it from the job."""
    return qwen38.GENERATE_PATH if model.is_qwen38 else llm.CHAT_PATH
