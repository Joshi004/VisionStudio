# Vision Studio — Proposed Story-to-Video Pipeline Architecture

## 1. Objective

We are evolving Vision Studio from a narration-driven video generator into an automated cinematic story-production system.

The final system should be able to accept a normal written story containing:

* narration,
* dialogue,
* actions,
* multiple characters,
* multiple environments,
* sound events,
* emotional changes,

and automatically turn it into a finished video.

We do not want the user to manually convert the story into a screenplay, scenes, shots, prompts, or timestamps.

The user should ideally provide something like:

```text
When Arjun moved into his new apartment, the landlord gave him only one strange warning.

“Whatever you hear at night, don’t go upstairs.”

Arjun laughed.

“There’s no upstairs.”

The landlord smiled awkwardly.

“Exactly.”

…

Then, at exactly 2:17 AM, Arjun heard footsteps above his bedroom.

Thump.

Pause.

Thump.

…

“Arjun?”

His blood went cold.

The voice sounded exactly like his mother.

…
```

The system should understand the story and progressively transform it into structured production artifacts.

The core principle is:

> We should not ask one LLM call to understand the story, design characters, divide scenes, create shots, determine timing, write H3 prompts, and direct the movie simultaneously.

Quality is the priority.

Therefore, we want a sequence of smaller, focused reasoning stages.

---

## 2. Core hierarchy

We should maintain a clear distinction between:

```text
Story
  ↓
Scene
  ↓
Event
  ↓
Speech Unit
  ↓
Shot
  ↓
Generation Request
```

Each level answers a different question.

### Story

What kind of world and story are we creating?

### Scene

Where, when, and under what continuous dramatic context is this part of the story happening?

### Event

What actually happens in the story?

Examples:

* narration,
* dialogue,
* character action,
* sound,
* meaningful silence.

### Speech Unit

What exact chunk of text will be synthesized into one audio asset?

### Shot

What does the audience actually see during a specific period?

### Generation Request

How do we instruct H3 to generate that particular shot?

These concepts must remain separate.

---

## 3. Important terminology

### Scene

A scene is a story-level continuity container.

Example:

```text
Scene:
Arjun's bedroom
2:17 AM
Arjun is awake waiting for the footsteps.
```

A scene may contain many H3-generated shots.

A scene is not itself necessarily a generated video.

---

### Event

An event describes what happens.

For example:

```text
Event 1:
Narration:
"At exactly 2:17 AM, Arjun heard footsteps above his bedroom."

Event 2:
Sound:
One heavy thump above the ceiling.

Event 3:
Action:
Arjun opens his eyes.

Event 4:
Sound:
Three rapid footsteps.
```

Events contain story truth.

They should normally contain no camera instructions.

---

### Shot

A shot describes what we show the viewer.

The four events above might become:

```text
Shot 1:
Close-up of clock showing 2:17.
Narration begins.

Shot 2:
Close-up of Arjun opening his eyes.
First thump is heard.

Shot 3:
Camera slowly tilts toward ceiling.
Three quick footsteps are heard.
```

Therefore:

```text
4 events
→ 3 shots
```

The reverse is also possible.

One narration event may become three visual shots.

This is why events and shots must remain separate objects.

---

## 4. Current model strategy

For now we want to standardize on MiniMax H3 for video generation.

We have experimentally verified that:

* H3 can generate clips anywhere from about one second up to about fifteen seconds,
* approximately two-second clips work reliably,
* one-second clips can also work, although they are somewhat less reliable,
* H3 performs well for regular visual generation,
* H3 performs well for character-conditioned generation,
* H3 Ref2VA performs well for speaking characters,
* H3 can use image, audio, and later video references.

Therefore, we do not currently need a multi-model video router.

We still need an H3 mode/conditioning router.

For example:

```text
Narration visual
→ H3 with visual references

Dialogue
→ H3 Ref2VA with character references + dialogue audio

Complex physical performance
→ H3 Ref2VA with character refs + optional motion video

Continuity shot
→ H3 with relevant previous-state references

Rapid back-and-forth exchange (reserved)
→ H3 multi-shot prompt with two character references + two dialogue audios
```

The rapid-exchange route is reserved for the specific scenarios where it is genuinely required. We have not yet tested passing two audio references and two image references extensively, so it is an exception rather than the normal way of handling dialogue.

### How speech and sound reach H3

H3 Ref2VA produces its own audio track.

Dialogue and narration are treated differently.

**Dialogue** is never invented by the model. We generate the line ourselves with TTS first, in the speaking character's voice, and then pass that audio to H3 as a reference in partial copy mode.

In this mode the supplied speech is carried into the clip, while the model remains free to generate additional audio around it.

We do not need to pad the dialogue audio to the length of the shot. H3 pads it automatically. If we supply two seconds of audio and ask for a five-second video, the model fills the remaining three seconds with expression and no sound.

The audio that comes back from H3 is used as it is. For a dialogue shot, it is the shot's final audio: the dialogue, plus whatever sound effects and ambience the model added.

**Narration** is never given to H3. Narration is a voice-over rather than something a character on screen is saying, and giving it to H3 risks characters appearing to speak it. Narration also often spans several shots, which makes it awkward to hand to individual clips. It stays a TTS audio layer that is placed directly on the timeline.

The additional audio H3 generates is welcome. Sound effects are a property of the shot, and H3 is allowed to generate them for each shot.

The one thing H3 should not generate is background music.

Music is continuous across shots and scenes, so it is produced separately and laid underneath the finished timeline.

### Shot duration limits

The hard boundary for a single H3 shot is **1 to 15 seconds**.

To stay safely away from the edges of that range, we ask the planning stages to produce shots that fit roughly **2 to 10 seconds**.

The 2–10 second range is a planning target with margin, not a guarantee, and it should be configurable rather than hard-coded into prompts.

If a shot still ends up outside the range, the system regenerates it systematically (see Shot Planning and Quality Validation) rather than relying on the planner to always be right.

---

## 5. Main architectural principle

We want to separate:

**DISCOVERY**

from:

**DEFINITION**

and both from:

**PRODUCTION**

For example:

Character Discovery answers:

> Who are the characters?

Character Definition answers:

> Exactly what does this particular character look and sound like?

Similarly:

Scene Discovery answers:

> What are the major scenes in the story?

Scene Definition answers:

> What is happening before, during, and after this scene? What is its emotional state, environment, cast, and dramatic purpose?

This separation allows each LLM call to focus on one coherent task.

---

## 6. Stage 1 — Story / World Bible

The first LLM call receives the complete raw script.

The system works in English only, so every story, narration line and dialogue line is in English.

Its purpose is to establish global creative consistency.

We can call the output:

`StoryBible`

It should contain information such as:

