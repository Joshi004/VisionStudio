"""The story pipeline (PHASE-030): the rules of one run that takes a story from its text to a
rendered video with one click.

A run is one `story_pipeline` job (`jobs/story_pipeline.py`). It makes the same jobs the stage
buttons make, in the order of `STEPS`, and skips everything that is up to date. This module holds
what does not touch a stage: the steps and their order, the planning rules (pure), the run's
stored state, and starting, continuing and stopping a run. What "up to date" means for each step
lives in `services/story_pipeline_targets.py`.

- **Steps.** A step is a whole stage ("Define the characters"). It starts when the steps it
  `needs` are complete. A step is complete when every one of its targets (a character, a scene, a
  shot, or the project) is done.
- **Tries.** A target gets at most `MAX_TRIES` jobs per step in one run, paid language model
  calls included: the page says so before the run starts. When no target can go on, the run stops
  and says what is wrong.
- **Pauses.** At the start the user ticks the steps to pause after (none by default). The run
  pauses once a ticked step is complete, only if the run made jobs in it, and goes on when the
  user presses Continue.
- **Scope (PHASE-040).** A run is of scope `all` (everything that is not up to date, including
  what was never made) or `out_of_date` (only what exists and is out of date, plus what those
  regenerations make necessary; anything else is "left alone"). See `plan_step`.
- **Scenes (SCN-004).** A run may be limited to some scenes (`RunOptions.scenes`). It then looks
  only at the targets of those scenes, makes the story-wide work that is missing (never what is
  only out of date), makes no music and no full video, and ends with a render of each scene
  (the step `scene_render`). `remake_from` names one step whose targets in those scenes are made
  again once, even when they are up to date.
- **Overwrites.** Some targets hold what the user chose or wrote (a library character, a
  hand-written relation, a hand-picked narrator voice). The run replaces them only when the user
  allowed it once at the start (`confirm_overwrite`).

The run's state lives in `job.output` (see `new_output`); there is no table of its own.
"""

from __future__ import annotations

import copy
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Final, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, Project
from app.jobs import phases, store
from app.services import discovery
from app.services import review_points as review_rules

JOB_TYPE: Final = store.PIPELINE_RUN_TYPE
# What a run makes: everything that is not up to date, or only what exists and is out of date
# (and what that makes necessary).
Scope = Literal["all", "out_of_date"]
SCOPES: Final[tuple[Scope, ...]] = ("all", "out_of_date")
SCOPE_ALL: Final[Scope] = "all"
SCOPE_OUT_OF_DATE: Final[Scope] = "out_of_date"
# Jobs one target may be given in one step in one run.
MAX_TRIES: Final = 3
# Saved in `job.provider_job_id` so the dispatcher asks the run `poll` at every tick. It is not
# an id on any server.
MARKER: Final = "pipeline"

_ERROR_MAX_CHARS: Final = 300
_MAX_PROBLEMS_SHOWN: Final = 10
# The project as a whole is the one target of a step that has no list of targets.
PROJECT_KEY: Final = "project"


class StoryPipelineError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


# --- The steps ------------------------------------------------------------------------------


StepKind = Literal["story", "scene", "cross"]
# SCN-010 (§4.1 of Scene_pipeline_implementation_phases.md): how a step waits.
# - story: for whole steps (a step starts when every step it needs is complete).
# - scene: a scene's targets wait only for the same scene's targets of the steps they need.
# - cross: like a scene step, but a target reads several scenes (the views of a place) and waits
#   for each of them.
STORY: Final[StepKind] = "story"
SCENE: Final[StepKind] = "scene"
CROSS: Final[StepKind] = "cross"


@dataclass(frozen=True)
class Step:
    key: str
    label: str
    # The steps that must be complete before this one starts.
    needs: tuple[str, ...] = ()
    # True when the step does its work in the run itself and makes no job, so the steps after it
    # can be looked at in the same poll.
    inline: bool = False
    # How the step waits (SCN-010). A step that is not "story" is part of the scene lanes.
    kind: StepKind = STORY
    # The needs of a lane step that are waited for as whole steps, like a story-wide need: every
    # scene must be done there. The other needs of a lane step are waited for scene by scene.
    whole: tuple[str, ...] = ()


