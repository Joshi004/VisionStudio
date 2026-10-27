# Vision Studio — Explainer Mode Phases

An **explainer** is a project made of one script that one presenter speaks from start to finish. The presenter is a Character Lab character. In some passages the presenter is on camera, and in the others their voice is heard over B-roll.

- This document records what was decided, how it was built, what the owner still has to check, and what is known to be weak.
- The conventions of `Implementation_phases.md` (§3.3 to §3.5, §6) apply unchanged. Table and column details are in `DATABASE_STRUCTURE.md` (migration `0072`).
- Written 2026-10-27, from the plan "Explainer mode: presenter plus B-roll".

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

**Result (owner fills in):** _not yet run_

### EXPLAINER-006 — Run one explainer end to end (not done)

Make one explainer of about 2 minutes (finance or AI), once with a library set and once without. Check these:

- Discovery holds only the presenter and the set.
- No relations job runs and no narrator design job runs.
- The events are only narration, dialogue and pause.
- Presenter shots use the reference route with `fully_copy`. B-roll shots use the text route.
- The rendered video alternates between the presenter and B-roll, in one voice.

**Result (owner fills in):** _not yet run_

---

## 4. Known limits

- How well H3 keeps the presenter's face the same over many presenter shots is not tested.
- B-roll may still show text or invent a diagram, because the prompt can only ask H3 not to.
- `match_audio_duration` is left false for story shots. The audio is made as long as the clip by the placement, so the clip length is still decided by the shot plan.
- `shot_cut_repair_writer` has no explainer note in its instructions. It only has the code check, so a repair that adds a character to B-roll is refused and not corrected by the model.
- There are no automated tests, as asked. The changes were checked by running the code on throwaway data (migration up and down, project creation refusals, fixed discovery items, the FFmpeg filter, the planner and prompt writer on a presenter shot and a B-roll shot).

---

## 5. Progress log

| Id | Status | Notes |
|----|--------|-------|
| EXPLAINER-001 | Owner action | See §3. |
| EXPLAINER-002 | Done | Migration `0072`. |
| EXPLAINER-003 | Done | |
| EXPLAINER-004 | Done | Story prompts checked to be unchanged. |
| EXPLAINER-005 | Done | Not run against the GPU server. |
| EXPLAINER-006 | Owner action | See §3. |
