"""Background jobs (ANALYSIS.md Section 3.3).

- `store.py`: every change to a `job` row.
- `handlers.py`: the interface a job type implements, and the registry.
- `dispatcher.py`: the one loop that moves jobs forward.
- `phases.py`: the phase labels the UI shows.
- one module per job type: the labs (`generate_lab_video.py`, `write_lab_video_prompt.py`,
  `lab_voice.py`, `generate_lab_image.py`) and the Character lab
  (`write_character_look_prompt.py`, `write_character_take_prompt.py`) and the story stages
  (`write_story_bible.py`, `discover_characters.py`, `discover_environments.py`,
  `discover_scenes.py`, `define_character.py`, `discover_relations.py`, `design_voice.py`,
  `define_environment.py`, `define_scene.py`, `extract_events.py`,
  `resolve_looks_states.py`) and the environment library
  (`write_environment_prompt.py`).
- the steps the three discovery jobs share: `discovery_job.py`.
- the shared steps of the remote (GPU server) jobs: `gpu_job.py` (the constants and the
  retry rules), `remote_video.py` (the video jobs), `remote_image.py` (the Qwen image jobs)
  and `synthesize_speech.py` (the speech jobs).
- `llm_call.py`: the paid call the language model jobs share.

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
    from app.jobs.define_character import DefineCharacterHandler
    from app.jobs.define_environment import DefineEnvironmentHandler
    from app.jobs.define_scene import DefineSceneHandler
    from app.jobs.design_voice import DesignVoiceHandler
    from app.jobs.discover_characters import DiscoverCharactersHandler
    from app.jobs.discover_environments import DiscoverEnvironmentsHandler
    from app.jobs.discover_relations import DiscoverRelationsHandler
    from app.jobs.discover_scenes import DiscoverScenesHandler
    from app.jobs.extract_events import ExtractEventsHandler
    from app.jobs.generate_lab_image import GenerateLabImageHandler
    from app.jobs.generate_lab_video import GenerateLabVideoHandler
    from app.jobs.lab_voice import LabVoiceHandler
    from app.jobs.resolve_looks_states import ResolveLooksStatesHandler
    from app.jobs.write_character_look_prompt import WriteCharacterLookPromptHandler
    from app.jobs.write_character_take_prompt import WriteCharacterTakePromptHandler
    from app.jobs.write_environment_prompt import WriteEnvironmentPromptHandler
    from app.jobs.write_lab_video_prompt import WriteLabVideoPromptHandler
    from app.jobs.write_story_bible import WriteStoryBibleHandler

    handlers.register(GenerateLabVideoHandler())
    handlers.register(WriteLabVideoPromptHandler())
    handlers.register(LabVoiceHandler())
    handlers.register(GenerateLabImageHandler())
    handlers.register(WriteCharacterLookPromptHandler())
    handlers.register(WriteCharacterTakePromptHandler())
    handlers.register(WriteStoryBibleHandler())
    handlers.register(DiscoverCharactersHandler())
    handlers.register(DiscoverEnvironmentsHandler())
    handlers.register(DiscoverScenesHandler())
    handlers.register(DefineCharacterHandler())
    handlers.register(DiscoverRelationsHandler())
    handlers.register(DesignVoiceHandler())
    handlers.register(WriteEnvironmentPromptHandler())
    handlers.register(DefineEnvironmentHandler())
    handlers.register(DefineSceneHandler())
    handlers.register(ExtractEventsHandler())
    handlers.register(ResolveLooksStatesHandler())
