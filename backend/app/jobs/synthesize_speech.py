"""The shared part of the two speech jobs: Breeze TTS on the GPU server (Phase 21).

`lab_voice` (one speech in the Voice lab) and `generate_voiceover` (the voiceover of a project,
made from its script) differ only in what they do with the finished WAV, so both extend
`SpeechHandler` and implement `store_result`.

It is a remote job, so the three steps follow `JobHandler`:

- `start`: upload the voice recording (once, when the speech clones a voice), submit the
  first piece of the text that is not made yet, and save the server's job id.
- `poll`: ask the server about the job once per tick.
- `finish`: when the piece is made, submit the next one (and save its job id). After the last
  one, download every piece, join them, hand the WAV to `store_result` and purge the jobs on
  the server.

**A long script is several requests.** One request takes at most 1000 characters
(`services/speech_chunks.split_script`). The pieces are made one after the other, so the job
shows one cluster job at a time, and every piece uses the same voice recording, seed and
guidance, so the voice stays the same across the pieces. `job.input.done` holds the server's
job ids of the pieces that are made. A pre-emption or a restart continues with the first piece
that is not in it, and the uploaded recording is reused.

**Nothing is purged before the end**: purging a piece also deletes the uploads no other job
uses, and the pieces share the recording.

Failure handling follows the transcription job: a dropped connection never fails the job. It
fails when the server says it failed (other than pre-emption), refuses the request, or returns
something that cannot be used.

Breeze TTS 2's weights and outputs are licensed for research and non-commercial use only.
"""

from __future__ import annotations

import asyncio
import logging
from abc import abstractmethod
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final

from app.core import settings as settings_service
from app.core.urls import docker_mapped
from app.db.models import Job
from app.db.session import SessionLocal
from app.jobs import phases, store
from app.jobs.handlers import JobHandler
from app.jobs.transcribe import SERVER_RETRY_DELAY_S, is_preemption, phase_for_poll_error
from app.providers import gpu_server, speech_synthesizer
from app.providers.gpu_server import GpuCallError
from app.services import ffmpeg, speech_audio
from app.services.storage import StorageError, TempFile, get_storage

_logger = logging.getLogger(__name__)

GPU_URL_KEY: Final = "gpu_api_base_url"
PARTITION_KEY: Final = "gpu_partition"


@dataclass(frozen=True)
class Reference:
    """The saved voice a speech clones, as the job stored it when it was created."""

    voice_id: int
    path: str
    mime: str
    text: str


@dataclass(frozen=True)
class Plan:
    """What the job makes, read back from `job.input`."""

    chunks: list[str]
    instruction: str | None
    seed: int
    cfg_scale: float
    reference: Reference | None
    # The server's job ids of the pieces that are made, in order.
    done: list[str]
    # The id the server gave the uploaded recording, once it is uploaded.
    remote_reference_id: str | None

    @property
    def part(self) -> int:
        """The piece being made, counted from 1."""
        return len(self.done) + 1


@dataclass(frozen=True)
class SpeechFile:
    """The finished speech: a WAV in the temp folder, checked with ffprobe."""

    temp: TempFile
    duration_s: float
    sample_rate: int | None
    channels: int | None
    parts: int


def _reference(value: object) -> Reference | None:
    if not isinstance(value, dict):
        return None
    voice_id, path, mime, text = (value.get(key) for key in ("voice_id", "path", "mime", "text"))
    if (
        isinstance(voice_id, int)
        and isinstance(path, str)
        and isinstance(mime, str)
        and isinstance(text, str)
    ):
        return Reference(voice_id=voice_id, path=path, mime=mime, text=text)
    return None


