"""The prompt sent to the video model (ANALYSIS.md Section 5.4). Pure functions, no I/O.

For an LTX model it is one paragraph:

    Style: <style_prefix>. <description> <prompt_suffix>

For MiniMax H3 it is the structured prompt the model was trained on (the GPU server's guide and
MiniMax's own "Video Prompt Writing Guide"): the line that places the frames, then three fields.

    For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is
    fully referenced.

    integrated_multimodal_description: [Shot 1] <style_prefix>, <description> <prompt_suffix>

    overall_soundscape: <ambience and physical sounds>

    non_diegetic_music: <score, or N/A>

The scene's description is stored as one text. A description drafted for MiniMax H3 holds the
three fields (`is_h3_format`); one drafted for LTX is prose. `prompt_for` turns either into the
prompt of the model that makes the clip, and says so when it had to convert, because a
description written for one model reads worse to the other (the author is told to draft again).

The page shows this for every scene (the prompt preview), and Phase 9 sends the same text,
so there is exactly one place that builds it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from app.providers.video_generator import h3_prompt_prefix
from app.services.lab_prompt_writer import H3_DESCRIPTION, H3_MUSIC, H3_NO_MUSIC, H3_SOUNDSCAPE
from app.services.video_models import H3_MODEL, VideoModel

# The soundscape of a description that was written for LTX and has none of its own: plain
# ambience, with no speech (the voiceover is the sound of a narrated video).
DEFAULT_SOUNDSCAPE: Final = "Natural ambient sound that fits the scene, with no speech."

NOTE_LTX_TO_H3: Final = (
    "This scene's description was written for LTX, so it is wrapped in MiniMax H3's format "
    "(one shot, a plain soundscape and no music). Draft the descriptions again for a "
    "description written for MiniMax H3."
)
NOTE_H3_TO_LTX: Final = (
    "This scene's description was written for MiniMax H3, so its shot label and picture tags "
    "are removed and its soundscape is added as a sentence for this model. Draft the "
    "descriptions again for a description written for LTX."
)

_H3_HEADING: Final = re.compile(
    rf"({H3_DESCRIPTION}|{H3_SOUNDSCAPE}|{H3_MUSIC})[ \t]*:[ \t]*", re.IGNORECASE
)
# The line that places the frames. A description that has it (an author pasted a full prompt)
# keeps working: the line is dropped and written again, with this clip's own length.
_H3_FRAME_LINE_START: Final = re.compile(
    r"\s*(?:For the target video,|How the reference pictures align)", re.IGNORECASE
)
_H3_FIRST_SHOT: Final = re.compile(r"\s*\[Shot\s+1\]\s*", re.IGNORECASE)
_SHOT_MARKER: Final = re.compile(r"\[Shot\s+\d+\]\s*", re.IGNORECASE)
# A clip with a first frame names it "<Picture 1>", one with two frames "Picture 1" and
# "Picture 2" (the guide's I2VA and FL2VA cases), so the angle brackets are optional.
_FIRST_PICTURE: Final = re.compile(r"<?\bPicture 1\b>?", re.IGNORECASE)
_LAST_PICTURE: Final = re.compile(r"<?\bPicture 2\b>?", re.IGNORECASE)


@dataclass(frozen=True)
class ScenePrompt:
    """The prompt to send and, when the description had to be converted for the model, why."""

    text: str
    note: str | None = None


def _collapse(text: str | None) -> str:
    """Trims the text and turns every run of whitespace, line breaks included, into one space."""
    return " ".join((text or "").split())


def assemble_prompt(
    style_prefix: str | None, description: str | None, prompt_suffix: str | None
) -> str | None:
    """`Style: <style_prefix>.` + the description + the suffix, joined by single spaces. This is
    the LTX prompt.

    None while the description is blank: there is nothing to send yet. A blank style prefix
    leaves the style part out. A full stop is not doubled when the prefix already ends with
    one, and one is added after the description (when it has no `.`, `!` or `?`) only if a
    suffix follows it.
    """
    body = _collapse(description)
    if not body:
        return None

    parts: list[str] = []
    style = _collapse(style_prefix)
    if style:
        parts.append(f"Style: {style}" if style.endswith(".") else f"Style: {style}.")

    suffix = _collapse(prompt_suffix)
    if suffix and body[-1] not in ".!?":
        body += "."
    parts.append(body)
    if suffix:
        parts.append(suffix)
    return " ".join(parts)


# --- MiniMax H3 -----------------------------------------------------------------------------


def parse_h3_fields(description: str | None) -> dict[str, str] | None:
    """The fields of a description written in MiniMax H3's format, each on one line, keyed by
    field name. None when the text is not in that format: it must start with
    `integrated_multimodal_description:`, apart from a leading line that places the frames.

    A field that is missing from the text is missing from the result. The description field can
    be blank: the caller decides what that means.
    """
    text = description or ""
    headings = list(_H3_HEADING.finditer(text))
    if not headings or headings[0].group(1).lower() != H3_DESCRIPTION:
        return None
    preamble = text[: headings[0].start()]
    if preamble.strip() and not _H3_FRAME_LINE_START.match(preamble):
        return None

    fields: dict[str, str] = {}
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        fields.setdefault(heading.group(1).lower(), _collapse(text[heading.end() : end]))
    return fields


def is_h3_format(description: str | None) -> bool:
    """True when the description is written in MiniMax H3's format (`parse_h3_fields`)."""
    return parse_h3_fields(description) is not None


