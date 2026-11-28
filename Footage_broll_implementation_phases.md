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
- **An image** has `capture.image`, `image_px`, `page_url` (the page the image was found on, or null) and `sha256`. `source.url` is the image's own address and `source.final_url` that address after redirects. The stored file is `.jpg` or `.png`; WebP is stored as PNG (FTG-008).
- **A page** has `capture.image` (the page from its top, at most `PAGE_HEIGHTS`, 4, screens tall, at the evidence viewports), `image_px`, `viewport` (`[width, height]` in CSS pixels) with `device_scale`, `text_copy`, `focus_text` (null when no focus was asked) and `focus_rects` (`[x, y, width, height]` as fractions of `image`; empty when no focus was asked) and `sha256`. Words below the captured screens are refused, so `focus_rects` always lie in the image.
- **A PDF page** has what the evidence `pdf` capture has (`image`, `page`, `source_copy`, `render_scale`, `text_copy`) with `focus_text` and `focus_rects`. Its `image` is the **whole page** (the longer side at 4096 pixels), not a crop, and `focus_rects` are fractions of the page (FTG-008).

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
- **A still piece** (image, page, PDF) is on screen for at most `MAX_PIECE_FRAMES` (720 frames at 24 fps, 30 s), the backend's cap on a drawn clip (the motion service itself allows 4320 frames). A run of one still piece that is longer is cut at 30 s, with a note.
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
| FTG-003 | The owner's own files on a mark | Code | FTG-002 | Completed |
| FTG-004 | Placing footage over the shots | Code | — | Completed |
| FTG-005 | The footage clip and its preview | Code | FTG-003, FTG-004 | Completed |
| FTG-006 | Footage in the render | Code | FTG-005 | Completed |
| FTG-007 | The research brief and the waiting step | Code | FTG-002 | Completed |
| FTG-008 | The capture tool: images, pages and PDFs | Code (Mac) | — | Completed |
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

**Progress snapshot:** 8 completed (FTG-001 to FTG-008, 2026-11-28; the owner still has to rebuild the real app, and the motion image for FTG-005); 18 phases (13 to build now, 1 later, 4 deferred).

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

**Status:** Completed (2026-11-28; the owner still has to rebuild the real app and try the card in a browser)

**Objective.** The owner adds a photo or a video of their own to a mark, and it is ready to be shown.

**Current state.** Uploads stream the body (`api/voice_recordings.upload_scene_recording`: `request.stream()`, `content_length(request)`, `_UPLOAD_BODY`); nginx allows 512 MB. Files are stored with `Storage.save` under generated names. FFmpeg and FFprobe are used by the backend (`services/ffmpeg`).

**Scope.**
- An upload endpoint per mark (`kind` `image` or `video`, an optional credit of at most 120 characters, one line):
  - an image is a PNG, JPEG or WebP (WebP stored as PNG), at most 20 MB and 40 M pixels, checked from its content, and becomes an item at once;
  - a video is any file FFprobe reads with one video stream, at most 500 MB and 10 minutes. The job `prepare_footage_file` makes the stored copy: H.264, `yuv420p`, the shorter side at most 1080 pixels, **sound removed**, with its strip (a frame every 0.5 s) and its cut times (FFmpeg scene detection).
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
- [x] Upload endpoint and checks
- [x] `prepare_footage_file` handler
- [x] Mark card: files, order, start and end
- [x] Standard checks
- [ ] Owner: real app rebuilt (`docker compose up --build -d`, never `down -v`) and the mark card tried once in a browser

**Completion notes.**
- **No migration.** Everything is stored in the tables of `0106`: `footage_item` (`origin` `owner`, `import_id` NULL) and `footage_decision`.
- **Backend modules:**
  - `services/footage_decisions.py`: the project-wide decision versions. `add_accepted` (flushes; the upload commits it), `remove_item`, `reorder`, `set_use`, each one new version; nothing is stored when nothing changes. Content is as in the `FootageDecision` docstring, with `use` as `{item_key: {start_s, end_s}}` inside the mark's entry.
  - `services/footage_frames.py`: `prepare` (the muted H.264 copy), `write_strip` and `find_cuts`, with the constants FTG-009 must copy: `STRIP_EVERY_S` 0.5, `STRIP_COLUMNS` 10, `STRIP_TILE_W` 192, `STRIP_TILE_H` 108 and `CUT_SCENE_THRESHOLD` 0.3.
  - `services/footage_files.py`: the streamed upload and its checks, `remove_file`, `reorder_files`, `set_use` and `files_state`.
  - `jobs/prepare_footage_file.py` (`local`, `start_again`, one at a time) and three phase labels in `jobs/phases.py`.
  - `api/footage_files.py`: `GET /api/projects/{id}/footage-files`; `POST .../footage-marks/{mark_id}/files?kind=image|video[&credit=]` (raw body); `DELETE .../footage-files/{item_key}`; `PUT .../footage-marks/{mark_id}/order`; `PUT .../footage-files/{item_key}/use`.