# The order is a valid order to look at the steps in: each comes after the steps it needs.
STEPS: Final[tuple[Step, ...]] = (
    Step("story_bible", "Story Bible"),
    Step("character_discovery", "Find the characters", ("story_bible",)),
    Step("environment_discovery", "Find the environments", ("story_bible",)),
    Step("scene_discovery", "Find the scenes", ("story_bible",)),
    Step(
        "links",
        "Link to the libraries",
        ("character_discovery", "environment_discovery"),
        inline=True,
    ),
    Step("relations", "Character relations", ("character_discovery",)),
    Step("character_definitions", "Define the characters", ("links", "relations")),
    Step(
        "environment_definitions",
        "Define the environments and draw their pictures",
        ("links", "scene_discovery"),
    ),
    Step("character_images", "Draw the characters", ("character_definitions",)),
    Step("voices", "Voices and narrator", ("character_definitions",)),
    Step(
        "scene_definitions",
        "Define the scenes",
        ("character_definitions", "environment_definitions"),
        kind=SCENE,
    ),
    Step("events", "Extract the events", ("scene_definitions",), kind=SCENE),
    # MUSIC-006: the story's musical identity. Skipped as complete when the project's music is
    # switched off.
    Step("music_bible", "Write the Music Bible", ("events",)),
    # MUSIC-007: a recording of each theme, and its emotional versions. Also skipped as complete
    # when music is switched off.
    Step("music_themes", "Record the themes", ("music_bible",)),
    Step("resolution", "Resolve looks and states", ("scene_definitions",)),
    Step(
        "scene_staging",
        "Stage the scenes",
        ("scene_definitions", "events", "environment_definitions"),
        kind=SCENE,
    ),
    # SCN-010: the views of a place are planned from every scene set there, so a place waits for
    # each of its scenes to be staged (scene by scene), and every scene's place must be known
    # first (the whole of the scene definitions).
    Step(
        "environment_views",
        "Plan and draw the views of each place",
        ("scene_staging", "scene_definitions"),
        kind=CROSS,
        whole=("scene_definitions",),
    ),
    Step(
        "look_state_images",
        "Draw the looks and states",
        ("resolution", "character_images", "environment_definitions", "environment_views"),
    ),
    Step("speech_units", "Plan the speech", ("events",), inline=True, kind=SCENE),
    Step("speech_synthesis", "Speak the lines", ("speech_units", "voices"), kind=SCENE),
    # An explainer's captions and callouts follow the spoken words (EXPLAINER-007). Nothing
    # after it waits for it yet; the render will (EXPLAINER-008).
    Step("word_timings", "Time the words", ("speech_synthesis",), kind=SCENE),
    # EXPLAINER-009: the callouts an explainer shows on the picture. They are written from the
    # speech units alone (times are estimated), so the step does not wait for the voices.
    # Skipped as complete for a story and for an explainer with callouts off. Nothing after it
    # waits for it yet; the render will (EXPLAINER-010).
    Step("callout_plan", "Plan the callouts", ("speech_units",)),
    # EXG-002: the one look every graphic of a continuous explainer with graphics on shares. It
    # is written from the Story Bible alone. Skipped as complete for any other project. Nothing
    # after it waits for it yet; the graphics will (EXG-005).
    Step("graphic_theme", "Design the graphics look", ("story_bible",)),
    Step("shot_plans", "Plan the shots", ("speech_synthesis", "scene_staging"), kind=SCENE),
    # EXG-004: the brief of each graphic shot the cut planner chose, written from the shot's words
    # and the sentences around them. Skipped as complete for any project that is not a continuous
    # explainer with graphics on. A project with graphics on but no graphic shot has no targets.
    Step("graphic_briefs", "Write the graphic briefs", ("shot_plans",), kind=SCENE),
    # EXG-005: both versions of each graphic shot, a generated component and a block scene,
    # drawn to an exact clip. It needs the briefs and the video's theme. Skipped as complete for
    # any project that is not a continuous explainer with graphics on. The music placement and
    # the render wait for it (EXG-007): a graphic shot is a clip of the timeline.
    Step("graphics", "Make the graphics", ("graphic_briefs", "graphic_theme"), kind=SCENE),
    # MUSIC-008: where score, ambience, hits and silence go. It needs every scene's timeline and
    # runs beside the shot definitions (QM-16, option b). Skipped as complete when music is off.
    Step("music_plan", "Plan the music", ("shot_plans", "music_bible")),
    Step(
        "shot_definitions",
        "Define the shots",
        ("shot_plans", "resolution", "environment_views"),
        kind=SCENE,
    ),
    # MUSIC-009: the exact detail of each cue and its prompts, then an audit of all prompts. A cue
    # may send the plan back once (a revision target in this step). Skipped when music is off.
    Step(
        "music_cues",
        "Detail the music cues",
        ("music_plan", "music_themes", "shot_definitions"),
    ),
    # MUSIC-010: a recording (a take) of each prompt of each cue, checked, and the first that
    # passes selected. A target for each item. Skipped when music is off.
    Step("music_generation", "Generate the music", ("music_cues",)),
    Step("shot_continuity", "Check shot continuity", ("shot_definitions",), kind=SCENE),
    Step(
        "references",
        "Choose the references",
        ("shot_continuity", "look_state_images"),
        kind=SCENE,
    ),
    Step(
        "generation_requests",
        "Plan the generation requests",
        ("references",),
        inline=True,
        kind=SCENE,
    ),
    Step("prompts", "Compile the shot prompts", ("generation_requests",), kind=SCENE),
    Step("shot_generation", "Generate the clips", ("prompts",), kind=SCENE),
    # SCN-004, SCN-010: the render of each scene: the end of its lane. A run of some scenes
    # renders those scenes only. It waits for the callout plan (a scene render refuses while
    # one is wanted and not current) and for every shot plan (the scene's start time on the
    # story's timeline is the sum of the scenes before it).
    Step(
        "scene_render",
        "Render the scenes",
        ("shot_generation", "graphics", "callout_plan", "shot_plans"),
        kind=SCENE,
        whole=("shot_plans",),
    ),
    # MUSIC-011: the exact place of every selected music take on the render's own timeline. It
    # needs the takes of the music and of the shots. Skipped as complete when music is off.
    # The render waits for it (MUSIC-012): it mixes the placed music in.
    # EXG-007: both also wait for the graphics, whose videos are shots of the timeline.
    Step(
        "music_placement",
        "Place the music",
        ("music_generation", "shot_generation", "graphics"),
    ),
    Step("render", "Render the video", ("shot_generation", "music_placement", "graphics")),
)

STEP_KEYS: Final = tuple(step.key for step in STEPS)
STEP_LABELS: Final = {step.key: step.label for step in STEPS}
STEPS_BY_KEY: Final = {step.key: step for step in STEPS}


def is_lane_step(step: Step) -> bool:
    """Whether a step is part of the scene lanes (per scene or across scenes). Pure."""
    return step.kind != STORY


def hard_needs(step: Step) -> tuple[str, ...]:
    """The needs that must be complete, for every scene, before a step is looked at. A story-wide
    step waits for all its needs. A lane step waits for its story-wide needs and for the needs
    named in `whole`; the others are waited for scene by scene (`lane_needs`). Pure.
    """
    if not is_lane_step(step):
        return step.needs
    return tuple(
        key for key in step.needs if key in step.whole or not is_lane_step(STEPS_BY_KEY[key])
    )


def lane_needs(step: Step) -> tuple[str, ...]:
    """The needs of a lane step that are waited for scene by scene. Pure."""
    if not is_lane_step(step):
        return ()
    hard = set(hard_needs(step))
    return tuple(key for key in step.needs if key not in hard)


def lane_steps() -> tuple[Step, ...]:
    """The steps of the scene lanes, in the order of `STEPS`."""
    return tuple(step for step in STEPS if is_lane_step(step))


# SCN-004: the steps a run of some scenes does not look at. The music is planned and placed for
# the whole story, and the full video is rendered from all of it (S-2, S-8).
SCENE_RUN_SKIPS: Final[frozenset[str]] = frozenset(
    {
        "music_bible",
        "music_themes",
        "music_plan",
        "music_cues",
        "music_generation",
        "music_placement",
        "render",
    }
)
# SCN-004: the steps a scene run can make again from, once, although they are up to date. Each
# stage's own start function makes a new version for a target that is up to date; the choosing of
# references and the generation requests do not (they skip it), and a clip needs its chain, so
# neither is offered.
REMAKE_STEPS: Final[tuple[str, ...]] = (
    "scene_definitions",
    "events",
    "scene_staging",
    "speech_units",
    "shot_plans",
    "shot_definitions",
    "prompts",
)


