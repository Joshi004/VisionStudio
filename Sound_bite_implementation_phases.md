# Vision Studio — Sound Bite Phases

A **sound bite** is a short clip (3 to 15 s) of a real person saying, on camera, the words the script quotes. When an explainer says *At a Stanford economics summit in 2024, Huang offered his audience an unusual wish: "I wish upon you ample doses of pain and suffering."*, the narrator says the lead-in, stops, and the viewer sees and hears Jensen Huang say the quoted sentence himself. The narrator then carries on.

Sound bites are a new kind of evidence (`video`), built on the evidence layer (`Evidence_layer_implementation_phases.md`): the same claims, research round, capture tool, import, review and owner acceptance. What is new is that a sound bite **replaces part of the narration**: the narrator's reading of the quote is cut out of the take at render time and the clip plays in its place, with its own sound. When no clip is accepted, the narrator's reading simply stays.

- The conventions of `Implementation_phases.md` (§3.3 to §3.5, §6) and of `Evidence_layer_implementation_phases.md` apply unchanged. Table and column details go in `DATABASE_STRUCTURE.md`. The newest migration when this was written was `0099`.
- Written 2026-11-21, from a design discussion with the owner, a feasibility check on 2026-11-20 (§2) and the research report `reports/Sound bite editing in explainers.md` (notes in `research_notes/Sound bite editing in explainers/`). Defaults marked *practitioner* or *inference* in §4.7 come from that report and are starting values to tune by ear.

---

## How to use this document

Use the Opus → Sonnet workflow of `Evidence_layer_implementation_phases.md` ("How to use this document"), with this document's name and the prefix **SB-**. Every phase has the same fields: Objective, Current state, Scope, Out of scope, Dependencies, Expected outcome, Verification criteria, Completion checklist and Completion notes. Items marked **Planning decides** are left open on purpose and must be settled in the plan.

**Owner phases** (SB-010) are done by the owner. The agent prepares the steps, runs nothing destructive and no paid call without the owner's explicit go-ahead, and records the results.

### Why some phases can run in parallel

