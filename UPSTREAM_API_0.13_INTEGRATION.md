# Upstream model service 0.12 / 0.13: what changed and how to integrate it

Written 2026-10-14, from a live read of the GPU gateway (`http://localhost:18012`) compared with the
API this app last approved (snapshot rows 55 and 56 in `api_snapshot`, version **0.12.0**, approved
2026-10-12). The server now reports **0.13.0**. No code has been changed yet: this document is the plan.

---

## 1. Summary

| What | Upstream version | State in VisioStudio |
|---|---|---|
| **Lip sync on LTX audio-to-video** (`lip_sync: true` on LTX-2.3 and LTX-2.5) | 0.12.0 | API approved, **never used**. The Talking character lab calls LTX-2.3 audio-to-video without `lip_sync`. LTX-2.5 audio-to-video is not wired at all. |
| **TBDub standalone lip sync** (`POST /v1/tbdub/videos/lip-sync`) | 0.12.0 | Not used. |
| **`lip_sync` field on every job status** (`requested`, `applied`, `error`) | 0.12.0 | Not read. `gpu_server.job_status` ignores it. |
| **MiniMax H3**: `POST /v1/h3/videos/generate` and `POST /v1/h3/videos/audio-to-video` | **0.13.0 (new)** | Not approved, not used. |
| `JobListItem` / `JobStatusResponse` `pipeline` examples gain `h3:generate`, `h3:audio-to-video` | 0.13.0 | Documentation-only change. |

The server's own changelog for 0.13.0 says: *"No change to any existing endpoint."* The structural diff
of the two OpenAPI documents agrees: 2 operations added, 2 schemas added (`H3GenerateRequest`,
`H3AudioToVideoRequest`), 0 removed, and the only "changed" schemas differ in an `examples` list.

### Approval is no longer needed (done)

Previously the dispatcher paused every GPU job as "API changed" until the new server version was
approved in Settings, and requests were validated against the *approved* copy of the API. Both are
removed:

- `jobs/dispatcher.py` still calls `contract_guard.check()` before a GPU job, but only to record the
  server's current API and update the banner. It never holds a job back.