def _check_graph() -> None:
    """Every step comes after the steps it needs: the order of `STEPS` is then a valid order to
    look at them in, and the graph has no cycle.
    """
    seen: set[str] = set()
    for step in STEPS:
        if step.key in seen:
            raise ValueError(f"step {step.key} is listed twice")
        unknown = [key for key in step.needs if key not in seen]
        if unknown:
            raise ValueError(f"step {step.key} needs {unknown}, not before it")
        stray = [key for key in step.whole if key not in step.needs]
        if stray:
            raise ValueError(f"step {step.key} lists {stray} as whole, but does not need them")
        if step.whole and step.kind == STORY:
            raise ValueError(f"step {step.key} is story-wide: it waits for whole steps anyway")
        seen.add(step.key)


_check_graph()


def _check_review_points() -> None:
    """Every step a review point names exists, no step is in two review points, and a review
    point held scene by scene has only steps of the scene lanes.
    """
    seen: set[str] = set()
    for point in review_rules.REVIEW_POINTS:
        for key in point.steps:
            if key not in STEP_KEYS:
                raise ValueError(f"review point {point.key} names the unknown step {key}")
            if key in seen:
                raise ValueError(f"step {key} is in two review points")
            if point.per_scene and not is_lane_step(STEPS_BY_KEY[key]):
                raise ValueError(f"review point {point.key} is per scene, but {key} is not")
            seen.add(key)


_check_review_points()


def _check_scene_run_steps() -> None:
    """The steps of a scene run exist, and a step to remake from is not skipped."""
    for name, keys in (("SCENE_RUN_SKIPS", SCENE_RUN_SKIPS), ("REMAKE_STEPS", REMAKE_STEPS)):
        unknown = [key for key in keys if key not in STEP_KEYS]
        if unknown:
            raise ValueError(f"{name} names the unknown step {unknown[0]}")
    if SCENE_RUN_SKIPS & set(REMAKE_STEPS):
        raise ValueError("a step cannot be both skipped and remade in a scene run")


_check_scene_run_steps()


# --- What the user chose when starting ------------------------------------------------------


@dataclass(frozen=True)
class RunOptions:
    """The choices made once, at the start of a run."""

    # The keys of the steps to pause after.
    pause_after: frozenset[str] = frozenset()
    # Whether the run may replace what the user chose or wrote.
    confirm_overwrite: bool = False
    # What the run makes (PHASE-040).
    scope: Scope = SCOPE_ALL
    # The keys of the project's review points that the run stops at (PHASE-041). Copied from the
    # project when the run starts, so changing the settings does not change a run that is going.
    review_points: frozenset[str] = frozenset()
    # The ids of the scenes the run is limited to (SCN-004). Empty: the whole story.
    scenes: frozenset[str] = frozenset()
    # The step whose targets in those scenes are made again once. Only with scenes.
    remake_from: str | None = None

    @classmethod
    def from_input(cls, value: object) -> RunOptions:
        data: dict[str, Any] = value if isinstance(value, dict) else {}
        keys = data.get("pause_after")
        points = data.get("review_points")
        chosen = data.get("scenes")
        scenes = frozenset(
            item for item in (chosen if isinstance(chosen, list) else []) if isinstance(item, str)
        )
        remake = data.get("remake_from")
        return cls(
            pause_after=frozenset(
                key for key in (keys if isinstance(keys, list) else []) if key in STEP_KEYS
            ),
            confirm_overwrite=data.get("confirm_overwrite") is True,
            scope=SCOPE_OUT_OF_DATE if data.get("scope") == SCOPE_OUT_OF_DATE else SCOPE_ALL,
            review_points=frozenset(
                review_rules.normalize(points if isinstance(points, list) else [])
            ),
            scenes=scenes,
            remake_from=remake if scenes and remake in REMAKE_STEPS else None,
        )


# --- Targets and plans ----------------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    """One thing a step must get done: a character, a scene, a shot, or the project."""

    key: str
    # What a problem names ("Mira", "Scene 2: The cellar"). Empty for the project.
    label: str
    done: bool
    # A job (or look, or picture) of this step is queued or running for it, whoever started it.
    active: bool = False
    # Why nothing can be made for it now. Another try would not help.
    block: str | None = None
    # The stage's own follow-on work for it has not shown up yet (a re-plan, the repairs of a
    # check). The run waits a little instead of reporting it.
    settling: bool = False
    # What the user must allow before it is replaced. None when nothing needs allowing.
    consent: str | None = None
    # Why its newest job failed, for the message when its tries are used up.
    last_error: str | None = None
    # Targets of the same step that must be done first (a character drawn from another one).
    waits_for: tuple[str, ...] = ()
    # What the start function of the stage needs to find it (a scene id, a shot id).
    ref: tuple[str, ...] = ()
    # An output of this target exists and its stage says it is out of date (PHASE-040). Only the
    # `out_of_date` scope reads it.
    stale: bool = False
    # The targets that belong together (the scene of a shot or a line). None: the whole step.
    group: str | None = None
    # The stage already has something for this target that is not usable (a shot whose clips
    # all failed). It is not a missing target, so the `out_of_date` scope does not add it.
    existing: bool = False
    # The user rejected this target at a review point (PHASE-041): it is done, and is made
    # again. Set by `plan_step`, never by an adapter. The stage's start function is then given
    # consent to replace it, because rejecting it is what asks for that.
    redo: bool = False
    # The scenes a target that belongs to several scenes is for (a place the views of which are
    # planned from the scenes set there). Empty for any other target (SCN-004).
    scenes: tuple[str, ...] = ()
    # The scene run asked for this target to be made again although it is done. Set by
    # `plan_step`, never by an adapter. Unlike `redo`, the user's consent is still needed.
    remake: bool = False


def target_scenes(target: Target) -> tuple[str, ...]:
    """The scenes a target belongs to: its own scene, or the scenes it reads. None for a
    story-wide target. Pure.
    """
    if target.group is not None:
        return (target.group,)
    return target.scenes


@dataclass(frozen=True)
class Open:
    """The scenes a step of the scene lanes is not finished for (SCN-010). `everything` also
    covers the targets that belong to no scene, and a step the run has not got to yet.
    """

    scenes: frozenset[str] = frozenset()
    everything: bool = False

    @property
    def is_open(self) -> bool:
        return self.everything or bool(self.scenes)

    def has(self, scene_id: str) -> bool:
        return self.everything or scene_id in self.scenes

    def __or__(self, other: Open) -> Open:
        return Open(self.scenes | other.scenes, self.everything or other.everything)


CLOSED: Final = Open()
EVERYTHING: Final = Open(everything=True)


