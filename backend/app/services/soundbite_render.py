"""What the render needs to draw a sound bite (SB-009, `Sound_bite_implementation_phases.md` §4.7).
Pure: no I/O, no clock.

A sound bite clip is the owner's accepted cut of a downloaded video window, made at the output
size with a lower third and a source credit laid over its picture, and with its own sound. This
module holds the rules that do not need a file or a database:

- the **framing** of the picture: a source that has the frame's shape and is sharp enough fills the
  frame, any other source is fitted inside the frame over a blurred, darkened copy of itself (never
  black bars), and `compose_graph` is the ffmpeg graph that makes either;
- the **lower third** (the speaker, then the role at the time, the venue and the month of the
  recording), when it shows, and the `resolved` brief the motion service draws it from;
- the **speaker colours** of the captions, one for each real speaker of the story, in the order the
  speakers first appear;
- the **words** the clip's captions show, timed from the start of the cut;
- the **link** with the second of the video the cut starts at, for the description's Sources.

Nothing here is trusted text from the video: names and venues come from the owner's review, and
every number that reaches an ffmpeg filter is formatted here from a number.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

# --- The captions' speaker colours -----------------------------------------------------------

# Distinct from the narrator's white captions and from each other. A speaker takes the next colour
# of the list in the order the story's sound bites first show them; a longer story starts again.
SPEAKER_PALETTE: Final = ("#5CE1E6", "#7CFC9A", "#FFB347", "#FF8AD8")

# --- The lower third and the credit (§4.7) ---------------------------------------------------

# The lower third shows from 0.4 s after the clip starts, for 5 s at most, and is gone 0.3 s before
# the last words begin. A clip that leaves it less than 1.5 s has none.
LOWER_THIRD_IN_S: Final = 0.4
LOWER_THIRD_HOLD_S: Final = 5.0
LOWER_THIRD_BEFORE_LAST_WORD_S: Final = 0.3
LOWER_THIRD_MIN_S: Final = 1.5
LOWER_THIRD_FADE_S: Final = 0.25
# Sizes as shares of the frame's shorter side.
LOWER_THIRD_HEIGHT_RATIO: Final = 0.14
CREDIT_HEIGHT_RATIO: Final = 0.05
GAP_RATIO: Final = 0.02
# Landscape: the lower third is this share of the safe area's width at most; portrait: all of it.
LANDSCAPE_LOWER_THIRD_SHARE: Final = 0.6
CREDIT_SHARE: Final = 0.45
CREDIT_MAX_CHARS: Final = 60

# --- The picture ------------------------------------------------------------------------------

# A source this tall or shorter is shown framed, not blown up to the whole frame.
LOW_RES_HEIGHT_PX: Final = 480
# ... at this share of the frame, over the blurred copy.
LOW_RES_SHARE: Final = 0.8
# A source whose shape differs from the frame's by less than this share fills it.
ASPECT_TOLERANCE: Final = 0.02
BLUR_SIGMA: Final = 40
BACKGROUND_BRIGHTNESS: Final = -0.15

FULL: Final = "full"
FITTED: Final = "fitted"

_MONTHS: Final = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_DATE: Final = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_VIDEO_ID: Final = re.compile(r"[A-Za-z0-9_-]{11}")


# --- Speakers --------------------------------------------------------------------------------


def speaker_key(name: str) -> str:
    """A speaker's name as the story compares it: one line, lower case, single spaces."""
    return " ".join(name.casefold().split())


def assign_colours(speakers: Sequence[str]) -> dict[str, str]:
    """The caption colour of each speaker, by `speaker_key`, in the order they first appear in
    `speakers` (the story's sound bites in story order). The same person keeps one colour."""
    colours: dict[str, str] = {}
    for name in speakers:
        key = speaker_key(name)
        if key and key not in colours:
            colours[key] = SPEAKER_PALETTE[len(colours) % len(SPEAKER_PALETTE)]
    return colours


# --- The lower third -------------------------------------------------------------------------


def month_year(recorded: str) -> str:
    """`2024-03-01` as `March 2024`. Anything that is not an ISO date gives the empty text."""
    found = _DATE.fullmatch(recorded.strip())
    if found is None:
        return ""
    month = int(found.group(2))
    if not 1 <= month <= 12:
        return ""
    return f"{_MONTHS[month - 1]} {int(found.group(1))}"


def lower_third_lines(details: dict[str, Any]) -> tuple[str, str]:
    """The two lines of the lower third from the owner's details of a clip: the speaker, and
    `role · venue, Month Year`."""
    name = " ".join(str(details.get("speaker", "")).split())
    place = " · ".join(
        part
        for part in (
            " ".join(str(details.get("role", "")).split()),
            " ".join(str(details.get("venue", "")).split()),
        )
        if part
    )
    when = month_year(str(details.get("recorded", "")))
    second = f"{place}, {when}" if place and when else place or when
    return name, second