def read_plan(recorded: object) -> Plan | None:
    """The plan stored on the job, or None when the input is not a speech's."""
    if not isinstance(recorded, dict):
        return None
    chunks, instruction = recorded.get("chunks"), recorded.get("instruction")
    seed, cfg_scale = recorded.get("seed"), recorded.get("cfg_scale")
    done, remote_id = recorded.get("done", []), recorded.get("remote_reference_id")
    if not isinstance(chunks, list) or not chunks or not all(isinstance(c, str) for c in chunks):
        return None
    if not isinstance(done, list) or not all(isinstance(item, str) for item in done):
        return None
    if instruction is not None and not isinstance(instruction, str):
        return None
    if isinstance(seed, bool) or not isinstance(seed, int):
        return None
    if isinstance(cfg_scale, bool) or not isinstance(cfg_scale, int | float):
        return None
    reference = _reference(recorded.get("reference"))
    if recorded.get("reference") is not None and reference is None:
        return None
    return Plan(
        chunks=list(chunks),
        instruction=instruction,
        seed=seed,
        cfg_scale=float(cfg_scale),
        reference=reference,
        done=list(done),
        remote_reference_id=remote_id if isinstance(remote_id, str) else None,
    )


class SpeechHandler(JobHandler):
    provider = "gpu"
    restart_rule = "resume"

    @abstractmethod
    async def store_result(self, job: Job, speech: SpeechFile) -> bool:
        """Stores the finished speech and finishes the job, in one transaction. True when it
        did; False when it failed the job itself or the job was no longer running (the
        server's jobs are then not purged). The WAV is a temp file: move it, do not copy it.
        """

    # --- start: upload and submit ------------------------------------------------------------

    async def start(self, job_id: int) -> None:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running":
                await session.commit()
                return
            base_url = await settings_service.get_str(session, GPU_URL_KEY)
            partition = await settings_service.get_str(session, PARTITION_KEY)
            await session.commit()

        plan = read_plan(job.input)
        if plan is None or len(plan.done) >= len(plan.chunks):
            await self._fail(job_id, "The request for this speech is missing.")
            return
        try:
            await self._submit_part(job, base_url, partition, plan)
        except GpuCallError as exc:
            await self._give_up_starting(job_id, exc)
        except StorageError:
            await self._fail(job_id, "The voice recording could not be found on disk.")

    async def _submit_part(self, job: Job, base_url: str, partition: str, plan: Plan) -> None:
        """Uploads the recording if it is not uploaded yet, submits the piece that is next and
        saves the server's job id together with the pieces that are made. Raises GpuCallError
        and StorageError.

        502 at submit is retried once after a pause, and a 400 for an unknown asset id uploads
        the recording again once. Any other refusal is raised.
        """
        parts = len(plan.chunks)
        remote_reference_id = plan.remote_reference_id
        retried_server_error = False
        retried_asset = False
        while True:
            try:
                if plan.reference is not None and remote_reference_id is None:
                    await self._phase(job.id, phases.UPLOADING_VOICE)
                    remote_reference_id = await self._upload_reference(base_url, plan.reference)
                await self._phase(job.id, phases.speech_part(phases.SUBMITTING, plan.part, parts))
                body = speech_synthesizer.build_body(
                    text=plan.chunks[len(plan.done)],
                    instruction=plan.instruction,
                    reference_remote_id=remote_reference_id,
                    reference_text=plan.reference.text if plan.reference is not None else None,
                    seed=plan.seed,
                    cfg_scale=plan.cfg_scale,
                    partition=partition,
                )
                provider_job_id = await speech_synthesizer.submit(base_url, body)
                break
            except GpuCallError as exc:
                if exc.kind == "server_error" and not retried_server_error:
                    retried_server_error = True
                    await asyncio.sleep(SERVER_RETRY_DELAY_S)
                    continue
                unknown_asset = (
                    exc.status_code == 400 and "invalid asset reference" in exc.message.lower()
                )
                if (
                    exc.kind == "rejected"
                    and unknown_asset
                    and plan.reference is not None
                    and not retried_asset
                ):
                    retried_asset = True  # the server lost the upload: send it again
                    remote_reference_id = None
                    continue
                raise

        submitted = {
            **(job.input if isinstance(job.input, dict) else {}),
            "done": plan.done,
            "remote_reference_id": remote_reference_id,
            "server_url": docker_mapped(base_url),
            "endpoint": speech_synthesizer.SYNTHESIZE_PATH,
            "body": body,
        }
        async with SessionLocal() as session:
            await store.mark_submitted(session, job.id, provider_job_id, submitted)

    @staticmethod
    async def _upload_reference(base_url: str, reference: Reference) -> str:
        path = get_storage().get_path(reference.path)
        extension = path.suffix.lstrip(".").lower()
        filename = f"voice-{reference.voice_id}.{extension}"
        return await gpu_server.upload_file(base_url, path, filename, reference.mime)

    async def _give_up_starting(self, job_id: int, exc: GpuCallError) -> None:
        async with SessionLocal() as session:
            if exc.kind == "unreachable":
                await store.requeue(session, job_id, phases.WAITING_SERVER_UNREACHABLE)
            elif exc.kind == "busy":
                await store.requeue(session, job_id, phases.WAITING_SERVER_BUSY)
            else:
                await store.fail_job(session, job_id, f"Could not start the speech: {exc}")

    # --- poll ----------------------------------------------------------------------------------

    async def poll(self, job_id: int) -> bool:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            base_url = await settings_service.get_str(session, GPU_URL_KEY)
            await session.commit()
        if job is None or job.status != "running" or not job.provider_job_id:
            return False
        plan = read_plan(job.input)
        if plan is None:
            return False

        try:
            remote = await gpu_server.job_status(base_url, job.provider_job_id)
        except GpuCallError as exc:
            await self._record_poll(job_id, phase_for_poll_error(exc))
            return False

        parts = len(plan.chunks)
        if remote.status == "queued":
            await self._record_poll(
                job_id, phases.speech_part(phases.QUEUED_ON_CLUSTER, plan.part, parts)
            )
        elif remote.status == "running":
            await self._record_poll(
                job_id, phases.speech_part(phases.RUNNING_ON_CLUSTER, plan.part, parts)
            )
        elif remote.status == "succeeded":
            return True
        else:
            await self._server_reported_failure(job, remote.error)
        return False

    async def _server_reported_failure(self, job: Job, error: str | None) -> None:
        message = error or "The server reported the job as failed."
        async with SessionLocal() as session:
            if is_preemption(message) and job.attempt < phases.MAX_ATTEMPTS:
                await store.requeue(
                    session, job.id, phases.preempted(job.attempt + 1), next_attempt=True
                )
            else:
                await store.fail_job(
                    session, job.id, f"The GPU server reported an error: {message}"
                )

    # --- finish: the next piece, or join and store -------------------------------------------

    async def finish(self, job_id: int) -> None:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            base_url = await settings_service.get_str(session, GPU_URL_KEY)
            partition = await settings_service.get_str(session, PARTITION_KEY)
            await session.commit()
        if job is None or job.status != "running" or not job.provider_job_id:
            return
        plan = read_plan(job.input)
        if plan is None:
            await self._fail(job_id, "The request for this speech is missing.")
            return

        # A repeat of this call (the next piece could not be submitted a moment ago) finds the
        # piece already in the list.
        if job.provider_job_id not in plan.done:
            plan = replace(plan, done=[*plan.done, job.provider_job_id])
        if len(plan.done) < len(plan.chunks):
            await self._submit_next_part(job, base_url, partition, plan)
            return
        await self._join_and_store(job, base_url, plan)

    async def _submit_next_part(self, job: Job, base_url: str, partition: str, plan: Plan) -> None:
        try:
            await self._submit_part(job, base_url, partition, plan)
        except GpuCallError as exc:
            if exc.kind in ("unreachable", "busy"):
                # The finished piece is still the job's server job: the next tick tries again.
                await self._record_poll(job.id, phase_for_poll_error(exc))
            else:
                await self._fail(job.id, f"Could not start the next part of the speech: {exc}")
        except StorageError:
            await self._fail(job.id, "The voice recording could not be found on disk.")

    async def _join_and_store(self, job: Job, base_url: str, plan: Plan) -> None:
        storage = get_storage()
        temps: list[Path] = []
        try:
            await self._phase(job.id, phases.DOWNLOADING_SPEECH)
            for remote_id in plan.done:
                dest = storage.new_temp_path("wav")
                temps.append(dest)
                try:
                    await gpu_server.download_result(base_url, remote_id, dest)
                except GpuCallError as exc:
                    await self._result_not_downloaded(job, exc)
                    return

            joined = temps[0]
            if len(temps) > 1:
                await self._phase(job.id, phases.JOINING_SPEECH)
                joined = storage.new_temp_path("wav")
                temps.append(joined)
                list_path = storage.new_temp_path("txt")
                temps.append(list_path)
                try:
                    await speech_audio.join_wavs(temps[: len(plan.done)], list_path, joined)
                except speech_audio.JoinError as exc:
                    await self._fail_and_purge(job, base_url, plan, str(exc))
                    return

            await self._phase(job.id, phases.CHECKING_SPEECH)
            probe = await ffmpeg.probe(joined)
            if probe is None or not probe.audio_streams or not probe.duration_s:
                await self._fail_and_purge(
                    job, base_url, plan, "The speech could not be read. Make it again."
                )
                return
            stream = probe.audio_streams[0]
            speech = SpeechFile(
                temp=await storage.describe_temp(joined),
                duration_s=probe.duration_s,
                sample_rate=stream.sample_rate,
                channels=stream.channels,
                parts=len(plan.chunks),
            )
            await self._phase(job.id, phases.SAVING_SPEECH)
            stored = await self.store_result(job, speech)
        finally:
            for temp in temps:
                storage.discard(temp)

        if stored:
            purged = await self._purge_all(base_url, plan.done)
            async with SessionLocal() as session:
                await store.merge_output(session, job.id, {"purge": purged})

    async def _result_not_downloaded(self, job: Job, exc: GpuCallError) -> None:
        """A piece could not be downloaded. Only a result that cannot be had fails the job."""
        async with SessionLocal() as session:
            if exc.kind == "rejected" and exc.status_code == 409:
                return  # not finished after all: the next tick asks again
            if exc.kind == "rejected" and exc.status_code == 410:
                await store.fail_job(
                    session,
                    job.id,
                    "A part of the speech expired on the server before it was downloaded. "
                    "Make the speech again.",
                )
            elif exc.kind == "bad_answer":
                await store.fail_job(session, job.id, f"The speech could not be used: {exc}")
            else:
                await store.record_poll(session, job.id, phase_for_poll_error(exc))

    # --- the server's cleanup (best effort) ---------------------------------------------------

    @staticmethod
    async def _purge_all(base_url: str, remote_ids: list[str]) -> list[dict[str, Any]]:
        """Deletes the finished jobs and the uploads on the server. A failure is recorded and
        ignored.
        """
        answers: list[dict[str, Any]] = []
        for remote_id in remote_ids:
            try:
                answers.append((await gpu_server.purge_job(base_url, remote_id)).to_json())
            except GpuCallError as exc:
                _logger.warning("could not purge server job %s: %s", remote_id, exc)
                answers.append({"error": str(exc)})
        return answers

    async def _fail_and_purge(self, job: Job, base_url: str, plan: Plan, message: str) -> None:
        purged = await self._purge_all(base_url, plan.done)
        async with SessionLocal() as session:
            await store.fail_job(session, job.id, message)
            await store.merge_output(session, job.id, {"purge": purged})

    # --- small helpers ------------------------------------------------------------------------

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="running")

    @staticmethod
    async def _record_poll(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.record_poll(session, job_id, phase)

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
