# Vision Studio — Evidence Layer and Local Files Phases

The **evidence layer** shows proof on screen when an explainer says something that can be checked: a price, a figure from a report, something a person or a company said. The owner marks the lines that need proof, GLM proposes more, and a research agent (Cursor or Claude, run by the owner) finds a source for each claim and captures it with a capture tool that lives in this repository. The app imports the result, checks it, and the owner reviews every piece of evidence. Accepted evidence becomes an **evidence shot**: a screenshot of the source, zoomed to the quote, with the quote highlighted, drawn by code on the words it proves.

This document also moves the media files out of the Docker volume into a folder on the Mac (§3.1). That folder is where the owner sees and manages the files, and it is also where the app and the research agent hand work to each other.

- The conventions of `Implementation_phases.md` (§3.3 to §3.5, §6) apply unchanged. Table and column details go in `DATABASE_STRUCTURE.md`. The newest migration when this was written was `0097`.
- Written 2026-11-13, from a design discussion with the owner. Facts about the data volume and the Mac (sizes, free space, tools) were measured that day.

---

## How to use this document

### Opus → Sonnet workflow

1. Pick a phase whose status is **Not Started** and whose hard dependencies are met (§5).
2. Give Opus this document, `Implementation_phases.md` and a request such as:

   > Plan **EVD-0XX — <title>** only. Respect its Scope and Out of scope, the decisions in §3 and the design in §4 of `Evidence_layer_implementation_phases.md`, the conventions in §3.4 and §3.5 of `Implementation_phases.md`, and the Completion notes of every phase it depends on. Resolve every "Planning decides" item explicitly in the plan. Do not pull work from later phases. List the files to change, the API and UI changes, the settings, and how each Verification criterion will be checked.

3. Give the resulting plan to Sonnet for execution.
4. When the phase is done, update it as described in §7. Fill in its **Completion notes**: later phases read them to learn the real names of modules, tables, job types, endpoints and settings.

### Reading a phase

Every phase has the same fields: Objective, Current state (with starting points in the code), Scope, Out of scope, Dependencies, Expected outcome, Verification criteria, Completion checklist and Completion notes. Items marked **Planning decides** are left open on purpose and must be settled in the plan.

**Owner phases** (STOR-002, STOR-003, EVD-010) are done by the owner. The agent prepares the exact commands, explains each one, runs nothing destructive without the owner's explicit go-ahead, and records the results.

### Why some phases can run in parallel

- **One migration for the evidence layer.** EVD-001 creates every table, column and job type the layer needs (§4.8). Later evidence phases add no migration, so phases that run at the same time never fight over Alembic revision numbers. If a later phase still needs one, it takes the next free number and says so in its notes. The storage phases need no migration.
- **Contracts are in this document.** The folder layout (§4.3), the brief the app writes (§4.4) and the result the agent writes (§4.5) are fixed here, so the capture tool and the skill (EVD-004, EVD-005) can be built beside the backend phases. A phase that must change a contract updates the section here and says so in its notes.

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

For an explainer, the owner:

1. chooses on the create form whether the project has an evidence layer (on by default);
2. selects, in the script, the words that need proof, with an optional hint ("must be the SEC filing");
3. lets GLM propose other claims worth proving, and keeps or drops each one;
4. lets the pipeline run: everything that does not need evidence keeps going, and shot planning waits;
5. opens the round folder on the Mac, runs Cursor or Claude with the evidence skill, and the agent researches each claim on its own, capturing screenshots with the capture tool, and says clearly where no proof was found;
6. presses Import: the app checks every result and copies the files into its storage;
7. reviews every claim: accepts or rejects each piece of evidence, chooses which ones to show, and previews each as a short video;
8. presses Continue: shot planning puts an evidence shot on the words each claim covers, and the render shows them.

All media files, the evidence round folders included, live in a folder on the Mac that the owner can open in Finder.

---

## 2. Current state

What exists and is reused:

- **Storage.** Every file goes through `services/storage.py` (`Storage`). Names are generated (`<project_id>/<32 hex>.<ext>`, or `lab/<32 hex>.<ext>`), paths are checked to stay inside the media folder, and the database keeps only the **relative** path. An upload or a render is written to `tmp_dir` first and moved into place with `Path.replace` (`Storage._move`), which is an atomic rename and **only works when `tmp` and `media` are on the same mount**. `core/config.py` derives everything from `DATA_DIR` (default `/data`): `app.db`, `media/` and `tmp/`.
- **Docker.** `docker-compose.yml` mounts the named volume `visio-studio_data` at `/data` in `backend` (read-write) and in `frontend` (read-only). nginx serves `/media/` from `alias /data/media/` (`frontend/nginx.conf`). The backend runs as uid 10001 (`backend/Dockerfile`). The database runs in WAL mode (`db/session.py`, `PRAGMA journal_mode=WAL`). `.gitignore` already ignores `data/`.
- **Measured on 2026-11-13.** Media 25 GB in 9,399 files (13 GB in `media/lab`, the rest in about 60 project folders). `app.db` 1.5 GB plus a 227 MB WAL. Three old `backup-before-000N.db` files of about 3 MB each. After cleaning Docker's build cache the Mac had about 40 GB free. Most tables that store a media path also store its `sha256` (`asset`, `shot_take`, `speech_unit_audio`, `story_render`, `scene_render`, `voice`, `voice_recording`, `lab_image`, `lab_video_run`, `lab_voice_run`, `lab_music_run`, `lab_music_source`). A few do not (`shot_graphic`, `lab_graphic_render`, `callout_graphic`, `thumbnails`, `av_lab_test`).
- **The pipeline.** `services/story_pipeline.STEPS` lists every step with its `needs`. A step can be **skipped as complete** when it does not apply (`callout_plan`, `graphics`, the music steps; see their adapters in `services/story_pipeline_targets.py`, for example `_evaluate_callout_plan`). The board statuses are in `services/pipeline_board.py` (`off`, `running`, `attention`, `out_of_date`, `done`, `waiting`, `ready`). A run stops and says why when a target is blocked and nothing else can go on (`jobs/story_pipeline._stop_reason`). Review points (`services/review_points.py`) pause a run after a group of steps until the owner presses Continue, but only after steps the run itself made something in.
- **Marking words in the script.** Graphic suggestions (`services/graphic_suggestions.py`) are `{id, start, end, text}` code-point ranges of `script_text`, snapped to whole words (`normalise`), kept right when the script is edited (`reanchor`), and mapped onto a voice take's words (`take_suggestions`). They are stored in `project.graphic_suggestions`, set with `PUT /api/projects/{id}/graphic-suggestions`, and edited in `components/story/GraphicSuggestions.tsx`. They exist only for a continuous explainer with graphics on.
- **Cut planning.** `services/cut_planning_writer.py` plans a continuous explainer's shots on the take's words. A project with graphics on may plan `graphic` shots (`GRAPHIC`, at least `SHORTEST_GRAPHIC_S` = 3.0 s), drawn by code and never by H3. The owner's graphic suggestions are wishes: the planner follows them or lists them as declined with a reason.
- **Graphic shots.** The `graphic_briefs` and `graphics` steps, the tables `shot_graphic_brief`, `shot_graphic` and `shot_graphic_choice` (migration `0080`, `DATABASE_STRUCTURE.md` §4.76 to §4.78), and the `render_shot_graphic` job. A graphic shot's video is a clip of the timeline; `scene_render`, `music_placement` and `render` wait for `graphics`.
- **The motion service.** Remotion and headless Chrome (`motion/`), with no internet, no volume and no secrets, reachable only by the backend on `motion_net`. A render is asked for with JSON props, and the request body limit is 1 MB (`motion/src/server/index.ts`, `BODY_LIMIT_BYTES`). No composition takes an image today. The resolved props carry `safe_area` and `caption_zone` (`motion/src/types.ts`).
- **Model calls.** GLM-5.3 on Bitdeer (`services/llm_target`), called through `jobs/llm_call.ask_model`. The callout plan is the closest pattern for one project-wide model call reviewed by the owner (`services/callout_plan.py`, `callout_plan_writer.py`, `jobs/write_callout_plan.py`, `components/story/CalloutPlanPanel.tsx` and `CalloutPlanEditor.tsx`).
- **Helpers.** `services/number_words.numbers_in(text)` reads digits and English number words. `callout_plan_writer.locate_phrase(words, phrase)` finds a rough phrase among words.
- **Project switches.** `project.caption_mode`, `project.callouts` and `project.graphics`, set on the create form (`components/projects/CreateProjectModal.tsx`) and in settings (`ProjectSettingsForm.tsx`), checked in `services/projects.py`. A continuous explainer is told by `speech_synthesis.is_continuous(project)` (`projects.VOICE_CONTINUOUS`).
- **Outbound calls.** `core/outbound.py` is the backend's only HTTP path: no redirects, size limits, the Bitdeer key attached only for Bitdeer. It is not meant for fetching arbitrary pages, and the evidence layer does not use it for capture.
- **The Mac.** uv 0.12.5, Python 3.13.7 and Node 24.1.0 are installed.

What does not exist: anything about claims or evidence; a pipeline step that waits for something the owner brings from outside the app; any image input to the motion service; any files folder outside Docker.

---

## 3. Decisions

### 3.1 Local files

| # | Decision |
|---|----------|
| S-1 | Media and the temporary working files move to a folder on the Mac, chosen in `.env`. The suggested folder is `~/VisioStudioData`: outside the repository, so Cursor does not index 25 GB of video. |
| S-2 | **The database stays in the Docker volume.** SQLite in WAL mode on a Docker Desktop bind mount risks locking errors and corruption, and rows cannot be managed as files anyway. A visible copy can be added as snapshots (STOR-004, optional). |
| S-3 | `media` and `tmp` are on **one mount**, because `Storage` moves finished files into place with an atomic rename, which fails between two mounts. A Mac folder mounted over `/data/media` alone is therefore not enough. |
| S-4 | Stored names and relative paths do not change, so no database row changes. The owner may open, play and copy files from Finder. **Renaming, moving or deleting a file in Finder breaks the app**, because the database points at that exact name. |
| S-5 | **Nothing is deleted by the move.** The old copy stays in the Docker volume, hidden behind the new mount, until the owner removes it in STOR-003. `docker compose down -v` is never used. |
| S-6 | The frontend container sees only the media folder, read-only, no longer the whole volume with the database. |

### 3.2 Evidence layer

| # | Decision |
|---|----------|
| EV-1 | The evidence layer is for **explainers with a continuous voice**, the same projects that can have graphic shots, because evidence shots are planned by the cut planner on the take's words. A story project and a non-continuous explainer are unchanged. (Open question Q-E1.) |
| EV-2 | A project switch, `evidence`, is chosen on the create form and is **on by default** for those explainers. It can be changed later in settings. With it off, the evidence steps are skipped as complete and every prompt and plan stays exactly as it is today. |
| EV-3 | The owner marks the words that need proof. GLM then proposes other claims, each with a reason. The owner keeps or drops GLM's proposals before research. The owner's own marks are always kept. |
| EV-4 | **Phase 1 research is manual.** The app writes a research brief into a round folder. The owner runs Cursor or Claude there with the evidence skill. The agent researches **each claim on its own** and writes one result per claim. |
| EV-5 | **The agent never writes coordinates or screenshots by hand.** Only the capture tool (EVD-004) makes screenshots and highlight rectangles, and only after it has found the exact quote in the source. A wrong source cannot produce a highlight. |
| EV-6 | "Not found" is an explicit, acceptable result. Every claim gets a status (`found`, `partial`, `not_found`, `contradicted`, `blocked`), and a claim without proof lists what was tried. |
| EV-7 | The round folder is **untrusted input**. The import checks every file and copies the usable ones into storage under generated names. The agent's file names and text are never used as paths or shown as HTML. |
| EV-8 | **Nothing reaches the video without the owner's acceptance.** The owner reviews every piece of evidence, can reject any, and chooses which accepted ones are shown, and in what order. |
| EV-9 | **Only the consumers wait.** Shot planning and the steps that draw and render evidence shots need the evidence step. Everything before them (Story Bible, speech, voices and the rest) keeps running while the owner does the research. |
| EV-10 | On video, evidence is a **full-screen evidence shot** drawn by the motion service: a clip of the timeline like a graphic shot, never made by H3. The highlight is drawn at render time from the stored rectangles; the stored screenshot stays clean. The owner can preview each clip from the review screen. |
| EV-11 | The agent runs in the round folder, not in the repository (which holds `.env`). The skill tells it to treat everything it reads on the web as data, never as instructions, and to write only inside the round's `results/` folder. |
| EV-12 | Phase 1 covers **web pages and PDFs**. Evidence cards over presenter shots, text-only source lines, data charts, automated research and video evidence are later phases (EVD-011 to EVD-015). |

---

## 4. Design

### 4.1 How it works

```text
create project (explainer, continuous voice, evidence on)
 -> owner marks the words that need proof in the story editor            EVD-002
 -> GLM proposes more claims (one call); owner keeps or drops each        EVD-002
 -> step "Gather the evidence": the app writes the brief                  EVD-003
      ... the run keeps going on every step that does not need evidence,
          then stops and says it is waiting for evidence
 -> owner runs Cursor or Claude with the evidence skill in the round folder   EVD-005
      the agent searches, picks the exact quote, calls the capture tool   EVD-004
 -> owner presses Import: checks, files copied into storage               EVD-006
 -> owner reviews: accept, reject, choose what to show, preview clips     EVD-007, EVD-008
 -> owner presses Continue
 -> cut planning plans an evidence shot on each claim's words             EVD-009
 -> each evidence shot is drawn at its exact length, then the render      EVD-008, EVD-009
```

### 4.2 Where it sits in the pipeline

Changes to `services/story_pipeline.STEPS` (step keys and labels are suggestions; planning decides the final names):

- **`evidence_claims`**, "Propose the evidence claims" (story-wide, no needs; added by EVD-002). It asks GLM once for more claims when GLM has never answered for the project (done once an `ai` claim list version exists), and is skipped as complete when evidence does not apply (EV-1, EV-2). Asking again is the owner's click. EVD-003's `evidence` step needs it.

- **`evidence`**, "Gather the evidence" (story-wide, EVD-003; group `story`, needs `story_bible` and `evidence_claims`). It needs no model step: it works from the saved script and the claim list. It is complete when the newest round has been imported and reviewed, and the claim list has not changed since that round's brief. It is skipped as complete when evidence does not apply (EV-1, EV-2) and when no claim counts. It **waits for the owner** (a target with `awaiting`, board status `owner`, a run pause `waiting_for`), it is not a job.
- **`shot_plans`** gains `evidence` in its needs (EVD-003, done).
- **`evidence_clips`**, "Draw the evidence shots" (per scene, EVD-009). It needs `shot_plans` and makes one clip per evidence shot at the shot's exact length. It is skipped as complete when evidence does not apply.
- **`scene_render`**, **`music_placement`** and **`render`** gain `evidence_clips` in their needs (EVD-009), as they already need `graphics`.

No other step changes. A project without evidence runs exactly as it does today.

### 4.3 The files folder