- `contract_guard.latest_bodies()` (was `approved_bodies`) gives request checks (frame limits, "does
  this endpoint exist") the newest recorded document, approved or not. `check()` now also stores a
  document when nothing was ever approved.
- Approving in Settings is an optional review of what changed.

---

## 2. What we call today vs what the server offers

| Upstream endpoint | Used by VisioStudio |
|---|---|
| `POST /v1/ltx/videos/generate` | Yes: scene clips and Video lab (LTX-2.3, first frame) |
| `POST /v1/ltx/videos/keyframe-interpolation` | Yes: LTX-2.3, first and last frame |
| `POST /v1/ltx/videos/audio-to-video` | Yes: Talking character lab only, **without `lip_sync`** |
| `POST /v1/ltx25/videos/generate` | Yes: LTX-2.5, first frame |
| `POST /v1/ltx25/videos/interpolate` | Yes: LTX-2.5, first and last frame |
| `POST /v1/ltx25/videos/audio-to-video` | **No** |
| `POST /v1/tbdub/videos/lip-sync` | **No** |
| `POST /v1/h3/videos/generate` | **No (new)** |
| `POST /v1/h3/videos/audio-to-video` | **No (new)** |
| `POST /v1/ltx/videos/retake`, `POST /v1/ltx25/videos/retake` | **No** |
| `POST /v1/ltx/audio/generate` (text-to-audio) | **No** |
| `POST /v1/wan-animate/videos/replace` | **No** |
| `GET /v1/rvc/voices`, `POST /v1/rvc/convert`, `POST /v1/rvc/batch-convert` | **No** |
| `GET /v1/partitions` | **No** |
| `POST /v1/breeze-tts/synthesize` | Yes: Voice lab, voiceover |
| `POST /v1/parakeet/transcribe` | Yes: transcription |
| `POST /v1/qwen-image21/images/generate`, `/edit` | Yes: Image lab, frames, cast references |

---

## 3. Lip sync on LTX-2.3 and LTX-2.5 audio-to-video

### 3.1 What the server does

Both `AudioToVideoRequest` (LTX-2.3) and `Ltx25AudioToVideoRequest` (LTX-2.5) accept
`lip_sync: bool` (default `false`). With `true`, after the video is generated, TBDub redraws the
speaker's mouth to match the audio exactly, **in the same job**. The audio you upload is still muxed
into the result unchanged.

Things that matter for our code:

- **Frame rate becomes 25.** The server forces `frame_rate` to 25 and converts an explicit
  `num_frames` to the same duration at 25 fps. The stored request on the server then differs from
  the one we sent.
- **Failure is silent.** If lip sync fails, the job still reports `succeeded` and returns the video
  *without* lip sync. Only `lip_sync.applied == false` and `lip_sync.error` on the job status say so.
- **A retry needs the source job.** `POST /v1/tbdub/videos/lip-sync` with `source_job_id` re-syncs a
  succeeded audio-to-video job without regenerating it, but only while that job still exists on the
  server. **We purge every job right after storing its clip** (`GenerateLabVideoHandler._check_and_store`
  calls `self._purge`), so today a retry would always have to upload the video and audio again.
- It adds several minutes per job, only changes mouth, jaw and nearby skin, and expects one speaker
  with a visible face. Eyebrows, nods and laughs still have to be described in the prompt.

LTX-2.5 audio-to-video differences from LTX-2.3:

- It has no `mode` and no `enhance_prompt` (one guided recipe), the same as LTX-2.3 audio-to-video.
- It **does** honour `negative_prompt`. Its built-in default includes "bad lip sync", and a value we
  send replaces it.
- `audio_max_duration` (up to 20 s) can make the clip exactly as long as the audio, but it is
  mutually exclusive with `num_frames`. We should keep sending `num_frames` so the frame-limit check
  against the approved spec keeps working.

### 3.2 Backend changes

**`backend/app/providers/video_generator.py`**

- Add `LTX25_AUDIO_TO_VIDEO_PATH = "/v1/ltx25/videos/audio-to-video"` and register it in
  `_REQUEST_SCHEMAS` as `"Ltx25AudioToVideoRequest"`, otherwise `frame_limits` refuses it.
- Add it to `_NEGATIVE_PROMPT_ENDPOINTS`. It must **not** go into `_MODE_ENDPOINTS`.
- Add a lookup `AUDIO_ENDPOINTS: dict[VideoModel, str] = {"ltx-2.3": AUDIO_TO_VIDEO_PATH, "ltx-2.5": LTX25_AUDIO_TO_VIDEO_PATH}`.
  `model_for` already maps the `/v1/ltx25/` prefix to `ltx-2.5`.

**`backend/app/services/video_lab.py`** (`LipSyncForm`, `create_audio_run`)

- Add `video_model: VideoModel = "ltx-2.3"` and `lip_sync: bool = False` to `LipSyncForm`.
- Choose the endpoint from `AUDIO_ENDPOINTS[form.video_model]` instead of the hard-coded LTX-2.3 path,
  and store the real model on `LabVideoRun.video_model`.
- When `lip_sync` is true, **compute the frames at 25 fps ourselves**:
  `fps = 25`, `num_frames = request_num_frames(ceil(audio.duration_s * 25))`, `frame_rate = 25.0`.
  Then add `"lip_sync": True` to the stored request. The server then has nothing to rewrite, the
  stored request matches what ran, and `_upload_audio` pads the speech to the right length
  (it uses `num_frames / frame_rate`).
- Put `lip_sync` into `params` so the run list can show it.

**`backend/app/providers/gpu_server.py`** (`RemoteStatus`, `job_status`)

- Parse the new `lip_sync` object (`requested`, `applied`, `error`) into an optional field and include
  it in `to_json()`. It is then saved on `job.output.remote` by the existing polling code.

**`backend/app/jobs/generate_lab_video.py`** (`_check_and_store`)

- If the request had `lip_sync: true` and `remote.lip_sync.applied` is `false`:
  - still store the clip (the user paid for it), and record `lip_sync: {"applied": false, "error": ...}`
    in the job output and on the run's `params`;
  - **skip the purge**, so the server keeps the job for a re-sync by `source_job_id`. The server deletes
    it anyway after `job_retention_days` (7).
- If `applied` is `true`, keep today's behaviour (store, then purge).

**New, small: a "re-sync" job** (only if we want the retry button)

- One new job type, for example `lab_lip_sync`, with `provider="gpu"` so it joins the GPU pool
  automatically (`jobs/pools.py`).
- Its handler submits `POST /v1/tbdub/videos/lip-sync` with `{"source_job_id": <provider_job_id>, "seed": ...}`,
  downloads the MP4, replaces the run's file (or stores a new run linked to the old one), then purges
  both server jobs.
- The handler can extend `GenerateLabVideoHandler` like `lab_video` extends `generate_clip`: only
  `start` differs.

**`backend/app/services/talk_lab.py`, `backend/app/db/models.py`, migration `0016_...`**

- Add `video_model` (`'ltx-2.3' | 'ltx-2.5'`, default `'ltx-2.3'`) and `lip_sync` (bool, default
  false) to `lab_talk_run`, and to `TalkForm`. Pass them into `LipSyncForm` in `_start_video`.
- `services/talk_prompt_profiles.py`: the profile `ltx-2.3-audio-to-video` also suits LTX-2.5 (both
  endpoints say "describe the visible speaker, no need to quote the dialogue"). When `lip_sync` is on,
  add one rule: describe the non-mouth expression (eyebrows, nods, smile) explicitly, because TBDub
  only redraws the mouth.

### 3.3 Our API changes

| Our endpoint | Change |
|---|---|
| `POST /api/lab/talk/takes` (`TalkTakeCreate`) | New optional fields `video_model: "ltx-2.3" \| "ltx-2.5"` (default `"ltx-2.3"`) and `lip_sync: bool` (default `false`). |
| `GET /api/lab/talk/takes`, `GET /api/lab/talk/takes/{id}` (`TalkTakeOut`) | Return `video_model`, `lip_sync`, and from the video run `lip_sync_applied: bool \| null` and `lip_sync_error: str \| null`. |
| `GET /api/lab/videos/runs...` (`LabVideoRunOut`) | Same two read-only fields for audio runs. |
| New: `POST /api/lab/videos/runs/{run_id}/lip-sync` | Starts the re-sync job for a run whose lip sync was not applied. 409 if the source server job is gone (purged or expired); the message tells the user to start a new take. |

Frontend: `TalkLabForm.tsx` gets a model selector (LTX-2.3 / LTX-2.5) and a "Lip sync (adds a few
minutes)" switch. The run card shows a warning badge when `lip_sync_applied === false`, with a
"Retry lip sync" button. Regenerate `frontend/src/api/schema.d.ts`.

