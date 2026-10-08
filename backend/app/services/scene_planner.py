"""Proposing scene cuts with a language model (ANALYSIS.md Section 5.2 and 6.4,
`ScenePlanner`). Pure functions, no I/O.

The model decides *where* a scene ends in the words. Code decides *when*, and checks the
model's work:

1. `build_request`: the script with a number and a start time in front of every word, the
   rules, and the project's own instructions, as an OpenAI-style chat request.
2. `parse_answer`: the model's JSON, read defensively.
3. `check_cuts`: each cut is named by the number of a word, and the words quoted either
   side act as a checksum. A number that is a word or two off is moved to the place where
   the quoted words do match. A cut that matches nowhere nearby keeps its number and is
   flagged.

The calls to the model are made by `providers/llm.py` and the job that drives all this is
`jobs/plan_scenes.py`. The limits are enforced afterwards by `scene_splitter.py`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from app.providers import llm
from app.services.scene_cuts import Cut, Word
from app.services.transcript_matching import normalise

# A longer script is refused (Section 5.2: only 1-minute scripts need no splitting for
# small context windows). About 10 minutes of speech.
MAX_SCRIPT_WORDS: Final = 1500
# Hidden reasoning tokens are billed as output (Section 6.2, rule 4), so the answer is capped.
MAX_TOKENS: Final = 16000
# GLM-5.3-Flash always reasons. "high" gave the same cuts as "max" in half the time, while
# "low" ignored the length limits (Phase 6 plan, Spike 3).
REASONING_EFFORT: Final = "high"
# A cut is moved at most this many words to make its quoted words match.
CHECKSUM_WINDOW: Final = 3

_PROMPT_WORD_DECIMALS: Final = 2

_SYSTEM_PROMPT: Final = "\n".join(
    [
        "You split the script of a voiceover into scenes for a video. Each scene becomes one "
        "video clip, and scenes are joined with hard cuts.",
        "",
        "Rules:",
        "1. Every scene lasts at least {min_s:g} seconds and at most {max_s:g} seconds. "
        "A scene runs from the start time of its first word to the start time of the next "
        "scene's first word. The first scene starts at 0.00 and the last scene ends at "
        "{end_s:.2f}.",
        "2. Where to cut, best first: at a paragraph break (a blank line in the script), "
        "at the end of a sentence, at clause punctuation (a comma, semicolon, colon or dash), "
        "at a pause. Do not cut in the middle of a phrase. Avoid very short scenes.",
        "3. Keep one visual idea in one scene. There is no target length.",
        "4. Scenes follow the script in order, cover all of it, and do not overlap.",
        "",
        "Answer with a JSON object only, in exactly this form:",
        '{{"scenes": [{{"last_word": 57, "words_before_cut": "the lazy dog", '
        '"words_after_cut": "Then the fox"}}]}}',
        "- One entry per scene, in order, including the last scene.",
        "- last_word is the number of the scene's last word, copied from the script.",
        "- words_before_cut is the three words that end the scene (the last of them is "
        "last_word), and words_after_cut is the three words that start the next scene, "
        'both copied exactly. For the last scene, words_after_cut is "".',
    ]
)


def build_request(
    words: Sequence[Word],
    *,
    model: str,
    min_s: float,
    max_s: float,
    audio_end_s: float,
    instructions: str | None,
) -> dict[str, Any]:
    """The exact request body sent to the model. Nothing about the call is hidden from the
    job record: this body is stored on the job (Section 4.3, `job.input`).
    """
    system = _SYSTEM_PROMPT.format(min_s=min_s, max_s=max_s, end_s=audio_end_s)

    paragraphs: list[list[str]] = []
    current = -1
    for word in words:
        if word.paragraph != current or not paragraphs:
            paragraphs.append([])
            current = word.paragraph
        paragraphs[-1].append(f"[{word.index}|{word.start:.{_PROMPT_WORD_DECIMALS}f}] {word.text}")
    script = "\n\n".join(" ".join(paragraph) for paragraph in paragraphs)

    user = ""
    if instructions and instructions.strip():
        user += f"Extra instructions from the author:\n{instructions.strip()}\n\n"
    user += (
        f"Script: {len(words)} words, {audio_end_s:.2f} seconds of audio. "
        "Each word is written as [number|start time in seconds] followed by the word. "
        f"Blank lines are paragraph breaks.\n\n{script}"
    )

    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": MAX_TOKENS,
        "stream": False,
        "response_format": {"type": "json_object"},
        "reasoning_effort": REASONING_EFFORT,
    }


def request_hash(called_url: str, body: dict[str, Any]) -> str:
    """The cache key: the same address and the same request body give the same hash, so the
    same inputs never cost a second paid call (Section 6.2, rule 3).
    """
    canonical = json.dumps(
        {"url": called_url, "body": body},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --- Reading the answer ------------------------------------------------------------


def parse_answer(content: str) -> list[Any]:
    """The list of scenes in the model's answer. Raises ValueError, with a message fit for
    the user, when there is none.
    """
    if not content.strip():
        raise ValueError("The model's answer was empty.")
    answer = llm.parse_json_object(content)
    scenes = answer.get("scenes") if isinstance(answer, dict) else None
    if not isinstance(scenes, list):
        raise ValueError('The model\'s answer had no "scenes" list.')
    if not scenes:
        raise ValueError("The model's answer had no scenes.")
    return scenes


# --- Checking the cuts -------------------------------------------------------------


@dataclass(frozen=True)
class CheckStats:
    entries: int  # entries in the answer
    exact: int  # number and checksum words agree
    moved: int  # the number was off, and a nearby word fits the checksum words
    flagged: int  # the checksum words fit nowhere nearby: kept at the model's number
    dropped: int  # unusable: not a number, out of order, or after the end

    @property
    def has_valid_entries(self) -> bool:
        return self.entries - self.dropped > 0


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _quoted_words(value: object) -> list[str]:
    """The quoted words, each normalised (case, punctuation and apostrophes ignored)."""
    if not isinstance(value, str):
        return []
    return [token for token in (normalise(part) for part in value.split()) if token]


def _fits(script: Sequence[str], k: int, before: list[str], after: list[str]) -> tuple[bool, bool]:
    """Whether the quoted words match the script right before and right after word `k`."""
    before_ok = (
        bool(before)
        and k - len(before) + 1 >= 0
        and list(script[k - len(before) + 1 : k + 1]) == before
    )
    if k == len(script) - 1:
        after_ok = not after  # nothing follows the last word
    else:
        after_ok = bool(after) and list(script[k + 1 : k + 1 + len(after)]) == after
    return before_ok, after_ok


def _nearby_match(
    script: Sequence[str], k: int, before: list[str], after: list[str], low: int, high: int
) -> int | None:
    """The closest word to `k` (within the window, between `low` and `high`) where both
    quoted word groups match. Ties go to the later word, the usual off-by-one.
    """
    for distance in range(1, CHECKSUM_WINDOW + 1):
        for candidate in (k + distance, k - distance):
            if low <= candidate <= high and all(_fits(script, candidate, before, after)):
                return candidate
    return None


def check_cuts(words: Sequence[Word], entries: Sequence[Any]) -> tuple[list[Cut], CheckStats]:
    """Turns the model's entries into cuts, checking each one.

    - A number must be a whole number above the previous cut. Anything else is dropped.
    - A number at or past the last word means "the end of the script", however it was
      numbered. Entries after it are dropped.
    - The quoted words must match the script's words right before and after the cut. If
      they do not, the cut moves to the nearest word, within a few words, where they do.
      If there is none, the cut stays at the model's number and carries a note.

    The cuts always end with the last word of the script.
    """
    count = len(words)
    script = [normalise(word.text) for word in words]
    last_index = count - 1

    cuts: list[Cut] = []
    previous = -1
    exact = moved = flagged = dropped = 0
    ended = False

    for entry in entries:
        if ended:
            dropped += 1
            continue
        k = _as_int(entry.get("last_word")) if isinstance(entry, dict) else None
        if k is None or k < 0 or k <= previous:
            dropped += 1
            continue
        before = _quoted_words(entry.get("words_before_cut"))
        after = _quoted_words(entry.get("words_after_cut"))

        if k >= last_index:
            # The end of the script. Only the words before it can be checked.
            if k > last_index or _fits(script, last_index, before, after)[0]:
                cuts.append(Cut(last_word=last_index, source="ai"))
                exact += 1
            else:
                cuts.append(
                    Cut(
                        last_word=last_index,
                        source="ai",
                        note="the quoted words do not match the end of the script",
                    )
                )
                flagged += 1
            ended = True
            continue

        if all(_fits(script, k, before, after)):
            cuts.append(Cut(last_word=k, source="ai"))
            exact += 1
        else:
            nearby = _nearby_match(script, k, before, after, previous + 1, last_index - 1)
            if nearby is not None:
                k = nearby
                cuts.append(Cut(last_word=k, source="ai"))
                moved += 1
            else:
                cuts.append(
                    Cut(
                        last_word=k,
                        source="ai",
                        note=f"the quoted words do not match the script near word {k}",
                    )
                )
                flagged += 1
        previous = k

    if not ended:
        cuts.append(Cut(last_word=last_index, source="ai"))

    stats = CheckStats(
        entries=len(entries), exact=exact, moved=moved, flagged=flagged, dropped=dropped
    )
    return cuts, stats
