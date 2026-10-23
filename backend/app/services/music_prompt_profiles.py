"""What depends on the music model when an AI writes the prompt fields for the Music lab. Pure
data, no I/O.

Each of the five models wants a different kind of text: ACE-Step a short caption plus lyrics with
section tags, YuE2 a one-line style that starts with the language plus lyrics, Stable Audio 3
tagged descriptive prose, Stable Audio Open a short concrete sentence with a negative prompt, and
LTX audio a flowing description of a soundscape. A *music prompt profile* holds, for one model,
what the writer is told about it, one worked example and the checks that tell whether a written
prompt breaks the rules, the same idea as `lab_prompt_profiles.py` for the Video lab.

The rules come from the GPU server's own documentation of each endpoint (`GET /openapi.json`,
API 0.18.0: the `description` of every request field) and, where that says nothing (for example
how sparse a score under narration should be), from common music-prompting practice. They are a
starting point to be tuned by listening: that is what the lab is for. The job stores the
profile's id and version next to the exact request, so an earlier prompt can be compared with a
later one. Raise `version` whenever any text in a profile changes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Final

from app.services.music_models import MusicModel
from app.services.text_rules import TextRule

# The last line of the writer's instructions names the fields the answer has.
_ANSWER: Final = "Answer with one JSON object only, in exactly this form: "

# Added to the request, whatever the model, for a score that plays under the narration.
UNDER_NARRATION_RULE: Final = (
    "This piece plays underneath a spoken narration, so it must leave room for the voice: keep "
    "it sparse and steady, with soft dynamics, no busy or prominent lead melody, and nothing "
    "that crowds the middle of the frequency range where speech sits. It supports the mood "
    "without asking to be listened to."
)

# Tempo or key in an ACE-Step caption: they have fields of their own ("120 BPM", "in A minor").
_BPM_IN_TEXT = re.compile(r"\b\d{2,3}\s?bpm\b|\bbpm\s?[:=]?\s?\d{2,3}\b", re.IGNORECASE)
_KEY_IN_TEXT = re.compile(r"\b[A-G][#b\u266d]?[ -]?(?:major|minor)\b", re.IGNORECASE)
# Words that ask a model with no singing voice for vocals.
_VOCAL_WORDS = re.compile(r"\b(?:vocals?|singer|singing|sung|lyrics|choir|choral)\b", re.IGNORECASE)
# Words that ask for a song's worth of music inside a sound effect.
_MUSIC_WORDS = re.compile(r"\b(?:music|melody|song|beat|soundtrack|score)\b", re.IGNORECASE)


@dataclass(frozen=True)
class MusicPromptProfile:
    id: str
    # Raised by hand whenever any text below changes.
    version: int
    model: MusicModel
    # Named to the writer, so it knows what it is writing for.
    model_name: str
    # What the model is, in a sentence or two.
    intro: str
    # How to write the fields for this model.
    prompt_rules: str
    # One worked request (a brief) and its answer, from an unrelated story.
    example_inputs: dict[str, object]
    example_answer: str
    # What the writer is told the answer looks like (the last line of its instructions).
    answer_instruction: str
    # Warnings only, never errors: a field outside these ranges is still saved.
    rules: tuple[TextRule, ...] = ()


# --- ACE-Step 1.5 -------------------------------------------------------------------------

_ACE_EXAMPLE_INPUTS: Final[dict[str, object]] = {
    "kind": "song",
    "description": "A quiet closing song about leaving the village you grew up in.",
    "genre": ["folk"],
    "tone": ["wistful", "warm"],
    "era": "present day",
    "mood_start": "nostalgic",
    "mood_end": "hopeful",
    "duration_s": None,
    "under_narration": False,
    "lyrics_theme": "Packing one bag, the last walk past the school, a promise to come back.",
    "language": "English",
}

_ACE_EXAMPLE_ANSWER: Final = json.dumps(
    {
        "caption": (
            "wistful acoustic folk ballad, fingerpicked nylon guitar, soft upright bass, "
            "brushed snare, gentle female vocal with a warm breathy tone, close intimate "
            "recording, hopeful by the end"
        ),
        "lyrics": (
            "[Verse 1]\nOne bag by the kitchen door\nThe clock still ticks the same\n"
            "Mother pins a note inside\nAnd never says my name\n\n"
            "[Chorus - soft]\nI will carry you with me\nEvery road is home\n"
            "Light the window, leave it on\nI am not alone\n\n"
            "[Verse 2]\nPast the school and past the bridge\nThe river lets me go\n"
            "Every step a little lighter\nThan the last one, slow\n\n"
            "[Chorus - lifting]\nI will carry you with me\nEvery road is home\n"
            "Light the window, leave it on\nI will find my own\n\n"
            "[Outro]\nOoh, leave it on"
        ),
        "bpm": 72,
        "keyscale": "D major",
        "time_signature": "4",
        "duration": None,
        "vocal_language": "en",
    },
    ensure_ascii=False,
)

ACE_STEP: Final = MusicPromptProfile(
    id="ace-step-1.5",
    version=1,
    model="ace-step-1.5",
    model_name="ACE-Step 1.5",
    intro=(
        "ACE-Step 1.5 makes a full song with sung vocals, or an instrumental, from a caption "
        "and lyrics. It sings in 50+ languages and takes the tempo, key and length as exact "
        "fields."
    ),
    prompt_rules="\n".join(
        [
            "Rules for the fields:",
            "1. caption: one description, at most 512 characters (aim for 150 to 300), made of "
            "comma-separated parts: genre, mood, instruments and how they sound, timbre, era, "
            "production style and the vocal character (voice type, tone, delivery). For an "
            'instrumental say so ("instrumental, no vocals"). Never put the tempo or the key in '
            "the caption: they have their own fields.",
            "2. bpm, keyscale, time_signature: fill them from the mood and the genre. bpm is a "
            'whole number from 30 to 300, keyscale reads like "A minor" or "F# minor", '
            'time_signature is the text "2", "3", "4" or "6" (beats per bar). Use null for one '
            "only when it truly should be left to the model.",
            "3. duration: the requested length in seconds (10 to 600). Use null when the request "
            "names no length, and for a song with lyrics leave it null unless a length is "
            "requested: the model fits the length to the lyrics.",
            "4. lyrics, for a song: section tags on their own lines ([Intro], [Verse 1], "
            "[Pre-Chorus], [Chorus], [Bridge], [Outro], [Instrumental], [Guitar Solo]), a blank "
            "line between sections, and at most one modifier in a tag ([Chorus - anthemic], "
            "never two). About 6 to 10 syllables a line, so the lines sing naturally. At most "
            "4,000 characters. If the request supplies lyrics, keep its words and only add the "
            "tags and fix the line lengths. Otherwise write the lyrics from the theme, in the "
            "requested language.",
            "5. lyrics, for an instrumental (a score, or a stem, which is one instrument alone): "
            "write exactly [Instrumental].",
            "6. vocal_language: the short code of the sung language (en, zh, ja, ko, es, fr, de, "
            'pt, …), or "unknown" for an instrumental.',
            "7. Keep the caption and the lyrics consistent: the caption names a female vocal "
            "only if the lyrics are sung, and an instrumental caption never mentions vocals.",
        ]
    ),
    example_inputs=_ACE_EXAMPLE_INPUTS,
    example_answer=_ACE_EXAMPLE_ANSWER,
    answer_instruction=(
        _ANSWER + '{"caption": "...", "lyrics": "...", "bpm": 90, "keyscale": "A minor", '
        '"time_signature": "4", "duration": null, "vocal_language": "en"}'
    ),
    rules=(
        TextRule(
            _BPM_IN_TEXT,
            "The caption names a tempo. ACE-Step has the BPM field for it.",
        ),
        TextRule(
            _KEY_IN_TEXT,
            "The caption names a key. ACE-Step has the Key field for it.",
        ),
    ),
)

# --- YuE2 ---------------------------------------------------------------------------------

_YUE_EXAMPLE_INPUTS: Final[dict[str, object]] = {
    "kind": "song",
    "description": "A driving pop-rock theme for a heist crew's night-time getaway.",
    "genre": ["pop rock"],
    "tone": ["tense", "exhilarated"],
    "mood_start": "tense",
    "mood_end": "triumphant",
    "under_narration": False,
    "lyrics_theme": "Headlights off, the city asleep, nobody looks back.",
    "language": "English",
}

_YUE_EXAMPLE_ANSWER: Final = json.dumps(
    {
        "style": (
            "English, energetic pop rock, driving drums, palm-muted electric guitar, punchy "
            "bass, bright synth stabs, confident male voice with a slight rasp, anthemic hook, "
            "128 BPM"
        ),
        "lyrics": (
            "[Verse]\nHeadlights off on the empty street\nEvery shadow knows our names\n"
            "Counting seconds in the engine heat\nNobody here is playing games\n\n"
            "[Chorus]\nDon't look back, don't look back\nThe city sleeps and we are gone\n"
            "Don't look back, don't look back\nThe night belongs to us till dawn\n\n"
            "[Verse]\nCold coins singing in the seat\nA map of nothing on my knee\n"
            "Every mile a brand new beat\nRunning wild and running free\n\n"
            "[Chorus]\nDon't look back, don't look back\nThe city sleeps and we are gone\n"
            "Don't look back, don't look back\nThe night belongs to us till dawn"
        ),
    },
    ensure_ascii=False,
)

# What can start a YuE2 style line: the language first. The list is the common ones; another
# language only earns a warning, never a refusal.
_STYLE_LANGUAGES: Final = (
    "english|chinese|mandarin|cantonese|japanese|korean|spanish|french|german|portuguese|"
    "italian|russian|hindi|arabic"
)
_STYLE_STARTS_WITH_LANGUAGE = re.compile(rf"^\s*(?:{_STYLE_LANGUAGES})\b", re.IGNORECASE)

YUE2: Final = MusicPromptProfile(
    id="yue2",
    version=1,
    model="yue2",
    model_name="YuE2",
    intro=(
        "YuE2 makes a full song with sung vocals from a style line and lyrics. It is the "
        "backend for the best-sounding complete English or Chinese song. The song's length "
        "follows the lyrics, and there is no tempo field."
    ),
    prompt_rules="\n".join(
        [
            "Rules for the fields:",
            "1. style: one single line, at most 1,000 characters (aim for 100 to 250). The "
            "language comes first (English, Chinese, …), then the genre, the instruments, the "
            "vocal character (gender, timbre, delivery), the mood, and the tempo last, written "
            'as "88 BPM". The tempo goes here because YuE2 has no tempo field. No line breaks.',
            "2. lyrics: only the words to be sung, in the language named first in the style. "
            "Every part starts with a tag on its own line: [Verse], [Chorus] or [Bridge] (also "
            "[Intro] and [Outro] when wanted), and a blank line separates the parts. No other "
            "markup, no stage directions, no chords. At most 6,000 characters.",
            "3. The song's length follows the lyrics, so there is no duration to set: shape the "
            "length with the number of parts (more parts, a longer song). If the request names "
            "a length, plan the parts to fit it.",
            "4. Give every line a natural singing length, and repeat the chorus words exactly: "
            "a memorable repeated hook is what makes the song hold together. If the request "
            "supplies lyrics, keep its words and only add the tags and the blank lines.",
        ]
    ),
    example_inputs=_YUE_EXAMPLE_INPUTS,
    example_answer=_YUE_EXAMPLE_ANSWER,
    answer_instruction=_ANSWER + '{"style": "...", "lyrics": "..."}',
)

# --- Stable Audio 3 -----------------------------------------------------------------------

_SA3_EXAMPLE_INPUTS: Final[dict[str, object]] = {
    "kind": "score",
    "description": "Underscore for a detective walking through a rain-soaked city at night.",
    "genre": ["noir", "jazz"],
    "tone": ["lonely", "suspenseful"],
    "era": "1950s",
    "mood_start": "uneasy",
    "mood_middle": "searching",
    "mood_end": "resolved",
    "duration_s": 60,
    "under_narration": True,
}

_SA3_EXAMPLE_ANSWER: Final = json.dumps(
    {
        "prompt": (
            "TrackType: Music, VocalType: Instrumental, Genre: Jazz, Genre: Noir, Instruments: "
            "Double Bass, Brushed Drums, Muted Trumpet, Piano. A slow, smoky 1950s noir "
            "underscore at about 62 BPM. A walking double bass holds a soft, steady pulse under "
            "gently brushed drums. A muted trumpet enters sparingly with long, sighing notes, "
            "and a few sparse piano chords add an unresolved, uneasy colour that slowly "
            "settles toward a calmer ending. Low energy throughout, quiet and spacious, warm "
            "analogue tape sound with a little room reverb."
        ),
        "duration": 60,
    },
    ensure_ascii=False,
)

STABLE_AUDIO_3: Final = MusicPromptProfile(
    id="stable-audio-3",
    version=1,
    model="stable-audio-3",
    model_name="Stable Audio 3",
    intro=(
        "Stable Audio 3 makes instrumental music, stems, solo instruments and sound effects "
        "from a text prompt, up to 285 seconds, and it has no intelligible vocals. It works "
        "in 8 steps, and it has no negative prompt and no guidance setting."
    ),
    prompt_rules="\n".join(
        [
            "Rules for the fields:",
            "1. prompt: English, at most 2,000 characters. Start with metadata tags, then "
            "continue in descriptive prose.",
            "2. A music piece (a score) starts with tags: "
            '"TrackType: Music, VocalType: Instrumental, Genre: <genre>, Instruments: <list>." '
            "(Genre: can be repeated, Instruments: is a comma-separated list). Then describe the "
            "genre, each instrument and how it sounds and plays, the mood and energy and how "
            "they change, the BPM, and the production style (warm analogue, lo-fi, wide and "
            "cinematic, …).",
            '3. A stem or a solo instrument starts with "TrackType: Instrument". Name the one '
            "instrument and how it is played, and add nothing else: no band, no drums, no "
            "backing.",
            '4. A sound effect or an ambience starts with "TrackType: SFX". Say what makes the '
            "sound, how it is triggered, what surface or space it is in, and for how long. "
            "Keep it concrete and physical, and never ask for music.",
            "5. Never ask for singing, lyrics or a voice: there are no intelligible vocals.",
            "6. duration: seconds, at most 285. Pick the requested length when there is one. "
            "Otherwise pick one that fits the description: a sound effect wants a short "
            "duration (usually 1 to 10 seconds), an ambience 10 to 30, and a stem or a score "
            "as long as the request needs. Longer is not better.",
        ]
    ),
    example_inputs=_SA3_EXAMPLE_INPUTS,
    example_answer=_SA3_EXAMPLE_ANSWER,
    answer_instruction=_ANSWER + '{"prompt": "...", "duration": 30}',
    rules=(
        TextRule(
            _VOCAL_WORDS,
            "The prompt asks for vocals. Stable Audio 3 makes no intelligible vocals: use "
            "ACE-Step or YuE2 for a sung part.",
        ),
    ),
)

# --- Stable Audio Open --------------------------------------------------------------------

_SAO_EXAMPLE_INPUTS: Final[dict[str, object]] = {
    "kind": "sfx",
    "description": "A heavy wooden door being closed and locked in a stone corridor.",
    "place": "an old stone castle corridor",
    "duration_s": 6,
    "under_narration": False,
}

_SAO_EXAMPLE_ANSWER: Final = json.dumps(
    {
        "prompt": (
            "A heavy oak door swings shut in a stone corridor with a deep thud, followed by an "
            "iron key turning in a lock, large reverberant room."
        ),
        "negative_prompt": "Low quality, music, speech, noise.",
        "duration": 6,
    },
    ensure_ascii=False,
)

STABLE_AUDIO_OPEN: Final = MusicPromptProfile(
    id="stable-audio-open",
    version=1,
    model="stable-audio-open",
    model_name="Stable Audio Open 1.0",
    intro=(
        "Stable Audio Open makes a sound effect, a foley hit, a drum loop, an ambience or a short "
        "clip, up to 47 seconds, from a short English prompt. It is weak at long musical "
        "structure and makes no intelligible vocals."
    ),
    prompt_rules="\n".join(
        [
            "Rules for the fields:",
            "1. prompt: English, short and concrete, at most 1,000 characters (aim for 10 to 35 "
            "words). Name what makes the sound, what it is made of or hits, and the room or "
            'space. For a loop, give the tempo and the style first ("128 BPM tech house drum '
            'loop"). One or two sounds, not a whole scene.',
            "2. negative_prompt: a few words naming what to steer away from. Always include "
            '"Low quality." and add what the sound must not contain (for an effect: music, '
            "speech).",
            "3. duration: seconds, at most 47. Use the requested length when there is one. "
            "Otherwise a single effect is 2 to 8 seconds, and an ambience or a loop 10 to 30.",
            "4. Never ask for singing or a voice. Do not describe a story or a feeling: the "
            "model hears sounds, not meanings.",
        ]
    ),
    example_inputs=_SAO_EXAMPLE_INPUTS,
    example_answer=_SAO_EXAMPLE_ANSWER,
    answer_instruction=_ANSWER
    + '{"prompt": "...", "negative_prompt": "Low quality.", "duration": 8}',
    rules=(
        TextRule(
            _VOCAL_WORDS,
            "The prompt asks for vocals. Stable Audio Open makes no intelligible vocals.",
        ),
    ),
)

# --- LTX audio ----------------------------------------------------------------------------

_LTX_EXAMPLE_INPUTS: Final[dict[str, object]] = {
    "kind": "ambience",
    "description": "The sound of a quiet lighthouse keeper's kitchen on a stormy evening.",
    "place": "a small stone lighthouse kitchen",
    "mood_start": "cosy",
    "mood_end": "ominous",
    "duration_s": 15,
    "under_narration": True,
}

_LTX_EXAMPLE_ANSWER: Final = json.dumps(
    {
        "prompt": (
            "A cosy stone kitchen at the foot of a lighthouse on a stormy evening: a low wind "
            "moans around the walls, rain taps steadily on a small window, a kettle ticks as it "
            "cools on an iron stove, and now and then a distant wave booms against the rocks, "
            "growing slightly heavier toward the end."
        ),
        "negative_prompt": "music, speech, voices, distortion, clipping",
        "duration": 15,
    },
    ensure_ascii=False,
)

LTX_AUDIO: Final = MusicPromptProfile(
    id="ltx-audio",
    version=1,
    model="ltx-audio",
    model_name="LTX text-to-audio",
    intro=(
        "LTX text-to-audio makes a standalone sound effect or ambient soundscape (no video) from "
        "a flowing description."
    ),
    prompt_rules="\n".join(
        [
            "Rules for the fields:",
            "1. prompt: one flowing description in a single paragraph, in English. Name the "
            "place, then each sound source, what it is doing, how it changes over time and how "
            "it sounds (close or distant, soft or sharp, steady or occasional). Describe only "
            "what can be heard. About 30 to 80 words.",
            "2. negative_prompt: a short comma-separated list of what to steer away from (for "
            "an ambience or an effect: music, speech, voices, distortion).",
            "3. duration: seconds. Use the requested length when there is one, otherwise "
            "5 to 15 seconds.",
            "4. Do not ask for music or singing unless the request does.",
        ]
    ),
    example_inputs=_LTX_EXAMPLE_INPUTS,
    example_answer=_LTX_EXAMPLE_ANSWER,
    answer_instruction=_ANSWER + '{"prompt": "...", "negative_prompt": "...", "duration": 10}',
)

PROFILES: Final[dict[MusicModel, MusicPromptProfile]] = {
    "ace-step-1.5": ACE_STEP,
    "yue2": YUE2,
    "stable-audio-3": STABLE_AUDIO_3,
    "stable-audio-open": STABLE_AUDIO_OPEN,
    "ltx-audio": LTX_AUDIO,
}

# For the checks in `music_prompt_writer`: a sound effect or an ambience that talks about music.
MUSIC_WORDS: Final = _MUSIC_WORDS
STYLE_STARTS_WITH_LANGUAGE: Final = _STYLE_STARTS_WITH_LANGUAGE


def profile_for(model: MusicModel) -> MusicPromptProfile:
    return PROFILES[model]
