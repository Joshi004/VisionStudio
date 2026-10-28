# Vision Studio — Explainer Mode Phases

An **explainer** is a project made of one script that one presenter speaks from start to finish. The presenter is a Character Lab character. In some passages the presenter is on camera, and in the others their voice is heard over B-roll.

- This document records what was decided, how it was built, what the owner still has to check, and what is known to be weak.
- The conventions of `Implementation_phases.md` (§3.3 to §3.5, §6) apply unchanged. Table and column details are in `DATABASE_STRUCTURE.md` (migration `0072`).
- Written 2026-10-27, from the plan "Explainer mode: presenter plus B-roll".
- Sections 5 to 8 (captions and callouts, EXPLAINER-007 to EXPLAINER-011) were added on 2026-10-28, from a design discussion with the owner. Run those phases in their order (§7).

---

## 1. Decisions

| # | Decision |
|---|----------|
| E-1 | The kind is chosen when the project is created and never changed, like `speech_mode` (PHASE-049). The values are `story` and `explainer`. |
| E-2 | The presenter is mandatory and comes from the Character Lab. The presenter must not be archived, must have a mouth that can be seen (`has_visible_mouth`), and the newest version must have a `voice_id` and all five look angles. |
| E-3 | The set is optional. With a library environment (one with a picture), that is the set. Without one, the pipeline designs exactly one place from the Story Bible. |
| E-4 | The presenter's voice is also the narrator's voice. An explainer never makes a narrator voice by its own job, and the user cannot choose another. If the presenter's voice changes, the narrator is set again. |
| E-5 | The passages where the presenter is seen are **dialogue** events and shots. The TTS line is sent to H3 as `fully_copy` and is placed in silence that lasts exactly as long as the clip. All other passages are **narration** events and are shown as B-roll. |
| E-6 | B-roll is made on H3's text route: no reference picture, not even the set. H3's own sound is kept and ducked as it is today. |
| E-7 | Deterministic graphics (charts, diagrams, on-screen text) are **not** part of this. B-roll is asked to show no text, and a later phase can add a graphic source. |
| E-8 | Everything was done by branching the existing pipeline. With `kind = story`, every instruction and request stays byte-for-byte what it was (checked for the event, shot planning and shot definition instructions). |

---

## 2. How it works

```text
create project (kind explainer, presenter, optional set)
  -> Story Bible (explainer note)
  -> discovery: presenter and set written by code, no model for the presenter
  -> links, definitions, images and voice reused as_is
  -> events: only narration, dialogue, pause
  -> speech units + TTS (narrator = presenter voice)
  -> shot planning: one line of dialogue per presenter shot, other shots are B-roll
  -> shot definition: presenter visible only in a dialogue shot
  -> references: presenter shot = pictures, B-roll = none
  -> generation request: presenter shot = reference route + fully_copy, B-roll = text route
  -> prompt, take, render (unchanged)
```

### 2.1 What was built

| Stage | Where | What changed |
|-------|-------|--------------|
| EXPLAINER-002 | `services/project_kinds.py`, `services/explainer.py`, `services/projects.py`, `api/projects.py`, `api/project_cast.py`, migration `0072`, frontend create form, settings badge, `ExplainerCastPanel` | `project.kind`, the presenter and set checks, the cast written with the project, cast changes refused |
| EXPLAINER-003 | `services/discovery.py`, `jobs/discovery_job.py`, `discovery_writer.py`, `story_voices.py`, `story_pipeline_targets.py`, `api/story_voices.py` | Fixed discovery items (presenter, set), one designed place when there is no set, narrator = presenter voice |
| EXPLAINER-004 | `services/projects.py` (`prompt_mode`), `story_bible_writer.py`, `scene_discovery_writer.py`, `event_extraction_writer.py`, `shot_planning_writer.py`, `shot_definition_writer.py`, jobs `extract_events`, `plan_shots`, `define_shot`, `repair_shot_cut` | Explainer notes, the allowed event types, the checks below |
| EXPLAINER-005 | `reference_selection.broll`, `shot_references.py`, `generation_planner.py`, `generation_requests.py`, `shot_prompt_writer.py`, `speech_audio.place_in_silence`, `shot_takes.py`, `jobs/generate_lab_video.py` | Empty manifest for B-roll, `fully_copy` audio, prompt wording, the placed audio upload |