### 3.4 Using lip sync in projects (later, needs a decision)

This is task 8 in `tasks.md` ("use the audio-to-video flow in our system"). A scene in which a cast
character speaks on camera could be made by audio-to-video with that scene's slice of the voiceover as
the audio and `lip_sync: true`, instead of image-to-video. That needs a rule for which scenes are
"on-camera speech" (the scene characters from migration 0015 are a start, but the narrator vs
character split is not modelled yet), and a way to cut the scene's audio slice. It is a larger
design item and is not part of the first step.

---

## 4. MiniMax H3

### 4.1 What it is

MiniMax H3 is an open-weight audio+video model: the picture and a stereo soundtrack come out of the
**same** denoising loop, so dialogue quoted in the prompt is spoken with matching lip movement. Two
endpoints:

| Endpoint | Inputs | Produces |
|---|---|---|
| `POST /v1/h3/videos/generate` | `prompt`; optional `first_frame_asset_id` and/or `last_frame_asset_id` | text-to-video, first-frame, last-frame, or first-to-last-frame video, with generated sound |
| `POST /v1/h3/videos/audio-to-video` | `prompt`, `audio_asset_id` (2 to 15 s), and at least one of `image_asset_ids` (up to 9) or `video_asset_ids` (up to 3) | video with generated sound, using the audio as a **reference** (voice timbre, delivery or music), not as the soundtrack |

