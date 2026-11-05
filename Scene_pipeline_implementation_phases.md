# Vision Studio — Scene-by-Scene Pipeline and Shot Quality Phases

This document has two aims. The first is to fix the **system** behind the five shot problems found in project 48 (`Shot_generation_issues_analysis.md`). The second is to let a story be **made, watched and fixed one scene at a time**: early scenes are ready while later scenes are still being made, each scene can be rendered on its own, and a final pass assembles the whole story.

- **No phase fixes a story.** Nothing here edits project 48 or any other project's data by hand. Once the system is fixed, the owner fixes a story by regenerating one scene (S-1).
- The conventions of `Implementation_phases.md` (§3.3 to §3.5, §6) apply unchanged. Table and column details go in `DATABASE_STRUCTURE.md`. The newest migration when this was written was `0079`.
- Written 2026-11-03, from the analysis in `Shot_generation_issues_analysis.md` and a design discussion with the owner about scene-by-scene work and the GPU server's job priority.

---

## How to use this document

### Opus → Sonnet workflow

1. Pick a phase whose status is **Not Started** and whose hard dependencies are met (§5). The phases are numbered in the recommended order, so the lowest ready number is normally the next one.
2. Give Opus this document, `Implementation_phases.md`, `Shot_generation_issues_analysis.md` and a request such as:

   > Plan **SCN-0XX — <title>** only. Respect its Scope and Out of scope, the decisions in §3 and the design in §4 of `Scene_pipeline_implementation_phases.md`, the conventions in §3.4 and §3.5 of `Implementation_phases.md`, and the Completion notes of every phase it depends on. Resolve every "Planning decides" item explicitly in the plan. Do not pull work from later phases. List the files to change, the API and UI changes, the settings, and how each Verification criterion will be checked.

3. Give the resulting plan to Sonnet for execution.
4. When the phase is done, update it as described in §7. Fill in its **Completion notes**: later phases read them to learn the real names of modules, job types, endpoints and settings.

### Reading a phase

Every phase has the same fields: Objective, Current state (with starting points in the code), Scope, Out of scope, Dependencies, Expected outcome, Verification criteria, Completion checklist and Completion notes. Items marked **Planning decides** are left open on purpose and must be settled in the plan.

The manual phase (SCN-014) is done by the owner. The agent prepares material and records the results.

**Live checks cost GPU time.** A Verification item that says "regenerate one scene" queues real H3 clips (about 10 to 30 clips, each about 10 minutes on 4 GPUs). The agent asks the owner before starting one, names the project and scene, and never regenerates more than the item asks for.

---

## Table of contents