`prompt_mode(project)` is the one function the event and shot prompts branch on. It returns `explainer` for an explainer and the project's `speech_mode` for a story. It is copied into each job's input as `speech_mode`.

### 2.2 The code checks

- **Events:** an explainer may only have `narration`, `dialogue` and `pause` events. The word-for-word check of the script is unchanged.
- **Shot planning:** a shot that carries a line of dialogue must have the type `dialogue`, carry that one line and nothing else. A shot of type `dialogue` must carry a line of dialogue. Rapid exchanges are not possible.
- **Shot definition:** a shot with a line of dialogue lists the presenter, and only the presenter, in `characters`. Any other shot lists nobody.
- **References:** a shot of an explainer that shows no character gets a manifest with no picture. The router then picks the text route by itself, because the shot has no picture and no dialogue.
- **Generation request:** for an explainer, each dialogue audio has `marker: fully_copy`, and the request has `explainer: true`. The `explainer` key is stored only when it is true.
- **Upload:** a `fully_copy` audio is not sent as it is stored. The job places it at the line's start time inside silence of exactly `num_frames / 24` seconds (`speech_audio.place_in_silence`, FFmpeg `adelay`, `apad` and `atrim`). It was checked that the file has the exact number of samples.
- **Prompt:** with `fully_copy` the app writes the audio lines and an overall soundscape that says the only sound is the speech. The model writes no soundscape piece. In a B-roll prompt the set is not sent, and a rule says the presenter, the set and any text must not appear.

---

## 3. Owner actions

The agent could not run these, because they need the GPU server and listening to the result.

### EXPLAINER-001 — Check `fully_copy` with a padded audio (not done)

**Why:** `fully_copy` makes the audio the entire soundtrack, so the clip must be exactly as long as the audio. The code builds this, but nobody has yet checked that H3 gives good lips and no extra sound with an audio that has silence before and after the speech.

**How:**

1. Pick a speech of 2 to 4 seconds, and a clip length that is `17n + 5` frames (for example 125 frames, 5.208 s).
2. Make the padded audio with the same filter the app uses:

   ```bash
   ffmpeg -i speech.wav -af "adelay=500:all=1,apad=whole_dur=5.208333,atrim=end=5.208333" -c:a pcm_s16le padded.wav
   ```

3. In the Character lab, make a clip with the presenter's pictures, `fully_copy`, and `match_audio_duration` on, using `padded.wav`.
4. Judge: do the lips follow the words, does the speech start at 0.5 s, and is there no other sound, music or breath?

**If it fails:** set `AUDIO_MARKER_EXPLAINER` in `services/generation_planner.py` to `"partially_copy"`. That is the only change needed: the prompt wording, the soundscape piece and the upload follow the marker, and the audio is sent unplaced, as it is for a story today.

**Result (owner fills in):** Passed. The owner reported on 2026-10-28 that the check was run and the result is good. `AUDIO_MARKER_EXPLAINER` stays `"fully_copy"`.

### EXPLAINER-006 — Run one explainer end to end (not done)

Make one explainer of about 2 minutes (finance or AI), once with a library set and once without. Check these:

- Discovery holds only the presenter and the set.
- No relations job runs and no narrator design job runs.
- The events are only narration, dialogue and pause.
- Presenter shots use the reference route with `fully_copy`. B-roll shots use the text route.
- The rendered video alternates between the presenter and B-roll, in one voice.

**Result (owner fills in):** Passed. The owner reported on 2026-10-28 that end-to-end explainers render well, with their music.

---

## 4. Known limits

- How well H3 keeps the presenter's face the same over many presenter shots is not tested.
- B-roll may still show text or invent a diagram, because the prompt can only ask H3 not to.
- `match_audio_duration` is left false for story shots. The audio is made as long as the clip by the placement, so the clip length is still decided by the shot plan.
- `shot_cut_repair_writer` has no explainer note in its instructions. It only has the code check, so a repair that adds a character to B-roll is refused and not corrected by the model.
- There are no automated tests, as asked. The changes were checked by running the code on throwaway data (migration up and down, project creation refusals, fixed discovery items, the FFmpeg filter, the planner and prompt writer on a presenter shot and a B-roll shot).