```json
{
  "title": "The Seventh Floor",
  "language": "en",
  "genre": [
    "supernatural horror",
    "psychological mystery"
  ],
  "tone": [
    "slow burn",
    "ominous",
    "increasingly disturbing"
  ],
  "visual_style": "photorealistic cinematic horror",
  "time_period": "present day",
  "storytelling_style": {
    "narration": "controlled storyteller whose tension increases gradually"
  },
  "world_rules": [
    "Supernatural events should initially appear plausible.",
    "The hidden seventh floor exists outside normal perception.",
    "The horror should remain grounded rather than fantastical."
  ]
}
```

This should remain relatively high level.

We should not define individual characters or shots here.

The StoryBible becomes shared context for later calls.

---

## 7. Stage 2 — Character Discovery

Next we make one dedicated LLM call whose only job is:

> Identify all meaningful characters.

Input:

```text
Raw Script
+
StoryBible
```

Output should remain intentionally minimal.

For our Arjun example:

```json
[
  {
    "id": "arjun",
    "name": "Arjun",
    "description": "Young adult protagonist who moves into the apartment."
  },
  {
    "id": "landlord",
    "name": "Landlord",
    "description": "Older landlord who knows more about the building than he initially reveals."
  },
  {
    "id": "meera",
    "name": "Meera",
    "description": "Arjun's mother, connected to the historical fire."
  },
  {
    "id": "young_arjun",
    "name": "Young Arjun",
    "description": "Six-year-old version of Arjun appearing during the supernatural revelation."
  }
]
```

We intentionally do not ask for:

* precise appearance,
* height,
* wardrobe,
* detailed voice,
* image prompts.

Those belong to Character Definition.

---

## 8. Stage 3 — Environment Discovery

A separate focused LLM call identifies reusable environments.

Input:

```text
Raw Script
+
StoryBible
```

Example output:

```json
[
  {
    "id": "old_building",
    "name": "Old Apartment Building",
    "description": "Aging multi-story residential building."
  },
  {
    "id": "arjun_apartment",
    "name": "Arjun's Apartment",
    "description": "Large, sparse apartment apparently located on the top floor."
  },
  {
    "id": "arjun_bedroom",
    "name": "Arjun's Bedroom",
    "description": "Bedroom where the supernatural events repeatedly occur."
  },
  {
    "id": "hidden_staircase",
    "name": "Hidden Staircase",
    "description": "Impossible staircase that appears outside Arjun's apartment."
  },
  {
    "id": "burned_seventh_floor",
    "name": "Burned Seventh Floor",
    "description": "Fire-damaged version of the original sealed seventh floor."
  },
  {
    "id": "childhood_bedroom",
    "name": "Childhood Bedroom",
    "description": "Arjun's childhood bedroom appearing during the final revelation."
  }
]
```

Again, this is discovery only.

---

## 9. Stage 4 — Scene Discovery

Once character and environment IDs exist, we identify the major scenes.

Input:

```text
Raw Script
+
StoryBible
+
Character IDs
+
Environment IDs
```

The result should remain small.

For example:

```json
[
  {
    "index": 1,
    "id": "scene_move_in",
    "title": "The Warning",
    "description": "Arjun moves into the apartment and receives the landlord's strange warning."
  },
  {
    "index": 2,
    "id": "scene_first_night",
    "title": "The First Footsteps",
    "description": "Arjun hears impossible footsteps at 2:17 AM for the first time."
  },
  {
    "index": 3,
    "id": "scene_second_night",
    "title": "Something Being Dragged",
    "description": "The footsteps return and are followed by the sound of something heavy being dragged."
  },
  {
    "index": 4,
    "id": "scene_landlord_revelation",
    "title": "The Seventh Floor",
    "description": "The landlord reveals that he considers Arjun to be living on the seventh floor."
  },
  {
    "index": 5,
    "id": "scene_mothers_voice",
    "title": "The Voice Above",
    "description": "The supernatural presence calls Arjun by name using his dead mother's voice."
  },
  {
    "index": 6,
    "id": "scene_building_records",
    "title": "The Fire",
    "description": "Arjun discovers that the building once had seven floors and that his mother died in the fire."
  },
  {
    "index": 7,
    "id": "scene_hidden_staircase",
    "title": "Come Upstairs",
    "description": "A hidden staircase appears and leads Arjun toward the burned seventh floor."
  },
  {
    "index": 8,
    "id": "scene_final_revelation",
    "title": "The Building Remembers",
    "description": "Arjun discovers that he himself died in the fire and repeatedly forgets what happened."
  }
]
```

At this point we have completed discovery.

---

## 10. Discovery stage summary

The global discovery sequence is:

```text
Raw Script
     ↓
Story Bible
     ↓
Character Discovery ─────┐
                         ├── can run independently
Environment Discovery ───┘
     ↓
Scene Discovery
```

We now know:

* what story we are making,
* who exists,
* where things happen,
* and what the major dramatic sections are.

We have deliberately not attempted detailed generation yet.

---

## 11. Stage 5 — Character Definition

We now make one independent LLM call per discovered character.

Each call receives:

```text
Raw Script
StoryBible
Current Character
Other Character List
```

Its job is to create a stable reusable character definition.

For Arjun:

```json
{
  "id": "arjun",
  "visual_identity": {
    "apparent_age": 27,
    "sex": "male",
    "build": "lean",
    "height_character": "average-tall",
    "skin_tone": "...",
    "face_shape": "...",
    "hair": "...",
    "eyes": "...",
    "distinctive_features": "..."
  },
  "default_wardrobe": {
    "upper": "...",
    "lower": "...",
    "footwear": "..."
  },
  "voice_identity": {
    "age_character": "late twenties",
    "pitch": "medium",
    "texture": "natural and slightly warm",
    "accent": "neutral Indian English",
    "default_energy": "moderate"
  },
  "behavior": {
    "baseline": "rational, skeptical and curious",
    "gesture_style": "restrained"
  }
}
```

We already have a character-definition system inside Vision Studio.

Therefore the next process is:

```text
Character Definition
       ↓
Character Image Prompt
       ↓
Generate candidate images
       ↓
Choose canonical character
       ↓
Generate additional character views
       ↓
Store Character Asset
```

The `voice_identity` is not just descriptive text. In the same step that we define how the character looks, we also use it to derive the character's TTS voice.

```text
Character Definition
       ↓
voice_identity
       ↓
Derive TTS voice (voice design from the description)
       ↓
Store voice as part of the Character Asset
```

That voice is stored with the character and becomes the reference for every line the character speaks.

Dialogue is therefore always synthesized in the character's own voice first, and the resulting audio is what we later hand to H3. We never ask H3 to decide what a character sounds like.

The character should become reusable throughout the project and ideally across projects.

### Characters and the Character Lab

The Character Lab is not a separate system from this pipeline. They share the same characters.

* A character created by the pipeline appears in the Character Lab.
* A character created in the Character Lab can be used by the pipeline.
* A character can be edited directly in the lab, and the edit creates a new version of the same underlying character that projects use.