```text
~/VisioStudioData/                  host folder from .env (S-1), one mount in the backend (S-3)
  media/                            stored media, the same names as today; nginx serves it at /media/
  tmp/                              working files, cleared on start as today
  evidence/<project_id>/<round_id>/
    brief/
      claims.json                   written by the app (§4.4); the agent only reads it
      README.md                     how to run the agent for this round, with a ready-to-paste prompt
    results/
      <claim_id>/
        result.json                 one per claim (§4.5)
        e1.png, e1-context.png, e1.txt, e1.pdf, ...   files made by the capture tool
  db-snapshots/                     only with STOR-004
```

The `evidence/` folder is never served by nginx. The import copies what it accepts into `media/` under generated names (EV-7). The round folder itself is left as the agent wrote it, as a record.

### 4.4 The brief: `brief/claims.json` (version 1)

```json
{
  "schema": "visio.evidence.brief",
  "version": 1,
  "round_id": "r1",
  "project": {
    "id": 70,
    "title": "The project's name",
    "topic": "One line from the Story Bible: what the video is about",
    "orientation": "landscape",
    "today": "2026-11-13",
    "language": "en"
  },
  "rules": {
    "max_evidence_per_claim": 3,
    "preferred_domains": [],
    "blocked_domains": []
  },
  "claims": [
    {
      "id": "c1",
      "origin": "owner",
      "text": "the exact words of the script that need proof",
      "sentence": "the whole sentence those words are in",
      "context": "the sentences around it",
      "hint": "the owner's note, or an empty string",
      "kind_hint": "number"
    }
  ]
}
```

- `origin` is `owner` or `glm`. `kind_hint` is `number`, `quote`, `statement`, `event` or `other`.
- Claim ids are stable inside a project: a claim keeps its id in later rounds while its words are unchanged.
- `today` lets the agent read "now" and "this year" correctly. `orientation` tells the capture tool which viewport to use (§4.7).

### 4.5 The result: `results/<claim_id>/result.json` (version 1)

```json
{
  "schema": "visio.evidence.result",
  "version": 1,
  "round_id": "r1",
  "claim_id": "c1",
  "status": "found",
  "summary": "One or two plain sentences: what the sources say, set against the claim.",
  "attempts": [
    {"what": "the search or the address tried", "outcome": "why it was not used"}
  ],
  "evidence": [
    {
      "id": "e1",
      "kind": "web",
      "relation": "supports",
      "source_tier": "primary",
      "source": {
        "url": "the address the agent gave",
        "final_url": "the address after redirects, written by the tool",
        "publisher": "Who published it",
        "title": "The page or document title",
        "author": null,
        "published": "2026-10-03",
        "retrieved_at": "2026-11-13T15:02:11Z",
        "archive_url": null
      },
      "quote": "the exact words as they appear in the source",
      "what_it_says": "A plain sentence, including any difference from the claim.",
      "capture": {
        "tool": "visio-evidence-capture",
        "tool_version": "1",
        "image": "e1.png",
        "image_px": [2560, 1440],
        "context_image": "e1-context.png",
        "text_copy": "e1.txt",
        "source_copy": null,
        "page": null,
        "viewport": {"width": 1280, "height": 720, "device_scale": 2},
        "rects": [[0.12, 0.40, 0.61, 0.035], [0.12, 0.44, 0.33, 0.035]],
        "sha256": {"e1.png": "...", "e1-context.png": "...", "e1.txt": "..."}
      },
      "agent_notes": ""
    }
  ]
}
```