---

## 5. Captions and callouts: decisions

The goal is to make an explainer more engaging to watch. Captions follow the presenter's words, and callouts put the important things on screen.

| # | Decision |
|---|----------|
| E-9 | Captions and callouts are drawn by code on top of the finished picture at render time: one ASS subtitle file, burned in by FFmpeg (libass). H3 is still asked to draw no text, so E-7 stands for B-roll. |
| E-10 | This is for explainers only. A story project renders exactly as it does today. |
| E-11 | Two project settings, `captions` and `callouts`, are chosen on the create form and are on by default. They are only read at render time, so unlike `kind` they can be changed later in project settings without redoing anything. |
| E-12 | Caption words are the script's words (the speech units' text), never a transcript. Their timing comes from Parakeet word timestamps on each unit's TTS file, matched back to the script words. A unit that cannot be matched well gets estimated timing (each word gets its share of the unit's length by character count). |
| E-13 | Captions are word-synced: groups of 2 to 4 words, with the word being spoken highlighted. They are burned in only. No `.srt` file is made. |
| E-14 | Callouts are there to make the video more engaging, not to repeat the script, so the model may shorten, paraphrase or reframe. The types are `emphasis`, `number`, `question`, `comparison`, `list` and `section_title`. The presenter's name is never shown. |
| E-15 | Callout timing is loose. A callout names a speech unit and a rough phrase from it. Code finds the closest matching words in that unit's word timings and shows the callout there. If nothing matches well, it shows at the start of the unit. There is no word-for-word check. |
| E-16 | Code checks callouts for display rules only: text length per type, the gap between callouts, no two on screen at once, and a most-per-minute limit. One check is a **warning, never a refusal**: a `number` callout that shows a number the script does not say. |
| E-17 | The user reviews callouts on the board before rendering, and can edit the text, change the type or turn a callout off. An edit is stored as a new version. Only callouts that are turned on go to the render. |
| E-18 | Colours come from roles, not from each callout. The fixed roles are `number` (amber), `negative` (red) and `positive` (green). The `accent` role is picked by the model to suit the video. Code checks that the accent stays readable and uses a safe default when it does not. The caption highlight uses the accent. |
| E-19 | There is one layout per orientation, landscape and portrait, taken from the project's orientation. A landscape project is never reframed into portrait. |
| E-20 | Scripts are in English only. Parakeet's word timings are trusted for English. |

---

## 6. Captions and callouts: design

### 6.1 Where it runs

```text
speech units + TTS (unchanged)
  -> word timings: Parakeet on each unit's TTS file, matched to the script words   (EXPLAINER-007)
  -> callout plan: one model call, display checks, review on the board              (EXPLAINER-009)
  -> Render pressed: captions and callouts resolved to times and frozen in the timeline
  -> render job: writes one ASS file and burns it in during the final encode         (EXPLAINER-008, 010)
```

The word timings belong to the speech audio, so they are made again only when a unit's audio changes. The callout plan depends on the speech units, so changing the script makes it out of date. Nothing is resolved to times until Render is pressed, so a re-render of a stored timeline always gives the same picture.

### 6.2 Layout zones

The zones keep captions and callouts from ever covering each other.

| Element | Landscape | Portrait |
|---------|-----------|----------|
| Captions | Bottom-center, inside the title-safe area | Around the lower third, above the area Shorts and Reels cover with their buttons |
| Callouts on a presenter shot | Upper third, to one side of the presenter | Upper area, centered |
| Callouts on B-roll | Upper third | Upper area, centered |
| Section title | Centered. Captions are hidden while it shows | Centered. Captions are hidden while it shows |

The portrait safe-area margins are starting values taken from common platform guidance. The owner checks them on a phone in EXPLAINER-008.

### 6.3 Colour roles

| Role | Used for | Colour |
|------|----------|--------|
| `accent` | Caption highlight, `emphasis`, `question`, `section_title`, `list` | Picked by the model, readability-checked, with a fixed default |
| `number` | A neutral number | Amber |
| `negative` | Loss, risk, a warning, the weaker side of a `comparison` | Red |
| `positive` | Gain, growth, the stronger side of a `comparison` | Green |