The lab also has the concept of environments, so the same is true for environments (see below).

A project does not follow a character automatically. It pins a specific version of each character and environment it uses, so editing a character in the lab never silently changes existing projects, and never alters a finished video.

When a character is updated, the user decides which projects should adopt the new version:

* By default, only projects that are not yet complete are selected.
* The user can select additional projects, or deselect any of the defaults.
* Only the projects the user chooses to update are rebuilt, and only the parts that depend on the changed character (see the staleness section).

A project can also move to a different version of a character on its own, where that makes sense, by choosing another version from within the project.

---

## 12. Character identity and character looks

We should distinguish:

**CHARACTER IDENTITY**

from:

**CHARACTER LOOK**

Arjun should not become a new character every time he changes clothes.

Instead:

```text
Arjun
  │
  ├── Identity
  │
  └── Looks
       ├── move-in clothes
       ├── night clothes
       └── other story-specific looks
```

Our existing Character Lab concept already maps well to this.

A look is derived from the character's canonical identity images, so the face and body stay the same while the wardrobe changes. Looks that a scene needs are created when that scene is defined.

Young Arjun is a special case.

He is semantically a younger version of Arjun but visually may need his own identity asset relationship.

---

## 13. Stage 6 — Environment Definition

Each environment also receives its own definition call.

Input:

```text
StoryBible
Raw Script
Current Environment
Scenes using the environment
```

Example:

```json
{
  "id": "arjun_apartment",
  "architecture": "aging urban Indian apartment",
  "layout": "...",
  "visual_identity": {
    "walls": "...",
    "floor": "...",
    "windows": "...",
    "doors": "...",
    "furniture": "...",
    "color_palette": "..."
  },
  "important_landmarks": [
    "front door",
    "bedroom hallway",
    "ceiling",
    "main living area"
  ],
  "atmosphere": {
    "baseline": "large, quiet, empty and subtly unsettling"
  },
  "continuity_rules": [
    "The apartment should always feel unusually spacious.",
    "The architecture should remain recognizable between scenes."
  ]
}
```

Then:

```text
Environment Definition
       ↓
Environment Image Prompt
       ↓
Generate canonical environment reference(s)
       ↓
Store Environment Asset
```

Environments live in the Character Lab as well, and are shared with it in the same way as characters. An environment created by the pipeline is visible and editable in the lab, and an environment created in the lab can be used by the pipeline.

---

## 14. Environment identity versus environment state

We should not generate an entirely new environment every time its lighting changes.

For example:

* Arjun's apartment during move-in

and:

* Arjun's apartment at 2:17 AM

are the same environment.

Therefore:

```text
Environment
   │
   ├── canonical visual identity
   ├── canonical reference image(s)
   │
   └── scene-specific states
        ├── daytime
        ├── nighttime
        ├── supernatural
        └── damaged/burned if relevant
```

The canonical references for every environment are generated up front, together with the environment definition.

A scene-specific state, such as the same apartment at night, is not generated from scratch. It is generated from the canonical environment reference image, using it as the reference exactly as we do today.

The states a scene needs are known once that scene has been defined. They are matched against the states that already exist, and only the genuinely new ones are produced.

This should improve continuity significantly.

---

## 15. Parallelism at the definition stage

Once discovery is finished, character and environment definition work can run heavily in parallel.

For example:

```text
Arjun Definition ───────────┐
Landlord Definition ────────┤
Meera Definition ───────────┤
Young Arjun Definition ─────┤
                            ├── parallel
Apartment Definition ───────┤
Bedroom Definition ─────────┤
Hidden Staircase ───────────┤
Burned Floor ───────────────┤
Childhood Bedroom ──────────┘
```

Their corresponding image generations can also be scheduled independently.

---

## 16. Stage 7 — Scene Definition

Once character and environment definitions exist, we fully define each discovered scene.

We make one LLM call per scene.

For each scene, the model receives:

```text
StoryBible
Raw Script
Current Scene Skeleton
Previous Scene Summary
Next Scene Summary
Relevant Character Definitions
Relevant Environment Definition
```

Example:

```json
{
  "id": "scene_mothers_voice",
  "story_context": {
    "before": "Arjun has discovered that the landlord considers his apartment to be on the seventh floor.",
    "current": "The supernatural presence communicates directly with Arjun.",
    "after": "Arjun begins investigating the building's history."
  },
  "environment_id": "arjun_bedroom",
  "environment_state": "night",
  "time": {
    "time_of_day": "2:17 AM",
    "lighting_state": "dark bedroom with weak practical illumination"
  },
  "characters": [
    "arjun",
    "meera"
  ],
  "character_looks": {
    "arjun": "night_clothes"
  },
  "mood": {
    "start": "anticipatory fear",
    "middle": "terror",
    "end": "deeply personal horror"
  },
  "dramatic_goal": "Transform the haunting from an unexplained phenomenon into something personally connected to Arjun.",
  "continuity_start": {
    "arjun": "awake and waiting for 2:17 AM"
  },
  "continuity_end": {
    "arjun": "terrified after hearing the voice of his dead mother"
  }
}
```

A scene definition still does not contain shots.

It establishes the dramatic context in which later events and shots exist.

It also tells us which environment state and which character looks the scene needs.

Scene definitions run in parallel and each one describes its needs in its own words, so one scene may ask for `"night"` and another for `"nighttime"` when they mean the same thing. To avoid creating duplicate images, resolution is a separate pass that runs after all the scene definitions are done.

This pass is one dedicated LLM call, not part of Scene Definition. It receives every state and look the scenes asked for, together with a catalog of the states and looks that already exist, each with a text description. For every request it decides whether an existing one can be reused or a new one is needed, and it merges requests from different scenes that mean the same thing.

Code then validates the result, for example that every reused id really exists.

Each state or look that is genuinely new is then generated once, by using the canonical reference image as the reference, so that identity stays fixed while only the state changes.

---

## 17. Stage 8 — Event Extraction

After a scene has been defined, we make another focused LLM call.

Its question is:

> Exactly what happens inside this scene, in story order?

The supported event types should initially remain small:

```text
narration
dialogue
action
sound_event
pause
```

Example:

```json
{
  "scene_id": "scene_mothers_voice",
  "events": [
    {
      "id": "evt_1",
      "type": "narration",
      "text": "That night, Arjun stayed awake."
    },
    {
      "id": "evt_2",
      "type": "narration",
      "text": "At 2:16, nothing happened."
    },
    {
      "id": "evt_3",
      "type": "narration",
      "text": "2:17."
    },
    {
      "id": "evt_4",
      "type": "sound_event",
      "description": "One heavy thump directly above the bedroom ceiling."
    },
    {
      "id": "evt_5",
      "type": "action",
      "description": "Arjun freezes and looks toward the ceiling."
    },
    {
      "id": "evt_6",
      "type": "dialogue",
      "speaker_id": "meera",
      "text": "Arjun?",
      "delivery": {
        "emotion": "soft, distant and unnatural"
      }
    },
    {
      "id": "evt_7",
      "type": "narration",
      "text": "His blood went cold."
    }
  ]
}
```

