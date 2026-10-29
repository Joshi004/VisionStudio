"""The deterministic H3 router (PHASE-025, `Path_ahead.md` Section 29).

Pure functions: no database, no files, no clock, no model. The caller
(`services/generation_requests.py`) gathers what one shot needs and `plan` turns it into the exact
request the video model will be asked for, or refuses with a sentence for the user.

The rules:

- **Pictures** are the shot's reference manifest, in its order (`<Picture n>`).
- **Audios** are the audio of each dialogue line the shot carries, in plan order (`<Audio n>`),
  each used as a `partially_copy` reference. Narration is never sent (D-10). A speaker who is not
  visible in the shot (Q-4) is still sent, and flagged `speaker_visible: false` so the prompt can
  say the voice comes from somebody unseen (PHASE-026). A short line is used as is, with the time
  it starts inside the shot (Q-5, PHASE-001 V2).
- **Route:** pictures go to the reference endpoint (`H3_AUDIO_TO_VIDEO_PATH`), with the audios
  when there are any. A shot with neither pictures nor dialogue goes to the plain generate
  endpoint (text). A shot with dialogue and no pictures is refused: the generate endpoint takes no
  audio.
- **Continuity shots (PHASE-032, Q-7):** a shot that continues the one before it and has no
  dialogue takes the `first_frame` route: the generate endpoint, the last frame of the previous
  shot as its first frame and no other picture. One that has dialogue stays on the reference
  route with one more picture, a slot of kind `anchor` after the others. The request only
  records the slot (`anchor`); the frame is cut from the previous shot's take when the take is
  queued (`services/continuity_anchor.py`).
- **Frames:** the smallest `17n + 5` at or above the shot's length on the timeline
  (`duration_policy.shot_num_frames`, D-9), within the hard bounds. A shot planned since D-9
  changed already lasts a `17n + 5` length (`services/h3_lengths`), so it asks for exactly its
  length; an older plan asks for a little more, and the render trims the clip to the exact length.
- **Size:** MiniMax H3's own size for the project's orientation (`H3_SIZES`).
- **Rapid exchange (PHASE-043):** a shot the plan marks as an exchange has two or three lines
  from exactly two speakers who take turns, each visible with a character picture, on the
  reference route and with no continuity anchor. The request then records one internal cut per
  line (`exchange.cuts`): the first at 0, each later one at the start of its line. The prompt
  compiler writes one `[Shot n]` for each cut.

- **Explainer (EXPLAINER-005):** with `explainer` set, each dialogue audio is `fully_copy`: the
  presenter's line is the clip's whole soundtrack, and the job sends it placed at its start
  inside silence as long as the clip (`speech_audio.place_in_silence`). A B-roll shot has an
  empty manifest, so it takes the text route on its own.
- **Presenter shot of a continuous explainer (FLOW-007):** the shot has no dialogue lines of its
  own. Its one audio is the **window of the scene's voice take** that the clip covers: from the
  shot's start, for the clip's length (`num_frames / 24`), `fully_copy`, starting at 0. The
  request records the window (`audios[].window`: its start in the take, its length, the shot's
  length and the shot's own words) and the job cuts it when it uploads, padding with silence past
  the end of the take. The clip is longer than the shot, and the render trims it (F-6).

Nothing here chooses a seed or a partition: those are decided when the request is sent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Literal

from app.providers import video_generator
from app.services import video_models
from app.services.duration_policy import DurationPolicy, DurationPolicyError, shot_num_frames
from app.services.frame_counts import H3_FPS
from app.services.shot_planning_writer import EXCHANGE_MAX_LINES, EXCHANGE_MIN_LINES

Route = Literal["reference", "text", "first_frame"]

ROUTE_REFERENCE: Final = "reference"
ROUTE_TEXT: Final = "text"
# A continuity shot with no dialogue (PHASE-032, Q-7): the generate endpoint, with the last
# frame of the previous shot as the clip's first frame, and no other picture.
ROUTE_FIRST_FRAME: Final = "first_frame"
# How a continuity shot uses the frame its predecessor ends on.
ANCHOR_FIRST_FRAME: Final = "first_frame"
ANCHOR_REFERENCE: Final = "reference"
# The `kind` of the picture slot that stands for the anchor on the reference route. Its
# `lab_image_id` is None: the frame does not exist until the previous shot has a take.
ANCHOR_PICTURE_KIND: Final = "anchor"
# The `kind` of a manifest picture that shows a character (the other kind is `environment`).
CHARACTER_PICTURE_KIND: Final = "character"
# How every dialogue audio is used: the model copies its spoken layer, and the rest of the clip
# is made by the model.
AUDIO_MARKER: Final = "partially_copy"
# EXPLAINER-005: in an explainer the presenter's line is copied whole and is the clip's entire
# soundtrack, so H3's own sound is gone from those clips.
AUDIO_MARKER_EXPLAINER: Final = "fully_copy"
# What the GPU server's guide documents as the longest audio reference.
H3_MAX_AUDIO_SECONDS: Final = 15.0
# Rounding noise allowed when an audio is compared with the length of its shot.
_TOLERANCE: Final = 0.001


class GenerationPlanError(ValueError):
    """A shot that cannot be given a generation request. The message is meant to be shown."""


@dataclass(frozen=True)
class DialogueInput:
    """One dialogue line of the shot and its stored audio."""

    unit_id: str
    speaker_id: str
    text: str
    # The `speech_unit_audio` row: its id and the key that identifies the recording.
    audio_id: int
    audio_key: str
    # The measured length of the recording.
    duration_s: float | None
    # Where the line starts inside the shot, from the timeline.
    start_in_shot_s: float


@dataclass(frozen=True)
class TakeWindowInput:
    """The part of a scene's voice take that a presenter clip of a continuous explainer covers
    (FLOW-007).
    """

    scene_id: str
    # The `speech_unit_audio` row of the take, and the key that identifies the recording.
    audio_id: int
    audio_key: str
    speaker_id: str
    # Where the window starts inside the take, in seconds. Negative when the scene's lead-in
    # comes before the take.
    start_s: float
    # The words the take says inside the whole window, which the prompt quotes.
    text: str
    # The words inside the shot's own part of the window (from 0 to the shot's length): the
    # words the take check looks for, because the clip's trimmed tail is never shown.
    shown_text: str
    # The speech units whose words are in the shot.
    unit_ids: list[str]


@dataclass(frozen=True)
class GenerationPlan:
    shot_id: str
    scene_id: str
    model: str
    route: Route
    endpoint: str
    orientation: str
    width: int
    height: int
    fps: int
    target_seconds: float
    num_frames: int
    clip_seconds: float
    match_audio_duration: bool
    pictures: list[dict[str, Any]]
    audios: list[dict[str, Any]]
    notes: list[str] = field(default_factory=list)
    # PHASE-032: set for a continuity shot, `{from_shot_id, use, picture_order}` where `use` is
    # `first_frame` or `reference` and `picture_order` is the anchor's `<Picture n>` (reference
    # use only). None for every other shot.
    anchor: dict[str, Any] | None = None
    # PHASE-043: set for a rapid exchange, `{cuts: [{shot, audio, speaker_id, at_s}]}`, one cut
    # for each line, in order. None for every other shot.
    exchange: dict[str, Any] | None = None
    # EXPLAINER-005: set for the shot of an explainer project. Stored only when true, so the
    # requests of other projects keep their content.
    explainer: bool = False

    def as_dict(self) -> dict[str, Any]:
        """The `content` of a stored generation request."""
        content = {
            "shot_id": self.shot_id,
            "scene_id": self.scene_id,
            "model": self.model,
            "route": self.route,
            "endpoint": self.endpoint,
            "orientation": self.orientation,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "target_seconds": self.target_seconds,
            "num_frames": self.num_frames,
            "clip_seconds": self.clip_seconds,
            "match_audio_duration": self.match_audio_duration,
            "pictures": self.pictures,
            "audios": self.audios,
            "notes": self.notes,
            "anchor": self.anchor,
            "exchange": self.exchange,
        }
        if self.explainer:
            content["explainer"] = True
        return content


def _picture(entry: dict[str, Any], number: int) -> dict[str, Any]:
    """One manifest picture as the request names it. `label` is what a prompt calls it."""
    return {
        "label": f"Picture {number}",
        "order": number,
        "lab_image_id": entry["lab_image_id"],
        "kind": entry["kind"],
        "subject_id": entry["subject_id"],
        "subject_name": entry["subject_name"],
        "view": entry["view"],
        "variant": entry["variant"],
    }


def _check_audio(line: DialogueInput, target_s: float) -> float:
    """The length of one line's recording, after checking it fits the video model and the shot.
    Raises GenerationPlanError.
    """
    seconds = line.duration_s
    # Written so that None and NaN, which compare false to everything, are refused too.
    if seconds is None or not seconds > 0:
        raise GenerationPlanError(f"The speech of the line '{line.unit_id}' has no length.")
    if seconds > H3_MAX_AUDIO_SECONDS:
        raise GenerationPlanError(
            f"The speech of the line '{line.unit_id}' lasts {seconds:g} s, longer than the "
            f"{H3_MAX_AUDIO_SECONDS:g} s the video model takes as a reference."
        )
    if line.start_in_shot_s + seconds > target_s + _TOLERANCE:
        raise GenerationPlanError(
            f"The line '{line.unit_id}' would end at {line.start_in_shot_s + seconds:.2f} s, "
            f"after its shot ends at {target_s:g} s. Plan the shots of this scene again."
        )
    return seconds


def _window_audio(
    window: TakeWindowInput, num_frames: int, target_s: float, visible: set[str]
) -> dict[str, Any]:
    """The one audio of a presenter shot of a continuous explainer (FLOW-007): the window of the
    scene's take the clip covers. It is `fully_copy` and starts at 0 of the clip, and lasts as
    long as the clip, whatever the shot's own length is (the render trims the clip to the shot).
    Raises GenerationPlanError.
    """
    window_s = num_frames / H3_FPS
    if window_s > H3_MAX_AUDIO_SECONDS + _TOLERANCE:
        raise GenerationPlanError(
            f"The window of the voice take for this shot lasts {window_s:g} s, longer than the "
            f"{H3_MAX_AUDIO_SECONDS:g} s the video model takes as a reference. Plan the shots of "
            "this scene again."
        )
    if window.speaker_id not in visible:
        raise GenerationPlanError(
            "A presenter shot must show the presenter. Choose the shot's references again."
        )
    if not window.text.strip() or not window.shown_text.strip():
        raise GenerationPlanError(
            "The presenter says no words in this shot. Plan the shots of this scene again."
        )
    return {
        "label": "Audio 1",
        "order": 1,
        "unit_id": f"take:{window.scene_id}",
        "unit_ids": window.unit_ids,
        "speaker_id": window.speaker_id,
        "text": window.text,
        "speaker_visible": True,
        "speech_unit_audio_id": window.audio_id,
        "audio_key": window.audio_key,
        "duration_s": round(window_s, 3),
        "starts_in_shot_seconds": 0.0,
        "marker": AUDIO_MARKER_EXPLAINER,
        "window": {
            "start_s": round(window.start_s, 3),
            "seconds": round(window_s, 3),
            "shot_seconds": round(target_s, 3),
            "shown_text": window.shown_text,
        },
    }


def _exchange_cuts(
    route: Route,
    anchor: dict[str, Any] | None,
    pictures: list[dict[str, Any]],
    audios: list[dict[str, Any]],
) -> dict[str, Any]:
    """The internal cuts of a rapid exchange (PHASE-043), one for each line. Raises
    GenerationPlanError when the shot cannot be one.
    """
    if route != ROUTE_REFERENCE:
        raise GenerationPlanError(
            "A rapid exchange is made from reference pictures and the lines of its two speakers."
        )
    if anchor is not None:
        raise GenerationPlanError(
            "A rapid exchange cannot continue the shot before it. Plan the shots of this scene "
            "again."
        )
    if not EXCHANGE_MIN_LINES <= len(audios) <= EXCHANGE_MAX_LINES:
        raise GenerationPlanError(
            f"A rapid exchange has {EXCHANGE_MIN_LINES} to {EXCHANGE_MAX_LINES} lines of "
            f"dialogue; this shot has {len(audios)}."
        )
    speakers = [audio["speaker_id"] for audio in audios]
    if len(set(speakers)) != 2 or any(a == b for a, b in zip(speakers, speakers[1:], strict=False)):
        raise GenerationPlanError(
            "A rapid exchange needs exactly two speakers who take turns. Plan the shots of this "
            "scene again."
        )
    shown = {
        picture["subject_id"] for picture in pictures if picture["kind"] == CHARACTER_PICTURE_KIND
    }
    for audio in audios:
        if not audio["speaker_visible"] or audio["speaker_id"] not in shown:
            raise GenerationPlanError(
                f"The speaker of the line '{audio['unit_id']}' needs to be visible with a "
                "reference picture in a rapid exchange. Choose the shot's references again."
            )
    cuts: list[dict[str, Any]] = []
    for number, audio in enumerate(audios, start=1):
        at_s = 0.0 if number == 1 else audio["starts_in_shot_seconds"]
        if cuts and at_s <= cuts[-1]["at_s"]:
            raise GenerationPlanError(
                f"The line '{audio['unit_id']}' does not start after the line before it, so the "
                "exchange cannot be cut at each line."
            )
        cuts.append(
            {
                "shot": number,
                "audio": audio["order"],
                "speaker_id": audio["speaker_id"],
                "at_s": at_s,
            }
        )
    return {"cuts": cuts}


def plan(
    *,
    scene_id: str,
    shot_id: str,
    target_s: float,
    policy: DurationPolicy,
    orientation: str,
    pictures: list[dict[str, Any]],
    dialogue: list[DialogueInput],
    visible_character_ids: list[str],
    continues_from: str | None = None,
    exchange: bool = False,
    explainer: bool = False,
    take_window: TakeWindowInput | None = None,
    clip_frames: int | None = None,
) -> GenerationPlan:
    """The generation request of one shot. `pictures` are the manifest's `references` (each has
    `order`, `lab_image_id`, `kind`, `subject_id`, `subject_name`, `view` and `variant`) and
    `dialogue` the lines the shot carries, both in the order they are sent. `continues_from` is
    the id of the shot before it when this is a continuity shot (PHASE-032); `exchange` is true
    when the shot plan marks the shot as a rapid exchange (PHASE-043); `explainer` is true for a
    shot of an explainer project, whose dialogue audio is `fully_copy` (EXPLAINER-005).
    `take_window` is set for a presenter shot of a continuous explainer (FLOW-007): the shot's one
    audio is then that window of the scene's take and `dialogue` is empty. `clip_frames` is the
    clip length the timeline of a cut-based shot already worked out (FLOW-006): it is used as it is
    instead of being worked out again from the shot's length, which could differ by one step
    because a cut time is kept to a thousandth of a second. Raises GenerationPlanError.
    """
    if take_window is not None and (dialogue or exchange or not explainer):
        raise GenerationPlanError("A window of the voice take is only for a presenter shot.")
    sizes = video_generator.H3_SIZES.get(orientation)
    if sizes is None:
        raise GenerationPlanError(f"The project's orientation '{orientation}' has no H3 size.")
    width, height = sizes
    try:
        video_generator.check_size(width, height)
        num_frames = clip_frames if clip_frames is not None else shot_num_frames(target_s, policy)
    except DurationPolicyError as exc:
        raise GenerationPlanError(f"{exc} Plan the shots of this scene again.") from exc
    except ValueError as exc:
        raise GenerationPlanError(str(exc)) from exc

    max_pictures = video_generator.H3_MAX_REFERENCE_IMAGES
    if len(pictures) > max_pictures:
        raise GenerationPlanError(
            f"The shot has {len(pictures)} reference pictures; the video model takes at most "
            f"{max_pictures}."
        )
    max_audios = video_generator.H3_MAX_REFERENCE_AUDIOS
    if len(dialogue) > max_audios:
        raise GenerationPlanError(
            f"The shot carries {len(dialogue)} lines of dialogue; the video model takes at most "
            f"{max_audios} audios. Plan the shots of this scene again."
        )

    planned_pictures = [_picture(entry, number) for number, entry in enumerate(pictures, start=1)]
    notes: list[str] = []
    anchor: dict[str, Any] | None = None
    has_audio = bool(dialogue) or take_window is not None
    if continues_from is not None and not has_audio:
        # Q-7: a shot with no dialogue audio is made on the generate endpoint, which takes the
        # first frame and no other picture.
        route: Route = ROUTE_FIRST_FRAME
        endpoint = video_generator.H3_GENERATE_PATH
        planned_pictures = []
        anchor = {
            "from_shot_id": continues_from,
            "use": ANCHOR_FIRST_FRAME,
            "picture_order": None,
        }
        notes.append(
            f"This shot continues '{continues_from}': the clip starts on that shot's last frame "
            "and is sent with no other reference picture."
        )
    elif not pictures:
        if has_audio:
            raise GenerationPlanError(
                "The shot has dialogue but no reference pictures, and a text-only clip takes no "
                "audio. Choose the shot's references first."
            )
        route = ROUTE_TEXT
        endpoint = video_generator.H3_GENERATE_PATH
    else:
        route = ROUTE_REFERENCE
        endpoint = video_generator.H3_AUDIO_TO_VIDEO_PATH
        if continues_from is not None:
            # Q-7: a dialogue shot needs the reference endpoint, where the anchor is one more
            # reference picture, sent after the others.
            order = len(planned_pictures) + 1
            if order > max_pictures:
                raise GenerationPlanError(
                    f"The shot has {len(pictures)} reference pictures and needs one more for "
                    f"the last frame of '{continues_from}'; the video model takes at most "
                    f"{max_pictures}."
                )
            planned_pictures.append(
                {
                    "label": f"Picture {order}",
                    "order": order,
                    "lab_image_id": None,
                    "kind": ANCHOR_PICTURE_KIND,
                    "subject_id": continues_from,
                    "subject_name": f"Last frame of {continues_from}",
                    "view": "last_frame",
                    "variant": "",
                }
            )
            anchor = {
                "from_shot_id": continues_from,
                "use": ANCHOR_REFERENCE,
                "picture_order": order,
            }
            notes.append(
                f"This shot continues '{continues_from}': the last frame of that shot is sent as "
                f"Picture {order}."
            )

    visible = set(visible_character_ids)
    audios: list[dict[str, Any]] = []
    for number, line in enumerate(dialogue, start=1):
        seconds = _check_audio(line, target_s)
        speaker_visible = line.speaker_id in visible
        if not speaker_visible:
            notes.append(
                f"The speaker of the line '{line.unit_id}' is not seen in this shot: the voice "
                "comes from an unseen speaker."
            )
        audios.append(
            {
                "label": f"Audio {number}",
                "order": number,
                "unit_id": line.unit_id,
                "speaker_id": line.speaker_id,
                "text": line.text,
                "speaker_visible": speaker_visible,
                "speech_unit_audio_id": line.audio_id,
                "audio_key": line.audio_key,
                "duration_s": round(seconds, 3),
                "starts_in_shot_seconds": round(max(0.0, line.start_in_shot_s), 3),
                "marker": AUDIO_MARKER_EXPLAINER if explainer else AUDIO_MARKER,
            }
        )

    if take_window is not None:
        audios.append(_window_audio(take_window, num_frames, target_s, set(visible_character_ids)))

    exchange_content = _exchange_cuts(route, anchor, planned_pictures, audios) if exchange else None
    if exchange_content is not None:
        notes.append(
            f"A rapid exchange: the clip cuts at each of its {len(audios)} lines, one internal "
            "shot for each."
        )

    return GenerationPlan(
        shot_id=shot_id,
        scene_id=scene_id,
        model=video_models.H3_MODEL,
        route=route,
        endpoint=endpoint,
        orientation=orientation,
        width=width,
        height=height,
        fps=H3_FPS,
        target_seconds=round(target_s, 3),
        num_frames=num_frames,
        clip_seconds=round(num_frames / H3_FPS, 3),
        # The clip is as long as the shot asks, never as long as the audio: the shot's length is
        # never shorter than its speech (PHASE-021).
        match_audio_duration=False,
        pictures=planned_pictures,
        audios=audios,
        notes=notes,
        anchor=anchor,
        exchange=exchange_content,
        explainer=explainer,
    )