Red is kept for negative numbers. In finance, red reads as a loss, so a neutral number is amber, not red.

---

## 7. Captions and callouts: phases

Run them in this order: 007, 008, 009, 010. EXPLAINER-009 can also run in parallel with EXPLAINER-008, because it only needs EXPLAINER-007. EXPLAINER-011 is optional and comes last.

Standard checks are those of `Implementation_phases.md` §3.5. Items marked **Planning decides** are left open on purpose and must be settled in the plan.

### EXPLAINER-007 — Caption settings and word timings

**Status:** Done (code). The playback check against the GPU server is still the owner's (see the completion notes).

**Objective.** Let the user turn captions and callouts on or off when creating an explainer, and give every spoken word of an explainer an exact start and end time.

**Current state.**
- `project` has `kind` and `speech_mode` (migration `0072` is the newest). The create form is `frontend/src/components/projects/CreateProjectModal.tsx`, the settings form `ProjectSettingsForm.tsx`, and the checks are in `services/projects.py` and `api/projects.py`.
- TTS is made per unit by `jobs/synthesize_speech.py` into `speech_unit_audio` (one row per speech, with its measured `duration_s`). The TTS provider returns no word timings.
- Parakeet already returns word timestamps (`providers/transcriber.py`, `SpokenWord`). `jobs/check_take_dialogue.py` and `services/dialogue_check.py` use it on take clips, and the dialogue check normalizes words (NFKC, lower case, apostrophes dropped) and compares them with `difflib.SequenceMatcher`.

**Scope.**
- Two new `project` columns, `captions` and `callouts`, both booleans and on by default, in a new migration. The create form shows them only for an explainer. Project settings can change them at any time.
- A word-timing job that runs Parakeet on a unit's TTS file (narration and dialogue) after the speech is made. Because presenter shots use `fully_copy`, the voice in the clip is this same file, so one timing serves both kinds.
- Matching: the heard words are matched to the script words with the dialogue check's normalization. Each script word gets the time of its matched word. An unmatched word is given a time between its matched neighbours. When too few words match, the whole unit uses estimated timing (E-12), and this is recorded.
- Storage: one result per speech audio, holding the script words in order with `start` and `end` in seconds from the start of the file, and how the times were made (`parakeet` or `estimated`). The result is tied to the audio, so a new speech gets new timings.
- The job runs only for explainers whose `captions` or `callouts` setting is on.
- **Planning decides:**
  - whether the timings are a new table or part of `speech_unit_audio`;
  - whether this is a new job type or a step added after the TTS job;
  - the match threshold below which a unit falls back to estimated timing;
  - how the board shows a unit whose timing was estimated.

**Out of scope.** Drawing captions (008). Callouts (009, 010). Story projects. Any language other than English.

**Dependencies.** EXPLAINER-002 to EXPLAINER-006.

**Expected outcome.** Each speech of an explainer has a stored list of its script words, each with a start and an end time, and the project's caption and callout settings are saved.

**Verification criteria.**
- A new explainer stores the two settings, and changing them in settings is saved.
- A story project shows neither setting and starts no word-timing job.
- For a sample of units, the stored times land on the spoken words when played back (within about 0.1 s).
- A unit whose speech was remade gets new timings, and an unchanged unit keeps its old ones.
- A forced bad match (for example, the wrong audio) falls back to estimated timing and is marked as estimated.
- Standard checks.

**Completion checklist.**
- [x] Migration and project settings, create form, settings form
- [x] Word-timing job, matching, fallback, storage
- [x] Docs (`DATABASE_STRUCTURE.md`), standard checks

**Completion notes.** Done on 2026-10-28.

What was decided (the four "Planning decides" items):

