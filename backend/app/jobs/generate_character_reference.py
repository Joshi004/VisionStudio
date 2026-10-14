"""The `generate_character_reference` job: the reference picture of one cast member (a character
or a place), made by Qwen-Image-2.1 on the GPU server (ANALYSIS.md Section 4.2 and 6.2; project
cast).

It is a remote job, like `generate_frame`, and shares its steps: submit, poll, download and the
failure rules are `RemoteImageHandler`'s (`jobs/remote_image.py`). Its input names the member
(`cast_kind`, `cast_id`). This module is what is particular to a reference picture:

- `start`: check that a picture may be made, build the request (the first time only) and submit.
  It is plain text to image, with no reference of its own: this picture is the one every later
  picture is made from. A character is asked for in the shape 2:3 (a standing figure), a place in
  the nearest shape to the project's frame.
- `store_image`: store the picture exactly as it came, first of all (the server may keep a result
  for one download only), then, for a character, cut the backdrop away
  (`services/background_removal.py`) and store that too. The cut-out is the character's
  reference. A place is kept whole, because the place is the background.
- the member's status: `ready` once the picture is stored. A job that fails leaves a member
  that has no picture `failed`. A member that has one keeps it: the old picture is still good.

**The backdrop is removed on a best-effort basis.** The model that finds the character is
downloaded the first time it is used. When it cannot be, or finds nothing, the picture as it came
(a character on a plain white backdrop) is the reference, the job still succeeds, and its output
says so. A white backdrop is what the picture was asked for, and it is what is sent to the image
model later anyway (`reference_upload.py`).

**It only starts from a click or from an automatic run**, and everything that can be checked for
free is checked before anything is sent: the member's prompt and the approved GPU API (it must
have the image endpoint). The request is built once and stored in `job.input`, so every later
attempt sends the same request (the server's guide says a pre-emption is resubmitted unchanged).

Logs hold ids, sizes and phases, never the prompt.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from app.core import outbound
from app.core import settings as settings_service
from app.db.models import Asset, Job, Project
from app.db.session import SessionLocal
from app.jobs import phases, store
from app.jobs.generate_clip import GPU_URL_KEY, PARTITION_KEY
from app.jobs.generate_frame import IMAGE_MODE_KEY
from app.jobs.remote_image import RemoteImageHandler
from app.providers import contract_guard, image_generator
from app.services import api_contract, background_removal, frame_images, image_models
from app.services import cast as cast_service
from app.services.assets import add_asset
from app.services.frame_images import FrameRejected
from app.services.storage import StorageError, StoredFile, TempFile, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = cast_service.REFERENCE_IMAGE_JOB
# A standing figure is taller than wide.
CHARACTER_SHAPE: Final = "2:3"

_MEMBER_GONE = (
    "The character or the place no longer exists, so no reference picture was made. The "
    "image is kept as asset {raw}."
)


@dataclass
class _Read:
    """What `start` reads before it submits."""

    job_input: dict[str, Any]
    project: Project | None
    kind: str | None
    member_id: int | None
    # The member's prompt as it is now, or None when it has none or does not exist.
    prompt: str | None
    member_name: str | None
    block: str | None
    base_url: str
    partition: str
    mode: image_models.ImageMode
    # The approved OpenAPI document, or None when none is recorded.
    spec: dict[str, Any] | None


@dataclass(frozen=True)
class _Plan:
    request: dict[str, Any]
    recorded: dict[str, Any]


async def _one_chunk(data: bytes) -> AsyncIterator[bytes]:
    yield data


class GenerateCharacterReferenceHandler(RemoteImageHandler):
    job_type = JOB_TYPE

    # --- start: check, prepare (once), submit ------------------------------------------

    async def start(self, job_id: int) -> None:
        try:
            await self._start(job_id)
        finally:
            await self._note_failure(job_id)

    async def _start(self, job_id: int) -> None:
        read = await self._read(job_id)
        if read is None:
            return
        if read.project is None:
            await self._fail(job_id, "The project no longer exists.")
            return
        if read.block is not None:
            await self._fail(job_id, read.block)
            return

        plan = self._stored_plan(read.job_input)
        if plan is None:
            plan = await self._prepare(job_id, read, read.project)
            if plan is None:
                return  # the job was failed, or cancelled, in there
        await self.submit(job_id, read.base_url, plan.request, plan.recorded)

    @staticmethod
    def _stored_plan(job_input: dict[str, Any]) -> _Plan | None:
        """The plan of an earlier attempt, read back from the job's input. None the first time."""
        request = job_input.get("request")
        if (
            not isinstance(request, dict)
            or job_input.get("endpoint") != image_generator.GENERATE_PATH
            or not isinstance(job_input.get("member_sent"), dict)
        ):
            return None
        return _Plan(request=request, recorded=job_input)

    async def _prepare(self, job_id: int, read: _Read, project: Project) -> _Plan | None:
        """Works out the request and stores it on the job, before anything is sent. Runs on the
        first attempt only. Fails the job (returns None) when the approved GPU API has no image
        endpoint, or the request would be refused.
        """
        await self._phase(job_id, phases.PREPARING_IMAGE_REQUEST)
        kind = read.kind or ""
        prompt = read.prompt or ""
        aspect_ratio = (
            CHARACTER_SHAPE
            if kind == cast_service.CHARACTER
            else image_models.pick_aspect_ratio(project.gen_width, project.gen_height)
        )
        try:
            image_generator.check_endpoint(read.spec)
            request = image_generator.build_request(
                prompt=prompt,
                mode=read.mode,
                seed=secrets.randbelow(image_models.SEED_LIMIT),
                aspect_ratio=aspect_ratio,
                partition=read.partition,
            )
        except ValueError as exc:
            await self._fail(job_id, str(exc))
            return None

        expected_width, expected_height = image_models.ASPECT_SIZES[aspect_ratio]
        recorded: dict[str, Any] = {
            **read.job_input,
            "member_sent": {"kind": kind, "id": read.member_id, "name": read.member_name},
            "reference_prompt": prompt,
            "image_model": image_models.MODEL_ID,
            "image_mode": read.mode,
            "aspect_ratio": aspect_ratio,
            "expected_size": {"width": expected_width, "height": expected_height},
            "endpoint": image_generator.GENERATE_PATH,
            "request": request,
        }
        async with SessionLocal() as session:
            if not await store.update_input(session, job_id, recorded):
                return None  # cancelled while preparing: nothing was sent
        return _Plan(request=request, recorded=recorded)

    # --- Reading ----------------------------------------------------------------------

    async def _read(self, job_id: int) -> _Read | None:
        """Everything `start` needs, in one short read. None when there is nothing to run. The
        reasons an image may not be made are worked out here, before anything is sent.
        """
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running" or not isinstance(job.input, dict):
                await session.commit()
                return None
            job_input: dict[str, Any] = dict(job.input)
            project = await session.get(Project, job.project_id)
            target = cast_service.member_of_job(job)
            member = (
                await cast_service.get_member(session, project.id, *target)
                if project is not None and target is not None
                else None
            )
            block: str | None = None
            if project is not None:
                if member is None:
                    block = "The character or the place no longer exists."
                else:
                    block = cast_service.image_block(member)
            base_url = await settings_service.get_str(session, GPU_URL_KEY)
            partition = await settings_service.get_str(session, PARTITION_KEY)
            mode = image_models.resolve_mode(
                await settings_service.get_str(session, IMAGE_MODE_KEY)
            )
            bodies = await contract_guard.latest_bodies(session)
            await session.commit()
        spec = next((body for body in bodies if api_contract.is_openapi(body)), None)
        return _Read(
            job_input=job_input,
            project=project,
            kind=target[0] if target else None,
            member_id=target[1] if target else None,
            prompt=(member.reference_prompt or "").strip() if member is not None else None,
            member_name=member.name if member is not None else None,
            block=block,
            base_url=base_url,
            partition=partition,
            mode=mode,
            spec=spec,
        )

    # --- store_image: the picture, then its cut-out -------------------------------------

    async def store_image(
        self, job: Job, base_url: str, result: outbound.DownloadResult, dest: Path
    ) -> None:
        """The image is downloaded. Stores it exactly as it came, then makes the member's
        reference from it. The raw image is stored and recorded first, and the job's output
        names it, so a failure in any later step keeps it.
        """
        recorded = job.input if isinstance(job.input, dict) else {}
        request = recorded.get("request") if isinstance(recorded.get("request"), dict) else {}
        target = cast_service.member_of_job(job)
        async with SessionLocal() as session:
            project = await session.get(Project, job.project_id) if job.project_id else None
            member = (
                await cast_service.get_member(session, project.id, *target)
                if project is not None and target is not None
                else None
            )
            await session.commit()
        if project is None or target is None or member is None:
            await self._fail_and_purge(
                job,
                base_url,
                "The character or the place no longer exists, so no picture was made.",
            )
            return
        kind, member_id = target

        storage = get_storage()
        output: dict[str, Any] = dict(job.output) if isinstance(job.output, dict) else {}
        try:
            info = await frame_images.run_pillow(frame_images.inspect_image, dest)
        except FrameRejected as exc:
            await self._fail_and_purge(job, base_url, f"The image could not be used: {exc.message}")
            return

        await self._phase(job.id, phases.SAVING_IMAGE)
        remote = output.get("remote") if isinstance(output.get("remote"), dict) else None
        raw_provenance = {
            "role": "reference_raw",
            "provider": "gpu_server",
            "model": recorded.get("image_model") or image_models.MODEL_ID,
            "mode": request.get("mode"),
            "seed": request.get("seed"),
            "aspect_ratio": request.get("aspect_ratio"),
            "endpoint": recorded.get("endpoint"),
            "pipeline": remote.get("pipeline") if remote else None,
            "server_url": recorded.get("server_url"),
            "provider_job_id": job.provider_job_id,
            "job_id": job.id,
            "cast_kind": kind,
            "cast_id": member_id,
            "prompt": recorded.get("reference_prompt"),
            "expected_size": recorded.get("expected_size"),
        }
        try:
            temp = TempFile(path=dest, size_bytes=result.size_bytes, sha256=result.sha256)
            raw_stored = await storage.save(temp, project.id, info.ext)
        except StorageError as exc:
            await self._fail_and_purge(job, base_url, f"The image could not be stored: {exc}")
            return
        async with SessionLocal() as session:
            try:
                raw = await add_asset(
                    session,
                    project_id=project.id,
                    kind="reference",
                    stored=raw_stored,
                    mime=info.mime,
                    size_bytes=result.size_bytes,
                    sha256=result.sha256,
                    source="ai",
                    width=info.width,
                    height=info.height,
                    provenance=raw_provenance,
                )
                await session.commit()
            except BaseException:
                # Stored files are never deleted, so this leaves an unreferenced file behind.
                _logger.warning(
                    "job %d: image stored but not recorded: %s", job.id, raw_stored.relative_path
                )
                raise
        output["raw_asset_id"] = raw.id
        output["returned_size"] = {"width": info.width, "height": info.height}
        async with SessionLocal() as session:
            await store.record_output(session, job.id, dict(output))

        cutout_stored: StoredFile | None = None
        cutout_temp: TempFile | None = None
        if kind == cast_service.CHARACTER:
            await self._phase(job.id, phases.REMOVING_BACKDROP)
            try:
                png = await frame_images.run_pillow(
                    background_removal.remove_background, raw_stored.path
                )
                cutout_temp = await storage.receive(_one_chunk(png), max_bytes=len(png))
                try:
                    cutout_stored = await storage.save(cutout_temp, project.id, "png")
                except BaseException:
                    storage.discard(cutout_temp)
                    raise
            except background_removal.BackgroundRemovalError as exc:
                # Not fatal: the picture on its white backdrop is a good reference too.
                output["background_removed"] = False
                output["background_warning"] = str(exc)
                _logger.warning("job %d: backdrop not removed: %s", job.id, exc)
            except StorageError as exc:
                await self._fail_and_purge(
                    job,
                    base_url,
                    f"The cut-out could not be stored: {exc} The image is kept as asset {raw.id}.",
                )
                return

        saved = await self._save(
            job,
            project=project,
            kind=kind,
            member_id=member_id,
            raw=raw,
            cutout=(cutout_stored, cutout_temp) if cutout_stored and cutout_temp else None,
            size=(info.width, info.height),
            output=output,
        )
        if saved:
            # Best effort: a failure here is recorded and never fails the picture.
            purge = await self._purge(base_url, job.provider_job_id)
            async with SessionLocal() as session:
                await store.merge_output(session, job.id, {"purge": purge})

    # --- Saving the reference ---------------------------------------------------------------

    async def _save(
        self,
        job: Job,
        *,
        project: Project,
        kind: str,
        member_id: int,
        raw: Asset,
        cutout: tuple[StoredFile, TempFile] | None,
        size: tuple[int, int],
        output: dict[str, Any],
    ) -> bool:
        """Records the cut-out (when there is one), makes the picture the member's reference and
        finishes the job: all in one transaction. False when the job could not be finished (the
        member is gone, or the job is no longer running).
        """
        await self._phase(job.id, phases.SAVING_REFERENCE)
        async with SessionLocal() as session:
            member = await cast_service.get_member(session, project.id, kind, member_id)
            if member is None:
                await session.rollback()
                await self._fail(job.id, _MEMBER_GONE.format(raw=raw.id))
                return False
            reference = raw
            if cutout is not None:
                stored, temp = cutout
                reference = await add_asset(
                    session,
                    project_id=project.id,
                    kind="reference",
                    stored=stored,
                    mime="image/png",
                    size_bytes=temp.size_bytes,
                    sha256=temp.sha256,
                    source="derived",
                    width=size[0],
                    height=size[1],
                    provenance={
                        "role": "reference_cutout",
                        "raw_asset_id": raw.id,
                        "background_removal": background_removal.MODEL_NAME,
                        "job_id": job.id,
                        "cast_kind": kind,
                        "cast_id": member_id,
                    },
                )
            cast_service.mark_ready(member, reference.id)
            final = {
                **output,
                "reference_asset_id": reference.id,
                "background_removed": cutout is not None,
            }
            if not await store.finish_job(session, job.id, final, result_asset_id=reference.id):
                await session.rollback()
                _logger.warning(
                    "job %d: picture stored but the job is no longer running: asset %d",
                    job.id,
                    reference.id,
                )
                return False
            await session.commit()
        _logger.info(
            "job %d: reference picture made: %s=%d raw=%d reference=%d backdrop_removed=%s",
            job.id,
            kind,
            member_id,
            raw.id,
            reference.id,
            cutout is not None,
        )
        return True

    # --- A member that has no picture, and whose job failed, is `failed` --------------------

    async def poll(self, job_id: int) -> bool:
        ready = await super().poll(job_id)
        if not ready:
            await self._note_failure(job_id)
        return ready

    async def finish(self, job_id: int) -> None:
        await super().finish(job_id)
        await self._note_failure(job_id)

    @staticmethod
    async def _note_failure(job_id: int) -> None:
        """When the job has failed, marks its member `failed`, unless the member has a picture
        (an older one is still good). Every way a job can fail ends in one of the three entry
        points above, so this is the one place that needs to know.
        """
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            target = cast_service.member_of_job(job) if job is not None else None
            if job is None or job.status != "failed" or target is None or job.project_id is None:
                await session.commit()
                return
            member = await cast_service.get_member(session, job.project_id, *target)
            if member is not None and member.reference_asset_id is None:
                member.status = "failed"
            await session.commit()