- **`status`** of the claim: `found` (at least one source supports it), `partial` (supports part of it, or a slightly different number), `not_found` (nothing usable within the search budget; `attempts` lists what was tried), `contradicted` (a good source says otherwise), `blocked` (the right source exists but could not be captured: paywall, login, bot check).
- **`relation`** of one piece of evidence: `supports`, `partly_supports`, `contradicts` or `context`. **`source_tier`**: `primary` (the company, the person, the official body or the original publication), `secondary` (a reputable outlet reporting it) or `other`.
- **`kind`** is `web` or `pdf` in version 1. `video` and `data` are kept for later phases.
- **`capture`** is written only by the capture tool (EV-5). `rects` are `[x, y, width, height]` as fractions of `image`, one per line of the quote. For a PDF, `page` is the page number counted from 1, and `source_copy` is the copied PDF. For a web page, `text_copy` is the page's text as the tool read it.
- `evidence` is empty for `not_found` and `blocked`.
- **Added by EVD-004** (no break of the contract above):
  - `capture.context_box`: `[x, y, width, height]` as fractions of `context_image`, where `image` sits inside it (EVD-008 zooms from the context to the quote with it). For a PDF it is clamped to the page.
  - A PDF capture has `viewport: null` and `render_scale` (pixels per point), and also a `text_copy` (the page's text as the tool read it, for the review). Check 3 of a PDF still reads the PDF.
  - `image` always has the video's shape: a web capture is `viewport * device_scale` (2560x1440 landscape, 1440x2560 portrait); a PDF crop is 2560x1440 or 1440x2560 unless the scale limit of 8 makes it smaller.
  - The tool writes the whole `result.json`. Before `report` is run, `status` is `null` and `summary` is empty, and `validate` fails on them.
  - `quote` is the words as the source has them (white space made single spaces), except for a PDF quote that joins a hyphenated line end or has a U+FFFE hyphen, where it is the agent's words.
  - The quote rules (§4.6 check 3) are in `tools/evidence-capture/src/visio_evidence_capture/text.py` (`normalise_with_map`, three line-hyphen modes) and `pdf.find_in_text`. **EVD-006 must repeat them exactly.**

### 4.6 The checks on import

The import (EVD-006) checks every piece of evidence in this order. The capture tool's `validate` command (EVD-004) applies checks 1 to 4 too, so the agent can fix problems before the owner imports.

1. **Shape.** The schema and version are known, the round and claim ids match the brief, and every value is one the contract allows.
2. **Files.** Every file named is inside its claim's folder and is a regular file (no link). Its type is checked from its content (PNG, JPEG, PDF, UTF-8 text), its size is within limits, and its SHA-256 matches the one recorded.
3. **Quote.** After normalising (NFKC, curly quotes, spaces, soft hyphens), the quote is found in the text copy (web) or in the PDF's text on `page` (pdf).
4. **Rectangles.** Each lies inside the image, is not empty, and there are no more than a set number of them.
5. **Numbers.** A number the claim says (`numbers_in`) that the quote does not say gives a **warning**, never a refusal.
6. **The owner.** Accepts or rejects (EVD-007).

A failure in checks 1 to 4 makes that piece of evidence unusable, and the review screen shows why. (As built in EVD-006, the import is a little stricter than this list and than `validate`: an image must be a PNG, the addresses must be http or https, text values have the tool's length limits, and a link in a claim folder makes every piece of that claim unusable.) The checks prove that the quote is really in the captured source. They do not prove that the source is right: the owner's review does that.

### 4.7 The evidence shot on video

- **What it shows.** It opens on the screenshot with some context, zooms in to the quote's rectangles, a highlight sweeps across the quote in the video's accent colour, and it holds there. A source badge names the publisher and the date, and the page for a PDF.
- **Capture size.** A landscape project is captured at a desktop viewport and a portrait project at a phone viewport, where the text is naturally large. Planning in EVD-004 decides the exact sizes.
- **Readability.** After the zoom, the quote's text must be at least a minimum height on the output frame (EVD-008 decides the value). Below it, the review card shows a warning.
- **Length.** The clip is as long as its shot. The cut planner gives an evidence shot at least the longer of a floor (3 s, like a graphic shot) and the time needed to read the quote (EVD-009 decides the reading rate).
- **Captions** keep showing in their zone, and the composition keeps the highlight out of the caption zone (`caption_zone`). What happens to a callout during an evidence shot is decided in EVD-009.
- **Preview.** From the review screen, the owner can render a preview of a fixed length (EVD-008). The real clip is drawn at the shot's exact length after shot planning (EVD-009).

### 4.8 What the one migration creates (EVD-001)

Planning in EVD-001 decides the names and the exact split. The layer needs:

- `project.evidence`, a boolean (EV-2);
- the **claim list**: versions of the owner's marks, GLM's proposals and the owner's keep or drop choices, following the provenance convention (`Implementation_phases.md` D-3: immutable versions, `source` `ai` or `manual`, recorded inputs, out of date worked out on read);
- the **research round**: one row per brief written, with its claim list version, its folder, and when it was imported and reviewed;
- the **evidence items**: what an import stored for each claim and each piece of evidence, with the stored file paths, the check results and the warnings;
- the **owner's decisions**: accept or reject, shown or not, and the order, stored as versions;
- the **evidence clips**: rendered videos (previews, and exact-length clips for shots), with their measured frame counts, like `shot_graphic`;
- the job types: `suggest_evidence_claims` (paid model call), `write_evidence_brief` (local), `import_evidence` (local) and `render_evidence_clip` (local, uses the motion service).

---

## 5. Phase overview

| Id | Title | Kind | Hard dependencies | Status |
|----|-------|------|-------------------|--------|
| STOR-001 | A files folder outside Docker | Code | — | Completed |
| STOR-002 | Move the existing media | Owner | STOR-001 | In Progress |
| STOR-003 | Remove the old media copy from the volume | Owner, later | STOR-002 | Completed |
| STOR-004 | Database snapshots in the files folder | Code, optional | STOR-001 | Completed |
| EVD-001 | Evidence switch, tables and job types | Code | — | Completed |
| EVD-002 | Marking claims and GLM's proposals | Code | EVD-001 | Completed |
| EVD-003 | The research brief and the waiting step | Code | EVD-002, STOR-001 | Completed |
| EVD-004 | The capture tool | Code (Mac) | — | Completed |
| EVD-005 | The research skill for Cursor and Claude | Code (Mac) | EVD-004 | In Progress |
| EVD-006 | Importing and checking the evidence | Code | EVD-003, EVD-004 | Completed |
| EVD-007 | The review screen | Code | EVD-006 | Completed |
| EVD-008 | The evidence clip and its preview | Code | EVD-006 | Not Started |
| EVD-009 | Evidence shots in the cut plan and the render | Code | EVD-007, EVD-008 | Not Started |
| EVD-010 | One explainer end to end | Owner | EVD-005, EVD-009, STOR-002 | Not Started |
| EVD-011 | Evidence card over presenter shots | Code, later | EVD-010 | Deferred |
| EVD-012 | Source lines without a screenshot | Code, later | EVD-010 | Deferred |
| EVD-013 | Data evidence (prices and series as charts) | Code, later | EVD-010 | Deferred |
| EVD-014 | Automated research | Code, later | EVD-010 | Deferred |
| EVD-015 | Video evidence | Code, later | EVD-010 | Deferred |

**Tracks that can run at the same time:**

- **Files:** STOR-001 → STOR-002, then STOR-003 when the owner decides. STOR-004 at any time after STOR-001.
- **Backend:** EVD-001 → EVD-002 → EVD-003 → EVD-006 → {EVD-007, EVD-008} → EVD-009. EVD-001 can start beside STOR-001.
- **Mac tools:** EVD-004 → EVD-005 can start at once. They depend only on the contracts in §4.3 to §4.5.
- EVD-003 can be built before STOR-002, but the owner can only use the round folder from the Mac once STOR-002 is done.

**Progress snapshot:** 9 completed (STOR-001, STOR-003 and STOR-004, 2026-11-16; EVD-001, EVD-002, EVD-003, EVD-004, EVD-006 and EVD-007, 2026-11-17), 2 in progress (STOR-002: copied, verified and switched, the new-file smoke test is left; EVD-005: skill written and installed, the owner's runs in Cursor and Claude Code are left). Ready to start: EVD-008.

---

## 6. Phases

### STOR-001 — A files folder outside Docker

**Status:** Completed (2026-11-16)

**Objective.** Let media and the temporary working files live in a folder on the Mac, chosen in `.env`, while the database stays in the Docker volume. Nothing is copied or moved in this phase.

**Current state.**
- `core/config.py` derives `db_path`, `media_dir` and `tmp_dir` from `DATA_DIR` (default `/data`). `Storage` (`services/storage.py`) receives into `tmp_dir` and moves into `media_dir` with `Path.replace`, so the two must be on one mount (S-3).
- `docker-compose.yml` mounts the volume `data` at `/data` in `backend` and, read-only, in `frontend`. nginx serves `/media/` from `/data/media/`.
- The backend runs as uid 10001. `Storage` creates files with `open(..., "xb")` so that nginx, another user, can read them.

**Scope.**
- A second root for files, separate from `DATA_DIR`, holding `media/` and `tmp/` (and later `evidence/`). The database stays under `DATA_DIR`. When the new setting is not set, it defaults to `DATA_DIR`, so the app behaves exactly as today.
- Compose: the host folder named in `.env` is mounted at one path in `backend`. `frontend` mounts only that folder's `media/`, read-only, at the path nginx serves, instead of the whole volume (S-6). `backend` keeps the named volume at `/data` for the database.
- **A guard against a missing or wrong folder.** An unplugged disk or a mistyped path would otherwise look like an empty media folder, and new files would go into it. When the files root is set but the folder is not the expected one (for example, a marker file is missing) or cannot be written, the health check reports it and storing refuses with a clear message.
- Permissions work through Docker Desktop's file sharing: the backend user creates files, and nginx reads them.
- `.env.example` and `README.md`: the new setting, where files live, and that files must not be renamed, moved or deleted from Finder (S-4). The warning about `docker compose down -v` stays, because the database is still in the volume.
- **Planning decides:**
  - the setting's name and the container path;
  - how the guard recognises the right folder, and when the marker is written;
  - how the check runs without making existing media look missing in the real app. For example, use a separate throwaway compose project with its own empty volume, rather than pointing the real app at an empty folder.

**Out of scope.** Copying the existing media (STOR-002). Moving the database. Deleting anything.

**Dependencies.** None.

**Expected outcome.** With the setting unset, nothing changes. With it set, new files are written to the Mac folder and served from there.

**Verification criteria.**
- With the setting unset, the app starts and existing media plays as before.
- In a throwaway setup with the setting pointing at an empty test folder: a lab image made there appears in the Mac folder under `lab/`, plays at its `/media/` URL, and the save is an atomic move (no cross-device error).
- With the folder missing or unwritable, the health check says so and no file is written.
- The frontend container no longer sees `app.db`.
- Standard checks.

**Completion checklist.**
- [x] Files root setting, config, `Storage` unchanged in behaviour
- [x] Compose for backend and frontend, `.env.example`, README
- [x] Folder guard and health message
- [x] Checks above in a throwaway setup, ruff, ESLint, `tsc`
- [x] Real app rebuilt with the setting unset (2026-11-16, once no job was running): `/api/health` reports `files.ok: true, separate: false`, the frontend sees only `media`, and the owner confirmed the app works

**Completion notes.**
- **Settings.** `.env` gets `COMPOSE_FILE=docker-compose.yml:docker-compose.files.yml` and `VISIO_FILES_DIR=<absolute host path>`. The override file `docker-compose.files.yml` mounts that folder at `/files` in `backend` and sets `FILES_DIR=/files` there. `FILES_DIR` defaults to `DATA_DIR`, so with it unset nothing changes. The database, `-wal` and the `rembg` model cache stay under `DATA_DIR`.
- **Config.** `AppConfig.files_dir`, `files_dir_is_separate`; `media_dir` and `tmp_dir` are now under `files_dir`. Later phases that need `evidence/` put it under `config.files_dir`.
- **Marker.** An empty file `.visio-studio-files` at the root of the files folder, **created by the owner** (`mkdir -p DIR/media && touch DIR/.visio-studio-files`). The app never writes it. It is required only when the folder is separate. `media/` must exist before the first start, because Compose binds it into `frontend` before the backend can create it.
- **Guard.** `services/storage.py`: `FILES_MARKER`, `FilesFolderUnavailable` (a `StorageError`), `Storage.files_folder_problem()` (marker plus a write probe in `tmp/`). `receive`, `new_temp_path`, `partial_download_path`, `_save_in` and `clear_tmp` refuse without the marker. At startup, `main.py` skips `mkdir` and `clear_tmp` when there is a problem, and a handler turns `FilesFolderUnavailable` into HTTP 503 `{"detail": ...}`. Reads and deletes are unchanged.
- **Health.** `GET /api/health` has a new `files: {ok, separate, problem}`; a problem makes the status `degraded` (HTTP 503). The header (`BackendStatus.tsx`) says "files folder". `schema.d.ts` regenerated.
- **Compose.** The base file's `frontend` now mounts only the volume's `media` folder (`volume.subpath`), read-only. The override replaces that with `<folder>/media`, read-only, and both bind mounts use `create_host_path: false`, so Docker refuses to start when the folder is missing. Needs Docker Compose 2.35 or later (`!override`, `subpath`).
- **Checked on 2026-11-13** in a throwaway project (`visio-stor-test`, own volume, port 5481, folder `~/VisioStudioData-stor-test`): setting unset (health `files.separate: false`, frontend `/data` holds only `media`); setting on (an uploaded image in `media/lab/`, served by nginx with 200, `tmp/` empty, no cross-device error); marker removed (health 503 with the message, upload refused, no new file); `tmp/` read-only (health reports "cannot be written"); missing folder (Compose refuses to start the backend). The old files stay in the Docker volume untouched.
- **Deviation.** The first "setting unset" check ran on a fresh volume in the throwaway project, because jobs were running on the real app on 2026-11-13. The real app was rebuilt on 2026-11-16 and checked as listed above. The agent did not play media itself; the owner confirmed the app works.
- **Clean-up done by the owner on 2026-11-16:** `docker compose -p visio-stor-test down`, `docker volume rm visio-stor-test_data`, and the test folder removed. No `down -v`.
- **Disk space (for STOR-002).** On 2026-11-16 media was 28 GB (10,686 files) and the Mac had 23 GB free. Regenerable caches were cleared with the owner's go-ahead (updater bundles, Docker build cache, npm, pip and uv caches), giving 43 GB free.

### STOR-002 — Move the existing media (owner)

**Status:** In Progress

**Objective.** Copy all existing media from the Docker volume to the Mac folder, prove the copy is exact, and switch the app to it. Nothing is deleted.

**Current state.** About 25 GB in 9,399 files (2026-11-13). The Mac had about 40 GB free. Most media tables record each file's `sha256` (§2).

**Scope.** The agent prepares every command and explains it; the owner approves each step.
1. **Idle.** No job is running and no pipeline run is active. This is checked read-only from the database, not assumed.
2. **Space.** Free space on the Mac is at least the media size plus a margin (planning decides the margin; 10 GB is suggested).
3. **Stop.** `docker compose stop backend frontend`. Never `down`, never `-v`.
4. **Copy** with a throwaway container that mounts the volume **read-only** and the Mac folder as the destination, keeping every file and folder name.
5. **Verify:**
   - the same number of files and bytes on both sides;
   - every file's SHA-256 equal on both sides;
   - for the tables that record one, the database's `sha256` equal to the file's. Mismatches that already existed in the volume are listed, not fixed.
6. **Switch.** Set the STOR-001 setting in `.env` and start the services.
7. **Smoke test:**
   - open several projects, and play a render, a shot take and a voice line;
   - open the labs;
   - make one small lab item and see its file appear in the Mac folder.
8. **Rollback** if needed: unset the setting and restart. The old copy in the volume is untouched. Files made after the switch exist only in the Mac folder and must be copied back first.

**Out of scope.** Deleting the old copy (STOR-003).

**Dependencies.** STOR-001.

**Expected outcome.** The app runs from the Mac folder, and every file is verified equal to the original.

**Verification criteria.** File counts, bytes and hashes are equal; the smoke test passes; new files land in the Mac folder.

**Completion checklist.**
- [x] Idle and space checked
- [x] Copy made and verified
- [x] Switched
- [ ] Smoke-tested (owner: play existing media, open the labs, make one lab item and see its file in the Mac folder)

**Completion notes** (2026-11-16, in progress).
- **Folder.** `/Users/nareshjoshi/VisioStudioData`, created by the owner with `media/` and the `.visio-studio-files` marker. `.env` now has `COMPOSE_FILE=docker-compose.yml:docker-compose.files.yml` and `VISIO_FILES_DIR=/Users/nareshjoshi/VisioStudioData`. The switch is confirmed: `/api/health` reports `files.separate: true, ok: true`, `/files` holds the marker, `media` and `tmp`, and the frontend sees only `media`.
- **Before.** No job or pipeline run was active (checked read-only). 44 GB free, about 27 GB of media. About 20 GB of regenerable caches had been cleared first (updater bundles, Docker build cache, npm, pip, uv).
- **Copy.** `cp -a --no-preserve=ownership,xattr` in a throwaway container with the volume mounted read-only and no network. **7 min 7 s** for 10,342 files and 28,715,493,817 bytes.
- **Verification.** `scripts/verify_media_copy.py`, log `~/stor002-verify.log`. Same files, count and bytes on both sides (0 missing, 0 extra, 0 different size). SHA-256 equal for every file. For the 12 tables that record a hash (asset, shot_take, speech_unit_audio, story_render, scene_render, voice, voice_recording, lab_image, lab_video_run, lab_voice_run, lab_music_run, lab_music_source) every recorded hash equals its file's, and no row points at a missing file. The 7 path-only columns (av_lab_test, lab_graphic_render, shot_graphic, thumbnails, callout_graphic) all point at existing files. **No mismatches existed in the volume.**
- **Count note.** The volume held 10,686 files earlier on 2026-11-16 and 10,342 at copy time. Both sides were compared at the same moment, and no database row is missing a file, so the difference is most likely a deletion made in the app before the copy.
- **Rollback** is no longer possible: the old copy was removed in STOR-003 on the same day. The Mac folder is the only copy of the media.
- **Left:** the smoke test (owner).

### STOR-003 — Remove the old media copy from the volume (owner, later)

**Status:** Completed (2026-11-16)

**Objective.** Free the space the old media copy still takes inside Docker's disk image, once the owner trusts the new folder.

**Scope.**
- Only after the owner decides (Q-E5 suggests one week of normal use) and confirms explicitly.
- Remove **only the `media/` folder inside the volume**, using a throwaway container that mounts the volume. The database, its WAL and its backups are untouched. No `docker volume rm` and no `down -v`.
- Measure the size of Docker's disk image before and after.
- Optionally, move the three `backup-before-000N.db` files to the Mac folder.

**Dependencies.** STOR-002, and the owner's decision.

**Verification criteria.** The app still works, the volume's `media/` is gone, `app.db` is intact, and the freed space shows on the Mac.

**Completion notes** (2026-11-16).
- **Decision.** The owner chose to delete the same day as the switch, not after the suggested week (Q-E5), after being told it removes the rollback and that the Mac might not get the space back. The agent re-verified the copy first: `~/stor003-preverify.log` says `THE COPY IS EXACT` (10,342 files, 28,715,493,817 bytes, every SHA-256 equal), and no job was active.
- **What was run (by the owner).** A throwaway container with the volume mounted and no network: `find /data/media -mindepth 1 -delete`. It removed only the contents of `/data/media`; the empty `media` folder is kept so a Compose mount of it still works. No `docker volume rm`, no `down -v`.
- **Checked afterwards.** The volume's `/data/media` is empty (1 entry). `app.db`, `app.db-shm`, `app.db-wal` and the three `backup-before-000N.db` files are intact. `/api/health` is `ok` with `files.separate: true`. The Mac folder still holds 10,342 files.
- **Space.** Docker's disk image went from 75 GB to 48 GB and the Mac's free space from 18 GB to 44 GB, so Docker returned the space without a restart.
- **Not done.** The three `backup-before-000N.db` files (about 3 MB each) stay in the volume.
- **Rollback no longer exists.** The Mac folder is now the only copy of the media (about 28 GB). STOR-004 covers the database, not the media.

### STOR-004 — Database snapshots in the files folder (optional)

**Status:** Completed (2026-11-16)

**Objective.** Keep a consistent copy of the database in the Mac folder, so the owner has a visible backup that survives a lost volume.

**Scope.**
- A consistent snapshot of the live database (SQLite's backup API or `VACUUM INTO`, never a plain file copy of a database in use), written to `db-snapshots/` with the date in its name.
- **Planning decides:**
  - when snapshots are made (a button, on start, daily);
  - how many are kept, mindful that one is about 1.5 GB;
  - how the owner is told the last snapshot's age.

**Out of scope.** Moving the live database (S-2). Restoring is a documented owner action, not a button.

**Dependencies.** STOR-001.

**Verification criteria.** A snapshot opens with `sqlite3` and passes `PRAGMA integrity_check`; the app is not blocked while it is made; old snapshots are pruned to the limit.

**Completion checklist.**
- [x] Snapshot service (`VACUUM INTO`, integrity check, atomic rename, prune)
- [x] Daily check, button, API, health field
- [x] Settings "Backups" tab and header warning
- [x] README: how it works and the owner's restore steps
- [x] Real app rebuilt and checked (below); ruff, ESLint, `tsc`

**Completion notes** (2026-11-16).
- **Decisions (owner).** Made automatically when the newest snapshot is at least 24 h old (checked every hour, first check 5 min after start) and with a button. **One snapshot is kept.** The owner sees it in Settings, Backups, and the header warns when the newest is over 3 days old or none exists. The numbers are constants at the top of `services/db_snapshots.py` (`CHECK_INTERVAL_S`, `FIRST_CHECK_DELAY_S`, `MAX_AGE`, `WARN_AFTER`, `KEEP`, `FREE_SPACE_MARGIN_BYTES`), not settings.
- **Module.** `services/db_snapshots.py`. `VACUUM INTO` through a separate `sqlite3` connection in a worker thread, written to `db-snapshots/app-YYYY-MM-DD_HHMMZ.db.partial`, then opened `mode=ro&immutable=1` for `PRAGMA integrity_check` and the `alembic_version` read, then `os.replace` into place, then older snapshots are removed. A failed or cut-short snapshot leaves only a `.partial`, never replaces a good one, and is removed at the next start. Only names matching `SNAPSHOT_NAME` or `PARTIAL_NAME` inside `db-snapshots/` are ever deleted. Free space must cover the database, its WAL and 2 GB. One snapshot at a time (`_running` flag).
- **When it is off.** Unless `files_dir_is_separate` and `Storage.files_folder_problem()` is `None`. The status says why, and the button gets a 409. `evidence/` for the later phases still goes under `config.files_dir`; `db-snapshots/` sits beside `media/` and `tmp/` and is not served by nginx.
- **API.** `GET /api/db-snapshots` (`enabled`, `problem`, `running`, `last {name, made_at, size_bytes}`, `last_error`, `stale`); `POST /api/db-snapshots` returns 202, or 409 when one is running or snapshots are off. `GET /api/health` has a new `snapshots {enabled, last_made_at, stale}`, **information only**: it never makes the status `degraded`.
- **UI.** `components/settings/DatabaseSnapshotsSection.tsx` (a fixed "Backups" tab in `SettingsPage.tsx`), `api/dbSnapshots.ts`, and a note in `BackendStatus.tsx`. `schema.d.ts` regenerated.
- **No migration, no Compose change, no `.env` change.**
- **Checked on the real app** (rebuilt with `docker compose up -d --build backend frontend`, no job running, no `down`, no `-v`): a snapshot of the live database (1.5 GB class, `app.db` plus WAL) took **25 s** and is **643 MB** (compact). While it ran, `/api/health` and `/api/projects` answered in under 20 ms every time, and the log shows no "database is locked". `sqlite3` on the Mac: `integrity_check` is `ok`, revision `0097`, 19,148 jobs readable. A second snapshot left exactly one file and no `.partial`. A second press while one ran got 409. Before the first snapshot the status was `stale: true` (header warning).
- **Checked on throwaway folders** (not the real app): marker missing gives the "not the Visio Studio files folder" problem and the button is refused; `FILES_DIR` unset gives "Snapshots are off: the files folder is not set"; an older snapshot is pruned, an unrelated file is left alone.
- **Not checked.** The README's restore commands were written but **not run**: restoring over the live database was not tried. The header warning text after a snapshot older than 3 days was not seen in a browser; the logic follows the `stale` field the API reports.
- **Shutdown.** The snapshot runs in a thread that cannot be interrupted: stopping the backend while one is being made waits for it (about 25 s here).
- **Disk.** The snapshot of 643 MB sits in the Mac folder; a second one exists next to it for a moment while a new one is made.

### EVD-001 — Evidence switch, tables and job types

**Status:** Completed (2026-11-17)

**Objective.** Create everything the evidence layer stores in one migration (§4.8), and add the project switch.

**Current state.**
- The newest migration is `0097`.
- Job types are a CHECK on `job.type`, so new ones need a migration (`Implementation_phases.md` §3.4).
- Project switches follow `callouts` and `graphics`: a column on `project`, the create form, the settings form, and the checks in `services/projects.py`.

**Scope.**
- `project.evidence`, shown and on by default on the create form for a continuous explainer (EV-1, EV-2), hidden for every other project, changeable in settings, and refused by the API for a project it does not apply to.
- The tables and job types of §4.8, following D-3.
- `DATABASE_STRUCTURE.md` updated (tables, JSON shapes, job inputs and outputs).
- **Planning decides:** the table names and split; whether the owner's decisions are their own table or versions inside the item table; what turning `evidence` off later does to existing evidence (kept but ignored is suggested).

**Out of scope.** Any behaviour beyond the switch.

**Dependencies.** None. It may run beside STOR-001.

**Expected outcome.** The schema exists, and an explainer can be created with evidence on or off.

**Verification criteria.**
- The migration goes up, down and up again, and `alembic check` shows no difference for the new tables.
- The create form shows the switch only for a continuous explainer, on by default, and settings can change it.
- A story project refuses the switch.
- Standard checks.

**Completion checklist.**
- [x] Migration, models, `DATABASE_STRUCTURE.md`
- [x] Switch on create form and settings, API checks
- [x] Standard checks
- [x] Real app rebuilt (2026-11-17, no job running, no `down`, no `-v`) and the API rules checked on it
- [ ] Owner: the create form and the settings form seen in the browser (the agent did not open them)

**Completion notes** (2026-11-17).
- **Migration `0098`** (`0098_evidence_layer.py`): `project.evidence`, six tables and four job types. `job` is rebuilt for the new CHECK, as in `0096`. Downgrade deletes the jobs of the four types and every evidence row; files already copied into `media/` and the round folders are left.
- **`project.evidence`.** BOOLEAN NOT NULL, default 0. Every project that existed reads off (checked on the real app: 67 projects, all `false`). The create form defaults it on for a continuous explainer, and it does **not** need `graphics` on. `ProjectDetail.evidence`, `ProjectCreate.evidence` (`null` means on for a continuous explainer, off otherwise) and `ProjectUpdate.evidence` in `api/projects.py`; rules in `services/projects.py` (`EVIDENCE_ONLY_MESSAGE`, `validate_project`, `create_project(evidence=...)`, `update_project`). Any `PATCH` that sends `evidence` on a project that is not a continuous explainer gets 422, whatever the value.
- **Tables (decisions).** Six tables, all written as new rows and never changed, so the state of a round is worked out on read (imported: an `evidence_import` exists; reviewed: an `evidence_review` with `done` exists for the round):
  - `evidence_claim_list` (versions of the claims; `source` `ai` or `manual`; `inputs {script_sha256, based_on_version}`; `content {next_id, claims}`);
  - `evidence_round` (`round_no`, so the round id is `r<round_no>`; `claim_list_id`; `folder` relative to `config.files_dir`; `brief` JSON; `brief_sha256`);
  - `evidence_import` (`version` per round; `results`, `report`);
  - `evidence_item` (one per piece; `item_key`; `kind`, `relation` and `source_tier` nullable with CHECKs; a path and a SHA-256 column for each of image, context, text and PDF; `usable`, `checks`, `warnings`);
  - `evidence_review` (the owner's decisions, version per project; `content {claims: [{claim_id, items: [{item_key, verdict}], shown, no_proof_on_screen}]}`; `done`);
  - `evidence_clip` (`purpose` `preview` or `shot`; `item_id`; `scene_id`, `shot_id`, `shot_plan_id`; `inputs.items` is the ordered list of the pieces shown; `media_path`, `sha256`, `frame_count`, `metrics`, `warnings`, `last_error`).
- **The owner's decisions are their own table**, `evidence_review`, not versions inside the item table. A decision names an item by `item_key`, not by row id, so a re-import keeps decisions for unchanged items without copying. EVD-006 decides what `item_key` is made of.
- **Job types.** `suggest_evidence_claims` (`llm`, `never_rerun`), `write_evidence_brief`, `import_evidence` and `render_evidence_clip` (`local`, `start_again`). They are in the `job.type` CHECK, `api/jobs.py` `JobType` and the labels of `jobFormat.ts`. No handler, no routes, no job phases yet: the phase that adds each handler registers it and documents its `job.input` and `job.output`.
- **Turning `evidence` off later keeps everything and ignores it.** Later phases must treat `evidence = false` as "does not apply" and read nothing from these tables. The settings form says that switching it off deletes nothing.
- **Cleanup on delete.** All `project_id` keys cascade, so deleting a project removes its evidence rows, and `media/<project_id>/` already goes with it. Deleting a project also removes its `evidence/<project_id>/` round folder (decided and done in EVD-003, `project_deletion.delete_project`; a failure is logged and does not undo the delete, as with the media folder).
- **UI.** `CreateProjectModal.tsx` has an "Evidence" switch, on, shown only when the voice is continuous. `ProjectSettingsForm.tsx` has an editable switch in the continuous-voice block, and `settingsDraft.ts` carries the field.
- **Docs.** `DATABASE_STRUCTURE.md`: an Update entry, the `project.evidence` row, the job type note, Sections 4.93 to 4.98 and a Section 5 block with the JSON shapes. §4.8 of this document needed no change.
- **Checked.** On a throwaway `DATA_DIR`: `0098` up, down to `0097` and up again, and `alembic check` shows only the `FLOAT` against `REAL` notes on older tables, none for the new ones; a job of a new type inserts and the new tables exist. On the real app, rebuilt with `docker compose up -d --build backend frontend` (the newest database snapshot was about 20 minutes old, none was taken first): `/api/health` is `ok` at revision `0098`, and with four throwaway projects (deleted afterwards; no library item was deleted):
  - a continuous explainer gets `evidence: true` by default and `false` when sent `false`;
  - a story or a lines explainer with `evidence: true` gets 422;
  - `PATCH` of `evidence` on a story or a lines explainer gets 422 (both values);
  - `PATCH` `false` then `true` on a continuous explainer gets 200;
  - `null` gets 422 "Evidence cannot be empty" and `"yes"` gets 422.
  Ruff check and format, `npm run lint` and `npm run typecheck` pass; `schema.d.ts` was generated from the running backend and equals the one generated from the local code.
- **Not checked.** The two forms were not opened in a browser, and the labs and the Character Lab were only spot-checked through the API (the characters list and the project list answer, the frontend serves). Environment note: `backend/.venv/bin/alembic` has a stale shebang from the old folder name (`VisionPsyStudio`), so `uv run alembic` fails to spawn; `.venv/bin/python -m alembic` works.

### EVD-002 — Marking claims and GLM's proposals

**Status:** Completed (2026-11-17)

**Objective.** The owner marks the words that need proof; GLM proposes more; the owner keeps or drops GLM's proposals. The result is the claim list that research works from.

**Current state.**
- Graphic suggestions show how to mark words: `services/graphic_suggestions.py` (`normalise`, `reanchor`) and `components/story/GraphicSuggestions.tsx`, which already converts between code points and the browser's positions.
- The callout plan shows a one-call writer with owner review.
- `ask_model` is the model call path (D-7).

**Scope.**
- **Marking.** Select words in the story editor, snapped to whole words with no overlaps, with an optional hint per claim. The marks are kept right when the script is edited (`reanchor` behaviour), and a claim whose own words changed is flagged.
- **GLM's proposals** (`suggest_evidence_claims`, a paid call from a click). One call reads the script and the owner's marks. It returns extra claims as exact phrases from the script, each with a short reason and a `kind_hint`. Code finds each phrase in the script and drops any it cannot find or that overlaps an owner's mark. A limit on how many keeps the list short.
- **Instructions.** Only checkable statements: numbers, dates, prices, quotes, things a named person or organisation said, reported findings. No opinions, no common knowledge. Fewer and stronger is better.
- **Review.** GLM's proposals are shown as proposals the owner keeps or drops; the owner's marks are always in. Every change is stored as a new version of the claim list (source `manual` for the owner's, `ai` for GLM's).
- **Planning decides:**
  - whether evidence marks and graphic suggestions may cover the same words;
  - the limit on GLM's proposals (fixed, or per minute of script);
  - whether a pipeline run asks GLM by itself when there is no proposal yet, or only a click does. A click only is suggested, because it is a paid call.

**Out of scope.** Writing the brief (EVD-003).

**Dependencies.** EVD-001.

**Expected outcome.** The project has a reviewed claim list, each claim with its exact script words, origin and hint.

**Verification criteria.**
- Marks survive a small script edit elsewhere, and a claim whose words were edited is flagged.
- GLM's proposals on a sample script are found in the script, each with a reason, and none overlaps an owner's mark.
- Keeping and dropping are stored as new versions.
- A project with evidence off, and a story project, show none of this.
- Standard checks.

**Completion checklist.**
- [x] Marking UI and storage, re-anchoring
- [x] Proposal job, instructions, parsing and locating
- [x] Keep or drop review, versions
- [x] Standard checks
- [x] Real app rebuilt (2026-11-17, no job running, no `down`, no `-v`, no migration) and checked with throwaway projects, which were deleted afterwards (no library item deleted)
- [ ] Owner: the "Evidence claims" panel seen in the browser (the agent did not open it)

**Completion notes** (2026-11-17).
- **Decisions ("Planning decides").**
  - *Evidence marks and graphic suggestions may cover the same words:* yes, the two lists are independent (EVD-009 decides which shot wins). Inside the claim list there are never overlaps.
  - *Limit on GLM's proposals:* **none** (the owner's decision). The instructions say "fewer and stronger is better"; only the answer's token budget (`MAX_TOKENS` 24,000) bounds it.
  - *Does a run ask GLM by itself:* **yes, once.** This added a pipeline step that §4.2 did not list: **`evidence_claims`** ("Propose the evidence claims", group `story`, no needs). It is done once an `ai` claim list version exists, and is skipped as complete for a project that is not a continuous explainer with `evidence` on (board status `off`). Re-asking is a click only. EVD-003's `evidence` step should need `evidence_claims`. §4.2 is updated.
- **Marks follow the script on read, not on save.** `update_project` is not touched (it still re-anchors graphic suggestions only). `services/evidence_claims.reanchor_claims(script, claims)` runs on every read and before every owner action: a claim stays, or moves to the nearest place its words are, or is flagged `words_changed` (words gone, no longer whole words, or now overlapping a claim that counts; the owner's marks are placed first). `words_changed` is never stored. A flagged claim keeps its old place. **Later phases (EVD-003 and after) must treat a claim with `words_changed` as unusable**, and the stored positions are only trustworthy after `reanchor_claims`; read claims through `evidence_claims.state()` (or `reanchor_claims`), never straight from the row. The next version stores the positions as found, with the new `script_sha256`.
- **Rules of the claim list** (`services/evidence_claims.py`): ids are `c<n>` from `next_id`, never reused; the owner's marks are `origin` `owner`, `kept` true; GLM's are `origin` `glm`, `kept` null until decided. A claim with `kept` false (a dropped proposal) **stays** in the list so it is not proposed again; only the owner's marks are removed (`remove_mark`). An owner's mark over a proposal sets that proposal to `kept` false in the same version. Two owner marks may not overlap (422). `kind_hint` defaults to `number` when `numbers_in` finds a number, otherwise `statement`. The note (`hint`) is one line of plain text, at most 300 characters. At most 100 owner marks (`MAX_OWNER_MARKS`, input hygiene, not the proposal limit). Owner changes are refused with 409 while a `suggest_evidence_claims` job is queued or running. A no-op edit stores nothing.
- **Re-asking GLM** replaces only the undecided proposals; the owner's marks and every kept or dropped proposal stay. The request tells GLM which words are already marked and which the owner dropped. A new proposal with the same words and place as an old undecided one keeps its id. The job saves against the version and the script hash it started from, and fails ("Ask again") if either changed.
- **Job `suggest_evidence_claims`** (`jobs/suggest_evidence_claims.py`, `provider='llm'`, `never_rerun`, story model, one `ask_model` call, `job.input`/`job.output` in `DATABASE_STRUCTURE.md` Section 5). The pure parts are in `services/evidence_claims_writer.py` (`build_request`, `check_answer`, `locate_proposals`). The model gives `{claims: [{phrase, kind_hint, reason}]}`, never positions; code finds each phrase (spaces and line breaks count alike), snaps to whole words, and leaves out (listed in `job.output.dropped`) a phrase not in the story, over 300 characters, already marked, dropped before, proposed twice, or only placeable over a claim that counts. New phase text `SAVING_EVIDENCE_CLAIMS`.
- **API** (`api/evidence_claims.py`, tag `evidence-claims`): `GET /api/projects/{id}/evidence-claims` (`version`, `claims` each with `words_changed`, `job`, `blocked_reason`, `wanted`, `has_ai_version`), `POST .../marks`, `PATCH .../{claim_id}` (`hint`, `kind_hint`, `kept`), `DELETE .../{claim_id}`, `POST .../suggest` (202). 422 for a project without evidence or without a saved story, 404 for an unknown claim, 409 while GLM is proposing. A project with evidence off reads nothing from the tables.
- **Shared helpers moved, no behaviour change:** `services/script_ranges.py` (`snap_to_words`, `nearest_occurrence`, used by `graphic_suggestions.py`) and `components/story/storyMarks.ts` (`buildPositions`, `unitOffset`, used by `GraphicSuggestions.tsx` and `EvidenceClaims.tsx`).
- **UI.** `components/story/EvidenceClaims.tsx` (marking view, note and kind, claim cards with Keep, Drop, Remove and a "words changed" warning, "Ask GLM for more claims" with the job badge), mounted in `StoryEditor.tsx` under the graphic suggestions when the voice is continuous and `evidence` is on, and as the panel of the `evidence_claims` step in `StepPanel.tsx`. `api/evidenceClaims.ts` (key under the project's key, so saving the story refreshes the claims). `schema.d.ts` regenerated from the local code (additions only).
- **No migration, no Compose change, no setting.**
- **Checked on the rebuilt real app** (throwaway projects only, deleted afterwards): marks stored as versions 1 to 4 with the right `source` and `inputs`, earlier rows unchanged; an edit elsewhere in the story moved both marks (`words_changed` false) and an edit of one mark's own words flagged only that one; overlap, stale text, unknown claim, unknown kind and dropping an owner's mark all refused; a story project, a lines explainer and an explainer with evidence off give `wanted` false and 422 on every change, and the board step reads `off`. **One real GLM call** on a ~100-word sample script (job 31399, succeeded in a few seconds): three proposals, each found in the story with a reason, none overlapping the owner's mark, none left out; a second press while it ran returned the same job, and a mark during it got 409. Keep, drop, keep again, and an owner's mark over a proposal each stored a new version; deleting a proposal was refused; the board step read `done` afterwards. The graphic suggestions still mark and re-anchor as before (checked on the pure functions). Ruff check and format, `npm run lint` and `npm run typecheck` pass.
- **Not checked.** The panel was not opened in a browser (selection, the note field, the colours). A pipeline **run** that asks GLM once was not made, because a run on a new project would start other paid steps; the step uses the same `start_suggest` as the click, and a second queued job is deduped by `store.create_job`. Re-asking GLM over existing decisions was not tried against the real model (the replace-only-undecided rule in `save_ai_version` was only reasoned through; the phrase locating was checked on sample input).

### EVD-003 — The research brief and the waiting step

**Status:** Completed (2026-11-17)

**Objective.** Add the `evidence` step (§4.2). It writes the brief into a round folder (§4.3, §4.4) and then waits until the owner has imported and reviewed the results. Only the consumers wait (EV-9).

**Current state.**
- Steps, needs and skip-as-complete adapters live in `services/story_pipeline.py` and `story_pipeline_targets.py`. Board statuses are in `pipeline_board.py`.
- A run stops and explains itself when a target is blocked and nothing else can go on (`jobs/story_pipeline._stop_reason`).
- Review points pause only after steps the run made something in, so they do not fit a step that waits for the owner's outside work as they are.

**Scope.**
- The `evidence` step and its adapter, with the skip-as-complete rules of §4.2. `shot_plans` gains `evidence` in its needs.
- **Writing the brief** (`write_evidence_brief`, local). A new round id, the round folder, `claims.json` exactly as in §4.4, and `README.md` with the round's folder path on the Mac, the skill's name and a ready-to-paste prompt (the prompt text comes from EVD-005). The backend learns the Mac path of the files folder from the compose setting, so it can show it.
- **Round state:** brief written, then waiting for results, then imported (EVD-006), then reviewed (EVD-007). The step is complete only when the newest round is reviewed and the claim list has not changed since its brief. Otherwise it is out of date, and a new round is needed.
- **While waiting:**
  - the board shows the step as waiting for the owner, with the folder path and a copy button;
  - a run keeps making every step that does not need evidence;
  - when nothing else can go on, the run stops and says it is waiting for evidence. That is not reported as a failure.
- **Resume:** after review, the owner presses Run or Continue as today.
- **Planning decides:**
  - how the waiting is modelled: a reported block, or a new kind of review point;
  - whether the step needs `story_bible` (for the brief's topic line) or nothing;
  - whether a later round carries only the new or changed claims, and how results of earlier rounds are kept for unchanged claims;
  - whether an empty claim list completes the step.

**Out of scope.** Importing (EVD-006). Reviewing (EVD-007). The `evidence_clips` step (EVD-009).

**Dependencies.** EVD-002, STOR-001. STOR-002 must be done before the owner uses the folder from the Mac.

**Expected outcome.** Running the pipeline on an explainer with evidence on writes the brief, makes everything else that can be made, and stops at shot planning saying it waits for evidence.

**Verification criteria.**
- On a sample explainer, the steps before shot planning run, shot planning waits, and the run stops with the waiting message, not a failure.
- The brief appears in the Mac folder with exactly the reviewed claims, and the README's path and prompt are correct.
- Editing a claim after the brief makes the step out of date.
- With evidence off, the step is off and shot planning does not wait.
- A story project's steps behave exactly as before.
- Standard checks.

**Completion checklist.**
- [x] Step, adapter, needs, board state
- [x] Brief job, round folder, README
- [x] Run behaviour while waiting, resume (written and reasoned through; not run end to end, see "Not checked")
- [x] Standard checks
- [x] Real app rebuilt (2026-11-17, no job running, no `down`, no `-v`, no migration) and checked with a throwaway project, which was deleted afterwards (no library item deleted)
- [ ] Owner: the "Evidence" step panel, the board and the run panel seen in the browser (the agent did not open them)
- [ ] Owner: a real run on an explainer with evidence on, to see it stop with the waiting message (paid steps, so not started by the agent)

**Completion notes** (2026-11-17).
- **Decisions ("Planning decides").**
  - *How the waiting is modelled:* **a new kind of pause, `waiting_for`** (the owner's choice), not a reported block and not a review point. A step's target can carry `awaiting` (what the owner must do outside the app); it is not a problem and not a failure. A run keeps making every step it can. When nothing is going on and every step still to do is blocked only on such a wait, the run keeps `running`, sets `job.output.waiting_for` to the step and writes the phase "Waiting for you (gather the evidence): ...". Steps are evaluated again on every poll, so the run **goes on by itself** once the step is done, and **Continue** is accepted too (it only makes the run look again at once). No timeout.
  - *Does the step need `story_bible`:* **yes** (the brief's topic line), and `evidence_claims`. `shot_plans` needs `evidence`.
  - *Does a later round carry only new claims:* **no (the owner's choice): every round carries every claim that counts and stands alone.** The newest round is the evidence; earlier rounds stay as records and are not looked at. So EVD-006 imports one round and never has to merge.
  - *Does an empty claim list complete the step:* **yes.** With no claim that counts, the step is done and a brief is refused ("There are no claims to prove").
- **When a round is current.** The round's `brief.claims` must equal the claims that count now in id, origin, words, sentence, note and kind (`claim_keys`). The sentences around a claim (`context`) do not count, so an edit elsewhere in the story does not force a new round; an edit of the claim's own sentence does. Claims are read through `evidence_claims.state()`, so a claim with `words_changed` does not count.
- **What stops a brief.** A proposal of GLM nobody decided on (the step then says "Keep or drop the N claims GLM proposed", the owner's task), no claim, nothing changed since the newest round, no saved story, evidence off, or the files folder not being a separate marked folder (the evidence files are written only to the folder on the Mac, never into the Docker volume). Each has a plain message.
- **Where a round stands** is worked out on read from the rows (`evidence_rounds.round_status`): `brief_written`, `imported` (an `evidence_import` exists), `reviewed` (the newest `evidence_review` is `done` and was made for the newest import). EVD-006 and EVD-007 write those rows, so the step cannot complete until they exist.
- **Job `write_evidence_brief`** (`jobs/write_evidence_brief.py`, `provider='local'`, `start_again`, no model, no cost; `job.input` and `job.output` in `DATABASE_STRUCTURE.md` Section 5). It reads the claims and the story as they are when it runs, writes the round folder (`brief/claims.json`, `brief/README.md`, empty `results/`, each file by a partial name then moved) and the `evidence_round` row, and marks the job succeeded in one transaction. A folder written for a row that was never saved (or for a job cancelled meanwhile) is removed.
- **The brief** is §4.4 exactly: topic from the Story Bible (the project's name when there is none), the whole sentence and the sentence before and after each claim (cut at sentence ends, one line each), `max_evidence_per_claim` 3, empty domain lists, language `en`.
- **README.** It carries the round's folder on the Mac (from the new setting `FILES_HOST_DIR`, set by `docker-compose.files.yml` from `VISIO_FILES_DIR`; null when it is not known), the skill's name `visio-evidence` and a prompt. **The prompt is provisional: EVD-005 writes the skill and replaces `README_PROMPT`** (and `SKILL_NAME` if the skill is named differently).
- **Board.** New step status `owner` ("Waiting for you", orange), only when the steps it needs are done (so it does not claim the owner's attention before the Story Bible exists), with the reason under the step. New board mode `pipeline_waiting` with "Open step", Continue and Stop. The run panel shows an orange alert with Continue. `waiting_for` is in the run and board APIs.
- **API** (`api/evidence.py`, tag `evidence`): `GET /api/projects/{id}/evidence` (`wanted`, `claims_count`, `pending`, `awaiting`, `done`, `blocked_reason`, `can_write_brief`, `round` {`round_id`, `host_folder`, `folder`, `status`, `out_of_date`, `claims`, `created_at`}, `job`, `prompt`, `skill`) and `POST .../evidence/brief` (202 with the job, 422 with the reason). The claims' text is never in the answer; the brief file holds it. Deleting a project removes `evidence/<project_id>/`.
- **UI.** `components/story/EvidencePanel.tsx` (the panel of the `evidence` step: "Write the brief", the round's state, copy buttons for the folder and the prompt, the job badge and its error), `api/evidence.ts` (key under the project's key; the claim mutations refresh it), `BoardHeader.tsx`, `BoardStepList.tsx`, `boardSteps.ts`, `StoryPipelinePanel.tsx`. `schema.d.ts` regenerated from the local code (additions only).
- **Deviation from the plan as first thought.** While a run waits, it evaluates **all** steps as usual rather than only the evidence step: the finished steps are skipped as complete anyway, so only the evidence step and what is blocked behind it remain, with the same result and less code.
- **Checked on the rebuilt real app** (one throwaway explainer, deleted afterwards, and one throwaway story project): with no claim the step was done and a brief was refused; one owner mark made `can_write_brief` true; the job wrote `~/VisioStudioData/evidence/<id>/r1/` with `brief/claims.json` (exactly one claim with its sentence, context, note and kind), `brief/README.md` (the Mac path and the prompt) and an empty `results/`; the state read `brief_written` with the "Run the research in ..." message; a second brief was refused ("already has these claims"); editing the claim's note made the round out of date and a new brief possible; the board step read `out_of_date`; the story project read `wanted` false, the step `off`, and a brief 422; deleting the explainer removed its evidence folder and left the library character alone. The pure parts were run on sample input and not kept: `plan_step` with an awaiting target (waiting, no problem, nothing created), the board status (`owner` only when the needs are done), sentence and context cutting (also for words across a sentence end), the round comparison (an edit elsewhere keeps the round current, a changed note does not), and `_check_graph`. Ruff check and format, `npm run lint` and `npm run typecheck` pass; the labs, the project list and the frontend answer.
- **Not checked.** (1) **A pipeline run that waits and goes on** was not made: a run on an explainer starts paid and GPU steps, so it needs your go-ahead. The code path (`_apply` in `jobs/story_pipeline.py`, `waiting_phase`, `continue_run`) was reasoned through and its parts checked as above. (2) The step panel, the board header and the run panel were not opened in a browser. (3) The "undecided GLM proposals" wait was checked on the pure logic only, not with a real GLM answer. (4) Importing and reviewing (EVD-006, EVD-007) do not exist yet, so a round cannot go past `brief_written` in the app.
### EVD-004 — The capture tool

**Status:** Completed (2026-11-17)

**Objective.** A command-line tool, run on the Mac, that turns "this source contains these words" into verified captures: the screenshot, the highlight rectangles, the text copy and the result entry (§4.5). It is the only way coordinates are made (EV-5).

**Current state.** Nothing exists. The Mac has uv 0.12.5, Python 3.13.7 and Node 24.1.0. The contracts are §4.3 to §4.5.

**Scope.**
- **Location:** a standalone package in the repository with its own dependencies, not part of any Docker image, run with `uv run` (or `npx`).
- **Web capture:**
  - open the address in headless Chromium at a fixed viewport by orientation (§4.7), and wait for the page to load;
  - try to dismiss cookie banners and hide fixed headers;
  - find the quote in the page's text after normalising;
  - scroll it into view, then take the screenshot and a taller context image;
  - compute one rectangle per line of the quote as fractions of the image;
  - save the page's text copy, and record the final address after redirects.
  - When the quote is not found, fail with a clear message and print the nearest matching text, so the agent can pick the exact words.
- **PDF capture:**
  - take an address or a local file, and copy the PDF within a size limit;
  - find the quote in the text of its pages, across line breaks;
  - render that page, cropped around the quote with a margin, and keep the full page as the context image;
  - write the rectangles and the page number.
  - A PDF with no text layer (a scan) fails with "no text layer". OCR is out of scope.
- **Reporting:** a command that writes a claim's result with `not_found` or `blocked` and the attempts.
- **`validate`:** checks a round's results against the contract and checks 1 to 4 of §4.6, and prints a summary. The agent runs it before finishing.
- **Safety:**
  - writes only inside `results/<claim_id>/` of the round;
  - refuses addresses that are not http or https, and local or private addresses;
  - limits on time and size;
  - no logins and no stored cookies.
- The `capture` block records the tool's version and the exact viewport and scale.
- **Planning decides:**
  - Python or Node;
  - the libraries, minding licences: PyMuPDF, for example, is AGPL;
  - the command names;
  - the viewport sizes and the PDF render resolution;
  - how far the cookie-banner handling goes.

**Out of scope.** Searching (the agent does it). Backend changes. OCR. Video.

**Dependencies.** None (contracts in §4).

**Expected outcome.** Given a source and exact words, the tool writes a correct, self-checked capture, or refuses clearly.

**Verification criteria.**
- On the test set (Appendix A), the tool:
  - captures an article and a multi-line quote in a PDF correctly;
  - refuses a quote that is not there, and suggests near text;
  - handles a page with a cookie banner and a redirecting address;
  - refuses a private address and a scanned PDF.
- For each good capture, a debug image with the rectangles drawn shows them exactly over the quote.
- `validate` passes good output and fails a hand-edited bad one (a moved rectangle off the image, a changed hash).
- Lint for the tool passes.

**Completion checklist.**
- [x] Web capture, PDF capture, reporting, `validate`
- [x] Safety limits
- [x] Test set run (real public sources, not the owner's Appendix A set; see "Checked")

**Completion notes** (2026-11-17).
- **Where.** `tools/evidence-capture/`: a Python 3.13 package (`pyproject.toml`, `uv.lock`, `src/visio_evidence_capture/`), not in any Docker image, no backend or compose change, no migration. Install: `uv sync` and `uv run playwright install chromium` (README, "The evidence capture tool"). The executable is `visio-evidence-capture`; it is run from the round folder (`--round` defaults to the current folder).
- **Decisions ("Planning decides").**
  - *Language:* **Python** (the owner's choice).
  - *Libraries (all permissive):* `playwright` (Chromium), `pypdfium2` (PDF text, character boxes, rendering), `Pillow`, `httpx`. PyMuPDF (AGPL) and poppler (GPL) are not used. **EVD-006 should use `pypdfium2` too** so that the import reads a PDF's text like the tool does.
  - *Who writes `result.json`:* **only the tool** (the owner's choice). The agent passes every field as a flag. Until `report` is run `status` is `null` and `validate` fails on it.
  - *Commands:* `web`, `pdf` (`--url`, or `--file` with `--source-url`; `--page` to search one page), `report` (`--status`, `--summary`, repeatable `--attempt WHAT OUTCOME`; attempts are added each time it runs), `remove`, `validate`, `draw`. Exit code 0 done, 1 refused or checks failed, 2 wrong usage.
  - *Viewports:* landscape 1280x720 at scale 2 (image 2560x1440); portrait 360x640 at scale 4 (image 1440x2560), with a phone user agent and touch, but **not** Chromium's `is_mobile` mode (deviation from the plan: that mode zooms pages that have no viewport tag, which would make the rectangles wrong). Both the screenshot and the rectangles are checked against `window.innerWidth` and the visual scale.
  - *PDF rendering:* the crop has the video's shape, is centred on the quote, is at least 40% of the page's width, is moved inside the page when it fits (white around it when it does not), and is rendered so that it is 2560x1440 or 1440x2560, with the scale at most 8. The context image is the whole page at 150 DPI. A quote across a page break is refused with a plain message; a rotated page is refused.
  - *Cookie banners:* click a known consent button (OneTrust, Didomi, Cookiebot, TrustArc, Quantcast), else a button with exactly the text "reject all", "reject", "decline", "necessary only", "only necessary", "accept all", "accept all cookies", "accept", "i agree", "agree" or "got it" (reject first) inside something that looks like a consent box (fixed, a dialog, or named cookie/consent/...), in the page or in a consent frame. Then every `position: fixed` element is hidden, `sticky` ones become static, and a scroll lock is released. No code for particular sites. The English texts only: a banner in another language is hidden by the fixed-element rule instead.
  - *Quote rules* (EVD-006 must repeat them exactly, `text.py`): NFKC (a letter with its marks together), curly quotes straight, soft hyphens and zero-width characters removed, white space runs made one space, ends trimmed, case kept. pdfium's U+FFFE (a hyphen at a line end) counts as a hyphen. **A PDF is searched three ways** (the plan said two): as it is, with a line-end hyphen and the line break dropped ("trans-" "former" gives "transformer"), and with only the line break dropped ("English-" "to-German" gives "English-to-German"). A match needs the first line to end in a hyphen and the next to start with a letter.
  - *Web text:* the visible text nodes in reading order (hidden and script elements left out, a line break between blocks and at `<br>`); the same text, with white space compacted, is the text copy, and the tool checks that the quote is found in that copy. Open shadow roots and frames are not read.
- **What a web capture does.** Opens the address in a fresh Chromium context (no stored state, service workers blocked, no downloads, no permissions), waits for load (30 s) and a short quiet period, closes consent boxes, finds the quote, scrolls so that its middle is at 40% of the screen height, checks that it is wholly inside the screen and that nothing covers it (`elementFromPoint` at each line), takes the screenshot, and measures one rectangle per line (merged from the text nodes' own rectangles, 2 CSS pixels of room). Refused with a reason when: the quote is not on the page (with up to three nearest stretches of the page), it is taller than 80% of the screen, it is covered or clipped, the page is a PDF or a download, the server answers 4xx or 5xx, or the page moves while it is captured.
- **Context image: a change from the plan.** The plan said to use Playwright's `full_page` clip. On a 55,000 px Wikipedia page that took 30 s to time out (and 54 s through CDP), so the tool scrolls and joins up to three viewport screenshots instead (up to three screens tall, centred on the screen of the quote), and checks that the quote did not move while scrolling.
- **Safety, as built.**
  - Writes only in `results/<claim_id>/` for a claim of the brief; claim ids `^c\d+$`, evidence ids `^e\d{1,2}$`; refuses a link as `results/` or a claim folder; writes to a partial name then renames; refuses to write over a link; `remove` deletes only the four names the tool makes (`eN.png`, `eN-context.png`, `eN.txt`, `eN.pdf`); the brief is never written. At most `max_evidence_per_claim` pieces of evidence (replace one by using its id).
  - Addresses: only http and https, no user name or password, and every address the host name leads to must be globally routable (`ipaddress.is_global`), so localhost, 10.x, 172.16.x, 192.168.x, link-local and CGNAT are refused. The browser's own requests go through a route handler that aborts refused hosts. PDF downloads are followed by the tool, one redirect at a time (at most 5), each checked, with the size capped (50 MB) while streaming.
  - **A limit to know about:** Playwright does not show server redirects to the route handler, and Chromium follows them itself. So a public page that redirects to a private address makes **one blind GET** to it before the tool notices. After the load, the tool checks the server address of every response and every step of the main redirect chain, and refuses and **stores nothing**. Checked with a local server (the tool refused: "answered from a private address"); the data is never kept. A DNS answer that changes between the tool's check and the browser's own lookup is caught by the same server-address check.
  - Limits (`__init__.py`): load 30 s, whole capture 120 s, PDF 50 MB, text 5 MB, an image file 20 MB, 12 rectangles, quote 3 to 600 characters, 2000 pages without `--page`.
- **`validate`.** For every claim of the brief: a result exists; shape (schema, version, round id, status, summary, attempts, evidence fields, `published` as a date); status against evidence (found, partial and contradicted need some; not_found and blocked none; not_found needs an attempt); files (plain names, regular, no link, inside the round, type by content, size, SHA-256, `image_px` equals the real PNG size and the viewport times the scale, `tool` is `visio-evidence-capture`); the quote in the text copy (web) or on the PDF's page (pdf, with the three hyphen readings); the rectangles (1 to 12, `[x, y, w, h]`, not empty, inside the image). Warnings (do not fail): a status that no evidence backs, a file the result does not use, a folder that is not a claim of the round. A link in a claim folder fails.
- **`draw`.** Writes `<round>-<claim>-<evidence>.png` (rectangles over the image) and `...-context.png` (the image's place in the context) under the system temporary folder (`visio-evidence-debug/`), never in the round.
- **Checked** (2026-11-17, throwaway rounds in `/tmp`, deleted afterwards; nothing under `~/VisioStudioData`). These were real public sources, not the owner's Appendix A set (which does not exist yet): Wikipedia (landscape and portrait, a two-line and a three-line quote); the "Attention Is All You Need" PDF from arXiv, as a file and downloaded (a two-line quote, and a quote across a hyphenated line end), landscape and portrait; spiegel.de (a Sourcepoint consent box, hidden, quote on the headline, three lines); example.com through an httpbin redirect (`final_url` recorded); a missing quote (near text shown, for a page and a PDF); `http://192.168.1.1`, `http://localhost:5480/` and `file:///etc/passwd` refused; a scanned PDF (made with Pillow) refused with "no text layer"; a made-up quote across no page refused; the limit of three pieces of evidence, replacing, `remove` (its files go), bad ids and a claim not in the brief refused. In every good capture the rectangles drawn by `draw` sit on the quote (looked at). `validate` passed the good round (nine claims: found, blocked and not_found) and failed a hand-edited copy for each of: a rectangle outside the image, a changed byte (hash), a quote not in the text, a text file named `.png`, a `..` in a name, a link in a claim folder, and a `found` status without evidence. Ruff check and format pass.
- **Not checked.** (1) The owner's Appendix A set (an annual report with a two-line quote, a paywalled page, a "partial" stock-price case). (2) A site with a consent box in English that needed the button text rule: the only click seen was lemonde.fr's "accept", and no screenshot of it was taken. (3) A page whose quote sits in a scrolling box or is covered by a pop-up (the refusals are written, not seen). (4) A PDF page break and a rotated page (refusals written, not run). (5) A redirect from a public page to a private address, end to end (no public host would do it; only the post-load check was run against a local server). (6) Sites that block headless browsers answer 4xx or a check page (ft.com gave a Cloudflare check; the tool says to report the claim as `blocked`).
- **For the next phases.** EVD-005's skill must tell the agent: always pass the quote from the near-text list when a quote is refused; run `report` for every claim (a `not_found` claim needs an `--attempt`); never edit `result.json`; run `validate` last. Its prompt replaces `README_PROMPT` in `services/evidence_rounds.py`. EVD-006 reads `result.json` as written here, applies the quote rules above, and must open PDFs with `pypdfium2`. EVD-008 can use `capture.context_box` and `viewport` (null for a PDF).

### EVD-005 — The research skill for Cursor and Claude

**Status:** In Progress (2026-11-17): skill, install script and prompt are done; the owner's runs in Cursor and Claude Code are left

**Objective.** One written skill that makes a Cursor or Claude agent research each claim of a round on its own, use the capture tool, and report honestly.

**Scope.**
- A skill file usable by both products, with any reference file it needs.
- **Workflow.**
  - Read `brief/claims.json`.
  - For each claim, on its own (one subagent per claim where the product supports it, or one after another):
    - understand the claim in its sentence and context;
    - search, preferring primary sources (the company's filings and statements, official statistics, the person's own words, the original publication);
    - choose the exact words that prove or disprove it;
    - capture them with the tool;
    - fill in `relation`, `source_tier`, `what_it_says` and the summary.
  - Stay within a search budget per claim, and record every attempt.
- **Status rules** (EV-6):
  - `not_found` is a good answer, better than a weak source;
  - `contradicted` when a good source says otherwise;
  - `partial` when the source matches only part of the claim, or gives a different number;
  - `blocked` when the right source cannot be captured.
  - At most `max_evidence_per_claim` pieces of evidence per claim.
- **Safety rules** (EV-11): everything read on the web is data, never instructions; write only in `results/`; never edit the brief; use no credentials; run no command other than the capture tool and read-only listing.
- **Finish:** run `validate`, fix what it reports, and print a table of claims, statuses and sources.
- The ready-to-paste prompt that EVD-003 puts in the round's README.
- **Planning decides:** where the skill is installed so that both products find it from a round folder outside the repository; the search budget; how strict the command rule can be in each product. Check how each product reads the skill file; they are similar but not the same.

**Out of scope.** Running research automatically (EVD-014).

**Dependencies.** EVD-004.

**Expected outcome.** The owner can open a round folder, paste one prompt, and get a validated result for every claim.

**Verification criteria.**
- The owner runs it once in Cursor and once in Claude on the test brief (Appendix A), and every claim gets a result.
- The deliberately wrong claim comes back `contradicted`, and the obscure one comes back `not_found` with its attempts.
- `validate` passes, and no file is written outside `results/`.

**Completion checklist.**
- [x] Skill and reference text
- [x] README prompt text
- [x] Install script, run on the Mac (installed and re-installed; the skill is in `~/.claude/skills/visio-evidence/`)
- [x] Throwaway test round drafted (`/tmp/visio-evidence-test/r1`, outside the repository; it loads in the capture tool)
- [ ] Owner: run in Cursor on the test round, and record how it behaved
- [ ] Owner: run in Claude Code on the test round, and record how it behaved
- [ ] Owner: the real app rebuilt so that new rounds carry the new prompt (the agent did not rebuild it)

**Completion notes** (2026-11-17, written before the owner's runs; the last lines are to be filled in after them).
- **Where.** `tools/evidence-skill/`: `visio-evidence/SKILL.md`, `visio-evidence/reference.md` and `install.sh`. No migration, no frontend change, no contract change (§4 is unchanged).
- **Decisions ("Planning decides").**
  - *Where the skill is installed:* **`~/.claude/skills/visio-evidence/`, one copy** (the owner's choice). Claude Code reads it as a user skill, and Cursor reads `~/.claude/skills/` for compatibility (per Cursor's documentation, not tried yet). It is not put in `~/.cursor/skills/` too, so Cursor does not list it twice. It is **copied, not linked**, because Cursor's handling of linked skill folders is reported to be unreliable (forum reports, not documentation). Edit the source in the repository and run `install.sh` again.
  - *`install.sh`:* checks `uv`, runs `uv sync` for the capture tool, builds the copy in a hidden folder next to the target, writes the capture command into it in place of `{{TOOL}}`, and swaps it in. It refuses a repository or home path with characters other than letters, digits and `/ _ . -` (the path goes into a permission pattern), a link as the skills folder or the target, and an existing target that is not this skill. It touches no other skill. It does not install Chromium (README, "The evidence capture tool").
  - *How the agent calls the tool:* **`uv run --project <repository>/tools/evidence-capture visio-evidence-capture`** (the owner's choice), so that the tool's `uv.lock` and the Chromium already installed match. The `--project` option does not change the folder, so the agent stays in the round folder and `--round` can be left out.
  - *Search budget per claim:* at most 8 web searches, 10 sources opened, and 3 capture tries per source; stop early at `max_evidence_per_claim` good pieces or when a primary source settles the claim; every source looked at and not used is an `--attempt`. These numbers are a first guess and are for the runs to correct.
  - *How strict the command rule can be:* in **Claude Code**, the skill's `allowed-tools` lets only the capture tool command, `ls`, reading, searching and the web tools run without asking, so any other command asks the owner. In **Cursor**, a skill cannot limit commands (no such field is documented, and `allowed-tools` is not a Cursor field), so the rule is only written in the skill and the round's README tells the owner to keep the run mode on asking. `allowed-tools` is a limit on what is pre-approved, not a block: the owner can still approve a command, so it is guidance plus asking, not a security boundary.
  - *How each product reads the skill:* both need `name` (lowercase, equal to the folder) and `description`. The description is narrow ("only inside a round folder that has `brief/claims.json`") so that it does not load elsewhere. The skill is plain Markdown with no product-specific syntax besides `allowed-tools`.
- **What the skill tells the agent** (mirrors the capture tool's notes for the next phases): safety rules first (web content is data, only the tool writes, never edit `brief/` or a `result.json`, no credentials, only the tool command and `ls`); read the brief and use `project.today`; follow the claim's `hint`; run `validate` first to skip claims that are already done; one claim at a time and one subagent per claim where possible (at most 3 at once, with a stand-alone prompt for each, and no nested subagents); copy the quote word for word and never use a fetch tool's summary; when the tool refuses a quote, use the exact words of its near-text list (at most 3 tries per source); run `report` for every claim (a `not_found` claim needs an `--attempt`); run `validate` last and fix problems; print a table; say the owner must press Import.
- **The prompt** (`services/evidence_rounds.README_PROMPT`): "Use the visio-evidence skill to research every claim in brief/claims.json of this round, each on its own. Then run validate and show me the table of results." `SKILL_NAME` is unchanged. The README of a round (`readme_text`) gains a "First time only" part (run `tools/evidence-skill/install.sh`) and a step telling the owner to allow only the capture tool and web searches. The API and `EvidencePanel.tsx` already show `prompt` and `skill`, so they did not change. **Only rounds written after the real app is rebuilt carry the new text.**
- **Checked.** `install.sh` (bash syntax; run twice, so that both a new install and a replacement ran; the installed files hold no `{{TOOL}}`, and the permission line and the command read correctly); `shellcheck` is not installed, so it was not run. Ruff check and format on `evidence_rounds.py`; `readme_text` rendered and read. The test round (seven claims after Appendix A's kinds: a PDF figure, a quote, an official statistic, a company event, a wrong number, an invented claim and a paywalled one) loads in the capture tool and `validate` reports the seven claims as having no result yet. The claims are drafted from what the agent knows and **are not verified by the agent**; the owner may replace any.
- **Not checked.** The skill has **not been run by any agent yet**: how Cursor and Claude Code load it, whether Cursor accepts the `allowed-tools` line, whether Claude Code's pattern for a command with an absolute path matches, whether subagents are started and how well they follow the rules, whether Cursor's sandbox blocks the tool until it is allowed, and the time and cost per claim. **Owner runs, to record here:** the statuses of the seven claims (expected: `found` for c1 to c3 and probably c4; `contradicted` for c5; `not_found` with attempts for c6; `blocked` or `partial` for c7), whether `validate` passes, whether a file appeared outside `results/` (`find . -type f` in the round folder before and after; the listing before is in `/tmp/visio-evidence-test/before.txt`), and the time and cost per claim for each product.

### EVD-006 — Importing and checking the evidence

**Status:** Completed (2026-11-17); the real app has not been rebuilt yet

**Objective.** Bring a round's results into the app safely, check every piece of evidence (§4.6), and store it for review.

**Current state.**
- `Storage` generates names and keeps every path inside the media folder.
- `numbers_in` reads numbers.
- The round folder is in the files folder (STOR-001).

**Scope.**
- **"Import evidence"** on the evidence panel (`import_evidence`, local). It reads the current round's `results/`, runs checks 1 to 5 of §4.6, and copies every usable file into storage under a generated name. It then stores each claim's status, summary and attempts, and each item's source, quote, relation, tier, rectangles, checks and warnings. A claim without a result folder is shown as "no result".
- For the PDF text check, a PDF text library in the backend, minding licences.
- **Limits:** per file and per round, with file types checked from content.
- **Import report:** counts by status, and the problems of each claim, shown on the panel.
- **Importing the same round again** replaces items not yet reviewed, and keeps the owner's decisions for items whose files and quote are unchanged.
- **Planning decides:** the limits; the key that tells an item is unchanged; whether a file that fails a check is copied at all (not copying it is suggested).

**Out of scope.** The review decisions (EVD-007).

**Dependencies.** EVD-003, EVD-004 (the format and `validate` rules), EVD-001.

**Expected outcome.** The owner presses Import and sees every claim with its checked evidence, or the exact reason it cannot be used.

**Verification criteria.**
- The EVD-005 output imports.
- Each of these is refused with its reason while the rest imports:
  - a link inside a claim folder;
  - an oversized file;
  - a text file named `.png`;
  - a file name with `..`;
  - a quote missing from the text copy;
  - a rectangle outside the image.
- A number the quote does not say shows a warning.
- Imported files are in `media/` under generated names, and the round folder is left unchanged.
- Standard checks.

**Completion checklist.**
- [x] Import job and checks
- [x] Storage copy, limits, report
- [x] Re-import behaviour
- [x] Standard checks
- [x] Checked end to end on a throwaway backend (own `DATA_DIR` and files folder, a throwaway project, real captures made by the tool)
- [ ] Real app rebuilt (a dependency, `pypdfium2`, was added to the backend, so the image must be rebuilt: `docker compose up -d --build backend frontend`, with no job running, never `down` or `-v`). The agent did not rebuild it.
- [ ] Owner: the Import button and the import report seen in the browser (the agent did not open them)

**Completion notes** (2026-11-17).
- **Where.** `services/evidence_text.py` (the tool's quote rules, repeated), `services/evidence_checks.py` (pure checks 1 to 5 and `item_key`), `services/evidence_import.py` (reading the round folder, refusal, queueing, copying, saving), `jobs/import_evidence.py` (job type `import_evidence`, `provider='local'`, `start_again`, phase `IMPORTING_EVIDENCE`), `api/evidence.py`, `EvidencePanel.tsx` and `api/evidence.ts`. New backend dependency `pypdfium2` (5.15.2, the version the tool locks; Apache-2.0/BSD-3). No migration, no setting, no compose change. `DATABASE_STRUCTURE.md` has an Update entry, the `item_key` definition, the `results`, `report`, `capture` and `checks` shapes, and the job's `input` and `output`.
- **Decisions ("Planning decides").**
  - *Limits:* the capture tool's: `result.json` 1 MB; an image 20 MB and 40 million pixels; a text copy 5 MB; a PDF 50 MB; 12 rectangles; `max_evidence_per_claim` pieces per claim (the rest are left out and the claim says so). Added: **1 GB for the files of the whole round**; a file that would pass it is reported as "left out because the round's files are too large in all". File types are checked from content.
  - *`item_key`:* SHA-256 of the claim id, kind, relation, normalised quote, page, rectangles (6 places) and the real hashes of the four files. The agent's piece id is not in it; a piece that is not usable has it, so its key never equals a usable piece's. A second usable piece with the same key in one claim is refused as "the same evidence as eN" (check `duplicate`).
  - *A file that fails a check is copied at all:* **no** (the owner's choice). The item row is stored with `usable` false, its reasons in `checks` and NULL file columns.
  - *Importing again* (the owner's choice: allowed also after "Review done"): adds the next `evidence_import.version` with every item. After "Review done" the round reads `imported` again on its own (the newest review is for an older import), so the `evidence` step is not done until the owner reviews again. Checked.
- **Safety (EV-7).** Only the claim ids of the **stored** brief are looked at (never the folder names or the brief on disk); a round folder, `results/` or a claim folder that is a link is refused; every file is opened with `O_NOFOLLOW` and `O_NONBLOCK`, must be a regular file (`fstat`) and is read with a size limit; only plain file names are read (`^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$`); the round folder is never written. Stored names are made by `Storage` (`media/<project_id>/<32 hex>.png|txt|pdf`). The agent's text is stored as text and never used as a path or as HTML. Sentences sent to the browser carry agent values only cut short (`shown`). **A limit to know about:** a hostile PDF is parsed by pdfium inside the backend process (the same library as the tool, with the 50 MB limit); there is no separate sandbox.
- **Stricter than `validate`, on purpose** (the review screen shows these values): an image must be a PNG; `url`, `final_url` and `archive_url` must be http or https; text values have the tool's length limits (the quote 3 to 600 characters); a link anywhere in a claim folder makes every piece of that claim unusable. The rules of checks 1 to 4 are otherwise those of `validate` in the same order with the same wording, and on the hand-broken round both gave the same refusals. Check 5 (a number of the claim, by `numbers_in`, that the quote does not say) is a warning `number_not_in_quote` on every piece, usable or not.
- **What an import stores** (details in `DATABASE_STRUCTURE.md`): `evidence_import.results[claim_id]` is `{status, summary, attempts, problems, warnings}` for every claim of the brief (status null with no problems: no `result.json`; with problems: one that cannot be used), `report` has `by_status` including `no_result` and `invalid`. `evidence_item.capture` is tidied and has **no file names and no hashes** (the columns have the paths and hashes); `source` is tidied; `evidence_id` is `?<position>` when the agent's id was not valid or was used twice. A claim whose `result.json` is not valid (wrong schema, round or claim, no status, no summary) gets no item rows at all.
- **Files are shared.** A file whose SHA-256 equals one an earlier import of the round stored, or one stored earlier in the same import, is used again (after the stored file is checked to still have that hash). So two items or two imports may point at one stored file (seen: two claims quoting one PDF share it). **EVD-007 and later must never delete a stored file because one item is rejected or an import is replaced.**
- **API.** `POST /api/projects/{id}/evidence/import` (202 `{job_id}`, 422 with the reason: no evidence, no round, the claims changed since the brief, a brief is being written, files folder problem, no `result.json` written yet). `GET .../evidence` gained `can_import`, `import_blocked_reason` (cheap: it does not look at the folder, so "no result yet" is only found when asked), `import_job` and `latest_import` (`version`, `report`, and per claim `status`, `result_state` `ok|no_result|invalid`, `problems`, `warnings` and `items` with `usable`, `reasons`, `warnings`). The agent's summary, quote and notes are **not** in this answer: **EVD-007 needs its own endpoint for them**, and must refuse to accept an item that is not usable and ignore a decision whose `item_key` is not in the newest import.
- **UI.** The evidence panel has "Import evidence" (or "Import again"), the import job's badge and error, and the report: counts by status and a list of claims with problems, refused pieces and warnings in plain text.
- **Checked** (2026-11-17, on a throwaway backend started on its own `DATA_DIR` and files folder, a throwaway project, all deleted afterwards; the real app and `~/VisioStudioData` were not touched). Ten claims; the good ones were captured **by the capture tool** from real sources (a Wikipedia sentence of two lines, and a two-line quote of the arXiv "Attention Is All You Need" PDF with a line-end hyphen in "English-to-German", plus one `not_found` report) and `validate` passed them. Then six hand-broken copies. One import: **c1 to c3 usable, c4 `not_found` imported, and each of these refused with its reason while the rest imported**: a link in the claim folder, an oversized file (22.5 MB), a text file named `e1.png` (hash and type), a file name `../c1/e1.png`, a quote not in the text copy, a rectangle outside the image. A claim saying "41" with a quote saying 28.4 gave the warning. The stored files are in `media/<project>/` under generated names; a `shasum` listing of the round folder (links included) before and after is **identical**. Importing again gave version 2 with the same `item_key` for every item and **no new media file**; after a review row marked done, the round read `reviewed` and the new import made it `imported` again; re-capturing one item with another relation changed only that item's key. A claim edit after the brief gave 422 "The claims changed since round r1" and `can_import` false; a brief with no `results` gave 422 "No result has been written". Reader edge cases run on a scratch folder: a link as a claim folder, a link as `result.json`, bad JSON, a 100,000-deep JSON, a claim id with `..`, and the round size limit. **Quote-rule parity**: the backend's `evidence_text` and the tool's `text.py` and `pdf.find_in_text` gave the same normalised text and map for 3,011 sample strings in all three hyphen modes, and the same answer for 900 random quotes of the real PDF's first pages. Ruff check and format, `npm run lint` and `npm run typecheck` pass; `schema.d.ts` was generated from the local code (additions only).
- **Not checked.** (1) The real app was not rebuilt (see the checklist), so nothing was imported on it and no real Docker run of the new dependency was made (the lock resolves a manylinux wheel for `python:3.13-slim`, not tried). (2) The panel and its import report were not opened in a browser. (3) The failure paths that delete copied files (the job cancelled during an import, the files folder going away, the database refusing the rows) were read, not run. (4) A PDF with a rotated or odd page and a scanned PDF are only refused by the tool; the import reads PDFs through the same `pypdfium2` text, but a PDF the tool never made was not tried. (5) A round of many large files near the 1 GB limit was not tried (the limit was run with a 10-byte budget).

### EVD-007 — The review screen

**Status:** Completed (2026-11-17); the real app has not been rebuilt yet

**Objective.** The owner reviews every claim and every piece of evidence, and decides what reaches the video (EV-8).

**Scope.**
- **One card per claim:**
  - its script words, sentence, origin, status and summary;
  - for `not_found` and `blocked`, the attempts;
  - for `contradicted`, a visible note that the script may be wrong here.
- **Under each claim, its evidence:**
  - the screenshot with the highlights drawn by the frontend from the rectangles over the clean image, and the context image on demand;
  - the quote, the source (publisher, title, date, link, archive link), the relation and the tier;
  - the checks and warnings, and the agent's notes.
- **Decisions:** accept or reject each piece of evidence; choose which accepted ones are shown and in what order; for a claim with nothing shown, "no proof on screen" (the claim stays in the script without evidence). Decisions are stored as versions (D-3), and a re-import keeps them for unchanged items.
- **"Review done"** completes the round (EVD-003), and the run can continue.
- **Planning decides:** whether every claim must have a decision before "Review done" (suggested: yes); how many pieces of evidence one claim may show (suggested: as many as fit its words, at least one).

**Out of scope.** The video preview (EVD-008 adds a button here).

**Dependencies.** EVD-006.

**Expected outcome.** The owner can trust what goes into the video, because they chose each piece.

**Verification criteria.**
- Decisions survive a reload and a re-import of the same round.
- "Review done" completes the step, and the next run goes past shot planning.
- Changing the claim list afterwards makes the round out of date.
- The highlights drawn on screen sit over the quote for a web capture and a PDF capture.
- Standard checks.

**Completion checklist.**
- [x] Claim cards, evidence view with highlights
- [x] Decisions, versions, "Review done"
- [x] Standard checks
- [x] Checked end to end on a throwaway backend (own `DATA_DIR` and files folder, a throwaway project, real captures made by the tool)
- [ ] Real app rebuilt (`docker compose up -d --build backend frontend`, with no job running, never `down` or `-v`). The agent did not rebuild it. EVD-006's rebuild (a new dependency) is still open too, so one rebuild covers both.
- [ ] Owner: the review seen in the browser (claim cards, the highlights over the screenshot, the context window, "Review done"). The agent did not open it.

**Completion notes** (2026-11-17).
- **Where.** `services/evidence_review.py` (decisions, rules, `view`, `save_claim_decision`, `finish_review`), `api/evidence.py` (three new routes on the same router), `api/evidence.ts` (`useEvidenceReview`, `useSaveEvidenceClaimDecision`, `useFinishEvidenceReview`), `components/story/EvidenceReview.tsx` (mounted in `EvidencePanel.tsx` under the import report), and `components/story/evidenceLabels.ts` (the claim status words and colours, moved out of `EvidencePanel.tsx` so both files use them). **No migration, no job, no setting, no compose change, no new dependency.** `schema.d.ts` was generated from the running throwaway backend (additions only). `DATABASE_STRUCTURE.md` has an Update entry and the Section 5 note.
- **Decisions ("Planning decides").**
  - *Must every claim have a decision before "Review done":* **yes** (the owner's choice). A claim with usable pieces needs a verdict for every usable piece and either something shown or "No proof on screen". A claim with nothing usable (`not_found`, `blocked`, `no_result`, `invalid`, or every piece refused) needs "No proof on screen" ticked: nothing passes silently. "Review done" names the claims still undecided when it is refused (422).
  - *How many pieces one claim may show:* any number of its accepted pieces, at least one, otherwise "No proof on screen". A claim has at most `max_evidence_per_claim` (3) pieces, so that is the most. Whether they fit the claim's words is EVD-009's job.
  - *A piece that contradicts the claim* (`relation` `contradicts`): **the owner decides on the card** (the owner's choice). It can be accepted and shown; its card has a red note that the source says otherwise. A claim whose status is `contradicted` has a note that the script may be wrong here. Nothing is blocked in code.
- **API** (`api/evidence.py`): `GET /api/projects/{id}/evidence/review` (`round_id`, `import_version`, `version`, `done`, `editable`, `blocked_reason`, `undecided`, `claims`; each claim has its words, sentence, origin, note, status, summary, attempts, problems, warnings, `items`, `shown`, `no_proof_on_screen`, `decided`; each item has the key, the checks and warnings, the source, quote, `what_it_says`, notes, `image_url`, `context_url`, `image_px`, `rects`, `context_box`, `page` and `verdict`). `PUT .../review/claims/{claim_id}` (body `{items: [{item_key, verdict}], shown, no_proof_on_screen}`) replaces one claim's decision and returns the review. `POST .../review/done` returns the review. 404 for an unknown claim, 409 while an import runs, 422 for everything else that is refused (evidence off, no round, no import, claims changed since the brief, a key that is not a usable piece of that claim, two verdicts for one piece, a shown piece that is not accepted or shown twice, shown together with "no proof"). The `GET` of a project without evidence answers 200 with no claims and a `blocked_reason`. **This answer is the one place the claims' words and the agent's summary, quote, `what_it_says` and notes are sent to the browser**; the screen shows them as plain text, and shows a source address as a link only when it starts with `http://` or `https://` (`rel="noopener noreferrer"`).
- **Versions.** Every owner action is a new `evidence_review` row (`done` 0), written at once, so decisions survive a reload; a change that changes nothing stores nothing. "Review done" writes a row with `done` 1 and the same content (nothing is stored when the newest row is already that). **A change after "Review done" takes it back:** the round reads `imported` again (`round_status` needs a `done` row for the newest import) and the `evidence` step waits until "Review done" is pressed again. The same holds after a re-import of the same round, even when no piece changed: `inputs.import_id` is the old import, so the owner presses "Review done" once more, with every decision kept.
- **Re-import.** Decisions are read through `effective_decision`: only usable pieces of the claim in the newest import keep a verdict, and `shown` keeps only accepted pieces, in the owner's order. A re-captured piece with another relation or quote has a new `item_key`, so it drops out and its claim is undecided again, while the other claims and pieces keep their decisions. No stored file is deleted by a decision or a re-import.
- **Screen.** One card per claim (words, sentence, origin, note, status, "Decided" or "Undecided", summary, what was tried for `not_found` and `blocked`, problems and warnings), one card per piece (the screenshot with the quote's rectangles drawn over it as boxes at `x, y, width, height` in per cent of the image, so they follow the displayed size; "Show context" opens a window with the context image and an outline at `context_box`; the quote, the source with publisher, title, date and page, an archive link, relation and tier, warnings, the agent's notes; Accept, Reject and a "Show on video" box), an order list (Up, Down) when a claim shows more than one piece, the "No proof on screen" switch, and the "Review done" button with the undecided claims named. An unusable piece shows its reasons and has no buttons. **Accepting a piece shows it by default** (the owner can untick it); "No proof on screen" clears what is shown, and showing a piece clears "No proof on screen". These two behaviours are the screen's own and are not rules of the server.
- **Checked** (2026-11-17, on a throwaway backend started on its own `DATA_DIR` and files folder with a throwaway explainer, all removed afterwards; the real app and `~/VisioStudioData` were not touched). Three claims captured **by the capture tool** from real sources (the "Attention Is All You Need" PDF and its arXiv page for c1, Wikipedia for c2, a `not_found` report with two attempts for c3), imported by the real job:
  - the review read all three as undecided; "Review done" was refused naming c1, c2 and c3;
  - refused with the right status and sentence: an unknown claim (404), a key that is not a piece of the claim, two verdicts for one piece, a shown piece that is rejected, a piece shown twice, shown with "no proof", an unknown verdict (422);
  - a default decision stored nothing; each real decision stored one version (1 to 4), with the right `inputs`; the same decision again stored nothing; "Review done" stored version 5 with `done` true and `GET .../evidence` read `reviewed`, `done` true and no `awaiting`, and the board step `evidence` read `done`; pressing it again stored nothing; a reload gave the same decisions and the same order of the two shown pieces;
  - a change after "Review done" stored version 6, `done` false, and the round read `imported` again;
  - importing the same files again (version 2): every decision kept and every claim still decided, the round `imported`; re-capturing one piece with another relation and importing again: only c1 was undecided, its other piece kept its verdict and its place;
  - changing a claim's note after the round: the review read `editable` false with "The claims changed since round r1. Write a new round.", both writes got 422, the step read `out_of_date`; changing it back made the review editable again;
  - a project with evidence off: 200 with no claims and the reason, a write 422;
  - for the web and the PDF capture the `rects`, `context_box` and image size in the answer equal the capture tool's `result.json`, and the image files exist (the highlight is the same rectangle the tool's `draw` was checked against in EVD-004).
  Ruff check and format, `npm run lint` and `npm run typecheck` pass.
- **Not checked.** (1) The review screen was **not opened in a browser**: the boxes over the screenshot, the context window, the order buttons and the layout were not seen (the maths is the same fractions the tool's `draw` uses, but how it looks was not looked at). (2) The 409 while an import runs was written and reasoned through, not run. (3) The real app was not rebuilt, so nothing was reviewed on it. (4) A piece with a refused check and a `contradicts` piece were only read in the code; the throwaway round had no refused piece and no contradicting one. (5) The screen was not tried with a portrait capture.

### EVD-008 — The evidence clip and its preview

**Status:** Not Started

**Objective.** Draw an evidence shot as a video with the motion service (§4.7), and let the owner preview it from the review screen.

**Current state.**
- The motion service has compositions in `motion/src/templates` and `motion/src/blocks`, reached with JSON props and limited to 1 MB per request. It takes no image, and keeps no internet, no volume and no secrets.
- `render_shot_graphic` is the pattern for a job that asks the motion service for a clip and stores it.
- The resolved props carry `safe_area` and `caption_zone`, and the video's accent comes from the graphic theme or the callout plan.

**Scope.**
- **A new composition:**
  - it opens on the context, zooms in to the quote's rectangles, and plays the highlight sweep in the accent colour;
  - the source badge, inside the safe area, with the caption zone left free;
  - landscape and portrait, using the bundled fonts.
- **Getting the image to the motion service** without giving it a volume, the internet or secrets.
- **A readability check:** the quote's text height on the output frame after the zoom. Below the minimum, the review card shows a warning.
- **The render job** (`render_evidence_clip`): a preview at a fixed length from the review screen. The clip is stored as media with its measured frame count. Exact-length clips are made by EVD-009 with the same job.
- A "Preview video" button on each accepted piece of evidence in the review screen.
- **Planning decides:**
  - how the image reaches the motion service. Options: a data URL in the props with a larger body limit for this route only, or an address the backend serves only on `motion_net`;
  - the minimum text height;
  - the preview length;
  - the zoom and highlight timings;
  - where the accent comes from when the project has no graphic theme.

**Out of scope.** Placing clips on the timeline (EVD-009).

**Dependencies.** EVD-006, EVD-001. The preview button needs EVD-007's screen; the two can be built side by side.

**Expected outcome.** The owner can watch exactly how each piece of evidence will look in the video.

**Verification criteria.**
- Previews of a web capture and a PDF capture, in landscape and portrait, put the highlight on the quote, the badge is readable, and the caption zone is free.
- A capture with small text shows the readability warning.
- The motion service still has no network, volume or secrets (compose unchanged for it).
- Standard checks, and `npm run typecheck` in `motion/`.

**Completion checklist.**
- [ ] Composition, image delivery
- [ ] Render job, storage, readability check
- [ ] Preview button
- [ ] Standard checks

**Completion notes.** _To be filled in._

### EVD-009 — Evidence shots in the cut plan and the render

**Status:** Not Started

**Objective.** Accepted evidence appears in the video on the words it proves.

**Current state.**
- The cut planner plans `graphic` shots and takes the owner's suggestions as wishes (`cut_planning_writer.py`); `take_suggestions` maps script ranges onto a take's words.
- The `graphics` step makes a clip per graphic shot, and `scene_render`, `music_placement` and `render` wait for it.
- Graphic shots skip shot definition, references, prompts and generation.

**Scope.**
- **Evidence shots.** Cut planning gets every claim with evidence chosen to show, mapped onto the take's words. It plans a new shot type, `evidence`, over those words: starting on or just before the first word, at least as long as §4.7 requires, and showing the chosen pieces in the owner's order when there is time.
- **Stronger than a graphic suggestion.** Code checks that every claim with evidence to show has its evidence shot. The planner may leave one out only with a reason, which the board shows.
- **No H3.** An evidence shot never goes to H3; like a graphic shot, it skips definition, references, prompts and generation.
- **The `evidence_clips` step** (§4.2): one clip per evidence shot at the shot's exact length, made with EVD-008's job. `scene_render`, `music_placement` and `render` need it.
- **Render.** The clip is a shot of the timeline, like a graphic shot, and captions keep showing.
- **Out of date.** A new review decision or a new import makes the affected plan and clips out of date.
- **Planning decides:**
  - what a callout does during an evidence shot (hidden, or kept in its zone);
  - the reading rate for the minimum length;
  - how several pieces of evidence share one claim's words;
  - what the planner may give as a reason to leave a claim out;
  - how an evidence shot and a graphic suggestion on the same words are settled.

**Out of scope.** Evidence cards over presenter shots (EVD-011).

**Dependencies.** EVD-007, EVD-008, EVD-003.

**Expected outcome.** The rendered explainer shows each chosen piece of evidence, full screen, while the presenter says the words it proves.

**Verification criteria.**
- A continuous explainer with three claims with evidence to show gets three evidence shots on the right words and of the right lengths. The render shows them with captions.
- A project with evidence off gets a plan and a render exactly as before: the cut planning instructions and request are unchanged, checked the way E-8 of `Explainer_implementation_phases.md` checked story prompts.
- A project with graphics on still gets its graphic shots.
- Standard checks.

**Completion checklist.**
- [ ] Cut planner input, shot type, code checks
- [ ] `evidence_clips` step, needs of the render steps
- [ ] Timeline and render
- [ ] Standard checks

**Completion notes.** _To be filled in._

### EVD-010 — One explainer end to end (owner)

**Status:** Not Started

**Objective.** Make one real explainer with evidence and judge the whole layer.

**How:**
1. Make a 2 to 3 minute finance explainer with about six claims, mixing the kinds in Appendix A. Make it once in landscape and once in portrait.
2. Mark the claims, take GLM's proposals, and let the run stop for evidence.
3. Research with Cursor for one orientation and Claude for the other.
4. Import, review and render.

**Judge:**
- Can the highlighted words be read in the time they are on screen?
- Do the evidence shots start on the right words?
- Are the `not_found` and `contradicted` claims clear on the review screen?
- How long did the agent take per claim, and what did it cost?
- Did any check refuse something good, or let through something wrong?

**Dependencies.** EVD-005, EVD-009, STOR-002.

**Result (owner fills in):** _To be filled in. The owner then decides which deferred phases to move to Not Started._

### EVD-011 — Evidence card over presenter shots (later)

**Status:** Deferred

A smaller evidence card in the callout zone over a presenter shot, instead of a full-screen shot, for claims the presenter should stay on screen for.

### EVD-012 — Source lines without a screenshot (later)

**Status:** Deferred

A short text-only source line ("Source: Reuters, 3 Oct 2026") shown while a claim is spoken, for claims where a screenshot would add little.

### EVD-013 — Data evidence (later)

**Status:** Deferred

Numbers that change over time, such as stock prices, drawn as a chart from fetched data with a source and date badge, instead of a screenshot of a live quote page.

### EVD-014 — Automated research (later)

**Status:** Deferred

Research run by the app itself: a search service, pages fetched by code, GLM reading the fetched text, and the agent only for hard claims. The capture tool runs in its own locked-down container.

### EVD-015 — Video evidence (later)

**Status:** Deferred

A clip of the original statement, found by its transcript (Parakeet and `word_timings.align`), with the quoted words shown, using the `video` kind kept in §4.5.

---

## 7. Progress tracking

Follow `Implementation_phases.md` §6 (status values, what to update when a phase changes status, never renumbering). In this document, when a phase changes status:

1. Update its **Status** line in §6.
2. Update its row in the §5 table and the **Progress snapshot**.
3. Add a row to Appendix B.

Tick checklist items as they are done. Write the **Completion notes** before marking a phase Completed: the real names of tables, columns, job types, settings, endpoints, modules and UI components, each "Planning decides" item and how it was decided, and any deviation from Scope. If a phase changes a contract in §4, update §4 too.

---

## 8. Open questions and risks

### 8.1 Open questions

| ID | Question | Default until answered |
|----|----------|------------------------|
| Q-E1 | Is evidence only for explainers with a continuous voice? | Yes, the same as graphic shots (EV-1). |
| Q-E2 | Must every claim with evidence to show get an evidence shot? | Yes, unless the planner gives a reason the board shows (EVD-009). |
| Q-E3 | Where is the files folder? | `~/VisioStudioData` on the Mac's own disk. An external disk is possible, but must be connected whenever Docker starts. |
| Q-E4 | How many pieces of evidence can one claim show? | As many as fit its words; at least one (EVD-007). |
| Q-E5 | When is the old media copy removed (STOR-003)? | After one week of normal use, on the owner's explicit go-ahead. |

### 8.2 Risks

- **Copyright.** Screenshots of other people's pages in published videos. Short excerpts with a clear source and commentary are generally safer, but the rules differ by country. This is the owner's judgement, not legal advice.
- **Sources that cannot be captured.** Paywalls, logins, bot checks and cookie walls. These claims come back `blocked`. Supplying a PDF by hand can come later.
- **Stock prices.** A live quote page shows today's price, so a screenshot rarely proves a past price. Until EVD-013, a dated article or filing is the better source.
- **Agent quality varies** between Cursor and Claude and between runs. The checks prove only that the quote is in the captured source; the owner's review is the final guard.
- **Prompt injection.** Pages may carry instructions aimed at agents. The clean round folder, the skill's rules, the tool's limits and the untrusted import limit the harm.
- **Disk space.** 25 GB of media now lives on the Mac's disk instead of in Docker's disk image, and keeps growing there. There was about 40 GB free on 2026-11-13.
- **Bind mount speed.** Docker Desktop bind mounts are slower than volumes for many small files. The media files are mostly large, and `tmp` shares the mount (S-3).
- **Licences.** Some PDF and browser libraries have strong copyleft licences (PyMuPDF is AGPL). EVD-004 and EVD-006 choose with this in mind.
- **Skill format.** Cursor and Claude read similar skill files, but not identically. EVD-005 checks both.

---

## Appendix A — Test set

The owner assembles it from real sources before EVD-004 is verified. It is used again in EVD-005 and EVD-010.

| # | Claim kind | Source kind | Expected |
|---|-----------|-------------|----------|
| 1 | A company figure | An annual report PDF, with the quote over two lines | `found`, pdf, multi-line rectangles |
| 2 | Something a named person said | A news article | `found`, web |
| 3 | An official statistic | A government statistics page | `found`, web, `primary` |
| 4 | A stock price on a given date | A dated news article or filing | `found` or `partial` |
| 5 | A deliberately wrong number | Any good source for the right number | `contradicted` |
| 6 | A vague or obscure claim | — | `not_found`, with attempts |
| 7 | A real claim behind a paywall | A paywalled article | `blocked` |

Inputs for the capture tool alone (EVD-004): a page with a cookie banner, an address that redirects, a private address (`http://192.168.1.1`, refused), a scanned PDF with no text layer (refused), and a quote that is not on the page (refused, with near text).

---

## Appendix B — Progress log

| Date | Id | Event | Notes |
|------|----|-------|-------|
| 2026-11-13 | — | Document written | From the design discussion with the owner. Before writing, Docker's unused build cache and nine unused images were removed with the owner's go-ahead; the Mac went from 3.4 GB to 40 GB free. |
| 2026-11-13 | STOR-001 | In Progress | Code, compose, docs and throwaway checks done. The real app was not rebuilt because jobs were running. Then: rebuild the real app, spot check, mark Completed. |
| 2026-11-16 | STOR-001 | Completed | Real app rebuilt and checked. Throwaway project removed by the owner. Media measured at 28 GB; about 20 GB of caches cleared so STOR-002 has room (43 GB free). |
| 2026-11-16 | STOR-002 | In Progress | Media (10,342 files, 28.7 GB) copied in 7 min, verified exact (counts, bytes, every SHA-256, database hashes), app switched to the Mac folder. Smoke test left. |
| 2026-11-16 | STOR-003 | Completed | Old copy removed after a fresh exact re-verification. Docker disk image 75 GB to 48 GB; Mac free space 18 GB to 44 GB. The new-file smoke test of STOR-002 is still open. |
| 2026-11-16 | STOR-004 | Completed | Daily and on-demand snapshots (one kept) in `db-snapshots/`, Settings Backups tab, header warning, README restore steps. Real app rebuilt: a snapshot took 25 s (643 MB), integrity check ok, app stayed responsive. Restore commands not run. |
| 2026-11-17 | EVD-001 | Completed | Migration `0098`: `project.evidence`, six evidence tables, four job types. Real app rebuilt and the API rules checked with throwaway projects; owner to look at the create and settings forms. |
| 2026-11-17 | EVD-002 | Completed | Claim marks, GLM's proposals (one real call checked) and keep or drop, as `evidence_claim_list` versions; marks follow the story on read; new pipeline step `evidence_claims` (a run asks GLM once). No migration. Real app rebuilt and checked with throwaway projects; owner to look at the panel in the browser. |
| 2026-11-17 | EVD-003 | Completed | `evidence` step (needs `story_bible` and `evidence_claims`; `shot_plans` needs it), `write_evidence_brief` job and round folder in the files folder, `waiting_for` run pause that goes on by itself, board status `owner`, evidence API and panel. No migration. Real app rebuilt and checked with throwaway projects; a waiting run end to end and the UI in the browser are left to the owner. |
| 2026-11-17 | EVD-004 | Completed | `tools/evidence-capture/` (Python, Playwright, pypdfium2): `web`, `pdf`, `report`, `remove`, `validate`, `draw`. Checked on real public pages and PDFs, in both orientations, with refusals (private address, scan, missing quote) and a hand-broken round. No backend change. A public-to-private redirect makes one blind GET before it is refused (see the notes). The owner's Appendix A set is still to be run. |
| 2026-11-17 | EVD-005 | In Progress | `tools/evidence-skill/` (`visio-evidence` skill, reference, `install.sh`, installed to `~/.claude/skills/` for Cursor and Claude Code), the README prompt in `evidence_rounds.py` replaced, README section added. No migration. Not yet run by an agent: the owner's runs in Cursor and Claude Code on the test round are left, and the real app is not rebuilt. |
| 2026-11-17 | EVD-006 | Completed | `import_evidence` job: reads the newest round's `results/` safely, runs checks 1 to 5 with the tool's quote rules (`pypdfium2` added to the backend), copies the files of usable pieces into `media/` under generated names (identical files are shared), stores `evidence_import` and `evidence_item` rows; Import button and report on the evidence panel. No migration. Checked end to end on a throwaway backend with real captures and six hand-broken cases; the real app is not rebuilt yet (new dependency) and the panel is not seen in the browser. |
| 2026-11-17 | EVD-007 | Completed | Review of the newest import: `services/evidence_review.py`, `GET .../evidence/review`, `PUT .../review/claims/{claim_id}`, `POST .../review/done`, and the review in the evidence panel (claim cards, highlights drawn over the clean screenshot, context window, accept or reject, shown order, "No proof on screen"). Every change is an `evidence_review` version; "Review done" completes the `evidence` step. No migration. Checked end to end on a throwaway backend with real captures (decisions, reload, re-import, a re-captured piece, claims changed, evidence off). The real app is not rebuilt (EVD-006 is still waiting for it too) and the screen is not seen in the browser. |
