# Performance and Pipeline Board: analysis and plan

Date: 2026-10-27
Status: analysis only. No application code was changed.

This document answers three questions:

1. **Why does the app feel slow to open and use** (not how long generation takes)?
2. **Why is it hard to see what is done, what is running and what is next?**
3. **What should we change, and in what order?**

It is based on reading the code and on measurements taken against the running app (project 35 in the live database, 22 shots, about 79 jobs queued or running at the time). Anything that is measured is marked **Measured**. Anything that is reasoning only is marked **Not measured**.

---

## 1. Summary

The slowness has **two causes that multiply each other**, and neither is about media files first.

| # | Cause | Where | Evidence |
|---|-------|-------|----------|
| A | The project page mounts about 40 panels at once. Each one fetches its own data and polls on its own. | Frontend (`ProjectPage.tsx`) | **Measured**: 39 API calls on open |
| B | The backend recomputes the whole upstream chain of every stage on every read. Nothing is cached. | Backend (`services/*.state()`) | **Measured**: one `/staleness` call runs `character_relations.state()` **306 times** |
| C | While any job is active, the page re-asks the heaviest endpoints every 3 seconds. | Frontend polling + A + B | **Measured**: 63 queued and 16 running jobs right now |
| D | Media is loaded full size (no thumbnails) and one `<video>` is created per shot. | Frontend + storage | **Measured** sizes; contention **not measured** |

A and B together are the main problem. A sends 39 requests. B makes each request expensive. C keeps repeating it. D adds weight on top.

**The most effective order** (details in section 7):

1. Backend: stop recomputing the same state many times per request (request-scoped memoization).
2. Frontend: mount panels only when opened, add `staleTime`, stop polling the heavy endpoints.
3. Backend: one cheap "pipeline board" endpoint and one cheap "activity revision" endpoint.
4. Frontend: the new Pipeline Board page (all steps at once, details loaded on click).
5. Media: thumbnails, video posters, `preload="none"`, nginx gzip and caching.
6. Later: cross-request cache, storyboard strip, push updates, smaller payloads.

Steps 1 and 2 are small, independent, and remove most of the pain. The board (3 and 4) should come after step 1, otherwise the board itself would cost 3 to 4 seconds per refresh.

---

## 2. What was measured

### 2.1 Opening one project page (project 35)

Every endpoint the page calls, timed one at a time (the app was also busy with jobs, so the numbers are noisy but the shape is stable).

| Endpoint | Time | Size |
|----------|------|------|
| `/staleness` | 3,568 ms | 33 KB |
| `/story-renders` | 3,383 ms | 6 KB |
| `/story-pipeline` | 1,598 ms | 7 KB |
| `/shot-prompts` | 470 ms | 218 KB |
| `/generation-requests` | 446 ms | 38 KB |
| `/shot-takes` | 431 ms | 70 KB |
| `/shot-definitions` | 342 ms | 79 KB |
| `/shot-references` | 307 ms | **361 KB** |
| `/shot-continuity` | 233 ms | 1 KB |
| 30 other endpoints | 3 to 150 ms each | small |
| **Total, one at a time** | **11.9 s** | **915 KB** |

Notes:

- `/story-renders` returns 6 KB but takes 3.4 s. The cost is the recomputation behind it, not the data.
- Light stages (scenes, characters, music bible) are fast. The slow ones are the stages that sit **late** in the pipeline, because they rebuild everything before them.

### 2.2 Sending them in parallel makes it worse

A real browser fires these together. Simulating that with 6 connections at a time (the browser limit per host):

| Mode | Wall time |
|------|-----------|
| One at a time | 11.9 s |
| 6 at a time | **34.2 s** |
| All 39 at once | 14.0 s |

The backend is one Python process on one event loop (`uvicorn --workers 1`). Work is CPU-bound, so parallel requests do not run in parallel. They interleave and fight for the same loop and the same SQLite file. Parallel was slower than serial.

### 2.3 The same project varies a lot with load

`/staleness` for project 35 took 3.5 s in one run and **27 s** in another. The difference is background activity: while jobs run, the dispatcher and the polling both compete for the same loop.

