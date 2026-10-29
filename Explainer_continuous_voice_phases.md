# Vision Studio — Explainer Continuous Voice Phases

Today an explainer's speech is made line by line, and each line decides the picture: an on-camera line (`dialogue`) is its own TTS file and its own presenter shot, and a voice-over line (`narration`) is another TTS file shown over B-roll. This causes two problems the owner saw on project 42:

- **The pace changes with the picture.** Dialogue is made in `direction` mode with an emotion instruction ("urgent, breathless") at guidance 4. Narration has no emotion field (`event_extraction_writer`, `speech_unit_planner`), so it is made in `clone` mode with no instruction at guidance 1 and copies the calmer style of the voice's reference recording. On project 42 dialogue runs at about 163 words per minute and narration at about 144, and narration sounds flatter.
- **Cuts can only fall between lines.** A shot changes only at a speech unit boundary, and a presenter shot must hold exactly one whole line. The video cannot cut to B-roll halfway through a sentence, which is what makes an edited explainer feel fluent.

This plan fixes both at the root: **the voice is made first, as one continuous take per scene, and the picture is cut on top of it.** The same recording plays whether the presenter is seen or not, so the pace cannot change at a cut, and a cut can fall on any word.

- The conventions of `Implementation_phases.md` (§3.3 to §3.5, §6) apply unchanged. Table and column details go in `DATABASE_STRUCTURE.md`. The newest migration when this was written was `0074`; the Audio video lab added `0075`, FLOW-002 added `0076` and FLOW-003 added `0077`; FLOW-004 added no migration.
- Written 2026-10-29, from a design discussion with the owner about narration pace and cutting to B-roll mid-sentence.
- FLOW-001 is a go/no-go trial. Nothing else starts until it passes. It passed on 2026-10-29 (see its result).

---

## 1. Decisions