def union_open(opens: Collection[Open]) -> Open:
    """The scenes open in any of `opens`. Pure."""
    result = CLOSED
    for item in opens:
        result = result | item
    return result


def reachable(target: Target, upstream: Open) -> bool:
    """Whether a target of a lane step may be started now: nothing it comes after is still open
    for its scene (for each of its scenes, when it reads several). A target of no scene waits
    until nothing upstream is open at all. Pure.
    """
    if upstream.everything:
        return False
    scenes = target_scenes(target)
    if not scenes:
        return not upstream.scenes
    return not any(scene_id in upstream.scenes for scene_id in scenes)


@dataclass(frozen=True)
class StepView:
    """Where one step stands, read from its stage."""

    targets: list[Target]
    # Things to tell the user that are not problems.
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Started:
    """What starting one target did: the jobs it made (none for work done inline) or why it
    could not.
    """

    target: Target
    job_ids: tuple[int, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class Problem:
    step_key: str
    target_key: str
    label: str
    tries: int
    message: str
    # The scenes the target belongs to (SCN-010): what a problem holds back in the lanes.
    scenes: tuple[str, ...] = ()

    def text(self) -> str:
        message = self.message if self.message.endswith((".", "!", "?")) else f"{self.message}."
        return f"{self.label}: {message}" if self.label and self.label not in message else message

    def as_json(self) -> dict[str, Any]:
        return {
            "step": self.step_key,
            "target": self.target_key,
            "label": self.label,
            "tries": self.tries,
            "message": self.message,
        }


@dataclass(frozen=True)
class StepPlan:
    done: int
    total: int
    # Targets with work in progress (or about to settle).
    waiting: int
    creates: list[Target]
    problems: list[Problem]
    warnings: list[str] = field(default_factory=list)
    # Targets the `out_of_date` scope leaves as they are. They are not in `done` or `total`.
    left_alone: int = 0
    # The scenes this step is not finished for, from its own targets (SCN-010). The step's
    # whole openness also includes what is open upstream.
    unfinished: Open = CLOSED
    # The scenes with work going on in this step, or about to start (SCN-010).
    busy: frozenset[str] = frozenset()
    # Targets that wait for the same scene's upstream and were not looked at (SCN-010).
    upstream_waiting: int = 0

    @property
    def complete(self) -> bool:
        return self.done == self.total


def _short(text: str) -> str:
    one_line = " ".join(text.split())
    if len(one_line) <= _ERROR_MAX_CHARS:
        return one_line
    return f"{one_line[: _ERROR_MAX_CHARS - 1]}…"


def exhausted_message(tries: int, last_error: str | None) -> str:
    """Why a target that was tried `MAX_TRIES` times is reported."""
    reason = _short(last_error) if last_error else "it finished, but the result is still missing"
    return f"Tried {tries} times without success. The last try: {reason}"


def consent_message(consent: str) -> str:
    return (
        f"{consent} Tick “Allow overwrite” when you start the pipeline, and run it again. "
        "Until then this is left as it is."
    )


def is_story_wide(target: Target) -> bool:
    """Whether a target belongs to no scene in particular (a character, the Story Bible, the
    project). Pure.
    """
    return target.group is None and not target.scenes


def in_run_scenes(target: Target, scenes: Collection[str]) -> bool:
    """Whether a run limited to `scenes` looks at a target at all (SCN-004). Pure.

    With no scenes the run is of the whole story. Otherwise it looks at the targets of those
    scenes, the targets of a place that one of them is set in, and the story-wide targets.
    """
    if not scenes:
        return True
    if target.group is not None:
        return target.group in scenes
    if target.scenes:
        return any(scene_id in scenes for scene_id in target.scenes)
    return True


def in_scope(
    target: Target, options: RunOptions, made_upstream: bool, groups: set[str | None]
) -> bool:
    """Whether the run looks at a target that is not done. Pure.

    Scope `all`: always. Scope `out_of_date`: a target whose output is out of date, one that is
    being worked on, or one that was never made but that the run's own work upstream makes
    necessary (`made_upstream`) in a group that already has an output (a new shot of a scene
    that was planned again). Everything else is left alone.

    A run of some scenes (SCN-004) makes story-wide work that is missing, but leaves alone
    what exists and is out of date: that changes more than the scenes it was started for. The
    stages of the scenes then say so (their upstream is out of date) instead of making it.
    """
    if options.scenes and is_story_wide(target) and target.stale and not target.active:
        return False
    if options.scope == SCOPE_ALL:
        return True
    if target.stale or target.active or target.settling or target.redo or target.remake:
        return True
    return made_upstream and not target.existing and target.group in groups


def plan_step(
    step: Step,
    view: StepView,
    tries: Mapping[str, int],
    errors: Mapping[str, str],
    options: RunOptions,
    made_upstream: bool = False,
    rejected: Collection[str] = (),
    remake: bool = False,
    upstream: Open | None = None,
) -> StepPlan:
    """What to do now about a step. Pure.

    For each target that is not done, in this order: leave it alone when the scope says so; wait
    when work is in progress for it; wait when its scene is still open upstream (`upstream`,
    SCN-010); wait when a target it waits for is not done yet; wait while the stage's own
    follow-on work settles; report it when it needs consent that was not given, when nothing can
    be made for it, or when it has had `MAX_TRIES`; otherwise create the next job.

    `upstream` is what is still open in the lane steps this step comes after, and the scenes held
    back by a review. A target whose scene is open there is neither made nor reported: it is
    counted in `upstream_waiting`, and its scene stays open in `StepPlan.unfinished`. None: no
    scene lanes (every need is complete).

    `made_upstream` is whether the run has made work in a step this one needs (scope
    `out_of_date` only).

    `rejected` holds the keys of the targets the user rejected at a review point (PHASE-041).
    Such a target is not done until it has been made again: while nothing was started for it
    (`tries` is 0), while work is in progress for it, and while its newest job failed.

    A run of some scenes (`options.scenes`, SCN-004) looks only at the targets of those scenes
    (`in_run_scenes`). With `remake` (the step the run was told to remake from) every done
    target of a scene is made again in the same way, but unlike a rejected target it still needs
    the user's consent to replace what the user wrote.
    """
    targets = [target for target in view.targets if in_run_scenes(target, options.scenes)]
    pending: list[Target] = []
    for target in targets:
        again = target.active or not tries.get(target.key, 0) or target.last_error is not None
        if not target.done:
            pending.append(target)
        elif target.key in rejected and again:
            pending.append(replace(target, done=False, redo=True))
        elif remake and not is_story_wide(target) and again:
            pending.append(replace(target, done=False, remake=True))
    # The groups that already have an output (a done or an out-of-date target, or one that is
    # being worked on): what "the same scene already has shots" is judged by.
    groups = {target.group for target in targets if target.done or target.stale or target.active}
    left_alone = [
        target for target in pending if not in_scope(target, options, made_upstream, groups)
    ]
    left_keys = {target.key for target in left_alone}
    pending = [target for target in pending if target.key not in left_keys]
    pending_keys = {target.key for target in pending}
    waiting = 0
    creates: list[Target] = []
    problems: list[Problem] = []
    progressing: set[str] = set()
    following: list[Target] = []
    upstream_waiting = 0

    for target in pending:
        tried = tries.get(target.key, 0)
        scenes = target_scenes(target)
        if target.active:
            waiting += 1
            progressing.add(target.key)
        elif upstream is not None and not reachable(target, upstream):
            upstream_waiting += 1
        elif any(key in pending_keys for key in target.waits_for):
            following.append(target)
        elif target.settling:
            waiting += 1
            progressing.add(target.key)
        elif target.block is not None:
            problems.append(
                Problem(step.key, target.key, target.label, tried, target.block, scenes)
            )
        elif target.consent is not None and not options.confirm_overwrite and not target.redo:
            problems.append(
                Problem(
                    step.key,
                    target.key,
                    target.label,
                    tried,
                    consent_message(target.consent),
                    scenes,
                )
            )
        elif tried >= MAX_TRIES:
            message = exhausted_message(tried, errors.get(target.key) or target.last_error)
            problems.append(Problem(step.key, target.key, target.label, tried, message, scenes))
        else:
            creates.append(target)
            progressing.add(target.key)

    # A target that waits is decided last: the one it waits for may itself be waiting.
    for target in following:
        blockers = [key for key in target.waits_for if key in pending_keys]
        if all(key in progressing for key in blockers):
            waiting += 1
            progressing.add(target.key)
        # Otherwise the one it waits for is reported, and counting this one as going on would
        # keep the run alive for ever.

    pending_count = len(targets) - len(left_alone)
    unfinished_scenes = frozenset(
        scene_id for target in pending for scene_id in target_scenes(target)
    )
    return StepPlan(
        done=pending_count - len(pending),
        total=pending_count,
        waiting=waiting,
        creates=creates,
        problems=problems,
        warnings=list(view.warnings),
        left_alone=len(left_alone),
        unfinished=Open(
            unfinished_scenes, everything=any(not target_scenes(target) for target in pending)
        ),
        busy=frozenset(
            scene_id
            for target in pending
            if target.key in progressing
            for scene_id in target_scenes(target)
        ),
        upstream_waiting=upstream_waiting,
    )


def failure_message(done: int, total: int, problems: Sequence[Problem]) -> str:
    """What a stopped run says: how far it got, and what is wrong, step by step."""
    shown = problems[:_MAX_PROBLEMS_SHOWN]
    by_step: dict[str, list[str]] = {}
    for problem in shown:
        by_step.setdefault(problem.step_key, []).append(problem.text())
    parts = " ".join(
        f"{STEP_LABELS.get(key, key)}: {' '.join(texts)}" for key, texts in by_step.items()
    )
    more = len(problems) - len(shown)
    tail = f" And {more} more." if more > 0 else ""
    return f"Stopped with {done} of {total} steps done. {parts}{tail}"


def idle_message(done: int, total: int, incomplete: Sequence[Step]) -> str:
    """What a run says when nothing is running, nothing can be started and nothing is reported,
    yet it is not finished. It should not happen: it is a way out, so a run never hangs.
    """
    labels = ", ".join(step.label.lower() for step in incomplete)
    return (
        f"Stopped with {done} of {total} steps done: nothing is running and nothing can be "
        f"started, but these steps are not complete: {labels}. Run the pipeline again to try "
        "them."
    )


# --- The run's stored state -----------------------------------------------------------------

StepStatus = Literal["pending", "running", "done", "skipped", "failed"]
COMPLETE_STATUSES: Final = ("done", "skipped")


def new_output() -> dict[str, Any]:
    """The output of a run that has just started: every step waiting, nothing made yet."""
    return {
        "steps": {
            step.key: {"status": "pending", "done": 0, "total": 0, "left_alone": 0}
            for step in STEPS
        },
        # step key -> target key -> how many jobs this run has given the target.
        "tries": {step.key: {} for step in STEPS},
        # step key -> target key -> why the newest try failed.
        "errors": {step.key: {} for step in STEPS},
        # The id of every job this run made (the stages that make no job add none).
        "job_ids": [],
        "problems": [],
        "warnings": [],
        # The step the run is paused after, or None.
        "paused_at": None,
        # The steps the user has already pressed Continue after.
        "continued": [],
        # The review point the run waits at (PHASE-041), or None.
        "review_at": None,
        # The review points the user has already passed (approved, or nothing was made in them).
        "reviewed": [],
        # step key -> the targets the user rejected, to be made again.
        "rejected": {},
        # True after Continue: the next look reads the steps that were complete again, so what
        # was edited during the pause is seen.
        "recheck": False,
        # SCN-010: step key -> the scenes the run has made work for in it. A scene that the run
        # made nothing for in a review point passes the point without waiting.
        "made_in": {},
        # SCN-010: review point key -> the scenes that have passed it (approved, or nothing was
        # made for them there). Only the points held scene by scene.
        "scene_reviewed": {},
        # SCN-010: scene id -> the review point the scene waits at for the user.
        "scene_review_at": {},
        # SCN-010: where every scene stands, in story order (see `lane_summary`).
        "lanes": [],
        # SCN-010: how many of the answers to scene reviews in the run's input are applied.
        "answers_applied": 0,
    }


def read_output(value: object) -> dict[str, Any]:
    """A copy of a run's stored output that is safe to change (the stored JSON is replaced by a
    new object, never changed in place). Anything that is not a run's output starts afresh.
    """
    if not isinstance(value, dict) or not isinstance(value.get("steps"), dict):
        return new_output()
    output: dict[str, Any] = copy.deepcopy(value)
    fresh = new_output()
    for key in STEP_KEYS:
        if not isinstance(output["steps"].get(key), dict):
            output["steps"][key] = fresh["steps"][key]
    for name in ("tries", "errors"):
        if not isinstance(output.get(name), dict):
            output[name] = fresh[name]
        for key in STEP_KEYS:
            if not isinstance(output[name].get(key), dict):
                output[name][key] = {}
    for name in ("job_ids", "problems", "warnings", "continued", "reviewed"):
        if not isinstance(output.get(name), list):
            output[name] = []
    for name in ("paused_at", "review_at"):
        if not isinstance(output.get(name), str):
            output[name] = None
    rejected = output.get("rejected")
    output["rejected"] = (
        {
            key: [target for target in targets if isinstance(target, str)]
            for key, targets in rejected.items()
            if key in STEP_KEYS and isinstance(targets, list)
        }
        if isinstance(rejected, dict)
        else {}
    )
    output["recheck"] = output.get("recheck") is True
    output["made_in"] = _scene_lists(output.get("made_in"), STEP_KEYS)
    output["scene_reviewed"] = _scene_lists(
        output.get("scene_reviewed"), review_rules.REVIEW_POINT_KEYS
    )
    waiting = output.get("scene_review_at")
    output["scene_review_at"] = (
        {
            scene_id: point
            for scene_id, point in waiting.items()
            if isinstance(scene_id, str) and point in review_rules.POINTS_BY_KEY
        }
        if isinstance(waiting, dict)
        else {}
    )
    lanes = output.get("lanes")
    lane_list = lanes if isinstance(lanes, list) else []
    output["lanes"] = [item for item in lane_list if isinstance(item, dict)]
    applied = output.get("answers_applied")
    output["answers_applied"] = (
        applied if isinstance(applied, int) and not isinstance(applied, bool) else 0
    )
    return output


def _scene_lists(value: object, keys: Collection[str]) -> dict[str, list[str]]:
    """A stored map from a step or point key to scene ids, with anything else dropped."""
    if not isinstance(value, dict):
        return {}
    return {
        key: [scene_id for scene_id in scenes if isinstance(scene_id, str)]
        for key, scenes in value.items()
        if key in keys and isinstance(scenes, list)
    }


def complete_keys(output: Mapping[str, Any]) -> set[str]:
    """The steps the run has passed: complete, or complete when it got to them."""
    return {key for key in STEP_KEYS if output["steps"][key].get("status") in COMPLETE_STATUSES}


def record_progress(
    output: dict[str, Any], step_key: str, plan: StepPlan, *, status: StepStatus
) -> None:
    entry = output["steps"][step_key]
    entry["status"] = status
    entry["done"] = plan.done
    entry["total"] = plan.total
    entry["left_alone"] = plan.left_alone


def made_no_jobs(output: Mapping[str, Any], step_key: str) -> bool:
    """Whether the run has started nothing in a step (so a completed step was already complete)."""
    return not output["tries"][step_key]


def record_try(output: dict[str, Any], step_key: str, target_key: str, started: Started) -> None:
    """Counts one try for a target, with the jobs it made and why it failed, if it did."""
    counts = output["tries"][step_key]
    counts[target_key] = int(counts.get(target_key, 0)) + 1
    output["job_ids"].extend(started.job_ids)
    if started.error is not None:
        output["errors"][step_key][target_key] = _short(started.error)
    else:
        output["errors"][step_key].pop(target_key, None)
        # SCN-010: the scenes the run has made work for, to know which scenes have anything to
        # review at a review point.
        made = output["made_in"].setdefault(step_key, [])
        for scene_id in target_scenes(started.target):
            if scene_id not in made:
                made.append(scene_id)


def add_warnings(output: dict[str, Any], warnings: Sequence[str]) -> None:
    for text in warnings:
        if text not in output["warnings"]:
            output["warnings"].append(text)


def phase_of(
    output: Mapping[str, Any],
    running: Sequence[tuple[str, int, int]],
    options: RunOptions,
) -> str:
    """The phase label of the run: how many steps are complete and what is going on."""
    text = phases.pipeline_progress(len(complete_keys(output)), len(STEPS), running)
    waiting = len(output.get("scene_review_at") or {})
    if waiting:
        text = f"{text}; {waiting} {'scene' if waiting == 1 else 'scenes'} waiting for your review"
    if options.scenes:
        count = len(options.scenes)
        text = f"{count} {'scene' if count == 1 else 'scenes'}: {text}"
    return (
        f"Regenerating what is out of date: {text}" if options.scope == SCOPE_OUT_OF_DATE else text
    )


# --- Starting, continuing and stopping a run ------------------------------------------------


async def active_jobs(session: AsyncSession, project_id: int) -> list[Job]:
    """The project's jobs that are waiting or running, whatever they are."""
    statement = (
        select(Job)
        .where(Job.project_id == project_id, Job.status.in_(store.ACTIVE_STATUSES))
        .order_by(Job.id)
        .execution_options(populate_existing=True)
    )
    return list((await session.execute(statement)).scalars().all())


async def active_run(session: AsyncSession, project_id: int) -> Job | None:
    """The project's run that is waiting or running, or None."""
    job = await store.latest_job(session, project_id, JOB_TYPE)
    return job if job is not None and job.status in store.ACTIVE_STATUSES else None


def start_block(project: Project, active: Sequence[Job]) -> str | None:
    """Why a run cannot start now, or None. Pure. A run waits for no other job: two kinds of
    work on one project at once could replace each other's results.
    """
    if project.script_text is None or not project.script_text.strip():
        return "Save the story first: the pipeline starts from it."
    if active:
        many = len(active) > 1
        return (
            f"{len(active)} {'jobs are' if many else 'job is'} waiting or running for this "
            f"project. Wait for {'them' if many else 'it'} to finish, or cancel "
            f"{'them' if many else 'it'}, before running the whole pipeline."
        )
    return None


async def scene_items(session: AsyncSession, project_id: int) -> list[dict[str, Any]]:
    """The scenes of the newest list of scenes (`id`, `index`, `title`, ...), in story order.
    Empty when the project has no list yet.
    """
    row = await discovery.latest(session, "scenes", project_id)
    content = getattr(row, "content", None)
    items = content.get("scenes") if isinstance(content, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict) and isinstance(item.get("id"), str)]