Across projects (single request each):

| Project | `/staleness` | `/story-pipeline` | `/shot-takes` |
|---------|--------------|-------------------|---------------|
| 18 | 0.8 s | 0.4 s | 0.1 s |
| 23 | 1.2 s | 0.3 s | 0.2 s |
| 39 | 2.0 s | 1.0 s | 0.3 s |
| 34 | 6.7 s | 3.1 s | 0.9 s |
| 37 | 6.9 s | 2.1 s | 0.4 s |
| 36 | 10.4 s | 0.0 s | 1.3 s |
| 35 | **27.0 s** | 3.9 s | 0.5 s |

The cost grows with project size, so the app gets slower exactly as projects become real.

### 2.4 Why: the same state is computed again and again

Each stage has a `state()` function that is "worked out on every read; nothing here is stored" (this is in the code comments). A stage calls the `state()` of every stage before it. A stage that sits late in the pipeline therefore rebuilds almost everything.

I wrapped every `state()` with a counter and called the same code the API calls (read-only, nothing written):

| Request | Total time | `state()` calls | Worst repeat |
|---------|-----------|-----------------|--------------|
| `GET /staleness` | 3.1 s | **1,224** | `character_relations` 306x, `character_definitions` 303x, `environment_definitions` 228x, `scene_definitions` 147x |
| `GET /shot-takes` | 0.36 s | 146 | `character_definitions` 36x, `character_relations` 36x |
| Evaluate every pipeline step (what a run does) | 3.5 s | **1,315** | same pattern |

So about 25 real stage computations are done roughly 1,200 times. This is the single biggest backend cost.

The dependency chain that causes it (from the key and call structure):

```
shot_takes -> shot_prompts -> generation_requests -> shot_references -> shot_definitions
                                                  \-> shot_plans -> speech_synthesis, scene_definitions, scene_staging
shot_definitions -> shot_plans, look_state_resolution, scene_definitions, speech_units, scene_staging, environment_views
story_renders -> shot_plans + shot_takes + speech_synthesis (and again, three times in the file)
staleness -> about 20 different state() calls, each with its own chain
```

There are 167 `state(session, project)` call sites in the services and no cache anywhere (`lru_cache` is only used for config and storage).

---

## 3. Root causes in detail

### 3.1 The project page mounts everything (Frontend)

`pages/ProjectPage.tsx` renders about 40 panels in one long column. Every panel runs its own `useQuery`, so opening one project fires 39 requests, immediately, even for panels far below the screen that the user may never open.

Related findings:

- **No default `staleTime`** (`queryClient.ts`) and `refetchOnWindowFocus: true`. Switching browser tabs and coming back refetches all 39 queries again, each with the cost in section 2.
- **Cascading query keys.** The keys are nested on purpose so that one invalidation refreshes downstream data: `shotDefinitions -> shotReferences -> generationRequests -> shotPrompts -> shotTakes -> storyRenders`. Invalidating `shotDefinitions` refetches six queries, and `shotContinuity` as well. With every panel mounted, every one of them is "active" and refetches immediately.
- **Run signature change invalidates all project queries** (`api/storyPipeline.ts`). Each time a pipeline run changes state, every panel refetches at once.
- **All pages are bundled eagerly** (`router.tsx`, no `lazy()`): one 1.27 MB JS file and one 248 KB CSS file, served without compression. This is a smaller issue on localhost.

### 3.2 Polling every 3 seconds while anything runs (Frontend + Backend)

About 50 hooks have `refetchInterval`. Most are cheap when idle. The problem is what happens while a job is active:

- `useStaleness` polls every 3 s whenever **any job of the project** is active (`api/staleness.ts`). That is the most expensive endpoint (3.5 to 27 s). The poll interval is shorter than the request time, so it is effectively **continuously recomputing**.
- `shotDefinitions`, `shotReferences`, `generationRequests`, `shotPlans`, `shotTakes`, `storyPipeline` and others poll at 3 s as soon as one of their jobs is active, and several keep polling for a grace period afterwards.
- `useJobs` loads up to 200 jobs each time (72 KB).
- Every mounted panel can start its own polling, because every panel is mounted.