### 4.2 How it differs from LTX (what our code assumes today)

| | LTX (our assumption today) | H3 | Where it bites in our code |
|---|---|---|---|
| Size | project's gen size, multiple of 64, default 1920x1088 | multiple of 32, 256 to 1536 per side. Trained at **1344x768 / 768x1344** | `ORIENTATION_DEFAULTS` in `services/projects.py`: 1920 exceeds H3's maximum. H3 needs its own size. The render already scales clips to the output size (`render_commands.trim_args`, lanczos). |
| Frame rate | project fps, default 24 | **fixed 24**, no `frame_rate` field | `build_request` always sends `frame_rate`. |
| Frame grid | `8k + 1` (`frame_counts.request_num_frames`) | **`17n + 5`, 124 to 345 frames (5.17 to 14.4 s)** | Needs a new rounding function. The spec declares `num_frames` 120 to 360, which is wider than the real grid, so `frame_limits` alone is not enough. |
| Minimum length | 9 frames | **5.17 s** | Scenes default to 2 to 6 s (`DEFAULT_MIN/MAX_SCENE_SECONDS`). See 4.4. |
| Negative prompt | some endpoints | **none** (guidance-distilled) | Must not be sent. |
| `mode` / `enhance_prompt` | on the generate endpoints | **none**. The prompt is used exactly as sent | Must not be sent. |
| Prompt | free prose | **structured format** (section 4.5) | New prompt profiles needed. |
| Frames in body | `images[]` / `keyframes[]` / `first_frame_asset_id` | `first_frame_asset_id`, `last_frame_asset_id` (both optional) | `with_frames` needs an H3 branch. |
| Sound | LTX makes ambient sound | H.264 + **AAC stereo 32 kHz** soundscape, music and speech | The render resamples to 48 kHz and mixes under the voiceover at the clip volume already. |
| GPUs per job | 1 | **2 H100s on one node** | `jobs/pools.py` counts every job as one slot (section 4.6). |
| Time | 5 to 10 min | **not measured yet**: the server says budget more than 10 min. Cold start every job | UI copy ("5 to 10 minutes") and expectations. No timeout to change: the dispatcher has none for GPU jobs. |
| Memory | fits | 61.7 GiB transformer on an 80 GB card. A long clip at full size may run out of memory | Suggest a smaller canvas (960x544) on an out-of-memory failure. |
| Steps | n/a | optional `num_inference_steps` 4 to 100 (default 50, a benchmark used 20) | Optional "draft" setting for the Video lab. |

### 4.3 Backend changes for `POST /v1/h3/videos/generate`

**New model id** (pick one, for example `"minimax-h3"`)

- `services/video_models.py`: add to `VideoModel`, `LABELS` (`"MiniMax H3"`) and `MODEL_PATTERN`.
- `db/models.py`: the `video_model_valid` CHECK constraints on **`project`, `scene` and `lab_video_run`**
  list `('ltx-2.3', 'ltx-2.5')`. A new migration must rebuild them (SQLite needs Alembic batch mode to
  change a CHECK).
- `services/video_lab.py`: `MAX_MODELS = 2` becomes 3, and the "Choose LTX-2.3, LTX-2.5, or both"
  message changes.
- Frontend: `src/videoModels.ts`, `components/videoLab/videoLabView.ts`, the model badges in
  `VideoLabRunList.tsx` and `SceneClipSection.tsx`, and `schema.d.ts`.

**`providers/video_generator.py`**

- `H3_GENERATE_PATH = "/v1/h3/videos/generate"` → `_REQUEST_SCHEMAS["H3GenerateRequest"]`.
- `ENDPOINTS[("minimax-h3", "first_frame")]` and `ENDPOINTS[("minimax-h3", "first_and_last")]` both map
  to `H3_GENERATE_PATH` (one checkpoint does both).
