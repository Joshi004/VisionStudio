# Visio Studio: Iteration 1 Build Phases

Status: written on 2026-10-05 from `ANALYSIS.md` (Revision 3) and `DATABASE_STRUCTURE.md`. No code exists yet.

This document splits iteration 1 into phases, fixes their order, and sets the rules every phase follows. Each phase is planned by one model (**the planner**, Opus 5.5) and then built by another (**the executor**, Sonnet 5.5). The planner of every phase gets this document together with `ANALYSIS.md` and `DATABASE_STRUCTURE.md`. "You" means the project owner.

How the three documents divide the work:

- `ANALYSIS.md` says **what** the system does and **why**.
- `DATABASE_STRUCTURE.md` is the **schema**.
- This document says **in which order** to build it, **what goes into each phase**, and **how a phase is planned, built and checked**. It does not change the design. Where it adds a rule the other two do not have, it says **Added here**. Where it found something they leave open, it says **Gap**. If it seems to contradict them, stop and ask.

References: "Section N" means a section of `ANALYSIS.md`, and "DB Section N" means a section of `DATABASE_STRUCTURE.md`. Sections of this document are named as "this document".

Iteration 1 is done when a 1-minute voiceover and its script become a finished video in the two-container app (Section 7, milestone M5), and the hardening in Phase 11 is complete.

## Contents

