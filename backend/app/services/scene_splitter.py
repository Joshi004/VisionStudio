"""The rule-based splitter (ANALYSIS.md Section 5.2). Pure functions, no I/O.

It does two jobs:

- `enforce_limits` checks a list of cuts (the language model's, or the user's) against the
  project's shortest and longest scene, splits scenes that are too long and merges scenes
  that are too short. Every change is marked on the cut that ends the changed scene.
- `split_alone` proposes cuts with no help from the language model, when it failed twice.
  It starts with a cut at every paragraph break and then enforces the limits.

Where to cut, best first (`boundary_rank`): a paragraph break, the end of a sentence,
clause punctuation, a pause, anywhere. Parakeet's word times have almost no gaps, so a
pause is a weak signal, and the rank mostly comes from the script's own punctuation.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Final

from app.services.scene_cuts import Cut, Word, cut_time

# Times are stored with 3 decimals, so a length this close to a limit counts as on it.
_EPS: Final = 0.001
# A silence this long between two words is a "pause" boundary.
_PAUSE_GAP_S: Final = 0.5
# A silence this long inside a scene gets a note.
_LONG_SILENCE_S: Final = 1.5

RANK_PARAGRAPH: Final = 4
RANK_SENTENCE: Final = 3
RANK_CLAUSE: Final = 2
RANK_PAUSE: Final = 1
RANK_ANYWHERE: Final = 0

_CLOSERS: Final = "\"'\u201d\u2019)]}\u00bb"
_SENTENCE_END: Final = ".?!\u2026"
_CLAUSE_END: Final = ",;:\u2014\u2013"


@dataclass(frozen=True)
class SplitStats:
    cuts_added: int
    cuts_removed: int


@dataclass(frozen=True)
class _Scene:
    first: int  # first word
    last: int  # last word
    start: float
    end: float

    @property
    def length(self) -> float:
        return self.end - self.start


def boundary_rank(words: Sequence[Word], k: int) -> int:
    """How good a place to cut it is, right after word `k` (4 is best, 0 is worst)."""
    if not 0 <= k < len(words) - 1:
        raise ValueError(f"There is no boundary after word {k}.")
    current, following = words[k], words[k + 1]
    if current.paragraph != following.paragraph:
        return RANK_PARAGRAPH

    text = current.text.rstrip().rstrip(_CLOSERS).rstrip()
    if text and text[-1] in _SENTENCE_END:
        return RANK_SENTENCE
    if text and (text[-1] in _CLAUSE_END or text.endswith((" -", "--"))):
        return RANK_CLAUSE
    if following.start - current.end >= _PAUSE_GAP_S:
        return RANK_PAUSE
    return RANK_ANYWHERE


def _scenes(words: Sequence[Word], cuts: Sequence[Cut], audio_end_s: float) -> list[_Scene]:
    last_index = len(words) - 1
    scenes: list[_Scene] = []
    first = 0
    start = 0.0
    for cut in cuts:
        end = audio_end_s if cut.last_word == last_index else cut_time(words, cut.last_word)
        scenes.append(_Scene(first=first, last=cut.last_word, start=start, end=end))
        first = cut.last_word + 1
        start = end
    return scenes


def _check_cuts(words: Sequence[Word], cuts: Sequence[Cut]) -> None:
    if not words:
        raise ValueError("The script has no words.")
    if not cuts or cuts[-1].last_word != len(words) - 1:
        raise ValueError("The cuts must end with the last word of the script.")
    for earlier, later in zip(cuts, cuts[1:], strict=False):
        if later.last_word <= earlier.last_word:
            raise ValueError("The cuts must be in increasing order.")


def _join_notes(*notes: str | None) -> str | None:
    kept = [note for note in notes if note]
    return "; ".join(kept) if kept else None


def _with_note(cut: Cut, note: str) -> Cut:
    return replace(cut, note=_join_notes(cut.note, note))


# --- Splitting a scene that is too long -------------------------------------------


def _best_split(words: Sequence[Word], scene: _Scene, min_s: float, max_s: float) -> int:
    """The word after which to cut a scene that is too long.

    It prefers a cut that leaves both pieces within [min, max]. Failing that: both at least
    the minimum; both at most the maximum (the maximum is the hard limit, since the video
    API refuses longer clips, while a short clip is only a poor one); anything. Within the
    first group that has a candidate, the best boundary wins, and of equal ranks the one
    closest to the middle of the scene.
    """
    middle = (scene.start + scene.end) / 2
    candidates = range(scene.first, scene.last)

    def pieces(k: int) -> tuple[float, float]:
        time = cut_time(words, k)
        return time - scene.start, scene.end - time

    groups: list[Callable[[float, float], bool]] = [
        lambda a, b: min_s - _EPS <= a <= max_s + _EPS and min_s - _EPS <= b <= max_s + _EPS,
        lambda a, b: a >= min_s - _EPS and b >= min_s - _EPS,
        lambda a, b: a <= max_s + _EPS and b <= max_s + _EPS,
        lambda a, b: True,
    ]
    for fits in groups:
        pool = [k for k in candidates if fits(*pieces(k))]
        if pool:
            return min(
                pool,
                key=lambda k: (-boundary_rank(words, k), abs(cut_time(words, k) - middle)),
            )
    raise ValueError("A scene with a single word cannot be split.")


def _split_long_scenes(
    words: Sequence[Word], cuts: list[Cut], audio_end_s: float, min_s: float, max_s: float
) -> int:
    """Splits scenes longer than the maximum until none can be split further. Returns the
    number of cuts added. Scenes of one word cannot be split.
    """
    added = 0
    while True:
        scenes = _scenes(words, cuts, audio_end_s)
        position = next(
            (
                i
                for i, scene in enumerate(scenes)
                if scene.length > max_s + _EPS and scene.last > scene.first
            ),
            None,
        )
        if position is None:
            return added
        k = _best_split(words, scenes[position], min_s, max_s)
        note = "cut inside a sentence" if boundary_rank(words, k) <= RANK_PAUSE else None
        cuts.insert(position, Cut(last_word=k, source="rule", note=note))
        added += 1


# --- Merging a scene that is too short ---------------------------------------------


def _neighbour_to_merge_with(scenes: Sequence[_Scene], i: int, max_s: float) -> int | None:
    """The shorter neighbour of scene `i` whose merge stays within the maximum. A scene of
    no length is merged even if the result is too long: it cannot be a clip at all.
    """
    neighbours = [j for j in (i - 1, i + 1) if 0 <= j < len(scenes)]
    neighbours.sort(key=lambda j: scenes[j].length)
    for j in neighbours:
        if scenes[i].length + scenes[j].length <= max_s + _EPS:
            return j
    if neighbours and scenes[i].length <= _EPS:
        return neighbours[0]
    return None


def _merge_short_scenes(
    words: Sequence[Word], cuts: list[Cut], audio_end_s: float, min_s: float, max_s: float
) -> int:
    """Merges each scene shorter than the minimum into its shorter neighbour, shortest
    first, while the result fits. Returns the number of cuts removed.
    """
    removed = 0
    while True:
        scenes = _scenes(words, cuts, audio_end_s)
        short = sorted(
            (i for i, scene in enumerate(scenes) if scene.length < min_s - _EPS),
            key=lambda i: scenes[i].length,
        )
        for i in short:
            j = _neighbour_to_merge_with(scenes, i, max_s)
            if j is None:
                continue
            # The cut between the two scenes goes. The cut that ended the later of the two
            # stays, and now ends the merged scene.
            boundary = min(i, j)
            del cuts[boundary]
            cuts[boundary] = _with_note(cuts[boundary], "merged with a scene that was too short")
            removed += 1
            break
        else:
            return removed


# --- Marking what is still not right ----------------------------------------------


def _flag_remaining_problems(
    words: Sequence[Word], cuts: Sequence[Cut], audio_end_s: float, min_s: float, max_s: float
) -> list[Cut]:
    """Adds a note to the cut that ends every scene that is still outside the limits, or
    that holds a long silence, so the review step shows it.
    """
    flagged: list[Cut] = []
    for cut, scene in zip(cuts, _scenes(words, cuts, audio_end_s), strict=True):
        notes: list[str] = []
        if scene.length > max_s + _EPS:
            notes.append(f"longer than the maximum ({scene.length:.1f} s); no place to cut it")
        elif scene.length < min_s - _EPS:
            notes.append(
                f"shorter than the minimum ({scene.length:.1f} s); "
                "merging it would make a scene that is too long"
            )
        gap = max(
            (words[j + 1].start - words[j].end for j in range(scene.first, scene.last)),
            default=0.0,
        )
        if gap >= _LONG_SILENCE_S:
            notes.append(f"a silence of {gap:.1f} s inside this scene")
        flagged.append(_with_note(cut, "; ".join(notes)) if notes else cut)
    return flagged


def enforce_limits(
    words: Sequence[Word],
    cuts: Sequence[Cut],
    audio_end_s: float,
    min_s: float,
    max_s: float,
) -> tuple[list[Cut], SplitStats]:
    """Makes the scenes fit the project's limits.

    `cuts` are in increasing order and end with the script's last word. Cuts the splitter
    adds are `rule` cuts. A cut that survives keeps its own source, and gets a note when
    the splitter changed its scene. Raises ValueError when `cuts` are not in that shape.
    """
    _check_cuts(words, cuts)
    work = list(cuts)
    added = _split_long_scenes(words, work, audio_end_s, min_s, max_s)
    removed = _merge_short_scenes(words, work, audio_end_s, min_s, max_s)
    return _flag_remaining_problems(words, work, audio_end_s, min_s, max_s), SplitStats(
        cuts_added=added, cuts_removed=removed
    )


def split_alone(
    words: Sequence[Word], audio_end_s: float, min_s: float, max_s: float
) -> tuple[list[Cut], SplitStats]:
    """Proposes cuts with no help from the language model: one at every paragraph break,
    then the limits enforced. Every cut is a `rule` cut.
    """
    if not words:
        raise ValueError("The script has no words.")
    paragraph_cuts = [
        Cut(last_word=k, source="rule")
        for k in range(len(words) - 1)
        if words[k].paragraph != words[k + 1].paragraph
    ]
    cuts = [*paragraph_cuts, Cut(last_word=len(words) - 1, source="rule")]
    result, stats = enforce_limits(words, cuts, audio_end_s, min_s, max_s)
    return result, SplitStats(
        cuts_added=stats.cuts_added + len(paragraph_cuts), cuts_removed=stats.cuts_removed
    )