| # | Decision |
|---|----------|
| F-1 | This is for explainers only. A new project setting `voice_track` has the values `lines` (today's behaviour) and `continuous`. It is chosen when the project is created and never changed, like `kind`. New explainers default to `continuous`. Existing explainers stay `lines` and render exactly as today. A story project is byte-for-byte unchanged (as E-8). |
| F-2 | In `continuous` mode the presenter's speech is made as **one take per scene**: the text of the scene's speech units joined in order, spoken in one TTS job. The speech units stay: they are still the structure of the text (events, captions, callouts), but each one becomes a span inside the scene's take instead of a file of its own. |
| F-3 | The take is made in `direction` mode with **one delivery instruction for the whole take**, so every sentence has the same pace and energy. The instruction comes from a project-level presenter delivery text. Per-line emotions are not sent in this mode. |
| F-4 | The take's word timings (Parakeet and the matching of EXPLAINER-007) are the clock for everything after it: where each unit sits, where cuts can fall, captions, callouts and the music. |
| F-5 | **The picture is planned on top of the voice.** Whether the presenter is seen is a picture decision, not a speech decision. A cut may fall before any word, including inside a sentence. The planner picks the word each shot starts on, and code turns that into a time. The `dialogue` / `narration` labels from the events become a hint for the planner. |
| F-6 | A shot's length follows its cut points and is **not** moved onto H3's lengths. Its clip is made at the shortest H3 length that covers the shot, and the render trims the extra frames, which `render_commands.trim_args` already does. Cutting a clip's tail is safe here, because the voice comes from the take, not from the clip. |
| F-7 | A presenter shot sends H3 the **window of the take** the clip covers: from the shot's start, for the clip's length, as `fully_copy` starting at 0. A window that runs past the end of the take is padded with silence. A presenter shot is at most 345 frames (14.375 s), which is also under H3's 15 s audio limit. **The marker is always `fully_copy`**: in FLOW-001 both markers worked well, and `fully_copy` was slightly better than `partially_copy`, so `partially_copy` is not offered here. |
| F-8 | By default the render plays each scene's take as the voice layer, and the voice inside a presenter clip is not used: it copies the same audio, and using the take avoids any seam or jump at a cut. B-roll keeps H3's own sound, ducked under the voice as today. |
| F-9 | **The owner can switch one presenter shot to its clip's own voice.** Each presenter shot has a voice source: `take` (the default) or `clip`. With `clip`, the render mutes the take for exactly that shot's span and plays the clip's sound there instead, as the Audio video lab's "Mixed" video does. This is for a shot whose lip sync looks off against the take, or where the clip's voice sounds clearer (in FLOW-001 the H3 audio sounded slightly clearer than the TTS, probably because the two come out in different audio formats). The choice belongs to the shot, not to the clip, so it stays when the clip is made again. Changing it only makes the render out of date. |

---

## 2. How it works

```text
create explainer (voice_track continuous, presenter delivery)
  -> Story Bible, discovery, events, speech units          (unchanged)
  -> scene take: one TTS job per scene, one instruction    (FLOW-003)
  -> word timings of the take, and each unit's span in it  (FLOW-004)
  -> cut planning on the timed words: presenter or B-roll,
     each shot starting on a word                          (FLOW-005)
  -> timeline: shots at their cut times, clips at the
     shortest H3 length that covers them                   (FLOW-006)
  -> generation request: presenter = window of the take as
     fully_copy, B-roll = text route                       (FLOW-007)
  -> render: take as the voice layer (or a presenter clip's
     own voice where the owner switched it on), clips trimmed,
     captions, callouts and music from the take's timings  (FLOW-008)
```

### 2.1 An example

A scene's take is 19.70 s long, with a tail of 0.30 s, so the scene lasts 20.00 s. The planner answers with three shots:

| Shot | Starts on the word | Cut time | Type | Clip made at | Audio sent to H3 |
|------|--------------------|----------|------|--------------|------------------|
| 1 | word 1, "Microsoft" | 0.00 s | presenter | 5.875 s (141 frames) | take from 0.00 s to 5.875 s |
| 2 | word 15, "and" (mid-sentence) | 5.80 s | B-roll | 9.416 s (226 frames) | none |
| 3 | word 38, "So" | 14.90 s | presenter | 5.166 s (124 frames) | take from 14.90 s to 20.066 s, the part after 19.70 s padded with silence |

The render shows shot 1 for 5.80 s (the last 0.075 s of its clip is cut), shot 2 for 9.10 s and shot 3 for 5.10 s, all over the one take. The presenter's lips in shot 1 follow the take up to the cut, and the voice carries straight on over the B-roll. If the owner switches shot 3 to its clip's voice (F-9), the take is muted from 14.90 s to 20.00 s and the clip's own sound plays there; shots 1 and 2 are unchanged.

---

## 3. Phases

Run them in order: 001, 002, 003, 004, 005, 006, 007, 008, 009. FLOW-001 is a gate. FLOW-002 and FLOW-003 can be built together.

Standard checks are those of `Implementation_phases.md` §3.5. Items marked **Planning decides** are left open on purpose and must be settled in the plan of that phase.

### FLOW-001 — Trial: one long take, its timings, and a window clip (owner, done)

**Status:** Done (2026-10-29)

**Why:** the design relies on three things nobody has checked yet: that Breeze TTS keeps one pace over a whole scene, that Parakeet times a long take well, and that H3 gives good lips with a `fully_copy` window that starts and ends inside a sentence.

**How:**

1. **Long take.** In the Voice lab, use the presenter's voice (voice 6 on project 42) in `direction` mode with one instruction, for example "Speak fast and urgently, like breaking news, with high energy and punchy emphasis." Use the full text of one scene of project 42, for example `scene_exit_offer_terms` (its four units joined in order). Make one scene of more than 1000 characters too, because the job splits longer text into pieces made one after the other (`speech_chunks.split_script`) and joins them.
2. **Listen.** Is the pace the same from start to end? Can you hear the join between the pieces of the longer one (a change of pace, loudness or tone, or a cut breath)? Compare it with the current per-line files of the same scene.
3. **Timings.** Run the word-timing step's matching on the take (the agent can run `word_timings.align` on the Parakeet output for you) and check by playback that a sample of words land within about 0.1 s.
4. **Window clip.** Cut a window of the take that starts at a word inside a sentence and is a `17n + 5` frame length, for example 124 frames (5.167 s). Replace `3.20` with the start time of the chosen word:

   ```bash
   ffmpeg -ss 3.20 -i take.wav -t 5.166667 -af "apad=whole_dur=5.166667" -c:a pcm_s16le window.wav
   ```

   In the Character lab, make a clip with the presenter's pictures, `fully_copy` and `match_audio_duration` on, using `window.wav`. Judge: do the lips follow the words from the first frame, does a presenter already mid-sentence look natural, and is there no other sound?

**If the long take fails:** continuous takes can be made per paragraph instead of per scene (several takes per scene, each under 1000 characters), with the same instruction. The rest of the design is unchanged. Record the choice in FLOW-003.

**If the window clip fails:** cuts into a presenter shot are limited to sentence ends and pauses of 0.3 s or more, so a window always starts on a fresh phrase. Record the choice in FLOW-005.

**Result (2026-10-29): passed.** The owner ran the trial in the character's Audio video lab. The lab speaks a whole text as one take, times its words with Parakeet, cuts each marked part out of the take as a window padded to an H3 length, makes an H3 clip from each window, and renders two videos: "Mixed" (the take in the gaps, each clip's own sound inside its part) and "TTS only" (the take throughout, the clips muted). Findings:

- Both markers work well. `fully_copy` is slightly better than `partially_copy`, so the pipeline always uses `fully_copy` (F-7).
- Both renders worked well, so the take stays the default voice layer (F-8).
- In the mixed video the voice is slightly clearer where it comes from the H3 clip, probably because H3 and the TTS output audio in different formats. So the owner can switch a single presenter shot to its clip's voice, for example when its lip sync looks off (F-9, built in FLOW-008).
- Neither fallback is needed: takes stay per scene (FLOW-003), and cuts into a presenter shot may fall inside a sentence (FLOW-005).

### FLOW-002 — The `voice_track` setting and the presenter delivery

**Status:** Done (2026-10-29)

**Objective.** Let the owner choose continuous voice when creating an explainer, and give the presenter one delivery text that every take uses.

