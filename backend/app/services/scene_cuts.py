"""Cuts and scenes (ANALYSIS.md Section 5.2). Pure functions, no I/O.

A *cut* is named by the number of the last word of the scene it ends. The script's words
and their times come from the transcript (`transcript.script_words`). Every proposal,
whether it came from the language model or from the rule-based splitter, ends up as a
list of `Cut`s, and `build_scene_specs` turns that list into the rows of the `scene`
table. Phase 7 (editing cuts) reuses the same function, so a scene looks the same
whoever placed its cut.

Where a cut falls in time: in the middle of the silence between the last word of one
scene and the first word of the next. The first scene starts at 0.0 and the last one
ends at the end of the audio.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from app.db.models import Scene

CutSource = Literal["ai", "rule", "manual"]

_TIME_DECIMALS: Final = 3

# How far a stored scene time may differ from the time `build_scene_specs` works out again
# (times are stored with 3 decimals).
_TIME_TOLERANCE_S: Final = 0.0005

# The values that clear a scene's inputs (Phase 7: "discard inputs"): exactly the columns
# `has_inputs` reads. `use_clip_sound` is a preference, not an input, so it stays. Phase 8
# and 9 add their input columns here and to `has_inputs` together.
NO_INPUTS: Final[dict[str, None]] = {
    "scene_description": None,
    "scene_description_source": None,
    "first_frame_description": None,
    "last_frame_description": None,
    "frame_descriptions_source": None,
    "description_job_id": None,
    "first_frame_asset_id": None,
    "last_frame_asset_id": None,
    "selected_clip_asset_id": None,
}


@dataclass(frozen=True)
class Word:
    index: int  # 0-based, over every word of the script
    text: str  # as written, with its punctuation
    start: float
    end: float
    paragraph: int  # 0-based


@dataclass(frozen=True)
class Cut:
    """The end of a scene, named by the number of its last word."""

    last_word: int
    source: CutSource
    # Why this cut needs a look, if it does. Stored as `scene.cut_note`.
    note: str | None = None


@dataclass(frozen=True)
class SceneSpec:
    """One `scene` row to be written."""

    index: int
    start_s: float
    end_s: float
    text: str
    first_word: int
    last_word: int
    cut_source: str
    cut_note: str | None


def words_from_script_words(script_words: object) -> list[Word]:
    """Reads `transcript.script_words` (DATABASE_STRUCTURE.md Section 5).

    Raises ValueError when the stored value is not in that shape.
    """
    if not isinstance(script_words, list):
        raise ValueError("The transcript's script words are not a list.")
    words: list[Word] = []
    for position, entry in enumerate(script_words):
        try:
            word = Word(
                index=entry["index"],
                text=entry["word"],
                start=float(entry["start"]),
                end=float(entry["end"]),
                paragraph=entry["paragraph"],
            )
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"Script word {position} is not in the expected shape.") from None
        if word.index != position or not isinstance(word.text, str) or not word.text:
            raise ValueError(f"Script word {position} is not in the expected shape.")
        words.append(word)
    return words


def cut_time(words: Sequence[Word], last_word: int) -> float:
    """The time of the cut after word `last_word`: the middle of the silence between that
    word and the next one. The last word of the script has no next word, so it has no cut
    time (the last scene ends at the end of the audio).
    """
    if not 0 <= last_word < len(words) - 1:
        raise ValueError(f"There is no cut after word {last_word}.")
    return round((words[last_word].end + words[last_word + 1].start) / 2, _TIME_DECIMALS)


def end_of_audio(duration_s: float | None, words: Sequence[Word]) -> float:
    """Where the last scene ends: the voiceover's length, or the last word's end when the
    length is unknown. Never before the last word's end, which would give it no length.
    """
    last_end = words[-1].end if words else 0.0
    if duration_s is None or duration_s <= 0:
        return round(last_end, _TIME_DECIMALS)
    return round(max(duration_s, last_end), _TIME_DECIMALS)


def build_scene_specs(
    words: Sequence[Word], cuts: Sequence[Cut], audio_end_s: float
) -> list[SceneSpec]:
    """Turns cuts into scenes: times, text, `cut_source` and `cut_note`.

    `cuts` are in increasing order and end with the script's last word. Raises ValueError
    when they do not, or when a scene would end up with no length.
    """
    if not words:
        raise ValueError("The script has no words.")
    last_index = len(words) - 1
    if not cuts or cuts[-1].last_word != last_index:
        raise ValueError("The cuts must end with the last word of the script.")

    specs: list[SceneSpec] = []
    first_word = 0
    start = 0.0
    previous = -1
    for index, cut in enumerate(cuts):
        if cut.last_word <= previous:
            raise ValueError("The cuts must be in increasing order.")
        end = (
            round(audio_end_s, _TIME_DECIMALS)
            if cut.last_word == last_index
            else cut_time(words, cut.last_word)
        )
        if end <= start:
            raise ValueError(
                f"Scene {index + 1} would have no length (it ends at {end:.3f} s, "
                f"after starting at {start:.3f} s)."
            )
        specs.append(
            SceneSpec(
                index=index,
                start_s=start,
                end_s=end,
                text=" ".join(word.text for word in words[first_word : cut.last_word + 1]),
                first_word=first_word,
                last_word=cut.last_word,
                cut_source=cut.source,
                cut_note=cut.note,
            )
        )
        previous = cut.last_word
        first_word = cut.last_word + 1
        start = end
    return specs


def cuts_from_scenes(
    words: Sequence[Word], scenes: Sequence[Scene | Any], audio_end_s: float
) -> list[Cut]:
    """The cuts that made these scenes: the inverse of `build_scene_specs`.

    The `scene` table stores no word numbers, but a scene's text is its words joined by
    single spaces, so each scene is matched to the words that follow the previous scene.
    `scenes` are in order. Every scene must match, and the times `build_scene_specs` works
    out from the cuts must equal the stored ones, so that an edit rebuilds only what it
    changes and leaves every other scene exactly as it is. Raises ValueError when they
    do not (the scenes came from other words, or were made another way).
    """
    cuts: list[Cut] = []
    next_word = 0
    for position, scene in enumerate(scenes):
        if scene.index != position:
            raise ValueError("The scene numbers are not 0 to n-1 in order.")
        joined = ""
        last_word: int | None = None
        for k in range(next_word, len(words)):
            joined = words[k].text if k == next_word else f"{joined} {words[k].text}"
            if joined == scene.text:
                last_word = k
                break
            if len(joined) > len(scene.text):
                break
        if last_word is None:
            raise ValueError(f"The text of scene {position + 1} is not in the script's words.")
        cuts.append(Cut(last_word=last_word, source=scene.cut_source, note=scene.cut_note))
        next_word = last_word + 1
    if not cuts or next_word != len(words):
        raise ValueError("The scenes do not cover the whole script.")

    for spec, scene in zip(build_scene_specs(words, cuts, audio_end_s), scenes, strict=True):
        if (
            abs(spec.start_s - scene.start_s) > _TIME_TOLERANCE_S
            or abs(spec.end_s - scene.end_s) > _TIME_TOLERANCE_S
        ):
            raise ValueError(f"The times of scene {spec.index + 1} do not fit the script's words.")
    return cuts


def _has_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def has_inputs(scene: Scene | Any) -> bool:
    """True when the scene holds something the user (or a later phase) put there: a
    description, either frame or a chosen clip. Replacing such a scene asks first. Keep the
    columns in step with `NO_INPUTS`.
    """
    description = scene.scene_description
    return bool(
        (isinstance(description, str) and description.strip())
        or _has_text(scene.first_frame_description)
        or _has_text(scene.last_frame_description)
        or scene.first_frame_asset_id is not None
        or scene.last_frame_asset_id is not None
        or scene.selected_clip_asset_id is not None
    )
