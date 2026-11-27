# Vision Studio — Footage B-roll Phases

**Footage** is real picture shown full screen while the narrator talks: a few seconds of an event from an official YouTube channel, a press photo, a web page scrolled to the paragraph the script talks about, a page of a PDF, or a file the owner made (a screen recording of their own code). When an explainer says *"Prime Minister Narendra Modi met the US President at the White House"*, the viewer sees the two leaders shake hands while the narrator's sentence plays on. Footage is not proof. It supports what is said and makes the video more interesting to watch.

Footage follows the shape of the evidence layer (`Evidence_layer_implementation_phases.md`): the owner marks words, GLM proposes more, a research agent finds material with a capture tool in a round folder, the app imports and checks it, and the owner reviews it. What is different:

- **It is loosely tied to the words.** There is no quote to find. The agent looks for a picture that fits the owner's note ("the handshake, both leaders, flags behind"). Finding nothing is a fine answer: the shots already planned simply stay.
- **It is laid over the shots that are already there**, like a graphic overlay (`Graphic_overlays_implementation_phases.md`). Code places it on read, the shot plan never changes, and no H3 clip is made again because of it.
- **The narration and the timeline never change** (background mode). Footage between words, where the narrator pauses, is later work (FTG-015).

- The conventions of `Implementation_phases.md` (§3.3 to §3.5, §6), `Evidence_layer_implementation_phases.md`, `Sound_bite_implementation_phases.md` and `Graphic_overlays_implementation_phases.md` apply unchanged. Table and column details go in `DATABASE_STRUCTURE.md`. The newest migration when this was written was `0105`.
- Written 2026-11-28, from a design discussion with the owner. The facts about YouTube's preview pictures in §2 were measured that day.

---

## How to use this document

Use the Opus → Sonnet workflow of `Evidence_layer_implementation_phases.md` ("How to use this document"), with this document's name and the prefix **FTG-**. Every phase has the same fields: Objective, Current state, Scope, Out of scope, Dependencies, Expected outcome, Verification criteria, Completion checklist and Completion notes. Items marked **Planning decides** are left open on purpose and must be settled in the plan.

**Owner phases** (FTG-013) are done by the owner. The agent prepares the steps, runs nothing destructive and no paid call (no H3 clip, no model call on a real project) without the owner's explicit go-ahead, and records the results.

### Why some phases can run in parallel