Events contain story truth.

They should not contain camera instructions.

A `pause` event records that a meaningful silence belongs at that point in the story. It does not carry a duration, because no TTS audio exists for it. How long it lasts is decided later by the Shot Planner.

---

## 18. Why Event Extraction is separate from Scene Definition

These are fundamentally different tasks.

Scene Definition asks:

> What is this dramatic situation?

Event Extraction asks:

> What precisely happens inside it?

By separating them, we let each model call focus on one job.

This follows our quality-first philosophy.

---

## 19. Stage 9 — Speech Planning

Once events exist, we identify speech-containing events:

```text
narration
dialogue
```

Before TTS, we check whether individual speech events are too long.

We should not ask the LLM to guarantee exact duration.

Instead we estimate duration using:

```text
text length
+
expected speech rate
+
delivery style
```

If necessary, a long semantic event becomes multiple:

`SpeechUnits`

For example:

```text
Narration Event
45 words
estimated 18 seconds
```

may become:

```text
SpeechUnit A
SpeechUnit B
```

Each speech unit must remain semantically natural.

Dialogue should be split more conservatively than narration because performance continuity matters.

There is one limit on that conservatism. Dialogue audio is handed to H3 as part of a single shot, so a dialogue speech unit must still fit inside the shot duration limits. Narration has no such constraint because it can continue across several shots.

---

## 20. Stage 10 — TTS

Now we generate the actual audio.

Dialogue is synthesized with the speaking character's own TTS voice, the one derived during Character Definition. Narration is synthesized with a narrator voice that follows the storytelling style established in the StoryBible.

This audio is not just a timing exercise. The two kinds of speech are used differently.

* Dialogue audio is the real speech that will later be passed to H3 as a reference.
* Narration audio is never passed to H3. It is placed directly on the final timeline as the narration layer.

This is where exact timing enters the pipeline.

For example:

```text
Narration 01 = 4.32 sec
Narration 02 = 3.18 sec

Landlord:
"Whatever you hear at night, don't go upstairs."
= 2.84 sec

Arjun:
"There's no upstairs."
= 1.24 sec

Landlord:
"Exactly."
= 0.71 sec
```

These are measured audio durations.

We no longer need transcription to discover timing because we created the speech assets ourselves.

---

## 21. Removing transcription from the main path

The current Vision Studio architecture uses:

```text
Full Narration
→ ASR / transcription
→ word timestamps
→ scene cuts
```

For the new pipeline, we want:

```text
Structured Speech
→ TTS
→ measured audio duration
```

Therefore transcription no longer needs to be part of the main production path.

Parakeet can later remain useful for validation:

```text
Generated H3 dialogue
→ ASR
→ verify that intended dialogue was actually spoken
```

That is a better use of transcription.

It matters more because the audio that comes back from H3 is used as it is. This check is how we confirm that a dialogue shot actually contains the intended line. A shot that fails it is regenerated like any other failed shot.

---

## 22. Stage 11 — Shot Planning

Only after actual speech durations are known should we decide how to visually present a scene.

The Shot Planner receives:

```text
Scene Definition
Events
Character Definitions
Environment Definition
Actual Speech Durations
StoryBible
```

Its job is:

> How should the audience see these events?

For example:

```text
Event:
Narration:
"At exactly 2:17 AM, Arjun heard footsteps above his bedroom."
Speech duration:
3.1 sec

Event:
Heavy thump

Event:
Arjun looks upward

Event:
Three quick footsteps
```

The Shot Planner could create:

```text
Shot 1 — 2.5 sec
Close-up of clock showing 2:17 AM.
Narration begins.

Shot 2 — 2.5 sec
Arjun opens his eyes.
Narration finishes.
One heavy thump.

Shot 3 — 2.0 sec
Camera slowly tilts toward ceiling.
Three rapid footsteps.
```

This demonstrates an important principle:

> **Event count ≠ Shot count**

### Pauses and short events

Speech events get their duration from TTS. A `pause` event has no audio, so the Shot Planner decides how long it lasts, in the same way it decides the duration of every other shot.

The Shot Planner also decides how very short events, such as a one-word narration line or a pause, are combined with their neighbours or given a shot of their own.

### Shot duration policy

The Shot Planner is told to produce shots of roughly 2 to 10 seconds, which keeps a margin inside H3's hard boundary of 1 to 15 seconds.

We do not assume the planner always obeys this. Shot durations are checked deterministically after planning.

* A shot outside the 2–10 second target range is flagged, and the planner is asked to re-plan that part of the scene, for example by merging a very short shot with a neighbour or splitting a very long one.
* A shot outside the hard 1–15 second boundary never reaches generation.

The same discipline applies after generation: a clip whose duration is out of range is regenerated rather than silently accepted.

---

## 23. Narration can span several shots

Suppose:

> The apartment was on the top floor of an old six-story building. It was cheap, surprisingly spacious, and almost completely empty.

TTS produces:

```text
7.2 seconds
```

The Shot Planner could choose:

```text
0.0–2.4
Exterior of the old building

2.4–4.8
Arjun entering the apartment

4.8–7.2
Wide shot showing the empty interior
```

while the same narration plays continuously.

This is important for good pacing.

We should not force:

```text
one narration event = one video
```

---

## 24. Dialogue and short H3 clips

We have tested H3 and verified:

```text
~2-second clips
→ reliable

~1-second clips
→ often work but somewhat less reliable

up to ~15-second clips
→ possible
```

Very short speech is therefore not a problem. Even when a line is shorter than a second, we do not generate a shot that short. We plan a shot of at least about two seconds, which stays inside the safe range.

Therefore dialogue such as:

```text
"Yes."
"What?"
"Why?"
"Exactly."
```

can be handled naturally.

The video duration does not need to equal the speech duration exactly.

For example:

```text
Speech:
"Exactly."
= 0.71 sec

Generated Shot:
2.0 sec
```

Possible performance:

```text
0.0–0.7
"Exactly."

0.7–2.0
Landlord continues smiling awkwardly, holding Arjun's gaze, in silence.
```

The supplied audio plays from the start of the shot. H3 pads the rest with expression and no sound, so we do not need to add silence ourselves.

The shot's target duration must therefore never be shorter than the speech it carries.

For most scenes, a quick exchange is simply a sequence of short dialogue shots like this one. Only where a scene truly needs rapid back-and-forth inside a single shot do we use H3's multi-shot prompting with two character references and two dialogue audios. That route is reserved for such cases because we have not yet tested it extensively.

