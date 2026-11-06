"""Where the scenes of a full recording begin and end (REC-004). Pure rules, no I/O.

A person reads the whole script of a recorded explainer in one flow. `word_timings.align` gives
every script word a time, and each scene's words are the next `len(text.split())` of them (the
rule of `take_timings.unit_spans`). The recording can be cut only at a scene boundary, and a cut
is clean only where there is a pause:

- `scene_spans` finds each scene's first and last word and its time.
- `boundaries` looks at each pair of neighbouring scenes. The pause is the start of the next
  scene's first word less the end of this scene's last word. The boundary is **tight** when the
  pause is shorter than the setting, or when either of the two words was not actually heard
  (its time was filled in, not measured). The proposed cut is the middle of the pause.
- `split_windows` turns the cuts into the first and last sample of each scene, so the scenes
  add up to exactly the recording.
- `transcription_pieces` cuts a long recording into pieces under a length, at silences, for the
  transcription server (R-6).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

# How many words of each scene a tight boundary shows around the cut.
CONTEXT_WORDS: Final = 6


class BoundaryError(ValueError):
    """The scenes and the timed words do not add up. The message is meant for the user."""


@dataclass(frozen=True)
class SceneText:
    """One scene of the script a person reads: its id and the take text it is read from."""

    scene_id: str
    text: str


@dataclass(frozen=True)
class SceneSpan:
    """Where one scene sits in the recording's timed words. `first_word` and `last_word` are
    positions (from 0) in the recording's words; `start` and `end` are seconds.
    """

    scene_id: str
    first_word: int
    last_word: int
    start: float
    end: float


@dataclass(frozen=True)
class Boundary:
    """The change from one scene to the next."""

    after_scene_id: str
    before_scene_id: str
    # The silence between the two scenes' words, in seconds.
    pause_s: float
    # The middle of the pause: where the recording is cut unless the owner decides otherwise.
    cut_s: float
    tight: bool
    # One sentence for each reason the boundary is tight; empty when it is clean.
    reasons: list[str]
    # The last words of the scene before and the first words of the scene after.
    before_words: str
    after_words: str


# --- Scenes ---------------------------------------------------------------------------------


def scene_spans(scenes: Sequence[SceneText], words: Sequence[dict[str, Any]]) -> list[SceneSpan]:
    """The span of each scene inside the recording's timed words. Each scene takes the next
    `len(text.split())` words. Raises BoundaryError when the scenes and the words do not add up.
    """
    spans: list[SceneSpan] = []
    position = 0
    for scene in scenes:
        count = len(scene.text.split())
        if count == 0:
            raise BoundaryError(f"The scene '{scene.scene_id}' has no words to read.")
        last = position + count - 1
        if last >= len(words):
            raise BoundaryError("The recording has fewer timed words than the script.")
        spans.append(
            SceneSpan(
                scene_id=scene.scene_id,
                first_word=position,
                last_word=last,
                start=float(words[position]["start"]),
                end=float(words[last]["end"]),
            )
        )
        position = last + 1
    if position != len(words):
        raise BoundaryError("The recording has more timed words than the script.")
    return spans


def _word_heard(word: dict[str, Any]) -> bool:
    """Whether a word was heard. A timing that carries no flag is not trusted."""
    return word.get("heard") is True


def boundaries(
    spans: Sequence[SceneSpan], words: Sequence[dict[str, Any]], min_pause_s: float
) -> list[Boundary]:
    """One boundary for each pair of neighbouring scenes, in order."""
    found: list[Boundary] = []
    for before, after in zip(spans, spans[1:], strict=False):
        last_word = words[before.last_word]
        first_word = words[after.first_word]
        pause_s = max(0.0, after.start - before.end)
        reasons: list[str] = []
        if pause_s < min_pause_s:
            reasons.append(
                f"The pause between the scenes is {round(pause_s * 1000)} ms, "
                f"less than the {round(min_pause_s * 1000)} ms needed."
            )
        if not _word_heard(last_word):
            reasons.append(
                f"The last word of the scene before, '{last_word['text']}', was not heard."
            )
        if not _word_heard(first_word):
            reasons.append(
                f"The first word of the scene after, '{first_word['text']}', was not heard."
            )
        before_from = max(before.first_word, before.last_word - CONTEXT_WORDS + 1)
        after_to = min(after.last_word, after.first_word + CONTEXT_WORDS - 1)
        found.append(
            Boundary(
                after_scene_id=before.scene_id,
                before_scene_id=after.scene_id,
                pause_s=round(pause_s, 3),
                cut_s=round(before.end + pause_s / 2, 3),
                tight=bool(reasons),
                reasons=reasons,
                before_words=" ".join(
                    str(w["text"]) for w in words[before_from : before.last_word + 1]
                ),
                after_words=" ".join(
                    str(w["text"]) for w in words[after.first_word : after_to + 1]
                ),
            )
        )
    return found


# --- The split ------------------------------------------------------------------------------


def split_windows(
    total_samples: int, cuts_s: Sequence[float], sample_rate: int
) -> list[tuple[int, int]]:
    """The first and last (exclusive) sample of each scene. `cuts_s` are the cuts between
    neighbouring scenes in seconds, in order, so there is one more scene than cuts. The first
    scene starts at sample 0 and the last ends at `total_samples`. A cut is rounded to a sample
    and kept inside the recording and after the cut before it, so no scene is empty.
    Raises BoundaryError when the recording is too short to hold the scenes.
    """
    scene_count = len(cuts_s) + 1
    if total_samples < scene_count:
        raise BoundaryError("The recording is too short to be split into its scenes.")
    points = [0]
    for index, cut in enumerate(cuts_s):
        remaining = len(cuts_s) - index  # scenes still to come after this cut
        sample = round(cut * sample_rate)
        sample = max(sample, points[-1] + 1)
        sample = min(sample, total_samples - remaining)
        points.append(sample)
    points.append(total_samples)
    return list(zip(points, points[1:], strict=False))


# --- Pieces for the transcription server ----------------------------------------------------


def transcription_pieces(
    duration_s: float, silences: Sequence[tuple[float, float]], piece_s: float
) -> list[tuple[float, float]]:
    """Cuts a recording into consecutive pieces of at most `piece_s` seconds, as `(start, end)`
    in seconds. A recording that is not longer than that is one piece. A cut is the middle of
    the latest silence in the second half of the piece; with none there it is a hard cut at the
    limit. `silences` are `(start, end)` pairs.
    """
    if duration_s <= piece_s:
        return [(0.0, duration_s)]
    pieces: list[tuple[float, float]] = []
    start = 0.0
    while duration_s - start > piece_s:
        lower = start + piece_s / 2
        upper = start + piece_s
        middles = [
            (silence_start + silence_end) / 2
            for silence_start, silence_end in silences
            if lower < (silence_start + silence_end) / 2 <= upper
        ]
        cut = max(middles) if middles else upper
        pieces.append((start, cut))
        start = cut
    pieces.append((start, duration_s))
    return pieces