- **One migration.** FTG-001 creates every table, column and job type footage needs (§4.12). Later phases add none, so phases that run at the same time never fight over Alembic revision numbers. If a later phase still needs one, it takes the next free number and says so in its notes.
- **Contracts are in this document.** The folder (§4.3), the brief (§4.5) and the result (§4.6) are fixed here, so the capture tool and the skill (FTG-008 to FTG-010) can be built beside the backend phases.
- **The placement is pure.** FTG-004 needs only the timeline, the take's words and the pieces to show, so it can be built beside FTG-002 and FTG-003.
- **A first slice without research.** FTG-001 → FTG-002 → FTG-003 → FTG-005 → FTG-006 (with FTG-004 beside them) puts the owner's own files on video before any research exists. The research track (FTG-007 to FTG-012) then adds the agent's pieces to the same marks, decisions, clips and render.

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
- [Appendix A — Test set](#appendix-a--test-set)
- [Appendix B — Progress log](#appendix-b--progress-log)

---

## 1. Goal

For an explainer with a continuous voice and footage on, the owner:

1. selects words in the story and marks them as **footage**, with a note on what the viewer should see ("the handshake at the White House, both leaders, flags behind") and, if wanted, the kind: a video, a photo or a web page;
2. lets GLM propose other places where real footage would help, each with a note and a reason, and keeps or drops each one;
3. may add a file of their own to a mark (a photo, a screen recording). It is used as it is;
4. for the other marks, opens the round folder on the Mac and runs Cursor or Claude with the footage skill. For a YouTube video the agent looks at YouTube's own preview pictures, then at a sheet of frames half a second apart, and the capture tool downloads only the few seconds chosen, without sound. For a photo, a web page or a PDF the tool captures it;
5. presses Import, then reviews each piece: accepts or rejects it, puts the ones to show in order, and moves a clip's start and end when needed;
6. renders. Each mark's footage is shown full screen over the shots under its words, the narrator keeps talking, and a short credit line names the source.

A project without footage, or with footage off, renders exactly as today. Nothing is planned again and no H3 clip is made again because of footage.

---

## 2. Current state

What exists and is reused:

- **The evidence layer** (`Evidence_layer_implementation_phases.md`). Claims are code-point ranges of `project.script_text` snapped to words (`services/script_ranges.snap_to_words`), stored as versions of a list (`evidence_claim_list`, `services/evidence_claims.py`: `add_mark`, `update_claim`, `remove_mark`, `reanchor_claims`, `counting`, `is_active`; a GLM proposal counts until it is dropped). GLM proposes more in one call (`services/evidence_claims_writer.py`, `jobs/suggest_evidence_claims.py`, the story model `STORY_MODEL_KEY`). The round folder, the brief and delta rounds (`services/evidence_rounds.py`, `jobs/write_evidence_brief.py`; since OVL-006 a round carries only the claims that are waiting), the untrusted import (`services/evidence_import.py`, `evidence_checks.py`: `O_NOFOLLOW`, size limits, magic bytes, SHA-256, files copied to `media/<project_id>/<uuid>.<ext>` with `Storage.save`), the review (`services/evidence_review.py`, `EvidencePanel.tsx`, `EvidenceReview.tsx`) and the API (`api/evidence.py`, `api/evidence_claims.py`).
- **The story box.** `components/story/StoryMarkup.tsx` (layered marks, filters `all`, `evidence`, `graphics`, `decide`), `SelectionToolbar.tsx` (`MarkAction` `evidence`, `graphic`, `both`, with a hint), `EvidenceClaimCard.tsx`, `storyMarks.ts`.
- **The capture tool** (`tools/evidence-capture`, a uv project run on the Mac, `TOOL_VERSION` 2). Commands `web`, `pdf`, `video`, `report`, `remove`, `validate`, `draw`. `netguard.py` allows only public http and https addresses and checks every redirect. `web.py` drives headless Chromium (Playwright): consent banners dismissed, fixed elements hidden, the quote found in the page's text (`find_quote`, nearby text listed on a miss); the screenshot is **one viewport only**, plus a context image of up to 3 viewport heights. Viewports: landscape 1280x720 at scale 2, portrait 360x640 at scale 4. `video.py` and `youtube.py` call yt-dlp through its Python API (no cookies, no cache) and download only a window (`download_ranges`, `force_keyframes_at_cuts`), re-encoded to H.264. **The skill** (`tools/evidence-skill/visio-evidence/`, installed by `install.sh` into `~/.claude/skills`, read by Cursor and Claude Code) allows only the tool, `ls` and two exact `curl` calls.
- **Graphic overlays** (OVL-001 to OVL-007). Suggestions are placed by code on read (`services/graphic_overlays.place_overlays`, pure: runs of words, the middle of the pause before and after, `MIN_S` 3.0, `MAX_LEAD_S` 1.0, `GAP_S` 0.15, `MAX_FRAMES` 720), for a scene whose plan is current. The frozen timeline (version 6) has the optional key `graphic_overlays`; the render lays each as a full-frame H.264 clip at (0, 0) with `render_commands.Overlay`, split across cuts by `render_story.card_overlays`. **The overlays of a shot are stacked callouts, cards, split evidence, graphic overlays**, the last on top. `story_renders.timing_sources` and `next_render_sources` leave overlays out, so the music placement is not touched by them.
- **Drawn shots and H3.** `graphic`, `evidence` and `soundbite` shots (`scene_timeline.DRAWN_SHOT_TYPES`) never go to H3; `shot_definitions.is_drawn_shot` is the one place the H3 chain skips them. Presenter and B-roll shots (`cut_planning_writer.BROLL_TYPES`: `establishing`, `action`, `insert`) are H3 clips.
- **Evidence and sound bite clips.** `services/evidence_clips.py`, `jobs/render_evidence_clip.py`, `services/evidence_clip_layout.py` (camera, badge, stage) and `motion/src/evidence/Evidence.tsx` draw a screenshot with a camera that zooms in and a highlight sweep, at the output size and exact frames; the motion service's `/evidence-renders` takes bodies up to 32 MiB. Sound bite clips are cut and fitted by FFmpeg (`soundbite_render.compose_graph`: `full` for a 16:9 source, `fitted` over a blurred, darkened copy otherwise). `evidence_clips.accent_for` gives the accent colour.
- **Source lines** (EVD-012): a one-line credit drawn by `caption_ass.py` as a `SourceLine` event in the top margin, outside the safe area, from the frozen timeline's `source_lines`.
- **Uploads.** `api/voice_recordings.upload_scene_recording` streams the body (`request.stream()`, `content_length(request)`, the `_UPLOAD_BODY` OpenAPI block). nginx allows 512 MB (`client_max_body_size` in `frontend/nginx.conf`).
- **Sources in the description** (`services/youtube_sources.py`, `youtube_draft._evidence_sources`), project deletion (`services/project_deletion.py` removes `media/<id>/`, then `evidence_rounds.remove_project_folder`), and the board (`services/pipeline_board.py`, `EVIDENCE_STEPS` shown `off` when evidence is not wanted).

**YouTube's preview pictures, measured 2026-11-28** (yt-dlp 2026.10.26 in `tools/evidence-capture`; files in `/tmp`, nothing kept):

- yt-dlp lists YouTube's preview pictures (the ones shown when the mouse is over the progress bar) as `storyboard` formats `sb0` to `sb3`, and downloads them **without any of the video**. They come as JPEG sheets of several frames each.
- YouTube decides the spacing, evenly through the video, not on the cuts:

  | Video | Length | Largest preview | Grid per sheet | One frame every |
  |---|---|---|---|---|
  | Rick Astley music video | 3 min 33 s | 320x180 | 3x3, 12 sheets | about 2.0 s |
  | PM Modi and President Trump joint press meet (White House stream) | 41 min | 159x90 | 5x5, 10 sheets | about 9.9 s |
  | Nvidia GTC 2026 keynote | 2 h 19 min | 320x180 | 3x3, 93 sheets | about 10.0 s |

- All the previews of the first video were **about 300 KB**. A short shot (a 3 s handshake) of a long video can fall between two previews and never be seen.
- The feature is not documented by YouTube and could change. Every call warned that no JavaScript runtime was found, as in the sound bite check (`Sound_bite_implementation_phases.md` §2); it still worked.
- The lowest video stream of the first video (format `602`, 256x144) is about 80 kbit/s, so a minute of it is well under 1 MB.
- **An agent can read a contact sheet.** 36 previews of the first video were laid out as one 1920x1080 image with each frame's time stamped on it, and read back as an image: the shots and their times were clear.

What does not exist: footage of any kind; a mark that is neither a claim nor a graphic suggestion; a capture with no quote; a full-page screenshot; an image download; a video capture chosen by its picture; an upload of a picture or video to a project; a clip laid **under** cards and callouts.

---

## 3. Decisions

| # | Decision |
|---|----------|
| FT-1 | **Background only.** Footage is the picture while the narrator talks. The narration, the take, the timeline, the shot plan and the music never change. Footage between words (the narrator pauses) is FTG-015, later, built with SB-011. |
| FT-2 | **Its own layer, beside evidence.** Footage has its own switch, marks, rounds, items, decisions and clips. It shares the tools, not the data: the capture tool's package and network guard, storage, the motion service, the FFmpeg helpers and the render's overlay path. Reasons: footage has no quote and says nothing about truth, so the evidence checks and statuses do not apply; footage must work with evidence off; and the evidence readers (`shown_claims`, cards, source lines, the Sources section) must never pick up a footage picture by mistake. |
| FT-3 | **The same projects as evidence:** explainers with a continuous voice, because footage is placed on the take's words. A project switch, `footage`, is on by default for a new such explainer and can be changed in settings. With it off, the footage steps are skipped as complete and nothing changes. |
| FT-4 | **Marks.** The owner marks words and writes a note on what to show, with an optional kind (`any`, `video`, `photo`, `page`). GLM proposes more in one call, each with a note and a reason. The owner keeps or drops them; a proposal counts until it is dropped, as for evidence. Footage marks never overlap each other; they may overlap claims, graphic suggestions and sound bites (§4.9 decides who wins). |
| FT-5 | **Two sources.** The owner's own files, added to a mark, and agent research. Research in this document covers YouTube videos, images, web pages and PDFs. Recording a website while it is clicked (FTG-014) and other video sites (FTG-018) are later. |
| FT-6 | **Research stays manual on the Mac** (EV-4, EV-11, SB-5), with the same safety: everything read on the web is data, only the capture tool writes files, no cookies, logins or accounts, and the round folder is untrusted input for the import. A new skill (`visio-footage`) and a new command name of the capture tool. |
| FT-7 | **Video is muted.** A footage clip is downloaded and stored without sound and never plays sound. |
| FT-8 | **The moment in a video is found in three steps:** YouTube's previews (the area, with no download), a sheet of frames 0.5 s apart from a short low-resolution piece (the shot), and a download of only the chosen seconds at full quality (the exact frames). The agent decides what the picture shows, code decides the exact frames from the real cuts, and the owner confirms (§4.7). |
| FT-9 | **Where footage comes from.** In order of preference: the subject's own channel or site (the company, the government, the person), an official press kit or media library, a free-licence library such as Wikimedia Commons (licence recorded), then a news outlet. Never another explainer or commentary channel, a compilation or a re-upload, except a few seconds of a creator's video **when the script talks about that video**. Avoid pictures with an anchor, a ticker, a channel logo or large text on them. The source and licence are recorded for every piece. This is the owner's judgement, not legal advice. |
| FT-10 | **The same event, or file footage.** The agent says whether a piece shows the very event the words describe and gives the event's date. A piece of another occasion is shown as **file footage** in the review, and the owner decides whether the sentence can carry it. Who is in a picture comes from the source's title and description, never from the agent's guess from a face. |
| FT-11 | **Nothing reaches the video without the owner** (EV-8). Every piece the agent found is accepted or rejected by the owner. The owner's own file counts as accepted when it is added, and can be removed. |
| FT-12 | **Footage goes where B-roll could go.** Code places it on read, full screen, over the **presenter and B-roll shots** under its words (§4.9). It never covers a sound bite, a graphic shot, an evidence shot, a graphic overlay or a split stretch. Cards and callouts are laid on top of it. The shots under it are not changed. |
| FT-13 | **On screen.** Narrator captions show as over B-roll. A small credit line names the source for the whole piece. A web page is shown in a browser frame with its address. Callouts are kept over a video or a photo and dropped over a page or a PDF (text over text). No sound effect. |
| FT-14 | **Only the full render waits.** Shot planning, H3 clips, the music and scene renders never wait for footage. The full render waits until every mark that counts has footage or the owner's "no footage here"; "Continue without footage" decides that for every waiting mark at once. |
| FT-15 | **H3 B-roll under footage is still made**, like a planner graphic under an overlay (OVL §4.4). Skipping a clip that footage hides completely is FTG-016, later. |

---

## 4. Design

### 4.1 How it works

```text
create project (explainer, continuous voice, footage on)                    FTG-001
 -> owner marks words as footage, with a note on what to show               FTG-002
 -> GLM proposes more marks (one call); owner keeps or drops each           FTG-002
 -> owner may add a file of their own to a mark (accepted at once)          FTG-003
 -> step "Gather the footage": the app writes the brief for the marks
    that have no file of the owner's                                         FTG-007
      ... every other step keeps going; only the full render waits
 -> owner runs Cursor or Claude with the footage skill in the round folder  FTG-010
      images, pages and PDFs are captured by the tool                        FTG-008
      for YouTube: previews as contact sheets, then a 0.5 s sheet of a
      short range, then only the chosen seconds are downloaded, muted        FTG-009
 -> owner presses Import: files checked and copied into storage             FTG-011
 -> owner reviews: accept, reject, order, move a clip's start and end       FTG-012
 -> on read, code places each mark's pieces over the shots under its words  FTG-004
 -> each placed piece is drawn at its exact length                          FTG-005
 -> the render lays it full screen over those shots; the voice runs on      FTG-006
```

### 4.2 Where it sits in the pipeline

Changes to `services/story_pipeline.STEPS` (step keys and labels are suggestions; planning decides the final names):

- **`footage_marks`**, "Propose the footage" (story-wide, no needs; FTG-002). GLM is asked once, when it has never answered for the project; asking again is the owner's click. Skipped as complete when footage does not apply (FT-3).
- **`footage`**, "Gather the footage" (story-wide, needs `story_bible` and `footage_marks`; FTG-007). No model call. Complete when every mark that counts is **covered**: it has an accepted file of the owner's, or the newest reviewed round that holds it unchanged covers it, or the owner chose "no footage here". It **waits for the owner** (a target with `awaiting`, board status `owner`, a run pause `waiting_for`), like `evidence`. Skipped as complete when footage does not apply or no mark counts.
- **`footage_clips`**, "Draw the footage" (per scene, needs `shot_plans`; FTG-005). One clip for each placed piece of the pieces shown now (§4.9), at its exact length. A scene with nothing placed is complete. It does **not** need `footage`: a scene draws what is shown now, and a mark reviewed later adds clips.
- **`scene_render`** gains `footage_clips` in its needs. **`render`** gains `footage` and `footage_clips`.

`shot_plans`, `music_placement` and every H3 step are unchanged. A project without footage runs exactly as it does today.

### 4.3 The files folder

```text
~/VisioStudioData/
  footage/<project_id>/r<n>/
    brief/
      footage.json                   written by the app (§4.5); the agent only reads it
      README.md                      how to run the agent for this round, with a ready-to-paste prompt
    results/
      <mark_id>/
        result.json                  one per mark (§4.6)
        p1.mp4, p1-strip.jpg         a video piece (no sound) and its strip of frames 0.5 s apart
        p2.jpg                       an image piece (or p2.png)
        p3.png, p3.txt               a web page: the page image and its text
        p4.png, p4.pdf               a PDF page and the PDF
        scans/<video_id>/            the tool's working files for one video, never imported
          info.json                  title, channel, dates, length, chapters, licence
          captions.txt               the English captions as plain text, when there are any
          sheet-01.jpg, ...          contact sheets of YouTube's previews, each frame's time stamped
          fine-<from>-<to>/          a short range at low resolution:
            sheet-01.jpg, ...        frames 0.5 s apart, times stamped
            cuts.json                the exact cut times found in the range
```

The `footage/` folder is never served by nginx. The import copies what it accepts into `media/` under generated names, and leaves the round folder as the agent wrote it, as a record. The owner's own files go straight to `media/`.

### 4.4 The mark

Marks are stored like claims: versions of a list (`source` `manual` or `ai`), each version `{next_id, marks}`, a mark being:

```json
{
  "id": "f3",
  "origin": "owner",
  "start": 1520,
  "end": 1588,
  "text": "Prime Minister Narendra Modi met the US President at the White House",
  "note": "the handshake in the Oval Office, both leaders, flags behind",
  "kind_hint": "video",
  "reason": "",
  "kept": true
}
```

- `start` and `end` are code-point positions of `project.script_text`, snapped to whole words and moved with the words on every read, as claims are (`reanchor_claims`). `words_changed` is worked out on read, never stored.
- `note` is one line of at most 300 characters. It may be empty on an owner's mark (the agent then works from the sentence); GLM must write one.
- `kind_hint` is `any`, `video`, `photo` or `page`. `reason` is GLM's, empty on an owner's mark.
- `kept` is true for the owner's marks, `null` for a GLM proposal not decided and `false` for a dropped one. A mark counts when `kept` is not false and its words are unchanged.
- Ids `f1`, `f2`, ... are stable inside a project: a mark keeps its id while its words are unchanged.

### 4.5 The brief: `brief/footage.json` (version 1)

```json
{
  "schema": "visio.footage.brief",
  "version": 1,
  "round_id": "r1",
  "project": {
    "id": 101,
    "title": "The project's name",
    "topic": "One line from the Story Bible: what the video is about",
    "orientation": "landscape",
    "today": "2026-11-28",
    "language": "en"
  },
  "rules": {
    "max_pieces_per_mark": 3,
    "clip_seconds": {"min": 2, "max": 15},
    "preferred_domains": [],
    "blocked_domains": []
  },
  "marks": [
    {
      "id": "f3",
      "origin": "owner",
      "text": "the words of the script the footage goes under",
      "sentence": "the whole sentence those words are in",
      "context": "the sentences around it",
      "note": "the owner's (or GLM's) note on what to show",
      "kind_hint": "video",
      "needed_s": 4.8
    }
  ]
}
```

- `needed_s` is how long the words take in the scene's take when its word timings exist, otherwise an estimate at 2.5 words a second. It tells the agent how much footage the mark needs.
- A round carries only the marks that are waiting (delta rounds, as for evidence since OVL-006). A mark with an accepted file of the owner's, or decided "no footage here", is not in the brief.
- `orientation` tells the capture tool which viewport to use for pages, as for evidence.

### 4.6 The result: `results/<mark_id>/result.json` (version 1)

```json
{
  "schema": "visio.footage.result",
  "version": 1,
  "round_id": "r1",
  "mark_id": "f3",
  "status": "found",
  "summary": "One or two plain sentences on what was found and what was not.",
  "attempts": [
    {"what": "the search or the address tried", "outcome": "why it was not used"}
  ],
  "pieces": [
    {
      "id": "p1",
      "kind": "video",
      "tier": "official",
      "source": {
        "url": "https://www.youtube.com/watch?v=...",
        "final_url": "the address after redirects, written by the tool",
        "publisher": "The White House",
        "title": "The video's title",
        "published": "2025-02-13",
        "retrieved_at": "2026-11-28T10:02:11Z",
        "licence": "public domain (US government work)",
        "licence_url": null
      },
      "what_it_shows": "Modi and the President shake hands in front of the fireplace.",
      "same_event": "yes",
      "event_date": "2025-02-13",
      "on_screen_text": "none",
      "capture": {
        "tool": "visio-footage-capture",
        "tool_version": "1",
        "video_id": "11 characters",
        "channel": "channel name",
        "channel_id": "UC...",
        "upload_date": "2025-02-13",
        "youtube_licence": "standard",
        "duration_s": 2444.0,
        "window": {"start_s": 129.0, "end_s": 146.0},
        "use": {"start_s": 131.0, "end_s": 144.0},
        "moment_s": 136.5,
        "cuts": [133.21, 139.87],
        "media": "p1.mp4",
        "strip": "p1-strip.jpg",
        "strip_every_s": 0.5,
        "video_px": [1920, 1080],
        "fps": 29.97,
        "sha256": {"p1.mp4": "...", "p1-strip.jpg": "..."}
      },
      "agent_notes": ""
    }
  ]
}
```

- **`status`** of the mark: `found`, `not_found` (nothing usable; `attempts` lists what was tried and `pieces` is empty) or `blocked` (the right source exists but could not be captured: a bot check, a login, an age gate). There is no `partial` or `contradicted`: footage proves nothing.
- **`kind`**: `video`, `image`, `page` or `pdf`.
- **`tier`**: `official`, `press`, `commons`, `news`, `creator` or `other` (FT-9).
- **`same_event`**: `yes`, `no` (file footage) or `unknown`. **`on_screen_text`**, what the agent saw on the picture that is not part of the scene itself: `none`, `small` (a corner logo) or `large` (an anchor, a ticker, a big title).
- **`capture`** is written only by the tool. The times of a video are seconds of the source video: `window` is the part downloaded, `use` the part to use (inside `window`), `moment_s` the instant the agent chose (inside `use`), `cuts` the cut times the tool found inside `window`.
- **An image** has `capture.image`, `image_px`, `page_url` (the page the image was found on) and `sha256`.
- **A page** has `capture.image` (the page from its top, at most `PAGE_HEIGHTS`, 4, screens tall, at the evidence viewports), `image_px`, `viewport`, `text_copy`, `focus_text` and `focus_rects` (`[x, y, width, height]` as fractions of `image`; empty when no focus was asked) and `sha256`.
- **A PDF page** has what the evidence `pdf` capture has (`image`, `page`, `source_copy`, `render_scale`, `text_copy`) with `focus_text` and `focus_rects`.

### 4.7 Choosing the moment in a YouTube video

Three steps, each more precise, so the video is downloaded once and only the seconds that will be used.

1. **The area, to about 10 s, with no download** (`scan`). The tool writes the video's facts (`info.json`: title, channel, upload date, length, chapters, the start of the description, the licence), its English captions as plain text when there are any (they often place a silent moment: the handshake comes right before "Thank you, Mr. President"), and YouTube's largest previews laid out as contact sheets: 36 frames per image, each with its time stamped in a corner. The agent reads the sheets as images and names a range. A whole video is scanned only up to `MAX_SCAN_S` (20 minutes); for a longer one the agent first narrows it down with the chapters, the captions or the description and scans a range of at most 20 minutes.
2. **The shot, to 0.5 s** (`scan --fine`). The tool downloads only that range (at most `MAX_FINE_S`, 90 s) at 360p or less, without sound, and writes sheets of frames 0.5 s apart and the exact cut times (FFmpeg's scene detection). The agent picks the shot and the instant ("the handshake starts at 2:21.5, the leaders turn away at 2:26.0") and checks it for logos, tickers and an anchor.
3. **The exact frames** (`clip`). The tool downloads the chosen part plus 2 s on each side at up to 1080p, video only, re-encoded so it starts on the asked frame, finds the cut times again on this file, and writes a strip of its frames 0.5 s apart for the agent's last look and for the review.

**Who decides what.** YouTube only decides the spacing of its previews (step 1). The agent decides what the picture shows: which shot fits the note, which shots to avoid. Code decides the exact numbers: the cut times, the 0.5 s grid, and the first and last frame of each clip (FTG-005). The owner confirms in the review and can move the start and end.

**The cut rules code applies** when it cuts a video piece to its length on screen (FTG-005). Starting values, to tune by eye:

- A clip never shows a cut in its first or last `EDGE_S` (0.5 s): a flash of the previous shot is the worst mistake. An edge that would is moved to the other side of that cut.
- A clip starts at least `CUT_SETTLE_FRAMES` (3) frames after a cut and ends at least 3 frames before the next one, because some cuts are short dissolves.
- Inside `use`, the clip is placed so that `moment_s` is as near its middle as these rules allow.
- The clip is never slowed down, sped up or looped. When a piece is shorter than its place on screen, the placement gives it less time (§4.9).

### 4.8 The checks on import

The import (FTG-011) checks every piece in this order. The capture tool's `validate` applies checks 1 to 4 too, so the agent can fix problems before the owner imports.

1. **Shape.** The schema and version are known, the round and mark ids match the brief, every value is one the contract allows, the piece ids are `p1` to `p9`, and there are no more pieces than `max_pieces_per_mark`.
2. **Files.** Every file named is inside its mark's folder, a regular file (no link), used once, within its size limit, with the SHA-256 recorded. Its type is checked from its content: MP4 (`ftyp`), JPEG, PNG, PDF, UTF-8 text. `image_px` is the image's real size and at most 40 M pixels. The `scans/` folder is never read.
3. **Video.** FFprobe: exactly one video stream, H.264, `yuv420p`, **no audio stream**, at most 1080 pixels high, the length of `window` within 0.5 s, at most 60 MB.
4. **Places.** `use` lies inside `window` and lasts 2 to 15 s; `moment_s` lies inside `use`; `cuts` are in order and inside `window`; every `focus_rects` entry lies inside its image (at most 12).
5. **Warnings**, never refusals, shown on the review card: low resolution (the shorter side under 720 pixels), file footage (`same_event` `no`), event not checked (`unknown`), text on the picture (`on_screen_text` not `none`), not an official source (`tier` `news`, `creator` or `other`), the YouTube channel not the publisher, licence unknown, focus words not found in the page's text.
6. **The owner** accepts or rejects (FTG-012).

A failure in checks 1 to 4 makes that piece unusable, and the review shows why.

### 4.9 Where footage goes (`services/footage_placement.py`, pure)

Starting values, to tune by eye.

- **Runs.** For each mark that has pieces to show, one run per scene its words are in, from the middle of the pause before its first word to the middle of the pause after its last, on the scene's timeline through `TakeMap`, the way graphic overlays are placed.
- **What it may cover.** Only presenter and B-roll shots (FT-12). The time of a drawn shot (graphic, evidence, sound bite), a graphic overlay or a split stretch is cut out of the run; when that leaves several parts, each is its own run.
- **At least `MIN_S` (2.0 s).** A shorter run grows after its last word, up to the next thing it may not cover or the end of the scene, and then starts up to `MAX_LEAD_S` (1.0 s) earlier. With no room it is not placed, and the board says why.
- **Several pieces in a run** (a montage). The pieces shown are played one after another in the owner's order, with plain cuts. The run is shared out evenly; a video piece gets at most its `use` length, and the time it cannot fill goes to the still pieces after it. Each piece is on screen for at least `MIN_PIECE_S` (1.5 s); pieces that do not fit are left out, the last first, with a note. A boundary between two pieces moves to the middle of the nearest pause between words when one is within 0.5 s.
- **Not enough footage.** When the pieces together are shorter than the run (only video pieces, all short), the run ends when they end and the shot under it shows again.
- **A still piece** (image, page, PDF) is on screen for at most `MAX_PIECE_FRAMES` (720 frames at 24 fps, 30 s), the most the motion service draws. A run of one still piece that is longer is cut at 30 s, with a note.
- **Keys.** A run is `{scene_id}/{first}-{last}`: the scene and the run's first and last word in the take, counted from 1, like an overlay. A placed piece is `{run}:{item_key}`. The same words and the same piece keep the same key, so a clip is not drawn again when other marks change.
- **Worked out on read**, for a scene whose plan is current, from the plan, the timeline, the marks and the pieces shown now. Nothing is stored for the placement.

### 4.10 On screen

| Kind | How it is drawn |
|---|---|
| Video (agent's or owner's) | FFmpeg, from the stored file: the part of `use` that the cut rules of §4.7 give for the piece's length, fitted to the frame, no sound. |
| Image (agent's or owner's) | Motion service: the photo fills the frame with a slow move (a zoom of a few percent, or a pan across a landscape photo in a portrait frame). |
| Page | Motion service: a browser window drawn around the page with the real address in its bar; the page scrolls from its top to the focus, zooms in, and the focus words get the highlight in the accent colour. With no focus, a slow scroll. |
| PDF | Motion service: the page on the plain background, with a zoom to the focus and its highlight. |

- **Framing.** Landscape: a 16:9 source fills the frame, any other shape is fitted over a blurred, darkened copy of itself (`soundbite_render.compose_graph`). Portrait: fitted over the blurred copy by default; the review can choose a crop (`left`, `centre`, `right`) that fills the frame.
- **Credit line.** One line in the top margin for the whole piece, drawn like a source line (EVD-012): `Video: The White House`, `Photo: Jane Doe / Wikimedia Commons, CC BY 4.0`, `PDF: Alibaba Cloud`. A web page shows its address in the browser frame instead. An owner's file shows a credit only when the owner wrote one.
- **Stacking.** In the render, footage is laid first over a shot: footage, callouts, cards, split evidence, graphic overlays. So a card or a callout is always above the footage.
- **Callouts.** The span of a page or PDF piece is added to `graphic_spans`, so a callout that starts there is dropped with the usual warning. A video or image piece keeps callouts, as B-roll does.
- **Captions** are drawn as over B-roll. **Sound:** the footage has none; the shots' own sound and the voice play as without it. **Music** and **sound effects** do not change.

### 4.11 What runs again

| The owner | Runs again | Does not run again |
|-----------|------------|--------------------|
| marks words as footage, or changes a mark's note or kind | that mark's research in the next round, its import and review, then its clips and the renders | the shot plan and everything under it, H3 clips, the music |
| adds a file of their own | its preparation (a video), its clip, the scene render and the video render | the same |
| accepts, rejects, reorders, or moves a clip's start and end | that mark's clips, the renders | the same |
| removes a mark, or chooses "no footage here" | the renders | everything else |
| plans a scene again (for another reason) | the placement is worked out again; clips whose length or key changed are drawn again | research, import, review |

The music placement hashes shot frames and voice times (`music_placement._timeline_hash`), which footage does not change, and the timing sources leave footage out, so it stays current; FTG-006 checks it.

### 4.12 What the one migration creates (FTG-001)

Planning in FTG-001 decides the names and the exact split. Footage needs:

- `project.footage`, a boolean (FT-3);
- the **mark list**: versions of the owner's marks, GLM's proposals and the keep or drop choices, following the provenance convention (`Implementation_phases.md` D-3);
- the **footage round**: one row per brief written, with its mark list version, folder, brief and the brief's hash;
- the **footage import**: one row per import of a round, with the results per mark and the counts;
- the **footage items**: one row per piece, from an import or from the owner (the import NULL), with the mark, the piece id, a stable `item_key`, `origin` (`agent` or `owner`), kind, tier, source, what it shows, same event, on-screen text, the capture, the stored files each with its SHA-256 (video, strip, image, text, PDF), the cut times, usable, checks and warnings;
- the **owner's decisions**, as versions: for each mark, each item's verdict, the ordered list of pieces to show, a moved `use`, the portrait framing, "no footage here", and which rounds were marked reviewed. **Planning decides** between one list for the whole project (the default, because an owner's file has no round) and one per round like `evidence_review`;
- the **footage clips**: rendered videos (a preview, or a placed piece at its exact length), with their look and measured frames, like `evidence_clip`;
- the job types `suggest_footage_marks` (paid model call), `write_footage_brief` (local), `import_footage` (local), `prepare_footage_file` (local: an owner's video made ready) and `render_footage_clip` (local; motion service or FFmpeg).

---

## 5. Phase overview

| Id | Title | Kind | Hard dependencies | Status |
|----|-------|------|-------------------|--------|
| FTG-001 | Footage switch, tables and job types | Code | — | Completed |
| FTG-002 | Marking footage and GLM's proposals | Code | FTG-001 | Completed |
| FTG-003 | The owner's own files on a mark | Code | FTG-002 | Not Started |
| FTG-004 | Placing footage over the shots | Code | — | Not Started |
| FTG-005 | The footage clip and its preview | Code | FTG-003, FTG-004 | Not Started |
| FTG-006 | Footage in the render | Code | FTG-005 | Not Started |
| FTG-007 | The research brief and the waiting step | Code | FTG-002 | Not Started |
| FTG-008 | The capture tool: images, pages and PDFs | Code (Mac) | — | Not Started |
| FTG-009 | The capture tool: YouTube scans and clips | Code (Mac) | FTG-008 | Not Started |
| FTG-010 | The research skill | Code (Mac) | FTG-009 | Not Started |
| FTG-011 | Importing the research | Code | FTG-007, FTG-008 | Not Started |
| FTG-012 | The review screen | Code | FTG-011 | Not Started |
| FTG-013 | The Qwen vs Inkling explainer end to end | Owner | FTG-006, FTG-010, FTG-012 | Not Started |
| FTG-014 | Recording a website | Code, later | FTG-013 | Not Started |
| FTG-015 | Footage between words | Code, later | FTG-013, SB-011 | Deferred |
| FTG-016 | No H3 clip where footage hides it | Code, later | FTG-013 | Deferred |
| FTG-017 | Automatic frame search | Code, later | FTG-013 | Deferred |
| FTG-018 | Footage from other video sites | Code, later | FTG-013 | Deferred |

**Tracks that can run at the same time:**

- **First slice, the owner's files on video:** FTG-001 → FTG-002 → FTG-003 → FTG-005 → FTG-006, with FTG-004 built beside them.
- **Research, backend:** FTG-007 (after FTG-002) → FTG-011 → FTG-012. FTG-011 imports video pieces only once FTG-009 is done.
- **Mac tools:** FTG-008 → FTG-009 → FTG-010 can start at once. They depend only on the contracts in §4.3, §4.5 and §4.6.

**Progress snapshot:** 2 completed (FTG-001 and FTG-002, 2026-11-28; the owner still has to rebuild the real app); 18 phases (13 to build now, 1 later, 4 deferred).

---

## 6. Phases

### FTG-001 — Footage switch, tables and job types

**Status:** Completed (2026-11-28; the owner still has to rebuild the real app so `0106` is applied there)

**Objective.** Create, in one migration, everything footage stores, and the project switch.

**Current state.** The newest migration is `0105_scene_generated_takes.py`; `DATABASE_STRUCTURE.md` stops at `0104`. Job types are a CHECK on `job.type` (`db/models.py`), listed in `JobType` (`api/jobs.py`) and labelled in `jobFormat.ts`. The evidence switch is `project.evidence`, allowed only for a continuous explainer (`services/projects.py`, `EVIDENCE_ONLY_MESSAGE`), on the create form (`CreateProjectModal.tsx`) and in settings (`ProjectSettingsForm.tsx`, `settingsDraft.ts`, `lastProjectSettings.ts`).

**Scope.**
- Migration `0106` with the needs of §4.12.
- `project.footage`: allowed only for an explainer with a continuous voice (its own refusal sentence), on by default for a new one, changeable in settings. Turning it off deletes nothing. Existing projects read `false`.
- The switch on the create form and in settings.
- The five job types, registered with no handler.
- `DATABASE_STRUCTURE.md`: the new tables and column, and the missing paragraph for `0105`.
- **Planning decides:** the names of every table, column and job type; one decision list for the project or one per round (§4.12); whether an item's files are columns (as on `evidence_item`) or one JSON value of `{name: {path, sha256}}`.

**Out of scope.** Any step, screen or job handler.

**Dependencies.** None.

**Expected outcome.** The data can hold footage and the switch is on the forms. Nothing else changes.

**Verification criteria.**
- Upgrade, downgrade and upgrade again on a throwaway `DATA_DIR`.
- A story project and an explainer without a continuous voice refuse the switch with the sentence.
- A project created before the migration reads `footage` false and behaves as before.
- Standard checks.

**Completion checklist.**
- [x] Migration and models
- [x] Switch, refusal and forms
- [x] Job types registered
- [x] `DATABASE_STRUCTURE.md` (with `0105`)
- [x] Standard checks
- [ ] Owner: real app rebuilt (`docker compose up --build -d`, never `down -v`) so `0106` is applied there

**Completion notes.**
- **Migration** `0106_footage_layer.py` (revises `0105`): `project.footage` (BOOLEAN, NOT NULL, default 0), six tables and the `job.type` CHECK rebuilt with the five new types (`_EARLIER_JOB_TYPES` is the list of `0104` plus `write_sound_effect`). The downgrade drops the tables and the column, deletes the jobs of the five types, then restores the old CHECK. Upgrade, downgrade to `0105` and upgrade again ran clean on a throwaway `DATA_DIR`; `alembic check` shows no difference for the footage tables or `project.footage` (it lists only the FLOAT/REAL differences that older tables already have).
- **Tables and models** (`db/models.py`): `footage_mark_list` (`FootageMarkList`), `footage_round` (`FootageRound`, with `mark_list_id`), `footage_import` (`FootageImport`), `footage_item` (`FootageItem`), `footage_decision` (`FootageDecision`) and `footage_clip` (`FootageClip`). `DATABASE_STRUCTURE.md` has them as Sections 4.100 to 4.105, an Update entry for `0106`, the missing one for `0105`, the new rows of Section 4.1 (`footage` and `generated_take_scenes`) and the job types.
- **Job types:** `suggest_footage_marks` (`llm`, `never_rerun`), `write_footage_brief`, `import_footage`, `prepare_footage_file` and `render_footage_clip` (`local`, `start_again`). Added to the CHECK, `JobType` in `api/jobs.py` and `jobFormat.ts`. No handler is registered.
- **Switch:** `FOOTAGE_ONLY_MESSAGE` ("Footage is only for an explainer with a continuous voice.") in `services/projects.py`: `validate_project`, `create_project` (default on for a continuous explainer), `update_project` and `_prepare_value`; `footage` on `ProjectCreate`, `ProjectUpdate` and the project output in `api/projects.py`; the Footage switch on `CreateProjectModal.tsx` and `ProjectSettingsForm.tsx`, with `lastProjectSettings.ts` and `settingsDraft.ts`. `schema.d.ts` was regenerated.
- **Planning decides, decided:**
  - **The owner's decisions are one list for the whole project** (`footage_decision`), because an owner's file has no round. The rounds marked reviewed are recorded inside `content.reviewed_rounds`.
  - **An item's files are columns**, a path and a SHA-256 for each of `video`, `strip`, `image`, `text`, `pdf` and `upload` (the owner's original video, read by `prepare_footage_file`).
  - **Names** are as above. Beyond §4.12, `footage_item` also has `credit` (the owner's credit line), `cuts` (the cut times) and `prepare_job_id`, and two CHECKs: the enum values may be NULL (an agent's value the contract does not allow) and `import_id` is NULL exactly when `origin` is `owner`. `footage_clip.purpose` is `preview` or `piece`, with `placed_key` for a placed piece.
- **Checked** on a throwaway backend: a story project and a lines explainer asking for `footage` get the sentence; a PATCH on a story project gets it; a non-boolean is refused; a new story project reads `footage` false; `validate_project` accepts the switch on a continuous explainer. `ruff check`, `ruff format --check`, `npm run lint` and `npm run typecheck` pass.
- **No deviation** from Scope.

### FTG-002 — Marking footage and GLM's proposals

**Status:** Completed (2026-11-28)

**Objective.** The owner marks words as footage with a note, GLM proposes more, and the owner keeps or drops them.

**Current state.** Claims: `services/evidence_claims.py` (`add_mark`, `update_claim`, `remove_mark`, `reanchor_claims`, `counting`), `api/evidence_claims.py`, `services/script_ranges.py`. The story box: `StoryMarkup.tsx`, `SelectionToolbar.tsx`, `EvidenceClaimCard.tsx`, `storyMarks.ts`, `api/evidenceClaims.ts`. GLM's claims: `services/evidence_claims_writer.py` (`build_request`, `check_answer`, `locate_proposals`) and `jobs/suggest_evidence_claims.py` (story model, `never_rerun`). The step `evidence_claims` asks GLM once. The board shows `EVIDENCE_STEPS` `off` when evidence is not wanted.

**Scope.**
- `services/footage_marks.py`: the mark list of §4.4 (add, edit the note, kind and keep or drop, remove an owner's mark; re-anchor on read; what counts; at most 100 owner marks). An owner's mark that overlaps another footage mark is refused; one over a claim, a graphic suggestion or a sound bite is accepted.
- API under `/api/projects/{id}/footage-marks`: read, mark, ask GLM, edit, remove.
- The story box: a **Footage** action in the selection toolbar with the note and the kind, a `footage` filter and layer, and a mark card (`FootageMarkCard.tsx`) with the note, the kind, keep or drop and remove.
- GLM: `services/footage_marks_writer.py` and `jobs/suggest_footage_marks.py`, one call with the story model. The prompt asks for places where real footage would help (a named event, a meeting, a launch, a place, a person, a product, a page or a document the script names) and not for abstract ideas, numbers and statistics, quotes that are sound bites, or words already marked as footage. Each proposal has the exact `phrase`, a `note` that is concrete and searchable (who, what, where, when), a `kind_hint` and a `reason`. Code checks: the phrase is found and snapped, it does not overlap a footage mark, it is not inside a sound bite's quote, the note has 1 to 300 characters, and at most one proposal is kept per 60 words of the story.
- Step `footage_marks` (asks once; skipped as complete when footage does not apply). The board shows the footage steps `off` when footage is not wanted.
- **Planning decides:** the layer's colour; whether the toolbar's "both" can combine footage with evidence; the prompt's wording; whether GLM sees the claims and graphic suggestions as context (the default: yes, so it keeps footage off numbers).

**Out of scope.** The owner's files (FTG-003), the brief (FTG-007).

**Dependencies.** FTG-001.

**Expected outcome.** The owner can mark footage and see GLM's proposals in the story box; nothing else in the pipeline changes.

**Verification criteria.**
- Marks move with their words when the script is edited elsewhere, and show `words_changed` when their own words change.
- An overlapping footage mark is refused; a mark over a claim is accepted.
- `check_answer` refuses a malformed answer and leaves out a phrase not in the story, an overlap, a quote that is a sound bite and a missing note (with a stand-in answer; a real call only with the owner's go-ahead).
- A project with footage off shows no footage controls, and its pipeline steps are the same as before.
- Standard checks.

**Completion checklist.**
- [x] Mark list and API
- [x] Story box action, filter and card
- [x] GLM proposals and code checks
- [x] Step and board
- [x] Standard checks

**Completion notes.**
- **Backend** (no migration; the table is `footage_mark_list` of `0106`):
  - `services/footage_marks.py` holds the mark list: `wanted`, `reanchor_marks`, `counting`, `add_mark`, `update_mark`, `remove_mark`, `start_suggest`, `save_ai_version` and the memoized `state`. Footage marks never overlap each other; one over a claim, a graphic or a sound bite is accepted; an owner's mark drops a GLM proposal it covers. At most 100 owner marks; a note is one line of at most 300 characters. Changes are refused with 409 while the job runs.
  - `services/footage_marks_writer.py`: the prompt, `build_request`, `check_answer` (needs `{"marks": [...]}`, each with a phrase, a note and a reason) and `locate_proposals`. A proposal is left out, with a reason, when it is not in the story, too long, dropped before, repeated, over footage that counts, over a sound bite, or over the limit of one for every 60 words (`proposal_limit`, at least one; the model gives the strongest first).
  - `jobs/suggest_footage_marks.py` (story model, `never_rerun`), `SAVING_FOOTAGE_MARKS` and the handler registered. API `api/footage_marks.py` under `/api/projects/{id}/footage-marks` (read, `marks`, `suggest`, edit, remove).
  - Step `footage_marks` ("Propose the footage") after `evidence_claims`, with its adapter; the board shows it `off` through `FOOTAGE_STEPS` (later footage steps are added there) and groups it with `story`.
- **Frontend:** `api/footageMarks.ts` (and `schema.d.ts`, regenerated), `FootageMarkCard.tsx`, a footage layer in `storyMarks.ts` and `StoryMarkup.tsx` (an orange line above the words: solid for kept marks, dashed for a proposal not yet decided; a `Footage` filter and legend; a details section; "Ask GLM for footage"), and `SelectionToolbar.tsx`. The step panel `footage_marks` and the Mark up tab show the story box when footage is on.
- **Planning decided:**
  - The toolbar's Footage button (key F) opens a second row with the kind, the note and "Mark footage" (Enter saves); "Both" stays evidence plus graphic.
  - GLM sees as context the evidence claims that count, the sound bite quotes and the graphic suggestions, so it keeps footage off words that already have something shown.
  - A proposal in a sound bite quote is left out when it overlaps the quote (stricter than "inside": footage never covers a sound bite, FT-12).
  - The layer colour is orange. The owner's marks default to kind `any`.
- **Checked** on a throwaway backend and database (the real app on port 5480 was not touched; no GLM call was made): marks move with edits elsewhere and show `words_changed` when their own words change; an overlapping mark is refused and a mark over a claim is accepted; keep, drop, remove, and the wrong-origin refusals; 404 for an unknown mark; 409 while a job is active; a story project and a project with footage off read `wanted` false, refuse marks with 422 and show `footage_marks` as `off` on the board. `check_answer` and `locate_proposals` were run with stand-in answers (malformed, missing note, note over 300 characters, phrase not in the story, repeat, sound bite, dropped before, over the limit). `start_suggest` and `save_ai_version` were run without the dispatcher, including the refusal when the story or the list changed. `ruff check`, `ruff format --check`, `npm run lint` and `npm run typecheck` pass.
- **Not checked in a browser:** the story box was typechecked and linted but not clicked through; the owner should try marking, the Footage row and the filter once.
- **No deviation** from Scope.

### FTG-003 — The owner's own files on a mark

**Status:** Not Started

**Objective.** The owner adds a photo or a video of their own to a mark, and it is ready to be shown.

**Current state.** Uploads stream the body (`api/voice_recordings.upload_scene_recording`: `request.stream()`, `content_length(request)`, `_UPLOAD_BODY`); nginx allows 512 MB. Files are stored with `Storage.save` under generated names. FFmpeg and FFprobe are used by the backend (`services/ffmpeg`).

**Scope.**
- An upload endpoint per mark (`kind` `image` or `video`, an optional credit of at most 120 characters, one line):
  - an image is a PNG, JPEG or WebP (WebP stored as PNG), at most 20 MB and 40 M pixels, checked from its content, and becomes an item at once;
  - a video is any file FFprobe reads with one video stream, at most 500 MB and 10 minutes. The job `prepare_footage_file` makes the stored copy: H.264, `yuv420p`, at most 1080 pixels high, **sound removed**, with its strip (a frame every 0.5 s) and its cut times (FFmpeg scene detection).
- Items with `origin` `owner`, accepted when added and shown after the mark's other pieces. On the mark card the owner can remove one, change the order, and for a video set where it starts and ends, in steps of 0.5 s. The default is the first 15 s; `use` is 2 to 30 s for an owner's video.
- The choices written as decision versions (§4.12).
- **Planning decides:** where the strip and cut code lives so FTG-009 can match it (the capture tool is a separate uv project, so the code is likely written twice, with the same thresholds); the formats FFprobe must accept.

**Out of scope.** The review screen for the agent's pieces (FTG-012); the clip on video (FTG-005).

**Dependencies.** FTG-002.

**Expected outcome.** A mark can hold the owner's photos and videos, in order, each ready to be drawn.

**Verification criteria.**
- PNG, JPEG, WebP, MP4 and MOV uploads work; a file that is not an image, a file over the limit and a file with no video stream are refused with a sentence.
- The prepared video has no audio stream. Its strip has one frame per 0.5 s. On a test video made with FFmpeg from two colours, the cut time found is within one frame of the real cut.
- Removing a file and changing the order make new decision versions; stored rows are never changed.
- Standard checks.

**Completion checklist.**
- [ ] Upload endpoint and checks
- [ ] `prepare_footage_file` handler
- [ ] Mark card: files, order, start and end
- [ ] Standard checks

**Completion notes.** —

### FTG-004 — Placing footage over the shots

**Status:** Not Started

**Objective.** Code works out, on read, where each mark's pieces are shown on a scene's timeline (§4.9).

**Current state.** `services/graphic_overlays.place_overlays` places suggestions over a planned scene (runs, pauses, `MIN_S`, `MAX_LEAD_S`, `GAP_S`); `graphic_suggestions.take_suggestions` gives a suggestion's words in each take; `services/split_stretches.py` gives the split stretches; `shot_plans.SceneEntry` carries `cards`, `overlays`, `stretches` and their unplaced lists, worked out on read for a planned scene. `TakeMap` maps take times to scene times.

**Scope.**
- `services/footage_placement.py` (pure) with the rules of §4.9.
- The words of each mark in each scene's take, the way `take_suggestions` does it.
- `shot_plans.SceneEntry` gains the placed pieces and the marks or pieces not placed (with a reason code), worked out on read only for a scene whose plan is current.
- Board notes for a mark not placed and a piece left out.
- **Planning decides:** the exact sharing of a run between pieces; whether a run of one word is dropped.

**Out of scope.** Clips (FTG-005) and the render (FTG-006).

**Dependencies.** None for the pure part. The `SceneEntry` fields read the marks (FTG-002) and the shown pieces (FTG-003) once those exist.

**Expected outcome.** For every planned scene, the app knows which piece is on screen from when to when, or why not.

**Verification criteria.**
- Sample cases: a run over presenter and B-roll shots; a run cut in two by an evidence shot; a run on a sound bite; a short run that grows and leads; no room; a montage of two 3 s videos and an image over 10 s; a piece left out; a boundary moved to a pause; a mark across two scenes; a still piece longer than 30 s.
- A project without footage gives the same `SceneEntry` values as before, apart from the new empty fields.
- Standard checks.

**Completion checklist.**
- [ ] Placement module
- [ ] `SceneEntry` fields
- [ ] Board notes
- [ ] Sample cases and identity check
- [ ] Standard checks

**Completion notes.** —

### FTG-005 — The footage clip and its preview

**Status:** Not Started

**Objective.** Every placed piece is drawn at its exact length, and the owner can preview a piece.

**Current state.** `services/evidence_clips.py` (states, queue functions, look keys), `jobs/render_evidence_clip.py`, `services/evidence_clip_layout.py`, `motion/src/evidence/Evidence.tsx` (camera and highlight; registered in `server/schema.ts` and `renders.ts`), `soundbite_render.compose_graph` (`full` and `fitted`), `evidence_clips.accent_for`. Drawn clips have their frames plus one spare frame (`scene_timeline.clip_frames`).

**Scope.**
- `services/footage_clips.py` and `jobs/render_footage_clip.py`: one clip per placed piece, keyed by its look (the item, `use`, frames, size, frame rate, framing, accent, clip version), so it is drawn again only when the look changes; its status is worked out on read.
- **Video** (§4.10): FFmpeg cuts the piece by the cut rules of §4.7, fits it (`full`, `fitted` or the chosen portrait crop), at the output size and frame rate, with no sound.
- **Image, page and PDF** (§4.10): the motion service. Pages and PDFs are built here and checked with made-up captures in the shape of §4.6, so they are ready when the research arrives.
- A **preview** of a fixed 6 s from the mark card (and later from the review).
- Step `footage_clips` (per scene), with one target per placed piece (`footage:{scene}/{key}`), and its board notes. `scene_render` and `render` gain it in their needs.
- **Planning decides:** one composition with flags or a new one (cards were one flag on `Evidence`); the image moves; the look of the browser frame; how a tall page fits the 32 MiB body limit (a JPEG for the transfer, or a cap on its height).

**Out of scope.** Laying the clips over the shots (FTG-006).

**Dependencies.** FTG-003, FTG-004.

**Expected outcome.** The clips of a scene's footage exist, at the right length and size.

**Verification criteria.**
- Clips of exactly the asked frames at 24 and 30 fps, in landscape and portrait, for a video, an image, a made-up page and a made-up PDF.
- A video clip has no audio stream. On a test video with cuts at known times, no cut falls in the first or last 0.5 s and the moment is as near the middle as the rules allow.
- A 4:3 source is fitted over the blurred copy; a portrait crop fills the frame.
- A page clip shows the address in the browser frame and the highlight on the focus.
- A clip is not drawn again when nothing in its look changed.
- Standard checks, and `npm run typecheck` in `motion/`.

**Completion checklist.**
- [ ] Clip states, queue and job
- [ ] Video by FFmpeg, with the cut rules
- [ ] Image, page and PDF compositions
- [ ] Preview
- [ ] Step and board
- [ ] Standard checks

**Completion notes.** —

### FTG-006 — Footage in the render

**Status:** Not Started

**Objective.** The scene render and the video render lay each placed piece full screen over the shots it spans, under cards and callouts (§4.10).

**Current state.** The frozen timeline (version 6) has the optional keys `evidence_cards`, `graphic_overlays` and `source_lines`; `render_story` stacks a shot's overlays as callouts, cards, split evidence, graphic overlays, with `card_overlays` splitting each across cuts; `graphic_spans` keep callouts off; `story_renders.overlay_reasons` makes a render out of date when an overlay changes; `timing_sources` and `next_render_sources` leave overlays out; `youtube_sources.block()` writes the Sources section.

**Scope.**
- An optional key `footage_overlays` in the frozen timeline (id, scene, mark, item, kind, times, frames, clip, size), written only when there is one, so the version stays 6. The render job reads it and lays each one **first**, under callouts, cards, split evidence and graphic overlays.
- The spans of page and PDF pieces added to `graphic_spans`.
- Credit lines as source lines in the subtitles (§4.10).
- A scene render without a piece's clip leaves it out with a warning (`footage_without_clip`); a video render is refused with a sentence.
- Render out-of-date reasons: a piece added, removed or with a new clip.
- Footage left out of `timing_sources` and `next_render_sources`.
- The description's Sources section gets the footage's sources (`&t=` for a video, from `use`); an owner's file with a credit is listed by its credit.
- **Planning decides:** a new key for the credits or the `source_lines` key with a `mark` field.

**Out of scope.** The waiting step (FTG-007).

**Dependencies.** FTG-005.

**Expected outcome.** The owner's own files show in the video over the shots under their words, with the voice unbroken.

**Verification criteria.**
- On a snapshot of the real database (with the owner's go-ahead): for every project without footage, the SHA-256 of the frozen timeline and the ASS file are the same before and after, and the count of `generate_shot` jobs does not change.
- A throwaway scene render with synthetic clips: the footage over presenter and B-roll shots only, a card and a callout on top of it, the voice unbroken, and no `generate_shot` job queued.
- The music placement stays current.
- The description lists the footage sources.
- Standard checks.

**Completion checklist.**
- [ ] Timeline key and render job
- [ ] Stacking, callouts and credits
- [ ] Warnings, refusals and out-of-date reasons
- [ ] Sources section
- [ ] Identity check and throwaway render
- [ ] Standard checks
- [ ] Owner: real app rebuilt

**Completion notes.** —

### FTG-007 — The research brief and the waiting step

**Status:** Not Started

**Objective.** The app writes a research brief for the marks that need it, and the full render waits for the footage.

**Current state.** `services/evidence_rounds.py` (round folder, brief, `README_PROMPT`, `folder_problem`, delta rounds with `covered`, `waiting` and `live`, `awaiting_text`, `remove_project_folder`) and `jobs/write_evidence_brief.py`. The step `evidence` waits through `Target.awaiting` (`story_pipeline_targets._evaluate_evidence`), and a run pauses with `waiting_for` (`jobs/story_pipeline.py`). `EvidencePanel.tsx` shows the brief, the folder and the import.

**Scope.**
- `services/footage_rounds.py` and `jobs/write_footage_brief.py`: the folder of §4.3, the brief of §4.5 (with `needed_s` from the take's word timings), the README with a ready-to-paste prompt naming the skill, delta rounds, the state of each mark (covered, waiting), and the refusal sentences.
- Step `footage` (§4.2), waiting for the owner. `render` gains it in its needs (it already needs `footage_clips` since FTG-005); `scene_render` does not.
- **Continue without footage:** one decision version that sets "no footage here" on every waiting mark.
- `FootagePanel.tsx`: write the brief, the folder's path, what each mark is waiting for, and Continue without footage.
- Project deletion removes `footage/<id>/`, with the same guards as the evidence folder.

**Out of scope.** The import (FTG-011) and the review (FTG-012).

**Dependencies.** FTG-002.

**Expected outcome.** A run that reaches the video render stops and says it is waiting for footage; everything else keeps going.

**Verification criteria.**
- The brief of sample marks has the right fields; a mark with an owner's file is not in it; a changed note makes that mark waiting again and only it goes into the next brief.
- The run waits with "Waiting for you (Gather the footage): ..." while scene renders still go.
- Continue without footage makes the step complete and the video render free to run.
- Deletion removes only the project's footage folder and refuses a link.
- Standard checks.

**Completion checklist.**
- [ ] Rounds, brief and README
- [ ] Waiting step and needs
- [ ] Continue without footage
- [ ] Footage panel
- [ ] Project deletion
- [ ] Standard checks

**Completion notes.** —

### FTG-008 — The capture tool: images, pages and PDFs

**Status:** Not Started

**Objective.** The agent can capture a photo, a web page and a PDF page for a mark, with no quote.

**Current state.** `tools/evidence-capture` (§2): `cli.py`, `web.py` (one viewport plus context strips), `pdf.py` (pypdfium2), `netguard.py`, `rounds.py`, `validate`; Playwright, httpx and pillow are already dependencies.

**Scope.**
- A new console script, `visio-footage-capture`, in the same uv project. It reads `brief/footage.json` (§4.5) and refuses an evidence round; the evidence command refuses a footage round. The evidence commands do not change.
- `image --mark f3 --piece p2 --url <image address> --page-url <page>` with the piece's facts (`--tier`, `--publisher`, `--title`, `--published`, `--what-it-shows`, `--same-event`, `--event-date`, `--on-screen-text`, `--licence`, `--licence-url`). The image is fetched through `netguard` with each redirect checked (as `fetch_pdf` does): JPEG, PNG or WebP (WebP saved as PNG), at most 20 MB and 40 M pixels. A warning below 1280 pixels on the longer side.
- `page --mark --piece --url [--focus "words"]`: the evidence browser settings (consent banners, fixed elements hidden), a screenshot from the top of the page, at most `PAGE_HEIGHTS` (4) screens. With `--focus`, the words are found like a quote (`find_quote`, nearby text listed on a miss) and their rectangles kept. The page's text is kept.
- `pdf --mark --piece --url | --file --page N [--focus "words"]`: as the evidence `pdf` capture, with the focus optional.
- `report --mark --status found|not_found|blocked --summary --attempt`, `remove --mark --piece`, `validate` (checks 1 to 4 of §4.8 for these kinds).
- Only the tool writes, and only inside `results/<mark>/`.
- **Planning decides:** the module split; whether `page` stitches viewport strips (like the context image) or uses Playwright's full-page screenshot; `PAGE_HEIGHTS`.

**Out of scope.** YouTube (FTG-009), the skill (FTG-010).

**Dependencies.** None. Only the contracts of §4.3, §4.5 and §4.6.

**Expected outcome.** The capture tool can produce every still piece of a footage round.

**Verification criteria.**
- Real captures of an image from Wikimedia Commons, a page with and without a focus, and a PDF page, in landscape and portrait; `validate` passes.
- Refusals: a non-public address, a file over the limit, a focus not found (with nearby text listed), a footage command in an evidence round.
- `validate` catches a changed file.
- An evidence round still captures and validates as before.

**Completion checklist.**
- [ ] Command, brief reader and result writer
- [ ] `image`, `page`, `pdf`
- [ ] `report`, `remove`, `validate`
- [ ] Real captures and refusals

**Completion notes.** —

### FTG-009 — The capture tool: YouTube scans and clips

**Status:** Not Started

**Objective.** The agent can find the right moment of a YouTube video by its picture, and the tool downloads only those seconds, without sound (§4.7).

**Current state.** `video.py` and `youtube.py` (yt-dlp's Python API, no cookies, English caption track choice, `download_ranges`, H.264 re-encode, FFprobe checks). §2 records how YouTube's previews behave.

**Scope.**
- `scan --mark f3 --url <youtube address> [--from mm:ss --to mm:ss]`: `info.json`, `captions.txt` (the English track the `video` command would pick, as plain text), and YouTube's largest storyboard (no video downloaded), cut into frames and laid out as contact sheets of 36 with each frame's time stamped. A whole video only up to `MAX_SCAN_S` (20 min); otherwise a range of at most 20 min. With no storyboard, the tool says so and suggests a fine scan.
- `scan --fine --mark --url --from --to` (at most 90 s): only that range at 360p or less, video only; sheets of frames 0.5 s apart with their times; `cuts.json` from FFmpeg's scene detection.
- `clip --mark --piece --url --from --to [--moment mm:ss.s]` with the piece's facts as in FTG-008: `use` of 2 to 15 s; downloads `use` plus 2 s on each side at up to 1080p, video only, re-encoded to H.264 so it starts on the asked frame; finds the cuts again on that file; writes the strip; writes the `capture` of §4.6, with the channel, the upload date and YouTube's licence.
- YouTube addresses only; the same yt-dlp options as `video`. Scans are written in `scans/<video_id>/` and are never part of the result.
- **Planning decides:** the scene detection threshold (start at 0.3); the sheet layout for small previews (159x90); the bytes a scan may download.

**Out of scope.** Other video sites (FTG-018); automatic frame search (FTG-017).

**Dependencies.** FTG-008.

**Expected outcome.** For a video, the agent gets contact sheets in a few hundred KB, then a 0.5 s sheet of a short range, then a muted clip of only the chosen seconds.

**Verification criteria.**
- A scan of a short video and a ranged scan of a long keynote: each stamped time matches the frame a fine scan shows at that time.
- A fine scan of 60 s: the cut times are within one frame of the cuts seen in a full-quality clip of the same range.
- A clip has no audio stream, starts on the asked frame, and lasts as long as its window within 0.5 s.
- Refusals: an address that is not YouTube, a scan range too long, a `use` too long or too short.
- The bytes downloaded by each command are recorded in the notes.

**Completion checklist.**
- [ ] `scan` (previews, info, captions)
- [ ] `scan --fine` (sheets and cuts)
- [ ] `clip`
- [ ] `validate` for video pieces
- [ ] Real runs and refusals

**Completion notes.** —

### FTG-010 — The research skill

**Status:** Not Started

**Objective.** Cursor and Claude can research a footage round on their own, safely, and say honestly when nothing was found.

**Current state.** The evidence skill (`tools/evidence-skill/visio-evidence/SKILL.md`, `reference.md`, `install.sh`): safety rules, one subagent per claim (at most 3 at a time), the import through two exact `curl` calls.

**Scope.**
- `visio-footage` (`SKILL.md` and `reference.md`) and its install into `~/.claude/skills`. The allowed tools are the footage command, `ls`, two exact `curl` calls (`POST .../footage/import` and `GET .../footage` on `127.0.0.1:5480`), and Read, Glob, Grep, WebSearch and WebFetch.
- The rules: the same safety rules as evidence; one subagent per mark, at most 3 at a time; the source order and the creator rule of FT-9; the same-event check of FT-10 (who and when come from the title, the description and the event's own page, never from a face); `needed_s` as the amount of footage to find; at most `max_pieces_per_mark` pieces.
- **YouTube** (§4.7): candidates by title, channel and date; `scan`, read the sheets as images, narrow down, `scan --fine`, read again, `clip`; then read the strip and check that the picture has no anchor, ticker or large text, and that it shows what the note asks.
- **Images, pages and PDFs:** official galleries and Wikimedia Commons with their licence; the page the script names, with a focus on the words it talks about.
- Status rules (`found`, `not_found`, `blocked`), the attempts, the finish (validate, a table of marks, the import).
- **Planning decides:** one install script for both skills or one each.

**Out of scope.** Recording a website (FTG-014).

**Dependencies.** FTG-009.

**Expected outcome.** The owner pastes the README's prompt in the round folder, and the round comes back researched, validated and imported.

**Verification criteria.**
- One run in Cursor and one in Claude Code on a throwaway round with the marks of Appendix A. For each mark, record: found or not, the tier, same event or not, the time taken and the bytes downloaded.
- `validate` passes, and no file was written outside `results/`.
- A page that carries an instruction to the agent (a test page) does not change what the agent does.

**Completion checklist.**
- [ ] `SKILL.md` and `reference.md`
- [ ] Install
- [ ] Run in Cursor
- [ ] Run in Claude Code

**Completion notes.** —

### FTG-011 — Importing the research

**Status:** Not Started

**Objective.** The app reads a round's results as untrusted input, checks every piece and copies the usable files into storage (§4.8).

**Current state.** `services/evidence_import.py` and `evidence_checks.py` (limits, `O_NOFOLLOW`, regular files only, magic bytes, SHA-256, FFprobe for video, files reused by hash within a round, `discard_files` on failure), `jobs/import_evidence.py`, `api/evidence.py`.

**Scope.**
- `services/footage_import.py`, `services/footage_checks.py` and `jobs/import_footage.py`: checks 1 to 5 of §4.8 for each kind; usable files copied to `media/<project_id>/`; the report (counts by status, pieces and usable pieces); an unchanged piece keeps its `item_key` from one import to the next.
- API `POST /api/projects/{id}/footage/import` and `GET /api/projects/{id}/footage` (the round's status, the import job and the report), as the skill's `curl` calls expect.
- The panel shows the report.
- **Planning decides:** which helpers are shared with the evidence import and which are copied.

**Out of scope.** The review (FTG-012).

**Dependencies.** FTG-007, FTG-008. Video pieces once FTG-009 is done.

**Expected outcome.** The agent's pieces are stored, with their checks and warnings, ready for review.

**Verification criteria.**
- The rounds of FTG-010 import; each warning of §4.8 is shown where it applies.
- Tampered files are refused by the right check: a changed hash, a renamed type, a link, a video with sound, `use` outside `window`.
- The `scans/` folder is never read or copied.
- A second import of the same round keeps the item keys.
- Standard checks.

**Completion checklist.**
- [ ] Checks and copy
- [ ] Job and API
- [ ] Panel report
- [ ] Checks above
- [ ] Standard checks

**Completion notes.** —

### FTG-012 — The review screen

**Status:** Not Started

**Objective.** The owner reviews every piece the agent found, beside their own files, and chooses what each mark shows.

**Current state.** `EvidenceReview.tsx` (claim cards, piece cards, previews) and `SoundbiteClipPanel.tsx` (a player at the cut, cut buttons, risky flags in red); `services/evidence_review.py` (decisions as versions, `Review done`).

**Scope.**
- `FootageReview.tsx` in the footage panel. For each mark: its words and note, then each piece:
  - a video plays at its `use`, with the cut times marked and the strip, buttons that move the start or end by 0.5 s or to the edge of the shot, and the portrait framing choice;
  - an image, a page with its focus box, or a PDF page;
  - what it shows, the source with a link, and the warnings as badges: file footage, event not checked, text on the picture, not an official source, licence unknown, low resolution;
  - Accept and Reject, and a preview.
- Per mark: the order of the pieces to show, and "no footage here". **Review done**, and Continue without footage.
- The owner's files in the same list, accepted, with remove.
- API for decisions, done and preview; the decision checks (`use` inside `window` and 2 to 15 s, an item of that mark, done refused while a piece is undecided).
- **Planning decides:** whether "File footage" needs a second click to accept, like the risky flags of SB-017.

**Out of scope.** Changes to the placement (FTG-004).

**Dependencies.** FTG-011.

**Expected outcome.** The owner decides what every mark shows, and the video follows.

**Verification criteria.**
- Decisions are stored as versions; a reorder changes the placement and only that mark's clips.
- A `use` outside the window or longer than 15 s is refused.
- Review done is refused while a piece is undecided.
- The owner opens the screen in a browser and reviews the rounds of FTG-010.
- Standard checks.

**Completion checklist.**
- [ ] Review screen
- [ ] API and checks
- [ ] Browser check by the owner
- [ ] Standard checks

**Completion notes.** —

### FTG-013 — The Qwen vs Inkling explainer end to end (owner)

**Status:** Not Started

**Objective.** Footage on one real explainer, from marks to the published video, and the starting values of §4.7 and §4.9 tuned by eye.

**Steps** (the agent prepares them; the owner runs every paid or destructive step).
1. Footage on for the Qwen vs Inkling project (`explainer_scripts/qwen_vs_inkling/script.txt`); the marks of Appendix A, and GLM's proposals kept or dropped.
2. The owner's screen recording for Appendix A, row 7, added as a file.
3. Brief, research in Cursor (and once in Claude Code), import, review.
4. Scene renders: watch each footage span; note any flash of a cut, a credit hard to read, a montage too fast or too slow, a portrait framing that cuts a face.
5. Record in Appendix A what was found, and in this phase's notes the values changed and why.

**Verification criteria.** The video render shows every accepted piece where it belongs; no `generate_shot` job was queued because of footage; the music placement did not run again; the description lists every source.

**Completion notes.** —

### FTG-014 — Recording a website (later)

**Status:** Not Started (after FTG-013)

**Objective.** Real interaction on a website as footage: clicking a tab, typing into a search box, hovering over an interactive chart, a page loading.

**Scope (to plan after FTG-013).**
- A `record` command that runs a short list of steps the agent gives as one argument: `open`, `wait`, `scroll_to_text`, `scroll_by`, `click_text`, `hover_text`, `type_in_search`. No other step, no login, no form other than a search box, no download.
- The recording is frames captured at a steady rate and encoded as H.264 at good quality, at most 30 s; a new kind `recording`, reviewed and drawn like a video piece.
- **Planning decides:** the recorder (Playwright's own recorder is made for debugging and its quality is likely too low; frames captured at a steady rate are the likely choice, to be tested).

**Limits.** Sites that need a login cannot be recorded by the agent; the owner records those and adds them as a file (FTG-003).

### FTG-015 — Footage between words (later)

**Status:** Deferred

The narrator pauses and the footage plays, which makes the video longer. Built with SB-011, since both need a replaced span of zero length in `take_map`. The owner's rule for the sound: GLM reads the clip's transcript; when it has meaningful words, the clip's own sound plays; otherwise music. A clip with speech must get the sound bite flags (`turn_after`, `reported_speech` and the others) in the review, because it plays a real person's words. A clip with no transcript (an owner's file, another site) gets music unless a transcription step is added.

### FTG-016 — No H3 clip where footage hides it (later)

**Status:** Deferred

A B-roll shot that footage covers completely is not sent to H3, while the plan stays the same. Footage reviewed after the clip was made changes nothing. It needs `shot_definitions` to read the placement, and a removed piece must bring the shot's clip back.

### FTG-017 — Automatic frame search (later)

**Status:** Deferred

A local model that compares pictures with text (CLIP or SigLIP) scores every frame of a scan against the mark's note, so the best shots come first. The agent and the owner still decide.

### FTG-018 — Footage from other video sites (later)

**Status:** Deferred

A direct video address (a government or company site): no preview pictures, so frames are taken by seeking in the file over the network, or from a small low-quality copy of a short video.

---

## 7. Progress tracking

Follow §7 of `Evidence_layer_implementation_phases.md`: when a phase changes status, update its **Status** line in §6, its row in the §5 table and the **Progress snapshot**, and add a row to Appendix B. Write the **Completion notes** before marking a phase Completed: the real names of tables, columns, job types, endpoints, modules and UI components, each "Planning decides" item and how it was decided, and any deviation from Scope. If a phase changes a contract in §4, update §4 too.

---

## 8. Open questions and risks

### 8.1 Open questions

| ID | Question | Default until answered |
|----|----------|------------------------|
| Q-F1 | Is footage on by default for a new continuous explainer? | Yes, like evidence (FT-3). |
| Q-F2 | The shortest run and the shortest piece of a montage. | `MIN_S` 2.0 s and `MIN_PIECE_S` 1.5 s; tuned in FTG-013. |
| Q-F3 | Portrait framing of a landscape video. | Fitted over a blurred copy; a crop is the owner's choice. |
| Q-F4 | Callouts over a page or PDF piece. | Dropped (FT-13). |
| Q-F5 | May footage cover the planner's own graphic shot? | No (FT-12). |
| Q-F6 | Should a still piece have a soft limit (a photo held 12 s is dull)? | No limit but 30 s; a note above 8 s may be added in FTG-013. |
| Q-F7 | Are GLM's proposals researched before the owner decides? | Yes: a proposal counts until it is dropped, as for evidence. |
| Q-F8 | Must the owner's own files carry a credit? | No; a credit is shown only when written. |

### 8.2 Risks

- **YouTube's terms and blocks.** As for sound bites (`Sound_bite_implementation_phases.md` §8.2): downloading is outside YouTube's own features, and `yt-dlp` warns and can break when YouTube changes. The preview pictures are not documented and could change or disappear; without them `scan` falls back to a fine scan of a narrowed range.
- **Copyright, Content ID and reused content.** Footage of other people's videos is riskier than a sound bite: it has no commentary over it in its own words, and Content ID matches pictures. Official and public-domain sources, a few seconds per piece, a credit and a recorded licence lower the risk but do not remove it. US federal government works are generally public domain; the terms of Indian government footage (PIB, PMO) were not checked. This is the owner's judgement, not legal advice; get advice before monetising.
- **Misleading footage.** Footage of another meeting shown as this one misleads even though nothing is fake. FT-10 and the review are the guard.
- **The agent reading pictures.** The agent can be wrong about what a small preview shows. Who and when come from the source's text, the strip is checked before the result is reported, and the owner sees every clip.
- **Pages.** Cookie walls, pop-ups and bot checks; personal data on a page (comments with names); instructions aimed at agents. The same browser settings, safety rules and the review apply.
- **Wasted H3 time.** B-roll under footage is still made (FT-15) until FTG-016.
- **Tall pages and the motion service.** A 4-screen page at scale 2 is a large image; FTG-005 must keep the request under the 32 MiB limit.
- **Disk space.** Clips are short and scans are small, but the owner's videos (up to 500 MB each) add up in the files folder.

---

## Appendix A — Test set

From `explainer_scripts/qwen_vs_inkling/script.txt`, except row 8. None has been searched for yet. FTG-010 and FTG-013 fill in the last column.

| # | Script line | Words to mark | Kind | Where to look | What it tests | Found |
|---|-------------|---------------|------|---------------|---------------|-------|
| 1 | 1 | "They put a MacBook in airplane mode, no internet, nothing, and asked an AI running on that laptop to build them a flight simulator." | Video | Thinking Machines Lab's own demo video (line 67 says it plays mostly at 15 times speed) | An official channel, the same event, `needed_s` longer than one shot | — |
| 2 | 15 | "It's the most downloaded family of open models on Hugging Face." | Page | Hugging Face's Qwen organisation page, focus on the downloads | A page with a focus; if the words are also a claim, the evidence wins (FT-12) | — |
| 3 | 17 | "the company Mira Murati started after leaving her job as OpenAI's chief technology officer" | Image or video | A photo on Wikimedia Commons (licence and credit), or an official event channel | File footage (FT-10), the credit line for a free licence | — |
| 4 | 67 | "A reviewer called JeredBlu tried it on a 36GB Mac." | Video | JeredBlu's own video, a few seconds | The creator rule (FT-9): the script talks about that video | — |
| 5 | 103 | "Simon Willison, a well-known developer, asked Qwen3.8-27B to draw a pelican at that default." | Page | Simon Willison's blog post, focus on the pelican or "21 minutes" | A page in the browser frame; a callout dropped over it | — |
| 6 | 105 | "One developer on Hacker News said a single question ran for over 3 hours" | Page | The Hacker News comment, focus on its words | A focus found on a busy page | — |
| 7 | 111 | "So I went and looked at my own code." | Owner's file | The owner's screen recording of the code | FTG-003: an owner's video, its start and end, no credit | — |
| 8 | — | "Prime Minister Narendra Modi met the US President at the White House" (a throwaway round, not this script) | Video | The White House or PMO India channel; the handshake | The three steps of §4.7 on a 41-minute stream, the same-event check, a ticker avoided | — |

---

## Appendix B — Progress log

| Date | Phase | Change |
|------|-------|--------|
| 2026-11-28 | — | Document written. |
| 2026-11-28 | FTG-001 | Completed: migration `0106` (`project.footage`, six footage tables, five job types), models, the switch on the API and both forms, `DATABASE_STRUCTURE.md` (with `0105`). |
| 2026-11-28 | FTG-002 | Completed: footage marks (service, API, GLM proposals job), the `footage_marks` step and board entry, and the story box layer, toolbar row and card. No migration. |
