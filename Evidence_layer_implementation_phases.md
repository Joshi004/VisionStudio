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

- **`evidence`**, "Gather the evidence" (story-wide, EVD-003). It needs no model step: it works from the saved script and the claim list. It is complete when the newest round has been imported and reviewed, and the claim list has not changed since that round's brief. It is skipped as complete when evidence does not apply (EV-1, EV-2) and, **planning decides** in EVD-003, when the claim list is empty.
- **`shot_plans`** gains `evidence` in its needs (EVD-003).
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

### 4.6 The checks on import

The import (EVD-006) checks every piece of evidence in this order. The capture tool's `validate` command (EVD-004) applies checks 1 to 4 too, so the agent can fix problems before the owner imports.

1. **Shape.** The schema and version are known, the round and claim ids match the brief, and every value is one the contract allows.
2. **Files.** Every file named is inside its claim's folder and is a regular file (no link). Its type is checked from its content (PNG, JPEG, PDF, UTF-8 text), its size is within limits, and its SHA-256 matches the one recorded.
3. **Quote.** After normalising (NFKC, curly quotes, spaces, soft hyphens), the quote is found in the text copy (web) or in the PDF's text on `page` (pdf).
4. **Rectangles.** Each lies inside the image, is not empty, and there are no more than a set number of them.
5. **Numbers.** A number the claim says (`numbers_in`) that the quote does not say gives a **warning**, never a refusal.
6. **The owner.** Accepts or rejects (EVD-007).

A failure in checks 1 to 4 makes that piece of evidence unusable, and the review screen shows why. The checks prove that the quote is really in the captured source. They do not prove that the source is right: the owner's review does that.

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
| STOR-001 | A files folder outside Docker | Code | — | In Progress |
| STOR-002 | Move the existing media | Owner | STOR-001 | Not Started |
| STOR-003 | Remove the old media copy from the volume | Owner, later | STOR-002 | Not Started |
| STOR-004 | Database snapshots in the files folder | Code, optional | STOR-001 | Not Started |
| EVD-001 | Evidence switch, tables and job types | Code | — | Not Started |
| EVD-002 | Marking claims and GLM's proposals | Code | EVD-001 | Not Started |
| EVD-003 | The research brief and the waiting step | Code | EVD-002, STOR-001 | Not Started |
| EVD-004 | The capture tool | Code (Mac) | — | Not Started |
| EVD-005 | The research skill for Cursor and Claude | Code (Mac) | EVD-004 | Not Started |
| EVD-006 | Importing and checking the evidence | Code | EVD-003, EVD-004 | Not Started |
| EVD-007 | The review screen | Code | EVD-006 | Not Started |
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

**Progress snapshot:** 0 completed, 1 in progress (STOR-001: code done and checked in a throwaway setup; waiting for the real app to be rebuilt). Ready to start: EVD-001, EVD-004.

---

## 6. Phases

### STOR-001 — A files folder outside Docker

**Status:** In Progress

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
- [ ] Real app rebuilt with the setting unset, and the regression spot check (not done: a story-pipeline run and 14 lab image jobs were running on 2026-11-13, and a rebuild restarts the backend)