While a generation run is going, which is exactly when you are watching the screen, the page is at its slowest.

### 3.3 Backend runs everything on one event loop

- One uvicorn worker. The job dispatcher also lives in the same process and loop (`main.py` lifespan).
- The state computation is CPU-bound Python. While it runs, **nothing else in the backend runs**: other API calls and the dispatcher tick wait.
- The pipeline run polls at each dispatcher tick and evaluates steps (`story_pipeline_targets.py`). Evaluating every step costs about 3.5 s of loop time on project 35. **Not verified** that a run does this every tick; it should be checked when step 1 is done.
- Adding more uvicorn workers is **not** a safe fix: each worker would start its own dispatcher and could start duplicate jobs.

### 3.4 Media weight (Frontend + storage)

**Measured** on the data volume: 8 GB of media; 1,334 PNG files averaging 2.8 MB (1,233 of them over 1 MB); 782 MP4 files averaging 3.8 MB.

- **No thumbnails exist.** There is no thumbnail or poster code in the repo. Where a small picture is shown (look/state images, environment views, generation request pictures), the browser downloads the full PNG and scales it down.
- Images use `loading="lazy"`, which helps. But on one very long page, lazy loading only protects what is off screen.
- `ShotTakesPanel` renders one `<video preload="metadata">` per shot with a selected clip (22 on project 35). Browsers fetch part of each file to read its metadata. `StoryRenderPanel` does the same for renders.
- nginx serves `/api` and `/media` over HTTP/1.1 on one host. Browsers allow about 6 connections per host, so video and image requests can queue ahead of API calls. **Not measured in a browser**, this is reasoning. It is worth confirming in the browser network panel.
- nginx has no gzip and no cache headers for `/media` or `/assets`. Media files are named with a random id and written once (`storage.py` uses `uuid4().hex`), so they are safe to cache as immutable. The JSON responses (915 KB for project 35) are sent uncompressed.

### 3.5 Large payloads that are not needed up front

`/shot-references` is 361 KB and `/shot-prompts` is 218 KB for 22 shots. These carry full prompt text and details for every shot, although the user looks at one shot at a time. This matches your idea: summaries up front, details when clicked. It is a smaller win than 3.1 to 3.3 (it is localhost), so it comes later.

---

## 4. Why it is hard to see progress today

What exists:

- `StoryPipelinePanel` shows step status **only for the newest pipeline run** (a run is a `story_pipeline` job; its state lives in `job.output`). It has 5 states: Waiting, Running, Done, Up to date, Problem.
- Each stage panel shows its own status further down the page.
- `StageList` at the bottom of the page is a static list of "Available / Not available yet" and does not reflect real progress.
- `StalenessPanel` shows what is out of date, grouped by step.

What is missing:

- **No status for manual work.** If you press buttons yourself instead of running the pipeline, nothing summarizes where you are. The step list only exists inside a run.
- **No "next step".** Nothing says which step is ready to start by hand.
- **No "blocked by".** A step that cannot start does not say which earlier step it is waiting for.
- **No "is anything happening right now" indicator** for the project: pipeline run active, manual jobs running, waiting for a GPU slot, paused at a step, or idle.
- **The page is about 40 panels long**, with no overview and no way to jump quickly. Only a few panels have `id="pipeline-step-..."` anchors.

What we can reuse (important):

- `story_pipeline.STEPS` already defines **32 steps with their dependencies** (`needs`). That is the right model for the board and for "next step".
- Each step has an adapter `evaluate()` in `story_pipeline_targets.py` that already returns, per target (character, scene, shot, or project): `done`, `active`, `block` (why it cannot go on), `stale`, `last_error`, `waits_for`. This is exactly the status data the board needs. Nothing new has to be invented, but it is too slow today (3.5 s), which is why step 1 comes first.

---

## 5. The proposed Pipeline Board

### 5.1 Idea

One page for a project that shows **every step at once**, as a compact list. Nothing heavy loads until you click a step. From a distance you can see what is done, what is working, what is blocked and what you can click next.