def scene_label(item: Mapping[str, Any]) -> str:
    """ "Scene 3: The cellar", the way a run names a scene."""
    index = item.get("index")
    title = item.get("title") or item.get("id") or ""
    return f"Scene {index}: {title}" if index is not None else f"Scene {title}"


async def start_run(
    session: AsyncSession,
    project: Project,
    *,
    pause_after: Sequence[str],
    confirm_overwrite: bool,
    scope: Scope = SCOPE_ALL,
    scenes: Sequence[str] = (),
    remake_from: str | None = None,
) -> tuple[Job, bool]:
    """Queues a run, and commits. Returns `(job, created)`: a run that is already waiting or
    running is returned as it is (`created` False), with the choices it was started with.
    Raises StoryPipelineError for an unknown step or scene or when a run cannot start now.

    `scenes` (SCN-004) limits the run to those scenes (their ids); `remake_from` is the step
    whose targets in them are made again once (one of `REMAKE_STEPS`, and only with scenes).

    Whether the user has allowed the overwrites is decided by the caller (`confirmations`).
    """
    if scope not in SCOPES:
        raise StoryPipelineError(f"There is no scope {scope!r}.")
    unknown = [key for key in pause_after if key not in STEP_KEYS]
    if unknown:
        raise StoryPipelineError(f"There is no step {', '.join(repr(key) for key in unknown)}.")
    if remake_from is not None:
        if remake_from not in REMAKE_STEPS:
            raise StoryPipelineError(f"A scene cannot be made again from the step {remake_from!r}.")
        if not scenes:
            raise StoryPipelineError("Choose a scene to make again from a step.")
    # In story order, without repeats.
    chosen = set(scenes)
    in_order = [
        item["id"] for item in await scene_items(session, project.id) if item["id"] in chosen
    ]
    missing = sorted(chosen - set(in_order))
    if missing:
        raise StoryPipelineError(
            f"There is no scene {', '.join(repr(key) for key in missing)} in the newest list "
            "of scenes."
        )
    existing = await active_run(session, project.id)
    if existing is not None:
        return existing, False
    blocked = start_block(project, await active_jobs(session, project.id))
    if blocked is not None:
        raise StoryPipelineError(blocked)
    job, created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="local",
        input={
            "requested": JOB_TYPE,
            # In the order of the steps, without repeats.
            "pause_after": [key for key in STEP_KEYS if key in set(pause_after)],
            "confirm_overwrite": confirm_overwrite,
            "scope": scope,
            # The project's review points as they are now (PHASE-041).
            "review_points": review_rules.normalize(
                project.review_points if isinstance(project.review_points, list) else []
            ),
            # SCN-004: the scenes the run is limited to (none: the whole story).
            "scenes": in_order,
            "remake_from": remake_from,
        },
    )
    return job, created