- **Frontend:** `api/footageFiles.ts`, `FootageFilesSection.tsx` (inside `FootageMarkCard.tsx`: add with an optional credit, thumbnail, status, Up, Down, Remove, and for a ready video the start and end boxes with a muted preview), and `StoryMarkup.tsx` loads the files. `schema.d.ts` was regenerated from the app's OpenAPI (additions only).
- **Planning decided:**
  - **Where the strip and cut code lives:** in `services/footage_frames.py` with the constants above; the capture tool will copy them (FTG-009).
  - **Formats:** ffprobe's `format_name` must be `mov,mp4,m4a,3gp,3g2,mj2` (MP4, MOV, M4V) or `matroska,webm`. Anything else is refused, which also keeps playlist formats out.
  - **Strip:** one JPEG grid of fixed 192x108 tiles (the picture fitted, never cropped); tile `n` is the frame at `n * 0.5` s. `capture` holds `strip_columns`, `strip_rows`, `strip_tile_px` and `strip_frames`.
  - **Removing a file** is a decision version (verdict `rejected`, not in `shown`). The item row and its files stay stored.
  - **Ids:** `piece_id` is `o<n>` where n counts every file ever added to the mark, so it can pass 9 after removals; at most 9 files are shown on a mark. `item_key` is `owner-<uuid hex>`.
  - **A video's start and end:** both in steps of 0.5 s (the end may also be the very end of the video), inside the video, 2 to 30 s. Until the owner moves it, `use` is the first 15 s (or the whole video if shorter). The default is stored in `capture.use`; the owner's choice is in the decision.