1. [Goal](#1-goal)
2. [Current state](#2-current-state)
3. [Decisions](#3-decisions)
4. [Design](#4-design)
5. [Phase overview](#5-phase-overview)
6. [Phases](#6-phases)
7. [Progress tracking](#7-progress-tracking)
8. [Open questions and risks](#8-open-questions-and-risks)
- [Appendix A — Evidence from project 48](#appendix-a--evidence-from-project-48)
- [Appendix B — Progress log](#appendix-b--progress-log)

---

## 1. Goal

**Shot quality.** For any story, without hand edits:

| # | Problem (from the analysis) | What "fixed" means |
|---|---|---|
| 1 | Speech in an invented language, not caught | Silent shots never ask for talking, listeners are told to stay silent, and speech that should not be there is detected |
| 2 | Short lines fail the transcription check even when they are right | Spelling, digits, homophones and one-sound differences pass; the same answer twice stops the retries |
| 3 | Car interiors with no roof | A scene can take place partly inside a vehicle (or a lift, a booth), and in-vehicle shots get the vehicle as their place, with the outside seen through the glass |
| 4 | One clip per short line feels choppy | Runs of short lines between two people become one multi-shot clip (a rapid exchange) |
| 5 | People missing from group shots | Every character present is in a group shot, and the prompt states the exact head count |

**Scene by scene.** The owner can:

- watch scene 1 a few hours after starting a story, while later scenes are still being made;
- run the pipeline for one scene, and render one scene, from both the automatic run and the manual stage panels;
- fix a scene by regenerating it alone, and render it again;
- get the full video from a final pass that places the music across the whole story and renders the whole timeline.

---

## 2. Current state

What exists and is reused:

- **The pipeline run** (`services/story_pipeline.py` `STEPS`, `jobs/story_pipeline.py`). Every step has `needs`, and a step starts only when every step it needs is complete for **every** target (`_needs_are_ready`). Targets already carry a `group` (their scene) and their own `waits_for` inside one step (`plan_step`). Run options are `pause_after`, `confirm_overwrite`, `scope` (`all` or `out_of_date`) and `review_points` (`RunOptions`); there is no scene scope. Review points are in `services/review_points.py`.
- **Manual controls.** Most stage panels already have a per-scene action besides **… all**: "Define this scene again", "Stage the scene again", "Plan this scene again", "Plan scene" (`GenerationRequestsPanel`), "Compile scene" (`ShotPromptsPanel`) and "Generate scene" (`ShotTakesPanel`). There is no single "run this scene" and no scene render. `SceneSection.tsx` holds a scene's own buttons.
- **The render** (`services/story_renders.py` `start_render`, `next_render_sources`; `services/story_render_plan.py` `build_plan`; job `render_story`). It always builds the whole story, and `story_render_plan._check_takes` refuses it unless every shot of every scene has a selected take.
- **Music.** `music_plan` needs every scene's current shot plan, but nothing from the clips. `music_cues` and `music_generation` don't wait for clips. `music_placement` needs every cue's take **and** every shot's take (`music_placement.gather`), and the render waits for it. `services/music_preview.py` (job `preview_music_mix`) already renders the audio mix of **one scene's window** with the render's own timeline builder.
- **GPU order.** The dispatcher sorts queued jobs by `input.priority`, higher first (`jobs/store.priority_of`). Only chained shots set it (`shot_takes._chain_priority`). Our local limits (`max_parallel_h3_jobs` 500, `max_parallel_gpu_jobs` 1500) are far above the server's (H3 `max_jobs` 15, `GET /v1/capacity`), so almost every job is sent at once and the **server's** queue decides the order. Today that is submission order.
- **The server's job priority** (guide 0.23.0, 2026-11-03). Every generation request may carry `priority` from 1 (most urgent) to 10 (least urgent, the default). It is strict, with no ageing, and it also orders jobs **between models** when the global GPU limit is reached. `PUT /v1/jobs/{job_id}/priority` changes it for a job that is still queued (409 once it runs). LTX-2.3, LTX-2.5, Wan-Animate, RVC and TBDub ignore it, count as 10, and may answer 429 while a more urgent job waits. `gpu_server.submit(base_url, path, body)` is where the body is sent. `queue_state` on a queued job says why it waits (0.25.0).
- **Shot quality code** (starting points per problem are in the analysis and in each phase): `dialogue_check.py`, `shot_takes._needs_dialogue_check` and `queue_retry`, `shot_planning_writer.py`, `shot_definition_writer.py`, `shot_prompt_writer.py` (`NOBODY_SPEAKS`, `_EXCHANGE_RULES`), `generation_planner.py`, `reference_selection.py`, `scene_definition_writer.py` (one `environment_id` per scene), `environment_views.py` (views planned per environment from the needs of every scene set there), `number_words.py`. The transcriber returns `word_timestamps` (`providers/transcriber.py`), so a word's time is known.

What does not exist: a scene scope for a run, a scene render, server priority on any request, a second place per scene, a check of silent shots for speech, and a continuity check across a scene boundary.

---

## 3. Decisions

| # | Decision |
|---|----------|
| S-1 | **Fix the system, not the story.** No phase edits a project's stored artifacts by hand or names a project, scene or character in code or prompt text. A fix must work for any story. The owner fixes existing stories afterwards by regenerating scenes (SCN-004). |
| S-2 | **Story-wide work stays story-wide:** Story Bible, discovery, links, relations, character and environment definitions and pictures, voices, the looks and states, the Music Bible and themes, the music plan, cues and generation, the final music placement and the full render. Everything else is per scene and moves forward scene by scene (§4.1). |
| S-3 | **Story order is the default order of work.** Earlier scenes get their GPU work first (§4.2). The owner can push one scene to the front. |
| S-4 | **GPU order uses the server's `priority`**, mapped from one place in code (§4.2). The local limits stay as they are: jobs are still sent early so their uploads are done, and the server orders them. The local `input.priority` (higher first) keeps ordering chained shots and is translated, never sent as it is. |
| S-5 | **A scene render uses the full render's own timeline builder** (`story_render_plan.build_plan`) for one scene's window, so a scene looks and sounds in its render exactly as it will in the full video. A shot with no selected take gets a placeholder of its planned length (§4.3). A scene render never replaces the full render. |
| S-6 | **Music is planned for the whole story once.** A scene render plays the music only from a placement that is current for the story's timing, cut to the scene's window with short fades. When there is none, the scene render has no music and says so (§4.4). |
| S-7 | **Continuity is fixed before generation, not after.** A scene boundary is checked in text (definitions and continuity states) before the clips are made, because a fix after generation means new clips (§4.5). |
| S-8 | **The final video is a full render from the timeline**, never scene files joined together, so the audio is continuous and nothing is encoded twice. |
| S-9 | **Long stories stay out of scope** (D-13 of `Implementation_phases.md`). Splitting a story's discovery into chunks with a running summary is a later document. |
| S-10 | **Code writes counts, ids and lists of who is in frame**; the language model writes creative text (§3.4 of `Implementation_phases.md`). |
| S-11 | **Anything that queues GPU work starts only from a click or from a run the owner started.** Re-scoring existing takes (SCN-001) is local and queues nothing. |
| S-12 | English only. No automated tests (D-11 of `Implementation_phases.md`). |

---

## 4. Design

### 4.1 Story-wide steps and scene lanes

Each step of `STEPS` is one of three kinds. SCN-010 turns this table into code.

| Kind | Steps | How it waits |
|---|---|---|
| **Story-wide** | story_bible, the three discoveries, links, relations, character definitions, environment definitions, character images, voices, music_bible, music_themes, resolution, look_state_images, music_plan, music_cues, music_generation, music_placement, render | As today: for whole steps |
| **Per scene** | scene definitions, events, scene_staging, speech_units, speech_synthesis, word_timings, shot_plans, shot_definitions, shot_continuity, references, generation_requests, prompts, shot_generation, scene render (new) | A scene's targets wait only for **the same scene's** targets of the steps they need, plus the story-wide steps they need |
| **Cross-scene** | environment_views (planned per environment, from every scene set there), music_plan (needs every scene's shot plan) | For the scenes they read, and nothing else |

The boundary check of SCN-012 is not a step of its own: it is part of the per-scene `shot_continuity` step, whose target for a scene that follows another waits for that scene's target (`waits_for`).

A **lane** is one scene going through the per-scene steps. Lanes move independently, earlier scenes first. **Planning decides** (SCN-010) where callout_plan belongs (explainers only) and whether `environment_views` waits for every scene of its environment to be staged (simple; staging is a few minutes per story) or plans views as scenes arrive.

### 4.2 GPU priority

One function maps a job to the server's 1-to-10 value. Proposed levels (SCN-002 settles them):

| Level | Jobs |
|---|---|
| 1 | Work the owner asked for now: "Run this scene", "Generate scene", "Render scene" pushes, and Lab clicks |
| 2 | Short jobs that let a lane move on: Qwen3.8 calls, speech synthesis, pictures, transcription checks |
| 3 to 9 | Clips and other per-scene GPU work, in bands by the scene's position in story order: `3 + floor(position × 7 / scene_count)`, position from 0 |
| 10 | Everything else (for example music generation, which only the renders need) |

- A retried take keeps its scene's band, so an early scene still finishes first.
- Within a band, the server keeps submission order, and the dispatcher's local sort still sends chain heads first.
- **Pushing a scene to the front** gives its new jobs level 1 and changes its already queued jobs with `PUT /v1/jobs/{job_id}/priority` (a 409 means the job already runs, and is ignored).
- Priority is strict with no ageing, so level 1 must stay for short, owner-started work.

### 4.3 The scene render

- **Window:** from the scene's first frame to its last, on the same timeline as the full render (S-5), with captions and callouts as the project's settings say.
- **Missing shots:** a placeholder for the planned length. It shows the shot's number and summary on a plain frame and plays the shot's recorded dialogue (the speech units it carries), so the timing can be judged. **Planning decides** its exact look.
- **Music:** only from a current placement (§4.4), cut to the window with short fades.
- **Out of date** is worked out on read from what the render was made from (D-3), as the full render does.
- **Storage:** **Planning decides** (SCN-003) whether a scene render is a `story_render` row with a scene column, or a table of its own. Either way it is the phase's own migration, at the next free number.

### 4.4 Music in scene renders

- The music plan is written once all shot plans exist. With lanes (SCN-010), shot plans are among the first things made, about 2 hours into project 48.
- Music generation runs in the background at level 10.
- A **provisional placement** places the music when some shots have no take yet: it uses the planned time for every moment of a missing clip. The placer already falls back to the planned second when no sudden sound is found. It reuses the language model's newest choices (as `music_preview` does) and asks the model nothing new.
- The **final placement** (SCN-013) is made when every shot has a take, exactly as today.
- When a scene's timing changes (it was planned again), the music plan is out of date for the whole story, and scene renders have no music until it is planned again.

### 4.5 Scene boundaries

Two scenes **follow directly** when the second continues the first in time and place. **Planning decides** the rule in SCN-012, for example the same environment and no stated time jump. For such a pair, the last shot of the first scene and the first shot of the second are checked in text, as `shot_continuity` checks a cut inside a scene: who is there, where, wearing what, holding what, and in which light. A problem is fixed by the existing repair route before either clip is made.

---

## 5. Phase overview

| Id | Title | Kind | Hard dependencies | Status |
|----|-------|------|-------------------|--------|
| SCN-001 | Dialogue check: fair on short lines | Code | none | Completed |
| SCN-002 | GPU priority by scene | Code | none | In Progress |
| SCN-003 | Scene render | Code | none | In Progress |
| SCN-004 | Run one scene (automatic and manual) | Code | 003 | In Progress |
| SCN-005 | Speech rules: who talks and who does not | Code | none | In Progress |
| SCN-006 | Group shots: everyone present, exact head count | Code | none | In Progress |
| SCN-007 | Places inside places (vehicles, lifts) | Code | none | In Progress |
| SCN-008 | Conversation flow: rapid exchanges for short lines | Code | 005 | In Progress |
| SCN-009 | Catch unwanted speech | Code | 001 | In Progress |
| SCN-010 | Scene lanes in the automatic run | Code | 002, 004 | In Progress |
| SCN-011 | Music in scene renders | Code | 003 | In Progress |
| SCN-012 | Continuity across scene boundaries | Code | 010 | In Progress |
| SCN-013 | Final assembly | Code | 010, 011 | In Progress |
| SCN-014 | Owner live check on a new story | Manual | all | Not Started |

**Soft dependency for every quality phase (005 to 009):** SCN-003 and SCN-004, so a fix can be tried on one scene and watched in a scene render. They are not hard dependencies: a quality phase can still be checked on prompts and with "Generate scene".

### 5.1 Dependency graph

```text
SCN-001 ─────────────────────────────── SCN-009
SCN-002 ──────────────┐
SCN-003 ─┬─ SCN-004 ──┴─ SCN-010 ─┬─ SCN-012
         │                        └─┐
         └─ SCN-011 ────────────────┴─ SCN-013
SCN-005 ─── SCN-008
SCN-006
SCN-007
                     (all) ─── SCN-014 (owner)
```

### 5.2 Order and parallel work

- **Recommended order:** 001, 002, 003, 004 (quick wins and the tools to test one scene), then 005, 006, 007, 008 (the shot fixes, each tried on one scene), then 009, then 010 to 013 (full scene-by-scene running), then 014.
- **Can run together:** 001, 002 and 003 share no files. 006 and 007 can run together.
- **Must not run together:** 005 and 008 both change `shot_planning_writer.py` and `shot_prompt_writer.py`, so 008 waits for 005. 005, 006 and 007 all change `shot_definition_writer.py` and `shot_prompt_writer.py`; if two run together, their plans must name the rule blocks each one adds. 004 and 010 both change `RunOptions` and `jobs/story_pipeline.py`, so 010 waits for 004.

---

## 6. Phases

### SCN-001 — Dialogue check: fair on short lines

**Status:** Completed

**Objective.** A take whose speech is right passes the transcription check, whatever the line's length. A shot stops being retried when its takes keep hearing the same thing. Existing takes can be scored again without being made again.

**Current state.**

- `services/dialogue_check.py`: `normalize_words` lowers and strips the text; `compare` scores with a word-level `SequenceMatcher` ratio; the threshold is the setting `dialogue_match_threshold` (80).
- `services/number_words.py` reads digits and English number words.
- `services/shot_takes.py`: `_needs_dialogue_check` and `queue_retry` (up to `shot_take_max_retries` = 2 automatic retries).
- `jobs/check_take_dialogue.py` runs the check.
- In project 48, 47 of 91 failures were spelling, digits, homophones or one-sound differences, and 26 were empty transcripts on 1- or 2-word lines (Appendix A).

**Scope.**

- **Matching on both sides** (option 2A): numbers in one form (`number_words`), "%" as "percent", a short UK and US spelling list, and homophone groups (to/too/two, by/buy/bye, for/four, there/their/they're, …). The lists are data in one module, not prompt text.
- **Short lines** (2B): a line of 1 to 4 words passes when at most one word differs and the two words sound alike, or are close in letters. **Planning decides** the exact rule (for example a letter-level ratio on the differing word).
- **Interjections and one-word lines** (2C): an empty transcript on such a line does not fail the take. The take gets the result "speech not verifiable", can be selected automatically, and shows a badge.
- **Same answer twice** (2E): when two takes of a shot in a row hear the same normalised text and both fail, no further retry is queued. The shot shows "needs your review".
- **Score again:** a button (and endpoint) that scores every checked take of a project again from its stored transcript, with no new transcription and no new clip (S-11). It never changes which take is selected unless the selected one has no passing take and a passing one now exists; **Planning decides** whether it only reports this or also selects.
- `DATABASE_STRUCTURE.md` if the stored check result gains fields.

**Out of scope.** Words outside the line's time window and silent shots (SCN-009). Any prompt change (SCN-005, SCN-008).

**Dependencies.** None.

**Expected outcome.** On project 48, scoring again turns most of the 47 false failures into passes, and no shot loops to 6 takes on a spelling or a homophone.

**Verification criteria.**

- Score again on project 48: the change in failures is reported by category, matching the categories of the analysis. `scene_parking_garage/shot_11` ("The tyre's fine." heard as "the tires fine") passes.
- A real failure still fails: "Don't" heard as "Don't you think that's the first one".
- A take with an empty transcript on "Oh" is "speech not verifiable", not failed.
- Two failing takes with the same transcript queue no third take (checked by reading the queue after a stand-in check, with no GPU job).
- Standard checks.

**Completion checklist.**

- [x] Matching lists and rules
- [x] Short-line rule and "speech not verifiable"
- [x] Retry stop and "needs your review"
- [x] Score again (endpoint, button, `schema.d.ts`)
- [x] `DATABASE_STRUCTURE.md` if needed
- [x] Standard checks (ruff, ESLint and `tsc` pass; `schema.d.ts` regenerated from the code's own OpenAPI, additions only; no migration, so no `docker compose up --build`)

**Completion notes.**

- **No migration, no new job type, no new setting.** `shot_take.dialogue_check` is JSON and is now version 2. A version 1 check still reads: the API gives it `outcome` `matched`, or `no_speech` / `mismatch` from its problem code.
- **Modules.** `services/dialogue_matching.py` (new: `prepare`, `fold_numbers`, `to_us_spelling`, `fold_homophones`, `short_line_matches`, `is_unverifiable`, the lists `INTERJECTIONS` and `WEAK_FORM_PAIRS`). `services/dialogue_check.py`: `compare` tries the steps `RULES` = exact, numbers, spelling, homophones, then the short-line rule, and stores `outcome` (`matched`, `close_match`, `not_verifiable`, `mismatch`, `no_speech`), `rule`, `matched_expected` and `matched_heard`. New helpers `spoken_of(check)` and `heard_key(check)`. `normalize_words` is unchanged (callouts, word timings and graphics briefs import it). `number_words.is_number_word` is now public.
- **Short-line rule (decided in planning).** A line of 1 to 4 words passes when it differs in one place only, and that place is one word for one word with a letter ratio of at least 0.6, a weak form pair (the/a, him/em, ...), or the same letters split differently ("it" and "i t"). A missing or added word never passes.
- **Speech not verifiable (owner's choice).** Only an empty transcript on a one-word line or a line of only interjections. It is stored as `passed: true` with problem code `speech_not_verifiable`, so selection and the render need no change. "I did" and "I work" with nothing heard still fail (`no_speech`).
- **Same answer twice.** `shot_takes._repeated_answer(newest, before)`: same `shot_prompt_id`, both dialogue checks failed, same `heard_key`. `queue_retry` queues nothing then, and `ShotEntry.needs_review` / `needs_review` in the API (only while the shot's status is `failed`) shows "Needs your review". Computed on read, never stored.
- **Score again (owner's choice).** `POST /api/projects/{id}/shot-takes/rescore-dialogue` (`shot_takes.rescore_dialogue`, answer `RescoreDialogueOut`), button "Score dialogue again (N)" in `ShotTakesPanel` (N is `rescorable_count`). Only failed checks are judged again; they keep `checked_at` and `accepted_at` and get `rescored_at`. A shot with no selected take and nothing being made or checked gets its newest take that now passes. It queues no job, starts no dependent shot and does not call `dispatcher.nudge`.
- **Result on project 48** (run on a copy of the database, never on the live one): 91 failed checks judged again, 57 pass (numbers 7, spelling 12, homophones 10, short line 11, not verifiable 17) and 34 still fail (25 mismatch, 9 no speech). Numbers plus spelling are 19, and homophones 10, the same as the analysis counted. `scene_parking_garage/shot_11` passes on spelling. No take was selected, because every shot of project 48 already has a selected take.
- **Same answer twice, checked on the copy.** With the take pair of `scene_parking_garage/shot_11` set to two failed checks hearing "the tires fine": the shot read `failed` with `needs_review` true, and `queue_retry` queued no job (job count unchanged). With the earlier take's answer changed, `needs_review` was false and `queue_retry` went on to queue (it stopped at a missing picture file on the copy, which is unrelated).
- **Not done:** the live backend was not rebuilt or restarted, so press "Score dialogue again" on project 48 after the next `docker compose up --build -d`. A latent problem, not touched: in `queue_retry`'s `except ShotTakesError` handler the log line reads `take` attributes after `session.rollback()`, which can raise `MissingGreenlet` (seen only on the copy, where picture files were absent).

### SCN-002 — GPU priority by scene

**Status:** In Progress (code and docs done; live checks wait for the owner)

**Objective.** Clips of earlier scenes are made before clips of later scenes, short jobs are never stuck behind clips, and the owner can push one scene to the front.

**Current state.** §2 (GPU order and the server's job priority). `gpu_server.submit` sends the body. `store.priority_of` and `shot_takes._chain_priority` give the local order. The job input already records `priority` (0 for most jobs).

**Scope.**

- **One mapping function** (§4.2) from a job to the server level, used by every GPU job type that the server orders by priority. The scene's position comes from the scene list in story order.
- **Send `priority`** in the body of every such request. A backend that ignores it (LTX-2.3, LTX-2.5, Wan-Animate, RVC, TBDub) gets no value, or 10.
- **Show it:** a job's server level and its `queue_state` on the Activity page.
- **Push a scene:** an endpoint that gives a scene's queued jobs level 1 (`PUT /v1/jobs/{job_id}/priority`, a 409 ignored) and marks the scene so its new jobs get level 1 too. **Planning decides** where the mark is stored and when it ends (for example when the scene's last clip is selected, or after a run ends).
- **Planning decides** the final levels: which job types are level 2, whether Lab clicks are 1 or 2, and where music generation goes.

**Out of scope.** Changing the dispatcher loop (§3.4 of `Implementation_phases.md`), changing the local limits, and the "Run this scene" button (SCN-004).

**Dependencies.** None. The server must be at guide version 0.23.0 or later (it is at 0.25.0).

**Expected outcome.** During a story's clip phase, scenes finish roughly in story order instead of all near the end.

**Verification criteria.**

- A submitted H3 job shows the expected `priority` in `GET /v1/jobs/{job_id}`.
- With queued clips of an early and a late scene, the early scene's clips start first (by `started_at` on the server).
- Pushing a scene changes its queued jobs to 1, and a running job's 409 is ignored with no error.
- A Lab job still runs, and an LTX job that gets 429 waits and tries again (`WAITING_SERVER_BUSY`).
- Standard checks.

**Completion checklist.**

- [x] Mapping function and its levels
- [x] `priority` in every request that uses it
- [x] Level and `queue_state` shown
- [x] Push a scene (endpoint, `schema.d.ts`)
- [x] Standard checks (ruff check and format, ESLint and `tsc` pass; `schema.d.ts` regenerated from the code's own OpenAPI, additions only)
- [ ] Live checks (waiting for the owner's go-ahead, see the notes)

**Completion notes.**

- **Migration `0084`** adds `project.pushed_scene_id` (TEXT, NULL). It applies on the next `docker compose up --build -d` (not run yet: a rebuild restarts running jobs, so it needs the owner's go-ahead). No new job type, no new setting, no dispatcher change.
- **One module, `services/gpu_priority.py`.** `level_for(session, job)` is the only place that decides a level. Constants `MOST_URGENT` 1, `SHORT_WORK` 2, `BAND_FIRST` 3, `BAND_LAST` 9. `band(position, scene_count)` is `3 + position * 7 // scene_count`, at most 9. `with_priority(body, level)` returns a copy of the body with `priority`, or the body as it is when the level is None. `push_scene(session, project, scene_id)` and `stop_push(session, project)` return a `PushReport` (`changed`, `already_running`, `not_reached`); a 409 or 404 from the server counts as already running, never as an error.
- **Final levels (decided in planning).** 1: clips of the pushed scene. 2: Qwen3.8 calls (`llm_target.complete`), `synthesize_speech_unit`, `lab_voice`, `check_take_dialogue`, `time_speech_words`, `time_lab_speech_words`, `time_lab_graphic_words`, `lab_image` (story pictures and Image lab clicks alike), `lab_video` on MiniMax H3, `lab_music` with no project. 3 to 9: other `generate_shot` clips by the scene's place in the newest scene discovery (a scene not found gets 9). Nothing sent: `lab_music` of a project (story music, so the server's 10) and every LTX request (`/v1/ltx/`, `/v1/ltx25/`, and `/v1/ltx/audio/generate`). The level is worked out when the job's handler starts, so a retry or a late start takes the scene's band and any push made meanwhile.
- **Where it is sent.** `generate_lab_video` (`start`, then `_upload_and_submit_run(..., priority)`), `remote_image.submit(..., priority=)`, `synthesize_speech._submit_part`, `check_take_dialogue` and `time_speech_words` (`transcriber.build_body` / `submit` take `priority`), `generate_lab_music`, and `qwen38.complete(..., priority=)` / `to_request`. The body that is recorded as `input.body` is the one sent (a picture and a music run now record `body` always). The local `input.priority` (chain order) is never sent.
- **Server status.** `gpu_server.RemoteStatus` has `priority` and `queue_state` (one of `gpu_server.QUEUE_STATES`), kept in `output.remote` by the polls that keep it (clips, pictures, music). `gpu_server.set_priority(base_url, job_id, priority)` is the `PUT`. Speech and transcription jobs do not keep `output.remote`, so the Activity page shows their sent level but no `queue_state`.
- **Push.** `project.pushed_scene_id`, one scene per project; it ends only on "Stop pushing" or when another scene is pushed (the old scene's waiting clips go back to their band). Endpoints: `POST /api/projects/{id}/shot-takes/{scene_id}/push` and `DELETE /api/projects/{id}/shot-takes/push`, both answer `PushSceneOut {scene_id, changed, already_running, not_reached}`; `GET .../shot-takes` has `pushed_scene_id`. **"Generate scene" (`POST .../{scene_id}/run`) also pushes its scene**, when it started at least one job. A push changes only clips that are `running` locally with a server job id and the phase `queued on cluster`; clips not sent yet are sent at their new level.
- **Activity page.** `JobSummary.server_priority` and `.queue_state`; a dimmed line "Priority 3 · all GPUs busy" under the status badge of a queued or running job (`jobFormat.priorityText`). The scene's row in the shot generation panel has "Push to front" / "Stop pushing", a "Pushed to front" badge and a report of the last push.
- **For later phases.** SCN-004 "Run this scene" should call `gpu_priority.push_scene`, like "Generate scene" does. SCN-010 lanes need no new priority code: a clip's level comes from its scene's position, whoever queued it. Level 1 stays small on purpose (strict, no ageing, SQ-2).
- **Not done:** the live checks of the Verification criteria (they cost GPU time); see the progress log.

### SCN-003 — Scene render

**Status:** In Progress (code, docs and checks on a database copy done; the live run waits for the owner)

**Objective.** The owner can render one scene at any time and watch it, with placeholders for shots that have no clip yet.

**Current state.** §2 (the render, and `music_preview` for one scene's window). `story_render_plan._check_takes` refuses a render with a missing take. `StoryRenderPanel.tsx` shows the full render.

**Scope.** §4.3:

- the window, the placeholders and the out-of-date reasons;
- a **Render scene** button on each scene (in the scene's own buttons, `SceneSection`), and the scene's newest render playable there;
- the scene render list in `StoryRenderPanel`;
- music only when a current placement exists (the full one, today; SCN-011 adds the provisional one);
- the storage of §4.3 with its migration, and `DATABASE_STRUCTURE.md`.
- **Planning decides** whether a scene render is a new job type or the `render_story` job with a window, and how many renders per scene are kept.

**Out of scope.** The provisional music placement (SCN-011). Running the pipeline for a scene (SCN-004).

**Dependencies.** None.

**Expected outcome.** Any scene of project 48 can be rendered today.

**Verification criteria.**

- A scene with every take renders, and its length equals the sum of its planned shot lengths (to the frame).
- A scene with missing takes renders with placeholders, and their dialogue is heard at the right times.
- The same scene cut out of a full render and the scene render show the same frames at the same times (spot check of 3 frames).
- The full render still works and is unchanged.
- Migration up and down; standard checks.

**Completion checklist.**

- [x] Migration, models, `DATABASE_STRUCTURE.md`
- [x] Scene window in the timeline builder, placeholders
- [x] Job, API, `schema.d.ts`
- [x] Render scene button and scene render list
- [x] Standard checks (ruff check and format, ESLint and `tsc` pass; `schema.d.ts` regenerated from the code's own OpenAPI, additions only)
- [ ] Live run on the server (waiting for the owner's go-ahead, see the notes)

**Completion notes.**

- **Migration `0085`** adds the table `scene_render` and `render_scene` to the `job.type` CHECK. It applies on the next `docker compose up --build -d` (not run: a rebuild restarts running jobs, so it needs the owner's go-ahead). Up, down and up again were run on a copy of the live database (0084 to 0085 to 0084 to 0085): no `job` row lost (15402 before and after), `PRAGMA integrity_check` ok.
- **Decisions made in planning.** A scene render is **its own table**, not a `story_render` row: "a project is complete" reads `story_render` (Q-9), and every reader of it means a whole video. It is **its own job type**, `render_scene` (`RenderSceneHandler` is a subclass of `RenderStoryHandler`, so trimming, narration, music and loudness are the same code). **Every render is kept** (no limit; the owner's choice), numbered per `(project_id, scene_id)`. The button and the newest video are in the scene's row in **`ShotTakesPanel`** (not `SceneSection`); the list of scene renders is in `StoryRenderPanel`.
- **One builder.** `story_render_plan.build_plan` and the new `build_scene_plan` share `_build`. A scene is built **in story coordinates** and the timeline is then moved so the scene starts at frame 0 (`_shift_timeline`: frames, samples and milliseconds all by the scene's first frame, `frame_at(story_start_s)`), so every shot, line, caption and callout sits where the full render puts it. `TIMELINE_VERSION` stays 5; the two new keys are optional (`shots[].placeholder`, `narration.entries[].stand_in`). The full render's timeline is unchanged.
- **Placeholders** (`placeholder_reason`): a shot with no selected clip, a missing clip file, no graphic, or a missing graphic file. `placeholder_frame.draw` makes a PNG (scene and shot number, the reason, the plan's one-sentence description, the length) and `render_commands.placeholder_args` turns it into a silent clip of the shot's length that joins the trimmed clips (checked with FFmpeg: same codec, frame count right). A line of dialogue whose shots are **all** placeholders is played from its speech file (`stand_in`); a line shared with a real clip is not played and gives the warning `dialogue_not_heard`. Other warnings: `shot_placeholder`, `scene_start_unknown` (a scene before this one has no plan: the scene starts at 0 and has no music).
- **Music** only through the existing gate (`render_music.gate`), which needs the full placement today. The placement is cut to the scene's window with 0.5 s linear fades at the cut edges (`SCENE_MUSIC_FADE_S`); a scene that cannot take it is rendered without music and `no_music_reason` says why. **For SCN-011:** a provisional placement only has to be given to `scene_renders` in place of `render_music.gate`'s source (`_plan_scene` already tries the scene again without music when the music is what is wrong).
- **API.** `GET /api/projects/{id}/scene-renders` (every scene: `can_render`, `blocked_reason`, `planned_frames`, `placeholders`, warnings, `no_music_reason`, the newest job, every render with its out-of-date reasons) and `POST /api/projects/{id}/scene-renders/{scene_id}/run` (202 `{job_id}`; a render already waiting or running of the same scene returns its job). Out of date is worked out on every read (D-3). **For SCN-004 and SCN-010:** call `scene_renders.start_render(session, project, scene_id)` to end a scene run with a render, and `scene_renders.state` to see whether one is current. `RenderTakeOut` has a new required `placeholder` flag.
- **Frontend.** `api/sceneRenders.ts` (`useSceneRenders` asks again every 3 s only while a scene render job is active; `useRenderScene`), a **Render scene** button, a status badge and the newest scene video in each scene row of the shot generation panel, `SceneRenderList` in the full render panel, and `render_scene: "Scene video"` in the job labels.
- **Checked on a copy of the live database and its project 48 media** (the live data was only read): the full render timeline of the 22 first scenes (449 shots, 37277 frames) is **identical** to the one the code before this phase makes (`cmp` of the whole JSON). For each of those 22 scenes the scene timeline has the same shots, takes and frame counts as the full timeline's slice, and its length equals the end of its last shot. Real renders: `scene_hotel_entrance` (917 frames planned, 917 in the file, 38.208 s, audio present, "current"), and `scene_old_hardware_lead` with one placeholder (`shot_16`, 1320 frames planned and in the file, 55.0 s; the placeholder picture was looked at). Spot check of 3 frames of `scene_hotel_entrance` against the same frames of the selected clips: mean difference 3.5 to 7 of 255 per channel (video re-encoding), where a wrong frame would be far higher.
- **Known limits.** Project 48's full render is blocked today (scenes 23 to 35 have no or too short clips), and a scene starting after a scene with no plan starts at 0. The scene-renders GET builds the plan of every scene, so it is not cheap on a story of 35 scenes; it is asked only when the shot generation panel is open and again only while a scene render runs (the same cost as the full render panel's read).
- **Not done:** the live run on the server (needs a rebuild that restarts running jobs); see the progress log.

### SCN-004 — Run one scene (automatic and manual)

**Status:** In Progress

**Objective.** The owner can make or remake one scene from start to finish with one click, from the automatic run or from the scene in the stage panels, and render it.

**Current state.** §2 (the pipeline run and the manual controls). `RunOptions` has no scene scope. `story_pipeline.start_block` allows one active run per project.

**Scope.**

- **A scene scope in `RunOptions`:** the run looks only at the per-scene targets of the chosen scenes (§4.1). The story-wide steps the scene needs are made if they are missing. The music steps and the full render are skipped, and the run ends with a scene render (SCN-003).
- **The start dialog** of `StoryPipelinePanel` can choose scenes (one or more), with "all scenes" as the default.
- **Run this scene** on each scene's own buttons (`SceneSection`): starts a scene run for that scene (with the usual consent for replacing what the owner wrote), and pushes the scene to the front when SCN-002 is done.
- **The pipeline board** shows a scene run's scope.
- **Planning decides** what happens when a run is already active: refuse with a message (simplest), or add the scene to the running run's push.

**Out of scope.** Lanes in a full run (SCN-010).

**Dependencies.** SCN-003 (the run ends with a scene render). Soft: SCN-002 (the push).

**Expected outcome.** The owner remakes one scene of project 48 with one click and watches it.

**Verification criteria.**

- A scene run on a test project makes jobs only for that scene's targets (checked in the run's output and the job list).
- A scene run with scope `out_of_date` remakes only what is out of date in that scene.
- A full run behaves as before.
- Regenerate one scene with the owner's confirmation, and the run ends with a scene render.
- Standard checks.

**Completion checklist.**

- [x] Scene scope in `RunOptions` and the run
- [x] Start dialog and Run this scene
- [x] Pipeline board scope
- [x] API, `schema.d.ts`
- [x] Standard checks (ruff check and format, ESLint and `tsc -b` pass; `schema.d.ts` regenerated from the code's own OpenAPI, additions only)
- [ ] Live scene run on the server (waiting for the owner's go-ahead, see the notes)

**Completion notes.**

- **No migration, no new job type, no new setting.** Choices are in `job.input` (`scenes`, `remake_from`), run state in `job.output`, as before. `DATABASE_STRUCTURE.md` §5 describes both.
- **Decisions made in planning.** A scene run can name a step to **remake once** ("Make again from"), even when the scene is up to date; items the owner wrote still need "Allow overwrite". A run is refused while another run is active (the existing one-run-per-project rule). A run of exactly one scene calls `gpu_priority.push_scene` (SCN-002) when it is created.
- **For SCN-010.** `RunOptions.scenes` (frozenset of scene ids) and `RunOptions.remake_from`; `story_pipeline.in_run_scenes(target, options)` filters a target by scene (a target has `group` = its scene, or `scenes` for targets spanning scenes, such as environment views); `Target.remake` marks a done target to be made again (`redo` stays the review-point reject flag). Story-wide targets (`is_story_wide`) are made only if missing in a scene run; if stale they are left alone, and the stages that need them stop with their own "out of date" message. `SCENE_RUN_SKIPS` (music steps and `render`) are marked "skipped" in a scene run; the new step **`scene_render`** ("Render the scenes", after `shot_generation` and `graphics`) ends a scene run through `scene_renders.start_render` and is one done target in a full run. `REMAKE_STEPS` lists the steps that can be remade.
- **Per-target start paths.** `speech_units`, `references` and `generation_requests` start only the run's targets (not "do all") when the run has scenes or scope `out_of_date`. `confirmations(session, project, options)` and `review_targets(..., options)` look only at the run's scenes; consent is asked for owner-written targets even when they are done, and only `redo` targets skip it.
- **API.** `POST /api/projects/{id}/story-pipeline/run` takes `scenes` and `remake_from`; `GET` takes the same as query parameters (for the confirmation list) and returns `remake_steps`; a run returns `scenes` and `remake_from`; 422 when nothing is out of date for the chosen scenes (not when `remake_from` is set), 409 with the consent list as before. The board's run has `scenes` (labels) and the header shows "Running Scene N: Title".
- **Frontend.** `StoryPipelinePanel`: scene multi-select, "Make again from" select, scene-aware counts and button labels. New `RunSceneButton` (menu "Run this scene" and "Make again from…", consent and error dialogs) in each scene's row through `SceneSection`'s `runScene` prop. `api/storyPipeline.ts`: `useStoryPipelineState`, `useRunScene`.
- **Deviation.** `references` and `shot_generation` are **not** in `REMAKE_STEPS`: their targets already skip up-to-date items inside the step, and clips have chain waits, so "remake" would not do what it says. Remake starts at `scene_definitions`, `events`, `scene_staging`, `speech_units`, `shot_plans`, `shot_definitions` or `prompts`.
- **Checked on a copy of the live database (project 48; the live data was only read).** Full-run plans are identical before and after the change, apart from the new `scene_render` step. A scene run of `scene_hotel_entrance` has 10 shots and only that scene's targets; `scene_old_hardware_lead` has 16 shots with its 1 failed shot; music steps and render are skipped; with the scene already made, the only target to make is the scene render (scope `out_of_date`). Remake from `shot_definitions` and `prompts` on `scene_hotel_entrance` creates all 10 shots, from `scene_staging` creates the scene; remake from `prompts` on `scene_old_hardware_lead` asks consent for the one prompt written by the owner (`shot_16`) and lists it in the 409 list, and the full and plain scene runs list none. With the story changed on the copy, a scene run leaves the story-wide targets alone and `scene_definitions` stops with "The Story Bible is out of date".
- **Not done:** the live scene run (needs the rebuild with migrations 0084 and 0085, which restarts running jobs, and GPU time). It needs the owner's confirmation naming the project and the scene (S-11); see the progress log.

### SCN-005 — Speech rules: who talks and who does not

**Status:** In Progress

**Objective.** H3 is never asked for words it was not given. Silent shots show nobody talking, dialogue shots say who speaks, who is only heard and who stays silent, and nobody speaks after the last line. A recorded line from someone not in the frame (a phone, another room, a reaction shot of the listener) keeps working. Fixes problem 1 at its source, and the "finished" fragments of problem 2.

**Current state.** Issue 1 of the analysis. `shot_definition_writer.py` (action and `audio_intent`), `shot_prompt_writer.py` (`NOBODY_SPEAKS` added after an action that may say "he talks"), `shot_planning_writer.py` (events with speech but no recorded line). In project 48, about 50 of 244 silent prompts asked for talking or voice-like sound, and 28 of 81 dialogue shots with listeners did not say they stay silent.

Off-screen speech already works when the line is recorded. A character who is only heard in a scene is in the staging's `off_screen` list (`scene_staging_writer.py`) and is never shown. `generation_planner` marks each line `speaker_visible: false` when its speaker is not among the shot's visible characters, which covers both a voice that is never seen and a speaker who is simply out of this shot's frame. The prompt writes "an unseen speaker … says from outside the frame", and code adds `_unseen_sentence` ("nobody visible speaks it, and every visible mouth stays closed while it plays"). Two gaps remain: no sentence tells a visible listener to stay silent, and in a **mixed shot** (a visible speaker and an unseen voice in the same clip) the unseen sentence says every visible mouth is closed without saying who does speak and when.

**Scope.**

- **Owner decisions (2026-11-04).**
  - **Background voices: options A and B.** A voice with no recorded words (an argument through a wall, restaurant chatter, "the voice on the speakerphone continues") is never sent to H3 as a voice. It becomes non-voice sound (a door slams, cutlery and glasses, the phone's speaker crackles faintly) or a listener's reaction (A). Speech the audience must understand needs real lines in the story, which become recorded lines of an off-screen character and take the unseen-speaker route that already exists (B). The system never invents lines (S-1, S-10).
  - **Mixed shots: option A.** The code-written sentence (1C) covers every layout of speakers, mixed shots included.
- **Rules** (1A) in the shot definition and the prompt writer: a silent shot never shows anyone talking, and voice-like ambience is not allowed in any shot, silent or not (conversation, voices, chatter, murmur, laughter, phone voices). A voice with no recorded words is written as non-voice sound or as the listener's reaction (owner decision A).
- **A code check** (1B) in the prompt compiler that refuses talking words and asks again, the way label and tag checks work today. It reads the whole text of a silent shot, and the soundscape of every shot (a dialogue shot may say "says" next to its `<d>` lines, but its ambience may not carry voices). **Planning decides** the word list and its allowed phrases ("before he answers", "listens to the phone", "holds the phone to her ear" and "waits for an answer" are fine).
- **A code-written speaking-roles sentence** (1C) in every dialogue shot, built from the request's audios (`speaker_visible`, `subject`, start time) and the visible subjects, never by the model. It replaces `_unseen_sentence`, so the prompt has one statement of who speaks:
  - **All speakers visible:** "Only <Subject 2> speaks. <Subject 1> and <Subject 3> listen with their mouths closed."
  - **Only unseen voices:** "The voice of <Audio 1> comes from an unseen speaker outside the frame: nobody visible speaks it. <Subject 1> listens with the mouth closed."
  - **Mixed:** "Only <Subject 1> speaks on screen, at 00:02.400. The voice of <Audio 1> comes from outside the frame, and nobody visible speaks it. <Subject 2> listens with the mouth closed throughout."
  - **Planning decides** the exact wording, the wording when there is no visible listener, and how the sentence is written in a rapid exchange (one per `[Shot n]` or one for the whole clip), which SCN-008 relies on.
- **An end-of-speech sentence** (2F): after the last line, nobody speaks again until the clip ends, including an off-screen voice.
- **Planner and definer rules** (1D): an event that implies speech but has no recorded line is shown from a listener or as a reaction, never with the speaker talking on screen, and the shot definition writes no voice for it: its `audio_intent` is non-voice sound only (owner decision A).

**Out of scope.** Detecting speech in a clip (SCN-009). Changing how lines are grouped into shots (SCN-008). Off-screen voices inside a rapid exchange (issue 4 option E). A separate background-voice layer (recorded crowd sound mixed in at render, issue 1 option F), left to a later document. A phone or through-the-wall effect on a recorded voice. Writing lines for wordless voices: that is the story's text (owner decision B).

**Dependencies.** None. Soft: SCN-003 and SCN-004.

**Expected outcome.** No compiled silent prompt asks for talking, no soundscape carries voices, and every dialogue prompt says who speaks on screen, who is only heard and who stays silent, mixed shots included.

**Verification criteria.**

- Compile the prompts of the dinner and phone-call scenes of a test project again (language-model jobs only, no clips): no silent prompt has a talking word, no soundscape has a voice word, and every dialogue prompt with listeners has the speaking-roles sentence.
- A shot with a visible speaker and an unseen voice (a phone call or a reaction shot) gets the mixed sentence with the right labels and start time. A shot with only an unseen voice gets the unseen form. A shot with every speaker visible gets the first form.
- A stand-in answer with "he talks" in a silent shot is refused and asked again. So is a dialogue shot whose soundscape says "murmur of conversation".
- An event with a voice but no recorded line (for example a speakerphone voice that continues) is planned as a listener or reaction shot, and its definition's sound has no voice.
- Regenerate one dinner scene with the owner's confirmation, and listen for speech in its silent shots and for the wrong person speaking in its mixed shots.
- Standard checks.

**Completion checklist.**

- [x] Rules in the definition and prompt writers (silent shots and voice-free ambience)
- [x] Code check and its word list (silent shots and every soundscape)
- [x] Speaking-roles sentence for all three layouts, and the end-of-speech sentence
- [x] Planner and definer rules for speech with no recorded line
- [x] Standard checks (Ruff; no frontend change)
- [ ] Live checks: recompile of the dinner and phone-call scenes, and one regenerated scene (need the owner's go-ahead)

**Completion notes.**

- **Files.** Only instruction text and checks, no migration, no API or frontend change, no stored-shape change. `shot_prompt_writer.py` (rules, `_check_voices`, `_speaking_roles`, `_exchange_roles`), `shot_definition_writer.py` (`audio_intent` and speech rules in `_INSTRUCTIONS`) and `shot_planning_writer.py` (one rule in `_BODY`). Existing prompts are not marked out of date; a scene takes the new rules when its prompts are compiled again (S-1).
- **Rules (1A).** The common rules say no voice of any kind in a soundscape, only the audios of LABELS are spoken, and a voice with no audio is written as the sound of its source or left out (the exception to "leave out nothing"). Every "No speech, no music." soundscape rule now reads "No speech, no voices, no music."
- **Code check (1B), `_check_voices`, called from `check_answer`.** It also runs on a prompt the owner edits (`shot_prompts.save_edit`), so a hand edit is refused the same way. A refusal reaches the model's second attempt through `llm_call.with_correction`.
  - **No audio sent:** every piece except the `subject_N` descriptions is scanned for talking words (`_TALKING_FORMS`: talk, speak, spoke(n), say, said, explain, ask, answer(s/ed/ing), replies/replied/replying, murmur, whisper, mutter, shout, yell, call out, chat, chatter, conversation, voice, speech, laugh, chuckle, giggle and the like). The soundscape is scanned for `_SILENT_SOUNDSCAPE_FORMS` (the voice words, without the verbs of talking).
  - **Audio sent:** only the soundscape is scanned, for `_VOICE_AMBIENCE_FORMS` (conversation, chatter, voices, murmured, talk, speak, whispered, laughter, chuckle, giggle, shout, yell, cheer and the like). A single "voice", "murmur" or "whisper" is left out there on purpose: it is a "murmur of the city", "a whisper of fabric" or the line itself ("the quiet around the level voice").
  - **Allowed phrases** (`_ALLOWED_PHRASES`, taken out before the search): a negation up to six words before ("does not speak", "no one in the room speaks"), "says nothing", "before he answers", "about to speak", "waits for his answer", "waiting for the man to speak", and a line said before the clip ("has just been asked", "the man who spoke"). Matching is by whole word, so "speakerphone" and "listens to the phone" pass. "He talks up his firm", "keeps talking" and "the speakerphone voice drones" are refused.
- **Speaking-roles sentence (1C) and end of speech (2F).** `_speaking_roles` replaces `_unseen_sentence` (deleted). A shot with dialogue gets, in order: "Only <Subject 1> speaks on screen, and only the words of <Audio 1>." (several speakers: "Only … speak on screen, each only the words of their own audio."), "The voice of <Audio 2> comes from an unseen speaker outside the frame, and nobody visible speaks it." (plural for several), "<Subject 2> listens with the mouth closed throughout." (left out with no listener), and "After the last line, nobody speaks again until the clip ends." A silent shot keeps `NOBODY_SPEAKS`. A rapid exchange gets, after each `[Shot n]`, "Only <Subject k> speaks in this shot. <Subject j> listens with the mouth closed throughout." and the end sentence after the last shot (`_exchange_roles`); SCN-008 can rely on it. An explainer is unchanged (its one presenter is always on screen). The sentences add about 30 to 50 words, and the length limit is still checked after assembly. The start time of each line is still written in the shot's own sentence, not repeated in these.
- **Planner and definer rules (1D).** The planner shows an event that implies speech but has no speech unit from a listener or as a reaction. The definer writes no voice in `ambient` or `sound_events` and says that only the speakers of SPEECH talk. No new code check in either (the check is in the prompt compiler, as scoped).
- **Checked offline on a read-only copy of the live database (project 48; the live data was not changed).** All 673 stored prompts were re-checked with their generation requests. Of 429 dialogue prompts, 31 are refused for a voice in the soundscape ("table conversation continues", "his polished laugh carries", "voices carry from the corridor"). Of 244 silent prompts, 61 are refused for talking in their text and 29 for a voice in the soundscape; 154 pass. The first draft of the word lists refused 151 of 429 and 136 of 244, mostly "the murmur of the city" and "the single level voice", which is why a single "voice", "murmur" and "whisper" are left out of the soundscape check and the allowed phrases were widened. Stand-in answers: "He talks with easy gestures" and "murmur of conversation" are refused; "before he answers", "listens to the phone", "waits for an answer", "does not speak" and "a murmur of the city" pass. Sentences printed for all layouts: speakers all visible (alone and with listeners), only unseen voices, mixed (project 48 has 4), and rapid exchange.
- **Not done.** The live checks. Recompiling the dinner and phone-call scenes is a language-model run on the server, which needs a rebuild (it restarts running jobs), and the clip check needs GPU time. Both need the owner's go-ahead naming the project and scenes (S-11). The word lists are a starting point: if a live scene is refused twice for a harmless phrase, add it to `_ALLOWED_PHRASES`.

### SCN-006 — Group shots: everyone present, exact head count

**Status:** In Progress (code, docs and checks on a database copy done; live checks wait for the owner)

**Objective.** A group shot shows every character who is present and nobody else. Fixes problem 5.

**Current state.** Issue 5 of the analysis. `shot_definition_writer.py` rule "one entry for each character who is VISIBLE". The scene staging (`SceneStagingPanel`, `scene_staging`) knows where everyone is (zones and screen sides), but no code uses it to decide who must appear. `reference_selection.py` has room for 8 characters next to the place. In project 48, 49 group-size shots left people out, and one shot with all 5 listed showed more than a dozen.

**Scope.**

- **A rule** (5A): in a wide or medium-wide shot, or any shot framed on the group's view, list every character present at that moment.
- **A code check from the staging** (5B): refuse a group-size definition that leaves out a present, on-screen character, and ask again. Off-screen voices are not counted. **Planning decides** who is "present" when people enter or leave in the scene (for example from the events).
- **A code-written head count** (5C) in the prompt: "Exactly N people are in the room: <Subject 1> … <Subject N>. No one else is present, and the other chairs are empty."
- **Planning decides** whether this phase also adds 5D (an environment state such as "table set for five"), or leaves it for later.

**Out of scope.** Group keyframes made by an image model (5E).

**Dependencies.** None. Soft: SCN-003 and SCN-004.

**Expected outcome.** In a conference or dinner scene, every wide shot lists everyone present, and the prompt states the count.

**Verification criteria.**

- Define the shots of a 5-person scene of a test project again (language-model jobs only): every wide and medium-wide shot lists the present characters, and a stand-in answer that leaves one out is refused.
- Compiled prompts of those shots carry the head count.
- Regenerate one such scene with the owner's confirmation and count the people in 3 wide shots.
- Standard checks.

**Completion checklist.**

- [x] Rule in the definition writer
- [x] Presence from the staging and the check
- [x] Head count sentence
- [x] Standard checks (Ruff, ESLint, `tsc`)
- [ ] Live checks: re-stage and define a 5-person scene again, and one regenerated scene (need the owner's go-ahead)

**Completion notes.**

- **Files.** No migration, no new job type, no setting. `scene_staging_writer.py` (`presence` in the answer form and rule, `_check_presence`, `presence_at`), `shot_staging.py` (`presence` in `for_shot`, `GROUP_SHOT_SIZES`, `is_group_shot`, `presence` in `planner_block`), `shot_definition_writer.py` (rule 5A, `presence` in `staging_blocks`, `_check_presence`, `check_presence`, `MAX_PEOPLE_IN_SHOT`), `shot_cut_repair_writer.py` (one rule, `check_presence=True`), `jobs/define_shot.py` (`check_presence=True`), `shot_planning_writer.py` (one rule about `presence`), `shot_prompt_writer.py` (`_head_count`, one rule), `api/scene_staging.py` (`PresenceOut`, `PresenceIn`), and in the frontend `SceneStagingView.tsx` ("Comes and goes"), `SceneStagingEditor.tsx` (keeps `presence`) and `api/schema.d.ts`. `DATABASE_STRUCTURE.md` has the new staging field and an update line.
- **Presence (5B).** The staging has `presence`: only the placed characters who arrive or leave, each `{character_id, arrives_after_event_id, leaves_after_event_id}` (one may be null). Everyone else placed is present throughout; off-screen characters never are. `presence_at` gives `(present, away)` for a shot from its first and last event; a character who arrives or leaves during the shot is in neither list. A shot with no event sees everyone with no entry as present. `for_shot` adds `presence: {present, away}` only when the stored staging has the key, so **every staging stored before this phase gives the same output and hash as before, and no shot reads out of date**. Such a scene is not checked until it is staged again ("Make again from scene_staging", SCN-004).
- **Rule and check (5A, 5B).** The definer is told to list every character in the place in a medium-wide, wide or extreme-wide shot framed on the group, to show nobody from `away`, and to show no extras. `_check_presence` refuses a shot that shows someone `away`, and a group shot that shows people but leaves out someone `present` (`is_group_shot`: those sizes and `view_key` is the group, never a rapid exchange or an explainer). A shot with no people (an empty `characters`, such as the empty room before anyone enters) is not refused, and a group of more than 8 present (the room the 9 pictures leave) is not checked. The check runs only on model answers (`define_shot`, the cut repair), through `check_presence=True`; an owner edit, "Accept as is" and the other callers keep the default (False). The refusal reaches the model's second attempt through `llm_call.with_correction`.
- **Head count (5C).** `_head_count` is built from the subjects of the generation request, so it always matches the pictures: "<Subject 1> is the only person in this clip. Nobody else appears, not even in the background." or "Exactly N people appear in this clip: <Subject 1>, ... Nobody else appears, not even in the background." It follows the shot's own text, before the speaking-roles sentence or `NOBODY_SPEAKS`; in a rapid exchange it is written once, in `[Shot 1]`, before that shot's roles. No sentence for an explainer, a text-only shot, or a clip with no person picture. The compiler's rules also say to show no one who is not a subject. It is applied to **every** story shot that shows people (owner decision), so public places look empty.
- **Deferred.** 5D (an environment state such as "table set for five") and 5E (a group keyframe), by decision.
- **Checked offline on a read-only copy of the live database (project 48; the live data was not changed).** All 35 stored stagings have no `presence`: `presence_at` gives None and `for_shot` output has no `presence` key, so hashes are unchanged. Of 55 stored group-size definitions with people (a medium-wide, wide or extreme-wide shot framed on the group), 10 list fewer people than are placed (8 of them in scenes with 4 or more placed characters); that is the most the check would refuse if everyone placed were present (it ignores arrivals and leavings, so the real number will differ). Stand-in answers: a wide shot listing 2 of 5 is refused with the three missing names; listing all 5 passes; a shot showing someone who is away is refused; a medium-wide single focused on one character, a medium shot, a rapid exchange and an owner edit pass; someone who arrives during the shot may or may not be listed. Staging answers: no key gives an empty list, a valid entry is stored, and an off-screen character, an unknown event, an entry with no event, a leaving before the arrival and a duplicate are refused. Head count printed for the group, single and rapid exchange cases; 640 stored prompts with the sentence added are at most 7,676 characters (limit 8,000). Ruff, ESLint and `tsc` pass.
- **Not done.** The live checks. Staging and defining a scene again is a language-model run on the server, which needs a rebuild (it restarts running jobs), and counting people in clips needs GPU time. Both need the owner's go-ahead naming the project and scene (S-11).
- **Risks.** H3 may still ignore the count (SQ-7): the check controls only who gets a picture. The sentence says "people" even for a non-human character (the prompt compiler is not given the species; every story so far is human). Saving a staging by hand (the editor) on a scene staged before this phase writes `presence: []`, which turns the check on for that scene with everyone present throughout, and changes the shots' staging hash like any staging edit does.


### SCN-007 — Places inside places (vehicles, lifts)

**Status:** In Progress (code, docs and checks on a database copy done; live checks wait for the owner)

**Objective.** A scene can take place partly inside a vehicle, a lift or a booth. A shot inside it gets that place's picture, and the outside is seen only through the glass. Fixes problem 3 for every story.

**Current state.** Issue 3 of the analysis. `scene_definition_writer.py` asks for "the ONE environment … where the scene mainly happens". `reference_selection.py` always sends the scene's environment picture. `environment_views.py` plans the views of an environment from the scenes set there. `shot_prompt_writer.py` says the view "says what is seen behind the people". In project 48 the "John's Corolla" environment existed but the garage scene could not use it.

**Scope.**

- **Scene definition:** besides `environment_id`, a list of **inner places**: environments of the story that some of the scene's shots happen inside (a car parked in the garage). Each one has a short relation to the main place ("parked in the garage"). **Planning decides** the field names.
- **Environment discovery:** a rule that a vehicle or small enclosed space where action happens is its own environment.
- **Shot definition:** each shot names its place (the main place or one inner place). Code checks that the id is one of the scene's.
- **Environment views:** the views of an inner place are planned from the shots and scenes that use it, like any environment.
- **Reference selection:** the shot's own place picture is sent.
- **An enclosed-space prompt rule** (3E): inside a vehicle or a small room, describe the enclosure first (roof and headliner, pillars, windscreen frame, dashboard, door panels), show the outside only through the glass, and let the light come in through the windows.
- `DATABASE_STRUCTURE.md` for the new JSON fields.

**Out of scope.** Props as subjects (3D). Changing how a story is split into scenes (3B).

**Dependencies.** None. Soft: SCN-003 and SCN-004.

**Expected outcome.** A scene in a garage with in-car shots sends the car's picture for those shots, and the clips show a roof.

**Verification criteria.**

- Define a garage scene with in-car action again (language-model jobs only): it lists the car as an inner place, and its in-car shots name it.
- Their reference manifests hold the car's picture, and their prompts follow the enclosed-space rule.
- A scene with no inner place works exactly as before.
- Regenerate one such scene with the owner's confirmation and check 3 in-car frames for a roof and a consistent interior.
- Standard checks.

**Completion checklist.**

- [x] Scene definition field and its check
- [x] Discovery rule
- [x] Shot place and its check
- [x] Views and reference selection
- [x] Enclosed-space rule
- [x] `DATABASE_STRUCTURE.md`
- [x] Standard checks (Ruff, ESLint, `tsc`)

**Completion notes.**

- **Files.** No migration, no new table, no new job type, no setting. `scene_definition_writer.py` (`inner_places` in the answer form, `_inner_places`, `MAX_INNER_PLACES` 3), `scene_definitions.py` and `discovery_edits.py` (an inner place counts as a chosen and a used environment), `discovery_writer.py` (rule 3A), `shot_planning_writer.py` (`INNER PLACES` block, `place` per shot, `_place`, `_check_places`), `shot_plans.py` and `jobs/plan_shots.py` (the inner places reach the job, its checks and a manual save), `shot_definitions.py` (`_inner_place`, `inner_place` in the shot fields, `inputs.inner_place.sha256`, two out-of-date reasons), `shot_definition_writer.py` and `jobs/define_shot.py` (`VIEWS` block, `_inner_view`, `place` in the stored specification), `shot_cut_repair_writer.py`, `jobs/repair_shot_cut.py` and `shot_continuity.py` (the place is kept through a cut repair), `shot_references.py` (the inner place's own pictures), `shot_prompts.py` and `shot_prompt_writer.py` (view from the inner place, enclosed-space rule 3E), the API models of scene definitions, shot plans and shot definitions, and the story workspace (scene definition view and editor, shot plan view and editor, shot specification view and editor). `schema.d.ts` was edited by hand (`npm run gen:api` needs the running server).
- **Scene definition.** `inner_places`: up to 3 `{environment_id, relation}` (relation up to 100 characters), written **only when the list is not empty**, after `environment_state`. The ids must be discovered environments of the story, never the main place, never twice. `environment_id` is told to be the larger place. An inner place is a chosen environment, so it is linked, defined and counted in "where used".
- **Planner names the place (design choice).** A planned shot carries `place` (an inner place id) **only when it is inside one**; null, empty and the main place's id mean the main place; any other id is refused so the model answers again. A scene with no inner place ignores the field. A shot that `continues_previous` must have the same `place` as the shot before it. The shot's specification copies `place` after `scene_id`.
- **Light staging (design choice).** A shot inside an inner place has no zone staging (`_shot_staging` gives None; nobody is placed in the car). Its VIEWS are the inner place's `establishing` view and the views its own view plan has, with no `allowed_for`; `composition.view` must be one of them. The environment given to the definer is the inner place in its default state, with `inside_of` (the main place's name, description, state and the relation) to mark an enclosed place. The environment views of the main place are unchanged.
- **References and prompt.** The reference catalog of a shot with a `place` holds that place's pictures in its default state (not the main place's). The prompt compiler gets the view of that place and the enclosed-space rule: describe the enclosure first, show the outside only through the glass, the larger place is never around or above the people.
- **Staleness.** A shot definition of an inner-place shot records `inputs.inner_place.sha256` (the place, its relation and its views); the shot reads out of date when the place is gone from the scene or when it, its relation or its views changed. Nothing is recorded for a shot of the main place.
- **Nothing existing changes.** Every new key is written only when set. Checked on a read-only copy of the live database: the state of all 147 (project, stage) reads of scene definitions, shot plans and shot definitions (every status, out-of-date reason, stored definition and hash) is identical to what the code before the phase gives.
- **Checked offline on that copy with stand-ins (nothing was written to the live data).** Scene definition: an inner place is stored; an unknown id, the main id, a repeated id and more than 3 are refused; an empty list stores no key and an identical result. Shot plans: an inner place id is kept; unknown is refused; a scene with no inner place ignores `place`; `continues_previous` across places is refused. Shot fields of a stand-in in-place shot (project 30): the environment is the inner place with `inside_of`, views are `establishing` only (that place has no plan), `staging` is None, `inputs.inner_place` is set, an unlisted place is refused, and restoring the scene gives fields equal to before. The definer request has the `VIEWS` block and note only for the inner shot; `check_answer` accepts an inner view and refuses a view of another place and a missing view. The reference catalog of the same shot holds only the inner place's picture; the main shot's holds only the main place's. Ruff and `ruff format`, ESLint and `tsc` pass.
- **Deferred or different from the scope.** The planner (not the definer) names the place, by decision. The views of an inner place are **not** planned from the scenes that use it as an inner place: the view planner is unchanged, so an inner place with no scene of its own has only its master picture as a view (`establishing`). The view-plan artifact is not recorded in the shot's inputs; the hash of the place with its views is. The shot plan view shows the place id, not its name. `SceneDefinitionIn.inner_places` allows 20 entries in the API schema; the writer's check keeps the limit of 3.
- **Not done.** The live checks (define a garage scene again, read the manifests, 3 in-car frames for a roof). They need a rebuild, language-model runs and GPU time, and the owner's go-ahead naming the project and scene (S-11).
- **Risks.** The model may still not list the car as an inner place, or not name it per shot (SQ-7); the code only controls what is sent once it does. In-car shots have no presence or off-screen checks, and the place is always in its default state. A story whose car was never discovered as its own environment needs its environments discovered again (rule 3A applies only to a discovery run from now on).

### SCN-008 — Conversation flow: rapid exchanges for short lines

**Status:** In Progress (code, docs and checks on a database copy done; live checks wait for the owner)

**Objective.** Runs of short lines between two people become one multi-shot clip, so a conversation flows and the place stays the same across its cuts. Fixes problem 4, and the lone one-word lines of problem 2.

**Current state.** Issue 4 of the analysis. `shot_planning_writer.py` says "Use false for almost every shot" and "Prefer one line of dialogue per shot", with `EXCHANGE_MIN_LINES` 2 and `EXCHANGE_MAX_LINES` 3. `generation_planner._exchange_cuts` and `shot_prompt_writer._EXCHANGE_RULES` make the exchange. PHASE-043 in `Implementation_phases.md` is In Progress (owner check V6b open). In project 48, all 16 exchanges passed, 15 on the first take.

**Scope.**

- **Planner instructions** (4A): group consecutive short lines between the same two people into a rapid exchange; keep single shots for long or important lines.
- **A code pass after planning** (4B): merge runs of 2 or 3 alternating short lines into one exchange, while keeping the event-order checks. **Planning decides** the limits (for example each line under 2 s and the run under about 8 s) and whether 4B is built now or only if 4A under-uses exchanges on the test stories.
- Record the result in PHASE-043's notes, and close V6b with the owner when the live check passes.

**Out of scope.** Reactions inside an exchange (4C), one audio per speaker (4D) and three speakers (4E).

**Dependencies.** SCN-005 (same files, and the listener sentence must cover exchanges).

**Expected outcome.** Most runs of short lines in a two-person conversation become exchanges.

**Verification criteria.**

- Plan the shots of a two-person scene with many short lines again (language-model jobs only): the share of exchanges is reported, and no event is lost or reordered.
- Regenerate that scene with the owner's confirmation and watch it in a scene render.
- Standard checks.

**Completion checklist.**

- [x] Planner instructions
- [x] Merge pass (built, owner's choice)
- [x] PHASE-043 notes
- [x] Standard checks (ruff check and format; no frontend change)
- [ ] Live checks: plan one two-person scene again, and one regenerated scene watched in a scene render (need the owner's go-ahead)

**Completion notes.**

- **Files.** No migration, no API or frontend change, no setting, no stored-shape change. `shot_planning_writer.py` (rule text, `SHORT_LINE_MAX_S` 2.0, `EXCHANGE_SPEECH_MAX_S` 8.0, `merge_exchanges` and its helpers) and `jobs/plan_shots.py` (the call, and `exchanges_merged` in the job output and log). A merged shot is an ordinary `rapid_exchange: true` shot, so PHASE-043's definer rule, router and prompt form and SCN-005's `_exchange_roles` apply as they are.
- **Planner instructions (4A).** The `rapid_exchange` rule now asks for it on a run of two or three short lines (about 2 s or less each, 8 s or less in all) between the same two characters, and says when a line keeps its own shot (long, important, off screen or only heard, a wordless reaction between the lines). "Prefer one line per shot" reads "except in a rapid exchange", and the short-line shot-length rule leaves out lines in an exchange. The explainer note and the cut planner are unchanged. Existing plans are not marked out of date (staleness does not read the instructions); a scene takes the rule when it is planned again.
- **Merge pass (4B), decided in planning (owner's choices).** Built now, limits 2.0 s per line and 8.0 s per run. `merge_exchanges(content, units, unit_seconds, staging, target_min_seconds, events, warnings)` runs **only on a model's answer** in `plan_shots` (first plan and automatic re-plans), before `h3_lengths.fit_shots`; a plan saved by hand (`save_manual`) is never merged. It also skips a cut plan (`read.take`), an explainer, and a job with no staging.
  - A shot is a candidate when it is of type `dialogue`, not an exchange and not a continuity shot, carries exactly one dialogue line of at most 2.0 s, is not followed by a continuity shot, and its speaker is placed in the staging and is neither in `off_screen` nor in `presence` (arrivals and leavings are skipped on purpose).
  - A run is candidates in a row in the same `place`, alternating between exactly two speakers. It is cut into exchanges of 2 or 3 lines with no lone line (4 is 2+2, 5 is 3+2, 7 is 3+2+2); a group with more than 8 s of speech stays single.
  - The merged shot has the union of the events, the lines in order, `rapid_exchange` true, `target_duration` = the larger of the planning minimum and the lines plus `DIALOGUE_SETTLE_S` (then moved onto an H3 length by `fit_shots`), and the model's own descriptions joined (cut to 300 characters with a warning if needed). Shots are renumbered `shot_1..N`.
  - The merged plan is checked like an answer (event cover and order, speech placement, exchange rules, places); if any check fails the model's plan is kept and 0 is reported, so a merge cannot lose or reorder an event.
- **Checked offline on a read-only copy of the live database (project 48; the live data was not changed).** The newest stored plan of each of the 35 scenes, with its units, recorded lengths and staging, was merged: 71 exchanges made, shots 673 to 578, dialogue lines inside exchanges 38 of 456 to 204 of 456 (about 45 %). `scene_parking_garage`: 31 single-line shots to 9 exchanges, 45 to 32 shots, 22 of 31 lines in exchanges. Every merged plan passes `check_answer`, keeps every line in the same order, and after `fit_shots` has no blocking timeline problem (0 in all 35 scenes). Stand-ins: A,B,A merges into one 3.5 s exchange; 4 and 5 lines split 2+2 and 3+2; a 2.4 s line, an off-screen speaker, a third speaker, the same speaker twice, a continuity shot, a change of place, a speaker with a `presence` entry, a non-dialogue shot and a missing staging each stop or limit the merge; a long description is cut with a warning. Ruff check and format pass.
- **Not done.** The live checks: planning a two-person scene again is a language-model run on the server (needs a rebuild, which restarts running jobs), and watching it needs GPU time. Both need the owner's go-ahead naming the project and scene (S-11). PHASE-043's owner check V6b is still open, and SCN-008 is not marked Completed until a real exchange clip passes it.
- **Risks.** The merge turns about 45 % of project 48's lines into exchanges, so V6b matters more now: if H3 does not follow `[Shot 2] At <cue>` with two voices, many more clips are affected. The merged shot's description is the two or three single descriptions joined, so it can read as a list; the later definition and prompt steps write the real content. Lines play back to back inside an exchange; the pause between answers is whatever H3 makes.

### SCN-009 — Catch unwanted speech

**Status:** In Progress (code, docs and checks on a database copy done; the Parakeet babble check and live checks wait for the owner)

**Objective.** Speech that should not be there is found: words in a silent shot, and words outside a line's own time in a dialogue shot.

**Current state.** Issue 1 (option E) and issue 2 (option D) of the analysis. Silent shots are never transcribed (`_needs_dialogue_check`). The transcriber returns `word_timestamps`. **Not verified:** what Parakeet returns for babble in an invented language.

**Scope.**

- **First, a check with the owner:** run 3 known bad takes (babble) and 3 good silent takes through Parakeet and record what it returns. If it returns nothing for babble, **Planning decides** another signal (for example voice activity detection) before building the rest.
- **Silent shots:** transcribe them, and fail a take when words are heard.
- **Dialogue shots:** compare only the words inside each line's time (its start to its end plus about 0.7 s), and report words outside as "extra speech".
- The check result shows which kind of problem was found.

**Out of scope.** Replacing H3's sound in silent shots (1F).

**Dependencies.** SCN-001 (the same check code).

**Expected outcome.** A silent take with babble fails, and a dialogue take where H3 kept talking says so.

**Verification criteria.**

- The 3 babble takes fail and the 3 good silent takes pass (or the result of the owner check is recorded with the chosen signal).
- The selected take of `scene_dinner_begins/shot_7` (a silent shot whose prompt said "he talks") is checked, and the result is recorded in the notes.
- Standard checks.

**Completion checklist.**

- [ ] Owner check of Parakeet on babble (the owner runs it with the other live checks, at the end)
- [x] Silent-shot check
- [x] Line time windows and "extra speech"
- [x] Standard checks (Ruff, ESLint and `tsc` pass; `schema.d.ts` regenerated from the code's own OpenAPI; no migration, so no `docker compose up --build` for the schema)

**Completion notes.**

- **No migration, no new job type, no new setting.** The existing `check_take_dialogue` job does both checks. `shot_take.dialogue_check` is now version 3 (JSON); `DATABASE_STRUCTURE.md` has the update line and the shape.
- **Decisions made in planning (owner's answers, 2026-11-05).** (1) **Signal (SQ-1):** Parakeet's words are assumed to work; the owner runs the babble check (3 babble takes and 3 good silent takes) with the other live checks. If Parakeet returns nothing for babble, the silent check passes every take (harmless, no help) and voice activity detection is a follow-up. SQ-1 stays open until then. (2) **Older silent takes:** new takes are checked by themselves; takes made before the phase are checked only from a click, as a **report only** (stored and shown, never unselects the take, never queues a retry). (3) **Extra speech fails the take** and is retried like any failed clip.
- **Modules.** `services/dialogue_matching.py`: `FILLERS` (uh, um, mm, mhm, hm, ah, oh, ...; not `INTERJECTIONS`, which holds real words such as "hey"). `services/dialogue_check.py`: `DialogueLine.duration_s`, `compare` (line windows; the old whole-clip comparison is `_judge`), `compare_silent`, `blocks`, `is_report_only`, `is_silent`; constants `LINE_LEAD_S` 0.3, `LINE_TAIL_S` 0.7, `EXTRA_SPEECH_MIN_WORDS` 2, `SILENT_WORDS_ALLOWED` 0. `services/shot_takes.py`: `silent_checked`, `checks_speech`, `start_silent_speech_check`, `REPORT_ONLY_KEY`, `TakeEntry.checks_speech` and `can_audit_speech`, `ShotTakesState.silent_unchecked_count`; `queue_dialogue_check(..., report_only=)`. `jobs/generate_shot.py` queues the check for a silent take with a sound track. `jobs/check_take_dialogue.py` chooses `compare` or `compare_silent`, and stores a report with `report_only: true` and `kind: null`.
- **Line windows.** A line's window is its start less 0.3 s to its start plus its length plus 0.7 s; a word is inside when its middle is. Only the words inside are compared with the lines (all steps of SCN-001). Words outside are **extra speech** when two or more remain after leaving out filler sounds **and the line's own words** (a line that H3 says slowly runs past its window; this was added after the first run on project 48 showed 11 false failures of exactly that kind). A take that fails inside the windows but whose whole clip matches still passes (the line was said at another time than planned), with no extra-speech verdict. An empty window on a one-word line is "speech not verifiable" only when nothing else was heard either; a word outside is judged like the whole clip, as before. A line with no `duration_s` (a take made before the phase) and a FLOW-007 presenter line are compared as before. The window used for each line is stored in `windows`.
- **Silent shots.** A new take of a shot with no lines has `inputs.silent_check: true`. If its clip has a sound track it waits for its check like a dialogue take (`_needs_dialogue_check`, `_usable`, `select_take`: "Use anyway" works as for dialogue); a clip with no sound track needs none. `compare_silent` passes when no word is left after the fillers, and stores them in `matched_heard`, so the same-answer stop of SCN-001 (`_repeated_answer`) works for silent shots unchanged. Takes made before the phase have no flag: they are never "not checked" and **no shot changes status**.
- **Report on older takes.** `POST /api/projects/{id}/shot-takes/check-silent-speech` (body `{scene_id?}`, 202 `{job_ids}`, 422 when none needs it) queues one job per **selected** silent take with a sound track and no check, with `input.report_only` true; the buttons are "Check silent takes for speech (N)" for the project and "Check silent takes (N)" in each open scene. Each job is one short GPU transcription, started only by the click (S-11). `_usable` treats a report as passing, `queue_retry` ignores it (`kind` is null), and the job selects nothing. "Score dialogue again" also judges failed silent checks again, and keeps `report_only`.
- **API and frontend.** `TakeDialogueOut` gains `mode`, `extra_text`, `report_only` and the new outcomes; `ShotTakeOut` gains `checks_speech` and `can_audit_speech`; `ShotTakesOut` gains `silent_unchecked_count`. The take badges are "No speech heard", "Speech in a silent shot", "Extra speech" and "Speech heard (older take, still used)"; the take row shows what was heard in a silent shot and the words outside the lines.
- **Checked offline on a read-only snapshot of the live database (project 48; the live data was only read, and a queue on the copy was tried on the copy).** All 745 stored dialogue checks were judged again with the windows (70 have no window, 675 have): **689 that passed still pass, the 56 that failed still fail, and none changes**; 10 of the failures also carry an `extra_speech` problem (for example "Don't." with "you think that's the first one" heard, "When?" with "we're going to be able to do it", "People underestimating you." with "what he wanted"). `scene_parking_garage/shot_11` passes (all 6 takes). Before the refinements the first run turned 11 passes into failures (the last words of a slow line, for example "than you") and 9 failures into passes (a Cyrillic "мам" heard for "Mom?"), which is why the two rules above were added. Stand-ins: an empty transcript and "mm" pass a silent shot; "uh he said" and a babble-like word list fail it; two silent failures hearing the same words stop the retry, and different words do not; a failing report keeps the take selected, is never retried, and an older silent take is never "not checked"; a new silent take with a sound track waits for its check, and one with none does not. On the copy, project 48's state is unchanged (671 generated, 1 out of date, 1 failed, 0 not checked) and 243 selected silent takes can be reported on; pressing the button for `scene_dinner_begins` on the copy queued 14 report-only jobs and a second press was refused.
- **Not done.** (1) **The owner check of Parakeet on babble (SQ-1).** (2) The live checks: a new silent take is checked only after a rebuild (it restarts running jobs) and costs one short GPU transcription each; the button on `scene_dinner_begins` to check `shot_7` (the silent shot whose prompt said "he talks") needs the same and the owner's go-ahead naming project and scene (S-11). The results go into these notes. The phase is not Completed until then.
- **Risks.** Every new silent take waits for one short transcription before it is selected, which delays a chained shot a little. If Parakeet ignores babble, the silent check catches only real words. H3 may say a line at another time than planned: the margins, the two-word minimum, the line's own words and the whole-clip fallback limit false "extra speech", but a short line whose speech is heard far outside its window together with another word can still be refused (it is retried like any failed clip, and "Use anyway" works).

### SCN-010 — Scene lanes in the automatic run

**Status:** In Progress

**Objective.** In a full run, each scene moves to its next step without waiting for the other scenes, so scene 1's clips start early.

**Current state.** §2 (the pipeline run) and §4.1. In project 48, the first clip started 7 hours after the run began because every shot of every scene had to be defined first.

**Scope.**

- **The step kinds** of §4.1 in code.
- **Per-scene waiting:** a per-scene target waits only for its own scene's targets of the steps it needs, and for the story-wide steps it needs. The step adapters return targets for the scenes whose upstream is ready. **Planning decides** how this fits `_needs_are_ready` and `plan_step`, and which adapters assume a step is complete for every scene.
- **Cross-scene steps:** the waits of §4.1.
- **Review points per scene:** a review point holds the scene that reached it, not every scene. **Planning decides** the screen (for example one review per scene, or a review of scene 1 only that then lets every scene through).
- **Story order:** lanes go in story order, with SCN-002's levels.
- A scene render at the end of each lane (SCN-003).
- The pipeline board shows progress per scene.

**Out of scope.** Boundary checks (SCN-012) and the final pass (SCN-013).

**Dependencies.** SCN-002 and SCN-004.

**Expected outcome.** On a new test story, scene 1 can be watched a few hours after starting, and further scenes arrive one after another.

**Verification criteria.**

- On a test story, scene 1's first clip is queued before the last scene's shot definitions are done (job times).
- A failed target holds only its own scene.
- A review point stops the scene that reached it, and the others go on.
- A scene run (SCN-004) still works.
- Standard checks.

**Completion checklist.**

- [x] Step kinds
- [x] Per-scene waiting in the run and the adapters
- [x] Cross-scene waits
- [x] Review points per scene
- [x] Board per scene
- [x] Standard checks (ruff check and format, ESLint and `tsc -b` pass; `schema.d.ts` regenerated from the code's own OpenAPI, additions only)
- [ ] Live run on a test story (waiting for the owner's go-ahead, see the notes)

**Completion notes.**

- **No migration, no new job type, no new setting.** Run state is in `job.output` (`made_in`, `scene_reviewed`, `scene_review_at`, `lanes`, `answers_applied`), answers to scene reviews in `job.input.scene_answers`. `DATABASE_STRUCTURE.md` §5 describes both.
- **Step kinds.** `Step.kind` is `story`, `scene` or `cross` (§4.1 as code); `Step.whole` lists the needs a step waits for as whole steps (every scene), the others are per scene. `hard_needs` (what a step needs complete) and `lane_needs` (what it needs per scene) split `needs`; `_check_graph` refuses a `whole` that is not a need, and a `whole` on a story step.
- **Per-scene waiting.** `Open(scenes, everything)` says what is still open in a step. `plan_step(..., upstream)` does not create or report a target whose scene is open upstream (counted in `StepPlan.upstream_waiting`); `reachable(target, upstream)` is the gate. A lane step is complete only when no scene is open upstream either. `StepPlan.unfinished` and `busy` feed the lane summary. When every scene of the run is open upstream, a step's stage is not read at all.
- **Cross-scene steps (SQ-5).** `environment_views` is a `cross` step: its targets are `scenes=` (the scenes of the place), so a view is planned when the scenes it is used in are staged (`EnvironmentEntry.scene_ids`), and the step needs `scene_definitions` whole. A scene's later steps wait for the views of its own places only. `resolution`, `look_state_images` and `callout_plan` stay story-wide, so `shot_definitions` wait for `resolution`, and `references` for `look_state_images`.
- **Adapters (SQ-4).** Every adapter was checked. The scene adapters list targets per scene and need no change; `environment_views` (above) and `scene_render` changed. **`scene_render` in a full run** is now one target per scene (it needs `shot_generation`, `graphics`, `callout_plan` and `shot_plans` whole); a scene that cannot be rendered is a warning and counts as done. The pipeline board no longer shows `scene_render` as off.
- **Review points per scene.** `ReviewPoint.per_scene` is true for `scenes`, `staging`, `shot_plans` and `shots`; the two story-wide ones (`story_structure`, `images`) still stop the whole run. **Decision made in planning (owner): one review per scene, the others go on.** A scene waits at a point once the run made something in the point's steps for it (`made_in`), and passes without a pause when it made nothing. `held_scenes` holds a scene's later steps until it passes; steps that need a held point for every scene (story-wide ones) wait for all scenes. Answers: `POST /api/projects/{id}/story-pipeline/scene-review/{scene_id}` with `{rejected: [{step, target}]}` (422 when the scene is not waiting or a target is not in the review). The answer is appended to `job.input.scene_answers` because the run overwrites its `output` on every poll; the run applies it on its next look (`apply_scene_answers`) and looks again at once.
- **Board per scene.** `GET .../story-pipeline` returns `run.lanes` (one per scene: `status`, `step`, `review`, `done`, `total`) and `scene_reviews` (one per scene waiting, with its review's steps and targets). Run view of the Story pipeline panel: new `PipelineLaneList` (scene, status, step, "N of M", Show) and one `ReviewPointPanel` per waiting scene (button "Approve this scene"; the scene variant says the other scenes go on).
- **Known effects.** With the review point `scenes` on, `shot_definitions` wait until every scene passed it (because `resolution` reads all scenes); with `images` or any whole-story point, nothing changes from before. `references` wait for all look-state images. `music_*`, `music_placement` and `render` still wait for every scene (they are story-wide).
- **Names for SCN-012 and SCN-013.** `story_pipeline.lane_steps()`, `is_lane_step`, `hard_needs`, `lane_needs`, `Open`, `reachable`, `lane_summary` (the lane list, in story order), `output["lanes"]` and `output["made_in"]`; a boundary check can wait on `scene_render` of two neighbouring scenes through `opens["scene_render"]` in `_evaluate`.
- **Checked on a copy of the live database (all projects of the copy; the live data was only read; `_evaluate` only, no job was started).** Full-run plans are identical before and after the change, apart from the lanes themselves and `scene_render` (for example project 53: 9 of 9 scenes instead of 1 of 1; project 45: 8 of 8). Projects stuck at "links" stay stuck there. Project 41 (12 scenes, 39 of 44 shots defined): in the first look, `shot_generation` creates the clips of the two scenes whose prompts exist (scene 1 `shot_2`, scene 10 `shot_5`) while `word_timings` is still being made for every scene (before the change, `shot_generation` was not reached), `shot_continuity`, `references`, `generation_requests` and `prompts` count 2 to 6 targets waiting on their scene's upstream, and the 36 cancelled-clip problems carry their own scene, so a failed target holds only its scene. Scene runs (SCN-004: two scenes, remake from `shot_plans`, remake from `shot_generation`) give the same plans as before. With review point `scenes` on project 41: every scene waits for its review, approving one scene lets only that scene go on (staging, speech, shot plans, graphics), and rejecting `events` for a scene remakes only that scene's events. The GET and the scene-review POST were tried through the app on the copy (scene waiting, scene not waiting, a step outside the review, accepted).
- **Not done.** The live check of the verification criteria (scene 1's first clip queued before the last scene's shot definitions are done; a review point stopping only its scene) needs a run on a new test story, a rebuild (restarts running jobs) and GPU time. It needs the owner's go-ahead naming the project and the scene (S-11). Until then the phase is not Completed.
- **Risks.** A scene review that waits long does not hold other scenes, but it holds the story-wide steps that need every scene. A user who edits during a scene review gets the usual out-of-date rules for that scene.

### SCN-011 — Music in scene renders

**Status:** In Progress (code, docs and checks on a database copy done; the live run waits for the owner)

**Objective.** A scene render has its music before every clip of the story exists.

**Current state.** §2 (music) and §4.4. `music_placement.gather` needs every take. `music_preview` reuses the newest choices of the language model.

**Scope.**

- **A provisional placement** (§4.4): placed with the planned time of every missing clip, reusing the newest choices, asking the model nothing. **Planning decides** whether it is stored (marked provisional) or worked out each time a scene render starts.
- **Scene renders** use it, cut to the window with short fades.
- The scene render says when it has no music and why (no plan yet, plan out of date, music not generated yet).

**Out of scope.** The final placement (unchanged, SCN-013).

**Dependencies.** SCN-003.

**Expected outcome.** A scene render made before all clips exist plays the story's music.

**Verification criteria.**

- A scene render with music made before every clip exists: the music starts and stops at the same seconds as in a later full render, except for hits that were moved to a sound found in the clip.
- A scene render with an out-of-date plan has no music and says why.
- No paid call is made by a provisional placement.
- Standard checks.

**Completion checklist.**

- [x] Provisional placement
- [x] Music in scene renders, with fades
- [x] The no-music reasons
- [x] Standard checks (ruff check and format, ESLint and `tsc -b` pass; `schema.d.ts` regenerated from the code's own OpenAPI, additions only)
- [ ] Live run on the server (waiting for the owner's go-ahead, see the notes)

**Completion notes.**

- **No migration, no new job type, no new setting, no new table.** The one new stored thing is the optional key `music.provisional` in the frozen scene timeline (`scene_render.inputs`); `DATABASE_STRUCTURE.md` describes it.
- **Decision made in planning (owner): the provisional placement is not stored.** It is worked out when a scene render is started (`scene_renders.start_render`, so the button and the `scene_render` step of a run alike), and the scene's frozen timeline records what it was made from. A read (`GET .../scene-renders`) only checks that one can be made and measures nothing.
- **Names for SCN-013.** `render_music.scene_gate(session, project, place=)` returns a `SceneMusicGate` (`source`, `blocked_reason`, `provisional`, `provisional_inputs`, `final_current`, `final`). **The current final placement is always preferred**; a provisional one is used only when there is none (missing, out of date or blocked). `music_placement.place_provisional`, `provisional_check` (memoized, no measuring), `reuse_choices` (moved from `music_preview`), `input_differences` (the out-of-date sentences, shared with the final placement), `story_renders.timing_sources`, `story_render_plan.build_timing_plan`, `MusicSource.provisional`, `story_renders.mix_constant_reasons`.
- **How the timing is kept the same as the full render's.** Shot lengths come from the shot plans, not from the clips, so `build_timing_plan` (the full builder with placeholders; a clip shorter than its shot also stands as a placeholder, so no clip can stop it) puts every shot, line and cut on the same second as the full render. Placeholders have no sound, so the placer puts a moment on its planned second there (its normal fallback) and snaps to a detected sound in the clips that exist. A dialogue line played for placeholders (`narration[].stand_in`) is left out of the narration speech and of the timing hash, because it is already a dialogue unit.
- **No model call.** The placer's questions are answered from the newest final placement's choices (matched by id and description); a question with no answer gets `None`, so the code's own pick or a flag is used. No `place_music` job is made (checked: the count of `place_music` jobs did not change).
- **Out of date.** A provisional render has `timing_sha256` (shots' frames, narration and every speech unit's span, **without** the selected takes), the plan, the cues, the selected music takes, the settings and the analysis and placer versions. A clip arriving in another scene does **not** make it out of date. It is out of date when the final placement has been made since ("The final music placement was made since this video was made."), when music cannot be placed now (the reason), when the plan, a cue, a music take, a setting or the story's timing changed, or when the ambience switch or a mix setting changed.
- **No-music reasons.** The plan is missing or out of date, a scene's shots are not defined, a cue has no recording yet or its recording is out of date (the existing messages of `music_cues` and `music_placement`). They are shown as `no_music_reason`, as before. A scene that starts at an unknown place (`scene_start_unknown`) still has no music.
- **API and frontend.** `SceneRenderStateOut.music_provisional` and `RenderMusicOut.provisional`; `SceneRenderList` says "with provisional music" and "with the story's music, placed for now on the planned times of missing clips". A provisional render records `placement_version` 0.
- **Checked on a copy of the live database and its media, inside the running container with the new code and `DATA_DIR` on the copy (the live data was only read; no rebuild, no job was run, nothing was written to the media).** (1) With every clip present, the provisional placement equals the stored final placement on all projects that have one (19 of 19, 15 of 15 and 22 of 22 placed sounds on projects 53, 52 and 49). (2) On project 53 with the selected clips of 6 of 9 scenes removed on the copy, the final placement is blocked ("These shots have no clip yet"), the scene renders read as provisional, and the provisional placement has 18 of 19 sounds on the same samples as the final one; the one that differs is a hit (`cue_10`) that the final placement moved onto a sound found in a clip that was removed. A scene render started on the copy gives a timeline with a bed and two score sounds cut to the scene's window (total 550000 samples), 0.5 s linear fades at the cut edge (24000 samples) and `music.provisional` set. (3) Its stored row stays "current" when a clip arrives in another scene, becomes out of date with "The final music placement was made since this video was made." when the clips are back, and with the plan made out of date and no final placement the scene has no music and `no_music_reason` is "The music plan is out of date. Plan the music again first." (4) The full render timelines, the music timelines and the final placement's inputs and reasons of all 7 projects that have a timeline are **byte-identical** (`cmp`) between the code before and after this phase.
- **Known effects.** In a full run the `scene_render` step makes scene renders that are provisional; once the final placement exists they read as out of date, so by the run's own rule for out-of-date scene renders they should be made again (local FFmpeg work only, no GPU); this was reasoned from the code and not run. The first press on a story measures the narration files and the clips near moments; on project 53 the placement took about 2 seconds with a warm cache, and the measurements are cached by file hash. A provisional render has no `placement_id`, so the "placed again" sentence does not apply to it.
- **Not done:** the live run on the server (needs a rebuild that restarts running jobs and the owner's go-ahead naming project and scene), and listening to a rendered scene with provisional music: the check above covers the timeline the job renders, not the sound.

### SCN-012 — Continuity across scene boundaries

**Status:** In Progress (code, docs and checks on a database copy done; the live run waits for the owner)

**Objective.** When one scene continues straight into the next, the cut between them is checked and fixed in text before the clips are made.

**Current state.** §4.5. `shot_continuity` checks the cuts inside a scene (jobs `check_shot_continuity`, `repair_shot_cut`). Scene definitions have `continuity_start` and `continuity_end`.

**Scope.**

- The rule for "follows directly" (§4.5). **Planning decides** it.
- For each such pair, check the last shot of the first scene against the first shot of the second, with the same checks and repair route as a cut inside a scene.
- In lanes (SCN-010), the second scene's first shot waits for the check.

**Out of scope.** Fixing clips after generation.

**Dependencies.** SCN-010.

**Expected outcome.** No jump in clothing, props, place or light at a cut between two scenes that follow directly.

**Verification criteria.**

- On a test story with two scenes that follow directly, a stand-in mismatch (a different jacket) is found and repaired.
- Scenes that don't follow directly are not checked.
- Standard checks.

**Completion checklist.**

- [x] The "follows directly" rule
- [x] Boundary check and repair
- [x] Lane wait
- [x] Standard checks (ruff check and format, ESLint and `tsc -b` pass; `schema.d.ts` regenerated from the code's own OpenAPI, additions only)
- [ ] Live run on a test story (waiting for the owner's go-ahead, see the notes)

**Completion notes.**

- **No migration, no new job type, no new setting, no new table.** New JSON only: `scene_definition.content.continues_previous` (written only when true), and in `shot_continuity_check` the boundary `previous_scene` and the artifact `previous_shot_definition`. `DATABASE_STRUCTURE.md` has the update line and the shapes.
- **Decisions made in planning (owner's answers, 2026-11-05).** (1) **The rule:** the scene definition model writes `continues_previous`; code also requires the same place (the same `environment_id`, or one scene's main place is an inner place of the other) and no graphic shot as the previous scene's last planned shot or this scene's first. A definition made before the phase has no flag and is never checked. (2) **Looks:** code compares the resolved looks of the characters seen in both scenes and **reports** a difference (scene page and a pipeline warning); no repair changes a look. (3) **Mechanism (planning):** the boundary is folded into the following scene's own check, not a separate check: its `b0` is `previous_scene` (last shot of the scene before against this scene's first shot), and the repair changes only this scene's first shot, at its start. The previous scene is never changed, so a scene never waits for a later one and the two checks cannot undo each other. This replaces the "cross-scene step on `scene_render`" idea of §4.1 and the SCN-010 note.
- **Modules.** `scene_definition_writer` (answer form, rule, `continues_previous` in `check_definition`). `shot_continuity_writer`: `PREVIOUS_SCENE`, `follows_directly`, `look_mismatches`, `boundaries(..., previous=)`, and `editable_and_frozen` treating `previous_scene` like `scene_start`. `shot_continuity`: `PreviousCut`, `_previous_cuts`, `_previous_reason`, `_previous_of`, `_scene_busy`, `_covers(row, entry, previous)`, `queue_following_check`; `SceneContinuity.previous_scene_id` and `look_mismatches`. The cut handed to `repair_shot_cut` carries `previous_shot`, `time` and `environment_state` (read only). `jobs/check_shot_continuity` and `jobs/repair_shot_cut` call `queue_following_check` when a scene has settled. `story_pipeline_targets._evaluate_shot_continuity` sets `waits_for` on the previous scene's target and adds a warning for a look difference. API: `SceneContinuityOut.previous_scene_id` and `look_mismatches`; `SceneDefinitionIn` and `Out` `continues_previous`. Frontend: `ShotDefinitionsPanel` (cut row, note, look differences), `SceneDefinitionView`, `SceneDefinitionEditor` (checkbox).
- **Waiting.** A scene that follows another is checked only when the last shot of the scene before is defined and current and no check or repair runs for that scene (`_previous_reason`; `Check all` also holds it back behind a check it queued a moment ago). That scene's check, once settled (nothing left to repair), queues the next one; a repair that failed does the same. The check records the last shot's definition, so a new version of it makes the following scene read `not_checked` and it is checked again. A scene that already has a check that covers it is not affected by the previous scene being busy (`Check continuity` and the status only use the wait to start a check).
- **In a run.** The `shot_continuity` target of the following scene has `waits_for` the previous scene's target, which is the existing same-step wait, so a failed or reported previous check holds only the scenes after it that follow it. A scene run of the second scene only does not wait (the previous scene is not in the run).
- **Names for SCN-013.** `shot_continuity.PreviousCut`, `_previous_cuts`, `queue_following_check`; `shot_continuity_writer.follows_directly`.
- **Checked on a copy of the live database (read only on the live data; the copy was changed, then thrown away; no model was called, no job was run).** (1) Of 138 scenes in 49 projects none has the flag, so no state changes: for all 135 stored checks that cover their scene, the boundaries the new code builds are identical to the stored ones (`b0` included), and no scene has a previous scene or a look difference. (2) Stand-in pair (project 41, scenes 2 and 3, same place): after the flag is set on the second scene its status goes from consistent to `not_checked`; `queue_following_check` on the first queues its check once (a second call queues nothing); `b0` is `previous_scene`, its `before_state` is the previous last shot's `continuity_end`, the request holds `previous_shot`, `time` and `environment_state`, the recorded artifact is the previous last shot; with a planted mismatch the status is `mismatches` at `previous_scene` to `shot_1`, and the repair job reads and may change `shot_1` only, with its end frozen and `previous_shot` in the cut and in the built request; a new version of the previous last shot makes the check `not_checked`; a planted different look gives a look difference (`default` against `night_jacket`) and the pipeline warning; in `plan_step` the second scene waits while the first is pending. (3) Stand-ins for `follows_directly` (no flag, first scene, other place, inner place both ways, graphic edge on either side), `editable_and_frozen` and `shots_of_boundary` for `previous_scene`, a user-written first shot, and `look_mismatches` (heard-only characters, no resolution).
- **Not done.** The live run (a real check and repair on a test story with two scenes that follow directly, and the new `continues_previous` flag written by the model) needs a rebuild that restarts running jobs, Qwen3.8 time and the owner's go-ahead naming project and scenes (S-11). Until then the phase is not Completed.
- **Risks.** A wrong `continues_previous` of true makes the first shot adapt to the previous last shot (the owner can untick it in the editor). Redefining the previous scene's last shot checks the following scene again (one more model call per pair). The model may be conservative or loose about the flag: it decides the rule, code only adds the place and graphic-shot conditions. The previous scene's definition (its time and place state) is not recorded on the check, so changing only that does not make the check out of date.

### SCN-013 — Final assembly

**Status:** In Progress (code, docs and checks on a database copy done; the live run and the listening check wait for the owner)

**Objective.** Once every scene is done, one pass places the music for the whole story and renders the full video, with no join you can hear at scene cuts.

**Current state.** The automatic run already ends with `music_placement` and `render`. **Not checked yet:** what the render does to the shots' own sound at a scene cut.

**Scope.**

- With lanes, the run starts the final placement and the full render when the last scene is done.
- Read what the render does at scene cuts, and **Planning decides** whether a short crossfade of the shots' own sound is needed there.
- The render panel shows which scenes changed since their scene renders.

**Out of scope.** Joining scene files (S-8).

**Dependencies.** SCN-010 and SCN-011.

**Expected outcome.** The full video is made automatically at the end of a run, and matches the scene renders.

**Verification criteria.**

- On a test story, the run ends with a full render, and 3 spot frames match the scene renders.
- Scene cuts have no click and no jump in loudness (listened to by the owner).
- Standard checks.

**Completion checklist.**

- [x] Final pass in the run
- [x] Scene cuts in the render
- [x] Changed-scene list
- [x] Standard checks (ruff check and format, ESLint and `tsc -b` pass; `schema.d.ts` regenerated from the code's own OpenAPI, additions only)
- [ ] Live run on a test story and the owner's listening check (waiting for the owner's go-ahead, see the notes)

**Completion notes.**

- **No migration, no new job type, no new setting, no new table.** New JSON only: the optional shot keys `sound_fade_in_s` and `sound_fade_out_s` and the constant `scene_cut_fade_s` in the frozen timeline (`TIMELINE_VERSION` stays 5). `DATABASE_STRUCTURE.md` has the update line and the shapes.
- **What was already true.** `music_placement` and `render` are story-wide steps that start in the pass where `shot_generation` and `graphics` are complete for every scene (they did not need a change to start "when the last scene is done"). What was missing was what happens to the scene renders at that moment.
- **Decisions made in planning (owner's answers, 2026-11-05).** (1) **Scene renders after the final placement are kept** in a run of the whole story: a scene render whose only reasons are "The final music placement was made since this video was made." or "Music has been placed since this video was made." counts as done, so the run no longer depends on timing (before this, it made every scene render again only if the `scene_render` step was still open when the placement became current). The scene render list still shows it out of date, and "Render scene" makes it with the final music. A scene run (SCN-004) still renders the scene again. (2) **Scene cuts get longer fades, not an overlap.** What the render did at a scene cut: the same as at any cut (each shot's own sound has a 20 ms fade at both ends, shots are joined end to end, one limiter and one two-pass loudnorm for the whole mix; narration and music are continuous layers). Now the first shot of each scene fades its own sound in, and its last shot fades it out, over `SCENE_CUT_FADE_S` = 0.15 s (a starting value, not tuned by ear), shortened to the gap to the nearest line of dialogue in that shot and never under 20 ms. Only a shot that plays its clip's own sound gets it (no graphic, placeholder or presenter shot, and the clip has sound). A scene render uses the same builder for one scene, so its edges are the full render's edges.
- **Names.** `story_renders.MUSIC_PLACED_SINCE`, `scene_renders.FINAL_MUSIC_SINCE`, `SceneRenderEntry.final_music_only` (read in `story_pipeline_targets._evaluate_scene_render`). `story_render_plan.SCENE_CUT_FADE_S` and `scene_edge_fades(shots, dialogue_spans)` (called in `_build` once every dialogue span is known); `render_commands.ClipAudio.fade_in_s` and `fade_out_s` (replacing `fade_s`); `render_story.Shot.fade_in_s` and `fade_out_s` (`_parse_fade`: a value that is there must be a positive number, else "Render again"). `scene_renders.SceneChange`, `compare_scene` (pure) and `changed_scenes(session, project_id, full_timeline)`; API `StoryRendersOut.changed_scenes` (`SceneChangeOut`); frontend `ChangedScenes` in `StoryRenderPanel`.
- **Changed-scene list.** Compares the newest full render's frozen timeline with the newest scene render's of each scene: the plan (`plan_id`), per shot the take, graphic, placeholder, voice and length, and the narration's `audio_id`s. It does not compare music, captions, callouts or the mix. A scene with no scene render is one line "No scene render: scene …". It reads only the newest scene render row of each scene, and nothing is stored.
- **Checked on a copy of the live database (taken with SQLite's read-only backup; the live data was only read; no job was run, nothing was written to the media).** (1) Of the 21 stored timelines, 12 are version 5 and parse as before with no fade keys (the other 9 are older versions and were refused before the phase as well, with "Render again"); the filter graph of a clip with the default fades is the same as before, longer fades are applied, and are capped at half of the sound. A fade key parses, and a negative one is refused. (2) `scene_edge_fades` on the 20 stored full timelines: only the first and the last ordinary shot of each scene get a key (135 keys), at 0.15 s, no other key of any shot changes; with stand-in dialogue spans the fade shortens to the gap, is never under 0.02 s, and graphic, placeholder, presenter and silent shots get none. `music_placement._timeline_hash` reads explicit shot fields only, so final placements stay current. (3) `changed_scenes` and `GET .../story-renders` on the copy: project 53 (2 renders, no scene renders) lists its 9 scenes as having no scene render; project 48's one real scene render, used as a stand-in full render, gives no change when equal and, with another take and plan, the reasons "planned again" and "uses take 2 (its scene render showed take 1)"; stand-ins for a placeholder, a missing shot and a speech made again. (4) `_evaluate_scene_render` with stand-in states: in a full run a scene render with only the final-music reasons is done, one with another reason too is made again, one current is done, one missing is waiting; in a scene run the first is still made again.
- **Known effects.** Renders made before the phase have no scene-edge fades and stay current; render again to get them. In a run of the whole story, scene renders made before the final placement keep their provisional music (or no music); only the full video has the final music, and "Render scene" remakes one. The fades are made by the same builder for a scene render and the full render (not yet compared on a real render).
- **Not done.** The live checks of the Verification criteria need a rebuild (restarts running jobs), a run on a test story and the owner's go-ahead naming the project (S-11): that the run ends with a full render, that 3 spot frames of the full video match the scene renders, and the owner's listening check at the scene cuts (clicks and jumps in loudness; the cut times can be listed from the full render's timeline: the `start_ms` of each scene's first shot). Until then the phase is not Completed.
- **Risks.** Between two scenes that follow directly (SCN-012), a 0.15 s fade out then in may be heard as a short dip of the ambience; the owner's listening decides whether such pairs should keep 20 ms (a scene render would then need to know its neighbour). The 0.15 s is a starting value. Music is not part of the changed-scene list, so a scene whose only difference is its music is not listed.

### SCN-014 — Owner live check on a new story (manual)

**Status:** Not Started

**Objective.** The owner confirms that the five problems are gone and that scene-by-scene work behaves as promised.

**How:**

1. Choose a new story with a group dinner or meeting, an in-car scene, a phone call and quick two-person exchanges.
2. Start a full run. Note when scene 1 can be watched, and when each later scene arrives.
3. For each problem of §1, watch the scenes that have it and rate it as fixed, better or not fixed.
4. Regenerate one scene with a note, render it, and check the full render afterwards.
5. Then fix project 48 scene by scene, as the owner chooses.

**Dependencies.** All other phases, or the ones the owner wants checked.

**Result (owner fills in):** …

---

## 7. Progress tracking

The rules of `Implementation_phases.md` §6 apply. Update a phase's **Status** line and its row in §5 together, tick checklist items as they are done, write the **Completion notes** before marking a phase Completed, and add a row to Appendix B. Never renumber a phase. A dropped phase keeps its section with the status "Dropped: reason".

---

## 8. Open questions and risks

| # | Question or risk | Where it is settled |
|---|------------------|---------------------|
| SQ-1 | **What Parakeet returns for babble.** If nothing, the silent-shot check needs another signal. | SCN-009 (owner check first) |
| SQ-2 | **Server priority is new** (0.23.0, released 2026-11-03) and strict with no ageing. Too much level 1 work would hold everything else. | SCN-002 |
| SQ-3 | **Video lab jobs on LTX, Wan-Animate, RVC or TBDub** may get 429 while a more urgent story job waits for GPUs, so they can be slow to start during a story run. | SCN-002 (observe), owner |
| SQ-4 | **Step adapters may assume a step is complete for every scene.** Lanes need each one checked. | SCN-010 (settled: checked; only `environment_views` and `scene_render` changed) |
| SQ-5 | **Environment views wait for every scene of their environment.** A place used in many scenes holds the lanes until they are all staged. | SCN-010 (settled: a view waits only for the scenes it is used in; a shot waits only for the views of its own scene's places) |
| SQ-6 | **Planning a scene again changes the story's timing**, so the music plan goes out of date for every scene. Scene renders have no music until it is planned again. | SCN-011 |
| SQ-7 | **The language model may still ignore a rule** (talking in silent shots, leaving people out). The code checks of SCN-005 and SCN-006 are what make the fixes reliable. | SCN-005, SCN-006 |
| SQ-8 | **The numbers come from project 48 only.** | SCN-014 |
| SQ-9 | **Long stories** remain limited by the story-wide steps that read the whole story (scene and character definitions, discovery). | Out of scope (S-9) |

**Out of scope for the whole document:** fixing any existing story by hand (S-1), long-story chunking (S-9), group keyframes (issue 5 option E), one audio per speaker (issue 4 option D), and replacing H3's sound in silent shots (issue 1 option F).

---

## Appendix A — Evidence from project 48

From read-only queries on 2026-11-03 (project 48, 35 scenes, 673 shots, 761 takes).

| What | Value |
|---|---|
| Run start | 2026-11-02 07:05 |
| Speech synthesis done (all scenes) | 09:06 |
| Shot plans done (all scenes) | 09:09 |
| Shot definitions done (803 jobs) | 13:22 |
| First clip sent | 14:01 (every scene's clips at the same minute) |
| Scenes finished on 2026-11-02 | 2 (15:27 and 19:02) |
| Scenes finished 2026-11-03 05:13 to 08:27 | 33 |
| Clip phase | about 18.5 hours, about 32 minutes per scene on average |
| Takes checked / failed | 513 / 91 (47 false failures, 26 empty transcripts, 18 real) |
| Local H3 limit / server H3 limit | 500 / 15 |

---

## Appendix B — Progress log

| Date | Phase | Event | Notes |
|------|-------|-------|-------|
| 2026-11-03 | — | Document written | From `Shot_generation_issues_analysis.md` and the owner's design discussion. |
| 2026-11-04 | SCN-001 | Completed | Fair matching, short-line rule, "speech not verifiable", retry stop, Score dialogue again. No migration. Project 48 on a database copy: 57 of 91 failed checks pass. |
| 2026-11-04 | SCN-002 | Code done, live checks pending | Priority sent in every GPU request that honours it, push/stop scene (migration 0084), Activity shows level and queue state. Ruff, ESLint and `tsc` pass. Not yet run on the server: needs a rebuild (restarts running jobs) and GPU time. |
| 2026-11-04 | SCN-003 | Code done, live run pending | Scene render: own table `scene_render` and job `render_scene` (migration 0085), placeholders, scene window on the shared timeline builder, Render scene button and list. Ruff, ESLint and `tsc` pass. Migration up/down/up and real scene renders (one with a placeholder) on a copy of the live database; the full render timeline is identical to before. Not yet run on the server: needs a rebuild (restarts running jobs). |
| 2026-11-04 | SCN-004 | Code done, live run pending | Scene scope in `RunOptions` (scenes, remake from), `scene_render` step, scene-aware consent and 409, Run this scene button, scene picker in the start panel, board shows the scope. No migration. Ruff, ESLint and `tsc` pass. Dry runs on a copy of the live database (full run unchanged; scene, out-of-date, remake and consent cases). Not yet run on the server: needs a rebuild (restarts running jobs) and GPU time, with the owner's go-ahead naming project and scene. |
| 2026-11-04 | SCN-005 | Code done, live checks pending | Voice-free rules in the planner, definer and prompt compiler; `_check_voices` (talking words in silent shots, voices in every soundscape, also on owner edits); code-written speaking-roles sentence for visible, unseen-only, mixed and exchange shots, and the end-of-speech sentence. No migration. Ruff passes. Re-checked all 673 stored prompts of project 48 on a read-only copy of the live database (31 of 429 dialogue and 90 of 244 silent prompts refused). Not yet run on the server: needs a rebuild and the owner's go-ahead naming project and scenes. |
| 2026-11-04 | SCN-006 | Code done, live checks pending | `presence` (arrivals and leavings) in the scene staging, shot staging and planner; group-shot rule and `_check_presence` on model answers (define and cut repair); code-written head count in every reference prompt that shows people; "Comes and goes" in the staging view. No migration; shots of stagings made before the phase keep their hash. Ruff, ESLint and `tsc` pass. Checked offline on a read-only copy of the live database (10 of 55 group-size definitions of project 48 list fewer than the placed characters; stand-ins and head-count prints). Not yet run on the server: needs a rebuild and the owner's go-ahead naming project and scene. |
| 2026-11-04 | SCN-007 | Code done, live checks pending | `inner_places` in the scene definition (up to 3, stored only when set), discovery rule for vehicles and enclosed spaces, `place` per planned shot (the planner names it), light staging (VIEWS from the inner place, no zone staging), the inner place's pictures in the reference catalog, enclosed-space prompt rule, `inputs.inner_place` staleness, story workspace changes. No migration. Checked offline on a read-only copy of the live database (all 147 stage states identical to before; stand-ins for definition, plan, shot fields, definer checks and catalog). Ruff, ESLint and `tsc` pass. Not yet run on the server: needs a rebuild and the owner's go-ahead naming project and scene. |
| 2026-11-04 | SCN-008 | Code done, live checks pending | Planner rule asks for rapid exchanges on runs of short lines (2.0 s per line, 8.0 s per run); `merge_exchanges` merges such runs on model answers only (not manual saves, cut plans, explainers or jobs with no staging), with a re-check that falls back to the model's plan. No migration, no API or frontend change. Ruff passes. Merged the 35 stored plans of project 48 on a read-only copy of the live database: 71 exchanges, 673 to 578 shots, lines in exchanges 38 to 204 of 456, no blocking timeline problem after fitting. Not yet run on the server: needs a rebuild, a live replan and the owner's go-ahead naming project and scene; PHASE-043's V6b is still open. |
| 2026-11-05 | SCN-009 | Code done, live checks pending | Silent shots are transcribed and fail when words are heard (new takes; older takes get a report-only check from a click); dialogue takes compare only the words inside each line's time window and fail on extra speech (not filler sounds, not the line's own words; whole-clip fallback for late lines). `dialogue_check` version 3, `inputs.silent_check`, `POST .../shot-takes/check-silent-speech`, badges and buttons. No migration. Ruff, ESLint and `tsc` pass. Judged all 745 stored checks of project 48 again on a read-only copy: no pass turns into a fail and no fail into a pass; stand-ins for the silent, retry and report rules. Not yet run on the server: needs a rebuild, the owner's Parakeet babble check (SQ-1) and the owner's go-ahead naming project and scene. |
| 2026-11-05 | SCN-010 | Code done, live run pending | Step kinds and `Open` sets in the run: a scene's step starts as soon as its own scene's upstream is done; a failed target holds only its scene; `scenes`, `staging`, `shot_plans` and `shots` reviews are held per scene (own endpoint, answers in `job.input.scene_answers`); `scene_render` is one target per scene in a full run; run view lists the scenes. No migration. Ruff, ESLint and `tsc` pass. Plans on a copy of the live database: full runs unchanged apart from the lanes and `scene_render`, scene runs identical, per-scene review and rejection tried. Not yet run on the server: needs a rebuild and the owner's go-ahead naming project and scene. |
| 2026-11-05 | SCN-011 | Code done, live run pending | Provisional music placement for scene renders, worked out when a scene render starts (not stored; no migration, no model call): the story's timing with placeholders for missing clips, the final placement preferred when current, `music.provisional` in the scene timeline, out-of-date and no-music reasons, API and frontend fields. Ruff, ESLint and `tsc` pass. On a copy of the live database: provisional equals the final placement when every clip exists, differs only by a hit that moved onto a removed clip's sound, and the full render timelines and final placement inputs are byte-identical to before. Not yet run on the server: needs a rebuild and the owner's go-ahead naming project and scene. |
| 2026-11-05 | SCN-012 | Code done, live run pending | Scene boundary check folded into the following scene's own continuity check: `continues_previous` flag in the scene definition (model writes it, code adds same place and no graphic edge shot), `b0` as `previous_scene` against the previous scene's last shot, repair of the first shot only, the previous last shot recorded on the check, the following scene queued when the previous one has settled and waiting for it in a run, look differences reported by code (scene page and warning). No migration. Ruff, ESLint and `tsc` pass. On a copy of the live database: stored checks and boundaries unchanged for all 135 covering checks (no stored flag), stand-in pair checked end to end up to the built repair request. Not yet run on the server: needs a rebuild and the owner's go-ahead naming project and scenes. |
| 2026-11-05 | SCN-013 | Code done, live run pending | A full run keeps a scene render that is out of date only because the final music was placed since (no re-render of every scene, no timing dependence); the first and last shot of each scene fade the clip's own sound over 0.15 s at most (clear of dialogue, `sound_fade_in_s` and `sound_fade_out_s` in the frozen timeline, older timelines render as before); the render panel lists the scenes that differ from their newest scene render (`changed_scenes`). No migration. Ruff, ESLint and `tsc` pass. On a copy of the live database: 12 stored version 5 timelines parse as before, the fade keys land only on the 135 first and last ordinary shots of the 20 stored full timelines, the placement fingerprint ignores them, `GET .../story-renders` answers for projects with and without scene renders, run evaluation with stand-ins for full and scene runs. Not yet run on the server: needs a rebuild, the owner's go-ahead naming project, a full run on a test story and the owner's listening check at the scene cuts. |