This creates a more cinematic result than forcing a 0.71-second shot.

---

## 25. Stage 12 — Shot Skeleton Generation

The Shot Planner should initially produce compact shot objects.

For example:

```json
{
  "id": "shot_23",
  "scene_id": "scene_first_night",
  "source_event_ids": [
    "evt_4",
    "evt_5"
  ],
  "type": "reaction",
  "target_duration": 2.0,
  "description": "Arjun freezes and looks toward the ceiling."
}
```

This is shot discovery.

It is intentionally not the final H3 prompt.

---

## 26. Stage 13 — Shot Definition

For quality, we then make one focused call per shot.

Input:

```text
StoryBible
Scene Definition
Shot Skeleton
Source Events
Relevant Characters
Environment
Previous Shot Skeleton
Next Shot Skeleton
```

Output:

```json
{
  "shot_id": "shot_23",
  "duration": 2.0,
  "visual_story": "Arjun freezes as an impossible footstep echoes above him.",
  "characters": [
    {
      "id": "arjun",
      "expression": "suddenly alert and frightened",
      "pose": "partially upright in bed",
      "gaze": "toward ceiling"
    }
  ],
  "environment_state": {
    "lighting": "dim warm bedside light",
    "ceiling_visible": true
  },
  "composition": {
    "shot_size": "medium_close_up",
    "angle": "slightly low",
    "focus": "Arjun"
  },
  "camera": {
    "movement": "slow_push_in",
    "intensity": "subtle"
  },
  "action": {
    "start_state": "Arjun lying still",
    "primary_action": "his eyes snap upward toward the ceiling",
    "end_state": "Arjun remains frozen, staring upward"
  },
  "continuity_start": {
    "arjun": "lying still in bed, eyes closed"
  },
  "continuity_end": {
    "arjun": "partially upright, frozen, staring at the ceiling"
  },
  "audio_intent": {
    "dialogue": null,
    "ambient": "quiet bedroom at night",
    "sound_events": [
      "one heavy footstep above the ceiling"
    ]
  }
}
```

This becomes our cinematic shot specification.

### Shot continuity

Just as a scene has a `continuity_start` and `continuity_end`, so does every shot.

* The first shot of a scene starts from the scene's `continuity_start`.
* The last shot of a scene ends at the scene's `continuity_end`.
* Within a scene, each shot should start where the previous shot ended.

Shot Definition calls run in parallel, so neighbouring shots can disagree about these states. After definition, each shot's `continuity_end` is compared with the next shot's `continuity_start`. Shots that do not line up are defined again with their neighbour's state supplied as input.

### Sound effects belong to the shot

The sound events in `audio_intent` are a property of the shot. They are carried into the H3 prompt, and we accept that H3 generates them as part of the shot's own audio.

Background music is deliberately not part of `audio_intent`. It is a continuous layer owned by the whole story, not by an individual shot.

---

## 27. Why Shot Planning and Shot Definition are separate

Shot Planning asks:

> How many shots should exist and what does each accomplish?

Shot Definition asks:

> Exactly how should this one shot look, move and sound?

Again, we are separating discovery from definition.

---

## 28. Stage 14 — Reference Selection

Once a shot is fully defined, we determine the minimum references necessary to generate it.

This is a dedicated pass of its own, separate from Shot Definition and from prompt compilation, so that choosing references never competes for attention with designing the shot or writing the prompt.

For example:

**Arjun reaction shot**

```text
Arjun frontal reference
Arjun 3/4 reference
Bedroom environment reference
```

**Arjun dialogue shot**

```text
Arjun frontal
Arjun 3/4
Bedroom environment
Arjun dialogue audio
```

**Narration shot**

```text
Environment reference
Relevant character references, if any appear
```

Narration audio is not part of the reference set. It plays on the timeline over the shot.

**Complex physical acting shot**

Potentially:

```text
Arjun character references
Environment reference
Short motion reference video
Dialogue audio if relevant
```

We should follow the rule:

> Use the minimum sufficient reference set.

This improves both:

* H3 conditioning clarity,
* GPU memory usage.

We should not send every available character/environment image to every request.

### How references are chosen

The choice combines code and a model, in three steps.

**1. Code narrows the options.**

Using the structured fields of the Shot Definition, code keeps only the assets that can matter to this shot: the characters in the shot, their looks for the scene, and the shot's environment and its state. The model is therefore shown a small catalog, not everything in the project.

**2. A model chooses.**

One LLM call per shot receives the Shot Definition and the candidate catalog. Each catalog entry is a text description with its id, view (for example frontal or 3/4), look and state. The model does not need to see the images. Every image was generated from a prompt, so its description already exists.

The model picks the minimum sufficient set, for example which view of Arjun suits a shot where he looks up at the ceiling, and says briefly why. Because it reads meaning rather than exact labels, it does not depend on names matching perfectly.

**3. Code validates.**

Code checks that every chosen id exists, that the counts fit what H3 accepts, and that the set respects the minimum-sufficient rule. If the check fails, the call is retried, and if it still fails the selection falls back to simple matching on the shot's characters, look, environment and state, using the canonical images.

Reference Selection runs once per shot, and these calls can run in parallel.

---

## 29. Stage 15 — Generation Planning

This stage should be deterministic code, not an LLM.

Inputs:

```text
Shot Definition
Selected References
Speech Assets
Target Duration
Motion Complexity
```

Outputs:

```text
H3 partition/mode
duration/frame count
resolution
image references
audio references (and how they are applied, e.g. partial copy)
video references
GPU execution strategy
```

Example:

```json
{
  "model": "h3",
  "partition": "ref2va",
  "duration_seconds": 2.0,
  "resolution": "1344x768",
  "references": {
    "images": [
      "arjun_front",
      "arjun_three_quarter",
      "bedroom_night"
    ],
    "audios": [],
    "videos": []
  }
}
```

Hardware constraints and supported H3 frame counts should remain deterministic.

The LLM should not decide them.

This is also where the hard 1–15 second duration boundary is enforced. A shot outside it is rejected and sent back for re-planning instead of being generated.

### Exact durations without drift

To keep the timeline from drifting, Generation Planning asks H3 for a slightly longer clip than the shot needs. After generation, the clip is trimmed to the exact target duration, as we do today.

Trimming only removes the tail of a clip. This is safe for dialogue shots because the speech plays from the start and the shot target is never shorter than the speech.

### Shot dependencies and parallel generation

Most shots are independent, but a continuity shot needs the output of the shot before it.

Generation Planning therefore builds a dependency graph of the shots.

* Shots with no dependencies are generated in parallel, as we do today.
* A shot that depends on a previous shot waits until that shot has been generated.
* If a shot is regenerated, every shot that depends on it must be regenerated as well (see the staleness section).

---

## 30. Stage 16 — H3 Prompt Compilation

Only now do we write the final detailed H3 prompt.

