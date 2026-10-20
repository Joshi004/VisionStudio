"""The `discover_environments` job: a language model lists the story's environments (PHASE-005,
`Path_ahead.md` Section 8). All the steps are in `jobs/discovery_job.py`.
"""

from __future__ import annotations

from typing import Final

from app.jobs import phases
from app.jobs.discovery_job import DiscoveryHandler
from app.services import discovery

JOB_TYPE: Final = discovery.SPECS["environments"].job_type


class DiscoverEnvironmentsHandler(DiscoveryHandler):
    job_type = JOB_TYPE
    kind = "environments"
    saving_phase = phases.SAVING_ENVIRONMENTS