- `model_for`: recognise the `/v1/h3/` prefix.
- `build_request`: an H3 body is `prompt`, `width`, `height`, `num_frames`, `seed`, `partition`, and
  optionally `num_inference_steps`. **No `frame_rate`, `mode`, `enhance_prompt` or `negative_prompt`.**
- `with_frames`: for H3, `first_frame_asset_id` and, if any, `last_frame_asset_id`. Text-only is the
  same body without frames.
- `check_size` can stay: 1344 and 768 are multiples of 64. For H3 the hard limits are multiple of 32,
  256 to 1536.

**`services/frame_counts.py`**

- Add `h3_num_frames(target)`: the smallest `17n + 5` that is at least `max(target, 124)`, refusing
  anything over 345 frames (14.4 s).

**Sizes**

- An H3 run uses 1344x768 (landscape) or 768x1344 (portrait) whatever the project's gen size, the same
  way the Video lab already reads sizes from `ORIENTATION_DEFAULTS`. The frame PNG is fitted to the
  request size by `frame_images.render_frame_png` already, so frames come out at the H3 size.

**Pools**: see 4.6.

### 4.4 H3 in project scenes: two traps

1. **Short scenes are trimmed hard.** A 3 s scene gets a 5.17 s clip (124 frames), and the render keeps
   only the first 3 s. For a first-frame clip that only wastes GPU time.
2. **First-and-last-frame clips break for short scenes.** H3 lands on the last frame at the *end* of
   the generated video (5.17 s). The render cuts the clip at the scene's length, so for any scene
   shorter than about 5.2 s **the last frame is never shown**. LTX does not have this problem because
   its clip is at most 7 frames longer than the scene.

   Use the existing fallback in `endpoint_for` (the `note` mechanism) to make a short first-and-last
   scene with LTX-2.5 interpolate and tell the user why. Alternatively, an H3 project can raise
   `min_scene_seconds` to 5.2.

Also: in a narrated project, the clip sound sits under the voiceover. The scene prompt for H3 should
contain **no dialogue** (or describe narration as "an off-screen voiceover, lips stay closed") and
put the scene's sound effects in `overall_soundscape`. This gives better effects than LTX's
ambient sound. The per-shot `sfx` lists in `test.json` map straight onto that field.

### 4.5 The prompt format (needs new prompt profiles)

H3 was trained on a structured prompt, and nothing on the server rewrites it. For
`/videos/generate`:

```
integrated_multimodal_description: [Shot 1] <style, composition, subject, action, camera, speech> [Shot 2] At 00:03.500, <...>

overall_soundscape: <ambience and physical sounds, no dialogue>

non_diegetic_music: <instrumentation, tempo, dynamics, or N/A>
```

- Speech: speaker ids `(S1)`, words inside `<d>[English] ...</d>`.
- With a first frame, the first line must be
  `For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.`
- With first and last frames, the first line names the clip's length in seconds with two decimals
  (124 frames = `5.17`).

**Recommendation:** have *code* write the first line (it depends on the frame count, which only code
knows), and have the language model write the three fields. New profiles go in
`services/lab_prompt_profiles.py` (Video lab "write with GLM") and `services/description_profiles.py`
or `services/scene_prompt.py` (scene prompts). The full MiniMax guides are on the cluster at
`weights/h3/MiniMax-H3/docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md` and `..._ref_en.md`. Copy the
relevant rules into the profiles rather than calling the cluster for them.

### 4.6 GPU capacity: one H3 job uses two GPUs

> **Superseded by section 8.** The server now says how many GPUs a H3 job takes (4 or 8), and the app counts that.

`jobs/pools.py` counts every GPU job as one slot of `max_parallel_gpu_jobs`. With the limit at 4, four
H3 jobs would hold 8 GPUs. The simplest fix is a per-job slot cost (H3 = 2, everything else = 1),
read from the job's endpoint when the dispatcher counts running jobs. The new `PoolCapacityPanel.tsx`
should show slots used, not jobs. The two "GPUs" are reserved on one node, so an H3 job can also
wait in the Slurm queue longer than an LTX job. `GET /v1/partitions` (section 5) can show that.