Input:

```text
StoryBible
Shot Definition
Character Definitions
Environment Definition
Reference Manifest
```

GLM-5.3 acts as a prompt compiler.

Its job is not to reinterpret the story.

Its job is:

```text
structured production intent
        ↓
high-quality H3 Context-IR prompt
```

This is where we generate fields such as:

```text
subject_definitions
summary
retention_analysis
detailed_description
overall_soundscape
non_diegetic_music
```

when using Ref2VA.

The compiler writes the soundscape from the shot's sound events and ambience. It must also make sure H3 is told not to create background music, so `non_diegetic_music` is left empty or explicitly disabled. Music is added separately across the whole timeline.

---

## 31. Stage 17 — H3 Generation

Now H3 receives:

```text
Final H3 Prompt
+
Reference Images
+
Reference Audio (TTS dialogue only, in partial copy mode)
+
Optional Reference Video
+
Duration
+
Resolution
+
Generation Parameters
```

and generates the clip, which is then trimmed to the exact planned duration.

---

## 32. Stage 18 — Quality Validation

Initially we can keep validation simple:

```text
video decodes correctly?
duration within the hard 1–15 second boundary and close to the target?
audio exists?
expected resolution?
```

Later we add:

```text
correct character identity?
correct environment?
correct dialogue?
lip sync?
prompt adherence?
visual artifacts?
continuity?
```

Failures can trigger:

```text
retry with another seed
re-plan the shot, if its duration was out of range
```

and eventually more intelligent retry strategies.

Shots are regenerated systematically: the failing shot is regenerated on its own, and the rest of the timeline is left untouched.

---

## 33. Stage 19 — Final Timeline

Once shots have passed validation, they are placed on the final timeline.

We maintain separate audio layers:

```text
Narration
Shot audio (from H3: dialogue, SFX and ambience)
Background music
```

Narration comes from the TTS assets we created and is placed directly on the timeline. It is continuous across shot boundaries and is not affected by where shots are cut.

Shot audio comes straight from H3 and is used as it is. For a dialogue shot it contains the dialogue we supplied in partial copy mode, together with the sound effects and ambience the model added. For other shots it contains only the sound effects and ambience that belong to the shot.

Because dialogue is part of the shot audio, there is no separate dialogue layer, and speech is never doubled. Narration never enters H3, so the narration layer and the shot audio never contain the same speech.

Background music is the one layer that does not come from the shots at all. It is continuous and is generated separately.

Conceptually:

```text
                    VIDEO
Narration   █████████       █████████
Shot audio  █████████████████████████
(dialogue,            ██ ██       ███
 SFX etc.)       ↑thump     ↑knock
Music       █████████████████████████
```

Since narration is a separate layer, shot audio can be lowered under it where needed.

Audio is normalized across the whole timeline, as we already do today. That normalization is extended to the shot audio, so that differences in loudness and ambience between neighbouring clips do not produce audible jumps at the cuts.

FFmpeg remains responsible for final assembly.

---

## 34. Music is a separate, continuous layer

Background music is not generated by H3 and does not belong to any individual shot.

A dedicated:

`Music Planner`

looks at the emotional arc of the whole story, not individual shots, and plans the music that runs underneath it.

Music should usually span multiple shots and scenes, and it should be continuous rather than restarting at every cut.

We must never let every H3 shot independently create its own unrelated background music. This is why the prompt compiler explicitly keeps music out of the H3 prompt.

Sound effects are different. They are a property of the shot, and H3 is allowed to generate them.

So the audio in a finished video is:

```text
Narration                 → TTS, placed directly on the timeline
Dialogue                  → TTS, passed to H3 and kept in the H3 shot audio
Sound effects / ambience  → H3, per shot
Background music          → Music Planner, continuous
```

### Working decision: which models make music and sound effects (recorded 23 Oct 2026)

**Decision (from the project owner, refined the same day):** audio comes from three sources, and the later two are additions, not replacements.

1. **H3 keeps the sounds built into each shot.** These are mostly tied to that one shot (the footsteps, door or voice reaction seen on screen), and they are used as H3 returns them.
2. **Stable Audio adds extra sound effects (SFX) on top.** Two kinds go to it: an additional effect a shot needs that H3 did not make, and any effect or ambience that spans several shots (for example a room tone or rain that runs across a whole scene), because H3 works one shot at a time.
3. **ACE-Step adds the background music** on top, as the continuous layer in the Music Planner above.

Which Stable Audio model (3 or Open) is not decided. We will pick it later, after the trial listening and after checking current online sources for which one fits our use.

**Status: a working decision for planning, not yet confirmed.** It rests on the GPU server's and the models' own documentation. The 84 Music Lab trial runs (temporary folder `music_lab_trials/`, cases A to H) have been triggered, but nobody has listened to them yet. Those listening notes can confirm or change this.

What the documentation says that supports it:

- ACE-Step 1.5 makes songs and instrumentals from 10 s to 600 s, with exact `bpm`, `keyscale`, `time_signature` and `duration`. Its code is MIT, and its authors state that the generated music may be used commercially.
- Stable Audio 3 (up to 380 s on the server, 285 s in the lab today) and Stable Audio Open (up to 47 s) are documented for sound effects, foley, loops and ambience, with no vocals.
- Both ACE-Step and Stable Audio 3 have time-window editing endpoints on the GPU server (ACE-Step `repaint`, Stable Audio 3 `inpaint`). The Music Lab does not call them yet.

Open points to settle before this goes into the pipeline:

0. **First, find out what H3 really produces.** Plan this with the model itself: look at the audio H3 returns for real shots and note which sounds it adds on its own (effects, ambience, anything musical) and how much depends on the shot. That decides which effects we still need from Stable Audio. This has not been done.
1. **Which Stable Audio.** Stable Audio 3 and Stable Audio Open are both candidates for SFX. The trials (groups E and F) run both, plus LTX audio, on the same prompts. Open: choose one, or use Open for short effects and 3 for longer ones. To be settled later, with a check of current online sources.
2. **Overlap with what H3 already made.** §4, §26 and §34 above stay as they are: H3 still makes the shot's own sounds. The added layers must not double them (the same knock twice, or two room tones at once). Open: how the Planner knows what H3 already covered in a shot, and how an added effect is told apart from one H3 made. Also open: how an effect that spans shots is timed and cross-faded at the cuts.
3. **Timing of effects.** SFX are short separate clips, so each could be placed at the time of its event on the final timeline. This is only an idea. It needs the trial results on whether the effects come out as asked (case E: counts, order, length).
4. **Licence.** Stable Audio models use the Stability AI Community License: free below USD 1M annual revenue, a separate licence above. The server does not enforce it.
5. **Music Lab ordering.** `services/music_models.py` lists Stable Audio 3 before ACE-Step for scores ("best first"). That ordering is only a default for the lab's page and does not follow this decision. It has not been changed.