- **Storage:** a new table `speech_word_timing`, one row per `speech_unit_audio` row (`UNIQUE`, `CASCADE`). `speech_unit_audio` is unchanged, so a remade speech (a new audio row) gets new timings and an unchanged unit keeps its row.
- **Job:** a new job type `time_speech_words` (`jobs/time_speech_words.py`, built like `check_take_dialogue`). It is queued in the same transaction that stores a speech (`synthesize_speech_unit.store_result`) for an explainer with `captions` or `callouts` on. A new pipeline step `word_timings` ("Time the words", after "Speak the lines") queues it for any stored speech without a timing (speech made before this phase, captions turned on later, or a failed job). The step is `off` on the board for a story and for an explainer with both switches off.
- **Threshold:** a new setting `word_timing_match_threshold`, 70 percent, in the Speech group. It is the share of script tokens that match a heard token exactly. Below it, the unit gets estimated timing.
- **Board:** each unit's speech line shows a badge: "Words timed" (green), "Timing estimated" (orange, hover shows the match percent against the threshold and what was heard), "Timing words" (blue) or "Timing failed" (red, hover shows the error).

How the matching works (`services/word_timings.align`): script and heard words are normalized with the dialogue check's rules and matched with `SequenceMatcher`. A matched word takes the heard time. A script span that replaces a heard span (for example "five" heard as "5") shares that span's time by character count. A script word nothing was heard for gets a share of the gap between its timed neighbours. A word with no letters (for example a dash) gets a zero-length time at the end of the word before it.

Checked on throwaway data: migration `0073` up, down and up again, and `alembic check` shows no difference for the new table; `align` on a clean match with "five" heard as "5", a missing word, the wrong audio and an empty transcript; a story project refuses `captions` and `callouts` on PATCH and keeps the defaults. Ruff, `npm run lint` and `npm run typecheck` pass, and `schema.d.ts` was regenerated. There are no automated tests, as asked.

**Still for the owner (needs the GPU server and listening):** for a sample of units, play the audio and check that the stored times land on the spoken words within about 0.1 s, and make one speech again to see that it gets new timings. The 70 percent threshold is a starting value: how often Parakeet writes numbers as digits will only show on real units.

### EXPLAINER-008 — Word-synced captions burned into the render

**Status:** Done (code). The playback and phone checks are still the owner's (see the completion notes).

**Objective.** When `captions` is on, the rendered explainer shows word-synced captions, with the word being spoken highlighted.

**Current state.**
- `services/story_render_plan.py` builds the timeline (`TIMELINE_VERSION = 2`) with every shot, every narration speech (`start_ms`) and the dialogue spans. It is frozen on the job by `services/story_renders.start_render`.
- `jobs/render_story.py` renders only that timeline. The final encode is `render_commands.final_encode_args`, which already re-encodes the picture with `libx264`, so adding a video filter there costs little.
- The backend image is `python:3.13-slim` with Debian's `ffmpeg`. Debian's build is expected to include libass, but this has not been checked. The image has no fonts.

**Scope.**
- At Render, for an explainer with `captions` on, the timeline gains a caption list. Each entry is a group of 2 to 4 words with its start and end on the story timeline, and each word in it carries its own time. Each time is the unit's start plus the word's time inside its speech. The timeline version goes up by one.
- Grouping rules:
  - break at punctuation and at pauses;
  - a group never spans two units;
  - each group stays up for at least about 0.4 s;
  - nothing is shown during a pause.
- The render job writes an ASS file from the frozen captions and burns it in during the final encode, using karaoke tags for the highlight.
- A font file is bundled with the app, and FFmpeg is pointed at it, so renders look the same on any machine.
- Two layouts, landscape and portrait (§6.2). The highlight uses a fixed default colour until EXPLAINER-010 adds the accent.
- A render with `captions` off, and any story render, runs exactly the FFmpeg commands it runs today.
- **Planning decides:**
  - which font to bundle, and its licence (a bold sans-serif such as Inter or Montserrat, both under the SIL Open Font License);
  - the font sizes, line lengths and margins for each orientation;
  - whether caption text keeps its punctuation, and whether it is upper case;
  - how a missing word timing is handled at Render (fall back to estimated timing with a warning, or block the render).

**Out of scope.** Callouts (009, 010). An `.srt` file (E-13). Model-chosen colours (010).

**Dependencies.** EXPLAINER-007.

**Expected outcome.** A landscape and a portrait explainer both render with readable, word-synced captions that follow the voice, on presenter shots and B-roll alike.

