"""Background jobs (ANALYSIS.md Section 3.3).

- `store.py`: every change to a `job` row.
- `handlers.py`: the interface a job type implements, and the registry.
- `dispatcher.py`: the one loop that moves jobs forward.
- `phases.py`: the phase labels the UI shows.
- one module per job type (`transcribe.py`, `plan_scenes.py`, `draft_descriptions.py`,
  `write_image_prompt.py`, `generate_frame.py`, `generate_clip.py`, `render_final.py`,
  `generate_lab_video.py`, `write_lab_video_prompt.py`, `auto_pipeline.py`,
  `lab_voice.py`, `generate_voiceover.py`, `generate_lab_image.py`,
  `write_last_frame_prompt.py`, `generate_last_frame.py`, the project's cast:
  `extract_cast.py`, `write_character_reference_prompt.py`,
  `generate_character_reference.py`, `assign_cast.py`, and the Character lab:
  `write_character_look_prompt.py`, `write_character_take_prompt.py`).
- `remote_image.py`: the remote steps the Qwen image jobs (`generate_frame`,
  `generate_last_frame`, `generate_character_reference` and `lab_image`) share.
  `scene_frame.py`: what the two scene frame jobs do with the image once it is made.
  `llm_call.py`: the paid call the three cast language model jobs share.
  `reference_upload.py`: the cast pictures a scene's first frame is made from.

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
    from app.jobs.assign_cast import AssignCastHandler
    from app.jobs.auto_pipeline import AutoPipelineHandler
    from app.jobs.draft_descriptions import DraftDescriptionsHandler
    from app.jobs.extract_cast import ExtractCastHandler
    from app.jobs.generate_character_reference import GenerateCharacterReferenceHandler
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
    from app.jobs.write_character_look_prompt import WriteCharacterLookPromptHandler
    from app.jobs.write_character_reference_prompt import WriteCharacterReferencePromptHandler
    from app.jobs.write_character_take_prompt import WriteCharacterTakePromptHandler
    from app.jobs.write_image_prompt import WriteImagePromptHandler
    from app.jobs.write_lab_video_prompt import WriteLabVideoPromptHandler
    from app.jobs.write_last_frame_prompt import WriteLastFramePromptHandler

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
    handlers.register(ExtractCastHandler())
    handlers.register(WriteCharacterReferencePromptHandler())
    handlers.register(GenerateCharacterReferenceHandler())
    handlers.register(AssignCastHandler())
    handlers.register(WriteCharacterLookPromptHandler())
    handlers.register(WriteCharacterTakePromptHandler())