async def continue_run(
    session: AsyncSession,
    project: Project,
    rejected: Mapping[str, Sequence[str]] | None = None,
) -> Job:
    """Lets a paused run go on, and commits. Raises StoryPipelineError when the project has no
    run, or its run is not paused.

    `rejected` (PHASE-041) maps a step key to the targets the user rejected at a review point.
    Only a run waiting at a review point takes it, and only for the steps of that point; whether
    each target exists is checked by the caller. A rejected target gets its tries back and is
    made again, and the run waits at the same review point once more. With nothing rejected the
    review point counts as passed.

    Every Continue makes the run read the steps that were complete again, so what the user
    edited while it waited is seen.
    """
    run = await active_run(session, project.id)
    if run is None:
        raise StoryPipelineError("There is no run going on for this project.")
    output = read_output(run.output)
    paused = output["paused_at"]
    review = output["review_at"]
    if paused is None and review is None:
        raise StoryPipelineError("The run is not paused.")
    wanted = {step: list(dict.fromkeys(keys)) for step, keys in (rejected or {}).items() if keys}
    if wanted and review is None:
        raise StoryPipelineError("The run is paused, not at a review point: nothing to reject.")
    if paused is not None:
        if paused not in output["continued"]:
            output["continued"].append(paused)
        output["paused_at"] = None
    if review is not None:
        _leave_review(output, review, wanted)
        output["review_at"] = None
    output["recheck"] = True
    if not await store.save_progress(
        session,
        run.id,
        phase=phase_of(output, [], RunOptions.from_input(run.input)),
        output=output,
    ):
        await session.rollback()
        raise StoryPipelineError("The run is no longer going.")
    await session.commit()
    return run


