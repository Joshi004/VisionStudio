"""Background jobs (ANALYSIS.md Section 3.3).

- `store.py`: every change to a `job` row.
- `handlers.py`: the interface a job type implements, and the registry.
- `dispatcher.py`: the one loop that moves jobs forward.
- `phases.py`: the phase labels the UI shows.
- one module per job type (`transcribe.py`, `plan_scenes.py`, `draft_descriptions.py`,
  `write_image_prompt.py`, `generate_frame.py`, `generate_clip.py`, `render_final.py`,
  `generate_lab_video.py`, `write_lab_video_prompt.py`, `auto_pipeline.py`,
  `lab_voice.py`, `generate_voiceover.py`, `generate_lab_image.py`,
  `write_last_frame_prompt.py`, `generate_last_frame.py`, `write_talk_prompts.py`).
- `remote_image.py`: the remote steps the Qwen image jobs (`generate_frame`,
  `generate_last_frame` and `lab_image`) share. `scene_frame.py`: what the two scene frame jobs
  do with the image once it is made.

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
    from app.jobs.auto_pipeline import AutoPipelineHandler
    from app.jobs.draft_descriptions import DraftDescriptionsHandler
    from app.jobs.generate_clip import GenerateClipHandler
    from app.jobs.generate_frame import GenerateFrameHandler
    from app.jobs.generate_lab_image import GenerateLabImageHandler
    from app.jobs.generate_lab_video import GenerateLabVideoHandler
    from app.jobs.generate_last_frame import GenerateLastFrameHandler
    from app.jobs.generate_voiceover import GenerateVoiceoverHandler
    from app.jobs.lab_voice import LabVoiceHandler
    from app.jobs.plan_scenes import PlanScenesHandler
    from app.jobs.render_final import RenderFinalHandler
    from app.jobs.transcribe import TranscribeHandler
    from app.jobs.write_image_prompt import WriteImagePromptHandler
    from app.jobs.write_lab_video_prompt import WriteLabVideoPromptHandler
    from app.jobs.write_last_frame_prompt import WriteLastFramePromptHandler
    from app.jobs.write_talk_prompts import WriteTalkPromptsHandler

    handlers.register(TranscribeHandler())
    handlers.register(PlanScenesHandler())
    handlers.register(DraftDescriptionsHandler())
    handlers.register(WriteImagePromptHandler())
    handlers.register(GenerateFrameHandler())
    handlers.register(GenerateClipHandler())
    handlers.register(RenderFinalHandler())
    handlers.register(GenerateLabVideoHandler())
    handlers.register(WriteLabVideoPromptHandler())
    handlers.register(AutoPipelineHandler())
    handlers.register(LabVoiceHandler())
    handlers.register(GenerateVoiceoverHandler())
    handlers.register(GenerateLabImageHandler())
    handlers.register(WriteLastFramePromptHandler())
    handlers.register(GenerateLastFrameHandler())
    handlers.register(WriteTalkPromptsHandler())
