# Vision Studio — Explainer Music Phases

Today an explainer gets its music from the story music system (`Music_implementation_phases.md`), unchanged. That system was designed for narrative short films, and three things go wrong for an explainer:

- **The music does not fit the video.** Every music prompt says "a studio that turns written stories into short films". Themes stand for a character, a place or an idea, but an explainer has one presenter and one studio. The plan may ask for ambience beds (rain, wind, room tone), point sounds and hits, which a studio explainer does not want. The rules ("silence is a choice", "music that never stops is as weak as no music", a `through_silence` join for a time jump) are film-scoring rules. In an explainer the voice runs almost the whole time, and the music is a steady underscore that changes with the sections of the script. The mix lets music swell in the gaps between lines, which pumps under a fast presenter.
- **The music goes out of date whenever a shot changes.** The music plan records every scene's shot plan and a hash of the timeline (`music_plan._out_of_date_reasons`). In an explainer, shots are planned again often (a graphic, an evidence shot, a sound bite, a B-roll change). Each time, the plan, its critics, the cue details and the unlocked takes are made again, and the render is refused until they are.
- **The music waits for things it does not need.** Cue detail waits for the shot definitions (who is in each shot), and placement waits for every clip (because a hit may sit on a sound H3 made). An explainer's music needs only the voice and its sections.

This plan gives a continuous explainer its own music path: **a fresh, voice-first underscore for each project, planned on the voice, not on the shots**, and **subtle sound effects on graphic and evidence moments**, made once per project and reused across that project only.

- The conventions of `Implementation_phases.md` (§3.3 to §3.5, §6) apply unchanged. Table and column details go in `DATABASE_STRUCTURE.md`. The newest migration when this was written was `0101`.
- The decisions of `Music_implementation_phases.md` still apply to an explainer unless a decision below replaces them (MD-1 judgment belongs to the model, MD-10 first passing take, MD-22 every decision stored, MD-23 feedback loop, MD-19 final loudness all stand).
- Written 2026-11-26, from a design discussion with the owner about explainer audio and music.
- EXM-001 is a go/no-go trial. EXM-004 and later do not start until it passes.

---

## 1. Decisions

| # | Decision |
|---|----------|
| XM-1 | **For continuous explainers only.** A project with `kind = explainer` and `voice_track = continuous` gets the explainer music path. A `lines` explainer and a story keep today's music path, and every instruction and request they send stays byte-for-byte what it is today (as E-8). |
| XM-2 | **Music is generated fresh for every project.** There is no music kit and nothing is stored for reuse across projects. Each project's Music Bible, plan, cues and takes are its own, as today. |
| XM-3 | **A voice-first underscore.** The music plan of an explainer has only `score` and `silence` cues. No `bed`, `point` or `hit` cue is allowed. Score is sparse, with no lead melody competing with the voice, and changes at section boundaries (scenes), at a deliberate "post" (a short rise in a real gap: after a punchline, between sections) or at a "drop" (the music stops just before a key line and returns after it). |
| XM-4 | **No themes for explainers.** The Music Bible of an explainer has no themes, and the `music_themes` step is skipped as complete. Instead, the Bible names one shared palette for every cue: instruments, a tempo and a key (or a narrow range), and what to avoid. Every cue prompt carries it, so neighbouring sections sound like one score and crossfade cleanly. |
| XM-5 | **The music follows the voice, not the shots.** An explainer's plan names only scenes and speech units (no shots, no events). Its out-of-date check looks at what moves the voice: the scene list, each scene's take and its timing, the unit texts and the sound bite spans. A shot plan that changes only its picture (B-roll, graphic, evidence, presenter cuts) never makes the music plan, the cue details or the takes out of date. |
| XM-6 | **Music placement does not wait for the clips.** An explainer's placement is made on the timing alone, as the provisional placement of SCN-011 is (`music_placement._timeline_hash(with_takes=False)`), so a clip made again does not make it out of date. |
| XM-7 | **A mix for a talking voice.** The music is always ducked under the voice. It rises only at a planned post, in a gap of at least a set length, never in the short gaps between sentences. The explainer has its own duck depth and gap settings, so a story's mix is unchanged. |
| XM-8 | **Sound effects on graphic and evidence moments.** A new project switch, `sound_effects`, on by default for a new continuous explainer and off for every existing project. It is independent of `music_enabled`: a project with music off can still have sound effects. Changing it makes the render out of date and nothing else. |
| XM-9 | **Sound effects are made once per project and reused in that project only.** Each project gets two sounds, one for graphic shots and one for evidence (full-screen evidence shots and evidence cards), made by Stable Audio 3. Each sound plays at every such moment of that project. They belong to the project, are deleted with it, and are never offered to another project. |
| XM-10 | **Sound effects are placed by code, never by a model, and are subtle.** The sound's loudest moment lands on the first frame of the graphic or evidence. It plays well under the voice, is never placed inside a sound bite, and is skipped when it would follow another sound effect too closely. |
| XM-11 | **Takes and selection work as for music** (MD-10, MD-22, MD-23): several takes, a technical check, the first passing take selected automatically, and the owner can listen, select, reject with a note or lock. |

---

## 2. How it works