---

## 35. Call structure

### Global calls

We perform these once per story:

1. Story Bible
2. Character Discovery
3. Environment Discovery
4. Scene Discovery

---

### Per-character calls

```text
Character Definition × N
```

These can run in parallel.

---

### Per-environment calls

```text
Environment Definition × N
```

These can also run in parallel.

Character and environment definition calls can run concurrently.

---

### Per-scene calls

For every scene:

```text
Scene Definition
       ↓
Event Extraction
```

Scene definitions can mostly run in parallel once global assets exist.

After all scene definitions are done, one further call resolves the environment states and character looks that the scenes requested, reusing existing ones and merging duplicates, before any new state images are generated.

Each scene should receive brief summaries of its neighboring scenes so that it does not reason in complete isolation.

---

### Per-speech-unit operations

```text
Speech Chunking
TTS
Duration Validation
```

TTS jobs can run massively in parallel.

---

### Per-scene Shot Planning

Each scene should have an independent Shot Planner call.

We should not ask one LLM to create 60 shots for an entire long story in one response.

Instead:

```text
Scene 1 → Shot Planner
Scene 2 → Shot Planner
Scene 3 → Shot Planner
...
```

This gives the model much stronger local reasoning.

---

### Per-shot Definition

Once shot skeletons exist:

```text
Shot Definition × N
```

These can again run in parallel, while each call receives adjacent shot context.

Because they run in parallel, a continuity check across neighbouring shots follows, and any shots that do not line up are defined again.

---

### Per-shot Reference Selection

Once shots are defined:

```text
Reference Selection × N
```

Each shot gets its own dedicated call, and these can run in parallel.

---

### Per-shot Prompt Compilation

Finally:

```text
H3 Prompt Compilation × N
```

also parallelizable.

---

## 36. What we should not combine

For quality reasons, we should avoid calls such as:

```text
Character Definition
+
Shot Planning
+
H3 Prompt Writing
```

or:

```text
Scene Definition
+
Event Extraction
+
Final Video Prompt
```

or:

```text
Shot Planning
+
H3 inference configuration
```

or:

```text
Shot Definition
+
Reference Selection
+
H3 Prompt Writing
```

They require different kinds of reasoning.

---

## 37. What we should also not over-fragment

We should not create separate LLM calls for:

* camera angle
* camera movement
* shot size
* facial expression
* environment lighting
* sound intent

Those belong naturally together inside:

`Shot Definition`

The guiding principle is:

> One LLM call should perform one coherent intellectual task, not necessarily generate only one field.

---

## 38. Proposed data hierarchy

Conceptually:

```text
Project
│
├── Settings (including optional review points)
│
├── StoryBible
│
├── Characters (shared with the Character Lab)
│    ├── CharacterDefinition
│    └── CharacterAssets
│         ├── canonical images and views
│         ├── looks
│         └── TTS voice
│
├── Environments (shared with the Character Lab)
│    ├── EnvironmentDefinition
│    └── EnvironmentAssets
│         ├── canonical references
│         └── scene-specific states
│
├── StoryScenes
│    │
│    ├── SceneDefinition
│    │
│    ├── StoryEvents
│    │
│    └── Shots
│
├── SpeechUnits
│
├── GenerationRequests
│
├── Music
│
└── FinalTimeline
```

Characters and environments are not duplicated into the project. A project pins a version of the same shared objects that appear in the Character Lab.

---

## 39. Relationship between Events and Shots

The relationship is not one-to-one.

### Multiple events can become one shot

```text
Event:
Arjun laughs.

Event:
Arjun says:
"There's no upstairs."
        ↓
One dialogue shot
```

### One event can become multiple shots

```text
Narration:
"The apartment was cheap, spacious and almost completely empty."
        ↓
Exterior shot
Interior entrance shot
Wide empty-room shot
```

Therefore a shot should reference:

```json
{
  "source_event_ids": [
    "evt_3",
    "evt_4"
  ]
}
```

rather than owning authoritative story text itself.

The event remains the source of truth.

---

## 40. Review points

The pipeline is designed to run from raw story to finished video without anyone stepping in.

By default there are no review points.

A user who wants more control can add review points in the project settings, at the boundaries between stages. For example:

```text
after story structure (characters, environments, scenes)
after character and environment images
after scene definition and events
after shot planning
after generated shots
```

When a review point is enabled, the pipeline pauses there once the artifacts for that stage exist. The user can inspect them, edit them, regenerate them, and then let the pipeline continue.

A review point is only a pause. The stages produce exactly the same artifacts whether or not anyone is looking at them, which is why the intermediate structures must always be inspectable and editable.

Anything changed during a review goes through the same staleness mechanism as every other change.

---

## 41. Staleness and invalidation

Every artifact in the project depends on other artifacts. A shot depends on its shot definition, the speech units it carries, and the character looks and environment state it references. A character's TTS voice depends on that character's definition. Character and environment images depend on their definitions.

These artifacts will change. The user edits a character in the Character Lab, a definition is regenerated, an image is replaced, a shot fails validation. The system needs a clear answer to the question:

> Which of the things we already produced are no longer valid?

To answer it:

* Every artifact is versioned.
* Every artifact records the exact versions of the upstream artifacts it was produced from.
* When an artifact changes, everything derived from it is marked **stale**, and so is everything derived from those, down the chain.
* Dependencies are as narrow as the real inputs. A shot records which characters, looks, environment states and speech units it used, so changing the Landlord does not make a shot that only shows Arjun stale.

For example:

```text
Arjun's TTS voice changes
   ↓
Arjun's speech units are stale
   ↓
Shots in which Arjun speaks are stale
(shots without Arjun's dialogue are untouched)
```

```text
A canonical environment image is replaced
   ↓
Its scene-specific states are stale
   ↓
Shots that reference those states are stale
(events, scenes and speech are untouched, because they do not depend on images)
```

Stale does not mean deleted.

* The previous output remains available until it is replaced.
* Staleness only records that the artifact was built from inputs that have since changed.
* A stale artifact must never become a dead end. It can always be regenerated, or accepted as it is.
* Regeneration is selective. Only stale artifacts are rebuilt, in dependency order, and everything unaffected is reused.

The same mechanism covers failures. A shot that fails validation, or comes out with a duration outside the allowed range, is simply an artifact that needs regeneration. It is regenerated on its own without disturbing the rest of the project.

The one exception is a shot that other shots depend on. A continuity shot is built from the output of the shot before it, so when that earlier shot is regenerated, the continuity shot becomes stale and is regenerated too. These shot-to-shot dependencies are part of the same dependency graph, which is also what lets independent shots continue to be generated in parallel.

Because characters and environments are shared with the Character Lab, a project's artifacts become stale in the same way whether a character changes inside the pipeline or a project adopts a new lab version of it. Projects that stay on their pinned version are unaffected.