async def answer_scene_review(
    session: AsyncSession,
    project: Project,
    scene_id: str,
    rejected: Mapping[str, Sequence[str]] | None = None,
) -> Job:
    """Records the user's answer to the review a scene waits at (SCN-010), and commits. The run
    goes on while it waits, and saves its whole state at every look, so an answer written there
    could be overwritten. It is added to the run's `input` (which the run never writes) and the
    run applies it at its next look (`apply_scene_answers`).

    With nothing rejected the scene passes the point and goes on. Rejected targets of the
    point's steps are made again, and the scene waits at the same point once more. Raises
    StoryPipelineError when the project has no run, or the scene is not waiting at a review.
    """
    run = await active_run(session, project.id)
    if run is None:
        raise StoryPipelineError("There is no run going on for this project.")
    output = read_output(run.output)
    review = output["scene_review_at"].get(scene_id)
    point = review_rules.POINTS_BY_KEY.get(review) if review is not None else None
    if point is None:
        raise StoryPipelineError("This scene is not waiting for a review.")
    wanted = {step: list(dict.fromkeys(keys)) for step, keys in (rejected or {}).items() if keys}
    foreign = [step for step in wanted if step not in point.steps]
    if foreign:
        raise StoryPipelineError(
            f"The step {foreign[0]!r} is not part of this review point, so nothing in it can be "
            "rejected."
        )
    stored: dict[str, Any] = copy.deepcopy(run.input) if isinstance(run.input, dict) else {}
    answers = stored.get("scene_answers")
    stored["scene_answers"] = [
        *(answers if isinstance(answers, list) else []),
        {"scene": scene_id, "rejected": wanted},
    ]
    if not await store.update_input(session, run.id, stored):
        await session.rollback()
        raise StoryPipelineError("The run is no longer going.")
    return run


def apply_scene_answers(output: dict[str, Any], answers: object) -> bool:
    """Applies the answers users gave to scene reviews that the run has not applied yet (changes
    `output` in place). Returns whether anything changed. Pure.

    An answer for a scene that does not wait at a review any more is ignored (it was answered
    twice). With nothing rejected the scene passes its point; the rejected targets are made
    again. Either way the run looks at the steps that were complete again (`recheck`).
    """
    items = answers if isinstance(answers, list) else []
    applied = int(output["answers_applied"])
    changed = False
    for answer in items[applied:]:
        scene_id = answer.get("scene") if isinstance(answer, dict) else None
        if not isinstance(scene_id, str):
            continue
        point = review_rules.POINTS_BY_KEY.get(output["scene_review_at"].get(scene_id, ""))
        if point is None:
            continue
        rejected = answer.get("rejected")
        wanted = {
            step: [key for key in keys if isinstance(key, str)]
            for step, keys in (rejected if isinstance(rejected, dict) else {}).items()
            if step in point.steps and isinstance(keys, list)
        }
        del output["scene_review_at"][scene_id]
        if any(wanted.values()):
            _reject_targets(output, {step: keys for step, keys in wanted.items() if keys})
        else:
            passed = output["scene_reviewed"].setdefault(point.key, [])
            if scene_id not in passed:
                passed.append(scene_id)
        changed = True
    if len(items) != applied:
        output["answers_applied"] = len(items)
    if changed:
        output["recheck"] = True
    return changed


