"""Background jobs (ANALYSIS.md Section 3.3).

- `store.py`: every change to a `job` row.
- `handlers.py`: the interface a job type implements, and the registry.
- `dispatcher.py`: the one loop that moves jobs forward.
- `phases.py`: the phase labels the UI shows.
- one module per job type: the labs (`generate_lab_video.py`, `write_lab_video_prompt.py`,
  `lab_voice.py`, `generate_lab_image.py`, `generate_lab_music.py`, `write_lab_music_prompt.py`)
  and the Character lab
  (`write_character_look_prompt.py`, `write_character_take_prompt.py`) and the story stages
  (`write_story_bible.py`, `discover_characters.py`, `discover_environments.py`,
  `discover_scenes.py`, `define_character.py`, `discover_relations.py`, `design_voice.py`,
  `define_environment.py`, `define_scene.py`, `extract_events.py`,
  `resolve_looks_states.py`, `synthesize_speech_unit.py`, `plan_shots.py`, `define_shot.py`,
  `check_shot_continuity.py`, `repair_shot_cut.py`, `compile_shot_prompt.py`, `generate_shot.py`,
  `render_story.py`, `check_shot_takes.py`, `check_take_dialogue.py`,
  `select_shot_references.py`), the run of the whole story pipeline (`story_pipeline.py`)
  and the environment library
  (`write_environment_prompt.py`), the Music Bible (`write_music_bible.py`) and the music themes
  (`write_music_theme_prompt.py`), the music plan (`write_music_plan.py`) and the music cues
  (`write_music_cue.py`, `audit_music_cues.py`) and the rewrite of a rejected music take's prompt
  (`rewrite_music_prompt.py`) and the placement of the music on the timeline (`place_music.py`).
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
    from app.jobs.audit_music_cues import AuditMusicCuesHandler
    from app.jobs.check_shot_continuity import CheckShotContinuityHandler
    from app.jobs.check_shot_takes import CheckShotTakesHandler
    from app.jobs.check_take_dialogue import CheckTakeDialogueHandler
    from app.jobs.compile_shot_prompt import CompileShotPromptHandler
    from app.jobs.define_character import DefineCharacterHandler
    from app.jobs.define_environment import DefineEnvironmentHandler
    from app.jobs.define_scene import DefineSceneHandler
    from app.jobs.define_shot import DefineShotHandler
    from app.jobs.design_voice import DesignVoiceHandler
    from app.jobs.discover_characters import DiscoverCharactersHandler
    from app.jobs.discover_environments import DiscoverEnvironmentsHandler
    from app.jobs.discover_relations import DiscoverRelationsHandler
    from app.jobs.discover_scenes import DiscoverScenesHandler
    from app.jobs.extract_events import ExtractEventsHandler
    from app.jobs.generate_lab_image import GenerateLabImageHandler
    from app.jobs.generate_lab_music import GenerateLabMusicHandler
    from app.jobs.generate_lab_video import GenerateLabVideoHandler
    from app.jobs.generate_shot import GenerateShotHandler
    from app.jobs.lab_voice import LabVoiceHandler
    from app.jobs.place_music import PlaceMusicHandler
    from app.jobs.plan_environment_views import PlanEnvironmentViewsHandler
    from app.jobs.plan_shots import PlanShotsHandler
    from app.jobs.render_story import RenderStoryHandler
    from app.jobs.repair_shot_cut import RepairShotCutHandler
    from app.jobs.resolve_looks_states import ResolveLooksStatesHandler
    from app.jobs.rewrite_music_prompt import RewriteMusicPromptHandler
    from app.jobs.select_shot_references import SelectShotReferencesHandler
    from app.jobs.stage_scene import StageSceneHandler
    from app.jobs.story_pipeline import StoryPipelineHandler
    from app.jobs.synthesize_speech_unit import SynthesizeSpeechUnitHandler
    from app.jobs.write_character_look_prompt import WriteCharacterLookPromptHandler
    from app.jobs.write_character_take_prompt import WriteCharacterTakePromptHandler
    from app.jobs.write_environment_prompt import WriteEnvironmentPromptHandler
    from app.jobs.write_environment_view_prompt import WriteEnvironmentViewPromptHandler
    from app.jobs.write_lab_music_prompt import WriteLabMusicPromptHandler
    from app.jobs.write_lab_video_prompt import WriteLabVideoPromptHandler
    from app.jobs.write_music_bible import WriteMusicBibleHandler
    from app.jobs.write_music_cue import WriteMusicCueHandler
    from app.jobs.write_music_plan import WriteMusicPlanHandler
    from app.jobs.write_music_theme_prompt import WriteMusicThemePromptHandler
    from app.jobs.write_story_bible import WriteStoryBibleHandler

    handlers.register(GenerateLabVideoHandler())
    handlers.register(WriteLabVideoPromptHandler())
    handlers.register(LabVoiceHandler())
    handlers.register(GenerateLabMusicHandler())
    handlers.register(WriteLabMusicPromptHandler())
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
    handlers.register(SynthesizeSpeechUnitHandler())
    handlers.register(PlanShotsHandler())
    handlers.register(DefineShotHandler())
    handlers.register(CheckShotContinuityHandler())
    handlers.register(RepairShotCutHandler())
    handlers.register(CompileShotPromptHandler())
    handlers.register(GenerateShotHandler())
    handlers.register(RenderStoryHandler())
    handlers.register(CheckShotTakesHandler())
    handlers.register(StoryPipelineHandler())
    handlers.register(CheckTakeDialogueHandler())
    handlers.register(SelectShotReferencesHandler())
    handlers.register(StageSceneHandler())
    handlers.register(PlanEnvironmentViewsHandler())
    handlers.register(WriteEnvironmentViewPromptHandler())
    handlers.register(WriteMusicBibleHandler())
    handlers.register(WriteMusicThemePromptHandler())
    handlers.register(WriteMusicPlanHandler())
    handlers.register(WriteMusicCueHandler())
    handlers.register(AuditMusicCuesHandler())
    handlers.register(RewriteMusicPromptHandler())
    handlers.register(PlaceMusicHandler())
