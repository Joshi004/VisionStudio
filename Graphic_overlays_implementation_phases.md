# Vision Studio — Graphic Overlay Phases

A **graphic overlay** is a graphic the owner asked for, laid over the shots that are already there, while its words are spoken. When the owner marks *"The first ranked it the smartest open model in the world. The second ranked it fourth out of four,"* as a graphic, the video shows a full-screen graphic over those words, and the presenter and B-roll clips under it stay exactly as they were made. Nothing is planned again and no video clip is made again.

Today a graphic suggestion is a hint to the shot planner: it changes the shot plan, so every shot of the scene is made again (§2). This document turns suggestions into overlays placed by code, makes evidence added later a card instead of a new plan, and shows a graphic and evidence that land on the same words side by side.

- The conventions of `Implementation_phases.md` (§3.3 to §3.5, §6), `Evidence_layer_implementation_phases.md` and `Sound_bite_implementation_phases.md` apply unchanged. Table and column details go in `DATABASE_STRUCTURE.md`. The newest migration when this was written was `0101`.
- Written 2026-11-26, from a design discussion with the owner after project 94 (§2, "What happened in project 94").

---

## How to use this document

Use the Opus → Sonnet workflow of `Evidence_layer_implementation_phases.md` ("How to use this document"), with this document's name and the prefix **OVL-**. Every phase has the same fields: Objective, Current state, Scope, Out of scope, Dependencies, Expected outcome, Verification criteria, Completion checklist and Completion notes. Items marked **Planning decides** are left open on purpose and must be settled in the plan.

**Owner phases** (OVL-008) are done by the owner. The agent prepares the steps, runs nothing destructive and no paid call (no H3 clip, no model call on a real project) without the owner's explicit go-ahead, and records the results.

### Why some phases can run in parallel

