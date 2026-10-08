"""Background jobs (ANALYSIS.md Section 3.3).

- `store.py`: every change to a `job` row.
- `handlers.py`: the interface a job type implements, and the registry.
- `dispatcher.py`: the one loop that moves jobs forward.
- `phases.py`: the phase labels the UI shows.
- one module per job type (`transcribe.py`, `plan_scenes.py`, `draft_descriptions.py`,
  `generate_clip.py`, `render_final.py`).

A new job type is a new handler module plus one line in `register_handlers` below. The
dispatcher loop is not touched.
"""

from __future__ import annotations


def register_handlers() -> None:
    """Registers every job type's handler. Called once, by `dispatcher.start()`.

    Imports are inside the function so that importing `app.jobs` stays cheap and the
    handler modules can import the rest of the package without a cycle.
    """
    from app.jobs import handlers
    from app.jobs.draft_descriptions import DraftDescriptionsHandler
    from app.jobs.generate_clip import GenerateClipHandler
    from app.jobs.plan_scenes import PlanScenesHandler
    from app.jobs.render_final import RenderFinalHandler
    from app.jobs.transcribe import TranscribeHandler

    handlers.register(TranscribeHandler())
    handlers.register(PlanScenesHandler())
    handlers.register(DraftDescriptionsHandler())
    handlers.register(GenerateClipHandler())
    handlers.register(RenderFinalHandler())