### 4.7 `POST /v1/h3/videos/audio-to-video` (reference mode)

> **Changed in 0.14 and 0.15, see section 8.** The audio is optional and is now a list (`audio_asset_ids`).

This is a different tool from LTX audio-to-video:

- The audio is a **reference**. The prompt says, per reference, whether it is `fully_copy`,
  `partially_copy`, `reference` (follow voice timbre and delivery, words come from `<d>...</d>`) or
  `weak_reference`. The output soundtrack is the model's own rendition, never bit-exact.
- Up to **9 reference images** (`<Picture 1..9>`) and **3 reference videos** (`<Video 1..3>`). The
  references do not set the canvas, so `orientation` or `width`/`height` must be sent.
- Six-part prompt: `subject_definitions`, `summary`, `retention_analysis`, `detailed_description`,
  `overall_soundscape`, `non_diegetic_music`. 350 to 500 words recommended.
- `match_audio_duration: true` makes the clip as long as the audio (within 5.17 to 14.4 s).

Where it fits:

1. **Talking character lab, a new voice mode "voice reference (H3)".** Picture plus a saved voice
   sample (`Voice` row) as `<Audio 1>` with `reference`, and the dialogue in `<d>`. One GPU job makes
   speech and video together, with no Breeze TTS step. The speech is generated, not exact. If an exact
   line is needed, follow it with TBDub (`video_asset_id` + `audio_asset_id`) or use LTX lip sync.
2. **Cast consistency (more speculative).** Cast reference pictures as `<Picture N>` with
   `fully_preserved` could keep characters consistent across scenes, including multi-character
   scenes, without a first frame. But the endpoint always needs an audio reference. Whether an
   ambience clip marked `weak_reference` works as a neutral placeholder **has not been tested**.
   Try it in the lab before designing around it.

Code impact beyond 4.3:

- `generate_lab_video._LabPlan` needs a list of reference images (and later videos) besides
  `first_frame` / `last_frame`. The upload loop must upload them in order, because the order is what
  the prompt labels refer to.
- `_upload_audio` pads the speech to the clip length for LTX. For H3 the audio must **not** be padded
  (it is a 2 to 15 s reference). Check that range before submitting.
- Endpoint constant and schema `H3AudioToVideoRequest` in `video_generator.py`.

### 4.8 Licence

The server's guide says the MiniMax H3 Community License does **not** allow use or hosting in the
United States, the European Union, the United Kingdom or South Korea without MiniMax's written
authorization, and needs authorization for products above 20 million USD yearly revenue. The API
does not enforce this. Read the licence (`LICENSE` in the weights folder) before shipping H3 output in
anything public, and consider a one-line notice in the UI next to the model choice.

### 4.9 Our API changes for H3

| Our endpoint | Change |
|---|---|
| `POST /api/lab/videos/runs` (`LabVideoRunCreate`) | `models` accepts `"minimax-h3"`. Optional `num_inference_steps` (H3 only). `negative_prompt` and `mode` are ignored for H3 and the response `params` shows that, as it already does for LTX-2.5. Length is validated against 5.17 to 14.4 s for H3. |
| `POST /api/lab/videos/prompt-drafts` | Takes the target model, so the language model writes the H3 structured format when H3 is chosen. |
| Project and scene settings (`video_model`), Regenerate picker | Accept `"minimax-h3"` after the migration. The clip note explains a fallback to LTX-2.5 for short first-and-last scenes. |
| `POST /api/lab/talk/takes` | Later: `voice_mode: "h3_reference"`, with `voice_id` (the sample) and no speech step. |
| Settings → GPU capacity | Shows slot cost per running job (H3 = 2). |

---

## 5. Other upstream capabilities we could add

These are not new in 0.13.0, but none are wired in today.