- **One migration.** OVL-001 creates everything overlays store (§4.7). Later phases add none, so phases that run at the same time never fight over Alembic revision numbers. The one exception is OVL-007, which added migration `0103` after the owner chose to store a split stretch's evidence clips under their own purpose (see its completion notes); it ran alone, so nothing fought over a number.
- **The placement is pure.** OVL-003 needs only the timeline and the take's words, so it can be built beside OVL-002.
- **Evidence is its own track.** OVL-006 touches the evidence rounds and the shot plan's evidence check, not the graphics code.

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
- [Appendix A — Progress log](#appendix-a--progress-log)

---

## 1. Goal

For a continuous explainer with graphics on, the owner:

1. marks words of the saved story as a graphic, at any time, before or after the video clips are made;
2. gets a graphic for every suggestion: no rule of the Story Bible and no choice of the planner can decline it. The only rule kept is that numbers on screen are numbers said in the script (OV-4);
3. sees the graphic full screen over whatever shot is under its words (presenter, B-roll, the planner's own graphic), with the voice running on;
4. adds evidence to a claim after the shots exist and sees it as a card, with no new shot plan;
5. where a graphic and evidence land on the same words, sees both, side by side;
6. **never pays for a new video clip** because of a suggestion or evidence added later. What runs again is the overlay's brief and graphic, and the render.

A project without suggestions renders exactly as today.

---

## 2. Current state

**What happened in project 94** (2026-11-26). Scene 1 had five shots: presenter, two B-roll shots, an evidence shot and presenter, all with finished clips. The owner added two suggestions: `g1` over the words of the two B-roll shots and `g2` over the evidence shot's words. The shot plan of scene 1 went out of date ("The graphic suggestions for this scene changed since these shots were planned.") and every shot of the scene with it, down to the render. The scene was planned again (plan version 2). The planner **declined both** suggestions, because the Story Bible says "Numbers and statistics are only ever spoken by the narrator, never rendered as on-screen graphics." Version 2 cut the scene on exactly the same words as version 1, but every description was reworded and the two B-roll shots changed type (`action` to `insert`). So four H3 clips were out of date and were made again (jobs 36190 to 36193), for no graphic at all.

Why, in the code:

- **A suggestion is an input of the shot plan.** `shot_plans._scene_suggestions` puts the marked words into the take sent to the planner (`take["suggestions"]`), and `cut_planning_writer._SUGGESTION_RULES` calls it "a wish, not an order". The plan records `inputs.graphic_suggestions_sha256`; `shot_plans._suggestion_reasons` makes the plan out of date when it changes. The plan's `content.graphic_suggestions` says what became of each (`followed`, `reason`), shown in `ShotPlansPanel.tsx`.
- **The planner reads the whole Story Bible** and ranks it above a suggestion.
- **Planning again starts from nothing.** A plain re-plan does not give the planner the previous shots (only an owner's note or an automatic re-plan after a failed check does, `user_feedback.blocks`, `replan.previous_shots`).
- **A shot is "the same" only when its skeleton hash is.** `shot_definitions._skeleton_sha256` hashes the shot's `id`, `type`, `description`, events, speech units, duration and words. The description is free text the model writes again every time, and the id is the shot's position (`f"shot_{position}"` in `cut_planning_writer`), so a re-plan nearly always changes every shot. Definition, references, generation request, prompt and clip follow.
- **Suggestion ids are positions too.** `graphic_suggestions._merge` numbers them `g1`, `g2`, ... in story order on every save, so adding one before `g1` renumbers the rest.
- **Graphics are stored per shot.** `shot_graphic_brief`, `shot_graphic` and `shot_graphic_choice` are keyed by `(project_id, scene_id, shot_id)`, and a brief is out of date when its shot's skeleton hash, its context hash, the take or its timing changed (`shot_graphic_briefs`). An attempt is current when the hash of its resolved brief (brief, theme, words timed from the clip's start, clip length; `shot_graphics.resolve_for_shot`) is the one worked out now.
- **The brief writer does not read the style rules.** `shot_graphic_brief_writer.bible_for_model` passes only the Story Bible's `title` and `tone`. Its own rule is that every number on screen is said in the shot's words or the words around it (`said_as`).

What exists and is reused:

- **Overlays in the render.** `render_commands.Overlay` (a clip, its place, and which of its frames show over which frames of a shot) is laid over a shot in stage 1 (`trim_args`). Motion callouts (CMO-005) and evidence cards (`render_story.card_overlays`, which splits a card across the cuts it crosses) use it.
- **Evidence cards** (EVD-011, `services/evidence_cards.py`): placed by code on read, over presenter and B-roll shots, from the claims shown **now** (`shot_plans._claim_times` reads `_scene_evidence`, not the plan's record), for a scene whose plan is current (`status == "planned"`). A claim that has no evidence shot gets a card, or a reason on the board when there is no room.
- **The split evidence shot** (EVD-016): an evidence clip drawn in a panel (`evidence_clip_layout.split_panel`, landscape evidence left and callout right 50/50, portrait callout 30 % on top and evidence 70 % below) so a callout can share the screen.
- **Spans callouts keep off.** `story_render_plan` collects `graphic_spans` (graphic shots, full evidence shots, cards) and `callout_render.resolve` drops a callout that starts in one, with a `callout_dropped` warning.
- **Limits.** A graphic shot lasts at least `cut_planning_writer.SHORTEST_GRAPHIC_S` (3.0 s). The motion service draws at most `shot_graphics.MAX_FRAMES` (720) frames at `graphics_lab.FPS` (24), so 30 s.

**Evidence added later is worse than a suggestion today** (written before OVL-006, which changed it: see its notes). The newest evidence round counts only while it has exactly the claims that count now (`evidence_rounds.state`, `current`). One new claim makes it not current, so `evidence_review.shown_claims` returns nothing for the whole project: every scene with evidence goes out of date ("The evidence to show in this scene changed since these shots were planned."), and shots cannot be planned until a new round is researched and reviewed (`shot_plans.EVIDENCE_FIRST_MESSAGE`).

What does not exist: a graphic tied to words instead of a shot; a graphic placed by code; a way to add evidence without a new shot plan; a split of a graphic and evidence.

---

## 3. Decisions

| # | Decision |
|---|----------|
| OV-1 | **Every graphic suggestion is an overlay.** Suggestions never go to the shot planner again, before or after clips exist. The planner still plans its own graphic shots, as today. |
| OV-2 | **A suggestion overrides the rules.** Code places it, so no Story Bible rule and no planner choice can decline it. |
| OV-3 | **Full screen, over any shot.** An overlay covers whatever is under its words: presenter (the voice runs on), B-roll, the planner's own graphic shot, an evidence shot (then OV-7). The shots under it are not changed. |
| OV-4 | **Numbers on screen are said in the script.** The brief writer's rule stays: a graphic never shows a number that the words of the overlay or the words around it do not say. |
| OV-5 | **A sound bite wins**, as today (SB-008): its words are taken out of the suggestion. No overlay is drawn over a sound bite shot. |
| OV-6 | **Evidence added later is a card.** A claim or a piece shown after the shots were planned gets a card (EVD-011) and no new shot plan. The plan goes out of date only when something one of its evidence shots shows is no longer shown. Exception: a sound bite accepted later still changes its scene's plan, since a clip replaces words and cannot be a card (OVL-006). |
| OV-7 | **A graphic and evidence on the same words share the screen.** One split stretch covers both, from the start of the first to the end of the last, so the layout never changes in the middle of a sentence. |
| OV-8 | **No new video clip** because a suggestion was added, changed or removed, or because evidence was added. What runs again: the overlay's brief and graphic, card clips, the scene render and the video render. |
| OV-9 | **Suggestions stay where they are.** The owner marks words in the same "Suggest graphics" box; only what happens to them changes. |

---

## 4. Design

### 4.1 How it works

```text
owner marks words as a graphic                                          GraphicSuggestions.tsx
 -> project.graphic_suggestions saved (the shot plan does not change)    OVL-002
 -> on read, for each scene with a current plan: the overlays of its
    take, placed by code on the scene's timeline                          OVL-003
 -> each overlay gets a brief, then a graphic (both versions, the
    owner's choice as for graphic shots)                                  OVL-004
 -> an overlay that meets evidence is drawn split with it                 OVL-007
 -> the render lays each overlay full screen over the shots it spans      OVL-005
```

### 4.2 Where an overlay goes (`services/graphic_overlays.py`, pure)

Starting values, to tune by eye:

- **One overlay per suggestion and scene.** `graphic_suggestions.take_suggestions` already gives each suggestion's words in each scene's take; a suggestion that runs into the next scene gives one overlay in each. Words a sound bite replaces are taken out (OV-5); when what is left is not one unbroken run, each run is its own overlay. **Planning decides** whether a run shorter than two words is dropped.
- **Start and end.** It starts in the middle of the pause before its first word and ends in the middle of the pause after its last word, the way the cut planner places a cut, mapped to the scene's timeline with `TakeMap` like the shots.
- **At least `SHORTEST_GRAPHIC_S` (3.0 s).** Shorter, it runs on after its last word, up to the next overlay or the end of the scene, and then starts up to 1.0 s earlier. No room: no overlay, and a reason on the board.
- **At most 720 frames (30 s).** Longer, it is not placed and the board asks the owner to split the suggestion.
- **Two overlays never overlap.** Suggestions never do (`_merge`), but a lengthened one ends 0.15 s (`evidence_cards.GAP_S`) before the next one starts.
- **Never over a sound bite shot.** An overlay is cut short where a sound bite shot starts.
- It is worked out on read, from the plan, the timeline and the take, like cards. Nothing is stored for the placement.

### 4.3 What an overlay is, and when it is out of date

- **Key.** `{scene_id}/{first}-{last}`: the scene and the overlay's first and last word in the take, counted from 1. Never the `g` number, which is renumbered (§2). The same words in the same take keep the same key and the same graphic when other suggestions are added or removed.
- **Brief.** The same writer as a graphic shot (`shot_graphic_brief_writer`), with the overlay's words, the words around them as context, and the overlay's length in place of the shot's. A brief is out of date when the overlay's words, its context, its start or end, the take or its timing changed. **A re-plan does not make it out of date**: an overlay depends on the take and the suggestion, not on the shots.
- **Graphic.** Both engines and the owner's choice, as for a graphic shot (`shot_graphics`), resolved for the overlay's span at the output size (or the panel's size, §4.5). A new theme makes it out of date, as today.

### 4.4 Over the shots

- The overlay's video is an ordinary full-frame clip (H.264, `yuv420p`, no alpha needed), laid at `(0, 0)` over every shot it spans with the `Overlay` path, split across cuts like a card.
- **Sound.** The shots' own sound plays as it would without the overlay (ducked under the voice); the overlay has none. **Planning decides** whether B-roll sound is lowered further under an overlay.
- **Captions** are drawn as over a graphic shot today.
- **Callouts** keep off an overlay: its span is added to `graphic_spans`, so a callout that starts in it is dropped with the usual warning.
- **The planner's own graphic shot under an overlay** is still made (one brief and a local render), and hidden. **Planning decides** whether to skip making it.

### 4.5 When a graphic and evidence meet (OVL-007)

- An overlay **meets** evidence when its span overlaps a full-screen evidence shot or a card.
- The **split stretch** runs from the start of the first to the end of the last of them. Both sides are drawn for the whole stretch, so the overlay's span grows to the stretch (its beats stay timed to its words) and the evidence side holds its clip or card for the stretch.
- **Layout.** Landscape: evidence left, graphic right, 50/50 (evidence on the left as in EVD-016). Portrait: graphic on top, evidence below. **Planning decides** the portrait proportions (default 50/50).
- The graphic is drawn at the panel's size for its whole length, so an overlay that is split is resolved and hashed at that size, and drawn again when it stops being split. The evidence side uses the split mode of the evidence clip (EVD-016) with the graphic's panel in place of the callout's.
- A callout that starts in a split stretch is dropped (a split stretch has no third panel).

### 4.6 What runs again

| The owner | Runs again | Does not run again |
|-----------|------------|--------------------|
| adds or changes a suggestion | its overlay's brief (one model call) and graphic (model call and local render), the scene render, the video render | shot plan, definitions, references, generation requests, prompts, H3 clips, music cues |
| removes a suggestion | the scene render and the video render | everything else |
| shows a new claim or piece (OVL-006) | its research round, its card clip, the renders | the shot plan and everything under it |

Music placement hashes shot frames and voice times (`music_placement._timeline_hash`), which overlays do not change, so it should stay current; OVL-005 checks it.

### 4.7 What the one migration creates (OVL-001)

Where overlay briefs, attempts and choices are stored. **Planning decides** between:

1. **A `target` column** (`shot` or `overlay`, default `shot`) on `shot_graphic_brief`, `shot_graphic` and `shot_graphic_choice`, with the overlay key of §4.3 in `shot_id` and `shot_plan_id` left NULL. The jobs and the engines are reused as they are. The default.
2. **New tables** for overlays with the same shape.

---

## 5. Phase overview

| Id | Title | Kind | Hard dependencies | Status |
|----|-------|------|-------------------|--------|
| OVL-001 | Storage for overlay graphics | Code | — | Completed |
| OVL-002 | Suggestions leave the shot planner | Code | — | Completed |
| OVL-003 | Placing the overlays | Code | — | Completed |
| OVL-004 | Briefs and graphics for overlays | Code | OVL-001, OVL-003 | Completed |
| OVL-005 | Overlays in the render | Code | OVL-002, OVL-004 | Completed |
| OVL-006 | Evidence added later becomes a card | Code | — | Completed |
| OVL-007 | Split screen for a graphic and evidence | Code | OVL-005, OVL-006 | Completed |
| OVL-008 | Project 94 end to end | Owner | OVL-005, OVL-007 | Not Started |
| OVL-009 | Keep unchanged shots when a scene is planned again | Code, later | — | Deferred |

**Tracks that can run at the same time:**

- **Graphics:** OVL-001 and OVL-003 → OVL-004 → OVL-005.
- **Planner:** OVL-002 (done). It had to be done before OVL-005 is used on a real project.
- **Evidence:** OVL-006 (done), then OVL-007 (done).

**Progress snapshot:** 7 completed (OVL-001, OVL-002, OVL-003, OVL-004, OVL-005, OVL-006, OVL-007).

---

## 6. Phases

### OVL-001 — Storage for overlay graphics

**Status:** Completed (2026-11-26; the owner still has to rebuild the real app so `0102` is applied there)

**Objective.** Store, in one migration, everything overlay graphics need (§4.7).

**Current state.** `shot_graphic_brief`, `shot_graphic` and `shot_graphic_choice` are keyed by `(project_id, scene_id, shot_id)` (revision `0080`); `shot_plan_id` is nullable.

**Scope.**
- Migration `0102` with the choice of §4.7.
- Models, and `DATABASE_STRUCTURE.md`.
- Every existing reader of the three tables reads only rows for shots (so nothing changes for graphic shots).
- **Planning decides:** option 1 or 2 of §4.7; the column names.

**Out of scope.** Writing overlay rows (OVL-004).

**Dependencies.** None.

**Expected outcome.** The data can hold overlay graphics; nothing visible changes.

**Verification criteria.**
- Upgrade, downgrade and upgrade again on a throwaway `DATA_DIR`.
- The graphics state of a real snapshot is the same before and after.
- Standard checks.

**Completion checklist.**
- [x] Migration and models
- [x] Readers limited to shot rows
- [x] `DATABASE_STRUCTURE.md`
- [x] Standard checks
- [ ] Owner: real app rebuilt so `0102` is applied there

**Completion notes.** Done 2026-11-26. Option 1 of §4.7 (a `target` column).

- **Migration** `backend/app/db/migrations/versions/0102_graphic_overlay_storage.py`. `shot_graphic_brief`, `shot_graphic` and `shot_graphic_choice` each gain `target` (TEXT, NOT NULL, `server_default 'shot'`) with the CHECK `ck_<table>_target_valid` (`target IN ('shot', 'overlay')`). The UNIQUE of the brief is now `uq_shot_graphic_brief_project_id (project_id, target, scene_id, shot_id, version)` and that of the choice `uq_shot_graphic_choice_project_id (project_id, target, scene_id, shot_id)`, with the same names as before. `shot_graphic`'s UNIQUE `(brief_id, engine, attempt)` is unchanged. The downgrade deletes overlay rows (choices, graphics, briefs) first.
- **Overlay row layout** (for OVL-004): `target = 'overlay'`, `scene_id` the scene, `shot_id = '{first}-{last}'` (first and last word in the take, counted from 1), `shot_plan_id` NULL. `shot_graphic_briefs.shot_key(scene_id, shot_id)` then gives the §4.3 key `{scene_id}/{first}-{last}`.
- **Models** (`app/db/models.py`): `ShotGraphicBrief`, `ShotGraphic`, `ShotGraphicChoice` have `target`, the CHECK and the new UNIQUEs.
- **Constants**: `shot_graphic_briefs.TARGET_SHOT` (`"shot"`) and `TARGET_OVERLAY` (`"overlay"`). `shot_graphics` uses them through `shot_graphic_briefs`.
- **Readers limited to shot rows** (they filter on `target == TARGET_SHOT`, and new rows set it explicitly): `shot_graphic_briefs.newest_row`, `save_version`, `_newest_rows`; `shot_graphics._rows_by_shot`, `_choices`, `set_choice` (select and new row), `_new_row`. `_next_attempt`, the jobs, the APIs, `staleness` and `story_pipeline_targets` needed no change (by `brief_id`, by a row id, or through these two services). **OVL-004 must add overlay readers beside these and must not loosen them.**
- **Checked** (2026-11-26, a throwaway `DATA_DIR`, removed afterwards). Upgrade to `0101`, three seeded rows (one brief, attempt and choice), upgrade to `0102`: the rows kept their data and read `shot`, the schema shows the column, CHECKs and UNIQUEs, `PRAGMA foreign_key_check` and `integrity_check` are clean. An overlay row with the same scene and `shot_id` as a shot row is accepted; a duplicate of the same target is refused; `target = 'bad'` is refused. Downgrade with overlay rows present deleted them and kept the shot rows with the old UNIQUEs; upgrade again gave `0102`. `alembic check` shows only the older FLOAT/REAL differences, none for these tables. `ruff check`, `ruff format --check`, `eslint` and `tsc -b` pass.
- **Not checked.** (1) The identity check on a snapshot of the real database (asked of the owner; not run): dump `shot_graphic_briefs.state` and `shot_graphics.state` as sorted JSON for every graphics project with the code at the previous commit on a copy at `0101`, then with this code on a copy at `0102`, and diff the two. By construction the filters match every existing row. (2) The services were not run against a database with overlay rows (none are written until OVL-004). (3) No `gen:api` was needed: no API change.

### OVL-002 — Suggestions leave the shot planner

**Status:** Completed (2026-11-27; the owner still has to rebuild the real app so the new code runs there)

**Objective.** A suggestion no longer changes, or makes out of date, any shot plan (OV-1).

**Current state.** §2, first bullet: `_scene_suggestions`, `take["suggestions"]`, `_SUGGESTION_RULES`, `_SUGGESTIONS_ANSWER_FORM`, `declined_suggestions`, `suggestion_results`, `inputs.graphic_suggestions_sha256`, `_suggestion_reasons`, `content.graphic_suggestions`.

**Scope.**
- The planner's request has no suggestions: the suggestion rules, answer form and `declined_suggestions` are removed, and the take has no `suggestions`. A scene without suggestions gets a byte-identical request.
- `_suggestion_reasons` is removed, so no plan is out of date because of suggestions, including plans made before this phase (project 94's scene 1).
- `content.graphic_suggestions` of old plans is no longer shown in `ShotPlansPanel.tsx`; old rows are not changed.
- `GraphicSuggestions.tsx` says what a suggestion now does: "The graphic is drawn over the shots under these words. The shots are not planned again."
- **Planning decides:** whether `SUGGESTION_ON_SOUNDBITE_TEXT` moves to OVL-003's reasons. Decided: it moves to `graphic_suggestions.SOUNDBITE_REASON`, with the placing code beside it.

**Out of scope.** Drawing the overlays (OVL-003 to OVL-005). Until OVL-005, suggestions have no effect on the video.

**Dependencies.** None.

**Expected outcome.** Adding, changing or removing a suggestion changes no plan, no definition and no clip.

**Verification criteria.**
- The planner's request for a scene without suggestions is byte-identical before and after (a real snapshot).
- On a snapshot of project 94: scene 1's plan is current; adding a suggestion leaves every step of the board as it was.
- Standard checks.

**Completion checklist.**
- [x] Planner request without suggestions
- [x] No plan out of date because of suggestions
- [x] Panels and texts
- [x] Identity check on a snapshot
- [x] Standard checks
- [ ] Owner: real app rebuilt so the new code runs there

**Completion notes.** Done 2026-11-27. No migration, no change to `DATABASE_STRUCTURE.md` (the removed JSON keys were never documented there).

- **`cut_planning_writer.py`**: removed `SUGGESTION_ON_SOUNDBITE_TEXT`, `SUGGESTIONS_KEY`, `_SUGGESTIONS_ANSWER_FORM`, `_SUGGESTION_RULES`, `_SUGGESTIONS_BODY`, `suggestions_of` and `suggestion_results`. The `suggestions` parameter is gone from `_answer_form`, `_body`, `_evidence_body`, `_soundbite_body` and `instructions` (now `instructions(graphics, evidence, soundbites)`). `take_block` no longer writes `graphic_suggestion` on a word, and `check_answer` no longer writes `content.graphic_suggestions`. The slot of the text that held the suggestion rules is now `extra_rules` (the evidence rules, then the sound bite rules), so the text is unchanged.
- **`shot_plans.py`**: removed `_scene_suggestions`, `take["suggestions"]`, `inputs.graphic_suggestions_sha256` and `_suggestion_reasons` (and its call in `_out_of_date_reasons`). `_Loaded.suggestions` stays: OVL-003 reads it.
- **`graphic_suggestions.py`**: new pure `scene_suggestions(story, scene_item, take_words, entries, soundbite_words)` (the body of the old `_scene_suggestions`, with the sound bite's word positions passed in) and `SOUNDBITE_REASON`. OVL-003 calls them with `_soundbite_words` from `shot_plans`. The module docstring now says a suggestion is drawn over the shots, not planned.
- **`jobs/plan_shots.py`**: `_is_suggestions` removed. A job queued earlier that still carries `take.suggestions` still reads, because nothing looks at the key.
- **API**: `GraphicSuggestionResultOut` and `ShotPlanContentOut.graphic_suggestions` removed; `schema.d.ts` regenerated (21 lines removed, nothing else changed). Old plan rows are untouched: their `content.graphic_suggestions` and `inputs.graphic_suggestions_sha256` are ignored when read.
- **Frontend**: `ShotPlansPanel.tsx` no longer shows "Graphics you suggested"; `GraphicSuggestions.tsx` says "The graphic is drawn over the shots under these words. The shots are not planned again."
- **Checked** (2026-11-27, on a copy of the real database taken with SQLite's backup API from the running container and upgraded to `0102`; no model call, no job queued; the live data was only read; the copies were removed afterwards). 18 projects with graphics on, 41 scenes whose request could be built (11 with suggestions): (1) the 8 system messages of `instructions` for graphics, evidence and sound bites on or off are identical before and after; (2) the planner's request of the 30 scenes without suggestions is byte-identical before and after (SHA-256 of the whole request, fixed model name); (3) for the 11 scenes with suggestions, the request after equals the request before with `take["suggestions"]` removed, and so differs from before only by the removed parts; (4) the plan's recorded inputs are the old ones without `graphic_suggestions_sha256` in all 41; (5) the only change in any scene's plan status is that the reason "The graphic suggestions for this scene changed since these shots were planned." is gone (project 82, four scenes, which are out of date for other reasons too); (6) project 94: with the old code, adding a suggestion made scene `opening_puzzle` out of date and changed the board's steps; with the new code the board's steps and every scene's plan are identical before and after adding one (only the board's `revision` counter, which counts database activity, differs). `ruff check`, `ruff format --check`, `eslint` and `tsc -b` pass.
- **Not checked.** (1) A real planning call (none was made: it is paid). (2) The project 94 snapshot did not have scene 1 as described in §2: its plans in the copy were already current, so the check above uses `opening_puzzle`. (3) The browser panels were not opened, only linted and type-checked. (4) Until OVL-005, suggestions have no effect on the video, as the phase says.

### OVL-003 — Placing the overlays

**Status:** Completed (2026-11-27; the owner still has to rebuild the real app so the new code runs there)

**Objective.** Code places every overlay on its scene's timeline (§4.2) and gives its key (§4.3).

**Current state.** `evidence_cards.place_cards` places cards on read; `shot_plans.SceneEntry` carries `cards`, `unplaced_cards`, `source_lines` and `splits`.

**Scope.**
- `services/graphic_overlays.py` (pure): `place_overlays(suggestions, slots, total_s)` with the rules of §4.2; `Overlay` (key, scene, words, start, end, the shots under it) and `Unplaced` (code and sentence).
- `SceneEntry.overlays` and `unplaced_overlays`, worked out on read for a scene whose plan is current, as cards are.
- Board notes for an overlay with no room or too long (`story_pipeline_targets`).
- **Planning decides:** the reason codes; whether a run under two words is dropped.

**Out of scope.** Briefs and graphics (OVL-004); evidence (OVL-006, OVL-007).

**Dependencies.** None.

**Expected outcome.** The shot plans state lists each scene's overlays with their times.

**Verification criteria.**
- `place_overlays` on sample cases: a short suggestion lengthened, one with no room, one over 30 s, one across a cut, one across two scenes, one cut by a sound bite, two close together.
- Project 94's two suggestions placed where their words are spoken (times checked against the take).
- Standard checks.

**Completion checklist.**
- [x] `graphic_overlays.py`
- [x] `SceneEntry` fields and API
- [x] Board notes
- [x] Sample cases and project 94 placement
- [x] Standard checks
- [ ] Owner: real app rebuilt so the new code runs there

**Completion notes.** Done 2026-11-27. No migration, no change to `DATABASE_STRUCTURE.md` (nothing is stored), no new job or setting.

- **`services/graphic_overlays.py`** (pure; imports only `evidence_cards` and `graphic_suggestions`). Constants `MIN_S` (3.0), `MAX_FRAMES` (720), `FPS` (24), `MAX_LEAD_S` (1.0), `GAP_S` (`evidence_cards.GAP_S`), copied with a comment naming their source so the module does not import `shot_graphics`. Values: `Wanted` (a run to place, with its natural start and end), `Overlay` (`scene_id`, `suggestion_id`, `text`, `first_word`, `last_word`, `start_s`, `end_s`, `shot_ids`; `overlay_id` = `"{first}-{last}"`, `key` = `"{scene_id}/{first}-{last}"`, `length_s`), `Unplaced` (`scene_id`, `suggestion_id`, `text`, `key` or None, `code`, `message`) and `Placement`. `runs(words, soundbite_words)` splits a suggestion's kept take positions (from 0) only where a sound bite word lies between neighbours; a position missing from the list is bridged. `place_overlays(wanted, slots, total_s)` takes the `evidence_cards.Slot` list of the scene's shots.
- **Reason codes** (`UNPLACED_TEXT`): `no_room`, `too_long` (more than 720 frames, measured on the natural length before lengthening), `soundbite` (every word is a sound bite; the text is `graphic_suggestions.SOUNDBITE_REASON`) and `one_word`.
- **Planning decided.** A run of one word is dropped (`one_word`) only when a sound bite cut the suggestion down; a suggestion the owner marked as one word is kept and lengthened. To tell them apart `graphic_suggestions.scene_suggestions` now sets `"trimmed": True` on a suggestion that lost some words (and kept some) to a sound bite. An overlay that starts on the take's first word starts at 0.0 (the first shot owns the lead-in), and one that ends on the take's last word ends at `timeline.total_s`; every other edge is `take_map.to_scene(cut_planning_writer.cut_time(...))`, the same as the shots. A run whose cut time is inside a sound bite's clip, or a word without a time, is skipped.
- **Placement rules as built.** Start moves to the end of a sound bite shot it starts in; end is cut where the next sound bite shot starts. A short run is lengthened up to the next run's natural start less 0.15 s, the next sound bite start less 0.15 s, or the end of the scene; then its start is pulled back by up to 1.0 s, never before the previous overlay's end plus 0.15 s or a sound bite shot's end. Under 3.0 s after that: `no_room`. `shot_ids` are the overlapped shots that are not sound bite shots.
- **`shot_plans.py`**: `SceneEntry.overlays` and `unplaced_overlays`, filled by `_graphic_overlays` beside the cards for a scene whose status is `planned`. Nothing for a project without suggestions, or a scene without a cut plan, take map or timed words.
- **API**: `ShotPlanEntryOut.overlays` (`GraphicOverlayOut`: `key`, `suggestion_id`, `text`, `first_word`, `last_word`, `start_seconds`, `end_seconds`, `shot_ids`) and `unplaced_overlays` (`UnplacedOverlayOut`: `suggestion_id`, `text`, `code`, `message`). `schema.d.ts` regenerated from the app's own OpenAPI on a throwaway `DATA_DIR` (41 lines added, nothing else). No UI uses them yet (OVL-004).
- **Board**: `story_pipeline_targets._overlay_notes` gives "`{scene}: '{text}' gets no graphic: {reason}`" for each unplaced overlay, as the warnings of the **Graphic briefs** step.
- **Checked** (2026-11-27, no model call, no job). (1) Sample cases on `place_overlays` and `runs`: a short run lengthened (4.0 to 7.0 s); no room at the end of the scene; 31 s refused as `too_long` and exactly 30 s placed; across a cut (both shots listed); across two scenes (one overlay in each, keyed by scene); cut at a sound bite shot's start; starting inside one (moved to its end); short next to a sound bite (`no_room`); two close together, both placed with at least 0.15 s between them, and the tight case where the first is `no_room`. (2) A copy of the real database (SQLite's backup API from the running container, read only, upgraded to `0102`, removed afterwards), `shot_plans.state` for all 18 graphics projects: no error, no overlay for a project without suggestions (the projects with suggestions placed 2, 5, 2 and 6 overlays in the scenes that have a current plan, none unplaced). Project 94, scene `opening_puzzle`: `g1` from 4.625 to 11.75 s over `shot_2` and `shot_3` (its words run 4.72 to 11.68 s in the take) and `g2` from 13.042 to 21.792 s over `shot_4` (words 13.04 to 21.68 s); the lead-in is 0.0 s there. (3) `ruff check`, `ruff format --check`, `eslint` and `tsc -b` pass.
- **Not checked.** (1) No real project has a sound bite and a suggestion together, so the cut-by-sound-bite path ran only in the sample cases, not through `shot_plans`. (2) No real case of `no_room`, `too_long` or `one_word` came up on the copy. (3) The board note text was not seen on the board, only built. (4) Nothing draws or stores an overlay yet, so there is no visible change until OVL-004 and OVL-005.

### OVL-004 — Briefs and graphics for overlays

**Status:** Completed (2026-11-27; the owner still has to rebuild the real app so the new code runs there)

**Objective.** Each overlay gets a brief and a graphic, made and chosen like a graphic shot's, and out of date only for its own reasons (§4.3).

**Current state.** `shot_graphic_briefs` (`_material`, `_find_shot`, `start_shot`), `shot_graphics` (`resolve_for_shot`, `start_shot`, `UsedVideo`), the pipeline steps `graphic_briefs` and `graphics`, `GraphicBriefsPanel.tsx` and `GraphicsPanel.tsx`, all per shot.

**Scope.**
- The material of an overlay: its words timed from its start, its context, its length; the brief writer's request unchanged apart from these values (OV-4 kept).
- Out-of-date rules of §4.3; a re-plan never makes an overlay out of date.
- Both engines, repairs, and the owner's choice for an overlay; resolved for the overlay's span at the output size.
- Pipeline targets `overlay:{key}` in `graphic_briefs` and `graphics`; these steps no longer wait for an out-of-date shot plan for overlays of scenes whose plan is current.
- The two panels list overlays beside graphic shots, named by their words.
- **Planning decides:** how the material builds a span for `resolve_for_shot` (a `ShotSpan`-like value or a new function).

**Out of scope.** The render (OVL-005); the panel size (OVL-007).

**Dependencies.** OVL-001, OVL-003.

**Expected outcome.** Pressing Make on an overlay gives a full-frame video timed to its words.

**Verification criteria.**
- On a throwaway app with a copy of project 94: briefs and graphics for both overlays (one model call each, with the owner's go-ahead); the numbers on screen are the numbers said.
- A re-plan of the scene leaves both current; a changed take makes them out of date.
- Graphic shots of a real snapshot are unchanged (state and hashes).
- Standard checks.

**Completion checklist.**
- [x] Material and briefs
- [x] Graphics, repairs and choice
- [x] Pipeline targets
- [x] Panels
- [x] Checks above (the paid parts as stand-ins, see below)
- [x] Standard checks
- [ ] Owner: real app rebuilt so the new code runs there

**Completion notes.** Done 2026-11-27. No migration (the overlay rows of `0102` are now written), no new job type, no new setting. `DATABASE_STRUCTURE.md` has the `inputs` shape of an overlay's brief and an update paragraph.

- **`graphic_overlays.py`**: new `clip_frames(start_s, end_s)` (frames on the 24 fps grid plus one spare frame, the count a graphic shot gets) and `SPARE_FRAMES`. `place_overlays` refuses with `too_long` when `clip_frames` is above 720, checked on the natural length and again on the rounded times, so a placed overlay can never be refused by `resolve_for_shot`. **A change from OVL-003:** an overlay of exactly 30.0 s is now `too_long` (721 frames); 29.958 s is the longest placed. The message says "about 30 seconds or more".
- **`shot_graphic_briefs.py`**: `_overlay_material` (words timed from the overlay's start on the scene's clock, by `take_map.to_take(start_s)` and `timed_words`; context; hashes), `_overlay_saved_inputs`, `_overlay_out_of_date_reasons`, `_overlay_refusal`, `OverlayEntry` (on `SceneEntry.overlays`), `start_overlay` and `overlay_job_key`. `newest_row` and `save_version` take a `target` (default `shot`), `_newest_rows` too. `_source_reasons` is the part of the out-of-date rule a shot and an overlay share (the sentences around, the take, its timing); the shot's reasons and their order are unchanged. The brief writer is given the fixed description `OVERLAY_DESCRIPTION` ("The owner asked for a graphic over these words. Show what they say.") and `shot_seconds = overlay.length_s`; nothing else of the request changed (OV-4 kept).
- **Out of date (§4.3).** An overlay's brief is out of date when its start or end, its context, the take or the take's timing changed. It records no shot plan and no skeleton hash, so a re-plan cannot change it. A moved start or end is a new brief (one model call, then the engine calls), as §4.3 says; the owner chose that over a free redraw.
- **`jobs/write_shot_graphic_brief.py`**: the task reads `target` (a job without one is for a shot) and accepts `shot_plan_id` None only for an overlay; the version is saved with that target.
- **`shot_graphics.py`**: an overlay is read with the same `ShotEntry` as a graphic shot (`target`, `overlay`, and a stand-in `shot` whose `id` is `{first}-{last}`, `spoken_text` the words and `start_s`/`end_s` the scene's clock), kept in `SceneEntry.overlays`, so `scene.shots` and everything that reads it are as before. `_prepare_overlay` builds the span from `clip_frames` and calls `resolve_for_shot` unchanged (`shift_s = 0`, output size). `_rows_by_shot` and `_choices` take a target. `_new_row` and `_write` use the entry's target and `_write_key` (`overlay:{scene}/{first}-{last}`). `queue_repair` finds the entry by `row.target`. New: `start_overlay`, and `target` on `ask_again` and `set_choice`. Overlay refusals have their own wording ("This graphic's brief ...").
- **API**: `OverlayId` (`^[1-9][0-9]*-[1-9][0-9]*$`, since `DiscoveryId` refuses `-`). Both states list `overlays` on each scene (`GraphicBriefOverlayOut` and `ShotGraphicOverlayOut`, subclasses of the shot's model plus `suggestion_id` and `shot_ids`; a scene is listed when it has shots or overlays). New routes: `POST /graphic-briefs/{scene}/overlays/{id}/run`, `POST /graphics/{scene}/overlays/{id}/run`, `POST .../{engine}/ask-again`, `PUT .../choice`. `schema.d.ts` regenerated from the app's own OpenAPI on a throwaway `DATA_DIR` (353 lines added, nothing removed). The name `GraphicOverlayOut` was already taken by OVL-003's model, hence `GraphicBriefOverlayOut`.
- **Pipeline**: the `graphic_briefs` and `graphics` steps have a target `overlay:{scene}/{first}-{last}` for each overlay (label "Scene N, graphic over '...'"; `ref = (scene, overlay id, "overlay")`, so the batch key never equals a shot's). Overlays exist only for a scene whose plan is current, so these targets do not wait on an out-of-date plan. `staleness` lists an out-of-date overlay brief or graphic (not acceptable as is).
- **Frontend**: hooks `useRunOverlayBrief`, `useMakeOverlayGraphics`, `useAskOverlayGraphicAgain`, `useSetOverlayGraphicChoice`; polling includes overlays. Both panels list a scene's overlays after its graphic shots, headed "Graphic over:" with their words (and the context in the brief panel) and no planner's description.
- **Checked** (2026-11-27, a copy of the real database taken with SQLite's backup API from the running container and upgraded to `0102`, removed afterwards; no model call, no dispatcher: jobs were only queued rows in the copy). (1) **Identity:** for all 18 graphics projects the entries of graphic shots in both states (status, reasons, brief row and version, `resolved_sha256`, used engine and attempt, choice, refusal, engines) are byte-identical between `HEAD` and this code. (2) **Placement:** 29.9 s and 29.958 s placed (719 and 720 frames), 30.0 s and 31.0 s `too_long`, a short run lengthened to 3.0 s (73 frames). (3) **Project 94, scene `opening_puzzle`:** `12-30` (g1, 4.625 to 11.75 s over `shot_2` and `shot_3`) and `34-55` (g2, 13.042 to 21.792 s over `shot_4`). Starting a brief queued a job with `target = overlay`, `shot_plan_id` None, the fixed description, the overlay's words and 7.125 s; the same press twice gave one job; the job's task read back; a stand-in brief saved as `target = overlay`, `shot_id = 12-30`, no plan. Both then read `ready`, and the graphics resolved at 1920x1080 with 172 and 211 frames, equal to `clip_frames`. Starting the graphics of `12-30` queued `write_shot_graphic_component` and `write_shot_graphic_scene` with the dedupe value `overlay:opening_puzzle/12-30` and two attempt rows with `target = overlay`; the overlay read `working`; choosing a version without a video and an unknown overlay were refused with the sentences above. (4) **Out of date:** a new plan row with the same content left both briefs `ready`; a moved end made only that brief `out_of_date` (and its graphics blocked with "brief is out of date"); a new timing id made the other one `out_of_date`. (5) The API models, the two pipeline steps (targets with the right refs and labels) and the staleness overview ran on that copy for project 94 without error. (6) `ruff check`, `ruff format --check`, `eslint` and `tsc -b` pass.
- **Not checked.** (1) No model call and no render: the brief text, the two engines' code and the drawn video were not made (they need the owner's go-ahead and a rebuilt app); the brief in (3) is a hand-written stand-in, so "the numbers on screen are the numbers said" was not seen on a real brief (the brief writer's rules are unchanged). (2) Repairs of an overlay's component (`queue_repair` by target) were not run. (3) The panels were linted and type-checked, not opened in a browser. (4) "A re-plan leaves them current" was checked by adding a plan row with the same content, not by a real re-plan (that costs a model call). (5) The output size is used for every overlay until OVL-007 draws a split one at the panel's size. (6) Nothing lays the overlays over the shots yet (OVL-005).

### OVL-005 — Overlays in the render

**Status:** Completed (2026-11-27; the owner still has to rebuild the real app so the new code runs there)

**Objective.** The scene render and the video render lay each overlay full screen over the shots it spans (§4.4).

**Current state.** The frozen timeline (version 6) has `evidence_cards`; `render_story.card_overlays` lays them over shots with `render_commands.Overlay`; `graphic_spans` keep callouts off.

**Scope.**
- An optional key `graphic_overlays` in the frozen timeline (id, scene, times, frames, video, size); the render job reads it and lays each one at `(0, 0)` over the shots it spans, split across cuts. A timeline without the key renders as today, so the version stays 6.
- Overlay spans added to `graphic_spans`.
- A video render without an overlay's video is refused with a sentence; a scene render leaves it out with a warning, as for cards.
- Render out-of-date reasons: an overlay added, removed or with a new video.
- **Planning decides:** the B-roll sound under an overlay (§4.4).

**Out of scope.** Split stretches (OVL-007).

**Dependencies.** OVL-002, OVL-004.

**Expected outcome.** The rendered video shows the owner's graphics over the existing clips.

**Verification criteria.**
- The frozen timeline of a real project without suggestions is identical before and after.
- A throwaway render of project 94's scene 1 with `g1` as an overlay: the graphic over both B-roll shots, the voice unbroken, **no `generate_shot` job queued** (the count of that job type is the same before and after).
- Music placement stays current.
- Standard checks.

**Completion checklist.**
- [x] Timeline key and render job
- [x] Callouts kept off
- [x] Refusals, warnings and out-of-date reasons
- [x] Identity check and throwaway render
- [x] Standard checks
- [ ] Owner: real app rebuilt so the new code runs there

**Completion notes.** Done 2026-11-27. No migration, no new job type, no new setting. `DATABASE_STRUCTURE.md` has an update paragraph for the new timeline key and warning codes.

- **`story_render_plan.py`**: `OverlaySource` (`overlay_id`, `text`, `start_s`, `end_s`, `graphic`) and `SceneSource.overlays`. `_overlay_entries` is shaped like `_card_entries`: an overlay needs a video with `source_frames_needed(frames, fps)` frames (one short allowed); in a scene render one without it is left out with the warning `overlay_without_video`, in a full render the plan is refused with "These graphics over your words have no video yet: ... Make them in the Graphics step." The optional key `graphic_overlays` (`id`, `scene_id`, `scene_index`, `overlay_id`, `text`, times, `start_frame`, `frames`, `source_frames`, `graphic_id`, `engine`, `attempt`, `path`, `clip_frames`, `x` 0, `y` 0) is written only when there is one, so `TIMELINE_VERSION` stays 6. Overlay spans are added to `graphic_spans` (a callout starting in one is dropped). `_shift_timeline` moves them. New warning `overlay_over_evidence` when an overlay covers a card or a full-screen (not split) evidence shot.
- **`story_renders.py`**: `overlay_videos` (the overlay entries of `shot_graphics.state`, by `(scene id, overlay id)`), `_overlay_sources`, `scene_sources(..., with_overlays=True)`. `next_render_sources` and `timing_sources` pass `with_overlays=False`, so the music placement and its `_timeline_hash` cannot be touched by overlays. `overlay_reasons` is wired into `_render_reasons` and `state`: an overlay removed, with no current video, or with another attempt; an overlay with a video added since. An overlay with no video yet is not "added" (the render could not have had it).
- **`scene_renders.py`**: `_Context.overlays`; `_scene_reasons` uses `overlay_reasons` for the scene's own overlays.
- **`jobs/render_story.py`** (also used by `render_scene`): `GraphicOverlay`, `Timeline.graphic_overlays`, `_parse_graphic_overlays` (a bad entry is `_CHANGED_MESSAGE`; the video needs `source_frames - 1` frames), `probe_graphic_overlay`, and `card_overlays` now takes cards or overlays. The overlays of a shot are `[*callouts, *cards, *graphic overlays]`, so the graphic is on top (the owner's choice, until OVL-007).
- **Planning decided.** B-roll sound is not lowered under an overlay (no change to the mix). Stacking: graphic on top of a card, with a warning. Overlays are left out of the music and timing sources.
- **API**: the two warning codes in `WarningCode`; `schema.d.ts` regenerated from the app's own OpenAPI on a throwaway `DATA_DIR` (one line changed).
- **Checked** (2026-11-27, no model call, no render job queued; a copy of the real database taken with SQLite's backup API from the running container, upgraded to `0102`, and a worktree of `HEAD`; both removed afterwards). (1) **Identity:** for all 18 projects, the SHA-256 of the frozen timeline of every scene render (101 scenes), of the full render when it can be made, and of `next_render_sources`' timeline is the same at `HEAD` and with this code (the copy has no media, so most projects are blocked and the check is of the reason as well). `story_renders.state` and `scene_renders.state` ran for every project without error; the count of `generate_shot` jobs was 370 before and after. (2) **A scene render of a synthetic scene shaped like project 94's** (five shots: three clips, an evidence shot, a clip; solid-colour videos made with FFmpeg; an overlay of 4.625 to 11.75 s with a magenta video and one of 13.042 to 21.792 s): at 24 and at 30 fps the plan has the entry (frames 111 + 171 at 24, 139 + 214 at 30), the job reads it back (`parse_timeline`), and stage 1 (`trim_args` with the overlays `card_overlays` gives) shows the clip under the first shot, the graphic for all of the second shot and for the third shot until the overlay ends, and the clip again after it; no overlay on the others. The second overlay without a video: warning `overlay_without_video`, and a full plan is refused with the sentence; with a video: `overlay_over_evidence`. Without overlays the key is absent. (3) **Out of date:** `overlay_reasons` on sample cases: same, removed, no video, new attempt, added, added without a video (no reason), another scene ignored. (4) `ruff check`, `ruff format --check`, `eslint` and `tsc -b` pass.
- **Not checked.** (1) No real render and no real overlay video: project 94's copy has no media files, so "the graphic over both B-roll shots of scene 1" was checked on the synthetic scene, not on project 94, and the voice was not heard (the sound path of `trim_args` and the voice layer are not touched by overlays, but nothing was listened to). (2) The whole `render_story` job was not run (it needs the app's storage and job queue); its stage 1 was run with the same functions. (3) A callout dropped under an overlay was not run; the overlay span is added to `graphic_spans`, which `callout_render.resolve` already uses. (4) `mypy` is not installed in the backend environment, so it was not run. (5) The overlay is laid at the project's output size; a video of another size is scaled by the `overlay` filter's input, not checked (OVL-004 draws it at the output size). (6) When a scene's plan goes out of date its overlays are no longer listed, so a render laying them also says "removed" next to the plan's own reason.

### OVL-006 — Evidence added later becomes a card

**Status:** Completed (2026-11-27; the owner still has to rebuild the real app so the new code runs there)

**Objective.** Showing a new claim or piece after the shots were planned makes a card, not a new shot plan, and does not take away the evidence already shown (OV-6).

**Current state.** §2, "Evidence added later is worse than a suggestion today". Cards are already placed from the claims shown now (`_claim_times`), so once the plan stays current a newly shown claim without an evidence shot gets a card by itself.

**Scope.**
- **Shown evidence per claim, not all or nothing.** A claim stays shown while its words and its reviewed pieces are unchanged, even when another claim is new and not yet researched. A new claim is shown once a round that has it is reviewed.
- **The plan's evidence check** (`_evidence_reasons`) asks only whether every evidence shot of the plan still shows a shown piece of its claim, on the same words. A claim or piece added, or a later piece, gives a card; a claim removed that has its own evidence shot makes the plan out of date (that shot must go).
- Shots no longer wait for the evidence step when a plan exists and only new claims are not reviewed; a scene with no plan still waits (EV-9).
- A later re-plan gives the planner every shown claim, as today, so it may plan a full evidence shot for a claim that had a card.
- **Planning decides:** whether a new round carries the accepted pieces of unchanged claims, or the shown pieces are read across rounds; what the evidence step on the board says while a new claim waits.

**Out of scope.** Splits (OVL-007); a choice between card and shot for each claim.

**Dependencies.** None.

**Expected outcome.** Marking a new claim after the clips exist changes no plan and no clip; once its round is reviewed, it shows as a card.

**Verification criteria.**
- On a snapshot: a new claim leaves every scene's plan current and the existing evidence shots and cards as they were; after its round is reviewed it has a card.
- Removing a claim that has an evidence shot makes only its scene's plan out of date.
- Standard checks.

**Completion checklist.**
- [x] Shown evidence per claim
- [x] New evidence check on the plan
- [x] Shots no longer held back by a new claim
- [x] Board text
- [x] Checks above
- [x] Standard checks
- [ ] Owner: real app rebuilt so the new code runs there

**Completion notes.** Done 2026-11-27. No migration, no new job, no new setting, no change to the research skill. `DATABASE_STRUCTURE.md` has an update paragraph.

- **Planning decided (the owner's choices).** (1) **Delta rounds:** a new round's brief carries only the claims that are waiting; a claim's evidence is read from the newest *reviewed* round that holds it unchanged. This replaces the EVD-003 choice "every round carries every claim and stands alone" (noted in `Evidence_layer_implementation_phases.md`). (2) **Carry on:** a scene with a current plan goes on to cards, clips and renders while a new claim waits; a scene that needs a new plan still waits (EV-9).
- **`evidence_rounds.py`**: `EvidenceState` gains `covered` (claim id to the covering round), `waiting` (claims that count and have none) and `live` (the newest round holds at least one claim that counts, unchanged). `current` now means the newest round holds every waiting claim unchanged (a new brief would add nothing); `is_done` is "nothing is pending and nothing waits"; `make_round` writes `brief_claims(script, waiting)`; `refusal` has a new sentence for "every claim already has reviewed evidence"; `awaiting_text` adds "(N new claims; the M reviewed claims stay on video)" only when some claims are already reviewed. `claim_key` reads a missing `want` as `evidence` and a missing `speaker` as none, so a brief written without sound bites still matches a claim compared inside a set that has one. A round's standing is only worked out for a round that holds one of the waiting claims.
- **`evidence_review.py`**: `_load` is split into `_load_round`; only the newest round gets a write refusal. `_write_refusal` and `evidence_import.import_refusal` refuse when the newest round is not `live` (before: when the claims were not exactly the round's). New `shown_view` gives the `ReviewClaim` of each covered claim from its covering round, in story order; `shown_claims` and `shown_soundbite_clips` read it, so they no longer need "the newest round has exactly the claims that count now".
- **Readers**: `evidence_clips._newest_pieces` reads the usable pieces of the covered claims in the covering rounds' newest imports (so clips and card clips of older claims stay current); `youtube_draft` takes its Sources from `shown_view` and records the highest-version review row among the covering rounds.
- **`shot_plans.py`**: `_load` always reads the shown claims and sound bites; `evidence_problem` (which holds back planning) is set only when the evidence step is not done. `_evidence_reasons` no longer fingerprints the scene's claims: a plan is out of date only when an evidence shot of its own shows a piece that is no longer shown, its claim is gone, its text changed, or is now a sound bite's, or the claim's words are no longer near the claim's first shot (the shot must still touch the window from three words before the claim's first word to its last word). A claim or piece added gives no reason: `place_cards` gives it a card. `inputs.evidence_sha256` is still written and nothing reads it. The timeline for the plan job reads the sound bites the same way.
- **Pipeline**: `shot_plans` no longer needs the `evidence` step as a whole (`story_pipeline.STEPS`); `_evaluate_shot_plans` reports a scene held back by `EVIDENCE_FIRST_MESSAGE` as **awaiting** the owner (a wait), not as a block.
- **API and UI**: `EvidenceStateOut.reviewed_claims` and `waiting_claims`; `schema.d.ts` regenerated from the app's own OpenAPI (4 lines added, nothing else). `EvidencePanel.tsx` shows "N reviewed" and "N waiting for research", the badge reads "New claims since this brief" and the help text says a new round lists only new or changed claims; `EvidenceReview.tsx` says earlier rounds' claims are kept and not listed.
- **Exception to OV-6, kept on purpose.** A sound bite reviewed later still changes its scene's plan (`_soundbite_reasons` is unchanged): a clip replaces words, so it cannot be a card.
- **Checked** (2026-11-27, no model call, no job; a copy of the real database taken with SQLite's backup API from the running container, upgraded to `0102`, with a throwaway files folder, and a copy of `HEAD`'s source; all removed afterwards). (1) **Identity:** for the 7 projects with evidence on, every scene's status, reasons, evidence shots, cards, unplaced cards and source lines are the same at `HEAD` and with this code. Only the new fields and the refusal sentence differ. (2) **New claim on project 94** (16 scenes with a current plan, all claims with evidence shots): after marking words as a claim, every scene stays `planned`, the shot clips and card clips are unchanged, the step reads not done with one claim waiting and a brief can be written; the brief of round 2 holds only that claim. After a stand-in import (round not reviewed) nothing changed either. After a stand-in review (done) the claim is covered, the step is done, `shown_view` holds 16 claims, and only the scene of the claim changed: it has a card `c16.1` (2.72 to 5.72 s), with the card clip `none` (not made yet); the other scenes and every shot clip are identical. (3) **A claim with an evidence shot dropped:** only its scene (`opening_puzzle`) went `out_of_date` ("The evidence that a shot of this scene shows is no longer shown, or has moved."); the 15 others stayed planned. (4) **Pipeline:** `_evaluate_shot_plans` showed 16 scenes done and the one out-of-date scene open. While a claim waited, the other targets stayed done. (5) `ruff check`, `ruff format --check`, `eslint` (the two changed components) and `tsc -b` pass.
- **Not checked.** (1) No real research, import or review: the import and review rows of (2) are stand-ins I wrote, so the browser flow (review screen, "Review done") was not run and the panels were linted and type-checked, not opened. (2) No sound bite case: no project of the copy mixes a sound bite with a later claim, so `shown_soundbite_clips` through the covering rounds ran only on projects whose sound bites (if any) are in one round. (3) A round written **before** this change that is reviewed again after it becomes the covering round for every claim it holds; if its pieces got new keys, their evidence shots go out of date, as they would have before (not seen on the copy: no such round exists there). (4) A re-plan that gives the planner the claims while another waits was not run (it costs a model call). (5) While a claim waits, a planned scene reports `can_run` false with "Gather the evidence first..." (a manual re-plan of it waits too, as a scene without a plan does). (6) The review screen lists claims of the newest round that have since changed or been removed, and "Review done" asks for a decision on them too. (7) `mypy` is not installed in the backend environment, so it was not run.

### OVL-007 — Split screen for a graphic and evidence

**Status:** Completed (2026-11-27; the owner still has to rebuild the real app so migration `0103` and the new code run there)

**Objective.** An overlay that meets an evidence shot or a card shares the screen with it (OV-7, §4.5).

**Current state.** EVD-016 draws an evidence clip in a panel for a callout (`evidence_clip_layout.split_panel`, `evidence_clips.LAYOUT_SPLIT`); graphics are drawn at one frame size.

**Scope.**
- Split stretches worked out on read from overlays, evidence shots and cards (pure), carried on `SceneEntry`.
- The overlay's span grows to the stretch; its graphic is resolved and drawn at the panel's size.
- The evidence side: the evidence clip in split mode with the graphic's panel, or the card drawn in that panel, for the whole stretch.
- The render lays both panels over the shots of the stretch; callouts dropped in it.
- **Planning decides:** the portrait proportions; how a stretch that runs into a sound bite shot is cut.

**Out of scope.** Three panels.

**Dependencies.** OVL-005, OVL-006.

**Expected outcome.** Project 94's `g2` shows beside the evidence screenshot of shot 4.

**Verification criteria.**
- Sample cases: an overlay inside an evidence shot, one over its start, one over a card, one over two evidence shots in a row.
- A throwaway render of project 94's scene 1 in landscape and in portrait; the quote's text height on the evidence side is checked against the 38 px floor (EVD-008) and a warning given below it.
- Standard checks.

**Completion checklist.**
- [x] Split stretches
- [x] Graphic at panel size
- [x] Evidence side
- [x] Render
- [x] Checks above
- [x] Standard checks

**Completion notes.**

Decisions (owner, 2026-11-27): the evidence clips of a stretch get their own purpose `split` (migration `0103`), not card rows; portrait is 50/50, graphic on top (`evidence_layout.PORTRAIT_GRAPHIC_SHARE`).

- **`split_stretches.py` (new, pure).** `find(scene_id, overlays, evidence_shots, cards, bites)` joins overlays that strictly overlap an evidence shot or a card into a `Stretch` (union of overlays and evidence; touching only is no meeting). Each side is cut into `Segment`s: a member is drawn from its own start (the stretch's start for the first) to the next member's start (the stretch's end for the last). A stretch is refused, and the overlay stays full screen with a board note, when a graphic segment needs more than the 720-frame limit (`too_long`) or a sound bite shot is in the way (`soundbite`).
- **The overlay's own span is not changed.** `Overlay.start_s` and `end_s` stay as placed, so its brief (which records them) is not out of date; the stretch spans are carried on `SceneEntry.stretches` and `refused_stretches`. Evidence shots and cards that a stretch absorbs are removed from `SceneEntry.splits` and `cards`.
- **Graphic at panel size.** `graphics_resolve.resolve` takes the caption zone of the panel; `shot_graphics._prepare_overlay` resolves a split overlay at the panel's width and height for its segment (`shift_s` from the overlay's start to the segment's start). A changed size is a changed hash, so the graphic is drawn again from the same brief (no model call); when the overlay stops being split it is drawn again at full size the same way. `ShotGraphicOverlayOut.split` tells the panel.
- **Evidence side.** `evidence_clips` has `PURPOSE_SPLIT`, `split_state` and `queue_split_clip`: one `split` clip per evidence segment, made by the existing `render_evidence_clip` job in split mode (`inputs.layout = "split"`, `inputs.panel`, `segment_id`, `stretch_id`), a full-frame opaque video with the evidence in its half. Currency is by comparing look keys; dedupe key `split_clip_ref`. The pipeline gets `split:{ref}` targets, labelled "evidence beside a graphic".
- **Render.** Optional timeline key `split_evidence` (version stays 6); overlay entries carry the panel's `x`, `y` and `"split": true`. Stage 1 stacks `[*callouts, *cards, *split evidence, *graphic overlays]`, so the graphic panel covers the empty half of the evidence clip. Stretch spans are added to `graphic_spans`, so a callout that starts in one is dropped. A full render refuses while a split clip is missing (`split_without_video` in a scene render); a clip whose quote is below the floor gives `split_small_text`. Story and scene renders list a missing or changed split clip as out of date.
- **Checks run.** (1) Sample cases on `split_stretches.find`: inside an evidence shot, over its start, over a card, two evidence shots in a row, two overlays joined through one shot, no meeting, touching only, 31 s refused `too_long`, a sound bite in the way refused `soundbite`. (2) Migration `0103` up, down (with a `split` row, which the downgrade deletes) and up again on a copy of the real database taken at `0101` (it also ran `0102`); `integrity_check` and `foreign_key_check` ok; `alembic check` shows only the older `FLOAT`/`REAL` differences, none on `evidence_clip`. (3) Identity check on that copy: `shot_plans.state`, `shot_graphics.state`, `scene_renders.state` and `story_renders.state` of all 18 projects, dumped as sorted JSON at the previous commit and with this code, with the new fields left out. 14 projects are identical. Four (83, 84, 93, 94) have an overlay that meets evidence: there the only differences are the absorbed cards or evidence shots, the stretch start used as the overlay's drawn start, and the extra out-of-date reason for the split clip of project 94 ("The evidence clip of shot shot_4 of scene 1 is not ready now."). The `generate_shot` job count (370) and the total job count did not change, and no model call was made. (This run caught a missing `stretch` argument on `_shot_entry`, which is fixed.) (4) The plan entries (`_overlay_entries`, `_split_entries`, `_parse_split_evidence`) were built for a project-94-shaped scene in landscape (panels 960x1080, evidence left) and portrait (panels 1080x960, graphic on top) with no warning. (5) `ruff check`, `ruff format --check`, `tsc -b` and `eslint` on the panel pass; `gen:api` was run on a throwaway data folder (warning codes and `split`).
- **Not checked.** (1) No real split clip was made (H3-free but needs the owner's go-ahead and a rebuilt app), so the quote's height against the 38 px floor and the `split_small_text` sentence were not seen on project 94's real screenshot, and no real render ran: stage 1 with the panel positions was checked through the plan entries and the parser, not through ffmpeg. (2) No real graphic was redrawn at panel size (it needs a brief and the engines). (3) The graphics panel text was linted and type-checked, not opened in a browser. (4) The pieces after a joined stretch (two overlays through one shot) ran in the sample cases only; no real project has one. (5) `mypy` is not installed in the backend environment, so it was not run. (6) Cards in a stretch use the same `split` clip path as shots, so a card that is absorbed is drawn as a clip in its half rather than by the card's own layout; this was not seen on a real card.

### OVL-008 — Project 94 end to end

**Status:** Not Started

**Objective.** The owner checks the whole flow on project 94.

**Scope.** With the real app rebuilt: `g1` and `g2` as overlays (one full screen, one split with the evidence), a third suggestion added after the render, a claim added after the render, a full video render. The owner watches the result and notes what to tune (§4.2 starting values, the split layout, the sound under overlays). The agent records it and confirms that no H3 clip was made.

**Dependencies.** OVL-005, OVL-007.

**Completion notes.**

### OVL-009 — Keep unchanged shots when a scene is planned again (later)

**Status:** Deferred

**Objective.** A re-plan for any other reason (a story edit, a new take) keeps the clip of every shot that did not really change.

**Idea.** A shot of the new plan with the same type, the same first and last word and the same events as a shot of the previous plan takes that shot's description (and its id is matched), so its skeleton hash is the same and its definition and clip stay current. Or the planner is given the previous shots and asked to keep the unchanged ones word for word. Not needed for overlays; it removes the waste of §2 for every other re-plan.

---

## 7. Progress tracking

Follow §7 of `Evidence_layer_implementation_phases.md`: when a phase changes status, update its **Status** line in §6, its row in the §5 table and the **Progress snapshot**, and add a row to Appendix A. Write the **Completion notes** before marking a phase Completed. If a decision or the design changes, update §3 or §4 too.

---

## 8. Open questions and risks

### 8.1 Open questions

| ID | Question | Default until answered |
|----|----------|------------------------|
| Q-O1 | Should the planner still make its own graphic shots where an overlay will cover them? | Yes; they are made and hidden (§4.4). |
| Q-O2 | Should B-roll sound be lowered further under an overlay? | No: it plays as without the overlay. |
| Q-O3 | Portrait proportions of a split stretch? | Answered (2026-11-27): 50/50, graphic on top. |
| Q-O4 | Should the owner be able to choose a side panel instead of full screen for one overlay? | No (owner's choice, 2026-11-26). |

### 8.2 Risks

- **Paid B-roll hidden.** A B-roll clip under a full-screen overlay was paid for and is not seen. Accepted: making it again would cost more.
- **Overlays on every few seconds.** Nothing limits how much of a scene is covered; a scene covered from start to end hides the presenter. The board could warn above a share of the scene (not planned here).
- **Split readability.** Landscape evidence at half width is often under the 38 px floor (EVD-011's notes); the graphic at half width has less room for numbers.
- **The Story Bible says the opposite.** A project whose Story Bible forbids on-screen numbers gets number graphics when the owner asks for them (OV-2). That is the owner's choice; the planner's own graphic shots still follow the Story Bible.
- **Evidence rounds** (OVL-006) are the deepest change here: shown evidence moves from all or nothing to per claim. A mistake shows a piece whose claim changed; the checks of OVL-006 are there for that.

---

## Appendix A — Progress log

| Date | Phase | Change |
|------|-------|--------|
| 2026-11-26 | — | Document written. |
| 2026-11-26 | OVL-001 | Completed: migration `0102` (`target` column on the three graphics tables), models, readers limited to shot rows, `DATABASE_STRUCTURE.md`. |
| 2026-11-27 | OVL-002 | Completed: suggestions removed from the planner's request, answer, stored content and out-of-date check; `scene_suggestions` moved to `graphic_suggestions.py`; API field removed; panels and texts updated. |
| 2026-11-27 | OVL-003 | Completed: pure `graphic_overlays.py` (placement, keys, reason codes), `SceneEntry.overlays` and `unplaced_overlays`, API fields, board notes on the Graphic briefs step, `trimmed` flag on suggestions cut by a sound bite. |
| 2026-11-27 | OVL-004 | Completed: briefs and graphics for overlays (`target = 'overlay'` rows, `start_overlay` in both services, `overlays` on both states and APIs, pipeline and staleness targets, panel cards), `clip_frames` and the stricter `too_long` check. |
| 2026-11-27 | OVL-005 | Completed: optional `graphic_overlays` key in the frozen timeline (version stays 6), overlays laid full screen over the shots by `render_story` (on top of callouts and cards), refusals and warnings (`overlay_without_video`, `overlay_over_evidence`), out-of-date reasons for story and scene renders, overlays kept out of the music and timing sources. |
| 2026-11-27 | OVL-006 | Completed: evidence per claim (`covered`, `waiting`, `live` on the evidence state; delta rounds that carry only waiting claims; `shown_view` across reviewed rounds), a plan goes out of date for evidence only when its own evidence shot loses what it shows, `shot_plans` no longer waits on the evidence step as a whole, API counts and panel texts. |
| 2026-11-27 | OVL-007 | Completed: split stretches (pure `split_stretches.py`, carried on `SceneEntry`), graphic drawn at the panel's size from the same brief, `split` evidence clips (migration `0103`, `split_clip_ref`), optional `split_evidence` timeline key and panel position on overlay entries, callouts dropped in a stretch, warnings `split_without_video` and `split_small_text`, out-of-date reasons for renders, 50/50 portrait. |