**Verification criteria.**
- `ffmpeg -filters` in the backend container lists the `subtitles` filter.
- The highlight moves with the voice, with no visible lag, over a whole render.
- No caption shows during a pause, and no group mixes two units.
- On a phone, portrait captions are not covered by the Shorts or Reels buttons (the owner checks).
- Turning `captions` off gives a video with no captions. A story render is unchanged.
- The render's frame count, length and loudness checks still pass.
- Standard checks.

**Completion checklist.**
- [x] Caption list in the timeline, version bump
- [x] ASS writer, bundled font, burn-in in the final encode
- [x] Two layouts; docs; standard checks
- [ ] Owner check on a phone

**Completion notes.** Done on 2026-10-28.

What was decided (the four "Planning decides" items):

- **Font:** Montserrat ExtraBold (SIL Open Font License), `backend/app/assets/fonts/Montserrat-ExtraBold.ttf`. Its licence is in `backend/app/assets/licenses/Montserrat-OFL.txt`, outside the fonts folder because libass logs an error for every non-font file in `fontsdir`. The ASS family name is `Montserrat ExtraBold`, regular style.
- **Text:** upper case, sentence punctuation removed (`. , ! ? ; :`, quotes, brackets and dashes), apostrophes, hyphens inside a word, `%`, `$`, `-` before a number and the points of numbers such as "3.5" and "1,000" kept.
- **Layout** (fractions of the output size; `services/caption_plan.style_for`): landscape has a font of 6.5 percent of the height, a bottom margin of 9 percent and at most 28 characters in a group. Portrait has a font of 4.2 percent of the height, a bottom margin of 28 percent (above the Shorts and Reels buttons) and at most 14 characters in a group (the plan said 16, but 16 capitals of this font do not fit between the side margins). The highlight is `#FFD60A` until EXPLAINER-010.
- **Missing timing at Render:** the speech gets estimated times (character count, as EXPLAINER-007's fallback) and the plan carries one warning, `caption_timing_estimated`, which the render panel shows before Render is pressed. A speech whose stored timing is itself `estimated` gives no warning.

What was built:

- `services/caption_plan.py` (pure): text rule, style, grouping, story-time mapping, and reading the frozen track back. A group is at most 4 words, split into near-equal parts (5 words are 3 and 2). It breaks at a sentence mark and at a pause of 0.30 s or more, never holds two speeches, stays up at least 0.4 s unless the next group starts sooner, and a gap under 0.25 s inside a speech is closed.
- `services/caption_ass.py` (pure): the ASS file. **Deviation from the scope:** the highlight is not made with `\k` karaoke tags, because they leave every word already spoken highlighted. Each word gets its own event, which shows the whole group with that one word coloured; the events of a group meet exactly, so only the word being spoken is highlighted.
- `story_render_plan`: timeline version 3 with `captions` (null for a story and for captions off), narration and dialogue speeches alike. `story_renders` reads `speech_word_timing` only for an explainer with captions on, and a render is out of date when the captions setting changed since. Music placement (`next_render_sources`) is made without captions.
- `render_commands.final_encode_args(captions=...)` adds the `subtitles` filter in front of the picture; without it the command is exactly what it was. The two paths in the filter are checked against a safe character set. `jobs/render_story.py` has a new phase, "writing the captions", writes the file in the temp folder and records `output.captions`.

Checked on throwaway data: the backend container's FFmpeg 7.1.5 lists `subtitles` and `ass`, and burns a test ASS with the bundled font through `fontsdir` (the picture shows Montserrat) with an unchanged frame count. A plan was built for a landscape and a portrait output with a narration, a dialogue and an estimated speech, read back with `parse_timeline`, written as ASS and burned in with `final_encode_args`: the frame count equals the timeline's, and a render with `captions` off has no `subtitles` filter and the old `-map 0:v:0`. A path with a space and a quote is refused. Ruff passes. There are no automated tests, as asked.

**Known limits.** A presenter shot whose speech was made again after its take uses the current speech's timing while its clip holds the old audio (the take already shows as out of date). A speech that gets real timing after a render with estimated timing does not make that render out of date. libass logs "Fontconfig error: No writable cache directories" in the container; it is harmless (the bundled font is loaded from `fontsdir`), and it is only shown if a render fails.

**Still for the owner (needs the GPU server and watching):** play one landscape and one portrait explainer and check that the highlight follows the voice over the whole render; on a phone, check that the portrait captions are not covered by the Shorts or Reels buttons (the 28 percent margin is a starting value); render once with `captions` off, and one story, and compare them with before. The backend image must be rebuilt (`docker compose up -d --build backend`) for the new code and font to be in it.

### EXPLAINER-009 — Callout plan and review

**Status:** Not Started

**Objective.** Have the model suggest engaging callouts for an explainer, check them for display rules only, and let the user review and edit them on the board.

**Current state.**
- Each scene's speech units are stored in `speech_units` (versioned). Every other planning stage follows the same pattern of a writer, a job, a versioned artifact with provenance, a pipeline step (`services/story_pipeline_targets.py`) and a board panel (`frontend/src/components/board/StepPanel.tsx`).
- Explainers already have a Story Bible, which gives the tone and style.

**Scope.**
- One model call per explainer. It reads the Story Bible and every scene's speech units in order, and returns:
  - the `accent` colour (a hex value) with a short reason;
  - the callouts. Each callout has a `type` (E-14), a `role` (`accent`, `number`, `negative` or `positive`), its text (a `list` has up to three items and a `comparison` has two sides, each with its own phrase), the unit it belongs to, and a rough phrase from that unit.
- Instructions to the model:
  - callouts are there to keep the viewer watching: a hook question, the key idea in a few words, the big number, a clear comparison, a list that builds up;
  - fewer, stronger callouts beat many;
  - never show the presenter's name;
  - never repeat a whole sentence of the script.
- Code checks (E-16):
  - text length per type;
  - the minimum gap between callouts;
  - no two callouts on the same stretch of speech;
  - the most-per-minute limit.

  A failing answer is retried as in every other stage. The phrase is never checked word for word (E-15).
- A warning, not a refusal, when a `number` callout's number is not said in its unit. Number words such as "five" and "ten lakh" count as said.
- Accent check: the colour must be a valid hex value and readable over the caption style. Otherwise the default is stored, with a note.
- Storage: a new versioned artifact per project, with `source` `ai` or `manual`. Its provenance records the `speech_units` versions it was made from. Changing any scene's speech units makes it out of date.
- A board panel that lists the callouts in order, each with its type, text, role, unit, phrase, an on/off switch and any warning. The user can edit text, type and role. Saving makes a new `manual` version, checked by the same display rules.
- The step runs only for explainers with `callouts` on.
- **Planning decides:**
  - the starting limits (suggested: at least 4 s between callouts, at most 6 per minute, length limits per type);
  - which model runs the call;
  - whether the review panel can add a new callout or only edit and turn off existing ones;
  - how the readability check is measured (suggested: the WCAG contrast ratio against the caption outline colour).

**Out of scope.** Drawing callouts (010). Any change to shot planning (011).

**Dependencies.** EXPLAINER-007 (the `callouts` setting).

**Expected outcome.** A 2-minute explainer gets a short list of callouts the owner would actually want on screen, and the owner can adjust them in a minute.

**Verification criteria.**
- The plan passes the display checks, and a forced overlap or too many callouts is retried.
- A made-up number shows a warning in the panel and does not block anything.
- No callout shows the presenter's name.
- An edit is stored as a new version, and turning a callout off keeps it out of the render list.
- Changing the script makes the plan out of date.
- The owner judges the callouts on one real explainer.
- Standard checks.

**Completion checklist.**
- [ ] Writer (instructions, parser, display checks, number warning, accent check)
- [ ] Job, versioned storage and provenance, pipeline step
- [ ] Board panel with edit and on/off
- [ ] Owner judges one real explainer; docs; standard checks

**Completion notes.** _To be filled in._

### EXPLAINER-010 — Callouts drawn on the render, and colours

**Status:** Not Started

**Objective.** Draw the reviewed callouts on the rendered explainer, animated and coloured by role, and use the model's accent for the caption highlight.

**Current state.** EXPLAINER-008 burns an ASS caption file into the final encode. EXPLAINER-009 stores reviewed callouts with a unit and a phrase each, and the accent colour.

**Scope.**
- At Render, for an explainer with `callouts` on, each callout that is turned on is resolved to a time. Code finds the closest match for its phrase among the unit's timed words. With no good match, the callout shows at the unit's start (E-15). The callout stays up for at least about 2 s, or until its unit ends, whichever is longer.
- Each `list` item and each `comparison` side is resolved by its own phrase, so they build up as they are spoken.
- Each callout's shot (presenter or B-roll) is looked up so it is placed in the right zone (§6.2). The resolved callouts are frozen in the timeline, next to the captions.
- ASS styles and simple animations per type, for example:
  - a fade or slide in, with a box behind the text;
  - a short scale-up "pop" for `number`;
  - items appearing one by one for `list`;
  - two sides for `comparison`, side by side in landscape and stacked in portrait;
  - a centered `section_title`, with captions hidden while it shows.
- Colours by role (§6.3), with the caption highlight switching from the fixed default to the stored accent.
- A render with `callouts` off draws no callouts, and the captions are unaffected.
- **Planning decides:**
  - the exact animation timings;
  - the box style;
  - how far a phrase may differ before the callout falls back to its unit's start.

**Out of scope.** Charts or diagrams drawn from data (a later phase, if wanted). Telling B-roll to leave room (011).

**Dependencies.** EXPLAINER-008, EXPLAINER-009.

**Expected outcome.** A finished explainer with captions and a handful of well-timed, animated callouts that never cover each other or the captions.

**Verification criteria.**
- Each callout appears on or near its phrase, and a callout whose phrase does not match appears at its unit's start.
- No callout overlaps another or the captions, in landscape and in portrait.
- The colours follow the roles, and the caption highlight uses the accent.
- Turning `callouts` off removes them, and the captions stay the same.
- The owner judges one landscape and one portrait explainer as more engaging than the same video without callouts.
- Standard checks.

**Completion checklist.**
- [ ] Time resolution and zones in the timeline
- [ ] ASS styles and animations per type and orientation; colour roles
- [ ] Owner check in both orientations; docs; standard checks

**Completion notes.** _To be filled in._

### EXPLAINER-011 — Room for callouts in B-roll (optional, later)

**Status:** Not Started

**Objective.** Make B-roll leave empty space where a callout will sit, so the text never lands on the subject of the shot.

**Scope.** Planning decides. The likely shape: the callout plan runs before shot definition, and a B-roll shot that carries a callout gets one line in its definition and prompt asking for clear space in the callout's zone. With `callouts` off, every prompt stays as it is today.

**Out of scope.** Any change to presenter shots.

**Dependencies.** EXPLAINER-010, and the owner's judgement after it that callouts too often land on busy parts of the picture.

**Completion notes.** _To be filled in._

---

## 8. Captions and callouts: known risks

- Parakeet may hear a number or a name differently from how the script writes it ("5" for "five"). The matching handles a few differences, and a unit with too many falls back to estimated timing.
- The portrait safe-area margins are starting values, and the platforms change their buttons from time to time.
- The model may suggest callouts that are bland or too many. The display limits and the review panel are the guard, and the instructions favour fewer, stronger callouts.
- Burning in captions means a video without captions needs a second render with `captions` off.

---

## 9. Progress log

| Id | Status | Notes |
|----|--------|-------|
| EXPLAINER-001 | Done | Owner reported it passed on 2026-10-28. |
| EXPLAINER-002 | Done | Migration `0072`. |
| EXPLAINER-003 | Done | |
| EXPLAINER-004 | Done | Story prompts checked to be unchanged. |
| EXPLAINER-005 | Done | Run by the owner through EXPLAINER-006. |
| EXPLAINER-006 | Done | Owner reported it passed on 2026-10-28. |
| EXPLAINER-007 | Done | Caption settings and word timings. Migration `0073`. Owner still checks the timings by playback. |
| EXPLAINER-008 | Done | Word-synced captions burned in. Timeline version 3. Owner still checks the highlight and the portrait margin by playback and on a phone. |
| EXPLAINER-009 | Not Started | Callout plan and review. Can run in parallel with 008. |
| EXPLAINER-010 | Not Started | Callouts drawn, and colours. |
| EXPLAINER-011 | Not Started | Optional, later. |
