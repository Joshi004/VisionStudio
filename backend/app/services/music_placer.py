"""Placing the music on the timeline, exactly (MUSIC-011, `Music_implementation_phases.md`
Sections 4.4 to 4.7, MD-1, MD-12). Pure functions: no I/O, no clock, no model call.

The plan and the cue detail say *where in the story* each sound belongs, by anchors. This module
turns every anchor into an exact sample of the finished video's audio (48 kHz, the render's
own), fits each selected take to its span, and decides the fades and joins.

**One timeline.** Every position here is a second (or a sample) of the story as the render lays
it out: shot cuts on frame boundaries, speech units where the render puts them. The caller
(`services/music_placement.py`) builds the `World` from the same sources as the render, so the
two cannot disagree.

**What "inside a word" means.** A speech unit's recording, minus its own measured silences, is
a word interval. Music may not *start being audible* (the start of a fade-in, or a hard start)
or *stop being audible* (the end of a fade-out, or a hard stop) inside one. The rest of a fade
may run under a voice: that is how a quiet entry under narration works. A point that cannot be
helped is flagged and listed in `facts.inside_speech`.

**Edges, and the ladder (Section 4.7).** Every audible start and stop of a score or ambience
cue is an *edge*. For an edge, code builds a window around the nominal second (from the
anchor's relation and strictness), lists the real candidates in it (shot cuts, free stretches of
the speech, the moments of placed hits) and takes the best by mechanical rules. When nothing is
there it works down the ladder, and records the step in `ladder_step`:

- 0: found in the window;
- 1: found after widening the window once;
- 2: a gentler technique (a quiet fade that starts in the last gap before the anchor, or a short
  fade that ends in the next gap);
- 3: covered by a sound that already exists (a placed hit, or a swell of a bed that is already
  playing);
- 4: chosen by the model from the real candidates (`pending`, then `choices`);
- 5: flagged to the owner.

The model's choice (step 4) is also the normal path for the important anchors (`important`). It
is asked in **one** batched call by the caller: `place` returns the questions as `pending`, and
is run again with the answers.

**Moments** (hits, point sounds, sounds H3 makes) are placed on the detected sudden sound of
the shot's H3 audio when there is one, else on the planned second.

**Fitting.** A take is centred on its cue's span, so each side has the same spare length (the
handles). A planned change of mood that the take makes late or early slides the take (only
when its measured change point is strong). A musical ending is back-timed: the end of the
take's sound lands on the end point. A take too short for what is needed is trimmed, and that is
recorded.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

# The render's sample rate (`render_commands.SAMPLE_RATE`); a test keeps the two equal.
SAMPLE_RATE: Final = 48000
PLACER_VERSION: Final = 1

# --- Constants (recorded with every result) --------------------------------------------------
# The click-free edge of a hard start, a hard stop and a hit.
EDGE_FADE_S: Final = 0.010
# Music that stops before a hit stops this many frames before it.
BEFORE_HIT_FRAMES: Final = 2
# A join hidden under something fades over this long.
COVER_CROSSFADE_S: Final = 1.0
# A change point of the take must be this many standard deviations strong to slide the take.
SLIDE_MIN_STRENGTH: Final = 2.0
# How far from where a mood change is expected a change point of the take is looked for.
SLIDE_MAX_SEARCH_S: Final = 6.0
# Score and beds are brought to this loudness; hits and point sounds keep their own.
MATCH_LUFS: Final = -20.0
MATCH_MAX_DB: Final = 12.0
# A start or a stop keeps this far from the edge of a word.
FREE_MARGIN_S: Final = 0.1
# The gentler technique reaches at most this far from the anchor.
MAX_GENTLE_S: Final = 10.0
GENTLE_STOP_FADE_MIN_S: Final = 1.0
GENTLE_STOP_FADE_MAX_S: Final = 4.0
# The model is shown candidates this far from the anchor, at most this many.
GLM_REACH_S: Final = 15.0
MAX_GLM_CANDIDATES: Final = 8
# The crossfade point is looked for on this grid.
GRID_S: Final = 0.25
# A crossfade shorter than this is not one: the join becomes a hard cut.
MIN_CROSSFADE_S: Final = 0.1
# A cue shorter than this after trimming is flagged.
MIN_CUE_S: Final = 0.5
DEFAULT_FADE_S: Final = 3.0
RISE_FADE_FACTOR: Final = 1.5
SHORT_TERM_STEP_S: Final = 0.5
SILENT_LUFS: Final = -70.0

LANE_BED: Final = "bed"
LANE_SCORE: Final = "score"
JOINS_OVER_SOUND: Final = ("crossfade", "under_cover", "hard_cut")


def constants(params: Params) -> dict[str, Any]:
    """The values a placement used, recorded on it (D-3)."""
    return {
        "placer_version": PLACER_VERSION,
        "tight_s": params.tight_s,
        "loose_s": params.loose_s,
        "widen_factor": params.widen_factor,
        "crossfade_s": params.crossfade_s,
        "fps": params.fps,
        "edge_fade_s": EDGE_FADE_S,
        "before_hit_frames": BEFORE_HIT_FRAMES,
        "cover_crossfade_s": COVER_CROSSFADE_S,
        "slide_min_strength": SLIDE_MIN_STRENGTH,
        "match_lufs": MATCH_LUFS,
        "free_margin_s": FREE_MARGIN_S,
        "max_gentle_s": MAX_GENTLE_S,
        "glm_reach_s": GLM_REACH_S,
    }


# --- What a placement is made from -----------------------------------------------------------


@dataclass(frozen=True)
class Params:
    tight_s: float
    loose_s: float
    # 1.0 doubles a window that found nothing.
    widen_factor: float
    crossfade_s: float
    fps: int


@dataclass(frozen=True)
class Speech:
    """A speech unit on the story's timeline, with the silences measured inside its recording
    (absolute seconds, inside the span).
    """

    ref: str
    kind: str  # narration or dialogue
    start_s: float
    end_s: float
    silences: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True)
class Clip:
    """The H3 clip of a shot: where it sits and its sudden sounds (absolute seconds, strength)."""

    shot_ref: str
    start_s: float
    end_s: float
    onsets: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True)
class World:
    total_samples: int
    # Shot starts on frame boundaries, in seconds.
    cuts_s: tuple[float, ...]
    speech: tuple[Speech, ...]
    # Exact start and end by reference (`scene:`, `shot:`, `unit:`, `event:`).
    spans: Mapping[str, tuple[float, float]]
    # The shots that show each sound event.
    event_shots: Mapping[str, tuple[str, ...]]
    clips: Mapping[str, Clip]

    @property
    def total_s(self) -> float:
        return self.total_samples / SAMPLE_RATE


@dataclass(frozen=True)
class Anchor:
    ref: str
    edge: str
    relation: str
    strict: str
    # The second the plan resolved it to; used only when `ref` is not in the world's spans.
    seconds: float

    @staticmethod
    def of(raw: Mapping[str, Any]) -> Anchor:
        return Anchor(
            ref=str(raw["ref"]),
            edge=str(raw["edge"]),
            relation=str(raw["relation"]),
            strict=str(raw["strict"]),
            seconds=float(raw.get("seconds") or 0.0),
        )


@dataclass(frozen=True)
class Sound:
    """One selected take to place: a score or bed cue, a point sound, a hit cue, or a hit that a
    cue asked for.
    """

    item_id: str
    cue_id: str
    role: str  # cue or hit
    kind: str  # score, bed, point or hit
    summary: str
    intensity: int
    take_id: int
    lab_run_id: int | None
    path: str
    sha256: str
    duration_s: float
    measurement: Mapping[str, Any]
    start: Anchor | None = None
    end: Anchor | None = None
    at: Anchor | None = None
    start_style: str | None = None
    end_style: str | None = None
    fade_in_s: float | None = None
    fade_out_s: float | None = None
    # Where the cue's broad order of moods gives way from one to the next.
    mood_changes: tuple[Anchor, ...] = ()
    # A themed score cue that brings its theme in for the first time.
    important_start: bool = False


@dataclass(frozen=True)
class H3Sound:
    """A sound that H3 makes inside a shot: nothing to place, only its moment to find."""

    cue_id: str
    summary: str
    at: Anchor
    shot_ref: str
    event_ref: str


@dataclass(frozen=True)
class Boundary:
    from_id: str
    to_id: str
    join: str


@dataclass(frozen=True)
class PlacementInput:
    params: Params
    world: World
    sounds: tuple[Sound, ...]
    h3_sounds: tuple[H3Sound, ...] = ()
    boundaries: tuple[Boundary, ...] = ()


@dataclass(frozen=True)
class PlacementResult:
    content: dict[str, Any]
    # The questions for the model: see `place`.
    pending: list[dict[str, Any]]


# --- Time and samples ------------------------------------------------------------------------


def to_sample(seconds: float) -> int:
    return round(seconds * SAMPLE_RATE)


def event_spans(
    plan_timeline: Mapping[str, Any], spans: Mapping[str, tuple[float, float]]
) -> dict[str, tuple[float, float]]:
    """The exact span of each event of the plan's timeline: the units that voice it, or else the
    shots that show it (`music_timeline` says the same about the plan's own seconds).
    """
    found: dict[str, tuple[float, float]] = {}
    for event in plan_timeline.get("events", []):
        carriers = event.get("units") or event.get("shots") or []
        known = [spans[ref] for ref in carriers if ref in spans]
        if known:
            found[event["ref"]] = (min(s[0] for s in known), max(s[1] for s in known))
    return found


def exact_seconds(world: World, anchor: Anchor) -> float:
    """The nominal second of an anchor on the render's own timeline."""
    span = world.spans.get(anchor.ref)
    if span is None:
        return anchor.seconds
    if anchor.relation == "under":
        return (span[0] + span[1]) / 2
    return span[0] if anchor.edge == "start" else span[1]


def lufs_at(measurement: Mapping[str, Any], seconds: float) -> float:
    """The short-term loudness of a recording at `seconds`, or very quiet when unknown."""
    curve = measurement.get("short_term_loudness")
    values = curve.get("lufs") if isinstance(curve, Mapping) else None
    if not isinstance(values, list) or not values:
        return SILENT_LUFS
    index = min(max(int(seconds / SHORT_TERM_STEP_S), 0), len(values) - 1)
    value = values[index]
    return float(value) if isinstance(value, int | float) else SILENT_LUFS


# --- Candidates ------------------------------------------------------------------------------


@dataclass
class _Cand:
    kind: str  # cut, gap, hit, sound, planned, quiet_fade, bed_swell
    t: float
    priority: int
    description: str
    strength: float = 0.0
    # For a gentle fade: how long it should be.
    fade_s: float | None = None
    covered: bool = False
    id: str = ""


def _best(cands: list[_Cand], nominal: float) -> _Cand | None:
    if not cands:
        return None
    return min(cands, key=lambda c: (c.priority, abs(c.t - nominal), -c.strength))


def _merge(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[tuple[float, float]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _word_intervals(
    speech: tuple[Speech, ...], kinds: tuple[str, ...]
) -> list[tuple[float, float]]:
    """The stretches of the speech where someone is saying something: each unit's span minus
    its silences.
    """
    pieces: list[tuple[float, float]] = []
    for unit in speech:
        if unit.kind not in kinds:
            continue
        cursor = unit.start_s
        for start, end in sorted(unit.silences):
            start, end = max(start, unit.start_s), min(end, unit.end_s)
            if end <= start:
                continue
            if start - cursor > 0.05:
                pieces.append((cursor, start))
            cursor = max(cursor, end)
        if unit.end_s - cursor > 0.05:
            pieces.append((cursor, unit.end_s))
    return _merge(pieces)


def _describe(kind: str, t: float, extra: str = "") -> str:
    where = f"{t:.1f} s"
    if kind == "cut":
        return f"a shot cut at {where}"
    if kind == "gap":
        return f"a pause in the speech at {where}"
    if kind == "hit":
        return f"{extra or 'a hit'} at {where}"
    if kind == "sound":
        return f"a sudden sound in the clip at {where}{extra}"
    if kind == "planned":
        return f"the planned moment, {where}"
    if kind == "quiet_fade":
        return f"a quiet fade from the last pause, which starts at {where}{extra}"
    return f"{kind} at {where}"


# --- The placer ------------------------------------------------------------------------------


@dataclass
class _Cue:
    sound: Sound
    nominal_start: float
    nominal_end: float
    handle_s: float
    slide_s: float
    slide_reason: str
    base: float  # the take's own second at `nominal_start`
    start_edge: dict[str, Any] | None = None
    end_edge: dict[str, Any] | None = None
    start_t: float = 0.0
    end_t: float = 0.0
    fade_in_s: float = 0.0
    fade_out_s: float = 0.0
    fade_in_shape: str = "linear"
    fade_out_shape: str = "linear"
    join_in: dict[str, Any] | None = None
    join_out: dict[str, Any] | None = None
    back_timed: bool = False
    source_out_limit: float | None = None
    notes: list[str] = field(default_factory=list)
    fallbacks: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.sound.duration_s

    def src(self, story_s: float) -> float:
        return self.base + (story_s - self.nominal_start)


class _Placer:
    def __init__(self, data: PlacementInput, choices: Mapping[str, str | None]) -> None:
        self.data = data
        self.p = data.params
        self.w = data.world
        self.choices = choices
        self.frame_s = 1.0 / self.p.fps
        self.words = _word_intervals(self.w.speech, ("narration", "dialogue"))
        self.dialogue_words = _word_intervals(self.w.speech, ("dialogue",))
        self.free = self._free_intervals()
        # Where hits and sounds fall, once placed: `(second, label)`.
        self.moments: list[tuple[float, str]] = []
        self.pending: list[dict[str, Any]] = []
        self.flags: list[dict[str, Any]] = []
        self.mix_requests: list[dict[str, Any]] = []
        self.choice_log: list[dict[str, Any]] = []
        self.joins: list[dict[str, Any]] = []
        self.placements: list[dict[str, Any]] = []
        self.h3_out: list[dict[str, Any]] = []
        self.cues: dict[str, _Cue] = {}

    # -- speech and windows --

    def _free_intervals(self) -> list[tuple[float, float]]:
        free: list[tuple[float, float]] = []
        cursor = 0.0
        for start, end in self.words:
            if start > cursor:
                free.append((cursor, start))
            cursor = max(cursor, end)
        if self.w.total_s > cursor:
            free.append((cursor, self.w.total_s))
        return free

    def in_word(self, t: float) -> bool:
        return any(start < t < end for start, end in self.words)

    def _in_dialogue(self, t: float) -> bool:
        return any(start < t < end for start, end in self.dialogue_words)

    def _window(self, anchor: Anchor, nominal: float) -> tuple[float, float]:
        width = self.p.tight_s if anchor.strict == "tight" else self.p.loose_s
        relation = anchor.relation
        if relation == "before":
            low, high = nominal - width, nominal
        elif relation == "just_before":
            low, high = nominal - width, nominal - self.frame_s
        elif relation == "after":
            low, high = nominal, nominal + width
        elif relation == "under" and anchor.ref in self.w.spans:
            low, high = self.w.spans[anchor.ref]
        else:
            low, high = nominal - width, nominal + width
        return self._clip(low, high)

    def _clip(self, low: float, high: float) -> tuple[float, float]:
        return max(0.0, low), min(self.w.total_s, high)

    def _widen(self, window: tuple[float, float]) -> tuple[float, float]:
        low, high = window
        grow = (high - low) * self.p.widen_factor / 2
        return self._clip(low - grow, high + grow)

    # -- candidates for an edge --

    def _edge_cands(
        self,
        window: tuple[float, float],
        nominal: float,
        side: str,
        technique: str,
        *,
        use_hits: bool,
    ) -> list[_Cand]:
        low, high = window
        hard = technique == "hard"
        found: list[_Cand] = []
        for cut in self.w.cuts_s:
            if low <= cut <= high and not self.in_word(cut):
                found.append(_Cand("cut", cut, 0, _describe("cut", cut)))
        for free_start, free_end in self.free:
            lo = max(low, free_start + FREE_MARGIN_S)
            hi = min(high, free_end - FREE_MARGIN_S)
            if lo <= hi:
                t = min(max(nominal, lo), hi)
                found.append(_Cand("gap", t, 1 if hard else 0, _describe("gap", t)))
        if use_hits:
            for moment, label in self.moments:
                t = moment if side == "start" else moment - BEFORE_HIT_FRAMES * self.frame_s
                if low <= t <= high:
                    found.append(_Cand("hit", t, 0, _describe("hit", t, label)))
        return found

    def _gentle(self, side: str, nominal: float, technique: str) -> _Cand | None:
        """Ladder step 2: a quiet fade that starts in the last pause before the anchor, or a
        short fade that ends in the next pause after it.
        """
        if side == "start":
            for free_start, free_end in reversed(self.free):
                if free_start + FREE_MARGIN_S > nominal:
                    continue
                t = min(nominal, free_end - FREE_MARGIN_S)
                if t < free_start + FREE_MARGIN_S:
                    continue
                if nominal - t > MAX_GENTLE_S:
                    return None
                length = max(nominal - t, 0.0)
                return _Cand(
                    "quiet_fade",
                    t,
                    0,
                    _describe("quiet_fade", t, f", reaching full level by {nominal:.1f} s"),
                    fade_s=length,
                )
            return None
        for free_start, free_end in self.free:
            if free_end - FREE_MARGIN_S < nominal:
                continue
            t = max(nominal, free_start + FREE_MARGIN_S)
            if t > free_end - FREE_MARGIN_S:
                continue
            if t - nominal > MAX_GENTLE_S:
                return None
            length = min(max(t - nominal, GENTLE_STOP_FADE_MIN_S), GENTLE_STOP_FADE_MAX_S)
            return _Cand(
                "quiet_fade",
                t,
                0,
                f"a short fade that ends in the next pause, at {t:.1f} s",
                fade_s=length,
            )
        return None

    def _bed_swell(self, nominal: float, own_cue: str) -> _Cand | None:
        for cue_id, cue in self.cues.items():
            if cue_id == own_cue or cue.sound.kind != "bed" or not cue.end_t:
                continue
            if cue.start_t <= nominal <= cue.end_t:
                return _Cand(
                    "bed_swell",
                    nominal,
                    0,
                    f"a swell of the ambience bed {cue_id} that is playing at {nominal:.1f} s",
                    covered=True,
                )
        return None

    def _cover(
        self, side: str, nominal: float, window: tuple[float, float], own_cue: str
    ) -> _Cand | None:
        """Ladder step 3: a sound that already exists hides the point."""
        low, high = window
        hits = []
        for moment, label in self.moments:
            t = moment if side == "start" else moment - BEFORE_HIT_FRAMES * self.frame_s
            if low <= t <= high:
                hits.append(_Cand("hit", t, 0, _describe("hit", t, label), covered=True))
        best = _best(hits, nominal)
        return best or self._bed_swell(nominal, own_cue)

    def _reach_cands(
        self, side: str, nominal: float, technique: str, gentle: _Cand | None
    ) -> list[_Cand]:
        """What the model may choose among: the real candidates within reach of the anchor."""
        window = self._clip(nominal - GLM_REACH_S, nominal + GLM_REACH_S)
        found = self._edge_cands(window, nominal, side, technique, use_hits=True)
        if gentle is not None:
            found.append(gentle)
        # The same second twice (a cut inside a pause) is one candidate.
        unique: dict[tuple[str, float], _Cand] = {}
        for cand in found:
            unique.setdefault((cand.kind, round(cand.t, 3)), cand)
        ordered = sorted(unique.values(), key=lambda c: (abs(c.t - nominal), c.priority))
        return ordered[:MAX_GLM_CANDIDATES]

    # -- an edge, through the ladder --

    def _edge(
        self,
        *,
        edge_id: str,
        cue: _Cue,
        side: str,
        anchor: Anchor,
        technique: str,
        important: bool,
    ) -> dict[str, Any]:
        nominal = exact_seconds(self.w, anchor)
        window = self._window(anchor, nominal)
        use_hits = technique == "hard"
        notes: list[str] = []
        step = 0
        pick = _best(self._edge_cands(window, nominal, side, technique, use_hits=use_hits), nominal)
        wide = self._widen(window)
        if pick is None and self.p.widen_factor > 0:
            pick = _best(
                self._edge_cands(wide, nominal, side, technique, use_hits=use_hits), nominal
            )
            if pick is not None:
                step = 1
                notes.append(f"Nothing fitted within {window[1] - window[0]:.1f} s: widened once.")
        gentle: _Cand | None = None
        if pick is None:
            gentle = self._gentle(side, nominal, technique)
            if gentle is not None:
                pick, step = gentle, 2
                notes.append(
                    "No cut or pause near the anchor: a quiet fade from the nearest pause."
                )
        else:
            gentle = self._gentle(side, nominal, technique) if important else None
        if pick is None:
            pick = self._cover(side, nominal, wide, cue.sound.cue_id)
            if pick is not None:
                step = 3
                notes.append(f"Hidden under an existing sound: {pick.description}.")

        chosen_by = "code"
        reach = self._reach_cands(side, nominal, technique, gentle)
        ask = (important or pick is None) and bool(reach)
        if ask:
            for number, cand in enumerate(reach, start=1):
                cand.id = f"{edge_id}#{number}"
            best_id = next(
                (c.id for c in reach if pick is not None and c.kind == pick.kind and c.t == pick.t),
                None,
            )
            if edge_id in self.choices:
                answer = self.choices[edge_id]
                chosen = next((c for c in reach if c.id == answer), None)
                if chosen is not None:
                    pick, step, chosen_by = chosen, 4, "model"
                    notes.append(f"The model chose: {chosen.description}.")
                    self.choice_log.append(
                        {
                            "id": edge_id,
                            "cue_id": cue.sound.cue_id,
                            "edge": side,
                            "picked": chosen.description,
                            "important": important,
                        }
                    )
                elif pick is not None:
                    notes.append("The model's choice could not be used: kept the code's.")
            else:
                self.pending.append(
                    {
                        "id": edge_id,
                        "cue_id": cue.sound.cue_id,
                        "summary": cue.sound.summary,
                        "edge": side,
                        "technique": technique,
                        "nominal_s": round(nominal, 3),
                        "important": important,
                        "reason": "important" if important else "nothing_fitted",
                        "candidates": [
                            {
                                "id": c.id,
                                "kind": c.kind,
                                "t": round(c.t, 3),
                                "description": c.description,
                                "code_best": c.id == best_id,
                            }
                            for c in reach
                        ],
                    }
                )

        flagged = False
        if pick is None:
            step, flagged = 5, True
            pick = _Cand("planned", nominal, 0, _describe("planned", nominal))
            notes.append("Nothing could be found: placed on the planned second and flagged.")
            self.flags.append(
                {
                    "cue_id": cue.sound.cue_id,
                    "item_id": cue.sound.item_id,
                    "edge": side,
                    "second": round(nominal, 3),
                    "message": f"The {side} of {cue.sound.cue_id} could not be placed on a cut or "
                    f"a pause near {nominal:.1f} s.",
                }
            )
        final_technique = "fade" if pick.kind == "quiet_fade" else technique
        return {
            "nominal_s": round(nominal, 3),
            "chosen_s": pick.t,
            "kind": pick.kind,
            "description": pick.description,
            "ladder_step": step,
            "flagged": flagged,
            "covered": pick.covered,
            "technique": final_technique,
            "fade_s": pick.fade_s,
            "chosen_by": chosen_by,
            "notes": notes,
            # A hit or an existing sound hides a point, so it does not count as inside a word.
            "inside_speech": self.in_word(pick.t) and not pick.covered and pick.kind != "hit",
        }

    # -- moments: hits, point sounds and the sounds H3 makes --

    def _clip_shots(self, ref: str, window: tuple[float, float]) -> list[str]:
        if ref in self.w.event_shots:
            return list(self.w.event_shots[ref])
        if ref.startswith("shot:"):
            return [ref]
        return [
            shot
            for shot, clip in self.w.clips.items()
            if clip.end_s >= window[0] and clip.start_s <= window[1]
        ]

    def _onsets(
        self, anchor: Anchor, window: tuple[float, float], shots: list[str] | None = None
    ) -> list[_Cand]:
        found: list[_Cand] = []
        for ref in shots if shots is not None else self._clip_shots(anchor.ref, window):
            clip = self.w.clips.get(ref)
            if clip is None:
                continue
            for t, strength in clip.onsets:
                if (
                    window[0] <= t <= window[1]
                    and clip.start_s <= t < clip.end_s
                    and not self._in_dialogue(t)
                ):
                    found.append(
                        _Cand(
                            "sound",
                            t,
                            0,
                            _describe("sound", t, f" (strength {strength:.1f})"),
                            strength=strength,
                        )
                    )
        return found

    def _moment(
        self,
        *,
        moment_id: str,
        cue_id: str,
        summary: str,
        anchor: Anchor,
        important: bool,
        shots: list[str] | None = None,
    ) -> dict[str, Any]:
        """The exact second of a hit or a point sound: on the strongest detected sound of the
        shot's H3 audio in the window, else on the planned second.
        """
        nominal = exact_seconds(self.w, anchor)
        window = self._window(anchor, nominal)
        step = 0
        notes: list[str] = []
        pick = _best(self._onsets(anchor, window, shots), nominal)
        if pick is None and self.p.widen_factor > 0:
            pick = _best(self._onsets(anchor, self._widen(window), shots), nominal)
            if pick is not None:
                step = 1
                notes.append("No sound was detected in the window: widened once.")
        planned = _Cand("planned", nominal, 1, _describe("planned", nominal))
        if pick is None:
            pick, step = planned, 2
            notes.append("No sound was detected in the shot's audio: on the planned moment.")

        chosen_by = "code"
        if important:
            reach_window = self._clip(nominal - GLM_REACH_S, nominal + GLM_REACH_S)
            options = sorted(
                self._onsets(anchor, reach_window, shots), key=lambda c: abs(c.t - nominal)
            )[: MAX_GLM_CANDIDATES - 1]
            options.append(_Cand("planned", nominal, 1, planned.description))
            for number, cand in enumerate(options, start=1):
                cand.id = f"{moment_id}#{number}"
            if len(options) > 1:
                best_id = next(
                    (c.id for c in options if c.kind == pick.kind and c.t == pick.t), None
                )
                if moment_id in self.choices:
                    chosen = next((c for c in options if c.id == self.choices[moment_id]), None)
                    if chosen is not None:
                        pick, step, chosen_by = chosen, 4, "model"
                        notes.append(f"The model chose: {chosen.description}.")
                        self.choice_log.append(
                            {
                                "id": moment_id,
                                "cue_id": cue_id,
                                "edge": "at",
                                "picked": chosen.description,
                                "important": True,
                            }
                        )
                else:
                    self.pending.append(
                        {
                            "id": moment_id,
                            "cue_id": cue_id,
                            "summary": summary,
                            "edge": "at",
                            "technique": "moment",
                            "nominal_s": round(nominal, 3),
                            "important": True,
                            "reason": "important",
                            "candidates": [
                                {
                                    "id": c.id,
                                    "kind": c.kind,
                                    "t": round(c.t, 3),
                                    "description": c.description,
                                    "code_best": c.id == best_id,
                                }
                                for c in options
                            ],
                        }
                    )
        self.moments.append((pick.t, summary))
        return {
            "nominal_s": round(nominal, 3),
            "chosen_s": pick.t,
            "kind": pick.kind,
            "description": pick.description,
            "ladder_step": step,
            "flagged": False,
            "chosen_by": chosen_by,
            "notes": notes,
        }

    def _place_moments(self) -> None:
        for sound in self.data.sounds:
            if sound.kind in ("score", "bed") and sound.role == "cue":
                continue
            assert sound.at is not None
            result = self._moment(
                moment_id=f"{sound.item_id}:at",
                cue_id=sound.cue_id,
                summary=sound.summary,
                anchor=sound.at,
                important=sound.intensity >= 5,
            )
            loudest = sound.measurement.get("loudest_moment")
            loudest_s = float(loudest["time_s"]) if isinstance(loudest, Mapping) else 0.0
            self.placements.append(self._moment_placement(sound, result, loudest_s))
        for h3 in self.data.h3_sounds:
            result = self._moment(
                moment_id=f"{h3.cue_id}:at",
                cue_id=h3.cue_id,
                summary=h3.summary,
                anchor=h3.at,
                important=False,
                shots=[h3.shot_ref],
            )
            self.h3_out.append(
                {
                    "cue_id": h3.cue_id,
                    "summary": h3.summary,
                    "shot": h3.shot_ref,
                    "event": h3.event_ref,
                    **{k: result[k] for k in ("nominal_s", "chosen_s", "kind", "ladder_step")},
                    "description": result["description"],
                }
            )

    def _moment_placement(
        self, sound: Sound, result: dict[str, Any], loudest_s: float
    ) -> dict[str, Any]:
        moment = to_sample(result["chosen_s"])
        loudest = to_sample(min(max(loudest_s, 0.0), sound.duration_s))
        length = to_sample(sound.duration_s)
        start = moment - loudest
        source_in = 0
        if start < 0:
            source_in, start = -start, 0
        length_out = max(0, min(length - source_in, self.w.total_samples - start))
        return {
            **self._common(sound),
            "lane": "sounds",
            "story_start_sample": start,
            "source_in_sample": source_in,
            "source_out_sample": source_in + length_out,
            "length_samples": length_out,
            "fade_in": {"samples": to_sample(EDGE_FADE_S), "shape": "linear"},
            "fade_out": {"samples": to_sample(EDGE_FADE_S), "shape": "linear"},
            "match_gain_db": 0.0,
            "moment": {
                **{k: result[k] for k in result if k not in ("flagged",)},
                "moment_sample": moment,
                "source_peak_sample": loudest,
            },
            "start": None,
            "end": None,
            "join_in": None,
            "join_out": None,
            "slide_s": 0.0,
            "back_timed": False,
            "fallbacks": result["notes"],
            "notes": [],
        }

    def _common(self, sound: Sound) -> dict[str, Any]:
        return {
            "item_id": sound.item_id,
            "cue_id": sound.cue_id,
            "role": sound.role,
            "kind": sound.kind,
            "summary": sound.summary,
            "take_id": sound.take_id,
            "lab_run_id": sound.lab_run_id,
            "path": sound.path,
            "sha256": sound.sha256,
            "duration_s": round(sound.duration_s, 3),
        }

    # -- score and ambience cues --

    def _init_cue(self, sound: Sound) -> _Cue:
        assert sound.start is not None and sound.end is not None
        start = exact_seconds(self.w, sound.start)
        end = max(exact_seconds(self.w, sound.end), start + 0.01)
        span = end - start
        handle = max(0.0, (sound.duration_s - span) / 2)
        slide, reason = 0.0, "no mood change to line up"
        if sound.kind == LANE_SCORE and sound.mood_changes:
            slide, reason = self._slide(sound, start, handle)
        return _Cue(
            sound=sound,
            nominal_start=start,
            nominal_end=end,
            handle_s=handle,
            slide_s=slide,
            slide_reason=reason,
            base=handle + slide,
        )

    def _slide(self, sound: Sound, start: float, handle: float) -> tuple[float, str]:
        """Slide to fit: a planned change of mood that the take makes late or early moves the
        take so that it lands on the plan. Only a strong change point counts (RM-8), and the
        slide never goes beyond the handles.
        """
        if handle < 1.0:
            return 0.0, "too little spare length to slide"
        points = [
            (float(point["time_s"]), float(point.get("strength") or 0.0))
            for point in sound.measurement.get("change_points") or []
            if float(point.get("strength") or 0.0) >= SLIDE_MIN_STRENGTH
        ]
        search = min(handle, SLIDE_MAX_SEARCH_S)
        for anchor in sound.mood_changes:
            planned = exact_seconds(self.w, anchor)
            expected = handle + (planned - start)
            near = [p for p in points if abs(p[0] - expected) <= search]
            if near:
                actual = min(near, key=lambda p: abs(p[0] - expected))[0]
                slide = actual - expected
                return round(slide, 3), (
                    f"the take changes at {actual:.1f} s, expected {expected:.1f} s"
                )
        return 0.0, "no strong change point near a planned mood change"

    @staticmethod
    def _technique(style: str | None) -> tuple[str, float]:
        """The technique of an edge from its style, and the default length of its fade."""
        if style in ("hard_start", "hard_stop", "sting"):
            return "hard", EDGE_FADE_S
        if style == "musical_ending":
            return "ending", EDGE_FADE_S
        factor = RISE_FADE_FACTOR if style == "rise_from_ambience" else 1.0
        return "fade", factor * DEFAULT_FADE_S

    def _beds_playing(self, t: float) -> bool:
        return any(c.sound.kind == "bed" and c.start_t <= t <= c.end_t for c in self.cues.values())

    def _place_lane(self, lane: str) -> None:
        sounds = [s for s in self.data.sounds if s.role == "cue" and s.kind == lane]
        cues = {s.cue_id: self._init_cue(s) for s in sounds}
        over_sound: list[Boundary] = []
        by_end: set[str] = set()
        by_start: set[str] = set()
        through_silence: list[Boundary] = []
        for boundary in self.data.boundaries:
            if boundary.from_id not in cues or boundary.to_id not in cues:
                continue
            if boundary.join in JOINS_OVER_SOUND:
                over_sound.append(boundary)
                by_end.add(boundary.from_id)
                by_start.add(boundary.to_id)
            else:
                through_silence.append(boundary)

        # An edge that no crossfade, cover or hard cut decides is an ordinary edge. That includes
        # both sides of a join through silence: each cue meets the silence as a fade.
        for cue_id, cue in cues.items():
            if cue_id not in by_start:
                self._start_edge(cue)
            if cue_id not in by_end:
                self._end_edge(cue)

        self.cues.update(cues)
        for boundary in through_silence:
            earlier, later = cues[boundary.from_id], cues[boundary.to_id]
            self.joins.append(
                {
                    "from": boundary.from_id,
                    "to": boundary.to_id,
                    "type": boundary.join,
                    "made_as": boundary.join,
                    "point_s": round((earlier.end_t + later.start_t) / 2, 3),
                    "length_s": round(max(0.0, later.start_t - earlier.end_t), 3),
                    "ladder_step": max(
                        (earlier.end_edge or {}).get("ladder_step", 0),
                        (later.start_edge or {}).get("ladder_step", 0),
                    ),
                    "notes": [],
                }
            )
            earlier.join_out = {"with": boundary.to_id, "type": boundary.join}
            later.join_in = {"with": boundary.from_id, "type": boundary.join}
        for boundary in over_sound:
            self._join_over_sound(cues[boundary.from_id], cues[boundary.to_id], boundary)
        for cue in cues.values():
            self._finish_cue(cue)

    def _start_edge(self, cue: _Cue) -> None:
        sound = cue.sound
        assert sound.start is not None
        style = sound.start_style or "fade_in"
        technique, fade = self._technique(style)
        if style == "rise_from_ambience" and not self._beds_playing(cue.nominal_start):
            cue.notes.append("Meant to rise out of an ambience bed, but none is playing.")
            fade = DEFAULT_FADE_S
        if sound.fade_in_s is not None and style == "fade_in":
            fade = sound.fade_in_s
        edge = self._edge(
            edge_id=f"{sound.cue_id}:start",
            cue=cue,
            side="start",
            anchor=sound.start,
            technique=technique,
            important=sound.important_start,
        )
        cue.start_edge, cue.start_t = edge, edge["chosen_s"]
        cue.fade_in_s = (
            EDGE_FADE_S if edge["technique"] == "hard" else max(fade, edge["fade_s"] or 0.0)
        )

    def _end_edge(self, cue: _Cue) -> None:
        sound = cue.sound
        assert sound.end is not None
        style = sound.end_style or "fade_out"
        technique, fade = self._technique(style)
        if sound.fade_out_s is not None and style == "fade_out":
            fade = sound.fade_out_s
        edge = self._edge(
            edge_id=f"{sound.cue_id}:end",
            cue=cue,
            side="stop",
            anchor=sound.end,
            technique=technique,
            important=False,
        )
        cue.end_edge, cue.end_t = edge, edge["chosen_s"]
        if edge["technique"] == "fade" and edge["fade_s"]:
            fade = edge["fade_s"]
        cue.fade_out_s = EDGE_FADE_S if edge["technique"] in ("hard", "ending") else fade
        if edge["technique"] == "ending":
            self._back_time(cue)

    def _back_time(self, cue: _Cue) -> None:
        """A musical ending: the end of the take's sound lands on the end point."""
        trailing = float(cue.sound.measurement.get("trailing_silence_s") or 0.0)
        sound_end = max(cue.duration - trailing, 0.0)
        cue.base = sound_end - (cue.end_t - cue.nominal_start)
        cue.source_out_limit = sound_end
        cue.back_timed = True
        cue.slide_s, cue.slide_reason = 0.0, "back-timed to the recording's own ending"

    def _quiet_score(self, earlier: _Cue, later: _Cue, t: float) -> float:
        a = lufs_at(earlier.sound.measurement, earlier.src(t))
        b = lufs_at(later.sound.measurement, later.src(t))
        return 10 * math.log10(10 ** (a / 10) + 10 ** (b / 10))

    def _join_over_sound(self, earlier: _Cue, later: _Cue, boundary: Boundary) -> None:
        low = min(later.nominal_start, earlier.nominal_end)
        high = max(later.nominal_start, earlier.nominal_end)
        centre = (low + high) / 2
        width = max(high - low, self.p.loose_s)
        window = self._clip(centre - width / 2, centre + width / 2)
        step, notes = 0, []
        point: float | None = None
        length = 0.0
        kind = boundary.join

        if kind == "crossfade":
            point = self._crossfade_point(earlier, later, window)
            length = self.p.crossfade_s
        else:
            for attempt, win in enumerate((window, self._widen(window))):
                if attempt == 1 and self.p.widen_factor <= 0:
                    break
                point = self._cover_point(kind, win, centre)
                if point is not None:
                    step = attempt
                    break
            if point is None:
                point, step = centre, 2
                kind = "crossfade"
                notes.append(
                    "No cut, hit or line to carry the join: it is a short crossfade in the open."
                )
                if boundary.join == "hard_cut":
                    self.flags.append(
                        {
                            "cue_id": later.sound.cue_id,
                            "item_id": later.sound.item_id,
                            "edge": "join",
                            "second": round(centre, 3),
                            "message": f"The hard cut into {later.sound.cue_id} has no shot cut "
                            f"near {centre:.1f} s: crossfaded instead.",
                        }
                    )
            length = EDGE_FADE_S if boundary.join == "hard_cut" and step == 0 else COVER_CROSSFADE_S

        available_after = earlier.duration - earlier.src(point)
        available_before = later.src(point)
        wanted = length
        length = min(length, 2 * available_after, 2 * available_before)
        if wanted >= MIN_CROSSFADE_S and length < MIN_CROSSFADE_S:
            notes.append("Too little spare sound for a crossfade: a hard cut.")
        if length < MIN_CROSSFADE_S:
            length = EDGE_FADE_S
        shape = "equal_power" if length > EDGE_FADE_S else "linear"
        earlier.end_t = point + length / 2
        earlier.fade_out_s, earlier.fade_out_shape = length, shape
        later.start_t = point - length / 2
        later.fade_in_s, later.fade_in_shape = length, shape
        self.joins.append(
            {
                "from": earlier.sound.cue_id,
                "to": later.sound.cue_id,
                "type": boundary.join,
                "made_as": kind if length > EDGE_FADE_S else "hard_cut",
                "point_s": round(point, 3),
                "length_s": round(length, 3),
                "ladder_step": step,
                "notes": notes,
            }
        )
        earlier.join_out = {"with": later.sound.cue_id, "type": boundary.join}
        later.join_in = {"with": earlier.sound.cue_id, "type": boundary.join}

    def _crossfade_point(self, earlier: _Cue, later: _Cue, window: tuple[float, float]) -> float:
        """The quietest moment of both takes together inside the window, preferring a pause in
        the speech or a cut.
        """
        low, high = window
        steps = max(0, int((high - low) / GRID_S))
        options: list[tuple[bool, float, float, float]] = []
        centre = (low + high) / 2
        for number in range(steps + 1):
            t = low + number * GRID_S
            near_cut = any(abs(t - cut) <= self.frame_s for cut in self.w.cuts_s)
            preferred = near_cut or not self.in_word(t)
            options.append(
                (not preferred, self._quiet_score(earlier, later, t), abs(t - centre), t)
            )
        return min(options)[3] if options else centre

    def _cover_point(self, kind: str, window: tuple[float, float], centre: float) -> float | None:
        low, high = window
        found: list[_Cand] = []
        for cut in self.w.cuts_s:
            if low <= cut <= high:
                found.append(_Cand("cut", cut, 0, ""))
        for moment, _label in self.moments:
            if low <= moment <= high:
                found.append(_Cand("hit", moment, 0, ""))
        if kind == "under_cover":
            for start, end in self.words:
                lo, hi = max(low, start + 0.3), min(high, end - 0.3)
                if lo <= hi:
                    found.append(_Cand("speech", min(max(centre, lo), hi), 0, ""))
        best = _best(found, centre)
        return best.t if best is not None else None

    def _finish_cue(self, cue: _Cue) -> None:
        sound = cue.sound
        total = self.w.total_s
        start_t, end_t = cue.start_t, cue.end_t
        src_lo, src_hi = cue.src(start_t), cue.src(end_t)
        if start_t < 0:
            src_lo, start_t = src_lo - start_t, 0.0
        if end_t > total:
            src_hi, end_t = src_hi - (end_t - total), total
        if src_lo < 0:
            cue.notes.append(
                f"The take has no sound for the first {-src_lo:.1f} s of its span: it starts later."
            )
            start_t, src_lo = start_t - src_lo, 0.0
        limit = cue.source_out_limit if cue.source_out_limit is not None else cue.duration
        if src_hi > limit + 1e-6:
            cue.notes.append(f"The take is {src_hi - limit:.1f} s too short: it ends earlier.")
            end_t, src_hi = end_t - (src_hi - limit), limit
        length = max(0, to_sample(src_hi) - to_sample(src_lo))
        if end_t - start_t < MIN_CUE_S:
            self.flags.append(
                {
                    "cue_id": sound.cue_id,
                    "item_id": sound.item_id,
                    "edge": "span",
                    "second": round(start_t, 3),
                    "message": f"{sound.cue_id} is only {max(end_t - start_t, 0):.1f} s long "
                    "once placed.",
                }
            )
        fade_in = min(to_sample(cue.fade_in_s), length)
        fade_out = min(to_sample(cue.fade_out_s), max(0, length - fade_in))
        integrated = (sound.measurement.get("loudness") or {}).get("integrated_lufs")
        gain = (
            round(max(-MATCH_MAX_DB, min(MATCH_MAX_DB, MATCH_LUFS - float(integrated))), 2)
            if isinstance(integrated, int | float)
            else 0.0
        )
        cue.start_t, cue.end_t = start_t, end_t
        self.placements.append(
            {
                **self._common(sound),
                "lane": sound.kind,
                "story_start_sample": to_sample(start_t),
                "source_in_sample": to_sample(src_lo),
                "source_out_sample": to_sample(src_lo) + length,
                "length_samples": length,
                "fade_in": {"samples": fade_in, "shape": cue.fade_in_shape},
                "fade_out": {"samples": fade_out, "shape": cue.fade_out_shape},
                "match_gain_db": gain,
                "start": _edge_out(cue.start_edge),
                "end": _edge_out(cue.end_edge),
                "moment": None,
                "join_in": cue.join_in,
                "join_out": cue.join_out,
                "slide_s": cue.slide_s,
                "slide_reason": cue.slide_reason,
                "back_timed": cue.back_timed,
                "fallbacks": [
                    note
                    for edge in (cue.start_edge, cue.end_edge)
                    if edge
                    for note in edge["notes"]
                ]
                + cue.fallbacks,
                "notes": cue.notes,
            }
        )
        for edge in (cue.start_edge, cue.end_edge):
            if edge and edge["covered"] and edge["kind"] == "bed_swell":
                self.mix_requests.append(
                    {
                        "kind": "swell",
                        "cue_id": sound.cue_id,
                        "second": round(edge["chosen_s"], 3),
                        "length_s": 1.5,
                        "reason": edge["description"],
                    }
                )

    # -- the whole run --

    def run(self) -> PlacementResult:
        self._place_moments()
        self._place_lane(LANE_BED)
        self._place_lane(LANE_SCORE)
        inside: list[dict[str, Any]] = []
        for placement in self.placements:
            for side in ("start", "end"):
                edge = placement.get(side)
                if edge and edge["inside_speech"]:
                    inside.append(
                        {
                            "cue_id": placement["cue_id"],
                            "edge": side,
                            "second": round(edge["chosen_s"], 3),
                            "flagged": edge["flagged"],
                        }
                    )
        for flag in self.flags:
            flag.setdefault("flagged", True)
        content = {
            "version": PLACER_VERSION,
            "sample_rate": SAMPLE_RATE,
            "total_samples": self.w.total_samples,
            "constants": constants(self.p),
            "placements": sorted(self.placements, key=lambda p: p["story_start_sample"]),
            "joins": self.joins,
            "h3_sounds": self.h3_out,
            "mix_requests": self.mix_requests,
            "choices": self.choice_log,
            "flags": self.flags,
            "facts": {
                "placed": len(self.placements),
                "inside_speech": inside,
                "model_asked": len(self.pending),
            },
        }
        return PlacementResult(content=content, pending=self.pending)


def _edge_out(edge: dict[str, Any] | None) -> dict[str, Any] | None:
    if edge is None:
        return None
    return {key: value for key, value in edge.items() if key != "fade_s"} | {
        "chosen_sample": to_sample(edge["chosen_s"])
    }


def place(data: PlacementInput, choices: Mapping[str, str | None] | None = None) -> PlacementResult:
    """Places every sound. Pure and deterministic.

    The first run (`choices` empty) returns the questions for the model in `pending`: each has an
    `id` and its real `candidates`, one marked `code_best`. Run again with
    `choices={id: candidate id}` (a missing or unusable answer is `None`) for the final result;
    then `pending` is empty. With no pending question the first result is final.
    """
    return _Placer(data, choices or {}).run()