Proposed address: `/projects/:id/pipeline`, with a step detail at `/projects/:id/pipeline/:stepKey`. I suggest making it the default landing page of a project, with the current long page kept as "Classic view" until the board does everything it does.

### 5.2 Layout (sketch)

```
Project: English02            [Landscape]   [Settings]  [Classic view]

STATUS:  Pipeline running - "Generate the clips" 14 of 22
         1 waiting for a GPU slot, 3 running, 0 problems          [Stop]
   or:   Manual mode - nothing running.  Next: "Plan the shots"    [Open]
   or:   Paused after "Define the scenes"                          [Continue]

STORY
  [done]     Story Bible                               1 of 1
  [done]     Find the characters                       4 of 4
  [done]     Find the environments                     3 of 3
  [done]     Find the scenes                           5 of 5
CHARACTERS
  [done]     Define the characters                     4 of 4
  [running]  Draw the characters                       2 of 4    2 jobs
  [ready]    Voices and narrator                       0 of 5    <- next, click to open
SCENES
  [blocked]  Define the scenes          waiting for: Draw the characters
  [stale]    Extract the events                        5 of 5    2 out of date
SHOTS
  [problem]  Generate the clips                        14 of 22  2 failed
  ...
RENDER
  [not yet]  Render the video                          waits for: Generate the clips
```

Clicking a row opens that step's detail on the right (or a new route). The detail view is where the existing panel loads.

### 5.3 Step status model

Derived from data the backend already has. One status per step, in priority order:

| Status | Rule | Colour |
|--------|------|--------|
| Needs attention | A target failed or is blocked with a reason, and nothing is active | red |
| Running | At least one target of the step has an active job (queued or running) | blue |
| Out of date | Done, but one or more targets are stale | yellow |
| Done | Every target is done and none is stale | green |
| Ready (next) | Not done, nothing active, and every step in `needs` is Done | white with accent |
| Waiting | Not done and at least one step in `needs` is not Done. Shows which one | grey |
| Skipped / off | Step is turned off for the project (for example music switched off) | faint grey |

"Next in the order I can click" = the Ready steps, ordered by `STEPS`. The first one is highlighted as **Next**. There can be several Ready steps at once, because the graph allows parallel branches; showing all of them is more truthful than showing one.

"Is the pipeline actively being worked" comes from three things the system already knows: the newest `story_pipeline` run (running, paused, review wait, finished), whether any project job is queued or running, and the pool capacity (waiting for a GPU or API slot). The header combines them into one sentence.

### 5.4 Details only when clicked

- The board loads **one** small response (32 rows, a few KB).
- Opening a step mounts **only that step's existing panel** (loaded with `React.lazy`). The existing panels already fetch their own data, so they need almost no change for the first version.
- A shot step shows the 22 shots as a compact list. Clips, prompts and references load for the one shot you expand.
- Later, step details can get their own slimmer endpoints (section 3.5).

### 5.5 Backend for the board

Two new read-only endpoints. Names are a proposal.

1. `GET /api/projects/{id}/pipeline-board`: header (run state, active jobs, pool waiting, paused or review wait, next-step keys) and the list of steps with `key, label, group, needs, status, done, total, active, stale, failed, blocked_by, blocked_reason, updated_at`.
2. `GET /api/projects/{id}/activity`: tiny and very cheap. Returns a `revision` number that changes whenever anything in the project changes (job state, new artifact, edit), plus counts of queued and running jobs. The UI polls this one at a few seconds interval. Open panels refetch **only when the revision changes**.

The board endpoint should compute from the existing adapters' `evaluate()`. That is only affordable once step 1 (memoization) is done. Estimated cost after step 1: a few hundred milliseconds (**not measured, estimate** from 1,224 calls reduced to about 25 real computations).

### 5.6 Shot and video tracking (your point about scrolling the video)

I read "difficult to track the video and scroll through to the end" as: the page is too long and it is hard to find a shot or follow the video. I would handle this as part of the board, later:

- A horizontal **storyboard strip** of shots with poster thumbnails and a coloured border for status (generated, generating, failed, out of date).
- Click a shot to open its clip, prompt, takes and references in a side panel.
- A sticky mini step list so you can jump without scrolling.

Please correct me if you meant something different (section 8).

---

## 6. Other fixes, grouped

### 6.1 Backend

| Fix | Effect | Risk |
|-----|--------|------|
| **Request-scoped memoization of `state()`**: within one read-only request or one evaluation pass, each stage is computed once per project. | Turns about 1,224 computations into about 25. Biggest single win. | Medium. Must only be active during read-only passes. If a request writes and then reads, it must not reuse an old result. |
| Apply it to: GET endpoints (`/staleness`, `/story-pipeline`, `/shot-*`, `/story-renders`), the board endpoint, and the evaluate phase of a pipeline run (not the start phase). | Fixes both page loads and the run's own cost. | Needs care at the boundary between evaluate and start. |
| **Cross-request cache** keyed by a project revision, bumped by a database write hook (any flush of a row with a `project_id`, plus library tables). | Repeated polls with no change become nearly free. | Higher. Derived state may depend on library items from other projects, files or time. Needs an explicit list of invalidation sources. Do this only if step 1 is not enough. |
| Do not add uvicorn workers. | n/a | Duplicate dispatchers. |
| Gzip responses (backend or nginx). | JSON 915 KB becomes about 10x smaller on the wire (**estimate**). | Low. |

### 6.2 Frontend

| Fix | Effect | Risk |
|-----|--------|------|
| Panels mount only when expanded (accordion, `keepMounted` off), or when scrolled near. | 39 requests become about 3 on open. Also limits invalidation fallout, since only mounted queries refetch. | Low. Some panels read each other's data through hooks (for example `useGenerationRequests` reads `useShotDefinitions`); those panels must keep working when opened alone. |
| Default `staleTime` of about 15 to 30 s, `refetchOnWindowFocus: false` for project queries. | Tab switching stops refetching everything. | Low. |
| Stop polling `/staleness` every 3 s. Refresh it when the activity revision changes, or every 20 to 30 s, and only when its panel or the board is open. | Removes the most expensive repeated call. | Low. |
| Replace per-panel `refetchInterval` with the single `activity` revision. | One cheap poll instead of 10 to 20 heavy ones. | Medium. Touches about 50 hooks; do it gradually, board first. |
| `React.lazy` for pages and the heavy panels; Vite `manualChunks` for Mantine and React. | Smaller first load. | Low. Nice to have. |
| Lower `useJobs` limit and scope (200 jobs, all kinds, per project). | Smaller polls. | Low. |

### 6.3 Media

| Fix | Effect | Risk |
|-----|--------|------|
| Create a small WebP thumbnail (for example 320 px) when an image is stored; add `thumb_url` to API responses; use it in lists and the board. Full image on click. | Each thumbnail goes from about 2.8 MB to tens of KB. | Medium. Needs a backfill for the existing 1,334 images, and a schema/API change. The backfill must not delete or change originals. |
| Video poster (first frame JPG) stored next to each clip; `<video preload="none" poster=...>`; load the clip on click. | Removes 22+ metadata fetches on open. | Medium. Same backfill note. |
| nginx: gzip for JSON, JS, CSS; `Cache-Control: public, max-age=31536000, immutable` on `/media/` and `/assets/`. | Faster reloads and revisits. | Low. Safe because media names are write-once uuids. Confirm no code overwrites a name. |
| Consider serving `/media` from a second host name or port so media cannot queue ahead of API calls. | Helps if contention is confirmed in the browser. | Low. Only if measured. |

---

## 7. Recommended order of work

Ordered by (impact on what you feel) divided by (effort and risk). Effort is a rough guess (**uncertain**), in focused working days.

