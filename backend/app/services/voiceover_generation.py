"""Making a project's voiceover from its script with Breeze TTS (Phase 21).

The user pastes the script and chooses a saved voice (`project.voice_id`). The `generate_voiceover`
job then speaks the script in that voice and stores the WAV as the project's voiceover
(`asset.kind = 'voiceover'`, `asset.source = 'ai'`). From there the flow is the one of an
uploaded voiceover: the transcription follows, and takes its words from the audio.

The script is split into pieces of at most 1000 characters (`services/speech_chunks.py`), one
request each. Every piece uses the same saved voice, seed and guidance, so the voice stays the
same. A pause between pieces is whatever the model puts at the end of each.

A voiceover made from a script is out of date when the script has changed since
(`asset.provenance.script_sha256`): the page says so, and the user makes it again.

Breeze TTS 2's weights and outputs are licensed for research and non-commercial use only.

This module never calls the GPU server: `jobs/generate_voiceover.py` does that.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Asset, Job, Project, Voice
from app.jobs import store
from app.providers import speech_synthesizer
from app.services import speech_chunks, transcript_matching

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "generate_voiceover"
# A script of more pieces than this is refused: at about 1.5 minutes of speech a piece it is
# close to 45 minutes of voiceover, far beyond a short video.
MAX_PARTS: Final = 30
# Jobs of these types change the project's voiceover or read it, so a new voiceover waits.
_BUSY_TYPES: Final = ("transcribe", store.AUTO_RUN_TYPE)


class VoiceoverBlocked(Exception):
    """Why the voiceover cannot be made now. The message is meant to be shown to the user."""

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _blank(text: str | None) -> bool:
    return text is None or not text.strip()


def is_current(project: Project, asset: Asset | None) -> bool:
    """Is this voiceover one the app made from the script as it is now?"""
    if asset is None or asset.source != "ai" or _blank(project.script_text):
        return False
    provenance = asset.provenance if isinstance(asset.provenance, dict) else {}
    return provenance.get("script_sha256") == transcript_matching.script_sha256(
        project.script_text or ""
    )


def block_reason(project: Project, voice: Voice | None) -> str | None:
    """Why a voiceover cannot be made from the script and the chosen voice, or None. Pure.
    Says nothing about other jobs: see `busy_reason`.
    """
    if _blank(project.script_text):
        return "Paste the script first."
    if project.voice_id is None:
        return "Choose a saved voice first."
    if voice is None:
        return "The chosen voice no longer exists. Choose another."
    parts = len(speech_chunks.split_script(project.script_text or ""))
    if parts > MAX_PARTS:
        return (
            f"The script needs {parts} requests to the speech model, more than the {MAX_PARTS} "
            "this app makes at once. Shorten the script."
        )
    return None


async def busy_reason(session: AsyncSession, project_id: int) -> str | None:
    """Why another job of the project stands in the way, or None."""
    statement = select(Job.type).where(
        Job.project_id == project_id,
        Job.type.in_(_BUSY_TYPES),
        Job.status.in_(store.ACTIVE_STATUSES),
    )
    active = (await session.execute(statement)).scalars().first()
    if active == "transcribe":
        return "The voiceover is being transcribed. Wait for it to finish."
    if active is not None:
        return "An automatic run is active for this project. Wait for it to finish."
    return None


def build_input(project: Project, voice: Voice) -> dict[str, Any]:
    """What the job is created with: the pieces of the script, the voice and the script's hash,
    as they are now, so a later edit of the script or of the voice changes nothing for a job
    already created. The caller has checked `block_reason`.
    """
    script = project.script_text or ""
    chunks = speech_chunks.split_script(script)
    return {
        "requested": "voiceover",
        "chunks": chunks,
        "instruction": None,
        "seed": speech_synthesizer.DEFAULT_SEED,
        "cfg_scale": speech_synthesizer.CFG_SCALE_PLAIN,
        "script_sha256": transcript_matching.script_sha256(script),
        "reference": {
            "voice_id": voice.id,
            "path": voice.path,
            "mime": voice.mime,
            "text": voice.transcript,
        },
    }


async def create_job(
    session: AsyncSession, project: Project, voice: Voice, *, commit: bool = True
) -> tuple[Job, bool]:
    """Creates the `generate_voiceover` job, or returns the one that is already active."""
    return await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="gpu",
        input=build_input(project, voice),
        commit=commit,
    )
