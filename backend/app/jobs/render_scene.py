"""The `render_scene` job: one scene's video (SCN-003).

It is the `render_story` job (`jobs/render_story.py`) for one scene's window of the story: the
same local job, the same stages and the same FFmpeg commands, on the **timeline stored on the
job** (`job.input.timeline`, frozen when Render scene was pressed by
`services/scene_renders.start_render`). The scene is frame 0 of that timeline. What differs from
a story render is only this:

- a shot with no clip yet is a placeholder: a still picture of the shot's number and description
  held for its planned length (`services/placeholder_frame.py`), with silence;
- the video is stored as a `scene_render` row of its scene (`services/scene_renders`), never as
  a `story_render` row.

It is its own pool, one scene render at a time, beside a story render. Every temporary file is
removed afterwards, whatever happens. Logs hold the job id and the step, never a path's content.
"""

from __future__ import annotations

from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.render_story import RenderFailed, RenderStoryHandler, Timeline
from app.services import scene_renders

JOB_TYPE: Final = scene_renders.JOB_TYPE

_NO_SCENE: Final = "This scene render has no scene. Render the scene again."


class RenderSceneHandler(RenderStoryHandler):
    job_type = JOB_TYPE
    provider = "local"
    restart_rule = "start_again"
    allows_placeholders = True

    @staticmethod
    def _scene_of(recorded: Any) -> str:
        scene_id = recorded.get("scene_id") if isinstance(recorded, dict) else None
        if not isinstance(scene_id, str) or not scene_id:
            raise RenderFailed(_NO_SCENE)
        return scene_id

    async def _add_row(
        self,
        session: AsyncSession,
        *,
        project_id: int,
        job_id: int,
        recorded: Any,
        levels: dict[str, Any],
        path: str,
        size_bytes: int,
        sha256: str,
        width: int | None,
        height: int | None,
        frame_count: int | None,
        duration_s: float | None,
        audio: dict[str, Any] | None,
    ) -> Any:
        return await scene_renders.save_scene_render(
            session,
            project_id=project_id,
            scene_id=self._scene_of(recorded),
            job_id=job_id,
            inputs=recorded["timeline"],
            levels=levels,
            path=path,
            size_bytes=size_bytes,
            sha256=sha256,
            width=width,
            height=height,
            frame_count=frame_count,
            duration_s=duration_s,
            audio=audio,
        )

    def _extra_output(self, recorded: Any, timeline: Timeline) -> dict[str, Any]:
        return {
            "scene_id": self._scene_of(recorded),
            "placeholders": sum(1 for shot in timeline.shots if shot.placeholder is not None),
        }
