"""The exact timeline of one story scene, and the checks on it (PHASE-021, `Path_ahead.md`
Sections 22, 23, 24 and 29). Pure functions: no I/O, no clock.

A scene's shot plan says how long each shot lasts and which speech units are heard during it.
`build_timeline` turns that into seconds: where every shot starts and ends in the scene, and where
every speech unit starts and ends. It then checks the result against the duration policy and the
speech, and lists the problems. Nothing here is stored: the timeline is worked out on every read
(D-3), so it always matches the plan and the policy as they are now.

**Placement rule (the answer to Q-15).** Shots are laid one after another from 0 s. The speech
units are taken in the order of the speech plan. A unit starts at the start of the first shot
that carries it, or right after the previous unit when that one is still playing then; it lasts
as long as its measured recording. A narration unit that spans several shots plays through all
of them. A pause has no unit: the shot that shows it carries its time in its `target_duration`.

**Checks.**

- *Flagged* (`outside_target`): a shot outside the planning target range but inside the hard
  bounds. It starts a re-plan, and it never blocks generation. A dialogue shot longer than the
  target is not flagged when one H3 length shorter would not hold its line with the margin:
  `h3_lengths` makes such a shot that long on purpose, and a re-plan could not shorten it.
- *Blocking* (`outside_hard_bounds`): a shot outside the hard bounds never reaches generation.
- *Blocking* (`dialogue_too_short`): a line of dialogue does not fit inside its shot with a small
  margin left for the face to settle.
- *Blocking* (`narration_overlap`): a narration unit would start while the unit before it is still
  playing, so it cannot start with the shot that carries it.
- *Blocking* (`speech_past_scene_end`): a narration unit runs past the end of the scene's shots.

Both kinds start an automatic re-plan (`jobs/plan_shots.py`); after the tries are used up, only
the blocking ones keep a scene from generation.

**A continuous explainer's scene** (FLOW-006) is laid out by `build_cut_timeline` instead: its
shots start and end at the cut times of the plan, each with the clip length that covers it, and
only a shot outside the hard bounds is a problem. It is never planned again by itself.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from app.services.duration_policy import DurationPolicy, longest_cut_shot_s
from app.services.frame_counts import H3_FPS, H3_FRAMES_PER_STEP, h3_num_frames, target_frames

# Time kept after a line of dialogue inside its shot, for the face to settle.
DIALOGUE_SETTLE_S: Final = 0.5

# Places and lengths are kept to a thousandth of a second, so that float noise from adding up
# many tenths never raises a problem.
_DECIMALS: Final = 3
_TOLERANCE: Final = 1e-6

Severity = Literal["flagged", "blocking"]

OUTSIDE_TARGET: Final = "outside_target"
OUTSIDE_HARD_BOUNDS: Final = "outside_hard_bounds"
DIALOGUE_TOO_SHORT: Final = "dialogue_too_short"
NARRATION_OVERLAP: Final = "narration_overlap"
SPEECH_PAST_SCENE_END: Final = "speech_past_scene_end"


@dataclass(frozen=True)
class UnitInfo:
    """One speech unit as the timeline needs it, in the order of the speech plan."""

    id: str
    kind: Literal["narration", "dialogue"]
    # The length of its recording, measured.
    seconds: float


@dataclass(frozen=True)
class ShotSpan:
    shot_id: str
    start_s: float
    end_s: float
    # Only on the timeline of a cut plan (FLOW-006): the frames of the clip made for the shot,
    # the shortest H3 length (`17n + 5`) that covers it. The shot is not moved onto it (F-6): the
    # render trims the extra frames. None for every other timeline.
    clip_frames: int | None = None


@dataclass(frozen=True)
class UnitSpan:
    unit_id: str
    kind: Literal["narration", "dialogue"]
    start_s: float
    end_s: float
    # Where it would start if nothing before it were still playing: the start of the first shot
    # that carries it.
    natural_start_s: float
    # The shots that carry it, in order.
    shot_ids: list[str]

    @property
    def delayed(self) -> bool:
        """True when the unit before it is still playing when its first shot starts."""
        return self.start_s > self.natural_start_s + _TOLERANCE


@dataclass(frozen=True)
class TimelineProblem:
    severity: Severity
    code: str
    message: str
    shot_id: str | None = None
    unit_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "shot_id": self.shot_id,
            "unit_id": self.unit_id,
            "message": self.message,
        }


@dataclass(frozen=True)
class SceneTimeline:
    shots: list[ShotSpan]
    units: list[UnitSpan]
    total_s: float
    problems: list[TimelineProblem] = field(default_factory=list)

    @property
    def has_blocking(self) -> bool:
        return any(problem.severity == "blocking" for problem in self.problems)

    @property
    def has_flagged(self) -> bool:
        return any(problem.severity == "flagged" for problem in self.problems)


def _seconds(value: float) -> str:
    return f"{value:g} s"


def _shorter_h3_length_s(length_s: float) -> float:
    """The H3 length one step shorter than `length_s`, stored the way `h3_lengths` stores it:
    seconds, rounded down to a millisecond.
    """
    frames = math.ceil(length_s * H3_FPS - _TOLERANCE) - H3_FRAMES_PER_STEP
    return (frames * 1000 // H3_FPS) / 1000


def dialogue_needs(spans: list[ShotSpan], placed: list[UnitSpan]) -> dict[str, float]:
    """For each shot that carries dialogue, the shortest it may last: from its start until its
    last line ends, plus the settle margin.
    """
    starts = {span.shot_id: span.start_s for span in spans}
    needs: dict[str, float] = {}
    for unit in placed:
        if unit.kind != "dialogue":
            continue
        shot_id = unit.shot_ids[0]
        need = round(unit.end_s + DIALOGUE_SETTLE_S - starts[shot_id], _DECIMALS)
        needs[shot_id] = max(needs.get(shot_id, 0.0), need)
    return needs


def _check_shot(
    shot: dict[str, Any], policy: DurationPolicy, dialogue_need_s: float | None
) -> TimelineProblem | None:
    """The problem with one shot's length, or None. A shot outside the hard bounds is reported
    as that only, not also as outside the target. `dialogue_need_s` is the shortest the shot may
    last for its dialogue (`dialogue_needs`), or None when it carries none.
    """
    length = shot["target_duration"]
    shot_id = shot["id"]
    if length < policy.hard_min_s - _TOLERANCE:
        return TimelineProblem(
            "blocking",
            OUTSIDE_HARD_BOUNDS,
            f"Shot {shot_id} lasts {_seconds(length)}, which is shorter than the H3 minimum of "
            f"{policy.hard_min_s} s.",
            shot_id=shot_id,
        )
    if length > policy.hard_max_s + _TOLERANCE:
        return TimelineProblem(
            "blocking",
            OUTSIDE_HARD_BOUNDS,
            f"Shot {shot_id} lasts {_seconds(length)}, which is longer than the H3 maximum of "
            f"{policy.hard_max_s} s.",
            shot_id=shot_id,
        )
    if length < policy.target_min_s - _TOLERANCE:
        return TimelineProblem(
            "flagged",
            OUTSIDE_TARGET,
            f"Shot {shot_id} lasts {_seconds(length)}, which is shorter than the planning "
            f"target of {policy.target_min_s} to {policy.target_max_s} s.",
            shot_id=shot_id,
        )
    if length > policy.target_max_s + _TOLERANCE:
        if (
            dialogue_need_s is not None
            and dialogue_need_s > _shorter_h3_length_s(length) + _TOLERANCE
        ):
            return None
        return TimelineProblem(
            "flagged",
            OUTSIDE_TARGET,
            f"Shot {shot_id} lasts {_seconds(length)}, which is longer than the planning "
            f"target of {policy.target_min_s} to {policy.target_max_s} s.",
            shot_id=shot_id,
        )
    return None


def _place_shots(shots: list[dict[str, Any]]) -> list[ShotSpan]:
    spans: list[ShotSpan] = []
    cursor = 0.0
    for shot in shots:
        start = round(cursor, _DECIMALS)
        cursor += shot["target_duration"]
        spans.append(ShotSpan(shot_id=shot["id"], start_s=start, end_s=round(cursor, _DECIMALS)))
    return spans


def _place_units(
    shots: list[dict[str, Any]], spans: list[ShotSpan], units: list[UnitInfo]
) -> list[UnitSpan]:
    """Places each unit that some shot carries, in the order of the speech plan. A unit that no
    shot carries is left out (the plan's own check makes sure that does not happen).
    """
    carried_by: dict[str, list[int]] = {}
    for position, shot in enumerate(shots):
        for unit_id in shot["speech_unit_ids"]:
            carried_by.setdefault(unit_id, []).append(position)

    placed: list[UnitSpan] = []
    previous_end = 0.0
    for unit in units:
        positions = carried_by.get(unit.id)
        if not positions:
            continue
        natural = spans[positions[0]].start_s
        start = round(max(natural, previous_end), _DECIMALS)
        end = round(start + unit.seconds, _DECIMALS)
        placed.append(
            UnitSpan(
                unit_id=unit.id,
                kind=unit.kind,
                start_s=start,
                end_s=end,
                natural_start_s=natural,
                shot_ids=[spans[position].shot_id for position in positions],
            )
        )
        previous_end = end
    return placed


def _check_units(
    placed: list[UnitSpan], spans: list[ShotSpan], total_s: float
) -> list[TimelineProblem]:
    by_shot = {span.shot_id: span for span in spans}
    problems: list[TimelineProblem] = []
    for unit in placed:
        if unit.kind == "dialogue":
            # A line of dialogue sits in exactly one shot, and must end, with the margin, inside it.
            shot = by_shot[unit.shot_ids[0]]
            if unit.end_s + DIALOGUE_SETTLE_S > shot.end_s + _TOLERANCE:
                late = (
                    f", after it was held back {_seconds(unit.start_s - unit.natural_start_s)} by "
                    "the speech before it"
                    if unit.delayed
                    else ""
                )
                problems.append(
                    TimelineProblem(
                        "blocking",
                        DIALOGUE_TOO_SHORT,
                        f"The line {unit.unit_id} ends at {_seconds(unit.end_s)}{late}, but shot "
                        f"{shot.shot_id} ends at {_seconds(shot.end_s)}; it needs "
                        f"{_seconds(DIALOGUE_SETTLE_S)} to spare.",
                        shot_id=shot.shot_id,
                        unit_id=unit.unit_id,
                    )
                )
            continue
        if unit.delayed:
            problems.append(
                TimelineProblem(
                    "blocking",
                    NARRATION_OVERLAP,
                    f"The narration {unit.unit_id} should start at "
                    f"{_seconds(unit.natural_start_s)} with shot {unit.shot_ids[0]}, but the "
                    f"speech before it is still playing until {_seconds(unit.start_s)}.",
                    shot_id=unit.shot_ids[0],
                    unit_id=unit.unit_id,
                )
            )
        if unit.end_s > total_s + _TOLERANCE:
            problems.append(
                TimelineProblem(
                    "blocking",
                    SPEECH_PAST_SCENE_END,
                    f"The narration {unit.unit_id} ends at {_seconds(unit.end_s)}, after the last "
                    f"shot ends at {_seconds(total_s)}.",
                    shot_id=unit.shot_ids[-1],
                    unit_id=unit.unit_id,
                )
            )
    return problems


def build_timeline(
    shots: list[dict[str, Any]], units: list[UnitInfo], policy: DurationPolicy
) -> SceneTimeline:
    """The timeline of one scene and its problems.

    `shots` is the stored list (each has `id`, `speech_unit_ids` and `target_duration`), in
    order. `units` is the scene's speech units in the order of the speech plan, with the
    measured length of each recording.
    """
    spans = _place_shots(shots)
    total = spans[-1].end_s if spans else 0.0
    placed = _place_units(shots, spans, units)
    needs = dialogue_needs(spans, placed)

    problems: list[TimelineProblem] = []
    for shot in shots:
        problem = _check_shot(shot, policy, needs.get(shot["id"]))
        if problem is not None:
            problems.append(problem)
    problems.extend(_check_units(placed, spans, total))
    return SceneTimeline(shots=spans, units=placed, total_s=total, problems=problems)


@dataclass(frozen=True)
class CutUnit:
    """One speech unit of a continuous explainer's scene: its kind, and where it sits inside the
    scene's take in seconds from the take's start (`take_timings.UnitSpan`).
    """

    id: str
    kind: Literal["narration", "dialogue"]
    start_s: float
    end_s: float


def build_cut_timeline(
    shots: list[dict[str, Any]],
    units: list[CutUnit],
    lead_in_s: float,
    policy: DurationPolicy,
) -> SceneTimeline:
    """The timeline of one scene of a continuous explainer (FLOW-006). Its shots are cut on the
    words of the scene's take (FLOW-005), so they are not laid one after another by length:

    - a shot starts and ends at its stored cut times (`start_s`, `end_s`, seconds from the start
      of the take), moved by the lead-in. The first shot starts at 0, so the lead-in belongs to
      it;
    - the take sits at the scene's start plus the lead-in, so each unit sits at the lead-in plus
      its place in the take. The units carried by a shot are the ones the plan lists;
    - each shot gets the length of the clip made for it (`ShotSpan.clip_frames`);
    - the scene ends where its last shot ends;
    - the only problem reported is a shot outside the hard bounds (blocking). The planning
      target, and the checks of speech carried by a shot, do not apply: the voice is one take
      that plays whatever the picture shows.

    `shots` is the stored list (each has `id`, `speech_unit_ids`, `start_s` and `end_s`), in order.
    """
    spans: list[ShotSpan] = []
    problems: list[TimelineProblem] = []
    longest = longest_cut_shot_s(policy)
    for position, shot in enumerate(shots):
        start = 0.0 if position == 0 else round(lead_in_s + float(shot["start_s"]), _DECIMALS)
        end = round(lead_in_s + float(shot["end_s"]), _DECIMALS)
        spans.append(
            ShotSpan(
                shot_id=shot["id"],
                start_s=start,
                end_s=end,
                clip_frames=h3_num_frames(target_frames(start, end, H3_FPS)),
            )
        )
        length = round(end - start, _DECIMALS)
        if length < policy.hard_min_s - _TOLERANCE:
            problems.append(
                TimelineProblem(
                    "blocking",
                    OUTSIDE_HARD_BOUNDS,
                    f"Shot {shot['id']} lasts {_seconds(length)}, which is shorter than the H3 "
                    f"minimum of {policy.hard_min_s} s.",
                    shot_id=shot["id"],
                )
            )
        elif length > longest + _TOLERANCE:
            problems.append(
                TimelineProblem(
                    "blocking",
                    OUTSIDE_HARD_BOUNDS,
                    f"Shot {shot['id']} lasts {_seconds(length)}, which is longer than the "
                    f"longest cut shot of {_seconds(longest)}.",
                    shot_id=shot["id"],
                )
            )

    placed = [
        UnitSpan(
            unit_id=unit.id,
            kind=unit.kind,
            start_s=round(lead_in_s + unit.start_s, _DECIMALS),
            end_s=round(lead_in_s + unit.end_s, _DECIMALS),
            natural_start_s=round(lead_in_s + unit.start_s, _DECIMALS),
            shot_ids=[shot["id"] for shot in shots if unit.id in shot["speech_unit_ids"]],
        )
        for unit in units
    ]
    total = spans[-1].end_s if spans else 0.0
    return SceneTimeline(shots=spans, units=placed, total_s=total, problems=problems)


def story_offsets(totals: list[float | None]) -> list[float | None]:
    """Where each scene starts in the story, given the length of each scene in order, or None
    for a scene that has no plan. A scene's start is unknown (None) once any scene before it has
    no plan.
    """
    offsets: list[float | None] = []
    running: float | None = 0.0
    for total in totals:
        offsets.append(round(running, _DECIMALS) if running is not None else None)
        if running is not None and total is not None:
            running = round(running + total, _DECIMALS)
        else:
            running = None
    return offsets


def problems_for_model(timeline: SceneTimeline) -> list[dict[str, Any]]:
    """The problems as data for the model's next attempt (a JSON block, never text written into
    the instructions).
    """
    return [problem.as_dict() for problem in timeline.problems]