def credit_text(channel: object) -> str | None:
    """The source credit, `Video: <channel>`, or None when the channel is not known."""
    if not isinstance(channel, str):
        return None
    clean = " ".join("".join(c for c in channel if c.isprintable()).split())[:CREDIT_MAX_CHARS]
    return f"Video: {clean.rstrip()}" if clean else None


def lower_third_frames(last_word_start_s: float, fps: int) -> tuple[int, int] | None:
    """The frames of the clip the lower third shows in, `(first, end)` with `end` not included, or
    None when the clip is too short for it. `last_word_start_s` is where the clip's last word
    begins, in seconds from the start of the cut."""
    start_s = LOWER_THIRD_IN_S
    end_s = min(
        LOWER_THIRD_IN_S + LOWER_THIRD_HOLD_S, last_word_start_s - LOWER_THIRD_BEFORE_LAST_WORD_S
    )
    if end_s - start_s < LOWER_THIRD_MIN_S:
        return None
    return round(start_s * fps), round(end_s * fps)


def _even(value: float) -> int:
    return max(2, int(value) // 2 * 2)


def overlay_resolved(
    *,
    width: int,
    height: int,
    fps: int,
    accent: str,
    fonts: dict[str, str],
    safe: dict[str, int],
    caption: dict[str, int],
    name: str,
    detail: str,
    credit: str | None,
    last_word_start_s: float,
) -> dict[str, Any]:
    """The `resolved` brief of the motion service's `soundbite_overlay`: a full-frame transparent
    clip with the lower third (above the caption zone, at the safe area's left) and the credit (the
    safe area's top right). `lower_third` is None when there is no name or the clip is too short for
    it. Boxes are `[x, y, width, height]` in output pixels."""
    unit = min(width, height)
    gap = round(GAP_RATIO * unit)
    safe_width = safe["right"] - safe["left"]
    shown = lower_third_frames(last_word_start_s, fps) if name else None
    lower_third: dict[str, Any] | None = None
    if shown is not None:
        box_h = round(LOWER_THIRD_HEIGHT_RATIO * unit)
        box_w = safe_width if height > width else round(safe_width * LANDSCAPE_LOWER_THIRD_SHARE)
        lower_third = {
            "box": [safe["left"], max(safe["top"], caption["top"] - gap - box_h), box_w, box_h],
            "name": name,
            "detail": detail,
            "start_frame": shown[0],
            "end_frame": shown[1],
            "fade_frames": round(LOWER_THIRD_FADE_S * fps),
        }
    credit_box: list[int] | None = None
    if credit is not None:
        box_h = round(CREDIT_HEIGHT_RATIO * unit)
        box_w = round(safe_width * CREDIT_SHARE)
        credit_box = [safe["right"] - box_w, safe["top"], box_w, box_h]
    return {
        "accent": accent,
        "fonts": dict(fonts),
        "safe_area": safe,
        "caption_zone": caption,
        "lower_third": lower_third,
        "credit": credit,
        "credit_box": credit_box,
    }


# --- The picture -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Framing:
    """How a source's picture is put on the output frame."""

    kind: str  # `full` or `fitted`
    # The size of the picture inside the frame when it is `fitted`: it is scaled to fit this box.
    box: tuple[int, int]


def framing_for(source: tuple[int, int], frame: tuple[int, int]) -> Framing:
    """`full` when the source has the frame's shape (within `ASPECT_TOLERANCE`) and is taller than
    `LOW_RES_HEIGHT_PX`; otherwise `fitted`. A portrait frame therefore always fits a 16:9 window
    on the blurred copy, and a source of 480 p or less is shown at `LOW_RES_SHARE` of the frame."""
    source_w, source_h = source
    width, height = frame
    if source_w < 2 or source_h < 2 or width < 2 or height < 2:
        raise ValueError("A picture needs a size.")
    same_shape = abs((source_w / source_h) / (width / height) - 1) <= ASPECT_TOLERANCE
    if same_shape and source_h > LOW_RES_HEIGHT_PX:
        return Framing(FULL, (width, height))
    share = LOW_RES_SHARE if source_h <= LOW_RES_HEIGHT_PX and same_shape else 1.0
    return Framing(FITTED, (_even(width * share), _even(height * share)))


def picture_chain(framing: Framing, width: int, height: int, fps: int) -> str:
    """The filters from the source's picture (`[0:v:0]`, brought to `fps` first) to `[pic]`, at
    exactly `width` x `height`."""
    cover = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={width}:{height}"
    )
    if framing.kind == FULL:
        return f"[0:v:0]fps={fps},{cover},setsar=1[pic]"
    box_w, box_h = framing.box
    return (
        f"[0:v:0]fps={fps},split=2[sa][sb];"
        f"[sa]{cover},gblur=sigma={BLUR_SIGMA},eq=brightness={BACKGROUND_BRIGHTNESS}[bg];"
        f"[sb]scale={box_w}:{box_h}:force_original_aspect_ratio=decrease:flags=lanczos[fg];"
        "[bg][fg]overlay=x=trunc((W-w)/4)*2:y=trunc((H-h)/4)*2,setsar=1[pic]"
    )