def _leave_review(output: dict[str, Any], review: str, rejected: Mapping[str, list[str]]) -> None:
    """Records the user's answer at a review point in the run's output (changes it in place)."""
    point = review_rules.POINTS_BY_KEY.get(review)
    steps = point.steps if point is not None else ()
    foreign = [step for step in rejected if step not in steps]
    if foreign:
        raise StoryPipelineError(
            f"The step {foreign[0]!r} is not part of this review point, so nothing in it can be "
            "rejected."
        )
    if not rejected:
        if review not in output["reviewed"]:
            output["reviewed"].append(review)
        return
    # The point stays unreviewed: the run waits here again once the targets are made again.
    _reject_targets(output, rejected)


def _reject_targets(output: dict[str, Any], rejected: Mapping[str, list[str]]) -> None:
    """Gives the rejected targets their tries back, so the run makes them again."""
    for step, keys in rejected.items():
        known = output["rejected"].setdefault(step, [])
        known.extend(key for key in keys if key not in known)
        for key in keys:
            output["tries"][step].pop(key, None)
            output["errors"][step].pop(key, None)
        output["steps"][step]["status"] = "running"


# --- Review points held scene by scene (SCN-010) --------------------------------------------


def settle_scene_reviews(
    options: RunOptions,
    scene_ids: Sequence[str],
    opens: Mapping[str, Open],
    output: dict[str, Any],
) -> bool:
    """Brings the per-scene review points up to date (changes `output` in place). Returns whether
    anything changed.

    For each enabled point held scene by scene, and each scene that has not passed it: while any
    step of the point is still open for the scene, the scene is not waiting. Once none is, the
    scene waits for the user (`scene_review_at`) if the run made anything for it in the point's
    steps, and otherwise passes at once (it was all up to date), as a whole run does.

    `opens` is what is open in each step; a step missing from it has not been reached, so it is
    open for everything.
    """
    changed = False
    for point in review_rules.REVIEW_POINTS:
        if not point.per_scene or point.key not in options.review_points:
            continue
        passed = output["scene_reviewed"].setdefault(point.key, [])
        for scene_id in scene_ids:
            if scene_id in passed:
                continue
            if any(opens.get(key, EVERYTHING).has(scene_id) for key in point.steps):
                if output["scene_review_at"].get(scene_id) == point.key:
                    del output["scene_review_at"][scene_id]
                    changed = True
                continue
            made = any(scene_id in output["made_in"].get(key, ()) for key in point.steps)
            if made:
                if output["scene_review_at"].get(scene_id) != point.key:
                    output["scene_review_at"][scene_id] = point.key
                    changed = True
            else:
                passed.append(scene_id)
                output["scene_review_at"].pop(scene_id, None)
                changed = True
    return changed


def held_scenes(
    step: Step, options: RunOptions, scene_ids: Collection[str], output: Mapping[str, Any]
) -> frozenset[str]:
    """The scenes a step must not start for yet because they have not passed the review of a
    step it needs (SCN-010). The point the step belongs to does not hold it. Pure.
    """
    own = review_rules.point_of(step.key)
    held: set[str] = set()
    for point in review_rules.REVIEW_POINTS:
        if not point.per_scene or point.key not in options.review_points:
            continue
        if own is not None and point.key == own.key:
            continue
        if not set(point.steps) & set(step.needs):
            continue
        passed = set(output["scene_reviewed"].get(point.key, ()))
        held.update(scene_id for scene_id in scene_ids if scene_id not in passed)
    return frozenset(held)


def all_scenes_passed(
    point_key: str, scene_ids: Collection[str], output: Mapping[str, Any]
) -> bool:
    """Whether every scene has passed a point held scene by scene (SCN-010). Pure."""
    passed = set(output["scene_reviewed"].get(point_key, ()))
    return all(scene_id in passed for scene_id in scene_ids)


def lane_summary(
    scene_ids: Sequence[str],
    opens: Mapping[str, Open],
    busy: Collection[str],
    stuck: Collection[str],
    output: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Where every scene stands in the lanes, in the order given (SCN-010). Pure.

    `status` is `review` (waits for the user), `done` (every lane step is complete for it),
    `going` (work is in progress for it), `problem` (nothing is, and something it needs was
    reported) or `waiting`. `step` is the first lane step still open for the scene.
    """
    steps = lane_steps()
    rows: list[dict[str, Any]] = []
    for scene_id in scene_ids:
        open_steps = [step for step in steps if opens.get(step.key, EVERYTHING).has(scene_id)]
        review = output["scene_review_at"].get(scene_id)
        if review is not None:
            status = "review"
        elif not open_steps:
            status = "done"
        elif scene_id in busy:
            status = "going"
        elif scene_id in stuck:
            status = "problem"
        else:
            status = "waiting"
        rows.append(
            {
                "scene": scene_id,
                "status": status,
                "step": open_steps[0].key if open_steps else None,
                "review": review,
                "done": len(steps) - len(open_steps),
                "total": len(steps),
            }
        )
    return rows


async def cancel_queued_children(session: AsyncSession, run: Job) -> int:
    """Cancels the jobs that have not started, so a stopped run leaves no paid work waiting: the
    jobs the run made, and the jobs of the project made after the run began (the stages queue
    follow-on jobs of their own). A job that is already running finishes on its own. Commits.
    Returns how many were cancelled.
    """
    wanted = {
        job_id
        for job_id in read_output(run.output)["job_ids"]
        if isinstance(job_id, int) and not isinstance(job_id, bool)
    }
    if run.project_id is not None:
        statement = select(Job.id).where(
            Job.project_id == run.project_id, Job.status == "queued", Job.id > run.id
        )
        wanted.update((await session.execute(statement)).scalars().all())
    cancelled = 0
    for job_id in sorted(wanted):
        child = await store.get_job(session, job_id)
        if child is None or child.status != "queued" or child.project_id != run.project_id:
            continue
        try:
            await store.cancel_job(session, job_id)
            cancelled += 1
        except store.JobActionError:
            continue  # it started in the meantime
    await session.commit()
    return cancelled
