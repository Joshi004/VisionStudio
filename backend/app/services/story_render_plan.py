"""The plan of a story render (PHASE-028, `Path_ahead.md` Section 33). Pure: no I/O, no clock.

`build_plan` takes what the story workspace already knows (each scene's timeline from PHASE-021
and each shot's selected take from PHASE-027) and turns it into the **frozen timeline** the
`render_story` job reads (`job.input.timeline`). The job reads nothing else, so what happens to
the shots afterwards does not change a render that has been started, and a restart renders the
same thing again.

**Frames.** Shot boundaries are rounded to the frame grid once, at story level, and a shot's frame
count is the difference of its two boundaries (`frame_counts`). The counts add up to the boundary
of the last shot, so the video is as long as the sum of the shot targets to within half a frame.
A shot's length is stored on H3's own length (`h3_lengths`, D-9), so the clip normally has exactly
the frames its shot needs and nothing is cut. At another frame rate than H3's 24 a clip can be one
source frame short; the render repeats its last frame then. The plan checks the clip's frames.

**Audio** (the starting values below are untested by ear and are meant to be tuned):

- *Shot audio*: the sound of each selected clip, over the part its shot uses, is brought toward
  `SHOT_TARGET_LUFS` (`gain_toward`), so a cut does not jump. A clip is boosted by at most
  `MAX_BOOST_DB`.
- *Ducking* (the planning decision, a fixed reduction): wherever narration plays on the story's
  timeline, the shot audio is lowered by `DUCK_DB`, with ramps of `DUCK_RAMP_S` on both sides.
  Two narration spans less than `DUCK_MERGE_GAP_S` apart are one window, unless a line of
  dialogue falls between them, so the sound does not pump between sentences.
- *Narration layer*: only narration units, each at its place on the timeline. Dialogue is only in
  the shot audio, so it is never heard twice.

**Music** (timeline version 2, MUSIC-012). When the project has a current music placement
(`MusicSource`), the timeline also holds every placed sound with everything the mixer needs, in
the sound's own seconds (its time 0 is the first sample it plays):

- *Ducking*: the score and the ambience beds are lowered under narration and dialogue, by the
  depth of the cue's own mix note (`under_voice`: low or medium, two settings). Where a cue's mix
  lets the sound swell in the gaps between lines (`swell_in_gaps`), a gap of `MUSIC_GAP_RELEASE_S`
  releases the duck; otherwise only a gap of `MUSIC_GAP_HOLD_S` does, so the music holds steady.
- *Dips*: the score and the beds dip by `DIP_DB` around every placed hit, point sound and every
  sound the video model makes for a cue, so a swell never hides the thump the scene depends on.
- *Swells*: a placement's `mix_requests` (a bed swell that covers a join) raise the beds playing at
  that second by `SWELL_DB`.
- *The video model's sound under a bed* (MD-17): the shot audio is lowered by a setting wherever a
  bed plays, never during a line of dialogue. The setting is 0 (off) until the owner tunes it.

**Music in a continuous explainer** (EXM-005). The music sits under a talking voice, so for a
continuous explainer `_music_timeline` ignores a cue's `under_voice` and `swell_in_gaps`: every
score sound is lowered by `MixSettings.explainer_duck_db` and holds that level through every gap
shorter than `EXPLAINER_MUSIC_HOLD_GAP_S`, so it never rises between ordinary sentences. A cue's
posts (the gaps the music plan chose, `MusicSource.posts`) are the only place it comes up: a sound
gets a `rises` entry, the pause of each post (cut by the render's own speech spans, so never over a
word) raised by `MixSettings.explainer_post_rise_db`. A story's own keys and values do not change.
The values are recorded in `constants` of such a render.

**Captions** (timeline version 3, EXPLAINER-008). For an explainer, `captions` holds the style and
the caption groups made by `caption_plan.build_captions` from each speech's word timing (narration
and dialogue alike), on the story's timeline, and `burned` (CAP-001): whether the render draws
them on the picture. A track with no `burned` key is from before CAP-001 and was burned. It is
null for a story.

**Callouts** (timeline version 4, EXPLAINER-010). For an explainer with callouts on, `callouts`
holds the style and every callout that is turned on in the current callout plan, each with its
time, its zone and its laid-out text (`callout_render.resolve`), and the plan it came from. It is
null otherwise. While a section title shows, the captions are hidden.

**Motion callouts** (timeline version 6, CMO-005). With `callout_style` `motion`, an entry's
`motion` says which attempt of its graphic the render draws (a transparent clip laid over the
shots at the entry's box), and which other attempt it falls back to; an entry without it is drawn
as a box. The track records the callout look and the graphics look it was made with.

**Voice** (timeline version 5, FLOW-008). A continuous explainer speaks each scene as one take.
`voice` holds each scene's take at the scene's start plus the lead-in, cut into `pieces` around the
presenter shots the owner switched to their clip's own voice (`shots[].voice` is `clip`): the take
is silent for exactly such a shot's span, with a crossfade of `VOICE_FADE_S` at each edge. By
default (`take`) the sound inside a presenter clip is dropped, because it is a copy of the voice.
B-roll sound is ducked under the take as it is under narration. `narration` is empty and `voice`
is null for every other render.

**Graphic overlays** (OVL-005). A render of a project with graphic suggestions may have the
optional key `graphic_overlays`: each entry is a full-frame video laid at (0, 0) over every shot
it spans, on top of callouts and evidence cards. It changes no shot and no second of the story, so
the version stays 6. A callout that starts in one is left out, as under a graphic shot.

**Evidence beside a graphic** (OVL-007). Where an overlay and evidence share the screen, the
overlay entry has `split` true and the `(x, y)` of its panel (its video is drawn at the panel's
size), and the optional key `split_evidence` holds the evidence side: each entry is a full-frame
opaque video (the evidence drawn in its half, the other half empty) laid at (0, 0) under the
overlays. The version stays 6.

**Sound effects** (EXM-007). A project with `sound_effects` on and a selected take for its graphic
and evidence sounds (`SoundEffectSource`) may have the optional key `sound_effects`: the graphic
sound at the first frame of every graphic shot and graphic overlay, the evidence sound at the first
frame of every evidence shot and evidence card, each placed so that the sound's loudest moment
lands on that frame. Code places them, never a model. A sound that would play over a sound bite,
or that starts less than `SOUND_EFFECT_MIN_SPACING_S` after the one before, is left out (listed in
`skipped`). The render job mixes them as one more lane that nothing ducks. A timeline without the
key renders as before, so the version stays 6.

`master` holds the loudness the finished mix is brought to. Every constant used is recorded.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Final

from app.services import callout_render, caption_plan, font_metrics, frame_counts, render_commands
from app.services.take_map import NO_REPLACED, TakeMap, TakeMapError

# The shape of `job.input.timeline`. The job refuses a timeline it does not know. Version 2 adds
# the music layers, the dip of the shot audio under a bed and the master loudness (MUSIC-012).
# Version 3 adds `captions`: the word-synced captions of an explainer, or null (EXPLAINER-008).
# Version 4 adds `callouts`: the callouts of an explainer with their times and places, or null
# (EXPLAINER-010).
# Version 5 adds `voice`, the scene takes of a continuous explainer, and `voice` / `voice_window`
# on each shot (FLOW-008).
# Version 6 adds motion callouts (CMO-005): `callouts` gains `callout_style`, `look` and `theme`,
# and an entry may have `motion` (the version it is drawn with, its box and the start of each
# text). A version 5 timeline has none of them and is read as a track of boxes.
# A sound bite shot (SB-008) adds a `soundbite` key to its shot's entry; the render job reads shots
# by the keys it knows, so the version stays 6.
# The optional `graphic_overlays` key (OVL-005) holds the graphics laid over the shots; a timeline
# without it renders as before, so the version stays 6 here too.
TIMELINE_VERSION: Final = 6
# The versions the render job reads.
READABLE_TIMELINE_VERSIONS: Final = (5, 6)

SHOT_TARGET_LUFS: Final = -16.0
NARRATION_TARGET_LUFS: Final = -16.0
MAX_BOOST_DB: Final = 6.0
DUCK_DB: Final = -12.0
DUCK_RAMP_S: Final = 0.25
DUCK_MERGE_GAP_S: Final = 1.0

# --- The music in the mix (MUSIC-012). Starting values, untested by ear, to be tuned. ----------
# The ramps of the music's duck under a voice, longer than the shot audio's, so music breathes.
MUSIC_DUCK_RAMP_S: Final = 0.4
# A gap between two spoken stretches this long lets music that may swell come back up.
MUSIC_GAP_RELEASE_S: Final = 1.0
# ... and this long for music that must hold steady.
MUSIC_GAP_HOLD_S: Final = 4.0
# --- The music under a continuous explainer's voice (EXM-005). Starting values, to be tuned. ---
# A gap between two spoken stretches shorter than this keeps the music lowered: it never rises
# between ordinary sentences.
EXPLAINER_MUSIC_HOLD_GAP_S: Final = 4.0
# The ramps of a planned post's rise, shortened to half the pause when the pause is shorter.
EXPLAINER_POST_RAMP_S: Final = 0.15
# --- The sound effects of a continuous explainer (EXM-007). Starting values, to be tuned. ------
# A sound effect that would start less than this long after the one before is left out.
SOUND_EFFECT_MIN_SPACING_S: Final = 1.5
# The fade at each end of a sound effect, so it never clicks.
SOUND_EFFECT_FADE_S: Final = 0.005
# The take's length is a rounded measurement: the last bit is never played.
SOUND_EFFECT_TAIL_MARGIN_S: Final = 0.01
ROLE_GRAPHIC: Final = "graphic"
ROLE_EVIDENCE: Final = "evidence"
# A short dip around a sound the scene depends on: from DIP_BEFORE_S before to DIP_AFTER_S after.
DIP_DB: Final = -6.0
DIP_BEFORE_S: Final = 0.15
DIP_AFTER_S: Final = 0.5
DIP_RAMP_S: Final = 0.08
# A bed's swell that covers a join.
SWELL_DB: Final = 4.0
SWELL_RAMP_S: Final = 0.5
# The ramps of the shot audio's lowering under a bed.
BED_SHOT_RAMP_S: Final = 1.0
# loudnorm's loudness range, wide so a quiet story keeps its dynamics (linear mode).
MASTER_LRA: Final = 20.0

# --- The voice take of a continuous explainer (FLOW-008). Starting values, untested by ear. ----
# The crossfade at each edge of a presenter shot switched to its clip's own voice: the take fades
# out (or in) over this long, inside the shot, while the clip's sound fades in (or out).
VOICE_FADE_S: Final = 0.05
# The take's own fade at each edge of a sound bite (SB-008): 10 ms, the lowest of the 10 to 30 ms
# that §4.7 of `Sound_bite_implementation_phases.md` gives for speech edges. It is inside the
# take's pieces, never reaching into the clip; SB-009 may change it.
BITE_EDGE_FADE_S: Final = 0.01
VOICE_TAKE: Final = "take"
VOICE_CLIP: Final = "clip"

# --- The sound bite in the mix (SB-009). Starting values, untested by ear. ----------------------
# A sound bite's own sound is brought to the level of the narrator's take over the span it
# replaced, boosted by at most this much (a quiet interview can need more than a presenter clip).
BITE_MAX_BOOST_DB: Final = 12.0
# The clip's sound fades over this long at each end, inside the clip's own length.
BITE_CLIP_FADE_S: Final = 0.02
# The music (score and beds) under a sound bite: a deeper duck than the one under the narrator,
# down before the clip starts and back up after it ends.
BITE_MUSIC_DUCK_DB: Final = -26.0
BITE_DUCK_ATTACK_S: Final = 0.2
BITE_DUCK_RELEASE_S: Final = 0.45
# With "music off under this clip" the music goes to (nearly) silence instead, slower in and out.
BITE_DROP_DB: Final = -90.0
BITE_DROP_ATTACK_S: Final = 0.5
BITE_DROP_RELEASE_S: Final = 0.6
# A story with more music drops than this per ten minutes gets a warning.
BITE_MAX_DROPS_PER_10_MIN: Final = 3

LANE_SCORE: Final = "score"
LANE_BED: Final = "bed"
LANE_SOUNDS: Final = "sounds"
_LANES: Final = (LANE_SCORE, LANE_BED, LANE_SOUNDS)
_POINT_KIND: Final = "point"
UNDER_VOICE_LOW: Final = "low"

# How many shots a refusal names before it says "and n more".
_NAMED: Final = 5

_MS_PER_S: Final = 1000

# Warning codes.
TAKE_OUT_OF_DATE: Final = "take_out_of_date"
TAKE_WITHOUT_SOUND: Final = "take_without_sound"
# A speech has no stored word timing, so its captions use estimated times (EXPLAINER-008).
CAPTION_TIMING_ESTIMATED: Final = "caption_timing_estimated"
# Scene renders (SCN-003): a shot has no clip (or graphic) to show yet and a frame stands in for
# it; a line of dialogue is spoken inside a clip that is not there, so it is not heard; the scene
# starts at an unknown place in the story because an earlier scene has no plan.
SHOT_PLACEHOLDER: Final = "shot_placeholder"
# The narrator's words under a sound bite's clip are left out of the captions (SB-008).
SOUNDBITE_CAPTIONS_DROPPED: Final = "soundbite_captions_dropped"
# Too many sound bites switch the music off for the length of the story (SB-009).
SOUNDBITE_MUSIC_DROPS: Final = "soundbite_music_drops"
# A sound effect (EXM-007) has no selected take or no file: a scene render leaves it out.
SOUND_EFFECT_MISSING: Final = "sound_effect_missing"
DIALOGUE_NOT_HEARD: Final = "dialogue_not_heard"
SCENE_START_UNKNOWN: Final = "scene_start_unknown"

# Why a shot is a placeholder in a scene render.
PLACEHOLDER_NO_CLIP: Final = "No clip yet"
PLACEHOLDER_CLIP_FILE_MISSING: Final = "Clip file missing"
PLACEHOLDER_NO_GRAPHIC: Final = "No graphic yet"
PLACEHOLDER_GRAPHIC_FILE_MISSING: Final = "Graphic file missing"
PLACEHOLDER_NO_EVIDENCE: Final = "No evidence clip yet"
PLACEHOLDER_EVIDENCE_FILE_MISSING: Final = "Evidence clip file missing"
# A sound bite shot has no clip made for it yet (the evidence clips step makes it, SB-009).
PLACEHOLDER_NO_SOUNDBITE: Final = "Sound bite clip not made yet"
PLACEHOLDER_SOUNDBITE_FILE_MISSING: Final = "Sound bite clip file missing"
# Only in the timing timeline of a provisional music placement (SCN-011): a clip that is shorter
# than its shot counts as missing there, so the placement can still be made.
PLACEHOLDER_CLIP_TOO_SHORT: Final = "Clip too short"
PLACEHOLDER_GRAPHIC_TOO_SHORT: Final = "Graphic too short"
PLACEHOLDER_EVIDENCE_TOO_SHORT: Final = "Evidence clip too short"
PLACEHOLDER_SOUNDBITE_TOO_SHORT: Final = "Sound bite clip too short"
# An evidence card (EVD-011) with no clip is left out of a scene render, with this warning code.
CARD_WITHOUT_CLIP: Final = "card_without_clip"
# A graphic overlay (OVL-005) with no video is left out of a scene render, with this warning code.
OVERLAY_WITHOUT_VIDEO: Final = "overlay_without_video"
# A graphic overlay covers an evidence card or a full-screen evidence shot: the graphic is on top
# (an overlay that is drawn beside the evidence, OVL-007, does not).
OVERLAY_OVER_EVIDENCE: Final = "overlay_over_evidence"
# The evidence drawn beside a graphic (OVL-007) with no clip is left out of a scene render, with
# this warning code; and the one whose quote is too small to read at its half of the frame.
SPLIT_WITHOUT_VIDEO: Final = "split_without_video"
SPLIT_SMALL_TEXT: Final = "split_small_text"

# A music sound cut by the edge of a scene render fades over this long (a starting value, not yet
# tuned by ear).
SCENE_MUSIC_FADE_S: Final = 0.5

# SCN-013: the clip's own sound of the first shot of a scene fades in, and that of its last shot
# fades out, over this long at most (a starting value, not yet tuned by ear), so the ambience of
# one scene does not switch to the next one's abruptly. Never into a line of dialogue.
SCENE_CUT_FADE_S: Final = 0.15


class RenderPlanError(ValueError):
    """The story cannot be rendered now. The message is meant to be shown to the user."""


# --- What the plan is made from -------------------------------------------------------------


@dataclass(frozen=True)
class TakeSource:
    """A shot's selected take."""

    take_id: int
    take_number: int
    path: str
    frame_count: int | None
    has_audio: bool
    file_exists: bool
    # Why the take is out of date, one sentence each. Empty when it is current.
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class GraphicSource:
    """The video of a graphic shot (EXG-007): the attempt of the version the rule picks. It has no
    sound and no take; code drew it at the shot's frames plus one spare frame.
    """

    graphic_id: int
    engine: str
    attempt: int
    path: str
    frame_count: int | None
    file_exists: bool