| Phase | Work | Why here | Depends on | Effort |
|-------|------|----------|------------|--------|
| **0** | Save the measurement scripts into the repo (outside app code) so every phase can be compared to the same baseline. | We need before/after numbers. | none | 0.5 d |
| **1** | **Backend: request-scoped memoization of `state()`**, applied to the read endpoints and to the evaluate pass of the pipeline poll. | Cuts the cost of everything else, and the board needs it. | 0 | 1 to 2 d |
| **2** | **Frontend quick wins**: lazy-mounted collapsed panels, default `staleTime`, no focus refetch, `/staleness` not polled every 3 s. | Immediate relief, tiny code change. Independent of 1; can be done in parallel. | none | 1 d |
| **3** | **Backend: `pipeline-board` and `activity` endpoints.** | The data for the board. | 1 | 1 to 2 d |
| **4** | **Frontend: Pipeline Board page.** Step list, header status, next-step highlight, click-to-open detail that lazily mounts the existing panel. Classic view kept. | The new experience you asked for. | 2, 3 | 2 to 4 d |
| **5** | **Media**: nginx gzip and immutable caching first (hours), then thumbnails and posters with backfill, `preload="none"`. | Lighter pages, faster scroll. | none (can run any time after 2) | 1 d for nginx, 2 to 3 d for thumbnails |
| **6** | Replace per-panel polling with the activity revision; slim list payloads (summary first, detail on click); storyboard strip; consider a cross-request cache, or push updates (server-sent events) if polling is still not enough. | Polish and scale. | 3, 4 | open |

Each phase leaves the app working and can be merged on its own. Phase 1 and phase 2 together should be enough to make the app feel clearly faster; phases 3 and 4 give the visibility you asked for.

Expected results (**estimates, not promises**; we will measure after each phase):

- After phase 1: `/staleness` and `/story-pipeline` on project 35 from 3.5 s and 1.6 s to well under 1 s, and the 12 s total for the old page much lower.
- After phase 2: opening a project sends about 3 requests instead of 39.
- After phase 4: the board costs one small request and renders at once.

---

## 8. Open questions for you

1. **Board as default?** Should the board become the default page of a project, with the current page behind a "Classic view" link? (My recommendation: yes, keep Classic until the board covers everything.)
2. **Next step.** Show all Ready steps (several can be ready at once because steps run in parallel branches), with the first one highlighted? Or only the single next step? (Recommendation: all ready, first highlighted.)
3. **Run from the board.** In the first version, clicking a step opens its panel. Should the board also have a direct "Run this step" button on each Ready row? It would call the same actions the panels use. (Recommendation: second version.)
4. **The video and scrolling point.** Did I read it correctly (find shots and follow the final video without long scrolling)? A storyboard strip is the plan for that; if you meant the video player itself, tell me what is hard there.
5. **Thumbnails.** Are you fine with generating and storing small thumbnails and posters next to the originals, and backfilling old projects? Originals would never be changed or removed.
6. **Where do you see the slowness most?** Opening a project, switching tabs, or while jobs run? The analysis says all three, but the order of effort could change if one matters much more to you.

---

## 9. Limits and uncertainty

- Timings come from the API (a Python client against the running app), not from a browser. Browser rendering time, React render cost and video or image decoding were **not profiled**. Phase 0 should include a browser performance recording of opening a project so we can see what the browser itself spends.
- The timings are noisy because jobs were running (`/staleness` for project 35 varied from 3.5 s to 27 s). The call counts (1,224 and 1,315) are not noisy and are the more reliable evidence.
- Parallel behaviour was simulated with 6 connections, which is the usual browser limit, not measured in a browser.
- The claim that media requests queue ahead of API calls is reasoning, not measurement.
- The speed-ups and effort numbers are estimates. Memoization is the one with the clearest basis (call counts), but the real gain depends on how much of the time is in the repeated `state()` work versus database reads, which we will know after phase 1.
- I did not read all 167 `state()` call sites. A few stages may depend on things outside the database (files, library items shared between projects). That matters for any cache that lives longer than one request, which is why the cross-request cache is a later, optional step.
- Housekeeping: the counting script used for section 2.4 was copied into the running backend container at `/tmp/count_state.py` (read-only, nothing was written to the database). It could not be deleted because of permissions inside the container. It disappears when the container is recreated and has no effect on the app.