- **Deviation from Scope:** the size cap of a prepared video is on the **shorter side** (1080), not on the height, so a portrait 1080x1920 video keeps its size. The Scope line above was changed to say so. §4.8 (the agent's import) still says "at most 1080 pixels high"; FTG-011 should read it the same way or the two will disagree for portrait pieces.
- **Checked** on a throwaway database and data folder (no paid call, the real app on port 5480 was not touched):
  - PNG, JPEG, WebP (stored as PNG, transparency kept), MP4, MOV, MKV and WebM uploads work; each video was prepared by the job.
  - Refused with a sentence: a text file named `.png`, an image over 20 MB (413), an audio-only file, a playlist file, a 1 s video, an image sent as a video and a video sent as an image, a wrong content type (415), a credit over 120 characters, a story project, an unknown mark (404).
  - Every prepared video has one H.264 `yuv420p` stream and no audio (the MOV test file had a sound track); a 1080x1920 file stayed 1080x1920. The strip has `ceil(duration / 0.5)` tiles (13 for 6.2 s).
  - A video made of 3 s red then blue: the cut was found at 3.0 s, and a one-colour video has none.
  - Each add, reorder, move and removal made exactly one decision version; an unchanged order and a repeated removal made none; earlier versions were identical afterwards. Removed files stayed stored. The temp folder was empty at the end.
  - `ruff check`, `ruff format --check`, `npm run lint` and `npm run typecheck` pass.
- **A failing prepare job** was checked with a cut-off MKV that ffprobe still reads: the job failed with "The prepared video is not as long as the original.", the item read `failed` with that text, and nothing was stored for it.
- **Not checked:** the card in a browser (typecheck and lint only), and a video near the limits (500 MB, 10 min).

### FTG-004 — Placing footage over the shots

**Status:** Completed (2026-11-28)

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
- [x] Placement module
- [x] `SceneEntry` fields
- [x] Board notes
- [x] Sample cases and identity check (sample cases and a code-level identity argument; the snapshot comparison on the real database was not run, see below)
- [x] Standard checks

**Completion notes.**
- **No migration.** Nothing is stored for the placement.
- **Modules:**
  - `services/footage_placement.py` (pure): `place_footage(wanted, slots, blocked, pauses, total_s)` gives `Placement(pieces, unplaced, notes)`. `PlacedPiece` has `run_key`, `item_key`, `kind`, `index`, `start_s`, `end_s`, `shot_ids`, with `key` = `{run_key}:{item_key}` and `run_key` = `{scene_id}/{first}-{last}`. Constants: `MIN_S` 2.0, `MAX_LEAD_S` 1.0, `MIN_PIECE_S` 1.5, `SNAP_S` 0.5, `STILL_MAX_S` 29.917. Reason codes: `no_room`, `covered`, `soundbite`, `one_word`, `too_short`; piece notes `left_out` and `cut_short`.
  - `services/footage_decisions.py`: `shown_marks` (with `ShownFootageMark` and `ShownFootagePiece`) reads the counting marks, the newest decision version and the usable items. A project without footage reads no tables; a mark with `no_footage`, an unusable item or a video with no `use` shows nothing.
  - `services/shot_plans.py`: `_Loaded.footage`, `_footage(...)` (modelled on `_graphic_overlays`) and the `SceneEntry` fields `footage`, `unplaced_footage` and `footage_notes`, worked out only for a planned scene whose plan is a cut plan.
  - `services/story_pipeline_targets.py`: `_footage_notes`, returned as the warnings of the `footage_marks` step. FTG-005 moves them to `footage_clips`.
- **Planning decided:**
  - **Run cut by something footage may not cover:** the blocked time is the drawn shots (graphic, evidence, sound bite), graphic overlays and split stretches. Each part left is placed on its own, and a graphic overlay wins over footage on the same words.
  - **Pieces across the parts of one mark in a scene:** a shared cursor. The next part starts at the piece after the last one shown and wraps; a new scene starts again from the first piece. A part shows only as many pieces as fit at 1.5 s each, and the rest get a `left_out` note.
  - **Sharing a part's time:** water-filling (even shares, a video capped at its `use`, a still at `STILL_MAX_S`, unused time shared among the others). **Deviation from §4.9:** the section says the time a video cannot fill goes "to the still pieces after it"; water-filling gives it to every piece that can still use it, in any order. §4.9 should be read that way.
  - **A still piece's cap** is 29.917 s (718 frames at 24 fps), not 30 s: the clip has one spare frame and rounding both ends to the frame grid may add one, and a drawn clip may not pass 720 frames.
  - **Run of one word:** dropped (`one_word`) only when the mark lost its other words to a sound bite or to something footage may not cover. A one-word mark the owner chose is placed.
  - **Boundaries between pieces** move to the nearest pause middle within 0.5 s when both pieces keep at least 1.5 s and stay within their caps.
  - **Board notes** are on the `footage_marks` step for now.
- **Checked** on throwaway code and a throwaway database (no paid call, the real app was not touched; the scripts were removed):
  - `place_footage` sample cases: a run over presenter and B-roll shots; a run cut in two by an evidence shot (the second part continues with the next piece and wraps); a run entirely on a sound bite; a short run that grows after its words and one that starts early at the end of a scene; no room between graphic shots; a montage of two 3 s videos and an image over 10 s (second boundary moved to a pause, 5.95 s); a piece left out; a boundary moved to a pause; a mark across two scenes (each starts at the first piece); a 40 s run of one still (cut at 29.917 s with `cut_short`); one word left beside an overlay; an overlay covering all the words; two marks side by side.
  - `shot_plans._footage` on a hand-made scene (take map, shots, words): the marked words were found in the take, placed over presenter and B-roll shots, and two pieces were shared out. With no footage it returns nothing.
  - `shown_marks` on a migrated throwaway database: `[]` for a project with footage off and for one with no marks; an unusable video is skipped; a moved `use` changes the video's length; a removed file leaves the list; `shot_plans.state` ran for a project with footage on.
  - `ruff check` and `ruff format --check` pass.
- **Not done:** the snapshot comparison on the real database (`SceneEntry` values before and after for every project without footage) needs the owner's go-ahead. By construction a project without footage reads no footage tables, `_footage` returns at once, and the new fields default to empty. `npm run typecheck` was not run: no frontend or API file changed.

### FTG-005 — The footage clip and its preview

**Status:** Completed (2026-11-28; the owner still has to rebuild the motion image and the backend of the real app)

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
- [x] Clip states, queue and job
- [x] Video by FFmpeg, with the cut rules
- [x] Image, page and PDF compositions
- [x] Preview
- [x] Step and board
- [x] Standard checks

**Completion notes.**
- **No migration.** `footage_clip`, the job type `render_footage_clip` and the placed pieces already existed.
- **Modules:**
  - `services/footage_cut.py` (pure): `choose_start(use_start_s, use_end_s, length_s, moment_s, cuts, fps)`. `EDGE_S` 0.5, `CUT_SETTLE_FRAMES` 3. The valid start nearest the target wins; with none, the nearest grid start is used and the clip gets the warning `cut_in_clip`.
  - `services/footage_video.py`: `clip_graph` (fit over the blurred copy, fill, or a portrait crop `left`, `centre` or `right`, tail frames cloned) and `clip_args` (H.264 `yuv420p`, `-an`, constant frame rate). `soundbite_render._picture_chain` is now public (`picture_chain`), output unchanged.
  - `services/footage_clip_layout.py` (pure): the image look (fit or fill, zoom 1.05, blurred backdrop), the browser window of a page (title bar, three dots, address bar, highlight sweep), and the PDF camera.
  - `services/footage_clips.py`: the look of a clip, `piece_state` (memoized; nothing is read when footage is off), `queue_piece_clip`, `queue_preview`, `previews_for`. `FootageClipError` carries a sentence.
  - `jobs/render_footage_clip.py` (`local`, `start_again`, concurrency `GRAPHICS_MAX_RENDERS_KEY`): FFmpeg for a video, the motion service for the rest, then `ffprobe` checks the frames, size, rate, codec, pixel format and that there is **no audio**.
  - Motion: `shared/camera.tsx` (camera and highlight helpers, used by `Evidence` and `Footage`, `Evidence` unchanged in output), `footage/Footage.tsx` and `footage/props.ts`, the engine `footage_clip` on the large-body route `/evidence-renders` (`/renders` refuses it).
  - Step `footage_clips` ("Draw the footage", per scene, needs `shot_plans`; `scene_render` and `render` need it); one target per placed piece, `footage:{placed_key}`; the notes of `_footage_notes` moved here from `footage_marks`. `render` does not need `footage` yet (that step comes with FTG-007).
  - Preview: `POST /projects/{id}/footage-files/{item_key}/preview` (202, `{job_id}`), `FootageFileOut.preview`, `FootagePreview.tsx` in each ready file of the mark card, polling while a preview is queued or running; `StepPanel` shows the shot plan for `footage_clips`.
- **Planning decided:**
  - **Composition:** a new `Footage` composition with `mode` `image`, `page` or `pdf`.
  - **Image move:** a photo of the frame's shape fills it; any other shape is fitted over a blurred, darkened copy, with a 5% zoom over the clip. A portrait crop from the mark's `framing` fills the frame.
  - **Browser frame:** a rounded window on the plain evidence background with the page's host and path in an address bar; the page scrolls to the focus, zooms and the focus gets the accent highlight.
  - **32 MiB limit:** the picture is scaled down to what the largest zoom needs and sent as PNG; over 28 MiB it is sent as JPEG (quality 90); if still over, the clip fails with a sentence.
  - **An owner's video** has no `moment_s`: it starts at the chosen start, moved only as far as the cut rules need.
  - **The look** includes the portrait crop only for a video or an image, and the accent only for a page or a PDF, so a new accent never draws a video again and a crop never redraws a page.
- **Deviations:** `footage_clip` was not added to `graphics_render.COMPOSITION_OF` (the job names its composition itself). Page and PDF clips were checked with made-up captures only.
- **Checked** on a throwaway database and data folder, with the motion service run from a throwaway bundle on another port (no paid call; the real app on port 5480 was not touched; the scripts were removed):
  - `choose_start` samples: no cuts; a cut near an edge (the start moves past it); a moment near either end of `use` (kept inside it); dense cuts (warning); an owner's video starting at `use.start`.
  - Preview clips of exactly 144 frames at 1280x720 and 720x1280 for an owner video, an owner image, a made-up page and a made-up PDF, and a 61-frame clip at 30 fps: H.264, `yuv420p`, no audio. The cuts at 3, 6 and 9 s of a test video stayed out of the first and last 0.5 s.
  - Frames looked at: the 4:3 photo is fitted over the blurred copy; a portrait crop fills the frame (left and right differ); the page shows the window, the address and the highlight; the PDF shows its page and highlight.
  - Tall pictures: a 1280x5120 noise page stays PNG under the limit, a 1920x7680 one falls back to JPEG, both under 28 MiB.
  - A new framing makes only a video's and a photo's preview out of date, not a page's. The step has one done target for a project with footage off and none for a project with footage on and no plan.
  - `ruff check`, `ruff format --check`, `npm run typecheck` and `npm run lint` (frontend), `npm run typecheck` in `motion/`.
- **Not done:** `piece_state` and `queue_piece_clip` were not run on a real shot plan (they were checked by reading and through the preview path, which shares the look and the job); a 4-screen real page and the scroll's look on a real capture wait for FTG-008. The motion image and the backend of the real app must be rebuilt.

### FTG-006 — Footage in the render

**Status:** Completed (2026-11-28; the owner still has to rebuild the real app)

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
- [x] Timeline key and render job
- [x] Stacking, callouts and credits
- [x] Warnings, refusals and out-of-date reasons
- [x] Sources section
- [x] Identity check and throwaway render (the identity check is by construction; the snapshot comparison on the real database was not run, see below)
- [x] Standard checks
- [ ] Owner: real app rebuilt

**Completion notes.**
- **No migration.** The clips, items and decisions already existed.
- **Modules:**
  - `services/story_render_plan.py`: `FootageClipSource`, `FootageSource`, `SceneSource.footage`, `_footage_entries` (modelled on `_overlay_entries`), `_split_at_footage`, the warning code `footage_without_clip` and the optional key `footage_overlays` (the timeline version stays 6). `_shift_timeline` moves its frames and times. Footage is not given to `_sound_moments`, so it has no sound effect.
  - `services/story_renders.py`: `footage_clips_now`, `_footage_sources`, `footage_reasons`; `scene_sources` fills `SceneSource.footage` only when `with_overlays` is on, so `next_render_sources` and `timing_sources` leave footage out and the music placement is untouched. `services/scene_renders.py` has `_Context.footage` and calls `footage_reasons` for its own scene.
  - `jobs/render_story.py` (the scene render shares it): `FootageOverlay`, `_parse_footage_overlays`, `probe_footage`, and footage laid **first** in each shot's overlays, so the order is footage, callouts, cards, split evidence, graphic overlays. `_with_footage_credits` merges the credits into the source line events of the ASS file.
  - `services/footage_clips.credit_line` (pure) gives the credit line of a piece.
  - Sources section: `youtube_sources.footage_piece` and `block(..., footage=)`, `youtube_draft_writer.with_sources(..., footage)`, `youtube_draft._footage_sources` (reads the item keys of the render's frozen `footage_overlays`), the job input `footage_sources` (read as `[]` for an older job) in `jobs/write_youtube_draft.py`.
  - The API's `WarningCode` and `frontend/src/api/schema.d.ts` have `footage_without_clip` (edited by hand to match what the OpenAPI output gives).
- **Planning decided:**
  - **Credits:** the optional string `credit` on each `footage_overlays` entry, not a new top-level key and not the `source_lines` key, so footage stays out of the evidence keys (FT-2). It is on screen for the piece's own span. An owner's file: `Video: <credit>` or `Photo: <credit>` and nothing without a credit. An agent's piece: `Video`, `Photo` or `PDF: <publisher>`, with the licence added for the `commons` tier. A page: none (its address is in the browser frame). Agent text is cleaned (no braces, backslashes or angle brackets) and cut to 60 characters per part.
  - **Callouts over footage:** `callout_render` is unchanged. For a continuous explainer the plan gives it the shot spans split at the footage edges and the presenter spans with the footage taken out, so a callout that starts over a video or a photo is drawn as over B-roll. A page or a PDF span is added to `graphic_spans`, so a callout that starts there is dropped with the usual warning.
  - **A footage clip with no file:** a scene render leaves the piece out with the warning `footage_without_clip`; a full render is refused with "This footage has no clip yet: ... Draw it in the Draw the footage step."
  - **Out of date:** a piece removed, with no current clip, drawn again, or added with a ready clip (story renders and scene renders).
  - **Sources section:** footage sources follow the evidence's, each address once and not repeating an evidence address. A video's address is `&t=` the second of the source video where `use` starts (the owner's moved `use` if there is one, through `footage_clips.video_times`). An owner's file, or a piece with no address, is listed by its credit line only, and not at all without one. The footage sources are not shown to the model, so its "what we checked" note stays about evidence.
- **Checked** on a throwaway database and data folder (alembic to head in `/tmp`, no paid call, the real app on port 5480 was not touched; the scripts were removed):
  - A scene render through `RenderSceneHandler` with three placeholder shots and synthetic clips: a red video piece over 1 to 3 s and a green page piece over 5 to 7 s showed full screen; the frames outside them were the placeholders; the credit line `Video: The White House` was drawn in the top margin; a third piece with no clip gave `footage_without_clip` and was left out. The video had the 288 frames of the scene.
  - A plan with no footage has no `footage_overlays` key; a scene that starts later has its entries shifted (frame 24, 1000 to 3000 ms) and read back by `parse_timeline`; `_footage_entries` returns the missing label for a full render.
  - `credit_line` (owner with and without a credit, commons, page), `footage_piece`, `block` with and without footage (the text without footage is identical), `footage_reasons` for the five cases.
  - `ruff check`, `ruff format --check`, `npm run typecheck` and `npm run lint` (frontend).
- **Not done:** the snapshot comparison on the real database (the SHA-256 of the frozen timeline and the ASS file, and the count of `generate_shot` jobs, for every project without footage, before and after) needs the owner's go-ahead. By construction a project without footage reads no footage tables (`piece_state` returns at once), writes no `footage_overlays` key, passes the callout resolver the same lists and gets the same Sources text. A render with a card or a callout over footage, and `RenderStoryHandler` on a full project (with a voice take), were not run. The music placement staying current is by construction (`with_overlays=False` leaves footage out). The backend of the real app must be rebuilt.

### FTG-007 — The research brief and the waiting step

**Status:** Completed (2026-11-28; the owner still has to rebuild the real app and try the panel in a browser)

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
- [x] Rounds, brief and README
- [x] Waiting step and needs
- [x] Continue without footage (and a per-mark Undo)
- [x] Footage panel
- [x] Project deletion
- [x] Standard checks
- [ ] Owner: real app rebuilt (`docker compose up --build -d`, never `down -v`) and the Footage panel tried once in a browser

**Completion notes.**
- **No migration.** The tables (`footage_round`, `footage_import`, `footage_decision`) and the job type `write_footage_brief` come from `0106`.
- **Modules:**
  - `services/footage_rounds.py`: the brief (`brief_marks`, `build_brief`, `readme_text`), the folder files (`write_round_files`, `discard_round`, `remove_project_folder`, the same guards as the evidence folder), `state()` (memoized; a project without footage reads no tables), `refusal`, `awaiting_text`, `is_done`, `start_brief`, `make_round`, `needed_seconds`, `continue_without_footage` and `undo_no_footage`. From the evidence layer it imports only the pure helpers `sentence_spans` and `topic_of` (FT-2).
  - `services/footage_decisions.set_no_footage`: one decision version for any number of marks; nothing is stored when nothing changes.
  - `jobs/write_footage_brief.py` (`local`, `start_again`), the phase label `WRITING_FOOTAGE_BRIEF` and the handler registration.
  - Step `footage` ("Gather the footage", needs `story_bible` and `footage_marks`, after `evidence`); `render` needs it, `scene_render` does not. `_evaluate_footage` is a copy of the evidence step's (a target with `awaiting`, a run pauses with `waiting_for`). The board shows it `off` through `FOOTAGE_STEPS`, in the `story` group.
  - API `api/footage.py`: `GET /projects/{id}/footage`, `POST .../footage/brief`, `POST .../footage/continue-without`, `DELETE .../footage/marks/{mark_id}/no-footage`.
  - Project deletion removes `footage/<id>/` after the evidence folder.
- **Frontend:** `api/footage.ts`, `FootagePanel.tsx` (counts, the "Waiting for you" alert, each mark with its state and an Undo on a skipped one, the folder and prompt with Copy, Write the brief, Continue without footage), `StepPanel.tsx` (`footage`). The mark and file mutations also refresh the footage query. `schema.d.ts` was regenerated from the app's OpenAPI (additions only).
- **Planning decided:**
  - **When a mark is covered**, in this order: a usable file of the owner's is among the pieces shown on it (`owner_file`); the owner chose "no footage here" (`no_footage`); the newest reviewed round that holds it unchanged (`reviewed`). A round is **reviewed** when it has an import and its id (`r2`, or the number 2) is in `reviewed_rounds` of the owner's decisions. FTG-012 must write that list with ids like `r2`.
  - **A round holds a mark unchanged** when the brief entry has the same `id`, `origin`, `text`, `sentence`, `note` and `kind_hint`. `context` and `needed_s` are left out, so an edit elsewhere in the story or a new recording forces no round.
  - **`needed_s`** is worked out only when a brief is written (not on every read): for each scene whose take is timed, from the first covered word's start to the last one's end (the matching FTG-004 uses, `graphic_suggestions.scene_suggestions`), summed over the scenes; a mark with no timed word is estimated at 2.5 words a second, to 0.1 s.
  - **Undecided GLM proposals and marks whose words changed** block the brief, Continue without footage and the step (as for evidence). "Keep or drop the N footage marks GLM proposed." is the wait text.
  - **"No footage here"** is stored by mark id and holds until undone, even if the note changes. An owner's file covers a mark before it, so Undo on such a mark only clears the flag.
  - **The README** tells the owner to run `tools/footage-skill/install.sh`. FTG-010 decides the install script and must keep that path or change the README text (`footage_rounds.readme_text`).
  - **Undo** was added to the Scope at the owner's request (one decision version per click).
- **Checked** on a throwaway database and data folder with the app run on another port (no paid call, the real app on port 5480 was not touched; the scripts and the folder were removed):
  - The brief has the §4.5 fields, files and rules; `needed_s` estimated for untimed marks (7 words gave 2.8) and taken from timings with stand-in takes (3.4 s); the sentence and the sentences around it are right.
  - A mark with an owner's file is covered and a repeat brief is refused while the round holds the waiting marks unchanged. With round 1 reviewed, changing one note made only that mark wait, and round 2 held only it. Its wait text says the 2 covered marks stay.
  - The step view has `awaiting` while a mark waits and is done after Continue without footage; Undo makes the mark wait again; a second Undo gets 422 and an unknown mark 404. Each change made one decision version.
  - An undecided proposal blocks Continue and the brief with the sentence.
  - With footage off, the state reads nothing, the step is done with no `awaiting` and a brief is refused.
  - Deletion removed only the project's folder (another project's stayed), did nothing twice, and refused a symlink (its target stayed).
  - `render` needs `footage`, `scene_render` does not.
  - `ruff check`, `ruff format --check`, `npm run lint` and `npm run typecheck` pass.
- **Not checked:** the panel in a browser (typecheck and lint only); a real run of the pipeline to the `waiting_for` pause (the step view was evaluated directly; the pause logic is the evidence step's, unchanged); a video of the owner still being prepared leaves its mark waiting until the file is ready, and the panel refreshes then only on the next load or change (no polling for that). The backend of the real app must be rebuilt.
- **Deviation from Scope:** none.

### FTG-008 — The capture tool: images, pages and PDFs

**Status:** Completed (2026-11-28; the owner still has to run `uv sync` for the new command and check one Wikimedia image with their own contact, see the notes)

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
- [x] Command, brief reader and result writer
- [x] `image`, `page`, `pdf`
- [x] `report`, `remove`, `validate`
- [x] Real captures and refusals

**Completion notes.**
- **No migration, no backend change.** All work is in `tools/evidence-capture`; the evidence commands behave as before.
- **Modules** (new package `visio_evidence_capture/footage/`, console script `visio-footage-capture` in `pyproject.toml`, `TOOL_VERSION` "1"):
  - `__init__.py`: the schemas, the allowed values of §4.6 and the limits (`PAGE_HEIGHTS` 4, `MAX_IMAGE_PIXELS` 40 M, `LOW_RES_LONG_SIDE` 1280, `PDF_LONG_SIDE_PX` 4096).
  - `rounds.py`: `FootageRound` (reads `brief/footage.json`, mark ids `f<n>`, piece ids `p1` to `p9`, `max_pieces` from the brief), `Described`, `piece_entry`, `store_piece`, `remove_piece` and `report` (`found` needs a piece; `not_found` and `blocked` need none; `not_found` needs an attempt).
  - `image.py`, `page.py`, `pdf_page.py`, `validate.py` and `cli.py` (`image`, `page`, `pdf`, `report`, `remove`, `validate`).
  - Shared code touched: `netguard.py` (`fetch_pdf`'s download loop became `_fetch`, with the same checks and messages; `fetch_image` added) and `rounds.py` (an evidence round told it is a footage round). Evidence's private helpers in `web.py`, `pdf.py` and `validate.py` are imported, not moved.
- **Planning decided:**
  - **Module split:** as above, one module per command.
  - **`page` stitches viewport strips** with the evidence `_context_screenshot` from the top of the page (Playwright's one full-page screenshot is very slow on tall pages). A page shorter than one screen is captured one screen tall. `PAGE_HEIGHTS` is 4.
  - **Focus below the captured screens is refused** (owner's choice), with the screen number and the page's height in screens. The contract stays "the image starts at the page's top".
  - **A PDF `image` is the whole page**, because FTG-005's `pdf_plan` draws the whole page and zooms itself. A scan with no text layer is accepted with no focus.
  - **Images:** the type is read from the first bytes; the header is read before decoding so more than 40 M pixels is refused; WebP is stored as PNG; a JPEG with an EXIF orientation is stored upright.
- **Deviations from Scope:**
  - A turned JPEG is saved again as a **JPEG** (quality 95), not PNG as the plan said: the same photo as PNG is often over the 20 MB limit.
  - **Wikimedia refuses the tool's browser-like request** from Python (403, "robot policy"); a request that names the tool and gives a contact is accepted. `image` therefore reads `VISIO_FOOTAGE_CONTACT` (an email address or a website) and sends it in the User-Agent; on a 403 from a Wikimedia host with none set, the message says to set it. The owner must set it to their own contact. FTG-010 should put this in the skill's setup text.
- **Checked** in throwaway round folders in `/tmp` (removed afterwards; no paid call, the real app was not touched):
  - Landscape and portrait rounds written by hand in the §4.5 shape. Real captures: an image from NASA (public domain, 1920x1920 JPEG); the English Wikipedia page "Pelican" with no focus and with the focus "large water birds" (2560x5760 landscape, 1440x10240 portrait, the first 4 screens), a short page (example.com); a page of the arXiv paper 1706.03762 with and without a focus (3166x4096). The focus box was drawn over the stored page and PDF images and sits exactly on the words. `validate` passed on the landscape and portrait rounds, with `blocked` and `not_found` marks.
  - Refusals: `http://127.0.0.1`; an address that is a web page, not an image; a focus not found on a page (the nearest text listed) and on a PDF page; a focus on screen 17 of a 40-screen page; a page past the end of the PDF; a fourth piece in a mark of 3; a bad piece id; an unknown mark; `found` with no piece; `not_found` with no attempt; a footage command in an evidence round and the reverse. Image rules checked on made-up pictures: 7000x6000 pixels (refused before decoding), a WebP made into PNG, a turned JPEG made upright, an untouched JPEG keeping its bytes, a converted picture over 20 MB refused.
  - `validate` caught a changed byte (SHA-256), a changed text copy, a file with the wrong type, a wrong `image_px`, a focus rectangle outside the image and a link in a mark folder.
  - Evidence regression: a `web` and a `pdf` capture, `report` and `validate` on an evidence round gave the same output as before.
  - `ruff check` and `ruff format --check` in `tools/evidence-capture`.
- **Not done:** a Wikimedia Commons image (needs the owner's `VISIO_FOOTAGE_CONTACT`, see the deviation); Simon Willison's post and the other Appendix A pages were not captured (Wikipedia and arXiv stood in); an image over 20 MB while downloading was not tried (the cap is `fetch_pdf`'s, the same loop); an image whose `page_url` leads to a private address was not tried (`check_url` is used).

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
| 2026-11-28 | FTG-003 | Completed: the owner's photos and videos on a mark (upload API, `prepare_footage_file` job, decision versions, files section on the mark card). No migration. |
| 2026-11-28 | FTG-004 | Completed: footage placed on read (`services/footage_placement.py`, `footage_decisions.shown_marks`, three new `SceneEntry` fields, notes on the `footage_marks` step). No migration, no API or UI change. |
| 2026-11-28 | FTG-005 | Completed: the footage clip and its preview (`services/footage_clips.py`, `jobs/render_footage_clip.py`, FFmpeg cut rules, the motion `Footage` composition, the step `footage_clips`, the preview route and button). No migration. The motion image must be rebuilt. |
| 2026-11-28 | FTG-006 | Completed: footage in the render (`footage_overlays` timeline key, `render_story` lays it first under callouts and cards, credit lines, `footage_without_clip`, out-of-date reasons, footage in the Sources section). No migration. The backend of the real app must be rebuilt. |
| 2026-11-28 | FTG-007 | Completed: the research brief and the waiting step (`services/footage_rounds.py`, `jobs/write_footage_brief.py`, the step `footage`, Continue without footage, `FootagePanel.tsx`, `api/footage.py`). No migration. The backend of the real app must be rebuilt. |
| 2026-11-28 | FTG-008 | Completed: `visio-footage-capture` (`image`, `page`, `pdf`, `report`, `remove`, `validate`) in `tools/evidence-capture`, package `visio_evidence_capture/footage/`. No migration, no backend change. Wikimedia images need `VISIO_FOOTAGE_CONTACT`. |