@dataclass(frozen=True)
class EvidenceSource:
    """The clip of an evidence shot (EVD-009): the newest ready clip made for it. Like a graphic it
    has no sound and no take; the motion service drew it at the shot's frames plus one spare frame.
    """

    clip_id: int
    path: str
    frame_count: int | None
    file_exists: bool
    # True for a clip drawn split with a callout (EVD-016): callouts that start in it are kept.
    split: bool = False


@dataclass(frozen=True)
class CardClipSource:
    """The clip of an evidence card (EVD-011): the newest ready clip made for it, a transparent
    ProRes video at the card's own size."""

    clip_id: int
    path: str
    frame_count: int | None
    file_exists: bool


@dataclass(frozen=True)
class CardSource:
    """An evidence card over the shots of a scene (EVD-011): `start_s` and `end_s` sit on the
    scene's timeline like a shot's, `(x, y, width, height)` is where it is laid on the frame, and
    `clip` is None while it has no clip."""

    card_id: str
    claim_id: str
    item_key: str
    start_s: float
    end_s: float
    x: int
    y: int
    width: int
    height: int
    clip: CardClipSource | None


@dataclass(frozen=True)
class SourceLineSource:
    """A source line on a graphic shot (EVD-012), on the scene's timeline."""

    claim_id: str
    item_key: str
    start_s: float
    end_s: float
    text: str


@dataclass(frozen=True)
class OverlaySource:
    """A graphic overlay over the shots of a scene (OVL-005): `start_s` and `end_s` sit on the
    scene's timeline like a shot's, and `graphic` is the video the owner's choice (or the rule)
    picks for it, or None while it has none. It is laid full screen over every shot it spans.
    """

    overlay_id: str
    text: str
    start_s: float
    end_s: float
    graphic: GraphicSource | None
    # Drawn beside evidence in a panel of the frame (OVL-007): `start_s` and `end_s` are then the
    # stretch's span for this graphic, and `(x, y)` is its panel on the frame.
    split: bool = False
    x: int = 0
    y: int = 0


@dataclass(frozen=True)
class SplitClipSource:
    """The clip of evidence beside a graphic (OVL-007): the newest ready clip made for it, a
    full-frame opaque video with the evidence in its half. `small_text` is the sentence of its
    `small_text` warning, when it has one."""

    clip_id: int
    path: str
    frame_count: int | None
    file_exists: bool
    small_text: str | None = None


@dataclass(frozen=True)
class SplitSource:
    """A piece of evidence beside a graphic overlay (OVL-007): `start_s` and `end_s` sit on the
    scene's timeline, and `clip` is None while it has no clip."""

    segment_id: str
    claim_id: str | None
    item_key: str
    start_s: float
    end_s: float
    clip: SplitClipSource | None


@dataclass(frozen=True)
class SoundbiteClipSource:
    """The clip of a sound bite shot (SB-009): the newest ready clip made for it, with the lower
    third and the credit in the picture and the cut's own sound. `take_window` is the stretch of
    the narrator's take the clip replaces, in the take's own seconds (None outside a continuous
    explainer), and `words` the cut's words, `(text, start_s, end_s)` from the clip's start, for
    the captions in the speaker's `colour`."""

    clip_id: int
    path: str
    frame_count: int | None
    file_exists: bool
    music_drop: bool = False
    colour: str | None = None
    words: tuple[tuple[str, float, float], ...] = ()
    take_window: tuple[float, float] | None = None


@dataclass(frozen=True)
class SoundbiteSource:
    """The clip a sound bite shot plays (SB-008): the claim, the clip's item key and how long it
    plays in the scene, in seconds (the owner's cut moved to whole frames). `clip` is None while
    the shot has no clip (SB-009)."""

    claim_id: str
    item_key: str
    seconds: float
    clip: SoundbiteClipSource | None = None


@dataclass(frozen=True)
class ShotSource:
    shot_id: str
    # Where the shot sits in its scene's timeline.
    start_s: float
    end_s: float
    take: TakeSource | None
    # Only in a continuous explainer (FLOW-008): the shot shows the presenter, and the owner
    # switched it to its clip's own voice.
    presenter: bool = False
    clip_voice: bool = False
    # A graphic shot (EXG-007) has no take: its video is `graphic`, or None while it has none.
    is_graphic: bool = False
    graphic: GraphicSource | None = None
    # An evidence shot (EVD-009) has no take either: its video is `evidence`, or None while it has
    # none. It is played like a graphic shot, so the two share the checks below.
    is_evidence: bool = False
    evidence: EvidenceSource | None = None
    # The plan's one-sentence description of the shot, shown on its placeholder (SCN-003).
    description: str | None = None
    # A sound bite shot (SB-008) plays a real person's clip (SB-009 makes it): until it has one, a
    # scene render shows a placeholder and a full render is refused.
    is_soundbite: bool = False
    soundbite: SoundbiteSource | None = None

    @property
    def is_drawn(self) -> bool:
        """A graphic, an evidence or a sound bite shot: no take, no sound of its own from H3."""
        return self.is_graphic or self.is_evidence or self.is_soundbite

    @property
    def drawn(self) -> GraphicSource | EvidenceSource | SoundbiteClipSource | None:
        """The video of a drawn shot, or None while it has none."""
        if self.is_soundbite:
            return self.soundbite.clip if self.soundbite is not None else None
        return self.graphic if self.is_graphic else self.evidence


@dataclass(frozen=True)
class WordTimingSource:
    """The time of each script word of a speech, for the captions (EXPLAINER-007's
    `speech_word_timing`): `(word, start_s, end_s)` in seconds from the start of the file.
    `estimated_now` is True when no timing was stored and the times were estimated for this
    render, which the plan warns about.
    """

    words: tuple[tuple[str, float, float], ...]
    estimated_now: bool = False


@dataclass(frozen=True)
class UnitSource:
    """A speech unit on its scene's timeline, and the file of its speech."""

    unit_id: str
    kind: str
    start_s: float
    end_s: float
    # The length that was measured when the shots were planned, and the speech it belongs to.
    seconds: float | None
    audio_id: int | None
    path: str | None
    file_exists: bool
    # Only for an explainer: the word timing of the speech.
    timing: WordTimingSource | None = None
    # The shots of the scene that carry the unit, in order (SCN-003: a line whose shots are all
    # placeholders is played from its own speech file).
    shot_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class VoiceSource:
    """The voice take of a scene of a continuous explainer (FLOW-008). It plays from the scene's
    start plus the lead-in of `take_map`, which also says where its seconds go on the scene's
    timeline (SB-002).
    """

    audio_id: int
    path: str
    seconds: float
    file_exists: bool
    take_map: TakeMap


@dataclass(frozen=True)
class SceneSource:
    scene_id: str
    index: int
    title: str
    # Where the scene starts in the story; None when a scene before it has no plan.
    story_start_s: float | None
    # Why the scene's shots cannot go to a render (PHASE-021's `generation_blocked_reason`).
    blocked_reason: str | None
    plan_id: int | None
    plan_version: int | None
    shots: list[ShotSource]
    units: list[UnitSource]
    # Set for every scene of a continuous explainer, and only then.
    voice: VoiceSource | None = None
    # The evidence cards over its shots and the source lines on its graphic shots (EVD-011,
    # EVD-012). Empty without evidence.
    cards: list[CardSource] = field(default_factory=list)
    source_lines: list[SourceLineSource] = field(default_factory=list)
    # The graphic overlays over its shots (OVL-005). Empty without suggestions.
    overlays: list[OverlaySource] = field(default_factory=list)
    # The evidence drawn beside those overlays (OVL-007). Empty without a split stretch.
    splits: list[SplitSource] = field(default_factory=list)


@dataclass(frozen=True)
class MixSettings:
    """The settings of the mix, in whole dB and LUFS (`core/settings.py`, MUSIC-012)."""

    loudness_lufs: int = -14
    true_peak_db: int = -1
    duck_low_db: int = -18
    duck_medium_db: int = -10
    # A continuous explainer's music (EXM-005): its one duck depth, and how far the music rises
    # inside a planned post.
    explainer_duck_db: int = -22
    explainer_post_rise_db: int = 8
    # 0 leaves the shot audio alone under a bed.
    bed_shot_duck_db: int = 0


@dataclass(frozen=True)
class MusicSource:
    """The current music placement a render is made with (MUSIC-011's `music_placement.content`)
    and what the cues' own mix notes say.
    """

    placement_id: int
    placement_version: int
    # `music_placement.content`: samples at 48 kHz on this render's own timeline.
    content: dict[str, Any]
    # By cue id: how far under the voice the cue sits (`low` or `medium`), and whether it may
    # swell in the gaps between lines.
    cue_mix: dict[str, tuple[str, bool]]
    # Whether beds and point sounds are in the render (the project's ambience switch).
    ambience: bool = True
    # By cue id: the pauses the music plan chose for the music to rise in, `(start_s, end_s)` on
    # the story's timeline. Only a continuous explainer's cues have any (EXM-005).
    posts: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    # Set only for a provisional placement (SCN-011), made before every clip existed: what it was
    # made from (`music_placement.provisional_inputs`). It is written into `timeline.music` so
    # a scene render can tell later whether it is out of date.
    provisional: dict[str, Any] | None = None


@dataclass(frozen=True)
class SoundEffectTakeSource:
    """The selected take of one sound effect (EXM-006), with what its measurement says."""

    role: str
    take_id: int
    path: str
    file_exists: bool
    # Where the loudest moment is in the sound, and how long the sound is, in seconds.
    peak_s: float
    length_s: float
    # The integrated loudness of the sound, or None when it could not be measured.
    lufs: float | None = None
    # Set when the take cannot be placed (for example it was not measured): a sentence for the
    # owner. The render then refuses, or leaves the sound out of a scene render.
    problem: str | None = None