**Current state.**
- `project` has `kind`, `speech_mode`, `captions` and `callouts` (migration `0074` is the newest). The create form is `frontend/src/components/projects/CreateProjectModal.tsx`, the settings form `ProjectSettingsForm.tsx`, and the checks are in `services/projects.py` and `api/projects.py`.
- The TTS instruction is written per unit from its emotion (`speech_synthesis.instruction_for`), at most 500 characters (`speech_synthesizer.INSTRUCTION_MAX_CHARS`).

**Scope.**
- A new `project` column `voice_track` (`lines` or `continuous`), in a new migration. Existing rows get `lines`. The create form shows it only for an explainer, defaulting to `continuous`. It cannot be changed later, and a story always has `lines`.
- A presenter delivery text, at most 500 characters, used as the take's instruction.
- **Planning decides:**
  - whether the delivery text is a project column the owner writes, or is written by the model from the Story Bible's tone (with the owner able to edit it);
  - whether a scene may override it (for example a calmer closing scene);
  - the default text when none is given.

**Out of scope.** Making any speech (003).

**Dependencies.** FLOW-001 passed.

**Expected outcome.** A new explainer stores `voice_track` and a delivery text. Existing projects and stories show no change.

**Verification criteria.**
- A new explainer stores the setting, and a PATCH that changes it is refused.
- A story shows no setting and always has `lines`.
- Standard checks.

**Completion checklist.**
- [x] Migration, project checks, create form
- [x] Delivery text and its default
- [x] Docs (`DATABASE_STRUCTURE.md`), standard checks

**Completion notes.** Migration `0076` adds `project.voice_track` (`lines` or `continuous`, default `lines`, CHECK `ck_project_voice_track_valid`) and `project.presenter_delivery` (nullable text). Decisions made in planning:

- **Delivery source.** The delivery text is a nullable project column the owner may write. When it is empty, `services/explainer.presenter_delivery` returns the newest Story Bible's `storytelling_style.narration` as "Speak in this style: ...", and when there is no Bible, `DEFAULT_PRESENTER_DELIVERY` ("Speak clearly and confidently at a lively, steady pace, like a friendly expert explaining to one viewer, with natural emphasis on key words and numbers."). No model job was added. The result is cut to 500 characters and never stored. FLOW-003 calls it.
- **Editable.** The delivery text can be changed at any time in the project settings, only for a continuous explainer (PATCH on any other project gets 422). `voice_track` cannot be changed: a PATCH that sends it gets 422.
- **Scene override.** Not built: one text per project.
- **Creation.** An explainer defaults to `continuous` (the create form has a "Voice" choice and an optional delivery box). A story is always `lines`; a story that asks for `continuous`, or sends a delivery text, gets 422. The settings page shows a Voice panel for an explainer only.

Nothing reads `voice_track` yet, so no speech, plan or render changes. The OpenAPI schema (`schema.d.ts`) was generated from the local code, because the running backend image has not been rebuilt. The owner still has to rebuild it (`docker compose up -d --build backend`) so migration `0076` is applied, and to create one explainer in the browser to see the form.

### FLOW-003 — One voice take per scene

**Status:** Done (2026-10-29). Listening to the takes is the owner's (see the completion notes).

**Objective.** In `continuous` mode, make each scene's speech as one take with the presenter's voice and the delivery instruction.

**Current state.**
- `services/speech_synthesis.py` queues one `synthesize_speech_unit` job per unit and writes one `speech_unit_audio` row per job. A unit's audio is reused when its key (text, voice, mode, instruction) already has audio.
- `jobs/synthesize_speech.py` (`SpeechHandler`) already makes a long text as pieces of at most 1000 characters, all with the same voice, seed and guidance, and joins them (`speech_audio.join_wavs`).
- The narrator is the presenter's voice (E-4), so one voice speaks every unit.

**Scope.**
- For a `continuous` explainer, the speech step makes one take per scene instead of one file per unit. The take's text is the scene's units joined in order, each ending with its own punctuation. It uses `direction` mode, the delivery instruction and guidance 4.
- The take's key is a hash of the joined text, the voice and the instruction, so an unchanged scene is never made again, and changing one line remakes that scene's take only.
- The board shows one take per scene, with its state (`none`, `in_progress`, `ready`, `failed`, `out_of_date`) worked out on every read, as for units today.
- A `lines` project is unchanged.
- **Planning decides:**
  - whether a take is a new table, or a `speech_unit_audio` row with no unit (with its own `kind`);
  - whether takes are per scene or per paragraph (from FLOW-001);
  - how a sentence break is made audible between units (for example a full stop and a new line, or nothing extra).

**Out of scope.** Timings (004). Any change to the picture.

**Dependencies.** FLOW-002.

**Expected outcome.** Every scene of a continuous explainer has one take, spoken at one pace.

**Verification criteria.**
- The owner hears no change of pace between what used to be dialogue and narration.
- Changing one line makes only that scene's take out of date.
- A `lines` explainer and a story make exactly the jobs they make today.
- Standard checks.

**Completion checklist.**
- [x] Take storage, key and state
- [x] Speech step branch and board
- [x] Docs, standard checks

**Completion notes.** Done on 2026-10-29. Migration `0077`. Decisions made in planning:

