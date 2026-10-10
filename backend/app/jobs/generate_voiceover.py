"""The `generate_voiceover` job: a project's script, spoken by a saved voice (Phase 21).

It is `SpeechHandler` with one piece of text per 1000 characters of the script, and
`store_result` stores the joined WAV in the project's folder as an AI voiceover and points the
project at it, in one transaction with the finished job. The earlier voiceover and its file
stay, like every stored file.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from sqlalchemy import update

from app.db.models import Job, Project
from app.db.session import SessionLocal
from app.jobs import store
from app.jobs.synthesize_speech import SpeechFile, SpeechHandler, read_plan
from app.services import voiceover_generation
from app.services.assets import add_asset
from app.services.storage import get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = voiceover_generation.JOB_TYPE
MODEL_NAME: Final = "breeze-tts-2"


class GenerateVoiceoverHandler(SpeechHandler):
    job_type = JOB_TYPE

    async def store_result(self, job: Job, speech: SpeechFile) -> bool:
        recorded = job.input if isinstance(job.input, dict) else {}
        plan = read_plan(recorded)
        async with SessionLocal() as session:
            project = await session.get(Project, job.project_id) if job.project_id else None
            await session.commit()
        if project is None or plan is None or plan.reference is None:
            async with SessionLocal() as session:
                await store.fail_job(session, job.id, "The project no longer exists.")
            return False

        stored = await get_storage().save(speech.temp, project.id, "wav")
        provenance: dict[str, Any] = {
            "model": MODEL_NAME,
            "voice_id": plan.reference.voice_id,
            "script_sha256": recorded.get("script_sha256"),
            "parts": speech.parts,
            "seed": plan.seed,
            "cfg_scale": plan.cfg_scale,
            "job_id": job.id,
        }

        # The voiceover, the project pointing at it and the finished job are saved together or
        # not at all.
        async with SessionLocal() as session:
            asset = await add_asset(
                session,
                project_id=project.id,
                kind="voiceover",
                stored=stored,
                mime="audio/wav",
                size_bytes=speech.temp.size_bytes,
                sha256=speech.temp.sha256,
                source="ai",
                duration_s=speech.duration_s,
                provenance=provenance,
            )
            await session.execute(
                update(Project).where(Project.id == project.id).values(voiceover_asset_id=asset.id)
            )
            output: dict[str, Any] = {
                "asset_id": asset.id,
                "duration_s": speech.duration_s,
                "parts": speech.parts,
                "voice_id": plan.reference.voice_id,
            }
            if not await store.finish_job(session, job.id, output, result_asset_id=asset.id):
                await session.rollback()
                # Cancelled in the meantime. Stored files are never deleted.
                _logger.warning(
                    "job %d: voiceover stored but the job is no longer running: %s",
                    job.id,
                    stored.relative_path,
                )
                return False
            await session.commit()
        _logger.info(
            "voiceover made: project=%d asset=%d %.1fs in %d part(s)",
            project.id,
            asset.id,
            speech.duration_s,
            speech.parts,
        )
        return True