```text
continuous explainer, music on
  -> Music Bible, explainer branch: palette, section arc, no themes      (EXM-002)
  -> (music_themes skipped as complete)
  -> voice takes and their word timings                                   (unchanged)
  -> shot plans (cut plans)                                               (unchanged)
  -> music plan, explainer branch: score and silence only,
     anchors on scenes and units, out of date only when the voice
     or the sound bites change                                            (EXM-003, EXM-004)
  -> cue detail: no shot definitions, no hit requests                     (EXM-004)
  -> music takes (ACE-Step), beside the clips                             (unchanged)
  -> placement on the timing alone (no wait for the clips)                (EXM-003)
  -> render: music ducked under the voice with the explainer mix          (EXM-005)

continuous explainer, sound effects on (music on or off)
  -> two project sounds: graphic and evidence (Stable Audio 3),
     made once, first passing take selected                               (EXM-006)
  -> render: the graphic sound at every graphic shot, the evidence
     sound at every evidence shot and card, subtle, by code               (EXM-007)
```

### 2.1 An example

A 6-minute explainer has seven sections (scenes). The plan has six score cues and one silence: a tense hook (scene 1), a lighter bed under the credentials and the promise (scenes 2 and 3, one cue), a steady investigative bed for the evidence (scene 4), a rising bed into the reveal with a drop just before the key line (scene 5), a calm takeaway (scene 6) and a short outro (scene 7). Every cue uses the same palette (for example muted synth pulse, soft piano, light percussion, 96 BPM, D minor). The plan names `scene:...` and `unit:...` refs only.

Later the owner adds a graphic shot to scene 4. The cut plan of scene 4 changes, but its take, its units and its sound bites do not, so the music plan, the cue details, the takes and the placement all stay current (the placement is made on the voice, not on shot cuts, EXM-003), and the render plays the graphic sound on the new graphic shot's first frame.

---

## 3. Phases

Run them in this order: 001, then 002 and 006 (they can be built together), 003, 004, 005, 007, 008. EXM-001 is a gate for 004 and later.

Standard checks are those of `Implementation_phases.md` §3.5. Items marked **Planning decides** are left open on purpose and must be settled in the plan of that phase.

### EXM-001 — Trial: section underscores and the two sound effects (owner)

**Status:** Passed (owner, 2026-11-27)

**Why:** the design relies on three things nobody has checked: that ACE-Step 1.5 can make a sparse underscore that sits under a fast voice without fighting it, that two section cues made with the same palette (tempo, key, instruments) crossfade without an audible seam, and that Stable Audio 3 can make a short, subtle whoosh that does not sound cheap.

**How:**