- **One migration.** SB-001 creates every table, column and job type sound bites need (§4.8). Later phases add none, so phases that run at the same time never fight over Alembic revision numbers.
- **Contracts are in this document.** The brief's new field (§4.4) and the `video` result (§4.5) are fixed here, so the capture tool and the skill (SB-003, SB-004) can be built beside the backend phases.
- **The time mapping comes first and alone.** SB-002 changes no behaviour, touches the timing code everywhere, and must be finished before SB-008 starts.

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
- [Appendix A — Nvidia test set](#appendix-a--nvidia-test-set)
- [Appendix B — Progress log](#appendix-b--progress-log)

---

## 1. Goal

For an explainer with a continuous voice and the evidence layer on, the owner:

1. writes the quote into the script as a whole sentence in quotation marks, after a lead-in that names who said it, where and when (§4.2);
2. marks the quoted sentence as a claim and chooses **sound bite** for it. The app checks the lead-in and the quote against the script rules and shows any warning;
3. lets the pipeline run as today: the narrator reads the whole script, quote included, and shot planning waits for evidence;
4. runs the evidence skill in the round folder. For a sound bite claim the agent searches YouTube, finds the moment by its captions, and the capture tool downloads only that part of the video;
5. presses Import: the app checks the files and transcribes each clip with Parakeet, so the exact words are proven by the app, not by the agent;
6. reviews each clip with its context: confirms the speaker, the recording date and the meaning, adjusts the start and end on word boundaries, and accepts or rejects it;
7. presses Continue: the cut plan gives each accepted sound bite its own shot on the quote's words, and the render cuts the narrator's reading out and plays the clip, with a lower third, the clip's own captions and the music ducked under it.

A project without sound bites, or with the evidence layer off, renders exactly as today.

---

## 2. Current state

What exists and is reused:

- **The evidence layer** (`Evidence_layer_implementation_phases.md`). Claims are `{id, origin, start, end, text, hint, kind_hint, reason, kept}` code-point ranges of the script (`services/evidence_claims.py`); GLM proposes more (`evidence_claims_writer.py`, `kind_hint` includes `quote`). The brief (`brief/claims.json` v1), the round folder, the result (`results/<claim>/result.json` v1, where `kind` `video` is reserved), the untrusted import (`evidence_import.py`, `evidence_checks.py`), the review (`evidence_review.py`, `EvidenceReview.tsx`), evidence clips (`evidence_clip`, `render_evidence_clip`), cards and the Sources section of the YouTube description (`youtube_sources.py`).
- **The capture tool** (`tools/evidence-capture`, a uv project run on the Mac). Commands `web`, `pdf`, `report`, `remove`, `validate`, `draw`. Only the tool writes files, only inside `results/<claim>/`. **The skill** (`tools/evidence-skill/visio-evidence/`) forbids cookies, logins and any command other than the tool.
- **Speech recognition.** Parakeet on the GPU server (`providers/transcriber.py`, `POST /v1/parakeet/transcribe`, upload then poll), used by `jobs/time_speech_words.py`, whose heard words are matched to script words by `services/word_timings.align` (70 % threshold).
- **The clock.** One continuous take per scene; its word timings drive everything after it (`Explainer_continuous_voice_phases.md` F-4). `scene_timeline.build_cut_timeline` maps take time to scene time with one fixed offset (`lead_in_s`, 0.0); `story_offsets` adds the scenes up; `story_render_plan._build` freezes the timeline (version 6) on the render job.
- **Copies of the clock.** At least six places redo "take time + `lead_in_s`" themselves (survey of 2026-11-20): `shot_plans._claim_times` and `_split_shots`, `generation_requests._window_start` and `_take_window` (H3 presenter windows, stored on the request and the job), `shot_graphics._prepare` (`shift_s`, `voice_offset_s`), `story_renders._voice_units`, and `shot_graphic_brief_writer`. Captions and callouts are timed from the start of a speech unit plus word offsets, and a unit can hold several sentences.
- **The voice in the render.** `story_render_plan.voice_pieces` already splits a take into pieces with `in_sample` (place in the take) and `start_sample` (place in the story), today with the same difference for every piece. A presenter shot set to its clip's own voice mutes the take for its span with a crossfade (`VOICE_FADE_S`), gain-matched to the take (`voice_match_gain`) and not ducked (`render_story.clip_audio`).
- **Music** ducks under `speech_spans` (narration, voice and dialogue) and may swell in gaps of `MUSIC_GAP_RELEASE_S` (1.0 s); `music_placement._timeline_hash` includes shot frames and voice times, so a changed timeline puts the placement out of date.
- **Overlays.** The motion service draws transparent ProRes 4444 overlays (callouts, evidence cards) laid over shots by `render_story` (`Overlay`).

**The feasibility check of 2026-11-20** (round 84, the Costco explainer; nothing kept):

- `yt-dlp` 2026.10.26, run with `uvx` on the Mac, searched YouTube (`ytsearch`) with no key and no block. **Top results were other explainer channels retelling the story**; official footage (Georgetown University, CNBC, WSJ, Notre Dame) needed targeted searches.
- Captions only (`--skip-download --write-auto-subs`, json3): about **86 % of words carry their own start time**, none an end time. The quotes were found by keyword (Sinegal at 37:58 of a 57-minute Georgetown talk; Jelinek at 8:02 of a CNBC interview).
- **Section download works:** `--download-sections "*37:50-38:22"` fetched 32 s (720p, 4.4 MB) in about 26 s; the CNBC section came at 1080p.
- **It is fragile:** every call warned that no JavaScript runtime was found and that YouTube's "n challenge solving failed: some formats may be missing". It still worked.
- The captions do not mark a change of speaker: the Jelinek quote is followed at once by the interviewer.
- **Parakeet was not checked**: the cluster's transcription queue was stuck that day (the app's own `time_speech_words` jobs were "queued on cluster" too).

What does not exist: anything that downloads video; a `video` result; a transcription of an evidence file; a way to change the length of a scene's narration; a shot that carries a real person's voice.

---

## 3. Decisions

| # | Decision |
|---|----------|
| SB-1 | Sound bites are **evidence of kind `video`**, for the projects the evidence layer serves (continuous-voice explainers, EV-1) and only with the evidence switch on. There is no separate project switch. |
| SB-2 | **Replace mode only** in this document. The narrator's reading of the quote is cut out of the take at render time and the clip plays in its place. When no clip is accepted, nothing is cut: the narrator's reading is the fallback. Clip-first patterns (cold open, tease and back-ID, montage) need an insert mode and are later work (SB-011). |
| SB-3 | A sound bite is a **claim the owner marks as a sound bite** (`want: soundbite`). Its words must be one or more whole sentences inside quotation marks. GLM may propose quotes; only the owner turns a claim into a sound bite. |
| SB-4 | **Script rules** (§4.2) are checked when a claim is marked and when the script changes. Only "the quote is whole sentences in quotation marks" blocks marking, because the cut needs it. The others (lead-in reads complete without the quote, no parroting, no filler hand-off, attribution before the quote) are warnings the owner sees. |
| SB-5 | **Research stays manual on the Mac** (EV-4, EV-11). The capture tool gets a `video` command that downloads only a padded window of the video. No cookies, no logins, no account. A video the tool cannot fetch is `blocked`. |
| SB-6 | **The app proves the words.** On import, the backend transcribes every clip with Parakeet and compares the heard words with the claim. The agent's quote and YouTube's captions only find the moment. Each clip gets a **fidelity class**: `exact`, `near`, `paraphrase`, `mismatch`. Only `exact` and `near` can be shown. |
| SB-7 | **Real speech is never altered.** One continuous span of one source; no internal edits, no speed or pitch change, no AI clean-up of words. Only the start and end can be moved, and only onto word boundaries. |
| SB-8 | **Nothing reaches the video without the owner** (EV-8). For each clip the owner confirms the speaker, the recording date (not the upload date) and that the meaning holds in context, and for a standard-licence clip writes a one-line rights note. |
| SB-9 | **The script is never rewritten by the app.** A `near` clip is shown with the differences. The owner may edit the script, which makes speech for that scene again, as any script edit does. |
| SB-10 | **On screen and in the mix:** the speaker's face, a lower third (name; role at the time · venue, month year), a source credit, captions from the clip's own words in a speaker colour, the music ducked deeper or dropped. **Voices never overlap**: the narrator is silent for the whole clip. |
| SB-11 | **One time mapping first.** Before any sound bite reaches the timeline, every copy of "take time to video time" is replaced by one shared mapping (SB-002), checked to change nothing for existing projects. |
| SB-12 | **Sensitive context is the owner's call, helped by flags.** A clip near words such as "resigned", "allegation" or "investigation" gets a flag that must be acknowledged, and admission-like words in such a clip ("mistake", "sorry") are flagged again. |
| SB-13 | **Rights are the owner's judgement**, not legal advice. The app records the licence and the rationale, prefers official channels in the skill, and puts a link to the exact moment in the description's Sources section. |

---

## 4. Design

### 4.1 How it works

```text
owner writes the quote as whole sentences after a lead-in                    §4.2
 -> marks the quote as a claim, chooses "sound bite"; script rules checked     SB-005
 -> speech, word timings and the rest run as today
 -> step "Gather the evidence": the brief carries want=soundbite             SB-001, §4.4
 -> agent in the round folder: search YouTube, find the moment in captions,
    TOOL video downloads a padded window                                      SB-003, SB-004
 -> owner presses Import: files checked, each clip transcribed by Parakeet,
    fidelity class, proposed in and out points, flags                         SB-006
 -> owner reviews: speaker, date, meaning in context, trim, accept            SB-007
 -> owner presses Continue
 -> cut planning puts a sound bite shot on the quote's words                  SB-008
 -> the timeline replaces that span of the take with the clip               SB-002, SB-008
 -> the render plays the clip with its sound, lower third, captions, music duck   SB-009
```

### 4.2 The script pattern

The research is unanimous: the narrator **sets the clip up and does not say its words first**. The lead-in gives who, where, when and why it matters; the clip carries the words; the line after the clip reacts, echoes one word or moves on. Replace mode produces exactly this, as long as the lead-in still reads as a complete set-up once the quote is lifted out.

| Rule | Checked how | Example |
|---|---|---|
| The quote is one or more whole sentences in quotation marks | Blocks marking | Not replaceable: `in his words, the gaming cards "would carry the burden of CUDA"` |
| Attribution comes before the quote | Warning | Good: `At a Stanford economics summit in 2024, Huang offered an unusual wish: "…"` |
| The lead-in reads complete without the quote: it ends in a colon or a full stop, never in "that" or a dangling "said," | Warning | Bad: `Huang said that "…"` |
| The lead-in shares no run of three or more content words with the quote | Warning | Bad: `He wished them pain and suffering: "I wish upon you ample doses of pain and suffering."` |
| No filler hand-offs ("had this to say", "said the following", "tells us more") | Warning | — |
| Quote emotion, opinion or proof; numbers and facts belong to the narrator | Owner's judgement (shown as a hint) | Don't make "Revenue grew 200 %" a sound bite |
| The sentence after the quote adds something; it may echo one word, never restate the clip | Owner's judgement | `Pain and suffering. He meant it.` |

The fallback (no clip accepted) reads naturally because attribution is at the start: the narrator says the lead-in and then the quote, as ColdFusion and many others do.

### 4.3 Where it sits in the pipeline

No new step. Sound bites use the evidence steps:

- **`evidence`** (EVD-003) is complete only when the review is done, as today. A sound bite claim is a claim like any other.
- **`shot_plans`** already needs `evidence`. It gets the accepted sound bites and must put each on its quote's words (SB-008).
- **`evidence_clips`** (EVD-009) makes the sound bite's overlay (lower third and credit) and its trimmed, gain-matched clip (SB-009).
- **`scene_render`**, **`music_placement`** and **`render`** already need `evidence_clips`.

Speech, word timings, presenter clips and everything before shot planning are untouched: in replace mode the narrator reads the full script.

### 4.4 The brief (`brief/claims.json`, version 2)

One field is added to each claim, and the version goes to 2 so the skill knows to read it:

```json
{
  "id": "c4",
  "origin": "owner",
  "text": "I wish upon you ample doses of pain and suffering.",
  "sentence": "...",
  "context": "...",
  "hint": "SIEPR Economic Summit, March 2024",
  "kind_hint": "quote",
  "want": "soundbite",
  "speaker": "Jensen Huang"
}
```

- `want` is `evidence` (today's behaviour) or `soundbite`. A sound bite claim may also get web or PDF evidence; the agent is told to look for the clip first.
- `speaker` is the owner's name for who says the quote (required for a sound bite).
- The capture tool and the import accept version 1 and version 2. (The tool does since SB-001; the import reads no brief version, so it needs no change.)

### 4.5 The result for a clip (`kind: "video"`)

A piece of evidence of kind `video` in `result.json` (still version 1 of the result; the kind was reserved):

```json
{
  "id": "e1",
  "kind": "video",
  "relation": "supports",
  "source_tier": "primary",
  "source": {
    "url": "https://www.youtube.com/watch?v=...",
    "final_url": "...",
    "publisher": "Stanford SIEPR",
    "title": "...",
    "published": "2024-03-20",
    "retrieved_at": "2026-11-22T10:02:11Z",
    "archive_url": null
  },
  "quote": "the agent's copy of the words as the captions have them",
  "what_it_says": "...",
  "capture": {
    "tool": "visio-evidence-capture",
    "tool_version": "2",
    "video_id": "11 characters",
    "channel": "channel name",
    "channel_id": "UC...",
    "upload_date": "2024-03-21",
    "licence": "standard | creative_commons | unknown",
    "duration_s": 3412.0,
    "window": {"start_s": 1225.0, "end_s": 1257.0},
    "quote_at_s": {"start": 1232.4, "end": 1238.1},
    "media": "e1.mp4",
    "captions": "e1-captions.json",
    "context_text": "e1.txt",
    "video_px": [1920, 1080],
    "sha256": {"e1.mp4": "...", "e1-captions.json": "...", "e1.txt": "..."}
  }
}
```

- **`window`** is the downloaded part of the video, in the source's seconds: the quote plus at least 15 s on each side (for the review's context), at most 90 s in total. **`quote_at_s`** is where the captions put the quote, a first guess only.
- **`captions`** is YouTube's caption track for the window, as downloaded; **`context_text`** is the plain text of the window's captions.
- **`published`** is the **recording** date when the agent knows it (the talk, the interview), not the upload date. The agent says how it knows in `what_it_says`. `upload_date` is the tool's.
- The tool re-encodes the window so it starts on the first frame asked for (a section download otherwise starts on the previous keyframe, which can be 10 s early).

### 4.6 The checks on import

In addition to checks 1, 2 and 6 of the evidence layer (shape, files, the owner):

1. **Media.** `e1.mp4` is probed with `ffprobe`: H.264 or another codec the render reads, one video and one audio stream, the duration matches `window` within 0.5 s, at most 90 s and the size limit.
2. **Heard words.** The clip's audio is transcribed by Parakeet (a new GPU job, like `time_speech_words`). The claim's words are aligned to the heard words with `word_timings.align`'s matching.
3. **Fidelity class.** `exact` (same words after normalising filler words), `near` (contractions, a dropped or added filler, a small word), `paraphrase` (meaning only), `mismatch`. Thresholds: **Planning decides**. `paraphrase` and `mismatch` make the piece unusable as a sound bite (it may still be shown as context).
4. **Proposed trim** (§4.7): in point before the first quote word, out point after the last, snapped to the quietest point in the gap. **No clean gap** at either edge (another word within 80 ms, or the gap louder than the speech floor) is a warning, and the review must change the trim before accepting.
5. **Flags** (never refusals): a "but", "however", "I was wrong" or similar within two sentences after the out point; the words "he said", "they say", "imagine" or laughter near the quote (reported speech, a hypothetical, a joke); a recording date missing or later than the upload; a channel that is not the publisher's own; length outside 3 to 15 s; a sensitive word in the script within 20 s of the quote (SB-12).

### 4.7 The replace on the timeline, and the defaults

**Replace.** A sound bite shot covers the quote's words in the take, from the cut before its first word to the cut after its last (`cut_time` is the middle of the gap between two words, so no word is split). For a scene take with sound bite shots `i`, each over the take span `[s_i, e_i]` and with a clip of length `L_i`:

```text
scene_time(t) = lead_in + t + sum over bites with e_i <= t of (L_i - (e_i - s_i))
```

Take times inside `[s_i, e_i]` have no scene time: nothing of the take plays there. Every consumer gets times only from this mapping (SB-002). Presenter clips never cover a sound bite shot, so their windows in the take are unchanged and no H3 clip is made again. Captions and callouts are placed word by word through the mapping, not from a unit's start; the quote's own narrator captions and any callout on the quote's words are dropped (a warning lists them).

**Defaults** (from the report; *S* sourced, *P* practitioner, *I* inference). Planning of SB-006, SB-008 and SB-009 may change them and records why.

| Setting | Default | Basis |
|---|---|---|
| Clip length | 3–15 s; warn above 12 s | S + I |
| Bites per video | Warn above 4 per 10 minutes, or less than 20 s of narration between two bites | I |
| In point | First word onset − 80 to 150 ms, snapped to the quietest point in the gap | I (Parakeet's ~80 ms grid) |
| Out point | Last word offset + 150 to 300 ms; more slack at the tail than the head | I |
| Picture lead | The clip's picture starts 0.2–0.4 s before its first word, over its own room tone | P + I |
| Return | The narrator resumes 250–500 ms after the clip's last word | P + I |
| Audio edges | 10–30 ms fades on speech edges; 100–250 ms on room tone | I |
| Bite loudness | Static gain so the clip's speech matches the narrator's within ±1 LU; no speed, pitch or word changes | I + SB-7 |
| Music under a bite | At least 20 dB below the bite's speech; ramp from 200 ms before, release over 300–600 ms after | S (W3C) + P |
| Music drop | Per bite, off by default: the music fades out before the bite and comes back after it; at most 2–3 per 10 minutes | P |
| Picture, landscape | The source full frame; a framed card only for sources at or below 480p or with an aspect mismatch | S + I |
| Picture, portrait | A 16:9 window on a blurred copy of the clip; never black bars (face tracking is SB-013) | P |
| Lower third | 0.3–0.5 s after the clip starts, held 4–6 s, gone before the last words; line 1 the name, line 2 "role at the time · venue, month year" | P + S (dating) |
| Source credit | Small, for the whole clip; plus a timestamped link in the description | S + I |
| Captions | The clip's own heard words, in one colour per real speaker, distinct from the narrator, upright (not italic) | S (WCAG, BBC, Netflix) |

### 4.8 What the one migration creates (SB-001)

Planning in SB-001 decides the names. The feature needs:

- `want` and `speaker` on each claim in the claim list versions (they are JSON, so likely no column);
- on `evidence_item`, room for a `video` capture: the stored clip, its captions, its heard words, the fidelity class, the proposed trim and the flags;
- on the owner's review decisions: the chosen in and out points, the confirmed speaker, role, venue and date for the lower third, the acknowledged flags, the rights note;
- `evidence_clip.purpose` may be `soundbite` (the trimmed, gain-matched clip and its overlay);
- the job type for transcribing an evidence clip (paid GPU time, like `time_speech_words`).

---

## 5. Phase overview

| Id | Title | Kind | Hard dependencies | Status |
|----|-------|------|-------------------|--------|
| SB-001 | Tables, contracts and job type | Code | — | Completed (2026-11-21) |
| SB-002 | One time mapping for every consumer | Code | — | Not Started |
| SB-003 | The capture tool's `video` command | Code (Mac) | — | Not Started |
| SB-004 | The research skill for sound bites | Code (Mac) | SB-003 | Not Started |
| SB-005 | Marking sound bites and the script rules | Code | SB-001 | Not Started |
| SB-006 | Importing clips: transcription, fidelity, trim, flags | Code | SB-001, SB-003 | Not Started |
| SB-007 | The review screen for sound bites | Code | SB-006 | Not Started |
| SB-008 | Sound bite shots in the cut plan and the timeline | Code | SB-002, SB-007 | Not Started |
| SB-009 | The sound bite in the render | Code | SB-008 | Not Started |
| SB-010 | The Nvidia explainer end to end | Owner | SB-004, SB-005, SB-009 | Not Started |
| SB-011 | Insert mode: cold open, montage, back-ID | Code, later | SB-010 | Deferred |
| SB-012 | A quote card for the narrator's fallback | Code, later | SB-010 | Deferred |
| SB-013 | Face tracking for portrait | Code, later | SB-010 | Deferred |
| SB-014 | Sharper edges: forced alignment and speaker change | Code, later | SB-010 | Deferred |

**Tracks that can run at the same time:**

- **Timing:** SB-002 alone, now. It is useful even if sound bites change shape later.
- **Mac tools:** SB-003 → SB-004, now. They depend only on §4.4 and §4.5.
- **Backend:** SB-001 → {SB-005, SB-006} → SB-007 → SB-008 → SB-009.

**Progress snapshot:** 1 completed (SB-001).

---

## 6. Phases

### SB-001 — Tables, contracts and job type

**Status:** Completed (2026-11-21)

**Objective.** Create, in one migration, everything sound bites store, and fix the brief's version 2.

**Current state.** Claims are JSON in versioned claim lists (`services/evidence_claims.py`). `evidence_item` stores captures for `web` and `pdf`; `evidence_clip.purpose` is `preview`, `shot` or `card` (migration `0099`). The brief writer is `jobs/write_evidence_brief.py`.

**Scope.**
- Migration `0100` with the needs of §4.8.
- `want` and `speaker` accepted and kept in the claim list; `speaker` required when `want` is `soundbite`.
- The brief writer writes version 2 (§4.4) when any claim is a sound bite, version 1 otherwise, so rounds without sound bites are byte for byte as today.
- The job type for transcribing an evidence clip, registered with no handler yet (SB-006 builds it).
- `DATABASE_STRUCTURE.md` updated.
- **Planning decides:** the names of every column and job type; whether the heard words go in a column or in a stored file.

**Out of scope.** Any screen (SB-005, SB-007); the import of `video` (SB-006).

**Dependencies.** None.

**Expected outcome.** The data can hold sound bites; nothing visible changes.

**Verification criteria.**
- Upgrade, downgrade and upgrade again on a throwaway `DATA_DIR`.
- A brief written for a project without sound bite claims is identical to one written before the phase.
- Standard checks.

**Completion checklist.**
- [x] Migration and models
- [x] Claim fields and brief version 2
- [x] Job type registered
- [x] `DATABASE_STRUCTURE.md`
- [x] Standard checks
- [ ] Owner: real app rebuilt (`docker compose up --build -d`) so `0100` is applied there. The agent did not touch the real app or its database.

**Completion notes** (2026-11-21).
- **Migration `0100`** (`0100_sound_bites.py`, revises `0099`). `job` is rebuilt for the new CHECK, as in `0098`. Downgrade deletes `evidence_clip` rows of purpose `soundbite` or of a `video` item, then the `video` items, then the jobs of the new type; files in `media/` stay.
- **`evidence_item`** (`kind` CHECK now allows `video`). New nullable columns: `video_path`, `video_sha256` (the downloaded window), `captions_path`, `captions_sha256` (YouTube's caption track; the captions' plain text reuses `text_path` and `text_sha256`), `heard_words` (JSON `{text, words: [{text, start, end}]}`, seconds from the start of the window; **in a column, not a file**), `fidelity` (`exact`, `near`, `paraphrase`, `mismatch`; CHECK `ck_evidence_item_fidelity_valid`), `proposed_trim` (JSON `{in_s, out_s, in_clean, out_clean}`), `flags` (JSON `[{code, message}]`, kept apart from `warnings` because each must be acknowledged) and `transcribe_job_id` (FK to `job.id`, `ON DELETE SET NULL`). The transcription results are columns on the item, filled in later by the job (owner's choice at planning). Nothing writes them yet.
- **`evidence_clip.purpose`** may be `soundbite`.
- **Job type `transcribe_evidence_clip`** (a GPU job). In the `job.type` CHECK, `JobType` in `api/jobs.py` and the label "Sound bite transcription" in `jobFormat.ts`; **no handler and no `JOB_TYPE` constant**: SB-006 writes both, sets the restart rule and documents its input and output.
- **Owner's review decisions:** no column. SB-007 adds an optional `soundbite` object to an `items` entry of `evidence_review.content`; the shape is in `DATABASE_STRUCTURE.md` Section 5.
- **Claims** (`services/evidence_claims.py`): `want` (`WANT_EVIDENCE`, `WANT_SOUNDBITE`, `WANTS`) and `speaker` (`SPEAKER_MAX_CHARS` 100) are in `_CLAIM_FIELDS`. A claim stored before the migration has neither key and reads as `evidence` with no speaker (`_CLAIM_DEFAULTS`, applied in `reanchor_claims`); every new version stores both. `is_soundbite(claim)` is the check other code should use. `update_claim(..., want, speaker)` (and `PATCH .../evidence-claims/{claim_id}` with `want` and `speaker`): a sound bite needs a speaker and a claim that is kept and whose words are still in the story; `evidence` clears the speaker; a speaker for a claim that is not a sound bite is refused (422). A new mark and a GLM proposal are always `evidence`. **The rule "whole sentences in quotation marks" is not checked here: SB-005 adds it.**
- **Brief** (`services/evidence_rounds.py`): `BRIEF_VERSION_PLAIN` 1 and `BRIEF_VERSION_SOUNDBITE` 2 replace `BRIEF_VERSION`. When any claim that counts is a sound bite, the brief is version 2 and every entry also has `want` and `speaker` after `kind_hint`; otherwise it is version 1, byte for byte as before. `claim_keys` includes `want` and `speaker`, so changing either (or turning the last sound bite back to evidence) makes the newest round out of date. `jobs/write_evidence_brief.py` needed no change.
- **Capture tool** accepts briefs of version 1 and 2 (`BRIEF_VERSIONS` in `tools/evidence-capture`); anything else is refused. `TOOL_VERSION` is unchanged. The `video` command and the use of `want` and `speaker` are SB-003's.
- **Checked** on throwaway databases (2026-11-21): upgrade, downgrade to `0099` and upgrade again; `alembic check` shows no difference for the evidence tables or `job` (it still lists the older FLOAT/REAL differences of other tables, which are not from this phase). A brief for claims without a sound bite has the same SHA-256 as the one made by the code at `HEAD` (old claims without the new keys, and new claims with `want` `evidence`). Through the API: a sound bite without a speaker, with a blank speaker, on a dropped proposal, or with a speaker on an `evidence` claim gives 422; with a speaker it is stored; `evidence` clears it; claims stored without the new keys read correctly. `make_round` wrote a version 2 brief, the round was current, and a changed speaker made it out of date. The capture tool's `validate` accepts a version 2 and a version 1 round and refuses version 3. `ruff`, `eslint` and `tsc` pass; `schema.d.ts` was regenerated (from the app's own OpenAPI document, not a running server) and differs only by `want`, `speaker` and one description.
- **Not done by the agent:** the real app was not rebuilt, so `0100` is not yet applied to the real database (the owner rebuilds when no job is running; never `down -v`).

### SB-002 — One time mapping for every consumer

**Status:** Not Started

**Objective.** Every place that turns a take time into a scene or story time uses one shared mapping that can later hold replaced spans. No video changes.

**Current state.** §2, "Copies of the clock". `scene_timeline.build_cut_timeline` uses `lead_in_s + t`; at least six other places do the same sum themselves; captions and callouts add word offsets to a speech unit's start; `voice_pieces` keeps one take offset for all pieces of a take.

**Scope.**
- A pure mapping object per scene take: take time to scene time, scene time to take time (for spans that exist), and a list of replaced spans that is **always empty in this phase**.
- Every copy listed in §2 uses it, including the H3 window start (`generation_requests`), `shot_graphics`' offsets, `story_renders._voice_units`, the claim and split times in `shot_plans`, and the graphic brief writer.
- Captions and callouts placed through the mapping word by word, not from a unit's start plus offsets.
- `voice_pieces` reads each piece's story position from the mapping.
- **Planning decides:** where the object lives; whether the frozen timeline's version changes (it should not, as nothing in it changes).

**Out of scope.** Any non-empty replaced span (SB-008).

**Dependencies.** None. Must be completed before SB-008 starts.

**Expected outcome.** One place to change when sound bites arrive; the riskiest part of the feature (presenter windows, captions) is done and proven before any new behaviour.

**Verification criteria.**
- For at least two existing continuous explainers (one landscape, one portrait, one with graphics and callouts): the frozen timeline JSON, the ASS caption file, the H3 request window starts and the music placement hash are **identical** before and after (a one-off script, not kept).
- No H3 request or presenter clip becomes out of date.
- Standard checks.

**Completion checklist.**
- [ ] Mapping object
- [ ] Every copy replaced (list them in the notes)
- [ ] Captions and callouts word by word
- [ ] Identical-output check on real projects
- [ ] Standard checks

**Completion notes.** _To be filled in._

### SB-003 — The capture tool's `video` command

**Status:** Not Started

**Objective.** The agent can capture the moment a person says a quote: the tool finds it in the captions and downloads only that part of the video.

**Current state.** The tool (`tools/evidence-capture`) has `web` and `pdf` captures, a network guard (`netguard.py`), `report`, `remove` and `validate`. The feasibility check (§2) showed `yt-dlp` works for captions and section downloads, with warnings about YouTube's JavaScript challenge.

**Scope.**
- `TOOL video --claim c4 --id e1 --url <youtube address> --quote "<words>" [--near <mm:ss>] --relation ... --tier ... --what-it-says "..." [--recorded YYYY-MM-DD]`.
- Reads the claim's brief entry; refuses unless the claim is `want: soundbite`, or the agent passes `--as-context`.
- Fetches the video's details and its English caption track (manual captions first, then automatic); finds the quote with a loose match (normalised words, a minimum share of words in order); refuses with the nearest caption lines when it is not found, like `web` does.
- Downloads only the window of §4.5 with `yt-dlp`, re-encoded to start on the first frame asked for, at most 1080p.
- Writes the files and the `video` piece of `result.json` (§4.5) with hashes; `validate` checks them.
- Only `youtube.com` and `youtu.be` addresses; no cookies, no login, no account; a refusal by YouTube (bot check, age gate, private, members-only) becomes a clear message the agent reports as `blocked`.
- **Planning decides:** how `yt-dlp` is pinned and updated (it breaks when YouTube changes); whether to install Deno and allow `yt-dlp`'s remote challenge solver from GitHub (more reliable, but it downloads code at run time); the loose-match rule; the size limit.

**Out of scope.** Searching YouTube (the agent searches); transcription (SB-006); videos that are not on YouTube.

**Dependencies.** None (the contracts in §4.4 and §4.5).

**Expected outcome.** A sound bite claim gets a short, verifiable clip with its captions and source details, made only by the tool.

**Verification criteria.**
- Captures of the two clips of the feasibility check (Georgetown, CNBC) and of one Nvidia quote (Appendix A) pass `validate`; the clip starts within one frame of `window.start_s`.
- A wrong quote is refused with nearby caption lines; a private or removed video is refused with a sentence.
- `validate` fails on a changed file (hash), a window over 90 s and a missing caption file.

**Completion checklist.**
- [ ] `video` command, caption search, window download
- [ ] Result and `validate`
- [ ] Refusals
- [ ] `uv` lock updated

**Completion notes.** _To be filled in._

### SB-004 — The research skill for sound bites

**Status:** Not Started

**Objective.** The agent finds the right, original clip, not a retelling.

**Current state.** `tools/evidence-skill/visio-evidence/SKILL.md` and `reference.md` cover web pages and PDFs, with the safety rules that always win.

**Scope.**
- For a `want: soundbite` claim: look for a clip before any page; search YouTube through the web search tool and `site:youtube.com`; prefer the speaker's or event's **official channel** (the company, the university, the conference, the original broadcaster); never an explainer channel retelling the story, a compilation, a re-upload when the original exists, a dubbed or interpreted track, or a host reading the quote.
- Find the recording date (the event's own page, the description) and pass it with `--recorded`; say how it is known in `--what-it-says`.
- Check, from the captions around the quote, that the speaker is not quoting someone else and that the next sentences do not turn the point; say so in `--what-it-says`.
- `not_found` and `blocked` stay good answers; every source looked at and not used is an `--attempt`.
- The safety rules are unchanged. The only new command is `TOOL video`.
- **Planning decides:** the wording; whether the agent may also capture a web page about the same moment (for the description) when the clip is found.

**Out of scope.** Any change to the safety rules or to the import step of the skill.

**Dependencies.** SB-003.

**Expected outcome.** Runs in Cursor and Claude Code capture official clips or say clearly that none was found.

**Verification criteria.** A round with four sound bite claims of Appendix A, run once in Cursor and once in Claude Code: every clip from an official channel or with a reason why not, recording dates given, no explainer channel used.

**Completion checklist.**
- [ ] `SKILL.md` and `reference.md`
- [ ] Installed with `tools/evidence-skill/install.sh`
- [ ] Owner's runs in Cursor and Claude Code

**Completion notes.** _To be filled in._

### SB-005 — Marking sound bites and the script rules

**Status:** Not Started

**Objective.** The owner can turn a quote claim into a sound bite and sees at once whether the script around it will work.

**Current state.** Claims are marked and edited in the story editor (`components/story/EvidenceClaims.tsx`, `api/evidence_claims.py`); GLM's proposals carry `kind_hint`.

**Scope.**
- A "Sound bite" choice and a speaker field on a claim, enabled only when the claim's words are whole sentences inside quotation marks (SB-4).
- The script rules of §4.2 as a pure check on the script and the claim, run on marking and whenever the script changes; warnings shown on the claim, with the offending words.
- GLM's claim proposals may say a quote is a good sound bite (`kind_hint` `quote` is enough; no prompt change unless planning finds one is needed).
- **Planning decides:** the list of content words and filler hand-offs; whether a warning can be dismissed per claim.

**Out of scope.** Rewriting the script for the owner.

**Dependencies.** SB-001.

**Expected outcome.** The owner writes scripts that work whether the clip plays or the narrator reads the quote.

**Verification criteria.**
- The examples of §4.2 give the expected result (blocked, warning or clean).
- Line 95 of the Nvidia script, as written today, cannot be marked (the quote runs into "because…"); the rewrite in Appendix A can, with no warning.
- Standard checks; the browser checked by the owner.

**Completion checklist.**
- [ ] Choice and speaker field
- [ ] Script rules check
- [ ] Warnings in the editor
- [ ] Standard checks

**Completion notes.** _To be filled in._

### SB-006 — Importing clips: transcription, fidelity, trim, flags

**Status:** Not Started

**Objective.** Every imported clip comes with the words the app heard in it, how well they match the quote, a proposed trim and its flags.

**Current state.** `evidence_import.py` and `evidence_checks.py` check `web` and `pdf`. `time_speech_words` is the pattern for a GPU transcription job. **Parakeet on clip audio (keynote rooms, interviews, music beds) has not been tried** (§2).

**Scope.**
- Import of `video` pieces with the checks of §4.6 (media, files, hashes) and the copy into storage under generated names (EV-7).
- The transcription job on each usable clip's audio; its result stored; the claim's words aligned to it.
- The fidelity class; the proposed in and out points (§4.7), snapped to the quietest point using the audio itself, not only the word times; the flags of §4.6.
- A first check on five real clips of different kinds that Parakeet's words and times are good enough. **If they are not, swap or add a model before building on it** (the transcriber is a provider: another model or a forced aligner can sit behind the same job).
- **Planning decides:** the fidelity thresholds; how the quietest point is found (energy over 10 ms frames is the simple choice); the flag word lists; what happens when transcription fails (the piece waits, or is unusable with a sentence).

**Out of scope.** The review screen (SB-007); diarisation and forced alignment (SB-014).

**Dependencies.** SB-001, SB-003.

**Expected outcome.** The review can show, for each clip, what was really said, how it compares with the script, and where the cut would be.

**Verification criteria.**
- The clips of SB-003's verification import with the right fidelity class (one deliberately `near`, one `mismatch` made with a wrong quote).
- Proposed in and out points fall in silence when listened to, for at least four of five clips; the fifth, if not, is flagged.
- A tampered file and an over-long window are unusable with their reasons.
- Standard checks.

**Completion checklist.**
- [ ] Import and checks of `video`
- [ ] Transcription job
- [ ] Fidelity, trim, flags
- [ ] Parakeet check on real clips (result in the notes)
- [ ] Standard checks

**Completion notes.** _To be filled in._

### SB-007 — The review screen for sound bites

**Status:** Not Started

**Objective.** The owner can judge a clip as a journalist would before accepting it.

**Current state.** `EvidenceReview.tsx` shows web and PDF pieces with accept, reject, show and order (EVD-007).

**Scope.**
- A player for the downloaded window with the proposed clip marked; buttons to play the clip alone and with its context.
- The heard words, with the quote's words marked and the differences from the script shown (the fidelity class).
- Trim on word boundaries: move the start or the end word by word; the trimmed length shown, with the 3–15 s limits.
- Fields for the lower third, filled from the capture: name (the claim's speaker), role at the time, venue, month and year. The recording date must be confirmed.
- The flags, each acknowledged before the clip can be accepted; a rights note required for a `standard` or `unknown` licence.
- Accept, reject, show, order, as for other pieces.
- **Planning decides:** whether the player uses the stored clip file directly (an HTML video with start and end times is enough; no render).

**Out of scope.** A rendered preview with the lower third (SB-009 adds it to the same card).

**Dependencies.** SB-006.

**Expected outcome.** Every accepted clip has a confirmed speaker, date, trim and rationale.

**Verification criteria.** On a throwaway backend with the clips of SB-006: trimming, flags, required fields and acceptance behave as described; a clip with an unacknowledged flag or no confirmed date cannot be accepted. The owner opens the screen.

**Completion checklist.**
- [ ] Player and words
- [ ] Trim
- [ ] Lower-third fields, date, flags, rights note
- [ ] Standard checks

**Completion notes.** _To be filled in._

### SB-008 — Sound bite shots in the cut plan and the timeline

**Status:** Not Started

**Objective.** Each accepted sound bite gets its own shot on the quote's words, and the timeline gives that shot the clip's length.

**Current state.** The cut planner plans `evidence` shots from claims mapped onto the take's words, with code checks (EVD-009). Cards and source lines are placed by code on read (EVD-011, EVD-012). The time mapping exists with empty replaced spans (SB-002).

**Scope.**
- A new shot type, `soundbite`, drawn (never H3), from the cut before the quote's first word to the cut after its last. **Planning decides** whether the planner is told it as a fixed shot (and `check_answer` refuses any other placement) or code splits the planned shot after the answer; fixed in the request is the simpler to check.
- The mapping's replaced spans filled from the plan's `soundbite` shots and the accepted clips' trimmed lengths (§4.7).
- Everything that reads times follows: scene totals and story offsets; captions (the quote's narrator captions dropped); callouts on the quote's words dropped with a warning; evidence shots, cards and source lines never over a sound bite; graphic shots never cover a quote that is a sound bite.
- The plan is out of date when a sound bite is accepted, rejected or no longer shown; a new trim changes only the timeline (and so the scene render and the music placement), not the plan.
- **Planning decides:** what happens when the quote's words are inside a graphic shot the owner suggested (the sound bite should win).

**Out of scope.** The clip's sound, picture and overlay in the render (SB-009).

**Dependencies.** SB-002, SB-007.

**Expected outcome.** A frozen timeline in which the narration stops for exactly the clip's length and everything after it moves.

**Verification criteria.**
- On a sample take with two sound bites (one longer, one shorter than the narrator's reading): the scene length changes by the sum of the differences; every caption, callout, card and shot after each bite moves by the right amount; presenter windows in the take are unchanged.
- A project with no sound bites gives the identical timeline (SB-002's check, again).
- Standard checks.

**Completion checklist.**
- [ ] `soundbite` shot type and planner rule
- [ ] Replaced spans in the mapping
- [ ] Captions, callouts, evidence, graphics
- [ ] Out-of-date rules
- [ ] Standard checks

**Completion notes.** _To be filled in._

### SB-009 — The sound bite in the render

**Status:** Not Started

**Objective.** The viewer sees and hears the real person, cleanly, with name, date and source.

**Current state.** A presenter shot on its clip's own voice is mixed with a crossfade and gain match (`clip_audio`, `voice_match_gain`); music ducks under `speech_spans`; motion overlays are laid over shots; `youtube_sources` writes the Sources section.

**Scope.**
- The trimmed clip made at render size by the `evidence_clips` step (an `evidence_clip` with `purpose` `soundbite`): cut on the accepted in and out points, picture lead and room-tone tails of §4.7, static gain to the narrator, short fades; never a speed, pitch or word change. Portrait: the 16:9 window on a blurred copy.
- In the render: the take pieces before and after the bite (from the mapping), the clip with its own sound in between, voices never overlapping.
- The music ducks under the bite at the deeper level; the per-bite music drop (off by default) as a review option; the music placement takes the bite span as speech.
- The bite's captions from its heard words, in the speaker's colour, upright.
- The lower third and the source credit drawn by the motion service as a transparent overlay (like an evidence card), timed as in §4.7; a rendered preview button on the review card.
- The Sources section of the description: the clip's address with its start time (`?t=`).
- **Planning decides:** the speaker colours; the overlay's look (it should follow the graphic theme's accent, like evidence clips); the loudness measure used for the gain match.

**Out of scope.** Face tracking (SB-013); a quote card for the fallback (SB-012).

**Dependencies.** SB-008.

**Expected outcome.** A rendered explainer in which each sound bite plays seamlessly, at the narrator's loudness, with its lower third and captions.

**Verification criteria.**
- A scene render with two sound bites in landscape and portrait: no overlap of voices, no jump in loudness (measured within ±1 LU), the music under the bite at least 20 dB below its speech, the lower third readable and gone before the last words, captions in the speaker colour.
- The description has the timestamped link.
- A full render refuses with a sentence when a sound bite's clip is missing.
- Standard checks, `npm run typecheck` in `motion/`.

**Completion checklist.**
- [ ] Trimmed clip, gain, fades, portrait framing
- [ ] Render audio and music
- [ ] Captions
- [ ] Overlay and preview
- [ ] Description link
- [ ] Standard checks

**Completion notes.** _To be filled in._

### SB-010 — The Nvidia explainer end to end (owner)

**Status:** Not Started

**Objective.** Make the Nvidia explainer with three or four sound bites and judge the feature.

**How:**
1. Rewrite the quotes chosen from Appendix A to follow §4.2; mark them as sound bites.
2. Run the pipeline; research with Cursor or Claude; import; review every clip with its context.
3. Render once in landscape. Before publishing, upload privately to see whether Content ID claims any clip.

**Judge:**
- Does each bite feel like part of the video, or like a jump? Is the narrator's lead-in natural with the quote gone?
- Are the cuts clean at both ends? Did any edge include another voice?
- Did the fidelity class and the flags help, or get in the way?
- How long did research and review take per clip?
- Did Content ID claim anything?

**Dependencies.** SB-004, SB-005, SB-009.

**Result (owner fills in):** _Not started._

### SB-011 — Insert mode: cold open, montage, back-ID (later)

**Status:** Deferred

A clip that plays where the narrator says nothing: a cold open before the title, two or three clips back to back, or a clip followed by the narrator naming the speaker. Needs a script marker with no narrator words to replace, and the mapping's spans with a zero-length take span.

### SB-012 — A quote card for the narrator's fallback (later)

**Status:** Deferred

When a sound bite claim has no accepted clip, the narrator reads the quote; an on-screen card shows it in quotation marks with the speaker, venue and year.

### SB-013 — Face tracking for portrait (later)

**Status:** Deferred

A smoothed crop that follows the speaker's face instead of a window on a blurred copy.

### SB-014 — Sharper edges: forced alignment and speaker change (later)

**Status:** Deferred

Re-align only the two edge words with a forced aligner (about 20 ms against Parakeet's ~80 ms), and run speaker diarisation to flag another voice inside or next to the clip. Both as flags, never as decisions.

---

## 7. Progress tracking

Follow §7 of `Evidence_layer_implementation_phases.md`: when a phase changes status, update its **Status** line in §6, its row in the §5 table and the **Progress snapshot**, and add a row to Appendix B. Write the **Completion notes** before marking a phase Completed. If a phase changes a contract in §4, update §4 too.

---

## 8. Open questions and risks

### 8.1 Open questions

| ID | Question | Default until answered |
|----|----------|------------------------|
| Q-S1 | Should a sound bite be allowed in a scene that a presenter shot on its clip's own voice also covers? | No: the planner keeps them apart. |
| Q-S2 | How many sound bites per video? | Warning above 4 per 10 minutes (§4.7); no hard limit. |
| Q-S3 | When the clip's words are `near`, must the script be edited before rendering? | No; the review shows the differences and the clip's own words are captioned. |
| Q-S4 | Should a sound bite claim also get a web or PDF piece for the description? | Optional; the agent may add one. |
| Q-S5 | Do `yt-dlp`'s JavaScript challenge and its remote solver need to be allowed? | Decided in SB-003 after a week of use. |

### 8.2 Risks

- **YouTube's terms and blocks.** YouTube's terms do not allow downloading except through its own features. `yt-dlp` works today but warns, and breaks when YouTube changes. A blocked clip is a `blocked` claim; the narrator's reading is the fallback.
- **Copyright and monetisation.** Content ID can claim a few seconds of a news or keynote clip; YouTube judges reused content across the whole channel, whatever the licence. Short clips with commentary, from official channels, with a recorded rationale, lower the risk but do not remove it. The owner's judgement, not legal advice; get legal advice before monetising sound bites.
- **Meaning and adjacency.** The worst failures are a trim that cuts before the speaker's "but", and a harmless line placed where it reads as an admission (the BBC Panorama case of 2025). The flags help; the owner's review with context is the guard.
- **The Nvidia resignation section.** No keynote clip near narration about the allegations; Huang's written statement is narrator-read with attribution. Re-check the facts before publishing (House sessions on 1–2 December 2026).
- **Transcription quality.** Parakeet's word times are on an ~80 ms grid; keynote audio has applause and music. SB-006 checks real clips first and may swap or add a model.
- **The time mapping.** A missed copy of the clock breaks lip sync or regenerates paid H3 clips. SB-002 is done and proven alone, with identical-output checks.
- **AI disclosure.** An AI narrator over unaltered clips is not on YouTube's list of altered content; a photorealistic AI presenter may be. Ticking YouTube's AI-use box is the safe default.

---

## Appendix A — Nvidia test set

From `explainer_scripts/nvidia/script.txt`. **None has been searched for on YouTube yet**, except that the research found the first one (an excerpt, not yet the official upload). SB-004 and SB-010 confirm each.

| # | Script line | Quote | Notes |
|---|-------------|-------|-------|
| 1 | 95 | "I wish upon you ample doses of pain and suffering." | Stanford SIEPR Economic Summit, March 2024. In the audio it follows a false start; trim at the clean restart. Today's line cannot be replaced (the quote runs into "because…"). Rewrite, for example: *At a Stanford economics summit in 2024, Huang told his audience that character comes from setbacks, and then offered them an unusual wish: "I wish upon you ample doses of pain and suffering."* |
| 2 | 15 | "I used to be a dishwasher here. …" | Said at a Denny's; find the official video. The quote is a joke: check that it plays as one. |
| 3 | 39 | "Our company is thirty days from going out of business." | The script presents it as a staff-meeting sentence; a clip of Huang recounting it needs a lead-in that says so. |
| 4 | 97 | "Where there are no customers, there are also no competitors." | Today embedded mid-sentence ("he says"); rewrite as a whole sentence after the lead-in. |
| 5 | 87 | Larry Ellison: "me and Elon begging Jensen for GPUs. …" | Find the original event; check the full context (it is a joke). |
| — | 71 | Sutskever: "and it felt like a miracle" | Partial quote: not replaceable unless rewritten. |
| — | 29 | Irimajiri's words | Said in Japanese: no interpreted or dubbed audio (§4.6); stays narrator-read. |
| — | 105 | The resignation | No clips (§8.2). |

---

## Appendix B — Progress log

| Date | Phase | Change |
|------|-------|--------|
| 2026-11-21 | — | Document written. |
| 2026-11-21 | SB-001 | Completed: migration `0100`, claim `want` and `speaker`, brief version 2, job type `transcribe_evidence_clip` (no handler), capture tool accepts brief versions 1 and 2. |
