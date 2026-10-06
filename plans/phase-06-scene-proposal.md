# Phase 6: AI scene proposal

The executor's first step is to save this plan as `plans/phase-06-scene-proposal.md`, following the template in Section 4.6 of `ITERATION_1_PHASES.md`.

## 1. Goal and outcome

When this phase is done, you can:

- click **Propose scenes** on a project page and, after about 20 seconds and a Refresh, see the script split into scenes. Each scene shows its text, time range, duration (red outside the project's limits), who placed its cut (AI, rule), any flag, and a **Play** button that plays exactly that slice of the voiceover;
- click **Propose scenes** again with nothing changed and get the stored answer with no paid call, or click **Run again** to ask the model again;
- see a notice when the language model could not be used and the rule-based splitter proposed the scenes instead;
- be asked first when the recording differs from the script (the mismatch gate), and when scenes already have inputs (they are replaced on confirmation);
- see the scenes marked **out of date** after the script or the voiceover changes.

It provides the LLM client, the scene planner (prompt, request, checks), the splitter, and `build_scene_specs`, the cuts-to-scenes function that Phase 7 reuses.

```mermaid
flowchart TD
    click["Propose or Run again"] --> api["POST propose-scenes: gates, create job, 202"]
    api --> start["PlanScenesHandler.start"]
    start --> hash["Build the request and input_hash"]
    hash -->|"same hash, usable answer, not Run again"| cache["Reuse the stored answer"]
    hash -->|"otherwise"| call["LLM call: attempt 1, retry once"]
    call -->|"usable JSON"| checks["Checks: numbers, checksum words, window of 3"]
    cache --> checks
    call -->|"failed twice or refused"| alone["Splitter alone, from paragraph breaks"]
    checks --> enforce["Splitter enforces min and max"]
    alone --> build["build_scene_specs: times, text, cut_source, cut_note"]
    enforce --> build
    build --> save["One transaction: replace scenes and finish the job"]
```

## 2. Findings (2026-10-06)

- **Code.** Phase 5 is finished but **not committed** (working tree). The migration head is `0002`. There are no `scene` rows. The pieces this phase plugs into:
  - [backend/app/jobs/handlers.py](backend/app/jobs/handlers.py) has the `never_rerun` rule, and the dispatcher already skips the health and contract checks for `llm` jobs.
  - `store.create_job` returns the already-active job, so a double click gives one job.
  - [backend/app/core/outbound.py](backend/app/core/outbound.py) attaches the Bitdeer key only to `https://api-inference.bitdeer.ai`, and lets no caller set headers.
  - The settings `llm_base_url` and `llm_model` exist.
  - `transcript_matching.normalise` gives the checksum comparison for free.
  - `transcripts.transcription_state` gives the warnings for the mismatch gate.
- **Sample (project 5, transcript 1).** 137 script words in 12 paragraphs, and a voiceover of 60.20 s. Parakeet's word times have almost no gaps: the largest is 0.32 s, and gaps that size also appear inside phrases ("across | space."). So pauses measured from word times are weak signals.
- **Spike 3**: 4 paid calls, run one at a time from inside the backend container through `outbound.request`, with the prompt in Section 4. Total about $0.0035. You chose to skip the comparison with your own cuts.
  - **A (effort default, which is max; with time labels):** 36.5 s, 1,492 prompt and 6,934 output tokens (6,511 of them reasoning), about $0.0018. 15 scenes, all 15 checksums exact, every scene within 2 to 6 s. Cuts at every paragraph, plus "today |", "freely. |" and "Bang, |".
  - **B (effort low):** 3.9 s, 538 output tokens (195 reasoning), about $0.0003. It cut only at paragraph breaks, so 3 scenes ran over 6 s (9.5, 7.2 and 8.1 s), and the last entry used number 137, which is out of range.
  - **C (effort high, with time labels):** 19.0 s, 2,254 output tokens (1,831 reasoning), about $0.0007. The same 15 cuts as A, all exact.
  - **D (effort high, no time labels):** 16.4 s, 939 prompt and 2,568 output tokens. The same 15 cuts, but one checksum was miscopied: "the entire universe?" instead of "of the universe?" at word 23, with the number right. The check caught it.
- **[VERIFY] results.**
  - **JSON response mode:** `response_format: {"type": "json_object"}` is accepted, and the content was pure JSON, without fences, in all 4 runs. Bitdeer also documents a strict `json_schema` mode, which was not needed.
  - **Reasoning control:** GLM-5.3-Flash always reasons. Z.ai's docs say thinking cannot be disabled. `reasoning_effort` (`low`, `high`, `max`) is honoured by Bitdeer. `usage.reasoning_tokens` sits at the **top level** of `usage` and is included in `completion_tokens`. The message carries `reasoning_content` (about 20 KB at max effort).
  - **Cloudflare:** passes from inside the container with the app's User-Agent, and this was the first chat completion through the shared helper.
- **Time labels:** on this evenly paced sample they made no difference to the cuts, and they cost about 550 prompt tokens. They are kept, because uneven pacing needs them and they cost almost nothing.

## 3. Decisions

Your answers:

- **Spike 3 ran during planning** (4 calls, results above). **No comparison with your cuts.**
- **Scenes go out of date instead of locking.** The scenes record the voiceover asset id and the script hash they were proposed from, in the `job.input` of the `plan_scenes` job that wrote them. When either one differs from the project's current value, the page shows "out of date" with the reasons (`script_changed`, `voiceover_changed`), the same way the transcript does. Nothing is locked, and no Phase 3 endpoint changes. Proposing again (after transcribing again) replaces them, following the inputs rule.
- **Cache key (the Gap): `input_hash` inside `job.input`.** No migration. The lookup reads this project's `plan_scenes` jobs, newest first.

Planner choices, each **marked for your approval**:

- **APPROVAL: paid calls during the checks.** Up to 5 (3 expected), about $0.003 in total. Also **one** Parakeet transcription on the test project "Phase 5 checks", to trigger the mismatch gate.
- **APPROVAL: request settings from the spike.** These are constants in code, not UI settings:
  - effort `"high"`: the same cuts as max in half the time, while low ignored the limits;
  - `response_format` `json_object`;
  - `max_tokens` 16,000, about $0.004 at most per call;
  - a time limit of 180 s;
  - the temperature is not sent (the provider's default).
- **APPROVAL: no `openai` SDK.** The client is about 80 lines on `outbound.request`. The SDK would set `Authorization` itself and bypass the helper's URL, size and key rules.
- **APPROVAL: the retry policy, 2 attempts at most** (Section 5.8 "retry once", within Section 6.2's limit of 2 retries).
  - Retried once after 5 s: no answer or a timeout, HTTP 429, HTTP 5xx, and an unusable answer (unparseable, wrong shape, empty content, `finish_reason: "length"`).
  - Not retried: HTTP 400, 401, 403, 404 and 422. The splitter is used at once, and the notice shows the server's message.
  - After 2 failures, the splitter proposes alone. The job still **succeeds**, with `source: "rule"`.
- **APPROVAL: what the splitter does alone.** It starts with a cut at every paragraph break, then enforces the limits. Splitting the whole script near its middle would merge short paragraphs. On the sample this gives 15 scenes, one of them flagged.
- **Splitter rules** (Section 5.2, made concrete):
  - **Boundary rank:** a paragraph break (4), a sentence end (3: the word ends in `. ? !` or `…`, optionally followed by a quote or a bracket), clause punctuation (2: `, ; :` or a dash), a pause of at least 0.5 s (1), anything else (0).
  - **Too long:** prefer boundaries that leave both pieces within [min, max]; otherwise both at least min; otherwise any. Take the highest rank, and of equal ranks the one closest to the scene's middle. Repeat. A cut of rank 1 or below is flagged as "cut inside a sentence".
  - **Too short:** merge into the shorter neighbour if the result is at most max. Otherwise flag it.
  - **Long silence:** a gap of at least 1.5 s between two words gets a note. With Parakeet this rarely triggers.
- **Check rules.**
  - A cut is valid when 0 ≤ k < n−1 and k is above the previous cut. k ≥ n−1 means the end of the script (run B's 137), not an error.
  - A checksum matches when the quoted words, each normalised, equal the script's words before and after the cut, however many words were quoted.
  - On a mismatch, the cut moves to the nearest position within ±3 words where both sides match. If there is none, the cut stays at the AI's number and is flagged (run D).
  - The answer is **unusable** only when it is not JSON, has no `scenes` list, or has no valid entries. Single bad entries are dropped and counted.
- **Timing:** a cut is at `(words[k].end + words[k+1].start) / 2`, rounded to 3 decimals. The first scene starts at 0.0. The last ends at the voiceover's `duration_s` (or the last word's end if that is missing). The cut list always ends with the script's last word, whose "cut" is the end of the audio. That cut's `cut_source` is the proposal's source (`ai` or `rule`).
- **The inputs rule:**
  - A scene has inputs when it has a non-blank `scene_description`, either frame, or a `selected_clip_asset_id`.
  - Without inputs, scenes are replaced freely. With inputs, the endpoint answers 409 unless `discard_scenes_with_inputs` is true.
  - The handler checks again in its save transaction. If inputs appeared while the job ran and the job was not confirmed, the job fails and nothing is lost (the paid answer is cached).
  - Files are never touched.
- **The mismatch gate:** when `transcription_state` has warnings, the endpoint answers 409 unless `accept_mismatch` is true.
- **Preconditions (422):** a voiceover and a script exist; a transcript exists and is not out of date; the script has at most **1,500 words** (about 10 minutes; longer scripts are refused clearly, Section 5.2).
- **The paid answer is stored at once:** right after each attempt, the attempt and any usable answer go into `job.output`, before the checks run. A job interrupted by a restart fails ("never re-runs by itself"), but its stored answer is still used by the cache.
- **No `provider_job_id` for LLM jobs.** The completion id goes into the attempt record instead. A running job with a provider job id and no task would be polled forever.
- **APPROVAL, a deviation: the shape of `job.output` for `plan_scenes`.** DB Section 5 says "the LLM's raw answer verbatim". The answer is kept verbatim in `output.answer`, next to the usage, the attempts and the check counts (shape in Section 4). This updates DB Section 5 and is recorded in the phase log.
- **Small fix:** `store.cancel_job` says "already running on the GPU server" for every job type. It says "already running and cannot be cancelled" for non-GPU jobs.

## 4. Changes

### Database

No migration. [DATABASE_STRUCTURE.md](DATABASE_STRUCTURE.md):

- Section 5: the `plan_scenes` `job.input` and `job.output` shapes below.
- Section 7: the "AI picks cut words" row. In one transaction: DELETE the project's `scene` rows, INSERT the new ones, and UPDATE the job. Note that deleting a scene cascades to its `job` rows.

### JSON shapes

- `job.input` at creation: `{transcript_id, voiceover_asset_id, script_sha256, run_again, accept_mismatch, discard_scenes_with_inputs}`. The handler adds `server_url`, `endpoint` (`/chat/completions`), `request` (the exact body) and `input_hash` (`"sha256:" + sha256(canonical JSON of {url: called URL, body})`), and saves them **before** the call.
- `job.output`: `{source: "ai"|"rule", cache_hit_of_job_id, fallback_reason, answer: {scenes: [...]}|null, answer_usable, content (raw text, only when unusable, at most 20,000 chars), attempts: [{outcome, http_status, message, finish_reason, response_id, elapsed_s, usage}], usage: {prompt_tokens, completion_tokens, reasoning_tokens}, checks: {entries, exact, moved, flagged, dropped}, splitter: {cuts_added, cuts_removed}, scene_count, flagged_scenes}`. `reasoning_content` is not stored.

### The prompt (as run in the spike)

System message, with `{min:g}`, `{max:g}` and `{end:.2f}` filled in from the project and the voiceover:

```text
You split the script of a voiceover into scenes for a video. Each scene becomes one video clip, and scenes are joined with hard cuts.

Rules:
1. Every scene lasts at least {min} seconds and at most {max} seconds. A scene runs from the start time of its first word to the start time of the next scene's first word. The first scene starts at 0.00 and the last scene ends at {end}.
2. Where to cut, best first: at a paragraph break (a blank line in the script), at the end of a sentence, at clause punctuation (a comma, semicolon, colon or dash), at a pause. Do not cut in the middle of a phrase. Avoid very short scenes.
3. Keep one visual idea in one scene. There is no target length.
4. Scenes follow the script in order, cover all of it, and do not overlap.

Answer with a JSON object only, in exactly this form:
{"scenes": [{"last_word": 57, "words_before_cut": "the lazy dog", "words_after_cut": "Then the fox"}]}
- One entry per scene, in order, including the last scene.
- last_word is the number of the scene's last word, copied from the script.
- words_before_cut is the three words that end the scene (the last of them is last_word), and words_after_cut is the three words that start the next scene, both copied exactly. For the last scene, words_after_cut is "".
```

User message: `Extra instructions from the author:\n{cut_instructions}\n\n` (only when set), then `Script: {n} words, {end:.2f} seconds of audio. Each word is written as [number|start time in seconds] followed by the word. Blank lines are paragraph breaks.\n\n`, then one line per paragraph of `[i|start] word` entries (start to 2 decimals), with paragraphs separated by a blank line.

### Backend

- New [backend/app/providers/llm.py](backend/app/providers/llm.py): the LLM client (Section 6.4). It makes one attempt per call; the handler owns the retries.

```python
CHAT_PATH = "/chat/completions"
class LlmCallError(Exception): kind: Literal["unreachable","rate_limited","server_error","refused","bad_answer"]; status_code: int | None; message: str
@dataclass(frozen=True)
class ChatResult: content: str; finish_reason: str | None; usage: dict[str, Any] | None; response_id: str | None
def chat_url(base_url: str) -> str                       # docker_mapped(join_url(base_url, CHAT_PATH))
async def complete(base_url: str, body: dict[str, Any], *, timeout_s: float) -> ChatResult
def usage_counts(usage: object) -> dict[str, int | None] # prompt, completion, reasoning (top level or completion_tokens_details)
```

- New [backend/app/services/scene_cuts.py](backend/app/services/scene_cuts.py) (pure; Phase 7 reuses it):

```python
@dataclass(frozen=True)
class Word: index: int; text: str; start: float; end: float; paragraph: int
@dataclass(frozen=True)
class Cut: last_word: int; source: Literal["ai","rule","manual"]; note: str | None = None
@dataclass(frozen=True)
class SceneSpec: index: int; start_s: float; end_s: float; text: str; first_word: int; last_word: int; cut_source: str; cut_note: str | None
def words_from_script_words(script_words: object) -> list[Word]
def cut_time(words: Sequence[Word], last_word: int) -> float
def build_scene_specs(words: Sequence[Word], cuts: Sequence[Cut], audio_end_s: float) -> list[SceneSpec]  # cuts end at n-1; ValueError if times do not increase
def has_inputs(scene: Scene) -> bool
```

- New [backend/app/services/scene_splitter.py](backend/app/services/scene_splitter.py) (pure):

```python
@dataclass(frozen=True)
class SplitStats: cuts_added: int; cuts_removed: int
def boundary_rank(words: Sequence[Word], k: int) -> int
def enforce_limits(words, cuts, audio_end_s, min_s, max_s) -> tuple[list[Cut], SplitStats]
def split_alone(words, audio_end_s, min_s, max_s) -> tuple[list[Cut], SplitStats]
```

- New [backend/app/services/scene_planner.py](backend/app/services/scene_planner.py) (pure). This is Section 6.4's `ScenePlanner`, split into steps the way Phase 5 split `Transcriber`:

```python
MAX_SCRIPT_WORDS = 1500; MAX_TOKENS = 16000; REASONING_EFFORT = "high"; CHECKSUM_WINDOW = 3
def build_request(words, *, model: str, min_s: float, max_s: float, audio_end_s: float, instructions: str | None) -> dict[str, Any]
def request_hash(called_url: str, body: dict[str, Any]) -> str
def parse_answer(content: str) -> list[dict[str, Any]]           # ValueError("...") when unusable
@dataclass(frozen=True)
class CheckStats: entries: int; exact: int; moved: int; flagged: int; dropped: int
def check_cuts(words, entries) -> tuple[list[Cut], CheckStats]  # ends with Cut(n-1, "ai")
```

- New [backend/app/services/scenes.py](backend/app/services/scenes.py) (database):
  - `list_scenes(session, project_id)`;
  - `scenes_with_inputs(session, project_id) -> int`;
  - `replace_scenes(session, project_id, specs)`: DELETE, then INSERT. It flushes and does not commit;
  - `proposal_job(session, project_id)`: the newest succeeded `plan_scenes` job;
  - `stale_reasons(job, project)`;
  - `find_cached_answer(session, project_id, input_hash, exclude_job_id) -> Job | None`: any status, with `output.answer_usable`;
  - `scenes_state(session, project) -> ScenesState`.
- New [backend/app/jobs/plan_scenes.py](backend/app/jobs/plan_scenes.py): `PlanScenesHandler` (`plan_scenes`, `llm`, `never_rerun`, limit 2). Everything happens in `start`:
  1. Load the job, project, transcript and voiceover, and the two LLM settings. End the read.
  2. Fail with a readable message when the voiceover or the script changed since the click.
  3. Build the request and the hash, and save them with `store.update_input`.
  4. Look in the cache, unless `run_again`.
  5. Otherwise call the model, at most 2 attempts, saving each with `store.record_output`.
  6. Run the checks, then `enforce_limits`, or `split_alone` as the fallback.
  7. Run `build_scene_specs`.
  8. In one transaction: check the inputs again, `replace_scenes`, `store.finish_job(output)`, then commit (roll back if `finish_job` returns False).

  Logs hold the job id, attempt outcomes and token counts, never the prompt or the answer.
- [backend/app/jobs/phases.py](backend/app/jobs/phases.py): `preparing the prompt`, `asking the language model (attempt n of 2)`, `reusing the stored answer`, `checking the cuts`, `the language model failed: using the rule-based splitter`, `saving the scenes`.
- [backend/app/jobs/store.py](backend/app/jobs/store.py): `update_input(session, job_id, input)` and `record_output(session, job_id, output)` (running jobs only, conditional UPDATE, commit), and the cancel message fix.
- [backend/app/jobs/__init__.py](backend/app/jobs/__init__.py): register `PlanScenesHandler`.

### API (new [backend/app/api/scenes.py](backend/app/api/scenes.py), tag `scenes`, registered in [backend/app/api/__init__.py](backend/app/api/__init__.py))

- `POST /api/projects/{project_id}/propose-scenes`.
  - Body `{run_again?: bool, accept_mismatch?: bool, discard_scenes_with_inputs?: bool}`, with `extra="forbid"`.
  - 202 with `JobDetail` (the new job, or the active one).
  - 404.
  - 422 with "Upload a voiceover first.", "Paste the script first.", "Transcribe the voiceover first.", "The transcript is out of date. Transcribe again first." or "This script has N words; scene proposal handles up to 1,500."
  - 409 with the mismatch warnings, or with "N scenes have a description, frames or a clip...".
- `GET /api/projects/{project_id}/scenes` reads the database only and returns `ScenesOut`:
  - `job: JobSummary | null`: the newest `plan_scenes` job;
  - `proposal: ProposalOut | null`: `job_id, finished_at, source, fallback_reason, cache_hit_of_job_id, model, usage, checks, splitter`;
  - `scenes: [SceneOut {id, index, start_s, end_s, text, cut_source, cut_note, has_inputs}]`;
  - `stale_reasons`;
  - `llm: {model, will_call}`.

### Frontend

- New [frontend/src/api/scenes.ts](frontend/src/api/scenes.ts):
  - `useScenes(projectId)`, with the key `["projects", id, "scenes"]`, so saving the script or the voiceover refreshes the staleness;
  - `useProposeScenes(projectId)` (body flags), which calls `invalidateAfterJobAction` on success.
- New [frontend/src/components/projects/scenePlayer.ts](frontend/src/components/projects/scenePlayer.ts): `useScenePlayer()`. One hidden `<audio>` of the voiceover. Play sets `currentTime = start_s`, plays, and pauses at `end_s` through a `requestAnimationFrame` check that runs only while playing (local playback, not data polling). It also offers Stop.
- New [frontend/src/components/projects/ScenesSection.tsx](frontend/src/components/projects/ScenesSection.tsx), after `TranscriptSection` on [frontend/src/pages/ProjectPage.tsx](frontend/src/pages/ProjectPage.tsx):
  - **Propose scenes** and, once a proposal exists, **Run again**, with the line "Sends the script to {model} at {host} (paid). Propose reuses the stored answer when nothing changed; Run again always asks again";
  - both disabled, with the reason, when there is no current transcript or a proposal is active;
  - a Mantine `Modal` for the mismatch gate (the warnings from `useTranscription`) and the inputs confirmation, which then sends the matching flags;
  - the job's status badge, elapsed time and actions, with the hint "about 20 seconds; press Refresh";
  - the error when the job failed;
  - the out-of-date alert;
  - the splitter notice (`source === "rule"`, with `fallback_reason`);
  - a "reused the stored answer from job N" line;
  - the token line: "{model} · P prompt + C output tokens (R reasoning)";
  - a `Table` of the scenes: number, `start – end s`, duration (red with a tooltip outside `project.min/max_scene_seconds`), text, a cut-source badge, the `cut_note` in orange, and Play or Stop;
  - empty, loading and error states.
- Run `npm run gen:api` and commit `schema.d.ts`. The Activity page needs no change: "Scene proposal" already has a label.

### Configuration

No new setting, no new dependency, no nginx change.

## 5. Reading list for the executor

- `ANALYSIS.md`: Sections 3.6, 3.7 (LLM settings and the key rule), 5.1 (the matching output), 5.2 (all), 5.8 (the LLM and mismatch rows), 6.2 and 6.4.
- `DATABASE_STRUCTURE.md`: Sections 4.4, 4.5, 5 and 7.
- `ITERATION_1_PHASES.md`: Section 4, the Phase 6 section, and every phase log entry (especially Phase 5: the handler rules and Parakeet's word times).
- The code: [backend/app/jobs/transcribe.py](backend/app/jobs/transcribe.py) (the handler pattern), [backend/app/jobs/store.py](backend/app/jobs/store.py), [backend/app/jobs/dispatcher.py](backend/app/jobs/dispatcher.py), [backend/app/core/outbound.py](backend/app/core/outbound.py), [backend/app/services/transcripts.py](backend/app/services/transcripts.py), [backend/app/api/transcription.py](backend/app/api/transcription.py) and [frontend/src/components/projects/TranscriptSection.tsx](frontend/src/components/projects/TranscriptSection.tsx).

## 6. Steps in order

1. Save this plan. Add `scene_cuts`, `scene_splitter`, `scene_planner` and `providers/llm.py`. Check (no paid call) with ruff and a throwaway in-container `python -c` on transcript 1:
   - `split_alone` gives 15 scenes with cuts after words 9, 23, 35, 43, 49, 57, 65, 72, 80, 92, 99, 106, 116, 127 and 136. Only scene 0 is flagged ("light | reaching").
   - `check_cuts` on run B's answer (Section 2) plus `enforce_limits` adds the `rule` cuts 9, 43 and 57.
   - On run D's answer, word 23 is flagged and stays in place.
2. Add the phases, the store helpers, the handler and its registration. Check that the backend starts and logs no outbound call.
3. Add `services/scenes.py` and the API. Check with curl: **acceptance check 1** on project 5 (paid call 1). This is the natural break point.
4. Frontend: `api/scenes.ts`, `gen:api`, `scenePlayer.ts`, `ScenesSection`. Check in the browser.
5. Update DATABASE_STRUCTURE.md Sections 5 and 7.
6. Run every acceptance check, the linters and the earlier phases' main flow. Write the phase log entry, including the Spike 3 numbers.

## 7. Acceptance checks

Project 5 ("The First Light") is used for checks 1 to 5. Project 6 ("Phase 5 checks") is used for checks 6 to 9, so project 5 ends with real scenes.

1. **Propose (paid call 1).** On project 5 the job succeeds.
   - SQL: the first `start_s` is 0, the last `end_s` is 60.203 (the voiceover's duration), and every `start_s` equals the previous `end_s`.
   - Every scene is within 2 to 6 s or has a `cut_note`.
   - `job.output.usage` has prompt, completion and reasoning tokens, and `source` is `ai`.
2. **Cache.** Propose again: a new job succeeds with `cache_hit_of_job_id` set to check 1's job and no usage, and the backend log has no `outbound POST https://api-inference.bitdeer.ai` line for it. Run again (**paid call 2**): that line appears and `cache_hit_of_job_id` is null.
3. **Dead URL.** Save the LLM URL as `http://localhost:9`, then Propose. The phases show attempt 1, then attempt 2, and the job succeeds with `source: "rule"` and a `fallback_reason`. The page shows the splitter notice. Reset the URL.
4. **New limit.** Set the maximum to 4 s: the scenes are unchanged, and those over 4 s turn red. Propose (**paid call 3**): the new scenes are at most 4 s or flagged. Set the maximum back to 6 s and Propose: this is a cache hit of check 1's job, with no call.
5. **Play.** Play 3 scenes: each starts at `start_s` and stops at `end_s`. A headless check: `currentTime` stops within 0.05 s of `end_s`. You listen to confirm.
6. **Mismatch gate** (one Parakeet run). On project 6, edit the script substantially and transcribe. Warnings show. Set the LLM URL to `http://localhost:9`.
   - A POST without `accept_mismatch` answers 409 with the warnings.
   - In the UI, Propose opens the gate. Cancel does nothing, and Continue runs the job (the splitter fallback, so no paid call).
   - Restore the script and the URL.
7. **Inputs rule.** On project 6, `UPDATE scene SET scene_description='test' WHERE id=<one scene>`, then Propose (the URL still dead):
   - the API without the flag answers 409;
   - the UI asks first, and Cancel changes nothing;
   - Confirm replaces all the scenes, and the description is gone.
8. **Out of date.** On project 6, save a script change: the scenes show "out of date: script changed", and Propose is disabled with "Transcribe again first". Restore the exact script through PATCH: the scenes are current again.
9. **Restart.** Set the LLM URL to `http://10.255.255.1` (it hangs), Propose, and run `docker compose restart backend` while the job is "asking the language model". The job is `failed` with "Interrupted by a restart. Paid calls never re-run by themselves..." and never starts again. Restore the URL.
10. **Double click.** Two simultaneous POSTs return the same job id.
11. **No polling.** The project page idle for 60 s makes no requests (headless, plus your spot check).
12. **Definition of done.** ruff, tsc and ESLint are clean. `schema.d.ts` is regenerated. `docker compose up --build` works on the existing volume. Projects, voiceover, settings, the contract and transcription still work. No API response contains the key.

## 8. Out of scope

- Editing cuts, and edited scene text (Phase 7). Scene inputs (Phase 8).
- Splitting long scripts for small context windows (they are refused above 1,500 words).
- UI settings for effort, `max_tokens` or the time limit. Cost in currency. Refining cuts with FFmpeg `silencedetect`.
- The `openai` SDK. Cancelling a running LLM call.
- Guarding scene replacement against active clip jobs (Phase 9).
- Deleting jobs, transcripts or files.
- Automated tests.

## 9. Risks

- **Bitdeer behaves differently** (a 400 naming `reasoning_effort` or `response_format`, or `usage` moving): stop and ask.
- **The model varies between runs.** Only one run per setting was made. The splitter and the checks absorb bad cuts, and effort can be revisited from the job records.
- **Another LLM server may reject `reasoning_effort` or `response_format`.** The proposal then falls back with the server's message shown. Acceptable for iteration 1.
- **Parakeet absorbs silences into words**, so a cut can sit up to about 0.3 s later than the real pause (Phase 5 log). Acceptable for hard cuts. `silencedetect` could refine it later.
- **Replacing scenes deletes their `job` rows** (`scene_id` is ON DELETE CASCADE). There are none in Phase 6. Record in the phase log that Phase 9 must refuse replacement while a clip job is active.
- **Cost:** at most 2 calls of up to 16,000 output tokens each, about $0.008 at today's prices for one click in the worst case.
