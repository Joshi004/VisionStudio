"""The `discover_scenes` job: a language model divides the story into its scenes, and code cuts
the author's text into one slice per scene (PHASE-006, `Path_ahead.md` Section 9). Most steps
are in `jobs/discovery_job.py`; this job only changes the request and the check, because the
model gives each scene's opening words and the check places them in the story
(`services/scene_discovery_writer.py`).

It needs nothing from character or environment discovery, so it runs beside them (D-15).
"""

from __future__ import annotations

from typing import Any, Final

from app.jobs import phases
from app.jobs.discovery_job import DiscoveryHandler
from app.services import discovery, scene_discovery_writer

JOB_TYPE: Final = discovery.SPECS["scenes"].job_type


class DiscoverScenesHandler(DiscoveryHandler):
    job_type = JOB_TYPE
    kind = "scenes"
    saving_phase = phases.SAVING_SCENES

    def build_body(
        self,
        story: str,
        bible_content: dict[str, Any],
        model: str,
        library_cast: object,
        explainer: bool = False,
    ) -> dict[str, Any]:
        return scene_discovery_writer.build_request(
            story, bible_content, model=model, explainer=explainer
        )

    def check(
        self, content: str, story: str, library_cast: object, warnings: list[str]
    ) -> dict[str, Any]:
        return scene_discovery_writer.check_scenes(
            scene_discovery_writer.parse_answer(content), story, warnings
        )