def seconds_of(frames: int, fps: int) -> float:
    return round(frames / fps, 6)


def compose_graph(
    framing: Framing,
    *,
    width: int,
    height: int,
    fps: int,
    frames: int,
    audio_s: float,
    channel_filters: Sequence[str],
    with_overlay: bool,
) -> str:
    """The `-filter_complex` of the clip: input 0 is the video window, seeked to the cut's start,
    and input 1 (when `with_overlay`) the transparent overlay. Outputs `[v]` of exactly `frames`
    frames at `fps`, and `[a]` of exactly `frames / fps` seconds of 48 kHz stereo sound: the cut's
    own `audio_s` seconds of the window's sound, untouched in level and speed, then silence. The
    sound is never made louder or quieter here: the render matches it to the narrator."""
    if frames < 1 or fps < 1 or audio_s <= 0:
        raise ValueError("A clip needs frames and sound.")
    total_s = seconds_of(frames, fps)
    audio_s = min(audio_s, total_s)
    steps = [picture_chain(framing, width, height, fps)]
    if with_overlay:
        steps.append(
            f"[pic][1:v:0]overlay=x=0:y=0:format=yuv444:eof_action=pass,format=yuv420p,"
            f"trim=end_frame={frames},setpts=PTS-STARTPTS[v]"
        )
    else:
        steps.append(f"[pic]format=yuv420p,trim=end_frame={frames},setpts=PTS-STARTPTS[v]")
    sound = [
        *channel_filters,
        "aresample=48000",
        "asetpts=PTS-STARTPTS",
        f"atrim=end={audio_s:.6f}",
        f"apad=whole_dur={total_s:.6f}",
        f"atrim=end={total_s:.6f}",
        "aformat=sample_fmts=s16:sample_rates=48000:channel_layouts=stereo",
    ]
    steps.append("[0:a:0]" + ",".join(sound) + "[a]")
    return ";".join(steps)


# --- The words and the link ------------------------------------------------------------------


def caption_words(
    heard: Sequence[tuple[str, float, float]],
    first_word: int,
    last_word: int,
    in_s: float,
    length_s: float,
) -> tuple[tuple[str, float, float], ...]:
    """The words of the cut, `(text, start_s, end_s)` from the start of the clip: the heard words
    `first_word` to `last_word` (both included, positions in `heard`), moved by `in_s` and kept
    inside `0` to `length_s`. A word that ends before the clip starts or starts after it ends is
    left out. Empty for a range that is not inside `heard`."""
    if first_word < 0 or last_word >= len(heard) or last_word < first_word:
        return ()
    words: list[tuple[str, float, float]] = []
    for text, start, end in heard[first_word : last_word + 1]:
        low = max(0.0, start - in_s)
        high = min(length_s, end - in_s)
        if high > low and text.strip():
            words.append((text, round(low, 3), round(high, 3)))
    return tuple(words)


def last_word_start(
    heard: Sequence[tuple[str, float, float]], last_word: int, in_s: float
) -> float:
    """Where the cut's last word begins, in seconds from the start of the clip."""
    if not 0 <= last_word < len(heard):
        return 0.0
    return max(0.0, heard[last_word][1] - in_s)


def start_second(window_start_s: object, in_s: object) -> int | None:
    """The second of the original video the cut starts at: the window's start plus the cut's start
    in the window, rounded down. None when either is not a usable number."""
    if isinstance(window_start_s, bool) or isinstance(in_s, bool):
        return None
    if not isinstance(window_start_s, int | float) or not isinstance(in_s, int | float):
        return None
    second = math.floor(float(window_start_s) + float(in_s))
    return second if second >= 0 else None


def watch_url(video_id: object, second: int | None) -> str | None:
    """`https://www.youtube.com/watch?v=<id>&t=<n>s`, built from the 11-character video id (never
    from an address the agent wrote), or None for an id that is not one. Without a `second` the
    link has no time."""
    if not isinstance(video_id, str) or _VIDEO_ID.fullmatch(video_id) is None:
        return None
    base = f"https://www.youtube.com/watch?v={video_id}"
    return base if second is None else f"{base}&t={second}s"