| Upstream feature | What it does | What it could become here | Effort |
|---|---|---|---|
| **TBDub lip sync** (`POST /v1/tbdub/videos/lip-sync`) on any video + audio | Redraws the mouth of an existing video to an exact audio track. `audio_cfg_scale` / `ref_cfg_scale` tune it. | 1) Re-voice a scene after the voiceover changed, without regenerating the clip. 2) Combine with H3: H3 makes the performance, TBDub snaps the mouth to the exact Breeze TTS line. | Small, once the re-sync job from 3.2 exists |
| **Retake** (`POST /v1/ltx/videos/retake`, `/v1/ltx25/videos/retake`) | Regenerates only `[start_time, end_time]` of a video (picture and sound), keeps the rest. | "Fix this moment" on a scene take: pick a range on the clip and describe it. Our raw LTX takes are already `8k + 1` frames and multiples of 64, which retake requires. It must be run on the raw take, not the trimmed render. | Medium |
| **Text-to-audio** (`POST /v1/ltx/audio/generate`) | WAV sound effects or ambience from a prompt, no video. | A per-scene SFX or ambience track mixed in the final render (the render already mixes clip sound under the voiceover). Useful for LTX clips whose own sound is weak. | Medium |
| **RVC voice conversion** (`/v1/rvc/convert`, `/v1/rvc/batch-convert`, `GET /v1/rvc/voices`) | Makes a recording sound like one of the **pre-installed** voices while keeping its timing and emotion. Batch mode converts many files in one job. | A consistent character voice across a whole project: convert every line of one character in one job. Or record a line yourself and convert it. Limited to the voices installed on the server. | Medium |
| **Wan-Animate replace** (`POST /v1/wan-animate/videos/replace`) | Swaps the person in existing footage for a reference character image, keeping background, camera and light. No prompt. | Put a cast character into stock or user-recorded footage. A new lab first, since it is a different input (a video). | Medium–large |
| **Partitions** (`GET /v1/partitions`) | Live GPU availability and queue length per Slurm partition (cached 20 s). | Show availability next to the partition setting, and warn before starting a 2-GPU H3 job on a busy partition. | Small |
| **`incognito: true`** (every generation request) | No logs, inputs deleted when the job ends, result downloadable once. | A privacy switch for jobs that use real faces or voices. Our download-then-purge flow already fits, but our "download again on 410" retry would not work for incognito jobs. | Small |

---

## 6. Suggested order

1. ~~Approve 0.13.0~~ No longer needed (see section 1).
2. **Lip sync in the Talking character lab** (section 3): LTX-2.5 audio-to-video, the `lip_sync`
   switch, reading `lip_sync.applied`, skipping the purge when it failed. One migration
   (`lab_talk_run`), small API additions. Then the re-sync job and button.
3. **H3 in the Video lab** (`/videos/generate`, section 4.3): new model id and migration, request
   builder, `17n + 5` frame grid, H3 sizes, slot cost 2, H3 prompt profile. Measure real run times and
   memory on a few clips before offering it for scenes.
4. **H3 for project scenes** (section 4.4) with the short-scene fallback and soundscape-only prompts.
5. **H3 reference mode** in the Talking character lab (section 4.7), then test cast reference images.
6. From section 5, in order of value for effort: partitions display, TBDub re-voice, retake,
   text-to-audio SFX, RVC, Wan-Animate.

---

## 7. Open questions

- **Model id for H3:** `minimax-h3` (used above) or `h3`? It ends up in the database, the settings and
  the API, so it is worth fixing once.
- **Lip sync default:** off by default (as proposed: it adds minutes and fails on faces without a
  mouth, like the robots in `test.json`), or on for the Talking character lab?
- **Failed lip sync:** keep the server job for a manual retry (proposed), or retry once automatically
  with TBDub before storing?
- **Licence:** where will H3 output be published? That decides whether H3 can be offered at all.
- **H3 in scenes:** fall back to LTX-2.5 for short first-and-last scenes (proposed), or force
  `min_scene_seconds >= 5.2` on projects that use H3?

---

## 8. 0.14 / 0.15: optional audio, a list of audios, GPUs and an estimate from the server (done)

Read on 2026-10-18 from `GET /v1/guide?format=json` (`api_version` 0.15.0).

### 8.1 What changed upstream

