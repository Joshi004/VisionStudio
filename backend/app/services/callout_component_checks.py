"""The browser checks of a callout component, as rules the code can read from the motion
service's answer (CMO-003, `Callouts_motion_implementation_phases.md` §4.5).

Pure functions, no I/O. `jobs/callout_graphic_common.py` sends the requests.

The motion service draws still frames of the component (`POST /checks` with the engine
`callout_component`) and reports, for each, the text on screen, the share of the canvas that is
opaque and the texts that are cut. `rule_errors` turns that into sentences, for the model and for
the card:

- **Only the given words.** No word on screen at any checked frame is a word that is not in a
  part's text (case and punctuation ignored), and at the last checked frame, just before the exit
  fade, every word of every part is on screen.
- **Transparent enough.** At that last frame at most `MAX_COVER` of the canvas is opaque: a panel
  is fine, a filled rectangle is not.
- **Nothing cut.** From the frame at which every part has entered, no text is clipped or reaches
  outside the canvas. A part that has not entered yet is at opacity 0 but still laid out, so
  earlier frames are not judged.
"""

from __future__ import annotations

from typing import Any, Final

from app.services.dialogue_check import normalize_words

# The most of the canvas that may be opaque at the last checked frame.
MAX_COVER: Final = 0.6
# A part is complete this long after its frame (§4.4.1: "about 0.4 s", plus a margin).
ENTERED_AFTER_S: Final = 0.5
# The most frames one browser check draws (`MAX_CHECK_FRAMES` of the motion service).
MAX_CHECK_FRAMES: Final = 16
# The most words of a sentence that are listed in a message.
_LISTED: Final = 6


def entered_frame(resolved: dict[str, Any]) -> int:
    """The first frame at which every part has fully entered, never after the last checked
    frame."""
    fps = int(resolved["fps"])
    last = int(resolved["exit_frame"]) - 1
    latest = max(int(part["frame"]) for part in resolved["parts"])
    return min(latest + round(ENTERED_AFTER_S * fps), last)


def check_frames(resolved: dict[str, Any]) -> list[int]:
    """The frames the browser check draws, in ascending order: the first frame, each part's frame
    plus half a second, and the last frame before the exit fade. Repeats are dropped and at most
    `MAX_CHECK_FRAMES` are kept (the first, the last and the earliest of the others).
    """
    fps = int(resolved["fps"])
    last = int(resolved["exit_frame"]) - 1
    middle: list[int] = []
    for part in resolved["parts"]:
        frame = max(0, min(int(part["frame"]) + round(ENTERED_AFTER_S * fps), last))
        if frame not in middle and frame not in (0, last):
            middle.append(frame)
    middle.sort()
    kept = [0, *middle[: MAX_CHECK_FRAMES - 2], last]
    return sorted(set(kept))


def motion_resolved(
    resolved: dict[str, Any], zone: dict[str, Any], backdrop: str | None = None
) -> dict[str, Any]:
    """The `resolved` of one motion request (`motion/src/callout/props.ts`) for a zone: only the
    keys the service reads. `backdrop` is for an H.264 preview.
    """
    body: dict[str, Any] = {
        "kind": resolved["kind"],
        "placement": zone["placement"],
        "frame_height": resolved["frame_height"],
        "exit_frame": resolved["exit_frame"],
        "parts": resolved["parts"],
        "theme": resolved["theme"],
        "fonts": resolved["fonts"],
        "look": resolved["look"],
    }
    if backdrop is not None:
        body["backdrop"] = backdrop
    return body


def _words(text: str) -> list[str]:
    return normalize_words(text)


def _listed(words: list[str]) -> str:
    shown = ", ".join(f'"{word}"' for word in words[:_LISTED])
    return shown + (", ..." if len(words) > _LISTED else "")


def rule_errors(
    resolved: dict[str, Any], zone: dict[str, Any], answer: dict[str, Any]
) -> list[str]:
    """The rules a drawn component breaks at this zone, as sentences fit for the model. `answer`
    is the motion service's answer of a check that drew every frame (`ok`). Empty when the
    component keeps them.
    """
    where = f"In the {zone['placement']} zone ({zone['width']} x {zone['height']} px)"
    last = int(resolved["exit_frame"]) - 1
    entered = entered_frame(resolved)
    errors: list[str] = []

    allowed: set[str] = set()
    for part in resolved["parts"]:
        allowed.update(_words(str(part["text"])))

    texts = sorted(answer.get("texts") or [], key=lambda entry: int(entry["frame"]))
    strangers: list[str] = []
    for entry in texts:
        for word in _words(str(entry["text"])):
            if word not in allowed and word not in strangers:
                strangers.append(word)
    if strangers:
        errors.append(
            f"{where} the component shows words that are not in the callout's texts: "
            f"{_listed(strangers)}. Show only the given texts."
        )

    final = next((entry for entry in reversed(texts) if int(entry["frame"]) == last), None)
    if final is None and texts:
        final = texts[-1]
    if final is not None:
        shown = set(_words(str(final["text"])))
        missing = [
            str(part["text"])
            for part in resolved["parts"]
            if not set(_words(part["text"])) <= shown
        ]
        if missing:
            listed = ", ".join(f'"{text}"' for text in missing[:_LISTED])
            errors.append(
                f"{where} these texts are not all on screen at frame {int(final['frame'])}, "
                f"just before the callout fades out: {listed}. Every part must be fully visible "
                "by then."
            )

    opaque = [entry for entry in answer.get("opaque") or [] if int(entry["frame"]) == last]
    if opaque and float(opaque[-1]["share"]) > MAX_COVER:
        errors.append(
            f"{where} {round(float(opaque[-1]['share']) * 100)} percent of the canvas is opaque "
            f"at frame {last}; the most allowed is {round(MAX_COVER * 100)} percent. The video "
            "under the callout must stay visible: draw panels and text only, not a filled canvas."
        )

    cut: list[str] = []
    for entry in answer.get("cut") or []:
        if int(entry["frame"]) < entered:
            continue
        for text in entry["texts"]:
            if text not in cut:
                cut.append(text)
    if cut:
        listed = ", ".join(f'"{text}"' for text in cut[:_LISTED])
        errors.append(
            f"{where} these texts are cut off or reach outside the canvas: {listed}. Size and "
            "break the text so that it fits inside the canvas from `width` and `height`."
        )
    return errors