**Completion notes.**
- **Settings.** `.env` gets `COMPOSE_FILE=docker-compose.yml:docker-compose.files.yml` and `VISIO_FILES_DIR=<absolute host path>`. The override file `docker-compose.files.yml` mounts that folder at `/files` in `backend` and sets `FILES_DIR=/files` there. `FILES_DIR` defaults to `DATA_DIR`, so with it unset nothing changes. The database, `-wal` and the `rembg` model cache stay under `DATA_DIR`.
- **Config.** `AppConfig.files_dir`, `files_dir_is_separate`; `media_dir` and `tmp_dir` are now under `files_dir`. Later phases that need `evidence/` put it under `config.files_dir`.
- **Marker.** An empty file `.visio-studio-files` at the root of the files folder, **created by the owner** (`mkdir -p DIR/media && touch DIR/.visio-studio-files`). The app never writes it. It is required only when the folder is separate. `media/` must exist before the first start, because Compose binds it into `frontend` before the backend can create it.
- **Guard.** `services/storage.py`: `FILES_MARKER`, `FilesFolderUnavailable` (a `StorageError`), `Storage.files_folder_problem()` (marker plus a write probe in `tmp/`). `receive`, `new_temp_path`, `partial_download_path`, `_save_in` and `clear_tmp` refuse without the marker. At startup, `main.py` skips `mkdir` and `clear_tmp` when there is a problem, and a handler turns `FilesFolderUnavailable` into HTTP 503 `{"detail": ...}`. Reads and deletes are unchanged.
- **Health.** `GET /api/health` has a new `files: {ok, separate, problem}`; a problem makes the status `degraded` (HTTP 503). The header (`BackendStatus.tsx`) says "files folder". `schema.d.ts` regenerated.
- **Compose.** The base file's `frontend` now mounts only the volume's `media` folder (`volume.subpath`), read-only. The override replaces that with `<folder>/media`, read-only, and both bind mounts use `create_host_path: false`, so Docker refuses to start when the folder is missing. Needs Docker Compose 2.35 or later (`!override`, `subpath`).
- **Checked on 2026-11-13** in a throwaway project (`visio-stor-test`, own volume, port 5481, folder `~/VisioStudioData-stor-test`): setting unset (health `files.separate: false`, frontend `/data` holds only `media`); setting on (an uploaded image in `media/lab/`, served by nginx with 200, `tmp/` empty, no cross-device error); marker removed (health 503 with the message, upload refused, no new file); `tmp/` read-only (health reports "cannot be written"); missing folder (Compose refuses to start the backend). The old files stay in the Docker volume untouched.
- **Deviation.** The "setting unset" check ran on a fresh volume in the throwaway project, not on the real app. Commands to finish it: `docker compose up --build -d` when no run or job is active, then check `/api/health` and play a few existing files.
- **Left to clean up** (the owner's go-ahead needed): `docker compose -p visio-stor-test down`, `docker volume rm visio-stor-test_data`, remove `~/VisioStudioData-stor-test`. No `down -v`.

### STOR-002 — Move the existing media (owner)

**Status:** Not Started

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
- [ ] Idle and space checked
- [ ] Copy made and verified
- [ ] Switched and smoke-tested

**Completion notes.** _To be filled in: the folder used, the counts, the time the copy took, any hash mismatches found._

### STOR-003 — Remove the old media copy from the volume (owner, later)

**Status:** Not Started

**Objective.** Free the space the old media copy still takes inside Docker's disk image, once the owner trusts the new folder.

**Scope.**
- Only after the owner decides (Q-E5 suggests one week of normal use) and confirms explicitly.
- Remove **only the `media/` folder inside the volume**, using a throwaway container that mounts the volume. The database, its WAL and its backups are untouched. No `docker volume rm` and no `down -v`.
- Measure the size of Docker's disk image before and after.
- Optionally, move the three `backup-before-000N.db` files to the Mac folder.

**Dependencies.** STOR-002, and the owner's decision.

**Verification criteria.** The app still works, the volume's `media/` is gone, `app.db` is intact, and the freed space shows on the Mac.

**Completion notes.** _To be filled in._

### STOR-004 — Database snapshots in the files folder (optional)

**Status:** Not Started

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

**Completion notes.** _To be filled in._

### EVD-001 — Evidence switch, tables and job types

**Status:** Not Started

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
- [ ] Migration, models, `DATABASE_STRUCTURE.md`
- [ ] Switch on create form and settings, API checks
- [ ] Standard checks

**Completion notes.** _To be filled in._

### EVD-002 — Marking claims and GLM's proposals

**Status:** Not Started

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
- [ ] Marking UI and storage, re-anchoring
- [ ] Proposal job, instructions, parsing and locating
- [ ] Keep or drop review, versions
- [ ] Standard checks

**Completion notes.** _To be filled in._

### EVD-003 — The research brief and the waiting step

**Status:** Not Started

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
- [ ] Step, adapter, needs, board state
- [ ] Brief job, round folder, README
- [ ] Run behaviour while waiting, resume
- [ ] Standard checks

**Completion notes.** _To be filled in._

### EVD-004 — The capture tool

**Status:** Not Started

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
- [ ] Web capture, PDF capture, reporting, `validate`
- [ ] Safety limits
- [ ] Test set run

**Completion notes.** _To be filled in._

### EVD-005 — The research skill for Cursor and Claude

**Status:** Not Started

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
- [ ] Skill and reference text
- [ ] README prompt text
- [ ] Runs in both products recorded

**Completion notes.** _To be filled in: how each product behaved, the time and cost per claim._

### EVD-006 — Importing and checking the evidence

**Status:** Not Started

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
- [ ] Import job and checks
- [ ] Storage copy, limits, report
- [ ] Re-import behaviour
- [ ] Standard checks

**Completion notes.** _To be filled in._

### EVD-007 — The review screen

**Status:** Not Started

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
- [ ] Claim cards, evidence view with highlights
- [ ] Decisions, versions, "Review done"
- [ ] Standard checks

**Completion notes.** _To be filled in._

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