@dataclass(frozen=True)
class SoundEffectSource:
    """The sound effects a render of a project with the switch on is made with (EXM-007):
    `level_db` is how far under the voice they play, and `takes` has one entry for each sound the
    project needs, `None` while it has no selected take.
    """

    level_db: int
    takes: dict[str, SoundEffectTakeSource | None]


@dataclass(frozen=True)
class RenderPlan:
    timeline: dict[str, Any]
    warnings: list[dict[str, Any]] = field(default_factory=list)


# --- Pure rules -----------------------------------------------------------------------------


def _ms(seconds: float) -> int:
    """Seconds as whole milliseconds. Timeline places are kept to a thousandth of a second, so
    this is exact for them.
    """
    return math.floor(seconds * _MS_PER_S + 0.5)


def frame_at(ms: int, fps: int) -> int:
    """The frame index a boundary at `ms` falls on: the nearest, halves up (`frame_counts`'
    rule, in whole numbers so a half is never lost to float noise).
    """
    return (ms * fps + _MS_PER_S // 2) // _MS_PER_S


def source_frames_needed(frames: int, fps: int) -> int:
    """How many frames of an H3 clip (at its own 24 fps) cover `frames` frames at `fps`."""
    return -(-frames * frame_counts.H3_FPS // fps)


def gain_toward(loudness_lufs: float | None, target_lufs: float, max_boost_db: float) -> float:
    """The gain that brings a sound to `target_lufs`, boosted by at most `max_boost_db` (a louder
    sound is lowered as far as it takes). A sound that could not be measured keeps its own
    level. The job passes the values the timeline recorded, so a render always uses its own.
    """
    if loudness_lufs is None:
        return 0.0
    return min(max_boost_db, target_lufs - loudness_lufs)


def duck_windows(
    narration: list[tuple[float, float]],
    dialogue: list[tuple[float, float]],
    merge_gap_s: float,
) -> list[tuple[float, float]]:
    """The stretches of the story in which the shot audio is lowered: the narration spans, with
    two of them made one when they are less than `merge_gap_s` apart and no line of dialogue is
    heard between them. Times are story seconds.
    """
    merged: list[tuple[float, float]] = []
    for start, end in sorted(narration):
        if merged:
            previous_start, previous_end = merged[-1]
            gap_has_dialogue = any(
                line_start < start and line_end > previous_end for line_start, line_end in dialogue
            )
            if start - previous_end < merge_gap_s and not gap_has_dialogue:
                merged[-1] = (previous_start, max(previous_end, end))
                continue
        merged.append((start, end))
    return merged


def slice_windows(
    windows: list[tuple[float, float]], start_s: float, end_s: float, ramp_s: float
) -> list[list[float]]:
    """The windows that touch a shot (a ramp counts), in the shot's own time, which starts at 0."""
    sliced: list[list[float]] = []
    for start, end in windows:
        if end + ramp_s <= start_s or start - ramp_s >= end_s:
            continue
        sliced.append([round(start - start_s, 3), round(end - start_s, 3)])
    return sliced


def scene_edge_fades(
    shots: list[dict[str, Any]], dialogue_spans: Sequence[tuple[float, float]]
) -> None:
    """Gives the first and the last shot of every scene a longer fade of the clip's own sound at
    the scene's edge (`sound_fade_in_s`, `sound_fade_out_s`, in seconds). Only a shot that plays
    its clip's sound (no graphic, no placeholder, not a presenter shot of a continuous explainer)
    gets them. A fade is `SCENE_CUT_FADE_S`, or shorter when a line of dialogue of the shot is
    closer to the edge, and never shorter than the usual fade. `shots` is the whole timeline, in
    order; a scene render has one scene, so its edges are those of the full render. Changes the
    entries in place.
    """
    edges: dict[str, tuple[int, int]] = {}
    for position, entry in enumerate(shots):
        scene_id = entry["scene_id"]
        first = edges[scene_id][0] if scene_id in edges else position
        edges[scene_id] = (first, position)
    for first, last in edges.values():
        for position, is_start in ((first, True), (last, False)):
            entry = shots[position]
            if (
                entry.get("voice") is not None
                or entry.get("graphic") is not None
                or entry.get("evidence") is not None
                or entry.get("soundbite") is not None
                or entry.get("placeholder") is not None
                or not entry.get("has_audio")
            ):
                continue
            start_s, end_s = entry["start_ms"] / _MS_PER_S, entry["end_ms"] / _MS_PER_S
            inside = [span for span in dialogue_spans if span[0] < end_s and span[1] > start_s]
            if is_start:
                gap = min((span[0] - start_s for span in inside), default=SCENE_CUT_FADE_S)
                key = "sound_fade_in_s"
            else:
                gap = min((end_s - span[1] for span in inside), default=SCENE_CUT_FADE_S)
                key = "sound_fade_out_s"
            entry[key] = round(max(render_commands.FADE_S, min(SCENE_CUT_FADE_S, gap)), 3)


def merge_spans(spans: Sequence[tuple[float, float]], gap_s: float) -> list[tuple[float, float]]:
    """The spans in order, with two made one when they overlap or are less than `gap_s` apart."""
    merged: list[tuple[float, float]] = []
    for start, end in sorted(spans):
        if merged and (start <= merged[-1][1] or start - merged[-1][1] < gap_s):
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def subtract_spans(
    spans: Sequence[tuple[float, float]], removed: Sequence[tuple[float, float]]
) -> list[tuple[float, float]]:
    """What is left of `spans` once every span of `removed` is taken out."""
    holes = merge_spans(removed, 0.0)
    left: list[tuple[float, float]] = []
    for start, end in merge_spans(spans, 0.0):
        cursor = start
        for hole_start, hole_end in holes:
            if hole_end <= cursor or hole_start >= end:
                continue
            if hole_start > cursor:
                left.append((cursor, hole_start))
            cursor = max(cursor, hole_end)
        if cursor < end:
            left.append((cursor, end))
    return left


def constants(mix: MixSettings | None = None) -> dict[str, float]:
    """The audio values a render used, recorded on it (D-3)."""
    mix = mix or MixSettings()
    return {
        "shot_target_lufs": SHOT_TARGET_LUFS,
        "narration_target_lufs": NARRATION_TARGET_LUFS,
        "max_boost_db": MAX_BOOST_DB,
        "duck_db": DUCK_DB,
        "duck_ramp_s": DUCK_RAMP_S,
        "duck_merge_gap_s": DUCK_MERGE_GAP_S,
        "music_duck_low_db": float(mix.duck_low_db),
        "music_duck_medium_db": float(mix.duck_medium_db),
        "music_duck_ramp_s": MUSIC_DUCK_RAMP_S,
        "music_gap_release_s": MUSIC_GAP_RELEASE_S,
        "music_gap_hold_s": MUSIC_GAP_HOLD_S,
        "dip_db": DIP_DB,
        "dip_before_s": DIP_BEFORE_S,
        "dip_after_s": DIP_AFTER_S,
        "dip_ramp_s": DIP_RAMP_S,
        "swell_db": SWELL_DB,
        "swell_ramp_s": SWELL_RAMP_S,
        "bed_shot_duck_db": float(mix.bed_shot_duck_db),
        "bed_shot_ramp_s": BED_SHOT_RAMP_S,
        "voice_fade_s": VOICE_FADE_S,
        "scene_cut_fade_s": SCENE_CUT_FADE_S,
        "master_lufs": float(mix.loudness_lufs),
        "master_true_peak_db": float(mix.true_peak_db),
        "master_lra": MASTER_LRA,
    }


def explainer_constants(mix: MixSettings) -> dict[str, float]:
    """The values of a continuous explainer's music mix (EXM-005), recorded only on the timeline
    of such a render, so a story's recorded constants do not change."""
    return {
        "explainer_music_duck_db": float(mix.explainer_duck_db),
        "explainer_music_post_rise_db": float(mix.explainer_post_rise_db),
        "explainer_music_hold_gap_s": EXPLAINER_MUSIC_HOLD_GAP_S,
        "explainer_music_post_ramp_s": EXPLAINER_POST_RAMP_S,
    }


def bite_constants() -> dict[str, float]:
    """The values of the sound bite in the mix (SB-009), recorded on a timeline that has one. A
    timeline without a bite does not have them, so it does not change; the render reads a missing
    one as the value it has here."""
    return {
        "bite_max_boost_db": BITE_MAX_BOOST_DB,
        "bite_clip_fade_s": BITE_CLIP_FADE_S,
        "bite_music_duck_db": BITE_MUSIC_DUCK_DB,
        "bite_duck_attack_s": BITE_DUCK_ATTACK_S,
        "bite_duck_release_s": BITE_DUCK_RELEASE_S,
        "bite_drop_db": BITE_DROP_DB,
        "bite_drop_attack_s": BITE_DROP_ATTACK_S,
        "bite_drop_release_s": BITE_DROP_RELEASE_S,
    }


def sound_effect_constants() -> dict[str, float]:
    """The values of the sound effects (EXM-007), recorded only on a timeline that has the key,
    so every other timeline's recorded constants do not change."""
    return {
        "sound_effect_min_spacing_s": SOUND_EFFECT_MIN_SPACING_S,
        "sound_effect_fade_s": SOUND_EFFECT_FADE_S,
    }


# One moment a sound effect may be placed at: its first frame (on the story), a rank that puts the
# evidence sound before the graphic sound on the same frame, the role, the kind of moment, its
# reference and its scene.
_SoundMoment = tuple[int, int, str, str, str, str]


def _sound_moments(
    shots: list[dict[str, Any]],
    card_entries: list[dict[str, Any]],
    overlay_entries: list[dict[str, Any]],
) -> list[_SoundMoment]:
    """Where the graphic and evidence sounds may play (EXM-007): the first frame of every graphic
    shot and graphic overlay, and of every evidence shot and evidence card. A placeholder shot has
    neither key, so it has no moment.
    """
    moments: list[_SoundMoment] = []
    for shot in shots:
        ref = f"{shot['scene_id']}/{shot['shot_id']}"
        if isinstance(shot.get("evidence"), dict):
            moments.append(
                (shot["start_frame"], 0, ROLE_EVIDENCE, "evidence_shot", ref, shot["scene_id"])
            )
        elif isinstance(shot.get("graphic"), dict):
            moments.append(
                (shot["start_frame"], 1, ROLE_GRAPHIC, "graphic_shot", ref, shot["scene_id"])
            )
    moments.extend(
        (card["start_frame"], 0, ROLE_EVIDENCE, "evidence_card", card["id"], card["scene_id"])
        for card in card_entries
    )
    moments.extend(
        (
            overlay["start_frame"],
            1,
            ROLE_GRAPHIC,
            "graphic_overlay",
            overlay["id"],
            overlay["scene_id"],
        )
        for overlay in overlay_entries
    )
    return sorted(moments)


def _sound_effects_entry(
    source: SoundEffectSource,
    moments: list[_SoundMoment],
    *,
    bite_spans: Sequence[tuple[int, int]],
    fps: int,
    window_start: int,
    window_end: int,
    placeholders: bool,
    warnings: list[dict[str, Any]],
) -> dict[str, Any]:
    """The `sound_effects` part of the timeline (EXM-007). `window_start` and `window_end` are the
    samples of the story this render covers (the whole story, or one scene's window); a sound
    whose start falls before the window is cut at its edge. A moment whose role has no usable take
    refuses a full render and is left out of a scene render with a warning.
    """
    rate = render_commands.SAMPLE_RATE
    usable: dict[str, SoundEffectTakeSource] = {}
    problems: dict[str, str] = {}
    wanted_roles = {moment[2] for moment in moments if moment[2] in source.takes}
    for role in sorted(wanted_roles):
        take = source.takes[role]
        if take is None:
            problems[role] = f"The {role} sound effect has no selected take yet."
        elif not take.file_exists:
            problems[role] = f"The file of the {role} sound effect is missing. Make it again."
        elif take.problem is not None:
            problems[role] = take.problem
        else:
            usable[role] = take
    if problems:
        way_out = (
            " Make it in the Sound effects step, or switch sound effects off in the project's "
            "settings."
        )
        if not placeholders:
            raise RenderPlanError(" ".join(problems.values()) + way_out)
        warnings.extend(
            {
                "code": SOUND_EFFECT_MISSING,
                "scene_id": None,
                "shot_id": None,
                "message": f"{message} Its moments in this render have no sound.",
            }
            for message in problems.values()
        )

    samples_per_ms = rate // _MS_PER_S
    entries: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    last_moment_s: float | None = None
    for frame, _rank, role, kind, ref, scene_id in moments:
        take = usable.get(role)
        if take is None:
            continue
        ident = f"{kind}:{ref}"
        moment = render_commands.sample_count(frame, fps)
        start = moment - round(take.peak_s * rate)
        in_sample = 0
        if start < window_start:
            in_sample = window_start - start
            start = window_start
        take_samples = max(0, math.floor((take.length_s - SOUND_EFFECT_TAIL_MARGIN_S) * rate))
        length = min(take_samples - in_sample, window_end - start)
        if length < 1:
            skipped.append({"id": ident, "reason": "outside the video"})
            continue
        end = start + length
        if any(
            bite_start * samples_per_ms < end and bite_end * samples_per_ms > start
            for bite_start, bite_end in bite_spans
        ):
            skipped.append({"id": ident, "reason": "inside a sound bite"})
            continue
        moment_s = moment / rate
        if last_moment_s is not None and moment_s - last_moment_s < SOUND_EFFECT_MIN_SPACING_S:
            skipped.append({"id": ident, "reason": "too close to the previous sound effect"})
            continue
        last_moment_s = moment_s
        gain = (
            float(source.level_db)
            if take.lufs is None
            else min(MAX_BOOST_DB, NARRATION_TARGET_LUFS + source.level_db - take.lufs)
        )
        fade = min(round(SOUND_EFFECT_FADE_S * rate), length // 2)
        entries.append(
            {
                "id": ident,
                "role": role,
                "kind": kind,
                "scene_id": scene_id,
                "take_id": take.take_id,
                "path": take.path,
                "start_sample": start,
                "in_sample": in_sample,
                "length_samples": length,
                "gain_db": round(gain, 2),
                "fade_in": _cut_fade(fade),
                "fade_out": _cut_fade(fade),
            }
        )
    return {
        "level_db": float(source.level_db),
        "takes": {
            role: (take.take_id if take is not None else None)
            for role, take in source.takes.items()
        },
        "entries": entries,
        "skipped": skipped,
    }


def master(mix: MixSettings) -> dict[str, float]:
    """The loudness the finished mix is brought to."""
    return {
        "target_lufs": float(mix.loudness_lufs),
        "true_peak_db": float(mix.true_peak_db),
        "lra": MASTER_LRA,
    }


# --- The voice take (FLOW-008) ---------------------------------------------------------------


def voice_pieces(
    take_start_sample: int,
    take_samples: int,
    clip_spans: Sequence[tuple[int, int]],
    fade_samples: int,
    total_samples: int,
    take_map: TakeMap = NO_REPLACED,
    rate: int = render_commands.SAMPLE_RATE,
) -> list[dict[str, int]]:
    """The pieces of one scene's take that are heard, sample-exact at 48 kHz. `take_start_sample`
    is where the take starts on the story's timeline, `take_samples` its length, and `clip_spans`
    the `(start, end)` samples, on the story's timeline, of the shots whose own voice is used: the
    take is silent for exactly those spans. `take_map` (at `rate` samples a second) says how far
    later than `take_start_sample + in_sample` a piece plays, because of the clips that replace
    parts of the take (sound bites, SB-008).

    Each piece plays the part `in_sample` to `in_sample + length_samples` of the take at
    `start_sample` of the story. A piece that borders a clip span reaches `fade_samples` into it
    and fades out (or in) over that stretch, while the clip's own sound fades in (or out) over
    the same samples, so the cut between the two voices does not click. With no span the take is
    one piece with no fades. A take that starts outside the video has none.

    A stretch the map replaces (a sound bite) is cut out of the take for good: no piece plays
    any of it. The pieces beside it stop at its edge, never reaching into it, and fade over
    `BITE_EDGE_FADE_S` inside themselves, so the cut makes no click and nothing of the take is
    heard under the clip.
    """
    bites = take_map.replaced_take_samples(rate)
    # With a replaced span the take takes more room on the story than its own length, so the
    # room is checked for each piece below.
    length = take_samples if bites else min(take_samples, total_samples - take_start_sample)
    if length < 1:
        return []
    spans: list[list[int]] = []
    for start, end in sorted(clip_spans):
        low = max(0, take_map.take_sample_at(start - take_start_sample, rate))
        high = min(length, take_map.take_sample_at(end - take_start_sample, rate))
        if high <= low:
            continue
        if spans and low <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], high)
        else:
            spans.append([low, high])
    # Every stretch of the take that does not play as the take, in order: `(low, high, is_bite)`.
    cuts: list[tuple[int, int, bool]] = [(low, high, False) for low, high in spans]
    for low, high in bites:
        low, high = max(0, low), min(length, high)
        if high > low:
            cuts.append((low, high, True))
    cuts.sort()
    # The stretches of the take between the cuts, each with the cut before / after it, if any.
    gaps: list[tuple[int, int, bool | None, bool | None]] = []
    cursor = 0
    for position, (low, high, bite) in enumerate(cuts):
        gaps.append((cursor, low, cuts[position - 1][2] if position > 0 else None, bite))
        cursor = high
    gaps.append((cursor, length, cuts[-1][2] if cuts else None, None))

    edge = round(BITE_EDGE_FADE_S * rate)
    pieces: list[dict[str, int]] = []
    for gap_start, gap_end, before, after in gaps:
        # A clip span (False) is crossfaded into; a sound bite (True) is cut at its edge.
        crossfades_before, crossfades_after = before is False, after is False
        if gap_end <= gap_start and not (crossfades_before and crossfades_after):
            continue
        start = max(0, gap_start - fade_samples) if crossfades_before else gap_start
        end = min(length, gap_end + fade_samples) if crossfades_after else gap_end
        if bites:
            # The take's own place on the story, which the clips before it moved later.
            room = total_samples - (
                take_start_sample + start + take_map.bite_shift_samples_at(start, rate)
            )
            end = min(end, start + room)
        if end <= start:
            continue
        if crossfades_before:
            fade_in = min(fade_samples, gap_start - start)
        else:
            fade_in = min(edge, end - start) if before is True else 0
        if crossfades_after:
            fade_out = min(fade_samples, end - gap_end)
        else:
            fade_out = min(edge, end - start) if after is True else 0
        pieces.append(
            {
                "in_sample": start,
                "start_sample": take_start_sample
                + start
                + take_map.bite_shift_samples_at(start, rate),
                "length_samples": end - start,
                "fade_in_samples": fade_in,
                "fade_out_samples": fade_out,
            }
        )
    return pieces


def voice_match_gain(
    clip_lufs: float | None,
    take_span_lufs: float | None,
    take_gain_db: float,
    target_lufs: float,
    max_boost_db: float,
) -> float:
    """The gain of a presenter clip's own voice. It is brought to the loudness the take has in
    the mix over the same span (the take's loudness there plus the take's own gain), boosted by at
    most `max_boost_db`. When the take's span could not be measured, the clip is brought to
    `target_lufs` like any shot's sound; a clip that could not be measured keeps its own level.
    """
    if clip_lufs is None:
        return 0.0
    if take_span_lufs is None:
        return gain_toward(clip_lufs, target_lufs, max_boost_db)
    return min(max_boost_db, take_gain_db + take_span_lufs - clip_lufs)


# --- The music layers -----------------------------------------------------------------------


def _fade(raw: object, length: int) -> dict[str, Any]:
    """A placement's fade as the timeline records it, never longer than the sound."""
    fade = raw if isinstance(raw, dict) else {}
    samples = fade.get("samples")
    shape = fade.get("shape")
    return {
        "samples": max(0, min(samples if isinstance(samples, int) else 0, length)),
        "shape": shape if shape in ("linear", "equal_power") else "linear",
    }


def _windows_of(
    windows: Sequence[tuple[float, float]], start_s: float, end_s: float, ramp_s: float
) -> list[list[float]]:
    return slice_windows(list(windows), start_s, end_s, ramp_s)


def _post_rises(
    posts: Sequence[tuple[float, float]],
    speech_spans: Sequence[tuple[float, float]],
    ducked: Sequence[tuple[float, float]],
    start_s: float,
    end_s: float,
    rise_db: float,
) -> list[dict[str, Any]]:
    """The rises of one explainer sound (EXM-005), in the sound's own seconds: one for the pause of
    each post that lies inside the sound. The pause is the post's span with every spoken stretch
    taken out, and only the part where the music is still lowered (`ducked`), so a rise never
    lifts the music above its own level. Each is drawn in by a ramp (the filter's ramps lie
    outside its window): `EXPLAINER_POST_RAMP_S`, or half the pause when it is shorter.
    """
    rises: list[dict[str, Any]] = []
    for post_start, post_end in posts:
        lowered = subtract_spans([(post_start, post_end)], speech_spans)
        for pause_start, pause_end in subtract_spans(lowered, subtract_spans(lowered, ducked)):
            pause_start, pause_end = max(pause_start, start_s), min(pause_end, end_s)
            length = pause_end - pause_start
            if length <= 0:
                continue
            ramp = min(EXPLAINER_POST_RAMP_S, length / 2)
            rises.append(
                {
                    "windows": [
                        [
                            round(pause_start + ramp - start_s, 3),
                            round(pause_end - ramp - start_s, 3),
                        ]
                    ],
                    "db": rise_db,
                    "ramp_s": round(ramp, 3),
                }
            )
    return rises


def _music_timeline(
    music: MusicSource,
    mix: MixSettings,
    speech_spans: Sequence[tuple[float, float]],
    dialogue_spans: Sequence[tuple[float, float]],
    total_samples: int,
    bite_windows: Sequence[tuple[float, float, bool]] = (),
    explainer: bool = False,
) -> tuple[dict[str, Any], list[tuple[float, float]]]:
    """The `music` part of the timeline, and the spans of the story (seconds) in which a bed
    plays. Raises RenderPlanError for a placement this version cannot read.

    `bite_windows` are the sound bite clips, `(start_s, end_s, music_drop)` on the story: the score
    and the beds are lowered much deeper under each one, or switched off with `music_drop`
    (SB-009). A sound that no bite touches, and a render with no bite, have no `bite_ducks`.

    With `explainer` (a continuous explainer, EXM-005) every score sound ducks to
    `mix.explainer_duck_db` through every gap shorter than `EXPLAINER_MUSIC_HOLD_GAP_S`, and a
    sound whose cue has posts gets `rises` inside the pause of each post. A story is unchanged.
    """
    content = music.content
    rate = content.get("sample_rate")
    placements = content.get("placements")
    if rate != render_commands.SAMPLE_RATE or not isinstance(placements, list):
        raise RenderPlanError(
            "The music placement is not one this version can render. Place again."
        )
    rate_f = float(rate)

    kept: list[dict[str, Any]] = []
    left_out: list[dict[str, str]] = []
    for placed in placements:
        lane, kind = placed.get("lane"), placed.get("kind")
        if lane not in _LANES:
            raise RenderPlanError("The music placement is not one this version can render.")
        if not music.ambience and (lane == LANE_BED or kind == _POINT_KIND):
            left_out.append({"item_id": str(placed["item_id"]), "reason": "ambience is off"})
            continue
        start = int(placed["story_start_sample"])
        if start >= total_samples or int(placed["length_samples"]) < 1:
            left_out.append({"item_id": str(placed["item_id"]), "reason": "outside the video"})
            continue
        kept.append(placed)

    # The moments the music must make room for: placed hits and point sounds, and the sounds the
    # video model makes for a cue.
    moments = [
        int(placed["moment"]["moment_sample"]) / rate_f for placed in kept if placed.get("moment")
    ]
    moments += [float(item["chosen_s"]) for item in content.get("h3_sounds") or []]
    dips = merge_spans([(t - DIP_BEFORE_S, t + DIP_AFTER_S) for t in moments], 0.0)

    swells = [
        (float(item["second"]), float(item["second"]) + float(item["length_s"]))
        for item in content.get("mix_requests") or []
        if item.get("kind") == "swell"
    ]
    holds = {
        True: merge_spans(speech_spans, MUSIC_GAP_RELEASE_S),
        False: merge_spans(speech_spans, MUSIC_GAP_HOLD_S),
    }

    explainer_hold = merge_spans(speech_spans, EXPLAINER_MUSIC_HOLD_GAP_S) if explainer else []

    sounds: list[dict[str, Any]] = []
    bed_spans: list[tuple[float, float]] = []
    for placed in kept:
        lane = str(placed["lane"])
        start = int(placed["story_start_sample"])
        source_in = int(placed["source_in_sample"])
        length = min(int(placed["length_samples"]), total_samples - start)
        start_s, end_s = start / rate_f, (start + length) / rate_f
        musical = lane in (LANE_SCORE, LANE_BED)
        if lane == LANE_BED:
            bed_spans.append((start_s, end_s))

        duck: list[list[float]] = []
        duck_db: float | None = None
        dip: list[list[float]] = []
        bumps: list[list[float]] = []
        rises: list[dict[str, Any]] = []
        if musical:
            if explainer:
                duck = _windows_of(explainer_hold, start_s, end_s, MUSIC_DUCK_RAMP_S)
                if duck:
                    duck_db = float(mix.explainer_duck_db)
                rises = _post_rises(
                    music.posts.get(str(placed["cue_id"]), []),
                    speech_spans,
                    explainer_hold,
                    start_s,
                    end_s,
                    float(mix.explainer_post_rise_db),
                )
            else:
                under, may_swell = music.cue_mix.get(
                    str(placed["cue_id"]), (UNDER_VOICE_LOW, False)
                )
                duck = _windows_of(holds[may_swell], start_s, end_s, MUSIC_DUCK_RAMP_S)
                if duck:
                    duck_db = float(
                        mix.duck_low_db if under == UNDER_VOICE_LOW else mix.duck_medium_db
                    )
            dip = _windows_of(dips, start_s, end_s, DIP_RAMP_S)
        if lane == LANE_BED:
            bumps = _windows_of(
                [(a, b) for a, b in swells if start_s <= a <= end_s], start_s, end_s, SWELL_RAMP_S
            )
        bite_ducks: list[dict[str, Any]] = []
        if musical:
            for drop, depth, attack, release in (
                (False, BITE_MUSIC_DUCK_DB, BITE_DUCK_ATTACK_S, BITE_DUCK_RELEASE_S),
                (True, BITE_DROP_DB, BITE_DROP_ATTACK_S, BITE_DROP_RELEASE_S),
            ):
                around = _windows_of(
                    [(a, b) for a, b, dropped in bite_windows if dropped == drop],
                    start_s,
                    end_s,
                    max(attack, release),
                )
                if around:
                    bite_ducks.append(
                        {"windows": around, "db": depth, "attack_s": attack, "release_s": release}
                    )
        sounds.append(
            {
                "item_id": str(placed["item_id"]),
                "cue_id": str(placed["cue_id"]),
                "lane": lane,
                "kind": str(placed["kind"]),
                "path": str(placed["path"]),
                "start_sample": start,
                "in_sample": source_in,
                "length_samples": length,
                "gain_db": float(placed.get("match_gain_db") or 0.0),
                "fade_in": _fade(placed.get("fade_in"), length),
                "fade_out": _fade(placed.get("fade_out"), length),
                "duck": duck,
                "duck_db": duck_db,
                "dips": dip,
                "bumps": bumps,
                **({"bite_ducks": bite_ducks} if bite_ducks else {}),
                **({"rises": rises} if rises else {}),
            }
        )

    timeline = {
        "placement_id": music.placement_id,
        "placement_version": music.placement_version,
        "ambience": music.ambience,
        "total_samples": total_samples,
        "sounds": sounds,
        "left_out": left_out,
    }
    if music.provisional is not None:
        timeline["provisional"] = music.provisional
    return timeline, bed_spans


# --- The plan -------------------------------------------------------------------------------


def _named(items: list[str]) -> str:
    shown = ", ".join(items[:_NAMED])
    return shown if len(items) <= _NAMED else f"{shown} and {len(items) - _NAMED} more"


def _scene_label(scene: SceneSource) -> str:
    """The scene as a sentence starts with it. Not `str.capitalize`, which would lower the
    title's own capitals.
    """
    return f"Scene {scene.index} ({scene.title})"


def _check_scenes(scenes: list[SceneSource]) -> None:
    if not scenes:
        raise RenderPlanError("There are no scenes yet.")
    for scene in scenes:
        if scene.blocked_reason is not None:
            raise RenderPlanError(f"{_scene_label(scene)}: {scene.blocked_reason}")
        if scene.story_start_s is None or not scene.shots:
            raise RenderPlanError(f"{_scene_label(scene)} has no shots yet.")


def _words_outside(
    words: Sequence[tuple[str, float, float]],
    unit_start_s: float,
    windows: Sequence[tuple[float, float]],
) -> tuple[tuple[str, float, float], ...]:
    """The words of a unit that are not inside a window of its scene (a sound bite's shot).
    `words` are `(text, start_s, end_s)` from the unit's start at `unit_start_s` of the scene; a
    word is inside a window when its middle is strictly inside it. With no window, all words."""
    if not windows:
        return tuple(words)
    return tuple(
        word
        for word in words
        if not any(start < unit_start_s + (word[1] + word[2]) / 2 < end for start, end in windows)
    )


def placeholder_reason(shot: ShotSource) -> str | None:
    """Why a shot has nothing to show yet (a scene render puts a placeholder there), or None when
    its clip, or the video of its graphic, is there.
    """
    if shot.is_soundbite:
        clip = shot.soundbite.clip if shot.soundbite is not None else None
        if clip is None:
            return PLACEHOLDER_NO_SOUNDBITE
        if not clip.file_exists:
            return PLACEHOLDER_SOUNDBITE_FILE_MISSING
        return None
    if shot.is_graphic:
        if shot.graphic is None:
            return PLACEHOLDER_NO_GRAPHIC
        if not shot.graphic.file_exists:
            return PLACEHOLDER_GRAPHIC_FILE_MISSING
        return None
    if shot.is_evidence:
        if shot.evidence is None:
            return PLACEHOLDER_NO_EVIDENCE
        if not shot.evidence.file_exists:
            return PLACEHOLDER_EVIDENCE_FILE_MISSING
        return None
    if shot.take is None:
        return PLACEHOLDER_NO_CLIP
    if not shot.take.file_exists:
        return PLACEHOLDER_CLIP_FILE_MISSING
    return None


def _check_takes(scenes: list[SceneSource], *, placeholders: bool = False) -> None:
    """Every shot needs a selected take whose file is there. A graphic shot needs the video of its
    graphic instead (EXG-007), an evidence shot the clip of its evidence (EVD-009). With
    `placeholders` (a scene render), a shot that has none is let through: the render shows a
    placeholder for it.
    """
    without_clip: list[str] = []
    missing_file: list[str] = []
    without_graphic: list[str] = []
    missing_graphic: list[str] = []
    without_evidence: list[str] = []
    missing_evidence: list[str] = []
    without_soundbite: list[str] = []
    missing_soundbite: list[str] = []
    for scene in scenes:
        for shot in scene.shots:
            if placeholders and placeholder_reason(shot) is not None:
                continue
            label = f"{shot.shot_id} of scene {scene.index}"
            if shot.is_soundbite:
                clip = shot.soundbite.clip if shot.soundbite is not None else None
                if clip is None:
                    without_soundbite.append(label)
                elif not clip.file_exists:
                    missing_soundbite.append(label)
            elif shot.is_graphic:
                if shot.graphic is None:
                    without_graphic.append(label)
                elif not shot.graphic.file_exists:
                    missing_graphic.append(label)
            elif shot.is_evidence:
                if shot.evidence is None:
                    without_evidence.append(label)
                elif not shot.evidence.file_exists:
                    missing_evidence.append(label)
            elif shot.take is None:
                without_clip.append(label)
            elif not shot.take.file_exists:
                missing_file.append(label)
    if without_soundbite:
        raise RenderPlanError(
            f"These sound bite shots have no clip yet: {_named(without_soundbite)}. Make the "
            "evidence clips first (the step makes the sound bite clips too); until then only a "
            "scene render, which shows a placeholder for it, can be made."
        )
    if missing_soundbite:
        raise RenderPlanError(
            f"The clip file of these sound bite shots is missing: {_named(missing_soundbite)}. "
            "Make the evidence clips again."
        )
    if without_clip:
        raise RenderPlanError(
            f"These shots have no clip yet: {_named(without_clip)}. Generate them first."
        )
    if missing_file:
        raise RenderPlanError(
            f"The clip file of these shots is missing: {_named(missing_file)}. Generate them again."
        )
    if without_graphic:
        raise RenderPlanError(
            f"These graphic shots have no video yet: {_named(without_graphic)}. "
            "Make the graphics first."
        )
    if missing_graphic:
        raise RenderPlanError(
            f"The video file of these graphic shots is missing: {_named(missing_graphic)}. "
            "Make the graphics again."
        )
    if without_evidence:
        raise RenderPlanError(
            f"These evidence shots have no clip yet: {_named(without_evidence)}. "
            "Draw the evidence shots first."
        )
    if missing_evidence:
        raise RenderPlanError(
            f"The clip file of these evidence shots is missing: {_named(missing_evidence)}. "
            "Draw the evidence shots again."
        )


def _voice_entry(
    scenes: list[SceneSource],
    clip_spans: dict[str, list[tuple[int, int]]],
    shots: list[dict[str, Any]],
    fps: int,
    total_frames: int,
) -> dict[str, Any]:
    """The `voice` layer: each scene's take at its place, cut into the pieces that are heard. Also
    fills in `voice_window` (the part of the take under the shot, in the take's own seconds) on
    every shot that uses its clip's voice, which the render measures to match the two loudnesses.
    """
    rate = render_commands.SAMPLE_RATE
    total_samples = render_commands.sample_count(total_frames, fps)
    fade = round(VOICE_FADE_S * rate)
    takes: list[dict[str, Any]] = []
    for scene in scenes:
        assert scene.voice is not None and scene.story_start_s is not None
        take_map = scene.voice.take_map
        start_ms = _ms(scene.story_start_s + take_map.lead_in_s)
        start_sample = start_ms * (rate // _MS_PER_S)
        length = round(scene.voice.seconds * rate)
        spans = clip_spans.get(scene.scene_id, [])
        for entry in shots:
            if entry["scene_id"] != scene.scene_id or entry["voice"] != VOICE_CLIP:
                continue
            first = render_commands.sample_count(entry["start_frame"], fps)
            last = render_commands.sample_count(entry["start_frame"] + entry["frames"], fps)
            try:
                low = max(0, take_map.take_sample_at(first - start_sample, rate))
                high = min(length, take_map.take_sample_at(last - start_sample, rate))
            except TakeMapError as exc:
                raise RenderPlanError(
                    f"The voice of shot {entry['shot_id']} overlaps a sound bite: {exc}"
                ) from exc
            if high > low:
                entry["voice_window"] = {
                    "start_s": round(low / rate, 6),
                    "end_s": round(high / rate, 6),
                }
        takes.append(
            {
                "scene_id": scene.scene_id,
                "audio_id": scene.voice.audio_id,
                "path": scene.voice.path,
                "seconds": scene.voice.seconds,
                "start_ms": start_ms,
                "pieces": voice_pieces(
                    start_sample, length, spans, fade, total_samples, take_map, rate
                ),
            }
        )
    return {"takes": takes}


def _version_ref(ref: tuple[int, int] | None) -> dict[str, int] | None:
    return None if ref is None else {"id": ref[0], "version": ref[1]}


def build_plan(
    scenes: list[SceneSource],
    *,
    fps: int,
    width: int,
    height: int,
    mix: MixSettings | None = None,
    music: MusicSource | None = None,
    captions: caption_plan.CaptionStyle | None = None,
    captions_burned: bool = True,
    callouts: callout_render.CalloutSource | None = None,
    measure: callout_render.Measure | None = None,
    sound_effects: SoundEffectSource | None = None,
) -> RenderPlan:
    """The frozen timeline of a render and its warnings. Raises RenderPlanError with the reason
    when the story cannot be rendered now. `sound_effects` is None for a render without them
    (EXM-007). `music` is None for a render without music, and
    `captions` is None for a render without a caption track (a story), `captions_burned` says
    whether the render draws the track on the picture (CAP-001), and `callouts` is None for a
    render without callouts. `measure` measures a callout's text (the bundled font's by default).
    """
    return _build(
        scenes,
        fps=fps,
        width=width,
        height=height,
        mix=mix,
        music=music,
        captions=captions,
        captions_burned=captions_burned,
        callouts=callouts,
        measure=measure,
        placeholders=False,
        first_frame=0,
        sound_effects=sound_effects,
    )


def build_timing_plan(
    scenes: list[SceneSource], *, fps: int, width: int, height: int
) -> RenderPlan:
    """Where every shot, line and cut of the whole story sits, for a music placement made before
    every clip exists (SCN-011). It is the full builder with placeholders, and a clip that is
    shorter than its shot counts as missing too, so no clip can stop it. Shot lengths come from
    the shot plans, so every second is the one the full render will have. No music, captions
    or callouts. It is never rendered.
    """
    return _build(
        scenes,
        fps=fps,
        width=width,
        height=height,
        mix=None,
        music=None,
        captions=None,
        captions_burned=True,
        callouts=None,
        measure=None,
        placeholders=True,
        first_frame=0,
        short_clips_as_placeholders=True,
    )


def _card_entries(
    scenes: list[SceneSource],
    fps: int,
    total_frames: int,
    *,
    placeholders: bool,
    warnings: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """The evidence cards of the scenes as timeline entries (EVD-011), and the cards that have no
    usable clip. A card is laid over whatever shots it spans, so it only needs a frame range of
    the story and a clip with at least that many frames (one short is allowed, as for a shot). In
    a scene render a card without a clip is left out with a warning; in a full render it is
    returned as missing, and the plan refuses.
    """
    entries: list[dict[str, Any]] = []
    missing: list[str] = []
    for scene in scenes:
        if scene.story_start_s is None:
            continue
        for card in scene.cards:
            start_ms = _ms(scene.story_start_s + card.start_s)
            end_ms = _ms(scene.story_start_s + card.end_s)
            start_frame = frame_at(start_ms, fps)
            frames = min(frame_at(end_ms, fps), total_frames) - start_frame
            if frames < 1:
                continue
            label = f"{card.card_id} of scene {scene.index}"
            clip = card.clip
            if (
                clip is None
                or not clip.file_exists
                or clip.frame_count is None
                or clip.frame_count < frames - 1
            ):
                if not placeholders:
                    missing.append(label)
                    continue
                warnings.append(
                    {
                        "code": CARD_WITHOUT_CLIP,
                        "scene_id": scene.scene_id,
                        "shot_id": None,
                        "message": f"The evidence card {label} is left out: it has no clip yet.",
                    }
                )
                continue
            entries.append(
                {
                    "id": f"{scene.scene_id}/{card.card_id}",
                    "scene_id": scene.scene_id,
                    "claim_id": card.claim_id,
                    "item_key": card.item_key,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "start_frame": start_frame,
                    "frames": frames,
                    "clip_id": clip.clip_id,
                    "path": clip.path,
                    "clip_frames": clip.frame_count,
                    "x": card.x,
                    "y": card.y,
                    "width": card.width,
                    "height": card.height,
                }
            )
    return entries, missing


def _overlay_entries(
    scenes: list[SceneSource],
    fps: int,
    total_frames: int,
    *,
    placeholders: bool,
    warnings: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """The graphic overlays of the scenes as timeline entries (OVL-005), and the overlays that
    have no usable video. An overlay is laid over whatever shots it spans, so it only needs a
    frame range of the story and a video with the frames that range needs (one source frame short
    is allowed, as for a shot). In a scene render an overlay without a video is left out with a
    warning; in a full render it is returned as missing, and the plan refuses.
    """
    entries: list[dict[str, Any]] = []
    missing: list[str] = []
    for scene in scenes:
        if scene.story_start_s is None:
            continue
        for overlay in scene.overlays:
            start_ms = _ms(scene.story_start_s + overlay.start_s)
            end_ms = _ms(scene.story_start_s + overlay.end_s)
            start_frame = frame_at(start_ms, fps)
            frames = min(frame_at(end_ms, fps), total_frames) - start_frame
            if frames < 1:
                continue
            label = f"'{overlay.text}' of scene {scene.index}"
            graphic = overlay.graphic
            needed = source_frames_needed(frames, fps)
            if (
                graphic is None
                or not graphic.file_exists
                or graphic.frame_count is None
                or graphic.frame_count < needed - 1
            ):
                if not placeholders:
                    missing.append(label)
                    continue
                warnings.append(
                    {
                        "code": OVERLAY_WITHOUT_VIDEO,
                        "scene_id": scene.scene_id,
                        "shot_id": None,
                        "message": f"The graphic over {label} is left out: it has no video yet.",
                    }
                )
                continue
            entries.append(
                {
                    "id": f"{scene.scene_id}/{overlay.overlay_id}",
                    "scene_id": scene.scene_id,
                    "scene_index": scene.index,
                    "overlay_id": overlay.overlay_id,
                    "text": overlay.text,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "start_frame": start_frame,
                    "frames": frames,
                    "source_frames": needed,
                    "graphic_id": graphic.graphic_id,
                    "engine": graphic.engine,
                    "attempt": graphic.attempt,
                    "path": graphic.path,
                    "clip_frames": graphic.frame_count,
                    "x": overlay.x,
                    "y": overlay.y,
                    # Only an overlay drawn beside evidence has this key (OVL-007).
                    **({"split": True} if overlay.split else {}),
                }
            )
    return entries, missing


def _split_entries(
    scenes: list[SceneSource],
    fps: int,
    total_frames: int,
    *,
    placeholders: bool,
    warnings: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """The evidence beside graphic overlays as timeline entries (OVL-007), and the pieces that
    have no usable clip. Like a card, a piece only needs a frame range of the story and a clip
    with the frames that range needs (one short is allowed). In a scene render a piece without a
    clip is left out with a warning; in a full render it is returned as missing, and the plan
    refuses. A clip whose quote is too small to read gives a warning.
    """
    entries: list[dict[str, Any]] = []
    missing: list[str] = []
    for scene in scenes:
        if scene.story_start_s is None:
            continue
        for piece in scene.splits:
            start_ms = _ms(scene.story_start_s + piece.start_s)
            end_ms = _ms(scene.story_start_s + piece.end_s)
            start_frame = frame_at(start_ms, fps)
            frames = min(frame_at(end_ms, fps), total_frames) - start_frame
            if frames < 1:
                continue
            label = f"beside a graphic in scene {scene.index} ({piece.segment_id})"
            clip = piece.clip
            needed = source_frames_needed(frames, fps)
            if (
                clip is None
                or not clip.file_exists
                or clip.frame_count is None
                or clip.frame_count < needed - 1
            ):
                if not placeholders:
                    missing.append(label)
                    continue
                warnings.append(
                    {
                        "code": SPLIT_WITHOUT_VIDEO,
                        "scene_id": scene.scene_id,
                        "shot_id": None,
                        "message": f"The evidence {label} is left out: it has no clip yet.",
                    }
                )
                continue
            if clip.small_text is not None:
                warnings.append(
                    {
                        "code": SPLIT_SMALL_TEXT,
                        "scene_id": scene.scene_id,
                        "shot_id": None,
                        "message": f"The evidence {label} is hard to read at half the screen. "
                        f"{clip.small_text}",
                    }
                )
            entries.append(
                {
                    "id": f"{scene.scene_id}/{piece.segment_id}",
                    "scene_id": scene.scene_id,
                    "scene_index": scene.index,
                    "segment_id": piece.segment_id,
                    "claim_id": piece.claim_id,
                    "item_key": piece.item_key,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "start_frame": start_frame,
                    "frames": frames,
                    "source_frames": needed,
                    "clip_id": clip.clip_id,
                    "path": clip.path,
                    "clip_frames": clip.frame_count,
                    "x": 0,
                    "y": 0,
                }
            )
    return entries, missing


def _overlay_evidence_warnings(
    overlays: list[dict[str, Any]],
    cards: list[dict[str, Any]],
    shots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """One warning for each overlay that covers an evidence card or a full-screen evidence shot:
    the graphic is on top. An overlay drawn beside the evidence (`split`, OVL-007) covers none.
    """
    covered = [(card["start_ms"], card["end_ms"]) for card in cards]
    covered.extend(
        (shot["start_ms"], shot["end_ms"])
        for shot in shots
        if isinstance(shot.get("evidence"), dict) and shot["evidence"].get("layout") != "split"
    )
    warnings: list[dict[str, Any]] = []
    for overlay in overlays:
        if overlay.get("split"):
            continue
        if any(low < overlay["end_ms"] and overlay["start_ms"] < high for low, high in covered):
            warnings.append(
                {
                    "code": OVERLAY_OVER_EVIDENCE,
                    "scene_id": overlay["scene_id"],
                    "shot_id": None,
                    "message": f"The graphic over '{overlay['text']}' of scene "
                    f"{overlay['scene_index']} covers evidence. The graphic is shown on top.",
                }
            )
    return warnings


def _source_line_entries(scenes: list[SceneSource]) -> list[dict[str, Any]]:
    """The source lines of the scenes as timeline entries (EVD-012), in story order."""
    entries: list[dict[str, Any]] = []
    for scene in scenes:
        if scene.story_start_s is None:
            continue
        for line in scene.source_lines:
            entries.append(
                {
                    "scene_id": scene.scene_id,
                    "claim_id": line.claim_id,
                    "item_key": line.item_key,
                    "start_ms": _ms(scene.story_start_s + line.start_s),
                    "end_ms": _ms(scene.story_start_s + line.end_s),
                    "text": line.text,
                }
            )
    return entries


def _build(
    scenes: list[SceneSource],
    *,
    fps: int,
    width: int,
    height: int,
    mix: MixSettings | None,
    music: MusicSource | None,
    captions: caption_plan.CaptionStyle | None,
    captions_burned: bool,
    callouts: callout_render.CalloutSource | None,
    measure: callout_render.Measure | None,
    placeholders: bool,
    first_frame: int,
    short_clips_as_placeholders: bool = False,
    sound_effects: SoundEffectSource | None = None,
) -> RenderPlan:
    """What `build_plan` and `build_scene_plan` share. With `placeholders` (a scene render), a shot
    without a clip or graphic gets a placeholder instead of refusing the plan, and a line of
    dialogue whose shots are all placeholders is played from its own speech file. The first shot
    starts on frame `first_frame` (0 for a whole story, the scene's first frame for a scene).
    """
    mix = mix or MixSettings()
    if fps < 1 or width < 2 or height < 2:
        raise RenderPlanError("The project's output size or frame rate is not usable.")
    _check_scenes(scenes)
    _check_takes(scenes, placeholders=placeholders)

    shots: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    too_short: list[str] = []
    graphics_too_short: list[str] = []
    evidence_too_short: list[str] = []
    bites_too_short: list[str] = []
    # The graphic and the evidence shots, in ms: no callout is on screen over them. The evidence
    # shots drawn split (EVD-016) are apart: a callout may start in them.
    graphic_spans: list[tuple[int, int]] = []
    split_spans: list[tuple[int, int]] = []
    # The sound bite shots (SB-008): no callout is on screen over a real person's clip either, but
    # the warning for a callout left out says so in its own words.
    bite_spans: list[tuple[int, int]] = []
    # The same shots with their clip played (SB-009): `(start_s, end_s, music_drop)`, story seconds.
    bite_windows_story: list[tuple[float, float, bool]] = []
    warned_bites: set[str] = set()
    narration: list[dict[str, Any]] = []
    narration_spans: list[tuple[float, float]] = []
    dialogue_spans: list[tuple[float, float]] = []
    unplaced: list[str] = []
    timed_units: list[caption_plan.TimedUnit] = []
    callout_units: list[callout_render.CalloutUnit] = []
    estimated_units: list[str] = []
    voice_spans: list[tuple[float, float]] = []  # the units' spans of a continuous explainer
    presenter_spans: list[tuple[int, int]] = []  # the presenter shots, in ms
    clip_spans: dict[str, list[tuple[int, int]]] = {}  # by scene: shots on their own voice, samples
    silent_clips: list[str] = []
    cursor = first_frame  # the frame the last shot ended on
    continuous = any(scene.voice is not None for scene in scenes)
    if continuous:
        for scene in scenes:
            if scene.voice is None:
                raise RenderPlanError(f"{_scene_label(scene)} has no voice take.")
            if not scene.voice.file_exists:
                raise RenderPlanError(
                    f"The voice take of {_scene_label(scene)} is missing. Make the take again."
                )

    for scene in scenes:
        assert scene.story_start_s is not None  # `_check_scenes` made sure
        # The shots of this scene that have nothing to show yet (a scene render only).
        stand_ins: dict[str, str] = {}
        # The sound bite shots of this scene, which the narrator's words are not heard in.
        scene_bites = [candidate for candidate in scene.shots if candidate.is_soundbite]
        bite_windows = [(candidate.start_s, candidate.end_s) for candidate in scene_bites]
        if placeholders:
            for candidate in scene.shots:
                found = placeholder_reason(candidate)
                if found is not None:
                    stand_ins[candidate.shot_id] = found
        for position, shot in enumerate(scene.shots, start=1):
            take = shot.take
            graphic = shot.graphic
            start_ms = _ms(scene.story_start_s + shot.start_s)
            end_ms = _ms(scene.story_start_s + shot.end_s)
            start_frame = cursor
            end_frame = frame_at(end_ms, fps)
            frames = end_frame - start_frame
            cursor = end_frame
            label = f"{shot.shot_id} of scene {scene.index}"
            if frames < 1:
                raise RenderPlanError(f"The shot {label} lasts less than one frame.")
            if shot.is_soundbite:
                bite_spans.append((start_ms, end_ms))
            needed = source_frames_needed(frames, fps)
            if short_clips_as_placeholders and shot.shot_id not in stand_ins:
                # One source frame short is allowed, as below.
                available = shot.drawn.frame_count if shot.drawn else None
                if not shot.is_drawn and take is not None:
                    available = take.frame_count
                if available is None or available < needed - 1:
                    stand_ins[shot.shot_id] = (
                        PLACEHOLDER_GRAPHIC_TOO_SHORT
                        if shot.is_graphic
                        else PLACEHOLDER_EVIDENCE_TOO_SHORT
                        if shot.is_evidence
                        else PLACEHOLDER_SOUNDBITE_TOO_SHORT
                        if shot.is_soundbite
                        else PLACEHOLDER_CLIP_TOO_SHORT
                    )
            if shot.shot_id in stand_ins:
                if shot.is_drawn and not shot.is_soundbite:
                    graphic_spans.append((start_ms, end_ms))
                shots.append(
                    {
                        "scene_id": scene.scene_id,
                        "shot_id": shot.shot_id,
                        "scene_index": scene.index,
                        "start_ms": start_ms,
                        "end_ms": end_ms,
                        "start_frame": start_frame,
                        "frames": frames,
                        "take_id": None,
                        "take_number": None,
                        "path": None,
                        "source_frames": needed,
                        "has_audio": False,
                        "voice": None,
                        "voice_window": None,
                        "duck": [],
                        "bed_duck": [],
                        "placeholder": {
                            "reason": stand_ins[shot.shot_id],
                            "position": position,
                            "shot_count": len(scene.shots),
                            "description": shot.description,
                            "seconds": round(frames / fps, 3),
                        },
                        # Which clip the shot waits for and how long it plays, so a scene render
                        # can tell that a new cut changed it (SB-008).
                        **(
                            {
                                "soundbite": {
                                    "claim_id": shot.soundbite.claim_id,
                                    "item_key": shot.soundbite.item_key,
                                    "seconds": shot.soundbite.seconds,
                                }
                            }
                            if shot.soundbite is not None
                            else {}
                        ),
                    }
                )
                warnings.append(
                    {
                        "code": SHOT_PLACEHOLDER,
                        "scene_id": scene.scene_id,
                        "shot_id": shot.shot_id,
                        "message": f"The shot {label} shows a placeholder: "
                        f"{stand_ins[shot.shot_id].lower()}.",
                    }
                )
                continue
            if shot.drawn is not None:
                source_frame_count = shot.drawn.frame_count
            else:
                assert take is not None  # `_check_takes` made sure
                source_frame_count = take.frame_count
            # One source frame short is allowed: the render repeats the last frame (D-9).
            if source_frame_count is None or source_frame_count < needed - 1:
                have = (
                    "an unreadable number of" if source_frame_count is None else source_frame_count
                )
                (
                    graphics_too_short
                    if shot.is_graphic
                    else evidence_too_short
                    if shot.is_evidence
                    else bites_too_short
                    if shot.is_soundbite
                    else too_short
                ).append(f"{label} has {have} frames, needs {needed}")
            if shot.is_soundbite:
                # A real person's clip with its own sound (SB-009). The narrator's take is cut out
                # under it (SB-008), so nothing is ducked: the clip is heard whole, brought to the
                # narrator's level by the render, and the music is made room for below.
                assert shot.soundbite is not None and shot.soundbite.clip is not None
                clip = shot.soundbite.clip
                bite_windows_story.append(
                    (
                        start_ms / _MS_PER_S,
                        end_ms / _MS_PER_S,
                        clip.music_drop,
                    )
                )
                if captions is not None and clip.words:
                    timed_units.append(
                        caption_plan.TimedUnit(
                            scene_id=scene.scene_id,
                            unit_id=f"soundbite:{shot.shot_id}",
                            audio_id=clip.clip_id,
                            start_ms=start_ms,
                            words=clip.words,
                            colour=clip.colour,
                        )
                    )
                shots.append(
                    {
                        "scene_id": scene.scene_id,
                        "shot_id": shot.shot_id,
                        "scene_index": scene.index,
                        "start_ms": start_ms,
                        "end_ms": end_ms,
                        "start_frame": start_frame,
                        "frames": frames,
                        "take_id": None,
                        "take_number": None,
                        "path": clip.path,
                        "source_frames": needed,
                        "has_audio": True,
                        "voice": None,
                        "voice_window": None,
                        "duck": [],
                        "bed_duck": [],
                        "soundbite": {
                            "clip_id": clip.clip_id,
                            "claim_id": shot.soundbite.claim_id,
                            "item_key": shot.soundbite.item_key,
                            "seconds": shot.soundbite.seconds,
                            "music_drop": clip.music_drop,
                            "take_window": (
                                None
                                if clip.take_window is None
                                else {"start_s": clip.take_window[0], "end_s": clip.take_window[1]}
                            ),
                        },
                    }
                )
                continue
            if shot.is_evidence:
                # Like a graphic: no sound and no take, the voice take plays over it, and callouts
                # stay off it (EVD-009).
                evidence = shot.evidence
                assert evidence is not None  # `_check_takes` made sure
                (split_spans if evidence.split else graphic_spans).append((start_ms, end_ms))
                shots.append(
                    {
                        "scene_id": scene.scene_id,
                        "shot_id": shot.shot_id,
                        "scene_index": scene.index,
                        "start_ms": start_ms,
                        "end_ms": end_ms,
                        "start_frame": start_frame,
                        "frames": frames,
                        "take_id": None,
                        "take_number": None,
                        "path": evidence.path,
                        "source_frames": needed,
                        "has_audio": False,
                        "voice": None,
                        "voice_window": None,
                        "duck": [],
                        "bed_duck": [],
                        "evidence": {
                            "clip_id": evidence.clip_id,
                            **({"layout": "split"} if evidence.split else {}),
                        },
                    }
                )
                continue
            if shot.is_graphic:
                # A graphic has no sound and no take: the voice take plays over it, as over
                # B-roll, and callouts stay off it (EXG-007).
                assert graphic is not None
                graphic_spans.append((start_ms, end_ms))
                shots.append(
                    {
                        "scene_id": scene.scene_id,
                        "shot_id": shot.shot_id,
                        "scene_index": scene.index,
                        "start_ms": start_ms,
                        "end_ms": end_ms,
                        "start_frame": start_frame,
                        "frames": frames,
                        "take_id": None,
                        "take_number": None,
                        "path": graphic.path,
                        "source_frames": needed,
                        "has_audio": False,
                        "voice": None,
                        "voice_window": None,
                        "duck": [],
                        "bed_duck": [],
                        "graphic": {
                            "id": graphic.graphic_id,
                            "engine": graphic.engine,
                            "attempt": graphic.attempt,
                        },
                    }
                )
                continue
            assert take is not None
            # What this shot's sound is in a continuous explainer (FLOW-008).
            voice_of_shot: str | None = None
            if scene.voice is not None and shot.presenter:
                voice_of_shot = VOICE_CLIP if shot.clip_voice else VOICE_TAKE
            if voice_of_shot is not None:
                presenter_spans.append((start_ms, end_ms))
            if voice_of_shot == VOICE_CLIP:
                clip_spans.setdefault(scene.scene_id, []).append(
                    (
                        render_commands.sample_count(start_frame, fps),
                        render_commands.sample_count(end_frame, fps),
                    )
                )
                if not take.has_audio:
                    silent_clips.append(label)
            if take.reasons:
                warnings.append(
                    {
                        "code": TAKE_OUT_OF_DATE,
                        "scene_id": scene.scene_id,
                        "shot_id": shot.shot_id,
                        "message": f"The shot {label} uses take {take.take_number}, which is "
                        f"out of date: {' '.join(take.reasons)}",
                    }
                )
            if not take.has_audio and voice_of_shot != VOICE_TAKE:
                warnings.append(
                    {
                        "code": TAKE_WITHOUT_SOUND,
                        "scene_id": scene.scene_id,
                        "shot_id": shot.shot_id,
                        "message": f"The clip of the shot {label} (take {take.take_number}) "
                        "has no sound, so the shot is silent.",
                    }
                )
            shots.append(
                {
                    "scene_id": scene.scene_id,
                    "shot_id": shot.shot_id,
                    "scene_index": scene.index,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "start_frame": start_frame,
                    "frames": frames,
                    "take_id": take.take_id,
                    "take_number": take.take_number,
                    "path": take.path,
                    "source_frames": needed,
                    "has_audio": take.has_audio,
                    "voice": voice_of_shot,
                    "voice_window": None,  # filled in below, for a shot on its clip's voice
                    "duck": [],  # filled in below, once every narration span is known
                    "bed_duck": [],  # and every bed
                }
            )
        for unit in scene.units:
            start_s = scene.story_start_s + unit.start_s
            end_s = scene.story_start_s + unit.end_s
            # Captions and callouts follow the speech of a narration and of a line of dialogue
            # alike. A line of dialogue is in its clip at the place its unit has on the timeline.
            timing = (
                unit.timing
                if unit.timing is not None and unit.audio_id is not None and unit.file_exists
                else None
            )
            if captions is not None and timing is not None:
                assert unit.audio_id is not None
                # The narrator's words under a sound bite's clip are not heard, so they are not
                # captioned either (SB-008).
                caption_words = _words_outside(timing.words, unit.start_s, bite_windows)
                if len(caption_words) < len(timing.words):
                    for bite in scene_bites:
                        if bite.shot_id not in warned_bites and any(
                            bite.start_s < unit.start_s + (word[1] + word[2]) / 2 < bite.end_s
                            for word in timing.words
                        ):
                            warned_bites.add(bite.shot_id)
                            warnings.append(
                                {
                                    "code": SOUNDBITE_CAPTIONS_DROPPED,
                                    "scene_id": scene.scene_id,
                                    "shot_id": bite.shot_id,
                                    "message": f"The words of the sound bite shot {bite.shot_id} "
                                    f"of scene {scene.index} are left out of the captions: the "
                                    "clip plays there, not the narrator.",
                                }
                            )
                if caption_words or not timing.words:
                    timed_units.append(
                        caption_plan.TimedUnit(
                            scene_id=scene.scene_id,
                            unit_id=unit.unit_id,
                            audio_id=unit.audio_id,
                            start_ms=_ms(start_s),
                            words=caption_words,
                        )
                    )
                if timing.estimated_now:
                    estimated_units.append(f"{unit.unit_id} of scene {scene.index}")
            if callouts is not None:
                callout_units.append(
                    callout_render.CalloutUnit(
                        scene_id=scene.scene_id,
                        unit_id=unit.unit_id,
                        start_ms=_ms(start_s),
                        end_ms=_ms(end_s),
                        words=timing.words if timing is not None else (),
                    )
                )
            if scene.voice is not None:
                # The voice is the scene's take: no unit has a speech of its own.
                voice_spans.append((start_s, end_s))
                continue
            if unit.kind == "dialogue":
                dialogue_spans.append((start_s, end_s))
                covered = [shot_id for shot_id in unit.shot_ids if shot_id in stand_ins]
                if not covered:
                    continue
                if (
                    len(covered) == len(unit.shot_ids)
                    and unit.audio_id is not None
                    and unit.path is not None
                    and unit.seconds is not None
                    and unit.file_exists
                ):
                    # Every shot that carries the line is a placeholder: its recorded speech is
                    # played at its place, so the timing can be judged (SCN-003).
                    narration.append(
                        {
                            "scene_id": scene.scene_id,
                            "unit_id": unit.unit_id,
                            "audio_id": unit.audio_id,
                            "path": unit.path,
                            "start_ms": _ms(start_s),
                            "seconds": unit.seconds,
                            "stand_in": True,
                        }
                    )
                else:
                    warnings.append(
                        {
                            "code": DIALOGUE_NOT_HEARD,
                            "scene_id": scene.scene_id,
                            "shot_id": None,
                            "message": f"The line {unit.unit_id} of scene {scene.index} is "
                            "spoken inside a clip that is not there yet, so it is not heard.",
                        }
                    )
                continue
            if unit.audio_id is None or unit.path is None or unit.seconds is None:
                unplaced.append(f"{unit.unit_id} of scene {scene.index}")
                continue
            if not unit.file_exists:
                unplaced.append(f"{unit.unit_id} of scene {scene.index}")
                continue
            narration_spans.append((start_s, end_s))
            narration.append(
                {
                    "scene_id": scene.scene_id,
                    "unit_id": unit.unit_id,
                    "audio_id": unit.audio_id,
                    "path": unit.path,
                    "start_ms": _ms(start_s),
                    "seconds": unit.seconds,
                }
            )

    if silent_clips:
        raise RenderPlanError(
            f"The clip of these shots has no sound, so it cannot be their voice: "
            f"{_named(silent_clips)}. Switch them back to the take's voice, or select another take."
        )
    if too_short:
        raise RenderPlanError(
            f"A clip is shorter than its shot: {_named(too_short)}. Regenerate it, or select "
            "another take."
        )
    if graphics_too_short:
        raise RenderPlanError(
            f"A graphic is shorter than its shot: {_named(graphics_too_short)}. Plan the shots "
            "again, then make the graphics again."
        )
    if evidence_too_short:
        raise RenderPlanError(
            f"An evidence clip is shorter than its shot: {_named(evidence_too_short)}. Plan the "
            "shots again, then draw the evidence shots again."
        )
    if bites_too_short:
        raise RenderPlanError(
            f"A sound bite clip is shorter than its shot: {_named(bites_too_short)}. Make the "
            "evidence clips again."
        )
    if unplaced:
        raise RenderPlanError(
            f"The speech of these narration units is missing: {_named(unplaced)}. Make it again."
        )

    windows = duck_windows([*narration_spans, *voice_spans], dialogue_spans, DUCK_MERGE_GAP_S)
    for shot_entry in shots:
        if shot_entry["voice"] is not None or "soundbite" in shot_entry:
            continue  # a presenter shot's sound is dropped, or is the voice itself, or a bite
        shot_entry["duck"] = slice_windows(
            windows,
            shot_entry["start_frame"] / fps,
            (shot_entry["start_frame"] + shot_entry["frames"]) / fps,
            DUCK_RAMP_S,
        )

    scene_edge_fades(shots, dialogue_spans)

    voice_entry: dict[str, Any] | None = None
    if continuous:
        voice_entry = _voice_entry(scenes, clip_spans, shots, fps, cursor)

    music_entry: dict[str, Any] | None = None
    if music is not None:
        music_entry, bed_spans = _music_timeline(
            music,
            mix,
            [*narration_spans, *voice_spans, *dialogue_spans],
            dialogue_spans,
            render_commands.sample_count(cursor, fps),
            bite_windows_story,
            explainer=continuous,
        )
        drops = sum(1 for _start, _end, dropped in bite_windows_story if dropped)
        if not placeholders and drops * 600 > BITE_MAX_DROPS_PER_10_MIN * cursor / fps:
            warnings.append(
                {
                    "code": SOUNDBITE_MUSIC_DROPS,
                    "message": f"The music is switched off under {drops} sound bites in "
                    f"{cursor / fps / 60:.1f} minutes. More than {BITE_MAX_DROPS_PER_10_MIN} "
                    "in ten minutes can feel choppy.",
                }
            )
        if mix.bed_shot_duck_db < 0:
            # The video model's own sound is lowered under a bed, but never in a line of dialogue.
            lowered = subtract_spans(bed_spans, dialogue_spans)
            for shot_entry in shots:
                if shot_entry["voice"] is not None or "soundbite" in shot_entry:
                    continue
                shot_entry["bed_duck"] = slice_windows(
                    lowered,
                    shot_entry["start_frame"] / fps,
                    (shot_entry["start_frame"] + shot_entry["frames"]) / fps,
                    BED_SHOT_RAMP_S,
                )

    # The evidence cards (EVD-011) are laid over the shots: a callout stays off them, as off a
    # graphic or an evidence shot. The source lines (EVD-012) sit in the top margin.
    card_entries, cards_missing = _card_entries(
        scenes, fps, cursor, placeholders=placeholders, warnings=warnings
    )
    if cards_missing:
        raise RenderPlanError(
            f"These evidence cards have no clip yet: {_named(cards_missing)}. Draw the evidence "
            "shots first (the step makes the cards too)."
        )
    graphic_spans.extend((entry["start_ms"], entry["end_ms"]) for entry in card_entries)
    # The graphic overlays (OVL-005) are laid over the shots and the cards: a callout stays off
    # them too.
    overlay_entries, overlays_missing = _overlay_entries(
        scenes, fps, cursor, placeholders=placeholders, warnings=warnings
    )
    if overlays_missing:
        raise RenderPlanError(
            f"These graphics over your words have no video yet: {_named(overlays_missing)}. "
            "Make them in the Graphics step."
        )
    graphic_spans.extend((entry["start_ms"], entry["end_ms"]) for entry in overlay_entries)
    # The evidence beside a graphic (OVL-007): a split stretch has no room for a callout either.
    split_entries, splits_missing = _split_entries(
        scenes, fps, cursor, placeholders=placeholders, warnings=warnings
    )
    if splits_missing:
        raise RenderPlanError(
            f"This evidence beside a graphic has no clip yet: {_named(splits_missing)}. Draw it "
            "in the Evidence clips step."
        )
    graphic_spans.extend((entry["start_ms"], entry["end_ms"]) for entry in split_entries)
    warnings.extend(_overlay_evidence_warnings(overlay_entries, card_entries, shots))
    source_line_entries = _source_line_entries(scenes)

    # The sound effects (EXM-007): by code, on the first frame of each graphic and evidence moment.
    sound_effects_entry: dict[str, Any] | None = None
    if sound_effects is not None:
        sound_effects_entry = _sound_effects_entry(
            sound_effects,
            _sound_moments(shots, card_entries, overlay_entries),
            bite_spans=bite_spans,
            fps=fps,
            window_start=render_commands.sample_count(first_frame, fps),
            window_end=render_commands.sample_count(cursor, fps),
            placeholders=placeholders,
            warnings=warnings,
        )

    total_ms = _ms(cursor / fps)
    callouts_entry: dict[str, Any] | None = None
    hidden: list[tuple[int, int]] = []
    if callouts is not None:
        resolution = callout_render.resolve(
            callouts,
            callout_units,
            [(entry["start_ms"], entry["end_ms"]) for entry in shots],
            # The presenter is on camera in a presenter shot of a continuous explainer, whatever
            # unit label its words have.
            presenter_spans if continuous else [(_ms(s), _ms(e)) for s, e in dialogue_spans],
            total_ms,
            width,
            height,
            measure or font_metrics.measure,
            graphics=graphic_spans,
            splits=split_spans,
            bites=bite_spans,
        )
        callouts_entry = callout_render.track_dict(resolution.track)
        callouts_entry["plan_id"] = callouts.plan_id
        callouts_entry["plan_version"] = callouts.plan_version
        callouts_entry["callout_style"] = callouts.callout_style
        callouts_entry["look"] = _version_ref(callouts.look)
        callouts_entry["theme"] = _version_ref(callouts.theme)
        warnings.extend(resolution.warnings)
        hidden = callout_render.windows_hiding_captions(resolution.track)

    captions_entry: dict[str, Any] | None = None
    if captions is not None:
        groups = caption_plan.hide_during(
            caption_plan.build_captions(timed_units, captions, total_ms), hidden
        )
        captions_entry = caption_plan.track_dict(captions, groups, burned=captions_burned)
        captions_entry["estimated_units"] = estimated_units
        if estimated_units:
            warnings.append(
                {
                    "code": CAPTION_TIMING_ESTIMATED,
                    "message": "The words of these speeches are not timed yet, so their captions "
                    f"use estimated times: {_named(estimated_units)}.",
                }
            )

    timeline: dict[str, Any] = {
        "version": TIMELINE_VERSION,
        "fps": fps,
        "width": width,
        "height": height,
        "total_frames": cursor,
        "scenes": [
            {
                "scene_id": scene.scene_id,
                "index": scene.index,
                "title": scene.title,
                "story_start_s": scene.story_start_s,
                "plan_id": scene.plan_id,
                "plan_version": scene.plan_version,
            }
            for scene in scenes
        ],
        "shots": shots,
        "narration": narration,
        "voice": voice_entry,
        "music": music_entry,
        "captions": captions_entry,
        "callouts": callouts_entry,
        # Only a render with evidence cards or source lines has these keys (EVD-011, EVD-012).
        **({"evidence_cards": card_entries} if card_entries else {}),
        **({"source_lines": source_line_entries} if source_line_entries else {}),
        # Only a render with graphic overlays has this key (OVL-005).
        **({"graphic_overlays": overlay_entries} if overlay_entries else {}),
        # Only a render with evidence beside a graphic has this key (OVL-007).
        **({"split_evidence": split_entries} if split_entries else {}),
        # Only a render of a project with sound effects has this key (EXM-007).
        **({"sound_effects": sound_effects_entry} if sound_effects_entry is not None else {}),
        "master": master(mix),
        "constants": {
            **constants(mix),
            **(bite_constants() if bite_windows_story else {}),
            **(explainer_constants(mix) if continuous and music_entry is not None else {}),
            **(sound_effect_constants() if sound_effects_entry is not None else {}),
        },
        "warnings": warnings,
    }
    return RenderPlan(timeline=timeline, warnings=warnings)


# --- One scene (SCN-003) --------------------------------------------------------------------

_UNREADABLE_MUSIC: Final = "The music placement is not one this version can render. Place again."


def _cut_fade(samples: int) -> dict[str, Any]:
    return {"samples": samples, "shape": "linear"}


def _music_in_window(music: MusicSource, window_start: int, window_end: int) -> MusicSource:
    """The music source with only what plays inside the window (samples of the story's own
    timeline). A sound that reaches over an edge is cut at it and fades there over
    `SCENE_MUSIC_FADE_S`; a sound inside keeps its own fades. Positions stay on the story's
    timeline: the scene plan shifts them with everything else. A placement this version cannot
    read is returned as it is, for the full builder to refuse.
    """
    content = music.content
    rate = content.get("sample_rate")
    placements = content.get("placements")
    if rate != render_commands.SAMPLE_RATE or not isinstance(placements, list):
        return music
    fade = round(SCENE_MUSIC_FADE_S * render_commands.SAMPLE_RATE)
    kept: list[dict[str, Any]] = []
    try:
        for placed in placements:
            start = int(placed["story_start_sample"])
            length = int(placed["length_samples"])
            if length < 1 or start + length <= window_start or start >= window_end:
                continue
            clipped = dict(placed)
            if start < window_start:
                cut = window_start - start
                clipped["story_start_sample"] = window_start
                clipped["source_in_sample"] = int(placed["source_in_sample"]) + cut
                clipped["length_samples"] = length - cut
                clipped["fade_in"] = _cut_fade(fade)
                start, length = window_start, length - cut
            if start + length > window_end:
                clipped["length_samples"] = window_end - start
                clipped["fade_out"] = _cut_fade(fade)
            kept.append(clipped)
    except (KeyError, TypeError, ValueError) as exc:
        raise RenderPlanError(_UNREADABLE_MUSIC) from exc
    start_s, end_s = window_start / rate, window_end / rate
    narrowed = {
        **content,
        "placements": kept,
        "h3_sounds": [
            item
            for item in content.get("h3_sounds") or []
            if start_s <= float(item["chosen_s"]) <= end_s
        ],
        "mix_requests": [
            item
            for item in content.get("mix_requests") or []
            if float(item["second"]) < end_s
            and float(item["second"]) + float(item["length_s"]) > start_s
        ],
    }
    return replace(music, content=narrowed)


def _shift_timeline(timeline: dict[str, Any], first_frame: int, fps: int) -> None:
    """Moves a timeline made from frame `first_frame` so that the scene starts at 0: frames by
    `first_frame` exactly, samples by the samples of those frames exactly, and milliseconds by
    the same time to the nearest millisecond. The duck, dip and bump windows are in the shot's
    or the sound's own time and do not move.
    """
    if first_frame == 0:
        return
    ms = _ms(first_frame / fps)
    samples = render_commands.sample_count(first_frame, fps)

    def earlier(value: int) -> int:
        return max(0, value - ms)

    timeline["total_frames"] -= first_frame
    for shot in timeline["shots"]:
        shot["start_frame"] -= first_frame
        shot["start_ms"] = earlier(shot["start_ms"])
        shot["end_ms"] = earlier(shot["end_ms"])
    for speech in timeline["narration"]:
        speech["start_ms"] = earlier(speech["start_ms"])

    voice = timeline["voice"]
    for take in (voice or {}).get("takes", []):
        take["start_ms"] = earlier(take["start_ms"])
        for piece in take["pieces"]:
            piece["start_sample"] = max(0, piece["start_sample"] - samples)

    total_samples = render_commands.sample_count(timeline["total_frames"], fps)
    music = timeline["music"]
    if music is not None:
        music["total_samples"] = total_samples
        for sound in music["sounds"]:
            sound["start_sample"] = max(0, sound["start_sample"] - samples)
            sound["length_samples"] = min(
                sound["length_samples"], total_samples - sound["start_sample"]
            )

    effects = timeline.get("sound_effects")
    if effects is not None:
        for effect in effects["entries"]:
            effect["start_sample"] = max(0, effect["start_sample"] - samples)
            effect["length_samples"] = min(
                effect["length_samples"], total_samples - effect["start_sample"]
            )
        effects["entries"] = [e for e in effects["entries"] if e["length_samples"] >= 1]

    captions = timeline["captions"]
    for group in (captions or {}).get("groups", []):
        group["start_ms"] = earlier(group["start_ms"])
        group["end_ms"] = earlier(group["end_ms"])
        for word in group["words"]:
            word["start_ms"] = earlier(word["start_ms"])
            word["end_ms"] = earlier(word["end_ms"])
    for card in timeline.get("evidence_cards", []):
        card["start_frame"] -= first_frame
        card["start_ms"] = earlier(card["start_ms"])
        card["end_ms"] = earlier(card["end_ms"])
    for overlay in timeline.get("graphic_overlays", []):
        overlay["start_frame"] -= first_frame
        overlay["start_ms"] = earlier(overlay["start_ms"])
        overlay["end_ms"] = earlier(overlay["end_ms"])
    for piece in timeline.get("split_evidence", []):
        piece["start_frame"] -= first_frame
        piece["start_ms"] = earlier(piece["start_ms"])
        piece["end_ms"] = earlier(piece["end_ms"])
    for line in timeline.get("source_lines", []):
        line["start_ms"] = earlier(line["start_ms"])
        line["end_ms"] = earlier(line["end_ms"])
    callouts = timeline["callouts"]
    for entry in (callouts or {}).get("entries", []):
        entry["start_ms"] = earlier(entry["start_ms"])
        entry["end_ms"] = earlier(entry["end_ms"])
        for part in entry["parts"]:
            part["start_ms"] = earlier(part["start_ms"])
        motion = entry.get("motion")
        if motion is not None:
            motion["part_starts_ms"] = [earlier(start) for start in motion["part_starts_ms"]]


def build_scene_plan(
    scene: SceneSource,
    *,
    fps: int,
    width: int,
    height: int,
    mix: MixSettings | None = None,
    music: MusicSource | None = None,
    captions: caption_plan.CaptionStyle | None = None,
    captions_burned: bool = True,
    callouts: callout_render.CalloutSource | None = None,
    measure: callout_render.Measure | None = None,
    sound_effects: SoundEffectSource | None = None,
) -> RenderPlan:
    """The frozen timeline of one scene's render, on the same timeline builder as the whole story
    (S-5): every shot, line, caption and callout is placed exactly as in the full render and the
    timeline is then moved so the scene's first frame is frame 0. A shot with no clip or graphic
    is a placeholder of its planned length. `music` is cut to the scene's window. Raises
    RenderPlanError with the reason when the scene cannot be rendered now.
    """
    if fps < 1 or width < 2 or height < 2:
        raise RenderPlanError("The project's output size or frame rate is not usable.")
    extra: list[dict[str, Any]] = []
    if scene.story_start_s is None and scene.blocked_reason is None and scene.shots:
        # A scene before this one has no plan, so its place in the story is unknown.
        scene = replace(scene, story_start_s=0.0)
        extra.append(
            {
                "code": SCENE_START_UNKNOWN,
                "scene_id": scene.scene_id,
                "shot_id": None,
                "message": "A scene before this one has no shot plan yet, so its place in the "
                "story is not known, so this render has no music and starts the scene at 0.",
            }
        )
    _check_scenes([scene])
    assert scene.story_start_s is not None  # `_check_scenes` made sure
    first_frame = frame_at(_ms(scene.story_start_s), fps)
    last_end_s = max(shot.end_s for shot in scene.shots)
    last_frame = frame_at(_ms(scene.story_start_s + last_end_s), fps)
    window_music = (
        _music_in_window(
            music,
            render_commands.sample_count(first_frame, fps),
            render_commands.sample_count(last_frame, fps),
        )
        if music is not None and not extra
        else None
    )
    plan = _build(
        [scene],
        fps=fps,
        width=width,
        height=height,
        mix=mix,
        music=window_music,
        captions=captions,
        captions_burned=captions_burned,
        callouts=callouts,
        measure=measure,
        placeholders=True,
        first_frame=first_frame,
        sound_effects=sound_effects,
    )
    _shift_timeline(plan.timeline, first_frame, fps)
    plan.warnings.extend(extra)
    return plan