---

## 42. Example end-to-end transformation

Starting script:

```text
When Arjun moved into his new apartment, the landlord gave him only one strange warning.

“Whatever you hear at night, don’t go upstairs.”

Arjun laughed.

“There’s no upstairs.”

The landlord smiled awkwardly.

“Exactly.”
```

### Story understanding

```text
Scene:
The Warning
```

### Events

```text
Event 1 — narration
"When Arjun moved..."

Event 2 — landlord dialogue
"Whatever you hear at night, don't go upstairs."

Event 3 — action
Arjun laughs.

Event 4 — Arjun dialogue
"There's no upstairs."

Event 5 — action
Landlord smiles awkwardly.

Event 6 — landlord dialogue
"Exactly."
```

### TTS

```text
Narration = 4.3 sec
Warning = 2.8 sec
There's no upstairs = 1.2 sec
Exactly = 0.7 sec
```

### Shot Planner

Possible result:

```text
Shot 1 — 2.2 sec
Exterior/top floor of old building.
Narration begins.

Shot 2 — 2.1 sec
Arjun entering apartment.
Narration finishes.

Shot 3 — 3.2 sec
Landlord warning Arjun.
Dialogue.

Shot 4 — 2.0 sec
Arjun laughs and says:
"There's no upstairs."

Shot 5 — 2.0 sec
Landlord smiles awkwardly and says:
"Exactly."
```

### Shot Definition

For Shot 5:

```text
Character:
Landlord

Expression:
restrained awkward smile

Camera:
close-up
subtle push-in

Dialogue:
"Exactly."

Speech:
0.7 sec

Shot duration:
2.0 sec

Environment:
Arjun apartment

Mood:
subtly disturbing
```

### Generation

```text
Landlord references
+
Apartment reference
+
Landlord dialogue audio (TTS, partial copy)
+
H3 Ref2VA prompt
+
2.0 sec target
```

### Result

H3 generates the final shot.

This is the type of transformation we want throughout the entire story.

---

## 43. Capability areas of the finished system

The stages described above can be grouped into a handful of capability areas. Together they make up the system we want to reach.

### Story structure

```text
StoryBible
CharacterDiscovery
EnvironmentDiscovery
SceneDiscovery
```

Their JSON outputs are stored as artifacts.

---

### Entity definitions

```text
CharacterDefinition
EnvironmentDefinition
```

connected to our existing image-generation systems and shared with the Character Lab.

The result is:

```text
fully defined characters
+
canonical character images
+
a TTS voice for each character
+
fully defined environments
+
canonical environment images
```

---

### Scene understanding

```text
SceneDefinition
EventExtraction
```

Every scene has a detailed semantic representation, including the environment state and character looks it needs.

---

### Speech

```text
SpeechUnit planning
TTS
Actual duration measurement
```

Transcription is no longer part of the primary timing workflow.

---

### Directing

```text
ShotPlanner
ShotDefinition
```

The system understands how every part of the story should appear on screen, with shots that respect the duration limits and carry their own continuity.

---

### H3 generation

```text
Reference Selection
Generation Planning
H3 Prompt Compilation
H3 Generation
```

This reuses as much of the current Vision Studio H3 infrastructure as possible.

---

### Automated quality

```text
technical validation
identity checks
lip-sync checks
prompt adherence
continuity checks
retry and regeneration strategies
```

---

### Audio production

```text
music planning
music generation
final audio mixing
```

Sound effects are not planned here, because they are generated per shot by H3.

---

### Project control

```text
optional review points
staleness and invalidation
```

These cut across every other area. They are what let a user step in, edit, and regenerate selectively without breaking the rest of the project.

---

## 44. What we are fundamentally building

The system can ultimately be understood as several specialized agents/services:

```text
Story Compiler
        ↓
understands the story

Asset Designer
        ↓
creates reusable people and places

Scene Interpreter
        ↓
understands each dramatic situation

Event Parser
        ↓
identifies exactly what happens

Speech System
        ↓
creates the actual temporal constraints

Shot Planner
        ↓
acts as director/editor

Shot Designer
        ↓
fully specifies each visual unit

Reference Selector
        ↓
chooses the minimum sufficient references for each shot

Generation Planner
        ↓
understands H3 and hardware constraints

H3 Prompt Compiler
        ↓
translates production intent into model language

H3
        ↓
creates footage, with per-shot sound effects

Music Planner
        ↓
creates the continuous background music for the whole story

Quality System
        ↓
decides whether footage is acceptable

FFmpeg / Timeline Engine
        ↓
assembles the final movie
```

The most important architectural principle is that each layer produces a structured artifact that can be inspected, stored, regenerated, edited, and reused.

We should not create a black-box workflow where one giant prompt directly transforms a script into model prompts.

The intermediate structures are the product architecture.

They allow us to determine whether a failure originated in:

* story interpretation,
* character definition,
* environment definition,
* scene interpretation,
* event extraction,
* speech generation,
* shot planning,
* shot definition,
* H3 prompting,
* or H3 itself.

That traceability is essential if Vision Studio is going to become a reliable autonomous video-production system.

It is also what makes selective regeneration possible. Because every artifact knows what it was built from, a change or a failure at any layer can be repaired without rebuilding the whole movie.

---

## 45. Where we want to reach

The target is a reliable structured planning layer between:

**RAW STORY**

and:

**VIDEO GENERATION.**

Once the intermediate artifacts are reliable and stored correctly, they drive speech, directing and H3 generation. The existing H3 generation infrastructure sits downstream of this layer and is reused rather than redesigned.

Characters and environments are shared with the Character Lab, so assets can be created and refined in either place. Review points and staleness handling let a user step in only where they want to and regenerate only what has actually changed.

That structured planning layer is what will turn Vision Studio from a collection of generation workflows into an actual automated filmmaking system.

---

## 46. Spatial plans, staging and environment views

A place has more than one side. The environment definition carries a **spatial plan**: what is ahead of, to the left of, to the right of and behind the master picture's camera (the master picture is the `ahead` view), and the zones people can stand in.

**Scene Staging** (one call per scene, after events) decides where each visible character stands, which way they face, which side of the screen they appear on and which side of the place is behind them, plus an axis for the main conversation, a group background and moves keyed to events. Code checks it against the plan.

**Environment views** are camera-direction pictures of one place. A view planner reads the stagings of the scenes that use the place and chooses the views (at most 12); each view's edit prompt is written by a model and the picture is an edit of the master picture. A view in a state is an edit of the view picture and the state's master picture. Views belong to the library environment, like states.

**Shots** choose a view from the ones the staging allows for their focus (a single shot of a speaker uses that speaker's background, a two-shot or wide uses the group background), and code copies each character's screen side, so shot and reverse shot keep the 180-degree rule. Reference selection takes the shot's view picture.