1. [How to run a phase](#1-how-to-run-a-phase)
2. [Phase overview and order](#2-phase-overview-and-order)
3. [What you need to provide, and when](#3-what-you-need-to-provide-and-when)
4. [Rules for every phase](#4-rules-for-every-phase)
5. [The phases](#5-the-phases)
6. [Coverage check](#6-coverage-check)
7. [Phase log](#7-phase-log)

---

## 1. How to run a phase

1. **Plan.** Start a planner session with the prompt below. The planner reads the code as it stands and the phase log (earlier phases may have recorded deviations), runs the checks its phase asks for (read-only, unless the phase says otherwise and you agree), and writes a plan file. It asks you about anything ambiguous and about every decision that is yours to make.
2. **Review.** Read the plan, answer its questions, approve it.
3. **Build.** Start an executor session with the prompt below. It follows the plan, runs the acceptance checks, and adds an entry to the phase log at the end of this document.
4. **Check and commit.** Repeat the acceptance checks yourself (they are written to be repeatable), then commit. A commit per phase keeps every phase reviewable and easy to roll back.

Run the phases one at a time. The one exception is Spike 1, which lives in its own folder and can run alongside Phases 1 to 4.

If a phase is too big for one plan, the planner may split it into "a" and "b", as long as the app works and can be checked after "a".

**Prompt for the planner**

```text
Plan Phase <N> (<name>) of Visio Studio iteration 1.

Read ITERATION_1_PHASES.md in full (especially Section 4, the Phase <N> section and the
phase log), then ANALYSIS.md and DATABASE_STRUCTURE.md, then the current code.
Write the plan to plans/phase-<NN>-<short-name>.md using the plan template in Section 4.6
of ITERATION_1_PHASES.md.
Stay inside the scope of Phase <N>. Resolve its [VERIFY] items where you can.
Ask me about anything you cannot resolve and about every decision that is mine to make.
Do not write application code.
```

**Prompt for the executor**

```text
Implement plans/phase-<NN>-<short-name>.md.

Follow Section 4 ("Rules for every phase") of ITERATION_1_PHASES.md.
Build only what the plan lists. If the code or a live service behaves differently from
the plan in a way that changes behaviour, stop and ask me instead of working around it.
When done, run every acceptance check in the plan, then add the Phase <N> entry to the
phase log at the end of ITERATION_1_PHASES.md.
```

---

## 2. Phase overview and order

| # | Phase | When it is done, you can | Builds on | Needs from you | Size |
|---|---|---|---|---|---|
| 1 | Foundation | open an empty app at `http://127.0.0.1:5480`, backed by the full database | | | M |
| 2 | Global settings and GPU connection test | set the GPU server URL in the UI and test it | 1 | | S |
| 3 | Projects, voiceover and script | create a project, upload and play the voiceover, paste the script | 1 | a sample voiceover and script | M |
| 4 | GPU API contract guard | record and approve your server's API, and see a banner when it changes | 2 | GPU server running, its URL | M |
| S1 | Spike 1: LTX keyframe test | read a report on how LTX-2.3 behaves with your frames | no app code | GPU server, 2 to 3 frame pairs, OK for 10 to 15 GPU runs | S |
| 5 | Background jobs and transcription | transcribe the voiceover, see every script word with its time, see all jobs on an Activity page | 3, 4 | | L |
| 6 | AI scene proposal | click Propose scenes and get scenes within the length limits | 5 | OK for a few paid calls | L |
| 7 | Cut review and editing | move, add and remove cuts | 6 | | M |
| 8 | Scene inputs | add a description and two frames per scene, and see the prompt and readiness | 6 (7 first is better) | frames | M |
| 9 | Clip generation | generate clips in parallel, preview them with sound, regenerate, pick takes, mute | 4, 8, S1 | GPU server | L |
| 10 | Final render | render, play and download the finished video | 9 | | M |
| 11 | Hardening and end-to-end runs | rely on it through restarts, outages and server changes | 10 | two real projects | M |

Size is a rough guide: S is small, M is normal, L is large enough that the planner should consider splitting it.

The table order is one valid sequence. The diagram shows the real dependencies, so you can see which swaps are safe (for example Phase 4 before Phase 3 if your server is up early).

```mermaid
flowchart TD
    P1["1 Foundation"] --> P2["2 Settings"]
    P1 --> P3["3 Projects, voiceover, script"]
    P2 --> P4["4 Contract guard"]
    P3 --> P5["5 Jobs and transcription"]
    P4 --> P5
    P5 --> P6["6 AI scene proposal"]
    P6 --> P7["7 Cut editing"]
    P6 --> P8["8 Scene inputs"]
    P7 -.->|recommended first| P8
    P8 --> P9["9 Clip generation"]
    S1["Spike 1: LTX"] --> P9
    P9 --> P10["10 Final render"]
    P10 --> P11["11 Hardening"]
    U1(["You: GPU server running"]) --> P4
    U1 --> S1
    U1 --> P5
    U3(["You: frame pairs"]) --> S1
```

**Your GPU server is the critical path.** Phases 1 to 3 need nothing external. From Phase 4 on, every phase needs the GPU server, including Phase 5, which now also gets a working transcription endpoint from it (confirmed live 2026-10-05, Section 5.1 of `ANALYSIS.md`) — no separate dependency to wait on. Spike 1 needs the server and your frames but no app code, so run it as early as you can.

**Why these phases, in this order**

- Each phase is one coherent feature: small enough to plan in one session and build in one session, and it ends with something you can check in the UI.
- Simple phases (settings, projects) set the code patterns before the hard ones (the dispatcher, generation).
- Work that needs nothing external comes first, which gives you time to bring up the GPU server.
- The biggest unknown, how LTX behaves with two anchor frames, is measured in Spike 1 before the largest phase (9) is planned.

**Mapping to ANALYSIS.md.** Milestone M0 became Phases 1, 2 and 4. M1 is Phase 3. M2 became Phases 5, 6 and 7. M3 is Phase 8, M4 is Phase 9, M5 is Phase 10 and M6 is Phase 11. Of the three spikes in Section 7, Spike 1 (LTX) is its own step, Spike 2 (transcription) is the first planning step of Phase 5, and Spike 3 (cut proposal) is the first planning step of Phase 6. Spike 3 still needs something that exists only just before Phase 6 (a real transcript from Phase 5). Spike 2's endpoint now exists and is documented (Section 5.1), so it is runnable as soon as Phase 5 starts; what it still measures is real accuracy, not the contract.

---

## 3. What you need to provide, and when

| Before | What | Why |
|---|---|---|
| Phase 1 | Nothing required. Say so if you disagree with a convention in DB Section 8, or with port 5480. | Phase 1 adopts them as they are |
| Phase 3 | A sample voiceover and its script. A short one (20 to 30 seconds, about 5 to 8 scenes) keeps the frame work small while building. Full minutes come in Phase 11. | Acceptance checks from Phase 3 on |
| Phase 4 | The GPU server running, and its current URL | The planner reads the live guide and OpenAPI spec (Section 9, question 2) |
| Spike 1 | 2 to 3 pairs of first and last frames in your orientation, each with a short scene description, and an OK for 10 to 15 GPU runs of 5 to 10 minutes each | Section 9, question 1 |
| Phase 5 | Nothing new — the transcription endpoint exists and is documented (Section 5.1, confirmed live 2026-10-05, guide `api_version` 0.3.0). Just the GPU server running, as for every phase from 4 on. | The planner can read the real contract instead of a draft; Spike 2 still measures accuracy on a real recording |
| Phase 6 | An OK for a few paid Bitdeer calls during planning and checking (fractions of a cent each), and the cuts you would make by hand for the sample | Spike 3 compares the AI's cuts with yours |
| Phase 8 | First and last frames for the sample's scenes. For checks, one pair may be reused across scenes. | |
| Phases 9 to 11 | Time to watch and listen | Only you can judge quality, and whether clip sound contains words |

For every phase: review the plan, answer its questions, check the result, commit.

---

## 4. Rules for every phase

### 4.1 Scope and safety

1. **Build only what the phase lists.** If something seems missing, ask. Do not build ahead. The only forward-looking work allowed is what a phase lists under "Provides".
2. **The design lives in ANALYSIS.md and DATABASE_STRUCTURE.md.** Deviations are proposed by the planner, approved by you, and recorded in the phase log. A schema change means a new Alembic migration and an update to DATABASE_STRUCTURE.md in the same phase.
3. **Ask before:** any paid Bitdeer call, including during planning or checking; submitting more than two GPU jobs at a time during development; anything that deletes data (`docker compose down -v`, removing the `data` volume, deleting files or rows outside the app's normal flow); pushing to a remote.
4. **Secrets:** never print, log or commit `.env` or the key, and never send the key to the frontend. The Bitdeer key goes only to `api-inference.bitdeer.ai` (Section 3.7).
5. **No automated tests unless you ask for them** (your standing rule). Phases are checked with their manual acceptance checks. If you want tests later, the pure functions give the most value: transcript matching (Phase 5), the cut checks and splitter (Phase 6), and frame counts (Phase 9).
6. **No mock servers.** Check against your real GPU server and Bitdeer, and let phases that need them say so. (Added here: a fake GPU server would drift from the real API and hide exactly the changes Phase 4 guards against.)
7. **Two containers only**, `frontend` and `backend` (Section 3.1). No extra services, queues or databases.
8. **Dependencies:** add a library in the phase that first needs it. Use current stable versions, checked at planning time rather than taken from memory.

### 4.2 Architecture rules (from ANALYSIS.md)

- **One backend process**: a single uvicorn worker, because the dispatcher loop lives in it (Section 3.3).
- **Never block the event loop**: async HTTP, async database access (unless Phase 1 records otherwise), FFmpeg as a child process, heavy Pillow work in a thread.
- **Background work is a `job` row** run by the dispatcher, from Phase 5 on. Endpoints that start work return HTTP 202 with the job.
- **The browser never polls**: no refetch intervals, no WebSocket, no SSE. Data refreshes on page load, on returning to the tab, and with a Refresh button (Section 3.4).
- **Page loads never wait for the GPU server.** They read the database. Server status shown in the UI is whatever the dispatcher or a Test button last stored (Section 3.3, "Keeps the DB current").
- **The frontend talks only to `/api` and `/media`**, never to the GPU server or the LLM.
- **Settings are read when used**, through the settings service from Phase 2. Project values come from the `project` row.
- **All outbound HTTP goes through the shared helper** from Phase 2: Docker address mapping, timeouts, size limits, no redirects to another host, an explicit User-Agent, and the key rule.
- **Files only through `Storage`** (Section 3.5): server-generated names, checked paths, and only paths and metadata in the database. Stored files are never deleted in iteration 1. Temporary working files are.
- **FFmpeg and ffprobe only through the wrapper** from Phase 3: argument lists, never `shell=True`, low priority (Section 5.6).
- **Short transactions.** SQLite has one writer at a time. Never hold a transaction open across a network call or a child process.
- **Manual-first, AI-ready** (Section 4.2): every artifact records its `source`, and readiness is computed, never stored.

### 4.3 Code conventions

Phase 1 sets these, and records in the phase log any detail it fixes.

- Repo layout as in Section 7, plus `plans/` for phase plans and `spikes/` for throwaway scripts.
- Backend: Python with type hints, FastAPI, SQLAlchemy 2.x, Alembic and `uv`. All routes under `/api`. Pydantic request and response models are kept separate from ORM models, so the OpenAPI schema, and the frontend types generated from it, are accurate. Errors use FastAPI's `{"detail": ...}` with a readable message. Times are UTC.
- Actions that start work: `POST /api/<resource>/{id}/<action>`, returning 202 and the job.
- Frontend: TypeScript strict, React with Vite, TanStack Query for all server data, API types generated with `openapi-typescript` from the running backend and committed (regenerate after every API change), and one UI component library.
- `ruff` (lint and format) for Python, `tsc` and ESLint for the frontend, all clean at the end of every phase.
- Comments only where the code cannot say it itself.

### 4.4 Definition of done

1. Every acceptance check in the plan passes. The executor ran them, and you can repeat them.
2. `docker compose up --build` works from a clean checkout and on the existing `data` volume (migrations apply without losing data).
3. Linters are clean, and API types are regenerated if the API changed.
4. The main flow of the earlier phases still works.
5. The phase log entry is written, and DATABASE_STRUCTURE.md is updated if the schema changed.

### 4.5 Environment facts (checked on 2026-10-05)

- Docker Desktop 28.1.1 on arm64, Compose 2.35.1. Use native arm64 images.
- The Mac has Node 24.1, npm 11.4, `uv` 0.12.5, Python 3.13.7, FFmpeg 8.0 and git 2.50. The app uses the FFmpeg **inside the backend image**, whose version will differ. Phase 1 records it.
- Ports in use include 5173 (Vite's default) and 8000, held by Cursor, and 3001, 3501, 5174, 5190, 5432, 5433, 5501, 5544, 8010, 8011, 8080 and 8088, held by Docker. 5480 was free. Re-check before choosing.
- The GPU server is reached through a Cursor port forward on `127.0.0.1:8012`, which is `http://host.docker.internal:8012` from inside a container. Its health endpoint was `/v1/health` on 2026-10-04.
- There is no git repository yet, and `.env` holds a real key.

### 4.6 Plan template

Every plan file has these parts:

1. **Goal and outcome**, refined from the phase section.
2. **Findings**: the state of the code, the phase log entries that matter, and the results of the [VERIFY] checks.
3. **Decisions**: one line each, with the choice and the reason. Mark the ones that need your approval.
4. **Changes**: database (migration), backend (files, functions and their signatures), API (method, path, request, response, errors), background jobs (states, phases, what happens on restart), frontend (routes, components, and their empty, loading and error states), configuration.
5. **Reading list for the executor**: the exact sections of ANALYSIS.md and DATABASE_STRUCTURE.md it needs.
6. **Steps in order**, each ending at a point where something can be checked.
7. **Acceptance checks**: exact commands and clicks, with expected results.
8. **Out of scope**: what the executor must not build.
9. **Risks**: what might differ from the plan, and whether the executor should stop and ask or adjust.

---

## 5. The phases

### Phase 1: Foundation

**Goal.** A two-container app that starts with one command, with the full database schema, the security baseline and the conventions the other phases follow. No features.

**Read first.** Sections 2, 3.1, 3.5, 3.6, 3.7 (the rules after the table), 4.1, 5.9 and 7. All of DATABASE_STRUCTURE.md.

**In scope**

- `.gitignore` before anything else (`.env`, `data/`, `node_modules`, virtual environments, build output, `spikes/**/input` and `spikes/**/output`), then `git init`. Check `git check-ignore .env` before the first commit. `.dockerignore` files so `.env` never enters an image.
- `.env.example` with the variable names from Section 3.1 and no values.
- Docker Compose: `frontend` (nginx serving the built React app) and `backend` (FastAPI, one uvicorn worker); a named volume `data`, read-write in the backend and read-only in the frontend; healthchecks; a restart policy. Only the frontend port is published, on `127.0.0.1` (5480 suggested, configurable). The backend is reached only through nginx's `/api` proxy.
- nginx: `/api/` proxied to the backend with the original `Host` header; `/media/` served read-only from the volume, with Range requests for seeking; SPA fallback; a request-size limit that fits Phase 3's uploads.
- Backend skeleton in the Section 7 layout: configuration from environment variables, logging to stdout, docs at `/api/docs`, and `GET /api/health` (database reachable, FFmpeg and ffprobe versions).
- Database: SQLAlchemy models for **all seven tables** exactly as in DB Section 4, in one initial Alembic migration with the CHECK constraints and indexes. The schema is settled, so later phases share one model, and later changes are new migrations. WAL mode, `foreign_keys=ON` and a busy timeout on every connection. The file lives on the `data` volume. Migrations run at backend start.
- Security baseline (Section 3.7): reject requests whose `Host` is not `localhost` or `127.0.0.1`; reject state-changing requests whose `Origin` header is present and does not match the `Host`; no CORS middleware; JSON endpoints accept only JSON. (Added here, the Origin check: browsers send multipart uploads to other sites without a preflight, so "no CORS headers" alone does not protect the upload endpoints of Phases 3 and 8.)
- Backend image: native arm64, a current Python (3.13 matches the Mac), `uv`, and FFmpeg and ffprobe from the distribution.
- Frontend: Vite, React, TypeScript strict, React Router, TanStack Query, generated API types with a typed fetch client, the component library, and an app shell with navigation to placeholder Projects, Settings and Activity pages and a shared Refresh button.
- `npm run gen:api`, which regenerates the API types from `http://127.0.0.1:5480/api/openapi.json`. Node runs on the Mac.
- A short README: start, stop, rebuild, regenerate the API types, where data lives, and a warning never to run `docker compose down -v`.

**Out of scope.** Any feature. A hot-reload development setup (it can come later, if it keeps the Host and Origin checks intact).

**Decisions for the planner**

- Async or sync database access. Recommended: async SQLAlchemy with `aiosqlite` in the app, because the dispatcher lives in the event loop. Alembic may use the plain sync driver.
- The UI component library.
- The volume layout. Suggested: `/data/app.db` and `/data/media/<project_id>/<uuid>.<ext>`, with the database outside the media directory.
- How to declare the circular foreign key between `project.voiceover_asset_id` and `asset.project_id` (DB Section 3) so the migration works on SQLite.
- Whether the backend runs as a non-root user (preferred). If so, create `/data` in the image owned by that user, so the new named volume takes that ownership.
- The frontend route map. Suggested: `/projects`, `/projects/:id` with one section per step of the Section 1 flow, `/projects/:id/settings`, `/settings` and `/activity`.

**[VERIFY]**

- The Host and Origin checks work through the nginx proxy (Section 3.7 asks for this in M0).
- WAL and foreign keys are on. `foreign_keys` is set per connection, so check it through the app's engine, not a separate `sqlite3` session.
- The images are arm64.

**Provides.** The app factory and `/api` routing, the database engine and session helpers, all ORM models, the migration workflow, the security middleware, the frontend shell, the API client and the Refresh pattern.

**Acceptance checks**

1. With `.env` present, `docker compose up --build -d` brings both services to healthy.
2. `curl http://127.0.0.1:5480/api/health` reports the database as OK and shows the FFmpeg version.
3. The app shell loads at `http://127.0.0.1:5480`, and reloading a deep link such as `/settings` works.
4. A request with `Host: evil.example` is rejected, and so is a POST with `Origin: https://evil.example`.
5. All seven tables and their indexes exist. Through the app's engine, `journal_mode` is `wal` and `foreign_keys` is 1.
6. After `docker compose down` and `up`, the database file and its migration state are still there.
7. `git check-ignore .env` prints `.env`, and no image contains `.env`.
8. `ruff`, `tsc` and ESLint are clean.

**Pitfalls**

- nginx `alias` traversal: write `location /media/ { alias /data/media/; }` with both trailing slashes.
- nginx limits request bodies to 1 MB by default.
- SQLAlchemy does not notice in-place changes to a JSON column. Assign a new object.
- With async SQLAlchemy, lazy loading fails. Load relationships explicitly and use `expire_on_commit=False`.
- SQLite stores no time zone. Store UTC and add the zone when returning times, or elapsed times in the browser will be off by your 5.5-hour offset.

### Phase 2: Global settings and GPU connection test

**Goal.** Global settings stored in the database and edited on a Settings page, with a Test connection button for the GPU server.

**Read first.** Sections 3.1 ("Configuration has two layers"), 3.6 and 3.7. DB Sections 4.6 and 6.

**In scope**

- A settings registry for every global key in DB Section 6 except `api_contract_sources` (Phase 4 adds it with its own editor): type, built-in default, environment variable, validation and help text.
- Precedence: saved value, then environment variable, then built-in default, read at the moment of use. The API returns each effective value and where it came from.
- URL rules (Section 3.7): `http` and `https` only, no user name or password. `localhost` and `127.0.0.1` map to `host.docker.internal`, and the page shows "will call: ...".
- **The shared outbound HTTP helper** that every later phase uses: per-call timeouts and response size limits (small for JSON, larger for media downloads), no redirects to another host, an explicit User-Agent (the Cloudflare finding in Section 3.6), and the Bitdeer key attached only for `api-inference.bitdeer.ai`.
- Secrets shown only as "key set: yes or no".
- **Test connection**: calls the GPU server's health endpoint and shows reachable or unreachable, the address called and the response time. Unreachable is a normal result, not an error.
- The Settings page.

**Out of scope.** Recording the API (Phase 4). Testing the transcription URL (Phase 5) or the LLM (Phase 6).

**Decisions for the planner.** Allowed ranges for the numeric settings. Whether the last test result is kept in memory or stored (Phase 4's banner needs a remembered state).

**[VERIFY].** The health path and response on the current server. Reaching it from inside the container through the mapped address.

**Provides.** The settings service (read an effective value, save with validation), the outbound HTTP helper and the GPU health check.

**Acceptance checks**

1. The page lists every setting with its value and its source: saved, environment or built-in.
2. Saving `http://localhost:8012` shows "will call: http://host.docker.internal:8012", and the value survives a restart.
3. `ftp://...` and `http://user:pass@host` are rejected with a clear message.
4. Test connection says reachable when the server is up, and unreachable, without an error page, when it is down.
5. No API response contains the Bitdeer key.

### Phase 3: Projects, voiceover and script

**Goal.** Create a project with orientation first, edit its settings and guidelines, upload the voiceover, paste the script and play the audio.

**Needs.** From you: a sample voiceover and its script (see this document, Section 3).

**Read first.** Sections 0 (decisions 1, 2, 3 and 6), 1 (the first two steps of the flow), 3.5, 4.2, 4.4, 5.4 (the guideline fields) and 5.9 (upload abuse). DB Sections 4.1, 4.2 and 7.

**In scope**

- Project list, create (orientation first, defaults from Section 4.4), view and edit.
- Project settings and guidelines: generation and output size, fps, minimum and maximum scene length, `style_prefix`, `prompt_suffix`, `negative_prompt`, clip sound volume and cut instructions. Generation sizes must be multiples of 64, output sizes must be even (H.264 needs it), and the minimum must be below the maximum. The page states the size to create frames at.
- The `Storage` interface (save, open, get_path) with server-generated names and path checks, and the media URL convention.
- The FFmpeg and ffprobe wrapper (Section 5.6 rules). Its first use is probing uploads.
- Voiceover upload: size and type limits, an ffprobe check (an audio stream exists, its duration), SHA-256, an `asset` row (`kind = voiceover`, `source = upload`) and `project.voiceover_asset_id`. A new upload creates a new asset and repoints the project, and the old file stays.
- The voiceover is kept exactly as uploaded. Phase 5 sends it to the transcription endpoint as-is when its format is already one Parakeet accepts (Section 5.1 lists them; WAV, MP3 and M4A all qualify), and converts a copy only otherwise. The final mix always uses the original (Section 5.6).
- The script, saved exactly as pasted, blank lines included (they are scene-break hints, Section 5.2).
- Playing the voiceover from `/media`, with seeking.

**Out of scope.** Transcription, scenes, frames. Deleting projects or files.

**Decisions for the planner.** Upload size limits (a 15-minute 48 kHz stereo WAV is about 170 MB). Whether orientation can change after creation.

**[VERIFY].** Seeking works through nginx: a Range request for a media URL returns 206.

**Provides.** `Storage`, the FFmpeg and ffprobe wrapper, a helper that creates an `asset` row from a stored file, the orientation defaults and the project validation.

**Acceptance checks**

1. A new landscape project gets 1920 x 1088 generation, 1920 x 1080 output, 24 fps, 2 to 6 s and 20 percent clip sound. A portrait project gets the sizes swapped.
2. A generation width of 1900, or a minimum at or above the maximum, is rejected with a message.
3. WAV, MP3 and M4A uploads work, the asset row has the right duration, and the player seeks.
4. A text file renamed to `.mp3` is rejected, and an oversized file gets a clear message.
5. A script with blank lines comes back exactly as pasted.
6. Everything survives a restart, and files on disk have generated names only.

### Phase 4: GPU API contract guard

**Goal.** Record your GPU server's API, approve it once, and check it before every submission (Section 6.5).

**Needs.** From you: the server running, and its current URL. The planner first reads the live guide and OpenAPI documents, with GET requests only (Section 9, question 2) — a first read already happened on 2026-10-05 (see `[VERIFY]` below), but the planner still performs the app's own first **approval** through the flow it builds.

**Read first.** Sections 3.4 (banners), 5.8 (the row on the recorded GPU API changing), 6.1 and 6.5. DB Section 4.7.

**In scope**

- The `api_contract_sources` setting with an editor. Defaults: the guide (`/v1/guide?format=json`) and the OpenAPI spec (`/openapi.json`), stored as paths relative to a base URL.
- Fetching with time and size limits, and the fingerprint rule: the document's own `content_hash` if present, otherwise the SHA-256 of canonical JSON without `servers`.
- **Capture and approve**: fetch twice a few seconds apart, refuse a source that changed in between, and show what differs. Snapshots are only ever inserted. The baseline is the latest approved snapshot per source.
- **`check()`**: returns ok, changed with a diff, or unreachable. A change stores a pending snapshot. With no approved baseline yet it reports "not approved", so nothing can be submitted before your first approval.
- The diff: the changed JSON paths, plus an OpenAPI summary of operations added, removed and changed.
- The approved API list: version, fingerprints, approval time, and operations grouped by tag.
- A banner on every page for "GPU API changed", with the number of jobs waiting (zero until Phase 5), and for "GPU server unreachable".
- Test connection now runs the health check and the contract check.

**Out of scope.** Pausing jobs (Phase 5 calls `check()` from the dispatcher). Gating only on the operations the app calls (Section 6.5 leaves that for later).

**Decisions for the planner**

- **Gap:** Section 6.5 allows a source on another host (the transcription API), but sources are relative to "the server URL". In practice, as of 2026-10-05, transcription (`/v1/parakeet`) is on the *same* server and the *same* single `openapi.json` as LTX, so this does not come up yet. Still decide how a source would name its base, in case that ever changes or the transcription URL setting (Section 3.7) is pointed elsewhere.
- Repeated checks against the same change must not insert a new pending snapshot each time.
- What the banner reads, given this document's rule that page loads never wait for the GPU server.

**Already confirmed, from a manual read-only check on 2026-10-05 (not the app's own approval flow)**

- `content_hash` sits at the **top level** of the guide JSON (`GET /v1/guide?format=json`), as a `"sha256:..."` string.
- The server exposes exactly **one** combined OpenAPI document (`/openapi.json`) covering every backend, including transcription. There is no separate swagger document to add as a second source currently.
- Neither the guide nor the health response names an underlying model checkpoint or weights version — only a display name and path prefix per backend (Section 6.5, "Limits of this check," `ANALYSIS.md` Revision 4).
- Two fetches of the guide, a few seconds apart, gave the **same** `content_hash`, even though the neighbouring `generated_at` field differed between them.

**[VERIFY]**

- That the planner's own implementation reproduces the same `content_hash` stability and fingerprint rule end to end, through the actual `approve()`/`check()` code, not just a manual curl check.

**Provides.** `ContractGuard.check()` and `approve()`, and the system status the banner reads.

**Acceptance checks**

1. With the server up, both default sources are captured and approved, and the API list shows the version and the operations by tag.
2. A live endpoint such as `/v1/health`, added as a source, is refused as "changes by itself" if its body changes between fetches.
3. Editing the approved fingerprint directly in the database (or a real server update) makes the banner show a change. Approve clears it, and the old snapshot stays as history.
4. With the server down, pages still load quickly and the banner says unreachable.

### Spike 1: LTX keyframe test

**Goal.** Measure how LTX-2.3 behaves with your frames before Phase 9 is planned (Section 7, Step 0, item 1).

**Needs.** From you: the server running; 2 to 3 pairs of first and last frames in your orientation, each with a short scene description; an OK for 10 to 15 GPU runs.

**Read first.** Sections 5.3, 5.4, 5.6, 5.8, 6.1, and Step 0 in Section 7.

**In scope**

- Plain scripts in `spikes/ltx/`, written in Python with `httpx` and run on the Mac with `uv`. They touch no app code. Inputs go in `spikes/ltx/input/` and outputs in `spikes/ltx/output/`, both git-ignored.
- The whole job life cycle as the live guide describes it: upload the frames, submit `keyframe-interpolation` (first frame at `frame_idx` 0, last at `num_frames - 1`, strength 1.0), poll, download, purge.
- Runs: each pair with and without guidelines; one batch of 4 at once; sound checks (no quotes; with and without speech words in the negative prompt; with sounds described in the prompt). Optionally the fast `generate` call with two images.
- For each run, the spike records the request, the queue and run times, `typical_run_seconds`, and from ffprobe the frame count, fps, size, audio codec, sample rate and channels. You record how closely the clip hits both frames, how natural the motion is, and whether you hear anything like speech.
- `spikes/ltx/REPORT.md` with: the findings; the request and response shapes for upload, submit, status, download, cancel and purge (as observed, or as documented where not exercised); the errors seen; and concrete recommendations for Phases 8, 9 and 10 (endpoint, request fields, a default negative prompt, the clip sound volume, guidance on choosing frames).

**Acceptance.** The report answers every question in Step 0, item 1, and you agree with its conclusions after watching the clips.

The spike is small enough for one session: the planner can write and run the scripts itself, with your OK for the GPU runs.

### Phase 5: Background jobs and transcription

**Goal.** The dispatcher loop and job framework, with state in the database and resume after a restart (Section 3.3); an Activity page; and the first job type, transcription matched to your script (Section 5.1).

**Needs.** The transcription endpoint already exists and is documented (Section 5.1, confirmed live 2026-10-05, guide `api_version` 0.3.0): `POST /v1/parakeet/transcribe`. Its addition is itself the kind of server change Phase 4 is built to catch, so re-approve the API in Settings first if the contract guard flags it.

**First planning step (Spike 2 in ANALYSIS.md).** Most of the shape discovery this spike originally existed for is already done (Section 5.1): the request and response shapes, submit-then-poll mechanics, and format and chunking behaviour are confirmed from the live guide. What is still unmeasured is real-world accuracy: call the endpoint with the sample voiceover, after telling you, and record accuracy at word level, time taken end to end, and how many words fail to match the script.

**Read first.** Sections 3.2, 3.3, 3.4, 5.1, 5.8 (the connection-error and "unknown job id" rows), 6.4 and 6.5 ("What happens when something changed"). DB Sections 4.3, 4.5, 5 and 7.

**In scope**

- **The dispatcher** (Section 3.3): one loop started with the app. Each tick waits for the poll interval read from settings, or less when a new job nudges it. Per tick it checks running remote jobs, starts finishing steps, resubmits when a handler asks, runs `check()` before starting any submission, and starts queued jobs within the per-type limits. It never does slow work itself, and only task handles live in memory.
- **A handler interface** that fits all four iteration 1 job types, so Phases 6, 9 and 10 add handlers without touching the loop. Each type declares its concurrency limit (`generate_clip` uses the maximum parallel generations, `render_final` the maximum parallel FFmpeg runs) and its restart rule: remote jobs with a provider job id keep being checked, local jobs start again, and **paid LLM jobs never re-run by themselves** (Section 6.2, rule 1).
- At most one active job per type and scene, or per type and project for project-level jobs.
- Job endpoints: list per project and overall, job detail (input, output, error, timestamps), cancel a queued job.
- **The Activity page**: type, project, scene, status, phase, timestamps, elapsed time computed in the browser, error, and a detail view with the input and output JSON.
- **The `Transcriber` adapter** (Section 6.4): upload the voiceover through the shared `POST /v1/uploads`, submit `POST /v1/parakeet/transcribe` with just `{"audio_asset_id": ...}` (no language field to set; Parakeet auto-detects) to the transcription URL (blank means the GPU server URL), poll and download through the shared `GET /v1/jobs/{job_id}` and `.../result`. FFmpeg conversion of the voiceover runs first only if its format is outside Parakeet's accepted list (Section 5.1). New transcriptions wait as "paused: GPU API changed" while `check()` reports a change. A dropped connection never fails the job.
- **Transcript matching** (Section 5.1): normalise, align, interpolate missing words, ignore and count extra words, store `words` and `script_words`, and warn when many words differ.
- On the project page: a Transcribe button, the job's status and phase, the transcript (script words with times, unmatched words marked) and the mismatch warning.
- The waiting-job count in the Phase 4 banner.

**Out of scope.** The `plan_scenes`, `generate_clip` and `render_final` handlers. Live updates.

**Decisions for the planner**

- How a job "not found on this server" is shown (Section 3.3). It must not become `failed` by itself.
- **Gap:** the `transcript` table does not record which voiceover file or script version it came from. Decide how the app tells that a transcript is out of date after either one changes. A simple option is to store the voiceover asset id and a hash of the script (a migration and a DB update).
- The concurrency limit for transcription, and the mismatch warning threshold.
- How jobs interrupted by a restart are marked.

**[VERIFY].** Real-word accuracy on your own recordings and voice — the contract itself is confirmed (Section 5.1), but accuracy is only measured by running it, in Spike 2.

**Provides.** The dispatcher and handler registration; job helpers (create, set phase, finish, fail); the "latest job per scene" query; `Transcriber`; the matching function; UI parts for job status and elapsed time.

**If the GPU server is unreachable when this phase is built.** The planner may still split the phase: 5a builds the dispatcher, the job endpoints and the Activity page, checked with transcription jobs that wait on the unreachable server; 5b adds the real run and matching once it answers again. The endpoint itself is no longer the blocker (Section 5.1) — only the server being up is.

**Acceptance checks**

1. Transcribing the sample succeeds. Every script word has a time, and unmatched words are marked and counted.
2. `docker compose restart backend` during a transcription: the job is picked up and finishes, with at most the one duplicate Section 3.3 allows.
3. With the GPU URL pointing at a dead address, the job waits with a clear phase instead of failing, and finishes once the URL is fixed.
4. With a simulated API change (as in Phase 4), a new transcription waits as "paused: GPU API changed", the banner counts it, and approving releases it.
5. Changing the script after transcribing shows the transcript as out of date.
6. Two quick clicks on Transcribe create one active job.
7. With the page open and idle, the browser's network panel shows no repeated requests.

**Pitfalls.** With 200 or more items, Python's `difflib.SequenceMatcher` treats very common items as junk by default, which hurts matching on long scripts. Pass `autojunk=False` if you use it. Each background task opens its own database session.

### Phase 6: AI scene proposal

**Goal.** Propose scenes: the AI names the cut words, code checks them, converts them to times and enforces the limits, and the rule-based splitter checks the result or replaces the AI when it fails (Section 5.2).

**Needs.** From you: an OK for a few paid calls during planning and checking, and your own cuts for the sample.

**First planning step (Spike 3 in ANALYSIS.md).** On the sample's real transcript, run the numbered-word prompt on `zai-org/GLM-5.3-Flash` two or three times. Record whether a JSON response mode exists; whether hidden reasoning tokens are used and can be turned off; how often the word numbers and checksum words agree; how often code had to split or merge; the tokens and cost per run; and whether the time labels help. Compare with your cuts.

**Read first.** Sections 3.6 (the Cloudflare finding), 3.7 (LLM settings and the key rule), 5.2 (all), 5.8 (the LLM and mismatch rows), 6.2 (the rules for paid calls) and 6.4. DB Sections 4.4, 4.5, 5 and 7.

**In scope**

- **The LLM client** (Section 6.4): OpenAI-compatible; URL and model from settings; the key sent only to Bitdeer; a `max_tokens` cap; at most 2 retries, and only for rate limits and server errors; a JSON response mode if available, defensive parsing otherwise; token usage stored on the job. If you use the `openai` SDK, give it the shared helper's HTTP client and set its retry count to match.
- **The prompt**: numbered words with times, paragraph breaks kept, the rules, and the project's cut instructions.
- **The checks**: word numbers in range and increasing; checksum words matched ignoring case and punctuation; a cut moved to a nearby match for an off-by-one, and flagged otherwise.
- **Timing**: each cut at the middle of the silence between two words, the first scene from 0.0, and the last to the end of the audio.
- **The rule-based splitter** (Section 5.2): it enforces the limits on the AI's result, and proposes the cuts alone when the AI fails twice. The page says when that happened.
- **The cache**: the same inputs show the stored answer without a call, and Run again makes a new call.
- The `plan_scenes` job handler.
- A shared function that turns a list of cuts into `scene` rows (times, text, `cut_source`, `cut_note`), which Phase 7 reuses.
- UI: Propose scenes and Run again, marked as calls to the LLM; the job status; a notice when the splitter was used; the mismatch gate ("the recording differs from the script", with a way to continue); and the scene list with text, time range, duration (red outside the limits), cut source, flags and a button to play the scene.

**Out of scope.** Editing cuts (Phase 7). Splitting long scripts for small context windows (Section 5.2 says 1-minute scripts do not need it; refuse clearly above a size limit).

**Decisions for the planner**

- **Gap:** DATABASE_STRUCTURE.md has no column for the cache key. Choose between an `input_hash` column on `job` (a migration) and a hash stored inside `job.input`.
- What Propose does when scenes exist. Recommended: replace them freely while no scene has inputs; otherwise ask, and on confirmation discard all scenes (their files stay on disk).
- Once scenes exist, whether the voiceover and script lock, or changing them asks before discarding the scenes.
- The prompt details after the spike, the output cap, the search window for checksum words, and what counts as a very long silence.

**[VERIFY].** JSON response mode and reasoning control on Bitdeer (Section 6.2, rule 4). Whether calls from inside the container pass Cloudflare (Section 3.6).

**Provides.** The LLM client, `ScenePlanner`, the splitter, and the cuts-to-scenes function.

**Acceptance checks**

1. Propose on the sample: the scenes cover the audio from 0.0 to the end with no gaps or overlaps, each is within 2 to 6 s or flagged, and token usage is on the job.
2. A second click with the same inputs makes no paid call, and Run again makes one.
3. With the LLM URL pointing at a dead address, the job tries once more, then the splitter's proposal appears with a notice.
4. Changing the maximum to 4 s affects the next proposal only. Existing scenes are not re-cut.
5. Play plays exactly that scene's time range.

### Phase 7: Cut review and editing

**Goal.** The human checkpoint: move, add and remove cuts by clicking the gaps between words, with live length warnings and safe handling of scenes that already have inputs (Section 5.2, "Review step in the UI").

**Read first.** Sections 1 ("The key observation") and 5.2. DB Sections 4.4 and 7.

**In scope**

- A word view of the script with clickable gaps: add a cut, remove a cut, move a cut.
- Backend endpoints for cut edits that rebuild only the affected scenes with Phase 6's function. Edited cuts get `cut_source = manual` and are timed at the middle of the chosen gap.
- Durations and limit warnings update right away.
- **The inputs rule**: edits are free while the affected scenes have no inputs. When a scene beside the cut has a description, a frame or a clip, the edit asks first, and on confirmation clears only those scenes' inputs. Files stay on disk.

**Out of scope.** Editing scene text (it comes from the script). Undo.

**Decisions for the planner.** Exactly what "discard inputs" clears. Whether a scene keeps its id when its range changes. Whether a scene over the maximum only warns here (Phase 9 refuses clips longer than the API allows).

**Acceptance checks**

1. Adding a cut inside a long scene makes two scenes with updated durations and a manual cut.
2. Removing a cut merges two scenes, and a merged scene over the maximum shows red.
3. Moving a cut by one word changes only the two scenes beside it.
4. With a description set on a scene (directly in the database, until Phase 8 adds the UI), editing its cut asks first. Cancel changes nothing, and confirm clears only those two scenes.
5. Scene numbers stay 0 to n-1, without gaps, after many edits.

**Pitfalls.** With `UNIQUE (project_id, index)` (DB Section 4.4), shifting several scene numbers in one SQLite statement can collide row by row. Renumber in two steps, for example through temporary negative numbers.

### Phase 8: Scene inputs

**Goal.** For each scene: paste a description, upload or paste the first and last frame, see exactly the framing that will be sent, see the final prompt with hints, and see whether the scene is ready.

**Needs.** From you: frames for the sample's scenes (one pair may be reused across scenes for checks).

**Read first.** Sections 4.2, 5.3 (the image facts), 5.4, 5.7 and 5.9 (frame mismatch, prompts, uploads). DB Sections 4.2, 4.4 and 7. The Spike 1 report, if it exists.

**In scope**

- A scene editor: the description (`scene_description_source = manual`), and the first and last frame by file picker, drag and drop, or pasting from the clipboard.
- Image checks with Pillow: a real image, allowed formats, a pixel limit. Frames are stored as `asset` rows with `kind = frame` and `source = upload`.
- **Frame normalisation** (Section 5.3): RGB, centre-crop to the generation aspect ratio, resize to the generation size, with a preview of the result.
- **Prompt assembly** (Section 5.4): `Style: <style_prefix>.` + description + `<prompt_suffix>`, previewed per scene, with hints for word count, double quotes, "cut to", timestamps and "the video starts with".
- Readiness, computed: a description and both frames. The project page shows "n of m scenes ready" and can list the scenes that are not.

**Out of scope.** AI drafting. Reusing a frame across scenes, and chaining. Generation.

**Decisions for the planner**

- When normalisation runs. The constraints: the frames sent must match the project's generation size **at submission time** (it can change after upload), and Phase 9 must keep the exact file it sent, for reproducibility.
- Whether a large aspect mismatch between the upload and the generation size gets a warning.
- Defaults from the Spike 1 report, such as a negative prompt placeholder.

**Provides.** The normalisation, prompt assembly and readiness functions, all reused by Phase 9.

**Acceptance checks**

1. PNG, JPEG and WebP frames, including a grayscale or palette PNG, preview correctly cropped at the generation size and in RGB.
2. Pasting an image from the clipboard sets the frame.
3. The prompt preview follows the formula, and quotes or "cut to" trigger hints.
4. Readiness changes only when the description and both frames exist, and the counts follow.
5. A non-image, or an image above the pixel limit, is rejected.
6. Editing the cut of a scene that has inputs asks before discarding them (Phase 7's rule, now through the UI).

### Phase 9: Clip generation

**Goal.** Generate one LTX clip per ready scene, several at a time, surviving restarts, outages, pre-emption and API changes. Preview clips with their sound, regenerate, choose takes and switch each scene's clip sound.

**Needs.** The Spike 1 report, the GPU server running with its API approved, and ready scenes.

**Read first.** Sections 3.3 (all), 3.4, 5.3, 5.4, 5.5, 5.6 (clip sound), 5.8 (all), 6.1, 6.4 and 6.5. DB Sections 4.4, 4.5, 5 (the `generate_clip` input) and 7. The Spike 1 report.

**In scope**

- **The `VideoGenerator` adapter** (Section 6.4): submit (upload the frames, then submit), status, download, cancel and cleanup, following the live guide and the shapes in the spike report. Request fields as in Sections 5.3 and 5.4, including `enhance_prompt` off.
- **Frame counts**: a function that turns scene boundaries into frame counts on the project's fps grid (Section 5.5), and `num_frames` as the smallest 8k + 1 at or above the target (Section 5.3). Checked against the limits in the recorded OpenAPI spec, with sizes checked as multiples of 64.
- **The `generate_clip` handler**, with the phases from Section 3.4. It saves the provider job id right after submitting, checks each tick, downloads, verifies with ffprobe (video present, at least the target frame count, audio noted), stores the clip as an `asset` (`source = ai`, provenance with endpoint, prompt, seed and frame count), makes it the selected take (DB Section 7), and purges on the server, ignoring failures.
- **Every row of the failure table** in Section 5.8, including automatic resubmission after pre-emption (up to 3 attempts), "not found on this server" with a Resubmit action, and cancelling on the server.
- The parallel limit read each tick, the partition setting, at most one active generation per scene, a new random seed per attempt, and the exact request, with the server URL, stored on the job.
- UI per scene: Generate, Regenerate and Cancel; status and phase; elapsed versus typical time; error text; the takes, each with a video player with sound; Select take; the clip sound switch. A "Generate all ready scenes" button.

**Out of scope.** The render. The `retake` and `audio-to-video` endpoints. Automatic speech detection in clip sound.

**Decisions for the planner.** The endpoint: keyframe interpolation (Section 5.3) unless the spike says otherwise. Whether a resubmission reuses the job row with `attempt + 1` or creates a new row. Whether "Generate all" shows the count first. Where the frame files actually sent are kept (see Phase 8).

**[VERIFY].** Anything the spike left open. Whether the maximum frame count is in the spec (Section 3.7, "Validation").

**Provides.** `VideoGenerator`, and the frame count function, which Phase 10 must reuse.

**Acceptance checks**

1. One scene: the clip arrives with at least the target frame count and its sound, the job shows the exact request, and the uploads on the server are purged.
2. Four ready scenes with the limit at 2: never more than 2 run at once, and the next starts when a slot frees up, without any page refresh (check the job timestamps).
3. Changing the limit while jobs run applies at the next tick and leaves running jobs alone.
4. Restarting the backend mid-generation: the jobs continue and finish.
5. A dead GPU URL mid-run: no job fails, and restoring the URL lets them finish.
6. A simulated API change pauses new submissions while running jobs finish.
7. Regenerate gives a new take with a new seed. Selecting an older take, and the clip sound switch, both persist.
8. Cancelling a queued and a running job marks both cancelled, and the running one is cancelled on the server.
9. A double click on Generate creates one active job.

**Pitfalls.** Save the provider job id before anything else that can fail. Download to a temporary file and move it into place only after ffprobe passes.

### Phase 10: Final render

**Goal.** Trim, join and mix the clips and the voiceover into the final MP4, then preview and download it (Section 5.6).

**Needs.** A selected clip for every scene.

**Read first.** Sections 3.2 (FFmpeg as a child process), 5.5, 5.6 (all) and 8 ("Render from a timeline description"). DB Sections 4.2, 4.5 and 7. The audio facts in the Spike 1 report.

**In scope**

- **A timeline description**: the ordered list of (clip, frame count from Phase 9's function, clip sound on or off), plus the voiceover and the clip sound volume, stored on the job.
- **Stage 1, per clip**: trim to the exact frame count, crop or scale to the output size, constant fps, high-quality intermediate video; sound trimmed to the same length, 48 kHz stereo uncompressed, with short fades at both ends. A muted scene, or a clip without sound, gets silence of the same length.
- **Stage 2**: join in order, lower the clip sound to the project volume, mix it under the voiceover at full level, and encode the final H.264 and AAC file with `+faststart`, ending with the audio.
- The `render_final` handler: limited by the maximum parallel FFmpeg runs, low priority, phases such as "trimming clip 3 of 12", temporary files removed, started from scratch after a restart.
- UI: Render (disabled, with the reason, while a scene has no clip or its clip is shorter than the scene now needs), status, player, download, and earlier renders.

**Out of scope.** Ducking, music, subtitles, cached trims, a timeline editor (Section 8).

**Decisions for the planner.** The intermediate formats and quality settings. The mixing method for the FFmpeg version in the image.

**[VERIFY].** How FFmpeg's mixing changes input levels in the image's version (Section 5.6). The real sample rate and channel layout of LTX's sound (spike report).

**Acceptance checks**

1. The final video lasts as long as the voiceover, within one frame, at the output size and a constant fps.
2. Each cut falls on its scene boundary when you scrub to it.
3. The voiceover is at full level. The clip sound is quiet at 20 percent and absent at 0. A muted scene is silent only for its own length. There are no clicks at the cuts.
4. The video plays and seeks in the browser, and downloads.
5. Re-rendering after a volume change creates a new final asset, and the earlier one remains.

**Pitfalls.** MP4 is a poor container for uncompressed PCM audio, so use MKV or MOV for the intermediates.

### Phase 11: Hardening and end-to-end runs

**Goal.** Make iteration 1 dependable for real use (Section 7, M6). No new features.

**Needs.** From you: two real 1-minute projects with frames, and time to run them.

**In scope**

- Every failure you can meet shows a plain message: what happened and what to do next.
- Logs carry job and scene ids, and never a secret.
- Recovery drills: kill the backend during a generation and during a render; take the tunnel down; point the GPU URL at a different server ("not found on this server"); change the API mid-run; let the Mac sleep during a run.
- Two end-to-end runs with real 1-minute projects. Small problems found are fixed; anything bigger becomes a new phase.
- README additions: backing up the `data` volume, keeping the Mac awake for long runs, Docker Desktop's disk limit, and where the logs are.

**Acceptance checks**

1. Every drill behaves as Sections 3.3 and 5.8 describe.
2. Two complete 1-minute videos are produced end to end, with no hand edits to the database.

---

## 6. Coverage check

Everything ANALYSIS.md puts in iteration 1, and the phase that builds it.

| ANALYSIS.md item | Phase |
|---|---|
| Containers, volume, SQLite and migrations, `.gitignore` (3.1, 3.5, 3.6, 4.1) | 1 |
| Localhost-only safeguards (3.7 rules, 5.9) | 1, 2 |
| Global settings and Test connection (3.7) | 2, 4 |
| Project settings, guidelines, orientation defaults (3.7, 4.4, 5.4) | 3 |
| Voiceover, script, media serving (1, 3.5) | 3 |
| Recording and checking the GPU API, banners (3.4, 6.5) | 4, 5 |
| Dispatcher, job table, resume after restart (3.2, 3.3) | 5 |
| Activity view (4.2, 8) | 5 |
| Transcription and matching (5.1) | 5 |
| AI cut proposal, splitter, fallback, cache, paid-call rules (5.2, 6.2) | 6 |
| Reviewing and editing cuts (5.2) | 7 |
| Descriptions, frames, normalisation, prompt preview, readiness (4.2, 5.3, 5.4) | 8 |
| LTX generation, failure handling, takes, clip sound switch (5.3, 5.5, 5.8, 6.1) | 9 |
| Render and mix (5.5, 5.6) | 10 |
| Hardening (7, M6) | 11 |
| The three spikes (7, Step 0) | Spike 1, Phase 5 planning, Phase 6 planning |

Not in iteration 1: everything on the "not build" list in Section 8 (authentication, characters, AI drafting of descriptions and frames, timeline editing, music, subtitles, multi-user features, live updates in the browser, automatic ducking, cost gating for the GPU API). Added here: deleting projects or files, mock servers, and automated tests unless you ask for them.

---

## 7. Phase log

The executor adds an entry when a phase is finished, and every planner reads all entries. Keep them short and factual.

```text
### Phase <N>: <name> (done <date>)
Plan: plans/phase-<NN>-<short-name>.md
Built: <one or two lines>
Deviations from ANALYSIS.md or DATABASE_STRUCTURE.md: <none, or each with its reason and your approval>
Decisions later phases must follow: <list>
[VERIFY] results: <item: finding>
Known issues and leftovers: <list>
```

```text
### Phase 1: Foundation (done 2026-10-05)
Plan: plans/phase-01-foundation.md
Built: Two-container app (nginx + FastAPI/SQLite on a named volume) that starts with
`docker compose up --build -d`. All seven tables from DB Section 4 in one Alembic
migration, with WAL, foreign_keys and a 5s busy timeout on every connection. Host and
Origin security baseline, no CORS, JSON-only bodies. A Mantine + TanStack Query +
openapi-fetch frontend shell with placeholder Projects/Activity/Settings pages and a
Refresh button backed by GET /api/health. Backend image's FFmpeg and ffprobe:
7.1.5-0+deb13u1 (python:3.13-slim, Debian trixie).
Approved decisions: the constraint naming convention (pk_/fk_/uq_/ck_/ix_) was added;
DB Section 4's 8 idx_* names are unchanged. The Host check applies to /api only (nginx
serves the static bundle and /media/ for any Host). The /api/ upload limit is 512 MB.
The Compose project name is pinned to visio-studio. The published port is
127.0.0.1:${APP_PORT:-5480}:80.
Deviations from ANALYSIS.md or DATABASE_STRUCTURE.md: none. Note: the Phase 1 plan's
own prose said 10 CHECK constraints; DATABASE_STRUCTURE.md Section 4's literal DDL has
9 (orientation, kind, source, cut_source, scene_description_source, type, status,
provider, state). Built to the 9 in DATABASE_STRUCTURE.md, confirmed with
`alembic check` and a full sqlite_master dump; treated as a miscount in the plan's
prose, not a deviation from DATABASE_STRUCTURE.md.
Decisions later phases must follow:
- Routers: one app/api/<area>.py per area with its own `router`, included in
  `api_router`. Pydantic models live in that module, or app/api/schemas/ when large.
  Responses never return ORM objects. Dependencies use the Annotated[..., Depends(...)]
  form.
- Sessions: requests use SessionDep. Background tasks open their own
  `async with SessionLocal() as session`. Keep transactions short, and never rely on
  lazy loading (no ORM relationship() yet; a later phase that adds one uses
  lazy="raise").
- Times and JSON: times use UTCDateTime and utcnow(), and the API returns
  timezone-aware UTC. To change a JSON column, assign a new object. Nullable JSON
  columns use none_as_null=True.
- Migrations: change the models, then on the Mac set DATA_DIR=$(mktemp -d), run
  `uv run alembic upgrade head`, then `uv run alembic revision --autogenerate --rev-id
  000N -m "..."`. Review the result (ALTERs use batch operations, constraints are
  named), and update DATABASE_STRUCTURE.md in the same phase. The backend applies new
  migrations at start.
- Security: never add CORS middleware or strict_content_type=False, and keep
  TrustedHostMiddleware outermost, then OriginCheckMiddleware.
- Uploads: nginx allows 512 MB on /api/, and app-level limits stay at or below it.
- Frontend: all server data goes through TanStack Query and the `api` client, and
  refetchInterval is never set. Run `npm run gen:api` after every API change and commit
  schema.d.ts. TypeScript stays on ~5.9.3 until openapi-typescript and typescript-eslint
  support 6.x.
[VERIFY] results:
- Host and Origin checks through the nginx proxy: pass. Host: evil.example -> 400;
  cross-origin POST -> 403; same-origin POST -> 405 (reaches the router, both checks
  passed); Host: localhost:5480 GET -> 200.
- WAL and foreign keys, read through the app's own engine, not a separate sqlite3
  session: pass. journal_mode=wal, foreign_keys=1, busy_timeout=5000.
- arm64: pass. `docker image inspect` reports linux/arm64 for both
  visio-studio-backend and visio-studio-frontend.
Known issues and leftovers:
- Acceptance check 12 (no polling) was verified by code review, not a live browser
  network panel: no refetchInterval anywhere in the app, exactly one query ("health"),
  Refresh calls queryClient.invalidateQueries(), and refetchOnWindowFocus: true is the
  only other trigger. The built JS bundle was confirmed to contain the expected strings.
  No interactive browser was available in this environment to watch the network panel
  directly; worth a manual spot-check.
- `docker compose up --build -d` sometimes recreates a container whose own layers were
  all cache hits, because Buildx's attestation and provenance metadata changes the
  image digest even when the content does not change. Cosmetic only; the data volume
  is untouched (confirmed in acceptance check 6: same inode, same revision, no re-run
  migration).
- No other known issues. All 7 tables, 10 foreign keys, 9 CHECK constraints and 8 named
  indexes were confirmed against DB Section 4 with a full sqlite_master dump and
  PRAGMA foreign_key_list. Not committed; per the plan, you review and commit.
```

```text
### Phase 2: Global settings and GPU connection test (done 2026-10-06)
Plan: plans/phase-02-settings.md
Built: A settings registry for the 8 global settings of DB Section 6 (all except
api_contract_sources), with saved > environment > built-in precedence read at the moment of
use, GET /api/settings, PUT and DELETE (Reset) /api/settings/{key}, and a Settings page
with Save and Reset per setting, "Will call: ..." for URLs and "Key set: yes or no". The
shared outbound HTTP helper (app/core/outbound.py). A Test connection button for the GPU
server (POST /api/gpu/connection/test, GET /api/gpu/connection) whose last result is kept
in the database. No migration, no new table, no new npm package. New backend dependency:
httpx 0.28.1.
Approved decisions: the last test result is one internal row in `setting`
(key gpu_connection_last_test); Reset is included; numeric ranges are
max_parallel_generations 1 to 16, poll_interval_seconds 10 to 300, max_parallel_ffmpeg 1 to
4; redirects are never followed, not even to the same host.
Deviations from ANALYSIS.md or DATABASE_STRUCTURE.md: none. DATABASE_STRUCTURE.md Section 6
got a note about internal rows (no schema change).
Decisions later phases must follow:
- Read a setting with `get_str` or `get_int` (app/core/settings.py) at the moment of use.
  For transcription_url, `get_str` returns the GPU server URL when it is blank. Stored URLs
  are never Docker-mapped; mapping happens inside `outbound.request`.
- All outbound HTTP goes through `outbound.request()`. Never create another httpx client.
  It returns non-2xx answers and raises `OutboundError` (reason url, connection, timeout,
  redirect or too_large) when there is no usable answer. It takes no caller headers, so
  only the helper can set Authorization. Phase 5 adds uploads and Phase 9 adds
  `download_to_file` to this module and reuses its checks.
- Call exact paths: the GPU server answers a trailing-slash path with a 307, which the
  helper refuses.
- A new internal row in `setting` must be added to `INTERNAL_KEYS`. The settings API
  answers 404 for those keys.
- GPU reachability is read and written only through app/services/gpu_status.py. The stored
  result counts only while its `called_url` equals the address that would be called now.
- Our own errors are `{"detail": "<readable message>"}`. FastAPI's request validation 422
  uses a list instead, so the frontend's `detailMessage` shows `detail` only when it is a
  string.
- On zsh, never use `path` as a loop variable in a command: it is tied to PATH.
[VERIFY] results:
- Health path and response: `GET /v1/health` returns 200 in about 0.4 s with
  {"status":"ok","default_partition":"background","job_retention_days":7.0}. "Reachable"
  means HTTP 200 and a JSON object whose status is "ok".
- Reaching it from the container: pass, through `host.docker.internal:8012`, both with a
  plain urllib call and through `outbound.request`.
- Cloudflare (Section 3.6), partly re-confirmed for Phase 6: from inside the container,
  `GET https://api-inference.bitdeer.ai/v1/models` with User-Agent VisionPsyStudio/0.1 and
  the key returned 200 with 8 models. Without the key and with Python's default
  User-Agent, Cloudflare returned 1010. A chat completion call was not made.
Known issues and leftovers:
- Clicks on Save, Reset, Test connection and Refresh were not exercised in an interactive
  browser (none was available). Checked instead: headless Chrome rendered the Settings page
  with all 8 settings, badges, "Will call" lines, the stored connection result and
  "Key set: yes"; the same operations were run against the API with curl.
- Acceptance check 7: a headless load with 60 s of virtual time made exactly one request
  each to /api/health, /api/settings and /api/gpu/connection, and the backend logged no
  outbound call. Other open tabs (Cursor's browser, Chrome) refetched on window focus at
  irregular times, which is the designed refetchOnWindowFocus behaviour.
- The PUT operation documents 422 as ErrorResponse, but FastAPI's own request validation
  (for example 4.5 for an integer setting) returns a list. The UI cannot send such a value.
- Save is disabled while the draft equals the current value, so a value cannot be saved as
  "pinned" without changing it first.
- The JS bundle is now 504 kB, so Vite warns about chunks over 500 kB. Harmless.
- Phase 1 was still uncommitted when Phase 2 started, so both phases' changes sit together
  in the working tree (main has no commits). Not committed; you review and commit.
- The row gpu_connection_last_test remains in the database from the checks. It is a real
  reachable result for the current address, and all 8 settings are back to built-in.
```

```text
### Phase 3: Projects, voiceover and script (done 2026-10-06)
Plan: plans/phase-03-projects.md
Built: Create a project (orientation first, Section 4.4 defaults), edit its settings and
guidelines, upload a voiceover, paste the script, play the audio with seeking. Backend:
`Storage`, the FFmpeg and ffprobe wrapper (`run_tool`, `probe`), `add_asset`, project
validation and the endpoints GET and POST /api/projects, GET and PATCH
/api/projects/{id}, POST /api/projects/{id}/voiceover. Frontend: project list with a create
modal, project page (voiceover player, script editor), project settings page. No
migration, no new dependency, DATABASE_STRUCTURE.md unchanged.
Approved decisions: orientation is fixed after creation (the sizes stay editable but must
keep its shape); voiceover limit 400 MB; accepted formats WAV, MP3, M4A and FLAC, decided
by ffprobe from the file's content; value ranges as in the plan (generation sizes 256 to
3840 in steps of 64, output sizes 256 to 3840 and even, fps 12 to 60, scene length 0.5 to
20 s, volume 0 to 1, guidelines up to 2,000 characters, script up to 100,000).
Deviations from ANALYSIS.md or DATABASE_STRUCTURE.md: none.
Decisions later phases must follow:
- Files only through `get_storage()` (app/services/storage.py). A file is received into
  /data/tmp (created with "xb", never mkstemp, so nginx can read the result), checked, then
  moved with `save` to /data/media/<project_id>/<32 hex>.<ext>. `asset.path` holds that
  relative path and the URL is "/media/" + path. /data/tmp is emptied at backend start.
- Every new stored file extension must be added to the `types` block of `location /media/`
  in frontend/nginx.conf. A `types` block replaces the stock map, which has no wav or flac.
- FFmpeg and ffprobe only through `run_tool` and `probe` (app/services/ffmpeg.py). Inputs go
  through `file_input()`, and every run is under `nice -n 10` with a time limit.
- Uploads send the file as the raw request body with Content-Type application/octet-stream
  (415 otherwise), read with `request.stream()`. No multipart and no python-multipart.
  Phase 8's frame upload should do the same, or ask before adding a dependency.
- `add_asset` flushes but does not commit. The caller commits with the rest of its change.
- Project rules live in `validate_project` (app/services/projects.py). Every project edit,
  including the script, is PATCH /api/projects/{id} through `update_project`, which rolls
  back and raises ProjectValidationError on a broken rule. The script is stored exactly as
  sent (only an all-whitespace script becomes NULL), guidelines are trimmed and blank is NULL.
- A new voiceover creates a new asset and repoints the project. The old file and row stay.
- Frontend form pattern: the mutation hook lives in the page, and the draft lives in an inner
  component keyed by the saved values (ScriptEditor, ProjectSettingsForm). Pure draft logic
  goes in its own module (settingsDraft.ts) because ESLint wants component files to export
  only components.
- The GPU API spec declares no maximum for width, height, fps or frame count (only "must be
  a multiple of 64" in text, num_frames at least 9). Phase 9's maximum-frame-count [VERIFY]
  therefore ends as "not in the spec"; Phase 3 uses fixed sanity ranges.
[VERIFY] results:
- Range through nginx: pass. A Range request for a stored voiceover returns 206 with
  Content-Range for WAV, MP3, M4A and FLAC, with Content-Type audio/wav, audio/mpeg,
  audio/mp4 and audio/flac. In headless Chrome, seeking to 2.5 s worked and the /media
  requests answered 206. The stock nginx mime.types has no wav or flac, hence the types block.
Known issues and leftovers:
- No sample voiceover or script was available, so the checks used generated 5 s tones (WAV,
  MP3, M4A, FLAC, AIFF), a video, a text file renamed .mp3, an empty file and a 401 MB
  file. Please upload your real sample on a project page and confirm that it plays, seeks
  and shows the right length.
- Test projects 1 to 4 and their media files remain in the data volume. Deleting is not
  built and needs your confirmation. Project 2 has an extra WAV from a same-origin check.
- Added beyond the plan: the upload endpoint requires Content-Type application/octet-stream
  (415 otherwise), as defence in depth next to the Origin check. The frontend always sends
  it (the plan said file.type or octet-stream) and refuses files over 400 MB before sending.
- An oversized upload gets its 413 only after nginx has buffered the whole body (about 3 s
  for 401 MB on this Mac), because nginx adds Content-Length and request buffering is on. The
  limit inside Storage.receive, which counts bytes while receiving, is unreachable through
  nginx, so it was checked directly in the container.
- The generated MP3 reported 5.04 s in the container (ffprobe 7.1.5) and 5.00 s on the Mac
  (ffprobe 8.0): encoder padding, inside the 0.1 s tolerance. Real VBR files may differ a bit.
- Storage imports anyio directly (it ships with Starlette, as the plan said) but it is not
  listed in pyproject.toml.
- If the database write fails after a file is stored, the file stays unreferenced (stored
  files are never deleted) and a warning is logged.
- PATCH bodies with a wrong JSON type (for example fps 24.5 or "6") get FastAPI's own list
  in `detail`, not a readable string. The UI cannot send them.
- A browser textarea reports line breaks as \n, so a script pasted with \r\n through the UI
  is stored with \n. Through the API it is stored exactly as sent.
- The settings page shows clip sound in whole percent. A volume set through the API that is
  not a whole percent shows rounded, and saving without touching it does not change it.
- The UI was checked with a throwaway headless Chrome script (DevTools protocol, kept in
  /tmp, not in the repo): 28 checks passed, including no API requests during 60 s idle.
  The JS bundle is still over 500 kB, so Vite still warns. Harmless.
- Phases 1 and 2 are committed (b94d86c). Phase 3 is not committed; you review and commit.
```