1. **Two section cues.** In the Music Lab, with ACE-Step 1.5, make two instrumental score runs of about 60 s each for two neighbouring sections of a real explainer (for example scenes 4 and 5 of project 94): the same instruments, tempo and key in both briefs, one calmer and one rising. Ask for no lead melody.
2. **Under the voice.** Put each run under the matching scene take in an audio editor (or the scene's music preview, if a plan exists) at about the level of `music_duck_low_db`. Is the voice always clear? Does the music feel like "production" or like noise?
3. **The join.** Crossfade the end of the first run into the start of the second over about 2 s. Is the change of section heard as one score moving on, or as two different pieces?
4. **Sound effects.** With Stable Audio 3, kind `sfx`, make three takes each of: a soft, short whoosh for a graphic appearing (under 1.5 s), and a soft paper-like or light swish for a document or evidence appearing (under 1.5 s). Place one of each under a voice at a low level. Are they subtle enough to hear without noticing them?

**If the join fails** (two runs with the same palette still sound like different pieces): the explainer plan uses fewer, longer cues (one cue across several calm sections) and joins under a voice line (`under_cover`) with a long fade. Record the choice in EXM-004.

**If the underscore fails** (always too busy under the voice): the cue prompts ask for an ambient pad or pulse only, and the explainer duck is made deeper. Record the choice in EXM-004 and EXM-005.

**If the sound effects fail:** EXM-006 and EXM-007 are dropped, and the switch is not added.

**Result (owner fills in):** The owner marked the trial complete on 2026-11-27 and moved on to EXM-002. No fallback was chosen: the join, the underscore and the sound effects are taken as passing, so EXM-004 plans normal cues and EXM-006 and EXM-007 stay in scope.

### EXM-002 — The explainer Music Bible

**Status:** Code done, live run pending

**Objective.** Give a continuous explainer a Music Bible written for an explainer: one shared palette, an arc by section, and no themes.

**Current state.**
- `services/music_bible_writer.py` writes four directions, a choice and the Bible (MUSIC-006). Every prompt speaks of "a studio that turns written stories into short films". Themes stand for a `character`, `place` or `idea` (`THEME_KINDS`), up to `music_max_themes`. The Bible also has an `ambience` signature and `restraint` / `silence_rules`.
- `music_themes` (MUSIC-007) records each theme and its emotional versions. The step is skipped as complete only when music is off.
- The step `music_bible` needs `events` (`services/story_pipeline.py`).

**Scope.**
- An explainer branch of the three Bible prompts (directions, choice, Bible), used only for a continuous explainer: the script is an explainer one presenter speaks, the music is an underscore under an almost constant voice, it changes with the sections, and it must never compete with the voice.
- The explainer Bible has no themes (XM-4). In their place it has a **palette** every cue must follow: instruments, a tempo (or a narrow range), a key or mode leaning, the density, and what to avoid (for example vocals, a lead melody in the voice's range, big drums under speech).
- The `arc` stays one entry per scene, read as one entry per section, with a role (hook, setup, explain, tension, reveal, takeaway, outro or similar) and an energy level.
- No ambience signature for an explainer, or a fixed "none".
- The `music_themes` step is skipped as complete for a continuous explainer, as it is when music is off.
- A story and a `lines` explainer get exactly the instructions they get today.
- **Planning decides:**
  - whether the four directions and the choice stay for an explainer (cheap model calls), or one direction is written directly;
  - the exact fields of the palette, and whether they reuse existing Bible fields (`sound_world`, `musical_feel`) or are new;
  - whether the section role is a fixed list or free text;
  - whether the owner can write an optional project text that steers the music (like `presenter_delivery` steers the voice), kept on the project only.

**Out of scope.** The music plan (004). Any change for a story.

**Dependencies.** None.

**Expected outcome.** A continuous explainer's Music Bible has a palette and a section arc, and no themes, and no theme is recorded for it.

**Verification criteria.**
- A continuous explainer's Bible has no themes and has a palette; the themes step is complete with nothing made.
- A story's Bible request is byte-for-byte the same as before (checked against `HEAD`).
- Standard checks.

**Completion checklist.**
- [x] Explainer branch of the directions, choice and Bible prompts, and its answer checks
- [x] Themes step skipped for a continuous explainer
- [x] Docs (`DATABASE_STRUCTURE.md` for the Bible's content shape), standard checks

**Completion notes.** Code done 2026-11-27, **live run pending** (the running containers still serve the old code until `docker compose up --build -d`, and the first real Bible run is a paid model call the owner starts). No migration.

- **Planning decided.** Keep the three calls with explainer wording; the palette reuses `sound_world` (instruments, avoid) and `musical_feel` (a narrow tempo, one key, density), so no later step needs a new field; the section role is a fixed list (`ARC_ROLES`: hook, setup, explain, evidence, tension, reveal, takeaway, outro) with an energy of `low`, `medium` or `high`; no project music text for now; an older story-style Bible of a continuous explainer is reported out of date once.
- **Flag.** `music_bible.explainer_music(project)`. The job input gets `explainer: true` only for such a project, so a story's job is unchanged.
- **Prompts and checks.** `music_bible_writer`: `_EXPLAINER_DIRECTIONS_PROMPT`, `_EXPLAINER_CHOICE_PROMPT`, `_explainer_bible_prompt()`; the three builders take `explainer=False`; `check_bible(..., explainer=True)` stores `themes: []` (a non-empty list is refused), sets `ambience_signature` to the fixed `EXPLAINER_AMBIENCE`, and requires `role` and `energy` on every arc entry.
- **Themes step.** `music_themes.wanted(project)` (music on and not a continuous explainer): the adapter returns one finished target and the board shows the step as off.
- **API and UI.** `ArcEntry` and `ArcEntryIn` have optional `role` and `energy`; `MusicBibleState.explainer`. The Bible view and editor hide themes and ambience for an explainer and show a role and energy for each section.
- **Checked.** A script against `HEAD` showed the story's three requests and a story `check_bible` result are byte-for-byte the same; an explainer answer is stored with no themes and the fixed ambience, and an answer with themes, a wrong role or no role is refused. `ruff check`, `ruff format`, `eslint`, `tsc` pass and `schema.d.ts` is regenerated.
- **To check by the owner.** After a rebuild, run the Music Bible on project 94 (it shows "written for a story" first): a palette, roles and energies, no themes, and the themes step off on the board.

### EXM-003 — Music follows the voice, not the shots

**Status:** Code done, live run pending

**Objective.** Make an explainer's music plan, cue details and takes depend only on the voice, the sections and the sound bites, and make its placement independent of the clips.

**Current state.**
- `services/music_timeline.py` builds the timeline the plan is written against from every scene's shot plan: scenes with their moods, **shot cuts**, speech units, **events**, pauses and the gaps between units (`MIN_GAP_S` 1.0). Refs are `scene:`, `shot:`, `unit:` and `event:`.
- `services/music_plan.py` records, for each scene, its shot plan, speech units and events, and a `timeline_sha256`. A plan is out of date when any of them changes, and a scene must have a `generation_ready` shot plan.
- The step graph: `music_plan` needs `shot_plans` and `music_bible`; `music_cues` needs `music_plan`, `music_themes` and `shot_definitions`; `music_placement` needs `music_generation`, `shot_generation`, `graphics` and `evidence_clips`.
- `services/music_placement.py`: the final placement's `_timeline_hash` includes every shot's frames and selected take, so a clip made again makes it out of date. A provisional placement (SCN-011) leaves the takes out.
- For a continuous explainer, a scene's length is its take plus the tail (`cut_planning_writer.TAIL_S`), and a sound bite changes the clock of its scene (`services/take_map.py`). The cut plan holds the sound bites (SB-008).

**Scope.**
- For a continuous explainer, the music timeline lists scenes, speech units (with their spans in the take) and the gaps between and inside them (from the take's word timings). It lists no shots and no events, so the model cannot name them.
- The explainer plan's out-of-date check records: the Music Bible, the scene list, each scene's take and its word timing, the unit texts, and the sound bite spans of each cut plan (which words each bite replaces and its clip length). Shot cuts, shot types, graphics, evidence and B-roll are not recorded. A cue detail and its takes go out of date only through their plan, as today.
- `music_cues` does not wait for `shot_definitions` for a continuous explainer (the cue detail does not need who is in each shot).
- The explainer placement is made on the timing alone (XM-6): it does not wait for `shot_generation`, and a clip made again does not make it out of date. It still waits for the cut plans (the story's seconds) and the selected music takes.
- A story and a `lines` explainer keep their timeline, out-of-date check and step needs exactly as today.
- **Planning decides:**
  - how the step needs differ for an explainer while the step graph stays one graph (for example the adapter reports a story's extra needs as `settling`, as FLOW-004 did, or the needs are widened and the adapter judges);
  - whether the plan still waits for every scene's cut plan (simplest: the scene starts and the sound bites are known exactly) or starts right after the word timings with the sound bites added later (earlier, but the cue lengths may need more handles);
  - where the gaps inside a take come from (the take's word timings, or silence detection of the take as `audio_measurements` does for narration) and the shortest gap that is listed;
  - how existing explainer music plans are read after this phase (out of date once, or kept current when only the fingerprint changed).

**Out of scope.** The plan's prompts (004). The mix (005).

**Dependencies.** None for building; EXM-004 relies on it.

**Expected outcome.** On a continuous explainer, planning a scene's shots again (without changing its sound bites) leaves the music plan, cue details, takes and placement current, and a new clip leaves the placement current.

**Verification criteria.**
- With stand-in data: a changed shot plan with the same take and sound bites gives no out-of-date reason; a remade take, a retimed take, a changed unit text or a changed sound bite each gives one.
- A new selected clip does not make an explainer placement out of date.
- A story's music plan inputs and placement hash are unchanged (checked against `HEAD`).
- Standard checks.

**Completion checklist.**
- [x] Explainer music timeline (scenes, units, gaps; no shots, no events)
- [x] Explainer out-of-date inputs for the plan
- [x] Step needs: cue detail without shot definitions, placement without clips
- [x] Docs, standard checks

**Completion notes.** Code done 2026-11-27, **live run pending** (the running containers still serve the old code until `docker compose up --build -d`). No migration. Nothing here calls a model.

- **Planning decided.**
  - *Step needs:* one graph, with `Step.explainer_needs` and `story_pipeline.for_project(step, explainer=...)`, applied once per step in the run loop (`jobs/story_pipeline.py`) and the board (`services/pipeline_board.py`). `music_cues` needs `music_plan` and `music_themes`; `music_placement` needs `music_generation` and `shot_plans`.
  - *Plan start:* the plan still waits for every scene's cut plan (scene starts and bite lengths exact).
  - *Gaps:* from the pauses between units (no silence detection), listed from 0.5 s (`EXPLAINER_MIN_GAP_S`) with a `length_s`. Measured on project 94 the pauses inside a take are 0.4 to 0.96 s, `lead_in_s` is 0 and the tail 0.3 s, so a 1.0 s limit would list almost nothing. **Flag for EXM-004 and EXM-005:** a "post" in a gap has little room; most gaps are under 1 s.
  - *Old plans:* an explainer plan without `inputs.basis = "voice"` is out of date once.
  - *Placement and shot cuts:* the explainer placement is not snapped to shot cuts (`cuts_s` is empty), so a new shot cannot move it. This follows XM-6 and the expected outcome above, and replaces the sentence of §2.1 that said the placement is worked out again after a new graphic.
- **Flag.** `music_bible.explainer_music(project)`, as for EXM-002.
- **Timeline.** `music_timeline.build_voice`: the keys of a story's timeline, with `shots` and `events` empty, `mood: null`, and a new `soundbites` list (no shot ids). `GET /music-plan` scenes may have `mood: null` (`SceneSpanOut.mood` optional; `MusicPlanStrip` shows it only when present).
- **Plan.** `music_plan._inputs` for an explainer records the Bible, each scene's speech units, and `voice` (take, timing, bite hash) read from the scene's newest shot plan. `_voice_out_of_date_reasons` never reads the shot plan row, events or definitions. Cue details skip shot definitions and themes (`music_cues.load`).
- **Placement.** `story_renders.timing_sources` for an explainer; `inputs.voice_sha256` (`_voice_hash`: length, unit spans, take starts) replaces `timeline_sha256`.
- **Checked.** A script with stand-in data (not kept): a changed shot plan, a replanned scene with new shot ids, an added graphic and evidence shot give the same timeline, hash and no out-of-date reason; a remade take, a retimed take, a changed unit text, a changed sound bite, a longer bite clip, a new Bible and a changed scene list each give one; the explainer placement hash ignores shots and clips and the layout has no cuts. Against `HEAD`: a story's timeline and hash, `Step.needs` of every step, placement `inputs` (final and provisional) and `input_differences` are the same. `ruff check`, `ruff format`, `eslint` and `tsc` pass. `schema.d.ts` was edited by hand for the one field (the OpenAPI of the new code was read to confirm it) and is not regenerated from the running API.
- **Not checked.** `mypy` is not installed in the project's environment. The first real run on project 94 (the step board, a plan, cue details and the placement after adding a graphic shot) is for the owner after a rebuild. Until EXM-004, the plan's prompts are still the film ones: the model may name `shot:` refs or hits, which the check refuses and retries.

### EXM-004 — The explainer music plan and cue detail

**Status:** Code done, live run pending

**Objective.** Plan an explainer's music as a voice-first underscore: score and silence only, changes at sections, posts and drops, every cue following the Bible's palette.

**Current state.**
- `services/music_plan_writer.py`: kinds `score`, `bed`, `point`, `hit`, `silence`; joins `crossfade`, `under_cover`, `through_silence`, `hard_cut`; four critic lenses and a reviser, `music_plan_critic_rounds` rounds (default 2). The prompts are written for a short film.
- `services/music_cue_writer.py`: each cue's detail has anchors, the broad order of moods, `hit_requests` (up to `MAX_HIT_REQUESTS`), a `mix` (`under_voice` `low` or `medium`, `swell_in_gaps`, a note), fade lengths and the source (text, a theme version, a continuation). It reads the shot definitions of the cue's span.
- `services/music_prompt_writer.py` and the ACE-Step profile in `services/music_prompt_profiles.py` write each take's wording.

**Scope.**
- An explainer branch of the plan, critic and revise prompts, used only for a continuous explainer:
  - the script is spoken almost all the time, music sits under it, and changes go at section boundaries, posts and drops (XM-3);
  - only `score` and `silence` cues; anchors name `scene:` and `unit:` refs only (the timeline of EXM-003 has nothing else);
  - a post is a score cue's planned rise in a listed gap; a drop is a short `silence` cue just before a key line;
  - joins: `crossfade` and `under_cover` are the normal ones; `through_silence` only at a real break between sections; `hard_cut` only on a drop.
- Answer checks refuse `bed`, `point` and `hit` cues, `shot:` and `event:` refs and hit requests for an explainer.
- The critic lenses for an explainer: fit to the script's structure (does each section get the energy its role needs), restraint (too many changes, a post in a gap that is too short), consistency with the palette, and joins.
- Cue detail for an explainer: no shot definitions in its input, no hit requests, the source is always text (no theme), and the palette is in every cue's prompt. `under_voice` defaults to `low`; `swell_in_gaps` is true only for a cue with a planned post.
- A story and a `lines` explainer get exactly the instructions they get today.
- **Planning decides:**
  - the explainer's critic rounds (a separate setting, or one round fixed);
  - whether a post is a field of a score cue (its gaps by ref) or a mix note only;
  - the longest cue the plan may ask for (ACE-Step's limits and the risk of a long cue wandering, RM-9 of the music document), and whether calm neighbouring sections may share one cue;
  - the fallbacks chosen in EXM-001, if any.

**Out of scope.** The mix settings (005). Sound effects (006, 007).

**Dependencies.** EXM-001 passed, EXM-002, EXM-003.

**Expected outcome.** A continuous explainer's music plan reads as a section-by-section underscore with a few posts and drops, and every cue's prompt carries the same palette.

**Verification criteria.**
- A plan with a bed, a hit, a point, a shot ref or an event ref is refused and retried.
- The owner reads two explainer plans and judges them right for an explainer: changes at sections, no music fighting the voice, a drop or post where it helps.
- A story's plan and cue requests are byte-for-byte the same as before.
- Standard checks.

**Completion checklist.**
- [x] Explainer plan, critic and revise prompts, and answer checks
- [x] Explainer cue detail and prompt wording (palette, no hits, text source)
- [x] Docs, standard checks

**Completion notes.** Code done 2026-11-27, **live run pending** (the running containers still serve the old code until `docker compose up --build -d`, and the first real plan and cue details are paid model calls the owner starts). No migration. Nothing here calls a model.

- **Planning decided.**
  - *Post:* a field of a score cue. The model writes `posts` as a list of `unit:` refs; each names the listed gap right after that unit (`music_timeline.Index.gaps_after`). Code checks the gap exists, lies inside the cue and is named once, and stores `{after, start_s, end_s, length_s}`. Code sets `mix.swell_in_gaps` from it, so EXM-005 can rise only at these gaps. Whether a gap is long enough is judged by the `restraint` critic, not by code (most gaps are under 1 s, see EXM-003).
  - *Longest cue:* calm neighbouring sections may share one cue; code refuses an explainer score cue longer than `EXPLAINER_MAX_CUE_S` (120 s).
  - *Critic rounds:* the existing `music_plan_critic_rounds`. No new setting.
  - *EXM-001 fallbacks:* none, so normal cues.
  - *Drops and joins:* a drop is a short `silence` cue. "`through_silence` only between sections" and "`hard_cut` only at a drop" are prompt and critic rules, not code checks.
- **Flag.** `music_bible.explainer_music(project)`. The jobs `write_music_plan`, `write_music_cue`, `audit_music_cues` and `rewrite_music_prompt` get `explainer: true` in their input only for such a project, so a story's job input and requests are unchanged. The builders and checks take `explainer=False`.
- **Plan.** `music_plan_writer`: `EXPLAINER_KINDS`, `EXPLAINER_LENSES` (`section_fit`, `restraint`, `palette`, `joins`; `lenses(explainer)`), the explainer plan, critic and reviser prompts, and `check_plan(..., explainer=True)` (only `score` and `silence`, no `theme_id`, no `shot:` or `event:` ref, the 120 s limit, `posts`). `GET /music-plan` has `explainer`; a cue has optional `posts`; the editor offers only score and silence for an explainer, hides themes and keeps a cue's posts (with a button to clear them).
- **Cue detail.** `music_cue_writer`: `span_context(..., explainer=True)` (voice only, with `soundbites`), `_EXPLAINER_SPAN_PROMPT` (no hit requests), `check_detail(..., explainer=True)` (hit requests refused, `under_voice` defaults to `low`, `swell_in_gaps` from `posts`, a free edge may not move a post out of the cue), `_EXPLAINER_WORDING_PROMPT` and `_ACE_PALETTE_RULE` (every wording keeps the Bible's instruments, tempo range and key), `_EXPLAINER_AUDIT_PROMPT` (palette drift, no themes), and the rewrite of a rejected take. The cue source is always text.
- **Palette warnings.** `palette_of(bible)`; a wording whose `keyscale` is not named in `musical_feel.mode_leaning`, or whose `bpm` is outside the range read from `tempo` (when two numbers can be read), gets a warning on its wording (never a refusal).
- **Checked.** A script with stand-in data (not kept) against `HEAD` (a copy of the tree at `HEAD`): a story's plan, critic (all four lenses), revise, detail (with its context), wording, audit and feedback request bodies, and its `check_plan`, `check_detail`, `check_wordings`, `check_audit` and `check_feedback` results, are byte-for-byte the same. For an explainer: a plan with a bed, point or hit cue, a `shot:` or `event:` ref, a theme, a score cue over 120 s, or a post that is not a listed gap, lies outside its cue, is given twice or is on a silence cue is refused; a detail with hit requests is refused; `swell_in_gaps` follows `posts`; palette warnings fire for a wrong key or tempo. `ruff check`, `ruff format`, `eslint` and `tsc` pass. `schema.d.ts` was edited by hand (`CueIn.posts`, `CueOut.posts`, `PostOut`, `MusicPlanState.explainer`) and is not regenerated from the running API.
- **Not checked.** `mypy` is not installed in the project's environment, and the job modules cannot be imported outside the containers (no database driver), so the changes to the four jobs and to `music_cues`, `music_takes` and `music_plan` were checked by reading and by `ruff` only. The first real run on project 94 is for the owner after a rebuild: run the plan and read two plans (changes at sections, a post or drop where it helps, no `bed`/`hit`), then the cue details (every prompt follows one palette), and judge them right for an explainer.

### EXM-005 — The mix for a talking voice

**Status:** Code done, live run pending

**Objective.** Mix an explainer's music so the voice is always clear and the music only rises where the plan put a post.

**Current state.**
- `services/story_render_plan.py`: the music is ducked under narration and dialogue by the cue's `under_voice` (settings `music_duck_low_db` −18 dB and `music_duck_medium_db` −10 dB), with ramps of `MUSIC_DUCK_RAMP_S` (0.4 s). A cue with `swell_in_gaps` comes back up in a gap of `MUSIC_GAP_RELEASE_S` (1.0 s); otherwise only in a gap of `MUSIC_GAP_HOLD_S` (4.0 s). Under a sound bite the music goes down by `BITE_MUSIC_DUCK_DB` (−26 dB).
- The finished mix is brought to `render_loudness_lufs` (−14) with a ceiling of `render_true_peak_db` (−1).
- The voice of a continuous explainer is the `voice` layer (FLOW-008); music placement sees each unit's span as speech.

**Scope.**
- For a continuous explainer, the music duck and the gap rules come from explainer settings: a duck depth (deeper than a story's by default), a release gap for a planned post, and a hold gap for every other cue, so the music never rises between ordinary sentences.
- The sound bite duck and the final loudness are unchanged.
- A story's and a `lines` explainer's render commands are unchanged.
- **Planning decides:**
  - the starting values (to be tuned by ear on the first real explainer);
  - whether the explainer duck is one setting or one per `under_voice` level;
  - whether a high-frequency dip (EQ) of the music under the voice is worth adding now, or later.

**Out of scope.** The voice's own processing (a separate discussion about the voice master).

**Dependencies.** EXM-004.

**Expected outcome.** On a real explainer render the voice is always clear over the music, and the music rises only at planned posts.

**Verification criteria.**
- A story's FFmpeg commands are the same as before for the same timeline.
- The owner listens to one explainer render: no pumping between sentences, posts audible, the voice clear throughout.
- Standard checks.

**Completion checklist.**
- [x] Explainer mix settings and their use in the render plan
- [x] Docs (settings in `DATABASE_STRUCTURE.md`), standard checks

**Completion notes.** Code done 2026-11-27, **live run pending** (the running containers still serve the old code until `docker compose up --build -d`). No migration. Nothing here calls a model.

- **Planning decided.**
  - *Post:* a partial rise. The duck stays on through the gap and the music rises by `explainer_music_post_rise_db` (+8 dB) only inside the pause of each post, so in a gap under 1 s the music goes from -22 dB to about -14 dB, not back to full level. A rise is only made where the music is still lowered: a gap of 4 s or more is already released by the hold gap, so a post there adds nothing and no rise is written.
  - *Duck:* one setting for every explainer cue, `explainer_music_duck_db` (-22 dB). `under_voice` and `swell_in_gaps` are not read for a continuous explainer (EXM-004 defaults every cue to `low`).
  - *Gaps and ramps:* constants recorded on the timeline: hold gap `EXPLAINER_MUSIC_HOLD_GAP_S` 4.0 s, post ramp `EXPLAINER_POST_RAMP_S` 0.15 s (half the pause when shorter). The `MUSIC_GAP_RELEASE_S` of a story is not used.
  - *EQ dip:* left for after the first listen.
- **Render plan.** `story_render_plan`: `MixSettings.explainer_duck_db` and `explainer_post_rise_db`, `MusicSource.posts` (by cue id, `(start_s, end_s)`), `explainer_constants(mix)` (merged into `constants` only for a continuous explainer with music), `_post_rises(...)` and `_music_timeline(..., explainer=continuous)`. A rise is the post's span minus the render's own speech spans (so never over a word), inset by its ramp.
- **Source of the posts.** `render_music.cue_posts` reads `cues[].posts` from the plan named by the placement's `inputs.plan`; used in `gate`, `scene_gate` and the preview (`music_preview._source_with_take`). A story's plan has none.
- **Render job.** `render_commands.Rise` and `LaneSound.rises` (a `gain_bump_filter` after the duck); `render_story._parse_rises` (a missing key means none). The timeline stays version 6.
- **Out of date.** `story_renders.mix_settings` reads the two new settings; they are in `_MIX_CONSTANTS`, and `mix_constant_reasons` compares only keys a render recorded, so a story render never sees them.
- **Settings.** `explainer_music_duck_db` (-22, -40 to -1) and `explainer_music_post_rise_db` (8, 1 to 18) in group `Music`. The Settings page lists them without a frontend change. `DATABASE_STRUCTURE.md`: two rows and a paragraph in the render timeline section.
- **Checked.** A script with stand-in data (not kept) against a copy of `HEAD`: a story's music timeline, recorded constants and music lane FFmpeg arguments are byte-for-byte the same. For an explainer: the duck is -22 dB and held through gaps under 4 s (a 6 s gap is released); a post in a 0.4 s gap gives a rise inset by 0.15 s; a post over speech is cut to the silence; a post in a released gap, and a post with no silence, give no rise; no rise window overlaps speech; the lane arguments hold the rise filter. `_parse_rises` refuses a bad entry; `mix_constant_reasons` flags a changed explainer setting on an explainer render and ignores it on a story render. `ruff check` and `ruff format` pass.
- **Not checked.** `mypy` is not installed in the project's environment, and `render_story` cannot be imported outside the containers (no database driver), so `_parse_rises` was run by itself and the rest of that file by reading and `ruff`. `build_plan` was not run on a whole stand-in story. The owner's listen is open: after a rebuild, render project 94 and judge the voice clear throughout, no pumping between sentences and the posts audible, then tune the two settings by ear.

### EXM-006 — The project's sound effects: switch and generation

**Status:** Not started

**Objective.** Let a continuous explainer have two sound effects of its own, a graphic sound and an evidence sound, made once and reused at every graphic and evidence moment of that project.

**Current state.**
- `project` has `music_enabled`, `ambience_enabled`, `graphics` (fixed at creation) and `evidence` (changeable). The create form is `frontend/src/components/projects/CreateProjectModal.tsx` and the settings form `ProjectSettingsForm.tsx`; the checks are in `services/projects.py` and `api/projects.py`.
- A Music Lab run (`lab_music_run`, kind `sfx`, model `stable-audio-3`) is what a music take already is: `music_takes` makes a lab run plus a `music_take` row, measures it (`audio_measurements`), checks it, and selects the first take that passes.
- Graphic shots (`scene_timeline.GRAPHIC_SHOT_TYPE`) and evidence shots (`EVIDENCE_SHOT_TYPE`) are shots of a cut plan; evidence cards are laid over other shots (`services/evidence_cards.py`).

**Scope.**
- A new project column `sound_effects` (boolean), in a new migration: on by default for a new continuous explainer, off for every existing project, and only allowed on a continuous explainer. It can be changed at any time; changing it makes the render out of date and nothing else.
- A new pipeline step "Make the sound effects", skipped as complete when the switch is off, and for a project with neither graphics nor evidence on. It has two targets, `graphic` and `evidence` (a target is skipped when its feature is off).
- For each target, several Stable Audio 3 takes from a fixed brief (short, soft, no tonal content that could clash with the score), each a lab run belonging to the project. Each take is measured and checked: length under a limit, no clipping, sound starting at once, one clear loudest moment. The first take that passes is selected (XM-11).
- The owner can listen to the takes, select one, reject one with a note (a new wording from the note, as MD-23), lock the selected one, or make the sound again. Nothing makes a sound effect out of date by itself.
- The sounds belong to the project and are deleted with it (`services/project_deletion.py`). They are not listed for any other project.
- **Planning decides:**
  - the storage: a new small table (project, role, lab run, selected by, rejected, locked), or `music_take` rows with a role and no cue;
  - whether the brief is fixed text, or written once by the model from the Story Bible's tone (with the palette of EXM-002 when music is on);
  - the number of takes per sound (a setting, or the existing `music_cue_wordings`) and the check's limits;
  - whether the project's sound takes appear in the Music Lab list, or only on the project's board;
  - what the step needs (nothing, or the Story Bible for the brief).

**Out of scope.** Placing the sounds in the render (007).

**Dependencies.** EXM-001 passed (its sound effect part).

**Expected outcome.** A new continuous explainer with graphics or evidence on gets a selected graphic sound and evidence sound, which the owner can listen to and change.

**Verification criteria.**
- A new continuous explainer stores the switch on; a story and an existing project have it off and cannot turn it on unless they are a continuous explainer.
- The step makes the takes of each needed sound, selects the first passing one, and is skipped when the switch is off.
- Deleting the project deletes the sound rows and files.
- Standard checks.

**Completion checklist.**
- [ ] Migration, project checks, create and settings forms
- [ ] Step, takes, check and selection, owner actions on the board
- [ ] Deletion with the project
- [ ] Docs (`DATABASE_STRUCTURE.md`), standard checks

### EXM-007 — Sound effects in the render

**Status:** Not started

**Objective.** Play the project's graphic sound at every graphic shot and its evidence sound at every evidence shot and card, subtly, placed by code.

**Current state.**
- `services/story_render_plan.py` (timeline version 6) has a `sounds` music lane (`LANE_SOUNDS`) that only music placement fills, and only when music is on. A sound bite shot added keys to a shot's entry without changing the version (SB-008).
- The render job mixes the lanes with `amix normalize=0` before the final loudness.
- Evidence cards (`evidence_cards.place_cards`) have their start on the scene's timeline; a claim whose first word is on a graphic gets a source line, not a card.

**Scope.**
- When `sound_effects` is on and a sound is selected, the render plan adds a sound effect at:
  - the first frame of every graphic shot (the graphic sound);
  - the first frame of every evidence shot, and the start of every evidence card (the evidence sound).
- Each sound's loudest moment (from its measurement) lands on that moment, so a whoosh peaks as the picture appears. It is cut off at its own length, faded in and out over a few milliseconds, and played at a fixed level well under the voice (a setting).
- A sound effect is never placed inside a sound bite's span, and is skipped when it would start within a set time of the previous sound effect.
- It does not depend on music: it plays with music off. It does not dip the music.
- When the switch is on but a needed sound has no selected take, the render is refused with a clear message, as it is for a missing callout graphic.
- A story's and a `lines` explainer's render are unchanged, and a project with the switch off gives the same FFmpeg commands as before.
- **Planning decides:**
  - the starting level and the shortest spacing (tuned by ear);
  - whether the sound effects are a new key of the timeline (as SB-008 added one, the version unchanged) or a new version;
  - whether scene renders (SCN-003) play them too;
  - whether a graphic shot that directly follows an evidence shot (or the other way round) gets its sound.

**Out of scope.** Sounds on callouts, section titles or B-roll (not wanted, XM-8).

**Dependencies.** EXM-006.

**Expected outcome.** In a render, every graphic and evidence moment gets a soft sound that is noticed without standing out.

**Verification criteria.**
- With stand-in data: the right sound at every graphic shot, evidence shot and card; none inside a sound bite; a sound close after another is skipped; none with the switch off.
- The render's frame count, length and loudness checks pass.
- The owner listens to one render and judges the sounds subtle and on time.
- A story's FFmpeg commands are the same as before.
- Standard checks.

**Completion checklist.**
- [ ] Render plan entries and rules
- [ ] Render job mix and the refusal for a missing sound
- [ ] Docs, standard checks

### EXM-008 — One explainer end to end (owner, not done)

Make a new continuous explainer (for example a short version of project 94's script) with music, sound effects, graphics and evidence on. Check these:

- The Music Bible has a palette and a section arc, and no themes.
- The music plan reads as a section-by-section underscore, with a few posts and drops.
- The voice is clear over the music everywhere, with no pumping between sentences.
- The change from one section's music to the next sounds like one score moving on.
- Adding a graphic shot to one scene and rendering again does not make the music plan or takes out of date, and the new graphic gets its sound.
- Every graphic and evidence moment has a soft sound, and none sits inside a sound bite.
- Compared with a render of the same script on today's music path, the video sounds more like a produced explainer.

**Result (owner fills in):** _To be filled in._

---

## 4. Known risks

- **Fresh music each project means variable quality.** The first passing take is selected (MD-10), which depends on GPU timing, and nothing judges whether it suits the section. The owner's review after music generation and the lock are the protection.
- **The palette may not be followed.** How reliably ACE-Step 1.5 holds a requested tempo and key is not known. If neighbouring cues differ too much, joins are heard (EXM-001 checks this; the fallback is fewer, longer cues joined under the voice).
- **Long section cues may wander or loop** (RM-9 of the music document). The plan's longest cue (EXM-004) and the handles limit this.
- **Sound bites still move the music.** A sound bite changes its scene's clock, so a changed sound bite makes the explainer's music plan out of date (XM-5). This is correct but costs a plan, details and possibly takes.
- **Sound effects can sound cheap.** The level is low, there are only two sounds, and the owner can switch them off per project.
- **GPU load.** Music and sound effect takes share the pool with H3 clips. Starting them earlier (EXM-003) spreads the load, but the total is unchanged.
- **Existing explainer music plans** may read as out of date once after EXM-003, because their recorded inputs differ from the new ones (Planning decides in EXM-003).

---

## 5. Progress log

| Id | Status | Notes |
|----|--------|-------|
| EXM-001 | Passed | Owner trial: two section underscores with one palette, their join, and the two sound effects. Marked complete by the owner 2026-11-27. |
| EXM-002 | Code done, live run pending | Explainer Bible: palette in `sound_world`/`musical_feel`, arc with role and energy, no themes, themes step off. No migration. |
| EXM-003 | Code done, live run pending | Explainer music timeline (voice only, `soundbites`), voice-only plan inputs (`basis: "voice"`), placement on the voice (`voice_sha256`, no shot cuts), step needs per project. No migration. |
| EXM-004 | Code done, live run pending | Explainer plan (score and silence only, `posts`, 120 s cue limit, four explainer critic lenses), cue detail without hits (`swell_in_gaps` from posts), palette in every wording, explainer audit and rewrite. Flag `explainer: true` in the four job inputs. No migration. |
| EXM-005 | Code done, live run pending | Explainer mix: one duck setting (-22 dB) held through gaps under 4 s, a partial rise (+8 dB, setting) inside each planned post, optional `rises` key per sound in the render timeline (version stays 6). Settings `explainer_music_duck_db`, `explainer_music_post_rise_db`. No migration. |
| EXM-006 | Not started | |
| EXM-007 | Not started | |
| EXM-008 | Not started | Owner end-to-end check. |
