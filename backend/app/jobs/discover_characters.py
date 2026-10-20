"""The `discover_characters` job: a language model lists the story's characters (PHASE-005,
`Path_ahead.md` Section 7). All the steps are in `jobs/discovery_job.py`.
"""

from __future__ import annotations

from typing import Final

from app.jobs import phases
from app.jobs.discovery_job import DiscoveryHandler
from app.services import discovery

JOB_TYPE: Final = discovery.SPECS["characters"].job_type


class DiscoverCharactersHandler(DiscoveryHandler):
    job_type = JOB_TYPE
    kind = "characters"
    saving_phase = phases.SAVING_CHARACTERS