| Change | Version | Effect |
|---|---|---|
| `audio_asset_id` (one) became **`audio_asset_ids`** (a list, up to 3) on `POST /v1/h3/videos/audio-to-video`. The old field is rejected with 422. | 0.14 | Every H3 reference request we sent before would now fail. This was a **required fix**, not only a feature. |
| **Audio is optional.** At least one of `image_asset_ids` (up to 9) or `video_asset_ids` (up to 3) is needed; 12 references in all. | 0.14 | Pictures alone are enough. With pictures only, the prompt defines one `<Subject N>` per character or place and has no `<Audio N>` lines. |
| `match_audio_duration` needs at least one audio and measures `audio_asset_ids[0]`. | 0.14 | Without an audio, the length is sent instead. |
| **`gpus`** (4 or 8 for H3, null for other jobs) and **`estimated_run_seconds`** (queue wait not included) on the submit answer and on `GET /v1/jobs/{id}`. | 0.15 | The server says what a job takes. The guide says to prefer it over `typical_run_seconds`. A request too big for the server is refused with 422 and one sentence. |

### 8.2 What the app does now

| Where | Change |
|---|---|
| `providers/gpu_server.py` | `submit()` returns a `SubmitAnswer` (`job_id`, `gpus`, `estimated_run_seconds`). `job_status()` reads both fields. `submit_job()` still returns just the id for callers that want only that. |
| `providers/video_generator.py` | `with_h3_references` sends `audio_asset_ids`, and only when there is an audio. |
| `jobs/generate_lab_video.py`, `jobs/generate_clip.py` | Save the submit answer on the job's input (`submit_answer`). The lab handler uploads 0 to 2 audios, in order, and no longer needs one. |
| `jobs/pools.py` | `slot_cost`: a H3 job counts the GPUs the server reported (from the job's `output.remote` once running, else from `submit_answer`), 4 before the server has said, any other GPU job 1. The local "H3 = 2" figure is gone. |
| `lab_video_run.audio_references` (migration `0020`) | A JSON list of the audios of a run, filled from `audio_input` for old runs. `audio_input` still holds the first one. |
| `POST /api/lab/videos/reference-runs` | `audios` (0 to 2), `audio_owners`, `reference_roles` and `ambience` (up to 1,000 characters). The server checks: a voice needs its character's picture, and at most two voices. |
| `LabVideoRunOut` | `audio_references`, `gpus`, `estimated_run_seconds`. |
| `CharacterReferenceOut` | `lab_image_id`, so the Video lab can use a library character's picture. |
| Video lab form | Character 1, Character 2 (optional), Scene, Ambience and Other pictures. Each character has a name, a description and an optional voice. The six-part prompt is made from them, and is the author's to edit. The run list shows "The server says: 4 GPUs, about 12 min to run" once the server has answered. |

### 8.3 Left out on purpose

Reference videos (`video_asset_ids`, `<Video N>`) and a third audio. The form is for one or two characters
in a scene, and these would only add choices. The Character lab's takes send a single audio, as before,
through the list field.

### 8.4 Notes

- **Approval is not needed** (section 1). The first GPU job after the update records the 0.15 API and
  the Settings banner shows the change; approving it is an optional review.
- **Migration `0020`** runs by itself when the backend container starts (`alembic upgrade head`).
- A **front picture on a white backdrop** is what a library character gives. That white may show up
  as the clip's background unless a scene picture or the prompt sets the place. This has **not been
  tested** here: try it, and tell the model in `retention_analysis` what is kept.

---

## Appendix: how this was checked

- Live documents: `GET /openapi.json` and `GET /v1/guide?format=json` on the gateway (0.13.0).
- Baseline: the latest approved `openapi` and `guide` rows in `api_snapshot` (0.12.0), read from
  `/data/app.db` in read-only mode.
- Compared operations by `METHOD path`, schemas by name, and the guide's markdown with a line diff.
  The guide's own changelog entries for 0.12.0 and 0.13.0 match what the diff shows.
- Code references are to the working tree as of this date, including uncommitted changes.