- **Storage.** A take is a `speech_unit_audio` row with `kind = 'take'`, `unit_id` NULL and `speaker_id` NULL (migration `0077` makes `unit_id` nullable and adds `take` to the `kind` CHECK). No new table and no new job type: the `synthesize_speech_unit` job and its handler are used as they are, and `speech_word_timing` already points at `speech_unit_audio`, so FLOW-004 needs no new table. The downgrade deletes the take rows, which is stated in the migration.
- **Per scene.** FLOW-001 passed, so takes are per scene. A scene over 1000 characters is made in pieces by the existing chunker.
- **Sentence break.** The unit texts are joined with one space and nothing else, so the take reads exactly as the script does (a unit that was cut at a comma stays a comma).
- **Key and state.** `take_key` is the SHA-256 of `{take, text, voice_id, mode: direction, instruction}`, so it never equals a unit's key. A take's state (`unavailable`, `none`, `in_progress`, `failed`, `ready`, `out_of_date`) is worked out on every read by the rules of a unit, against the scene's earlier takes. The reasons say whether the scene's text, the presenter's voice or the delivery changed. The voice is the narrator's (the presenter's, E-4) and the instruction is `explainer.presenter_delivery` (FLOW-002); guidance is 4.
- **Where.** `speech_synthesis.state` gives each scene a `take` and the state a `continuous` flag; `start_take` and Make all queue one take per scene that is not ready or in progress. The units of a continuous explainer are refused ("This explainer speaks each scene as one take"). New route `POST /api/projects/{id}/speech-audio/{scene_id}/take/run`. The pipeline step `speech_synthesis` has one target per scene take (`take:{scene_id}`), and an out-of-date take shows in the stale list as "Scene N, voice take". The speech panel shows a take line (status, length, player, Make) in place of the per-unit buttons.
- **Not timed yet.** `synthesize_speech_unit` does not queue word timing for a take (FLOW-004).

**Interim effect.** For a continuous explainer, the `word_timings` step, shot planning and everything after them wait for unit audio that the project no longer makes, so the pipeline stops after the takes until FLOW-004 and FLOW-005 read them. A `lines` explainer and a story are unchanged.

Checked on throwaway data: migration `0077` up, down and up again (with a word timing kept across the upgrade, deleted with its take on the downgrade), and `alembic check` shows only the `FLOAT` against `REAL` differences that were there before. On a continuous project with two scenes: one take per scene with the joined text, direction mode, the default delivery and guidance 4; Make all made 2 jobs; after storing both, both are `ready`; changing one unit of the first scene made only that take `out_of_date` (the other stayed `ready`), and Make all then made 1 job and skipped the other; a unit's run was refused; a take key differs from the unit key of the same text. On a lines project: no take, `continuous` false, Make all made 4 jobs (3 and 1 units) whose input has the same keys as before, and a take run was refused. Ruff, `npm run lint` and `npm run typecheck` pass; `schema.d.ts` was generated from the local code (the running backend has not been rebuilt). There are no automated tests, as asked.

**Still for the owner (needs the GPU server and listening):** rebuild the backend image (`docker compose up -d --build backend`) so migration `0077` applies, make the takes of one continuous explainer, and listen for one pace across what used to be dialogue and narration.

### FLOW-004 — Word timings of the take, and each unit's span

**Status:** Done (2026-10-29). Playing the timings back against the GPU server is the owner's (see the completion notes).

**Objective.** Give every word of a take its time, and work out where each speech unit starts and ends inside it.

**Current state.**
- `jobs/time_speech_words.py` runs Parakeet on one speech file and `word_timings.align` matches the heard words to the script words. Results are stored in `speech_word_timing`, one row per `speech_unit_audio` row. A unit below `word_timing_match_threshold` (70 percent) gets estimated timing.

**Scope.**
- The word-timing job runs on each take. Since the take's text is the units joined in order, each script word belongs to one unit, so each unit's span is the time of its first word to the time of its last word.
- In `continuous` mode the timing job always runs, whatever `captions` and `callouts` say, because the cut planning needs it.
- A take whose match falls below the threshold cannot go on to cut planning, and the board says so (estimated timing is not good enough to cut on).
- **Planning decides:**
  - whether a take's timing reuses `speech_word_timing` (if a take is a `speech_unit_audio` row) or gets its own table;
  - whether the threshold for a take is the same 70 percent.

**Out of scope.** Using the spans in the render (008).

**Dependencies.** FLOW-003.

**Expected outcome.** Each take has its words timed, and each unit has a start and an end inside its scene's take.

**Verification criteria.**
- For a sample of words, the times land within about 0.1 s by playback.
- The unit spans meet in order with no overlap.
- A poorly matched take blocks cut planning with a clear message.
- Standard checks.

**Completion checklist.**
- [x] Timing on takes, unit spans
- [x] Block on a poor match, board
- [x] Docs, standard checks

**Completion notes.** Done on 2026-10-29. No migration. Decisions made in planning:

- **Storage.** A take's timing is a `speech_word_timing` row for its `speech_unit_audio` row (kind `take`). No new table, no new job type: `time_speech_words` already times `audio.text` against `audio.duration_s`.
- **Threshold.** The same setting, `word_timing_match_threshold` (70 percent). A take below it gets estimated timing, as any speech does, and is blocked from cut planning. The setting's help text says so.
- **Unit spans (tight).** A unit's span is the start of its first word to the end of its last word. Spans are in order and never overlap, and the pauses between units belong to no unit. They are worked out on every read from the take's timed words and the scene's current units, never stored. A take is only `ready` when its text is the current units joined, so the word counts line up; if they do not, the clock is blocked with a message.

What was built:

- `services/word_timings.times_takes(project)` and `wanted(project)`: a continuous explainer is always timed, whatever `captions` and `callouts` say. `synthesize_speech_unit.store_result` queues the timing job in the same transaction that stores a take (for a continuous explainer), and a unit's as before.
- `services/take_timings.py`: `unit_spans` (pure: each unit takes the next `len(text.split())` words, the split `align` uses) and `scene_clocks`, which gives each scene with a take its words and unit spans, or `blocked_reason`: no current take, being made, out of date, not timed yet or failed, or estimated ("Only X% of this take's words matched what was heard (Y% needed), which is too few to cut on. Make the scene's take again."). FLOW-005 reads it; nothing else does yet.
- Pipeline step "Time the words": for a continuous explainer, one target per scene take (`take:{scene_id}`). An estimated take is not done and carries the poor-match reason, so a run stops there and says why; a take being made is active. The step graph is unchanged (`shot_plans` does not wait on it), so a `lines` explainer is not affected.
- Board: `GET .../speech-audio` gives each take a `word_timing`; the take line shows the same badge as a unit ("Words timed", "Timing estimated" and so on) and, for an estimated take, a red line with the match and the threshold. `schema.d.ts` was regenerated from the local code (one new line).

Checked on stand-in data (the state functions replaced by fixed values): `wanted` and `times_takes` for a continuous explainer, a `lines` explainer with captions on, and a story; a three-unit take run through `word_timings.align`, with spans of 0 to 1.9 s, 2.0 to 2.9 s and 3.0 to 4.4 s (in order, no overlap, every word in exactly one unit, a hyphenated word kept whole, a unit with extra spaces); units that give too few words, too many words, or an empty unit refused; `scene_clocks` and the step's targets for a ready and timed take, an estimated one (blocked with the percentages), a take not made, out of date, being made, not timed and failed, and a scene with no units (no clock); a `lines` project has no clocks. Ruff, `npm run lint` and `npm run typecheck` pass. There are no automated tests, as asked. Not run: a real timing job on stored speech (it needs the GPU server).

**Still for the owner (needs the GPU server and listening):** rebuild the backend image (`docker compose up -d --build backend`), then make the takes of one continuous explainer and let the "Time the words" step time them. For a sample of words, play the take and check that the times land within about 0.1 s. Parakeet has only been tried on takes of the length used in FLOW-001, so how well it matches a long scene (and so how often the 70 percent bar blocks a take) is not yet known. No existing take is timed automatically: a take made before this phase is timed by the step the first time it runs.

### FLOW-005 — Cut planning on the voice

**Status:** Done (2026-10-29). Judging the cut points on real scenes is the owner's (see the completion notes).

**Objective.** Plan each scene's shots on top of the timed take, so a cut can fall on any word, including inside a sentence.

**Current state.**
- `services/shot_planning_writer.py` plans shots from events and speech units with their measured lengths. Each shot lists `source_event_ids`, `speech_unit_ids`, `type` and `target_duration`. For an explainer (`_EXPLAINER_NOTE`, `_check_explainer_shots`) a dialogue unit gets a `dialogue` shot of its own and narration is shown on B-roll.
- `services/shot_definition_writer.py` has an explainer note: the presenter is visible only in a shot that carries their line.

**Scope.**
- A new branch of the planner for `continuous` explainers. The user message gives the scene's words with their times, grouped by sentence, each sentence marked with its unit and the unit's `dialogue` / `narration` label as a hint, and the pauses between words.
- Each shot in the answer has: the index of the word it starts on (`start_word`), its type (`presenter` or a B-roll type), the events it shows and its description. The first shot starts on word 1. A shot ends where the next one starts, and the last one ends a short tail after the take.
- Code turns each `start_word` into a cut time inside the gap before that word, and checks:
  - the shots cover the take in order with no gap;
  - every shot is at least the planning minimum and at most 345 frames (14.375 s);
  - a presenter shot is at most 14.375 s, so its window fits H3's audio limit;
  - every event is shown, in order.
- The instructions ask for fluent cuts: open and close on the presenter, use B-roll for examples, numbers and descriptions, and cut on a natural phrase boundary (a comma or a short pause) rather than between two words that belong together. A cut mid-sentence is allowed and encouraged where it helps the viewer see what is being said.
- The shot definition note is extended: a `presenter` shot lists the presenter, and any other shot lists nobody. Its definition gets the words the presenter says in it.
- **Planning decides:**
  - whether this is a new writer or a branch of `shot_planning_writer`;
  - the smallest gap a cut may fall in, and where inside the gap the cut sits (its start, its middle, or a fixed lead before the next word);
  - the limits on how long the presenter may be on or off screen;
  - the lead-in before the first word and the tail after the last.

**Out of scope.** Clip lengths (006). Generation (007).

**Dependencies.** FLOW-004.

**Expected outcome.** A scene's shot plan cuts between the presenter and B-roll at word boundaries, some of them inside a sentence.

**Verification criteria.**
- A plan with a gap, an overlap, a presenter shot over 14.375 s or a missing event is refused and retried.
- The owner reads two scene plans and judges the cut points as natural.
- A `lines` explainer and a story get exactly the instructions they get today.
- Standard checks.

**Completion checklist.**
- [x] Planner branch, instructions, answer checks
- [x] Shot definition note
- [x] Docs, standard checks

**Completion notes.** Done on 2026-10-29. No migration. Decisions made in planning:

- **New writer, shared job.** `services/cut_planning_writer.py` is a new pure module (instructions, TAKE block, request, cut times, answer checks). The `plan_shots` job, the `shot_plan` table, `services/shot_plans.py` and the pipeline step are reused and branch on the project being continuous. `shot_planning_writer.py` is not changed, so a `lines` explainer and a story get exactly the instructions and the job input they get today (checked against `HEAD` for the shot definition instructions; the planner file has no diff).
- **Cut position (owner).** The middle of the gap between the end of the word before and the start of the start word, moved to the nearest 1/24 s frame. Any word boundary is allowed, including a gap of 0, because the take is never cut: only the picture changes. The first shot starts at 0 and the last ends at the take plus `TAIL_S` (0.30 s), rounded up to a frame. The lead-in is 0 (`LEAD_IN_S`): the take starts at the scene's start with its own leading silence. Both are stored on the plan (`cut_plan`).
- **Presenter limits (owner).** Code enforces only the hard limits: every shot at least `shot_target_min_seconds` (2 s by default) and at most 345 frames (14.375 s), with its own message for a presenter shot (H3's audio limit), and every event shown in order. Opening and closing on the presenter, and not leaving the presenter off screen for long, are in the instructions only.
- **Hand edits (owner).** Edit and "Accept as is" are refused for a continuous explainer (422, with the way out). Plan again, with or without a note, works.
- **Waiting for the timings.** The step graph is unchanged. A continuous scene whose take is being made or timed is `settling` in the "Plan the shots" step, so a run waits instead of reporting; any other reason (a failed timing, a poor match) is reported.

What was built:

- **The answer.** Each shot has `start_word`, `type` (`presenter`, `establishing`, `action` or `insert`), `source_event_ids` and `description`. The user message has the usual blocks plus `TAKE` (the take's length and its sentences, each with its unit and the unit's `dialogue` / `narration` label as a hint, each word with its number, time and `pause_before`) and a `DURATION POLICY` (shortest and longest shot, lead-in, tail) as data (D-8).
- **The checks** (a failing answer is refused and asked for once more): first start word is 1 and start words rise (so the shots cover the take with no gap and no overlap); a shot is not too short or too long; a shot lists the event of every unit that has a word in it, and a spoken event only when one of its words is in it; the events are consecutive and in story order and every event is shown (`shot_planning_writer._event_span` and `_check_event_cover` are reused).
- **The stored shot** keeps today's keys (`speech_unit_ids` worked out from the words, `target_duration` = `end_s - start_s`, `continues_previous` and `rapid_exchange` false) and adds `start_word`, `last_word`, `start_s`, `end_s` and `spoken_text`. The plan content has `cut_plan`. The plan's `inputs` hold one `speech_take` artifact (take, key, length, timing id) in place of the units' audio; a take made or timed again makes the plan out of date.
- **`shot_plans.py`.** A continuous scene is judged by its take clock (`take_timings.scene_clocks`), not its units' audio; the job input gets `take`; a cut plan has no timeline and no automatic re-plan until FLOW-006, so `generation_ready` is false with "Cut-based shots are not laid out on a timeline yet."
- **Shot definition.** A separate `_CONTINUOUS_NOTE` (used only for a cut-based shot; the `lines` note is untouched), and `shot_definitions._cut_speech_in_shot`, which lists each unit's words inside the shot: a `presenter` shot's words are the presenter's dialogue, so the existing character check gives "presenter shot lists the presenter, any other shot lists nobody". It runs once FLOW-006 gives cut plans a timeline.
- **API and board.** `presenter` is a shot type; `ShotOut` has the optional `start_word`, `last_word`, `start_s`, `end_s` and `spoken_text`; the plan view shows a cut shot's times and its words. `schema.d.ts` was regenerated from the local code (two changes).

Checked on throwaway data (no database; stand-in take, events and units): a good plan with a cut inside a sentence and a unit split over two shots; refused: a first start word other than 1, a repeated, decreasing, out-of-range or boolean start word, an unknown type, a shot under the minimum, a presenter shot and a B-roll shot over 14.375 s, a pause event left out, an event listed with none of its words, and words of an event that is not listed; cut times for a gap of zero, a short gap and a long pause; the TAKE text is valid JSON; the take input, the refusals for a missing or blocked take, the out-of-date reasons, the cut-plan generation message and timeline, and the definition fragments for a presenter shot, a B-roll shot and a scene with no single character. Ruff, `npm run lint` and `npm run typecheck` pass. There are no automated tests, as asked.

**Known limits.** The other APIs that re-emit a shot's `type` (shot definitions, references, prompts, takes, generation requests) still list the old six types; FLOW-006 must add `presenter` to them, because only then do cut plans reach them. The model is asked for fluent cuts but nothing but the hard limits is enforced, so a scene may open or close on B-roll. A shot's description is not checked against its words. `shot_cut_repair_writer` still has no explainer note (as before).

**Still for the owner (needs the model and judgement):** rebuild the backend image (`docker compose up -d --build backend`), make the takes and let the "Time the words" step time them, then press Plan on two real scenes and read the plans: are the cuts at natural places, some of them inside a sentence, with B-roll for the examples and numbers? The 2 s minimum and the 0.30 s tail are starting values.

### FLOW-006 — Timeline and clip lengths for cut-based shots

**Status:** Not Started

**Objective.** Lay a continuous explainer's shots at their cut times, and make each clip the shortest H3 length that covers its shot.

**Current state.**
- `services/scene_timeline.py` lays shots one after another and places each unit at the first shot that carries it. Its checks (`dialogue_too_short`, `narration_overlap`, `speech_past_scene_end`) assume speech is carried per shot.
- `services/h3_lengths.py` moves every shot onto an H3 length when the plan is saved (D-9), so the render has nothing to cut.

**Scope.**
- For a `continuous` explainer, a shot's start and end are its cut times. The take sits at the scene's start (after the lead-in). The per-unit checks do not apply, and the only blocking problem is a shot outside the hard bounds.
- Each shot gets a clip length: the shortest `17n + 5` frame length that is at least its shot. The shot is not moved (F-6).
- The scene's length is the end of its last shot.
- **Planning decides:** whether the clip length is stored on the plan or worked out on every read.

**Out of scope.** Generation (007) and the render (008).

**Dependencies.** FLOW-005.

**Expected outcome.** Every shot of a continuous explainer has an exact start and end, and a clip length that covers it.

**Verification criteria.**
- The shots of a scene add up to the take plus its lead-in and tail.
- Every clip length is a `17n + 5` frame length and at least its shot.
- A `lines` explainer and a story get exactly today's timeline.
- Standard checks.

**Completion checklist.**
- [ ] Timeline branch, clip lengths
- [ ] Docs, standard checks

**Completion notes.** _To be filled in._

### FLOW-007 — Generation requests, prompts and the take check for windows

**Status:** Not Started

**Objective.** Send each presenter shot the window of the take its clip covers, and check the take against the words in that window.

**Current state.**
- `services/generation_planner.py` lists each dialogue line's audio (`audio_key`, `starts_in_shot_seconds`, `marker: fully_copy` for an explainer). `services/shot_takes.py` uploads it placed inside silence with `speech_audio.place_in_silence`.
- `services/shot_prompt_writer.py` writes the audio definition from the line's text.
- `services/dialogue_check.py` compares the words heard in a take with the shot's dialogue lines.

**Scope.**
- A presenter shot's request has one audio: the take, from the shot's start, for the clip's length, always `fully_copy`, starting at 0 (F-7). A new function in `speech_audio` cuts the window and pads it with silence when it runs past the take's end.
- The request records the window's start and length and the take's key, so a remade take makes the shot's take out of date.
- The prompt's audio definition uses the words inside the window, taken from the timings.
- The take check compares the heard words with the words inside the shot's part of the window (from 0 to the shot's length), because the trimmed tail is never shown.
- B-roll shots are unchanged: text route, no audio.
- **Planning decides:** whether words that are only partly inside the window count in the take check.

**Out of scope.** The render (008).

**Dependencies.** FLOW-006.

**Expected outcome.** Presenter clips are lip-synced to the exact part of the take they cover.

**Verification criteria.**
- The uploaded window has exactly `clip frames / 24` seconds of audio, checked by sample count.
- The lips follow the words from the first frame on two real presenter shots, one of them starting mid-sentence (the owner checks).
- A `lines` explainer and a story send exactly today's requests.
- Standard checks.

**Completion checklist.**
- [ ] Window cut and upload
- [ ] Request, prompt and take check
- [ ] Docs, standard checks

**Completion notes.** _To be filled in._

### FLOW-008 — Render with the take as the voice

**Status:** Not Started

**Objective.** Render a continuous explainer with each scene's take as the voice, every clip trimmed to its shot, and captions, callouts and music timed from the take. Let the owner switch any presenter shot to its clip's own voice (F-9).

**Current state.**
- `services/story_render_plan.py` (timeline version 4) has a narration layer with only narration units. Dialogue is heard only in the shot audio, so it is never heard twice. Shot audio is ducked under narration.
- `render_commands.trim_args` already cuts each clip to its shot's frame count.
- Captions (`caption_plan`) and callouts (`callout_render`) are timed from each unit's word timing plus the unit's start. Music placement (`music_placement`) reads where narration and dialogue sit from the render's own sources (`story_renders.next_render_sources`).

**Scope.**
- A new timeline version with a voice layer: each scene's take at the scene's start plus the lead-in.
- By default the shot audio of a presenter clip is not used. B-roll shot audio is ducked under the voice as today.
- **Voice source per presenter shot (F-9).** Each presenter shot has a voice source, `take` (default) or `clip`, which the owner toggles on the shot (next to its takes on the shot generation board, with a note such as "use this when the lips look off"). With `clip`, the voice layer is silent for exactly the shot's span and the selected clip's own sound plays there, trimmed to the shot like its picture. The setting is kept on the shot, so it survives a new take of the clip and a new selection. Changing it makes the render out of date and nothing else (no clip is made again). It is offered only for presenter shots: a B-roll clip has no copy of the voice.
- The cut between the take and a clip voice must not click or jump: a short fade at each edge of the shot's span, and the clip voice brought to the take's loudness before the mix.
- Every clip is trimmed to its shot (F-6).
- Captions and callouts take their word times from the take, each unit's words at the unit's span. A caption group still never holds two units.
- The music placement sees the take's spans as speech, so it ducks and swells around the voice as it does today.
- A `lines` explainer and a story render exactly as today.
- **Planning decides:**
  - whether presenter shot audio on a `take` shot is dropped entirely or kept very low as room tone;
  - where the voice source is stored (a column on the shot's selection, or a per-shot setting of the project's render) and how the timeline names it;
  - the length of the fade at the edges of a `clip` shot, and how its loudness is matched to the take (a fixed gain from measuring both, or the per-shot loudness the render already measures);
  - how the voice layer is named in the timeline (a new layer, or the narration layer holding takes).

**Out of scope.** Any change to caption or callout styles.

**Dependencies.** FLOW-007.

**Expected outcome.** The rendered video has one even voice from start to end, and the picture cuts between the presenter and B-roll at word boundaries, some of them mid-sentence. Any presenter shot can be switched to its clip's own voice.

**Verification criteria.**
- The render's frame count, length and loudness checks pass.
- No word is heard twice and no word is cut at a cut.
- Captions and callouts follow the voice over a whole render.
- Switching one presenter shot to `clip` changes the voice in that shot's span only, with no click at its edges and no jump in loudness; every other shot's sound is the same as before. A shot left on `take` gives the same audio commands as a render with no switch at all.
- A `lines` explainer and a story give the same FFmpeg commands as before.
- Standard checks.

**Completion checklist.**
- [ ] Voice layer, timeline version
- [ ] Voice source per presenter shot: storage, toggle on the board, mute and mix in the render
- [ ] Captions, callouts and music on the take
- [ ] Docs, standard checks

**Completion notes.** _To be filled in._

### FLOW-009 — One continuous explainer end to end (owner, not done)

Make project 42's script again as a new continuous explainer, in portrait, with captions, callouts and music on. Check these:

- The voice has the same pace and energy whether the presenter is seen or not.
- At least some cuts to B-roll fall inside a sentence, and they feel natural.
- The presenter's lips follow the voice in every presenter shot, including one that starts mid-sentence.
- Captions, callouts and music follow the voice.
- Switching one presenter shot to its clip's voice sounds natural at both edges of the shot.
- Compared with the current project 42, the video feels more fluent.

**Result (owner fills in):** _To be filled in._

---

## 4. Known risks

- **Long takes.** The owner judged the FLOW-001 takes good. If a later, much longer scene drifts in pace or a join between 1000-character pieces is audible, per-paragraph takes are still the fallback.
- **Editing costs more.** Changing one sentence remakes that scene's take, its timings, its cut plan and the presenter clips whose windows changed. One take per scene, not per video, keeps this bounded.
- **A presenter shot starts with the mouth moving.** In FLOW-001 the `fully_copy` window clips gave good lips. If a shot still looks off, the owner can switch it to its clip's voice (F-9) or make the clip again; limiting cuts to sentence ends and pauses stays as the fallback.
- **Two kinds of voice in one video.** The H3 clip's voice sounds slightly clearer than the TTS take (probably a different audio format), so a shot switched to its clip's voice may sound a little different from the shots around it. The fade and loudness match of FLOW-008 keep the switch smooth, and the take stays the default so most of the video has one sound.
- **Clips are made longer than they are shown.** A clip is made at the next H3 length up, so up to 17 frames (about 0.7 s) per shot are generated and cut. That is a small extra GPU cost.
- **One instruction for a whole scene** cannot follow emotional turns inside the scene. A scene-level override (FLOW-002) is the way out if it matters.
- **Timing quality decides cut quality.** A take with a poor Parakeet match cannot be cut on, so it blocks the scene until it is made again (FLOW-004).

---

## 5. Progress log

| Id | Status | Notes |
|----|--------|-------|
| FLOW-001 | Done | Passed 2026-10-29 in the Audio video lab. Always `fully_copy`; the take is the default voice, with a per-shot switch to the clip's voice (F-9). |
| FLOW-002 | Done | 2026-10-29. Migration `0076`. Delivery text: owner's, else Story Bible narration, else a default; editable; no scene override. |
| FLOW-003 | Done | 2026-10-29. Migration `0077`. Takes are `speech_unit_audio` rows (kind `take`), per scene, units joined with one space. Not timed yet (FLOW-004). |
| FLOW-004 | Done | 2026-10-29. No migration. Takes are timed by the same job and table; unit spans are worked out on read (`take_timings`); an estimated take blocks cut planning. Owner checks the timings by playback. |
| FLOW-005 | Done | 2026-10-29. No migration. New `cut_planning_writer`; cut plans are `shot_plan` rows with `cut_plan` and word-based shots, no timeline until FLOW-006. Owner judges the cut points on real scenes. |
| FLOW-006 | Not Started | |
| FLOW-007 | Not Started | |
| FLOW-008 | Not Started | Includes the per-shot voice source (F-9). |
| FLOW-009 | Not Started | Owner end-to-end check. |