def _style_for_first_shot(style_prefix: str | None) -> str:
    """The project's style as a phrase for the start of `[Shot 1]`: no trailing full stop."""
    return _collapse(style_prefix).rstrip(".,;: ")


def _put_style_in_first_shot(description: str, style: str) -> str:
    """The description field with `[Shot 1]` in front, and the style right after it, where the
    guide says the style belongs ("[Shot 1] Live-action, cinematic, a medium-wide shot...").
    """
    opening = _H3_FIRST_SHOT.match(description)
    rest = description[opening.end() :] if opening else description
    return f"[Shot 1] {style}, {rest}" if style else f"[Shot 1] {rest}"


def _assemble_h3(
    fields: dict[str, str],
    style_prefix: str | None,
    prompt_suffix: str | None,
    num_frames: int,
    has_last: bool,
) -> str:
    """The three fields, the style in `[Shot 1]`, the suffix at the end of the description and,
    in front, the line that places the first frame (and the last, when there is one) on the
    clip's timeline. `fields` has a description.
    """
    description = _put_style_in_first_shot(
        fields[H3_DESCRIPTION], _style_for_first_shot(style_prefix)
    )
    suffix = _collapse(prompt_suffix)
    if suffix:
        if description[-1] not in ".!?":
            description += "."
        description = f"{description} {suffix}"
    soundscape = fields.get(H3_SOUNDSCAPE) or DEFAULT_SOUNDSCAPE
    music = fields.get(H3_MUSIC) or H3_NO_MUSIC
    body = (
        f"{H3_DESCRIPTION}: {description}\n\n{H3_SOUNDSCAPE}: {soundscape}\n\n{H3_MUSIC}: {music}"
    )
    # A scene always has a first frame (it is what a scene needs before a clip can be made).
    frame_line = h3_prompt_prefix(num_frames, True, has_last, body)
    return f"{frame_line}\n\n{body}" if frame_line else body


def _prose_from_h3_fields(fields: dict[str, str]) -> str:
    """A description in MiniMax H3's format as the one paragraph LTX reads: the shot label is
    dropped, the picture tags say "the first frame" and "the last frame", and the soundscape
    follows as sentences (unless it is `N/A`).
    """
    prose = _SHOT_MARKER.sub("", fields[H3_DESCRIPTION])
    prose = _FIRST_PICTURE.sub("the first frame", prose)
    prose = _LAST_PICTURE.sub("the last frame", prose)
    prose = _collapse(prose)
    prose = prose[:1].upper() + prose[1:]  # the label was in front of a lower-case "a wide shot"
    soundscape = fields.get(H3_SOUNDSCAPE, "")
    if soundscape and soundscape.upper() != H3_NO_MUSIC:
        if prose and prose[-1] not in ".!?":
            prose += "."
        prose = f"{prose} {soundscape}"
    return prose


def prompt_for(
    model: VideoModel,
    *,
    style_prefix: str | None,
    description: str | None,
    prompt_suffix: str | None,
    num_frames: int,
    has_last: bool,
) -> ScenePrompt | None:
    """The prompt `model` is sent for this scene, or None while the description is blank.

    `num_frames` and `has_last` only matter for MiniMax H3: the frame count sets the length in
    the line that places the frames, and `has_last` says whether the scene has a last frame.
    A description in the other model's format is converted, and the result's `note` says so.
    """
    fields = parse_h3_fields(description)
    if fields is not None and not fields[H3_DESCRIPTION]:
        return None  # a heading with no text under it: nothing to send yet
    if not _collapse(description):
        return None

    if model == H3_MODEL:
        note = None
        if fields is None:
            fields = {H3_DESCRIPTION: _collapse(description)}
            note = NOTE_LTX_TO_H3
        return ScenePrompt(
            _assemble_h3(fields, style_prefix, prompt_suffix, num_frames, has_last), note
        )

    if fields is None:
        text = assemble_prompt(style_prefix, description, prompt_suffix)
        return ScenePrompt(text) if text is not None else None
    text = assemble_prompt(style_prefix, _prose_from_h3_fields(fields), prompt_suffix)
    return ScenePrompt(text, NOTE_H3_TO_LTX) if text is not None else None
