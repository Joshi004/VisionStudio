# Visio Studio: Database Structure

Status: Derived from `ANALYSIS.md` (originally Revision 3, now updated for Revision 4's transcription findings), specifically Section 4 ("Database and data model"), cross-referenced with Sections 3.7, 4.4, 5.1, 5.2 and 6.5 for field-level detail. No code or migrations exist yet — this document turns the "draft data model" in `ANALYSIS.md` Section 4.3 into a complete, implementable structure.

**Update (2026-10-05):** `ANALYSIS.md` Revision 4 confirmed the transcription endpoint's real response shape against the live GPU server. Section 4.3 (`transcript` table) and the JSON shapes in Section 5 below are updated accordingly — `transcript.words` now holds the whole verified response object, not a guessed-at array.

**Update (Phase 6, 2026-10-06):** no schema change. Section 5 now documents the `plan_scenes` job's `input` (it carries the cache key `input_hash` and what the scenes were made from) and `output` (the model's answer is kept verbatim in `output.answer`, next to the attempts, the token usage and the check counts), and Section 7 says how scenes are replaced. The cache key lives in `job.input`, not in a new column.

**Update (Phase 9, 2026-10-06):** no schema change. Section 5 now documents the real `generate_clip` `input` and `output` (the request is built once and stored, and every later attempt sends it again) and the `asset.provenance` of a clip and of a derived frame, and Section 7 says how a clip, its take and its selection are written. A *take* is a succeeded `generate_clip` job together with its clip asset: there is still no clip table.

**Update (Phase 12, 2026-10-08):** migration `0003`. A new job type, `draft_descriptions` (a paid call to the language model that writes every scene's video prompt and its first and last frame descriptions in one request). `project` gains `description_instructions`. `scene` gains `first_frame_description`, `last_frame_description`, `frame_descriptions_source` and `description_job_id` (the job that wrote the AI text). Section 5 documents the job's `input` and `output`, and Section 7 says how the drafts are written and which fields they may overwrite.

**Update (Phase 13, 2026-10-08):** migration `0004`. Two tables for the Image lab page, where Bitdeer's image API is tested by hand: `lab_run` (one call: the exact request, the raw response, timing and usage) and `lab_image` (an upload, or a result of a run). They belong to no project. Nothing existing changes. See Sections 4.8, 4.9 and 7.

**Update (Phase 15, 2026-10-08):** migration `0005`. `scene.frame_descriptions_source` (one source for the pair) is replaced by `first_frame_description_source` and `last_frame_description_source`, copied from the old column wherever the text exists. The AI drafting job no longer writes a last-frame description (a clip is made from its first frame alone): it writes the video prompt and the first-frame description, and clears an earlier AI-written last-frame description in the scenes it writes into. The prompt profile is now `ltx-2.3-first-frame`, and the `world` and `continuity` values in the job's answer changed. See Sections 4.4, 5 and 7.

**Update (Phase 16, 2026-10-08):** migration `0006`. A new job type, `write_image_prompt`: one paid call to the language model for one scene (a scene job, `scene_id` set), which turns the scene's first-frame description, video prompt, narration and the draft's `world` into a detailed prompt for the image model. `scene` gains `image_prompt`, `image_prompt_source` and `image_prompt_job_id` (the job that wrote the AI text). Whether an AI prompt is out of date is computed when it is read, from a hash of its inputs kept on that job (`job.input.inputs_sha256`): no flag is stored. A new global setting, `image_prompt_llm_model`. See Sections 3, 4.4, 4.5, 5, 6 and 7.

**Update (Phase 17, 2026-10-08):** migration `0007`. A new job type, `generate_frame`, and a new job provider, `image`: one paid image from the image model (Seedream through Bitdeer) for one scene (a scene job, `scene_id` set). Its result is an `asset` (`kind='frame'`, `source='ai'`) that becomes the scene's first frame, and the raw image the model returned is kept as a second asset. **No table or column is added**: the frame is a normal asset, `scene.first_frame_asset_id` already points at it, and the scene's earlier frames are the result frames of its succeeded `generate_frame` jobs (no list is stored). Whether an AI frame is out of date is computed when it is read, from the prompt its provenance recorded. Two new global settings, `image_model` and `max_parallel_image_generations` (the second was replaced by the shared `max_parallel_gpu_jobs` on 2026-10-13, see below). See Sections 4.2, 4.5, 5, 6 and 7.

**Update (Phase 18, 2026-10-09):** no schema change. A new global setting, `default_negative_prompt` (a text for the video model: no background music, singing or speech, no on-screen text, logos or watermarks, and common video artifacts). A `generate_clip` job sends the project's own `negative_prompt` when it has one, otherwise this default, and a new project starts with this text as its own `negative_prompt`. Before this, a project with a blank `negative_prompt` sent none, and the GPU server's own default applied. See Sections 4.1, 5 and 6.

**Update (Phase 19, 2026-10-09):** migration `0008`. LTX-2.5 runs next to LTX-2.3, and the video model is chosen per app, project and scene. `project` and `scene` gain a nullable `video_model` (`ltx-2.3` or `ltx-2.5`; NULL means "inherit": the scene takes the project's, the project takes the global setting `default_video_model`). **`job.project_id` becomes nullable** and `job.type` gains `lab_video` and `write_lab_video_prompt`: the new Video lab belongs to no project, and its jobs are normal background jobs. A new table, `lab_video_run`, holds what the Video lab lists and compares (the model, the prompt, the settings, and the stored clip). A clip's job and asset record which model made it. No `negative_prompt` is sent to LTX-2.5 (it has none), so the project's and the global negative prompts are LTX-2.3 only. See Sections 3, 4.1, 4.4, 4.5, 4.10, 5, 6 and 7.

**Update (Phase 20, 2026-10-09):** migration `0009`. A new job type, `auto_pipeline`: one run of the automatic flow of a project, which makes the jobs of the manual steps one step after the other and starts a step only when every scene has finished the one before. **No table or column is added**: the run keeps its state in `job.input` and `job.output` (including the ids of the jobs it made, so a restart continues where it was), and only the `job.type` CHECK gains the new value. A run is a project job (`scene_id` is NULL, `provider='local'`) and keeps a fixed marker in `provider_job_id` so the dispatcher checks it every tick. Its jobs are ordinary jobs of the existing types, with `input.auto_run_id` naming the run. See Sections 4.5, 5 and 7.

**Update (Phase 21, 2026-10-10):** migration `0010`. Two things from the GPU API 0.5.0 to 0.7.0. (1) **LTX-2.5 first-and-last-frame**: `POST /v1/ltx25/videos/interpolate` replaces the fallback to LTX-2.3, so a scene with a last frame is made by the chosen model's own endpoint (`first_frame_asset_id` and `last_frame_asset_id` in the body, no `negative_prompt`), and the Video lab can take an optional last frame (`lab_video_run.last_frame`). (2) **Breeze TTS 2 text-to-speech** (`POST /v1/breeze-tts/synthesize`): `job.type` gains `lab_voice` and `generate_voiceover`; new tables `voice` (a saved voice: a recording and its exact transcript) and `lab_voice_run` (what the new Voice lab lists); `project.voice_id` names the saved voice that speaks the script when the app makes the voiceover (`asset.kind='voiceover'`, `asset.source='ai'`, with `provenance.script_sha256`). The automatic flow gains a first step, `voiceover`. Breeze TTS 2 is licensed for research and non-commercial use only. See Sections 3, 4.1, 4.5, 4.10, 4.11, 4.12, 5 and 7.

**Update (Phase 22, 2026-10-11):** migration `0011`. The image model changes from Seedream (Bitdeer) to **Qwen-Image-2.1 on the GPU server** (`POST /v1/qwen-image21/images/generate`, added in GPU API 0.8.0). (1) `generate_frame` becomes a remote GPU job like `generate_clip` (`provider='gpu'`, restart rule `resume`, a `provider_job_id`, polled by the dispatcher) instead of one synchronous paid call. Its stored request holds the nearest of the model's seven picture shapes, a random seed and the mode (the new global setting `image_mode`, which replaces `image_model`). The label-band crop is gone: the frame is the model's picture scaled to cover the generation size and trimmed evenly. The `image` value stays in the `provider` CHECK, but no job uses it any more. (2) The Image lab gets Qwen next to Seedream. A Qwen run is a `lab_image` job (`job.type` gains `lab_image`), and `lab_run` gains a nullable `job_id` and the status `running`; Seedream runs are unchanged. (3) The prompt profile the language model writes image prompts with is now `qwen-image-2.1` (150 to 300 words, no "bottom tenth" rule). The model's weights are under the Qwen Research License (non-commercial use only). See Sections 4.5, 4.8, 5, 6 and 7.

**Update (Phase 23, 2026-10-11):** migration `0012`. **AI last frames**, so a clip can be made from a first and a last frame (the LTX first-and-last-frame endpoints already existed). (1) `job.type` gains `write_last_frame_prompt` (a paid call to the language model for one scene) and `generate_last_frame` (a remote GPU job for one scene, like `generate_frame`). (2) `scene` gains `last_frame_prompt`, `last_frame_prompt_source` and `last_frame_prompt_job_id`, the counterparts of the three `image_prompt` columns: the instruction that **edits the first frame into the last frame** with Qwen-Image-2.1's edit endpoint (`POST /v1/qwen-image21/images/edit`, with the first frame uploaded as a reference image). (3) The drafting job's prompt profile is now `ltx-first-last`: the model decides, scene by scene, whether the clip gets a last frame and writes its description into `scene.last_frame_description` (source `ai`), or answers null. **No column is added for the frame itself**: it is a normal frame asset, `scene.last_frame_asset_id` already points at it, and the earlier last frames of a scene are the result frames of its succeeded `generate_last_frame` jobs. Whether an AI last frame is out of date is computed (its prompt, or the first frame it edited, changed), never stored. (4) A scene whose draft `continuity` is `continues_action`, after a scene that has a last frame, **starts on that frame**: the app sets its `first_frame_asset_id` to the previous scene's last frame (the same asset row), in the transaction that attaches it. (5) The automatic run has two more steps, `last_frame_prompts` and `last_frames`. See Sections 3, 4.4, 4.5, 5 and 7.

**Update (Phase 24, 2026-10-11):** migration `0013`. **The Talking character lab**: a character picture speaks a line of dialogue, lip-synced, and the three labs become tabs of one Lab page (no schema change for that part). (1) The GPU server's audio-to-video endpoint (`POST /v1/ltx/videos/audio-to-video`, `AudioToVideoRequest`, LTX-2.3, quality recipe only) makes a clip to match a recorded speech and muxes that speech in unchanged. It is a `lab_video` job like any other Video lab run, and `lab_video_run` gains `audio_input` (`{"source": "voice_run" \| "voice", "id": n}`, NULL for every other clip); the job's input also carries `audio` (the file's path and type, copied when the run starts). The clip is as long as the speech (the smallest `8k + 1` frame count that is not shorter, at most 20 seconds). (2) `job.type` gains `write_talk_prompts` (a paid call to the language model that writes a voice instruction and a video prompt). (3) New tables `lab_character` (the cast: a name, a picture, a description the language model reads, an optional default voice) and `lab_talk_run` (one take: the dialogue, the picture, the prompts, and the three steps it is made in, each a job the other labs already run: `prompt_job_id`, `voice_run_id`, `video_run_id`). A take with `auto_continue` starts its next step by itself when the prompts job finishes and when the speech is stored; if a step cannot start, the reason is kept in `lab_talk_run.last_error`. See Sections 3, 4.10, 4.13, 4.14 and 5.

**Update (project cast, 2026-10-12):** migration `0014`. **A project's cast, so a character or a place looks the same in every scene.** (1) New tables `character` and `location` (Sections 4.15 and 4.16): the characters and places of a story, each with the text that describes it (found by one language model job that reads the script, edited by hand), the prompt for its **reference picture** and the picture itself. (2) `scene` gains `character_id` and `location_id` (the one character and the one place the scene shows; `character_id` is replaced by the table `scene_character` in migration `0015`, below), `cast_assignment_source` (`manual` \| `ai`) and `cast_assignment_job_id`. (3) `asset.kind` gains `reference` (a reference picture). (4) `job.type` gains `extract_cast`, `write_character_reference_prompt`, `generate_character_reference` and `assign_cast`. (5) A scene that shows a member has its first frame made by **the image model's edit endpoint, from the picture of each member** (the character is image 1, the place the next), instead of from words alone; the image prompt of such a scene is written for that (`QWEN_IMAGE_21_CHARACTER_EDIT`), and it carries the members in its inputs, so assigning a scene differently makes its prompt out of date. A scene that shows none is made as before. (6) A character's picture is asked for on a plain **white** backdrop, which is then removed (`rembg`), so the stored picture has a transparent backdrop; a place is kept whole. It is sent to the image model flattened on white again. (7) The automatic run has four more steps, between `scenes` and `descriptions`: `cast`, `cast_prompts`, `cast_images` and `cast_assignment`. (8) A scene's choice of cast counts as one of its inputs (`scene_cuts.has_inputs` and `NO_INPUTS`): replacing a scene, or changing its cut, asks first and then clears the choice, like a description or a frame. Nothing speaks in these stories: a character's voice is only a note for the language model. See Sections 3, 4.2, 4.4, 4.5, 4.15, 4.16, 5 and 7.

**Update (several characters in a scene, 2026-10-13):** migration `0015`. **A scene may show any number of characters.** (1) New table `scene_character` (Section 4.17): one row for each character a scene shows, with its `position` (the order of the character's reference picture: 0 is image 1). (2) `scene.character_id` is dropped. Every existing choice is copied into `scene_character` at position 0 first, so none is lost. (3) A scene made from the cast sends one reference picture for each character (images 1, 2, and so on, in `position` order) and then the place's. The image model's edit takes 10 pictures, so a scene shows at most **9** characters (`cast.MAX_SCENE_CHARACTERS`): code applies this limit (the `assign_cast` answer is cut there, a manual choice above it is refused with 422), and no prompt asks for any number of characters. (4) The prompts leave the number of characters to the model: `assign_cast` now answers with a list of names (`characters`) for each scene, and the profile `QWEN_IMAGE_21_CHARACTER_EDIT` (version 2) names each character by its image number. A character's entry in `cast.references` of the image prompt's inputs gains `name`, so the writer can tell several characters apart: the image prompts of scenes that show a character are therefore out of date once. (5) `NO_INPUTS` no longer holds `character_id`. A cut edit that clears a scene's inputs also deletes the scene's `scene_character` rows (`scenes.apply_cut_edit`). See Sections 3, 4.4, 4.17, 5 and 7.

**Update (parallel automatic run and two shared pools, 2026-10-13):** **No table or column is added.** (1) The automatic run (`auto_pipeline`) is no longer a queue of fourteen steps done one after the other: the steps are a graph. A step starts when the steps it *needs* are complete, and a scene (or a character, or a place) goes on to its next step as soon as its *own* input is ready (for example, a clip starts once its scene's frames are made, while other scenes' frames are still being made). The cast is found from the script at once, beside the voiceover. `job.output` of a run no longer has a `step` key (an older run's is ignored), and `problems[]` always had a `step`. (2) The per-job-type limits are gone. Two numbers limit all work, shared by every kind of job: `max_parallel_gpu_jobs` (the GPU server) and `max_parallel_paid_api_calls` (the paid inference API). They replace `max_parallel_generations` and `max_parallel_image_generations` (a saved value of either is never read), and there is no concurrency group any more. A new endpoint, `GET /api/jobs/capacity`, reports each pool's limit and what is running and waiting in it. See Sections 3.3, 4.5, 6 and 7.

**Update (MiniMax H3 reference: optional audio, a cast and the server's own GPUs and estimate, 2026-10-18):** migration `0020`, for GPU API 0.14.0 and 0.15.0. (1) `lab_video_run` gains `audio_references` (a list of `{"source": "voice_run" \| "voice", "id": n}`, in `<Audio N>` order; NULL for every other clip and for a reference clip made without audio). The audio of a MiniMax H3 reference clip is **optional** (0 to 2 audios in the Video lab, the server takes 3): the request field is the list `audio_asset_ids`, and the old single `audio_asset_id` is refused by the server. Runs made before the migration get a list of the one audio they had. `audio_input` stays, and for a reference clip holds the first audio (or NULL). (2) A reference run's `params` also hold `reference_roles` (what each picture is: `character_1`, `character_2`, `scene` or `other`), `audio_durations_s`, `audio_owners` (which character each audio is the voice of) and `ambience`, so a run loads back into the form. (3) The server now says how many GPUs a MiniMax H3 job got (`gpus`, 4 or 8) and about how long it will run once it starts (`estimated_run_seconds`), in its submit answer and in `GET /v1/jobs/{id}`. The app keeps both: `job.input.submit_answer` (`{gpus, estimated_run_seconds}`) at the submit and `job.output.remote` (refreshed at every poll). The dispatcher counts an H3 job as the server's `gpus` slots (4 until the server has said), instead of the fixed two. See Sections 4.10 and 6.

**Update (MiniMax H3 as a project, scene and app video model, and the default, 2026-10-18):** migration `0021`. `project.video_model` and `scene.video_model` accept `minimax-h3` as well as `ltx-2.3` and `ltx-2.5`: the two CHECK constraints are rebuilt (SQLite needs a table rebuild for that, which the migration does in batch mode), and no column is added. The downgrade first sets every `minimax-h3` value of those two columns to NULL ("inherit"), then puts the old constraints back. The `default_video_model` setting now defaults to `minimax-h3` **in the code only**: a value already saved is kept, so an install that saved `ltx-2.5` keeps it until the setting is changed. A clip made by MiniMax H3 is asked of one endpoint for both clip modes (`POST /v1/h3/videos/generate`), so its job `input` and its clip provenance also store the clip mode (`clip_mode`), which the endpoint alone no longer tells. It runs at 24 fps and in its own size (1344 x 768 or 768 x 1344), is never shorter than 124 frames (5.17 s) nor longer than 345 (14.4 s), and gets no negative prompt. A scene shorter than 5.17 s that has a last frame is made by LTX-2.5 instead (the clip's `model_note` says why). A scene's description drafted for H3 is one text of three fields (`integrated_multimodal_description`, `overall_soundscape`, `non_diegetic_music`), and `scene_prompt.prompt_for` turns either that or an LTX paragraph into the prompt of the model that makes the clip. The render timeline entries gain `source_frames`, the frames the clip needs at its own fps, so a 24 fps H3 clip in a project of another fps is not taken for too short. The `draft_descriptions` job input gains `video_model`, and its `profile` is `minimax-h3-scene` when the project's model is MiniMax H3. See Sections 3, 4.1, 4.4, 5, 6 and 7.

**Update (PHASE-002 shot-duration policy, 2026-10-20):** no schema change. Four new global settings in the `Shot duration` group, all integers in **whole seconds**: `h3_min_shot_seconds`, `shot_target_min_seconds`, `shot_target_max_seconds` and `h3_max_shot_seconds`. Each is between 1 and 14, where 14 is `H3_MAX_FRAMES // H3_FPS` (345 frames is 14.375 s, so 15 s is beyond what the GPU server accepts). They must stay in that order (each at or below the next): saving a value that breaks the order is refused, and `duration_policy.read_duration_policy` checks it again when it reads, because a reset can still break it. See Section 6.

**Update (PHASE-046 retire the narration pipeline, 2026-10-20):** migration `0022`. The voiceover-driven narration pipeline is removed, so later phases can build story projects without it. The Image lab, the Voice lab, the Video lab and the Character lab are unchanged. (1) `job` rows whose type is not one of the six lab types (`lab_image`, `lab_video`, `write_lab_video_prompt`, `lab_voice`, `write_character_look_prompt`, `write_character_take_prompt`) are deleted. `job.scene_id` and `idx_job_scene` are dropped, and the `job.type` CHECK is rebuilt with those six values (SQLite needs a table rebuild for that, which the migration does in batch mode). (2) The tables `scene_character`, `scene`, `character`, `location` and `transcript` are dropped. (3) `project` loses twelve columns: `min_scene_seconds`, `max_scene_seconds`, `style_prefix`, `prompt_suffix`, `negative_prompt`, `clip_sound_volume`, `cut_instructions`, `description_instructions`, `video_model`, `language`, `voiceover_asset_id` and `voice_id`, with the CHECK and the two foreign keys that went with them. What is left is `id`, `name`, `created_at`, `orientation`, the four sizes, `fps` and `script_text`. (4) The setting rows `default_video_model`, `default_negative_prompt` and `max_parallel_ffmpeg` are deleted, and the three are no longer settings. (5) `asset` is unchanged: its rows and files are never deleted, and its CHECK constraints keep every value, so a `voiceover`, `clip`, `final` or `reference` asset made earlier stays valid. (6) **There is no downgrade**: `downgrade()` raises `NotImplementedError`, because the deleted rows cannot be rebuilt. Restore a backup of `app.db`, or use the git tag `narration-final` (the last commit with the narration code, `git show narration-final:<path>`) with a database from before. Sections 4.3, 4.4, 4.15, 4.16 and 4.17 and the narration shapes of Section 5 are now short notes: the full text is at that tag (`git show narration-final:DATABASE_STRUCTURE.md`). The older updates above describe the schema as it was when each was written. See Sections 3, 4.1, 4.2, 4.5, 5, 6 and 7. Older than this phase and not changed by it: Sections 4.13 and 4.14 and the indexes of `lab_character` and `lab_talk_run` still describe the Talking character lab's first tables, which migration `0016` replaced with the Character lab's own tables (`library_character`, `character_look`, `character_look_candidate`, `character_reference` and `character_take`).

**Update (PHASE-003 story workspace, 2026-10-20):** no schema change and no migration. (1) The story is stored in the existing `project.script_text` column, which the app now calls the *story text* (the project page's "Story" editor); the column and the API field keep the name `script_text`. (2) Two new global settings in a new `Story` group: `story_words_per_minute` (default 150, from 60 to 300) and `story_max_minutes` (default 10, from 1 to 120, decision D-13). The estimated length of a story is its word count divided by the pace; a story above the limit still saves, with a warning. `GET /api/projects/{id}` (and the create and patch answers) gain `story_length` (`word_count`, `estimated_seconds`, `words_per_minute`, `limit_seconds`, `over_limit`), computed on read by `app/services/story_length.py`, never stored. (3) A new section 2.1, **Story artifact provenance (D-3)**, is the convention every later stage table follows. See Sections 2.1, 4.1, 6 and 7.

**Update (PHASE-004 Story Bible, 2026-10-20):** migration `0023`. The first story stage. (1) New table `story_bible` (Section 4.18): one immutable row per version of a project's StoryBible, following the provenance convention of Section 2.1 (`source`, `job_id`, `version`, `inputs`, `created_at`) plus `project_id` and `content` (the bible itself). `UNIQUE (project_id, version)`. (2) `job.type` gains `write_story_bible`: the CHECK is rebuilt in batch mode, so `job` now has seven types. Unlike the lab jobs, this one **belongs to a project** (`job.project_id` is set), with `provider='llm'` and the restart rule `never_rerun`; its `input` and `output` are in Section 5. (3) The settings `llm_provider` and `llm_model`, which nothing used since PHASE-046, become **the one story LLM setting** (labels "Story provider" and "Story model (Bitdeer)"): every story stage uses them (decision D-12). The built-in default model changes from `zai-org/GLM-5.3-Flash` to `zai-org/GLM-5.3`; a value already saved is kept. While Bitdeer is not available, `llm_provider` is set to `qwen38` on the Settings page (a temporary test setup, not a code change). (4) New endpoints under `/api/projects/{id}/story-bible` (run, read, read one version). Whether the newest version is out of date is **computed on every read** from `inputs.story_sha256` and the project's current `script_text`, never stored. See Sections 2.1, 3, 4.5, 4.18, 5, 6 and 7.

**Update (PHASE-005 character and environment discovery, 2026-10-20):** migration `0024`. The second and third story stages: two focused calls that list the story's characters and its environments. (1) Two new tables, `character_discovery` and `environment_discovery` (Sections 4.19 and 4.20). Each is the shape of `story_bible`: one immutable row per run, which is one **version of the whole list** (the set carries the version, the provenance and the `content`; there is no row per character), following Section 2.1. `inputs` records the story hash **and the StoryBible version the list was made from** (`artifacts: [{"kind": "story_bible", "id", "version"}]`). `UNIQUE (project_id, version)` in each table, so the two lists are numbered separately. (2) `job.type` gains `discover_characters` and `discover_environments`: the CHECK is rebuilt in batch mode, so `job` now has nine types. They are **two job types and not one with a kind**, because the job store merges a second click into any waiting or running job of the same type for the project, so a single type would make the character run block the environment run; with two, both run at once (and beside scene discovery of PHASE-006, D-15). Both belong to a project, are `provider='llm'` with the restart rule `never_rerun`, and use the story model setting (D-12). (3) No setting is added. (4) New endpoints under `/api/projects/{id}/discovery/{kind}` (`kind` is `characters` or `environments`: run, read, read one version). A run is refused (422) when there is no saved story, no StoryBible, or when the newest StoryBible is out of date with the saved story. Whether the newest version of a list is out of date is **computed on every read**: the story text hashes differently from `inputs.story_sha256`, or the project has a newer StoryBible than the one recorded. Relations between characters are not stored (D-14). See Sections 3, 4.5, 4.19, 4.20, 5 and 7.

**Update (PHASE-006 scene discovery, 2026-10-20):** migration `0025`. The fourth story stage: the story divided into its scenes, **each scene tied to the exact slice of the author's story it owns**. (1) New table `scene_discovery` (Section 4.21): the same shape as `character_discovery`, one immutable row per run, which is one version of the whole scene list, following Section 2.1; `inputs` records the story hash and the StoryBible version it read. `UNIQUE (project_id, version)`. Each scene in `content` has `index`, `id`, `title`, `description`, `starts_with`, `start`, `end` and `text`. **The model gives only `id`, `title`, `description` and `starts_with`** (the scene's opening words, copied from the story); **code sets the rest**: scene 1 starts at character 0, every later scene starts at the word where its opening words are found, each scene ends where the next begins and the last ends at the end of the story, and `text` is `story[start:end]`. So the scenes' texts joined in order are the whole story, byte for byte, with no gap, overlap or skipped word. Scenes carry **no character or environment ids** (D-15). (2) `job.type` gains `discover_scenes`: the CHECK is rebuilt in batch mode, so `job` now has ten types. It is its own job type, so it runs beside the two PHASE-005 discovery jobs. It belongs to a project, is `provider='llm'` with the restart rule `never_rerun`, and uses the story model setting (D-12). (3) No setting is added. (4) New endpoints under `/api/projects/{id}/scenes` (run, read, read one version). A run is refused (422) on the same conditions as the PHASE-005 runs: no saved story, no StoryBible, or a StoryBible out of date with the story. Whether the newest version is out of date is **computed on every read**, as for the lists of PHASE-005. See Sections 3, 4.5, 4.21, 5 and 7.

**Update (PHASE-007 character versioning, 2026-10-20):** migration `0026`. Every production-relevant change of a library character is kept as an **immutable version**, so a project can later pin one (PHASE-008). (1) New table `library_character_version` (Section 4.27): one row per version, never changed once written, numbered from 1 per character (`UNIQUE (character_id, version)`). It freezes the character's `profile` (twelve fields), its voice (`voice_id`, `voice_description`) and its current look: `look_id` plus `look_references`, the exact picture of every angle at that moment, so redoing an angle later (which updates `character_reference` in place) cannot change an old version. `library_character` stays the editable head. It follows the provenance convention of Section 2.1 where it applies (`source`, `version`, `created_at`); there is no job and no upstream artifact, and `source` is `manual` for every change made in the lab. (2) `character_take` gains a nullable `character_version`: the character's newest version when the take was made. (3) A version is added by `services/character_versions.record_version_if_changed` when the profile changes, when the voice or the voice description changes, when a look turns ready (it becomes the current look), and when an earlier ready look is made current again (`PUT /api/lab/characters/{id}/current-look`). A save that changes nothing adds no version, and archiving is not a version change. While the current look is being redone, the newest version's look part is carried forward; the redo adds its own version once the look is ready again. (4) No `job.type` change, so `job` is not rebuilt. No backfill: a character made before this migration has no version until its next change, which writes version 1. (5) **Documentation catch-up:** the Character lab's tables, which migration `0016` and later added without documentation, are now described in Sections 4.22 to 4.26; Sections 4.13 and 4.14 (the tables `0016` replaced) say so. See Sections 3, 4.22 to 4.27 and 7.

**Update (PHASE-008 character links, 2026-10-20):** migration `0027`. A story project's discovered characters are **backed by library characters, and the project pins one version of each**. (1) New table `project_character_link` (Section 4.28): one row per linked discovered character, found by `(project_id, discovery_id)` (`discovery_id` is the slug `id` inside `character_discovery.content`, the only thing that ties a link to the list, so a re-run of discovery that keeps an id keeps its link). It names the library character (`character_id`), the **pinned version** (`pinned_version`, a plain number, found by `(character_id, pinned_version)` in `library_character_version`), `how` (`created` or `mapped`) and `discovery_version` (the list version it was linked from). `UNIQUE (project_id, discovery_id)` and `UNIQUE (project_id, character_id)`: a discovered character is linked once, and a project uses a library character for one entry only. (2) `library_character` gains the nullable `origin_project_id` (FK → `project.id`, `SET NULL`) and `origin_discovery_id`, which mark a character the pipeline made for a project. (3) **A pin never moves because of a lab edit.** "A newer version is available" is computed on read (`newest version > pinned_version`) and never stored. (4) A pipeline-made character is created with its `name` from the discovery, its `notes` from the one-line description, and an **empty `species` and `appearance`** until PHASE-009 writes them; its version 1 has `source='ai'`. `character_card` leaves those two lines out when empty. (5) No `job.type` change: every link action is a synchronous database write, so `job` is not rebuilt. No backfill. See Sections 3, 4.22, 4.28 and 7.

**Update (PHASE-009 character definition, 2026-10-20):** migration `0028`. The fifth story stage: **one model call per linked character writes its structured definition** (`Path_ahead.md` Section 11), which is saved on the library character as a **new version that the project pins**. (1) `library_character` gains a nullable JSON `definition` (the character's current definition, Section 4.22). `library_character_version` gains `definition` (the definition frozen in that version), `job_id` (FK → `job.id`, `SET NULL`: the job that wrote the version; NULL for a manual one) and `inputs` (the D-3 inputs of Section 2.1: the story hash and the StoryBible and character-list versions the definition was made from; NULL for a manual one) (Section 4.27). The definition holds `visual_identity`, `default_wardrobe`, `voice_identity`, `behavior` and `era` (the shape is in Section 5). (2) `job.type` gains `define_character`: the CHECK is rebuilt in batch mode, so `job` now has eleven types. It is **one job per character** (`input.discovery_id` names it), belongs to the project, is `provider='llm'` with the restart rule `never_rerun`, and uses the story model setting (D-12). `jobs/store.create_job` gained an optional `dedupe_key`: a second click for **the same character** returns that character's waiting or running job, while different characters' jobs run side by side when the pool allows. (3) A definition run **overwrites the lab profile fields it fills**: `age`, `gender`, `species`, `has_visible_mouth`, `appearance`, `outfit`, `personality`, `voice_description`, `era_kind`, `era_years` and `era_setting`; it never changes `name` or `notes`. The text written over stays readable in the earlier version. The new version has `source='ai'`, and **the project's pin moves to it** (the pipeline's own change: a lab edit never moves a pin). A later lab edit **carries the definition forward** into its own version, so a hand edit does not lose it. When `record_version_if_changed` is given `inputs`, it also compares them, so the same text made from newer inputs is a new version and the provenance stays current. (4) A character the user **chose from the library** (`project_character_link.how = 'mapped'`) is overwritten only after the request confirms it (`confirm_overwrite`), and "Define all" skips it. (5) Whether a definition is **out of date** is computed on every read from the pinned version's `inputs` (the story text, the newest StoryBible, and the entry's name and description in the list), never stored. (6) No setting is added. New endpoints under `/api/projects/{id}/character-definitions` (read, run all, run one). See Sections 2.1, 3, 4.5, 4.22, 4.27, 5 and 7.

**Update (PHASE-010 canonical character images, 2026-10-20):** migration `0029`. The sixth story stage: **each defined character gets its look made by the pipeline, with nobody choosing a master**, by reusing the Character Lab's look pipeline. (1) `character_look` gains `project_id` (FK → `project.id`, `SET NULL`, indexed by `idx_character_look_project`), `discovery_id` (TEXT, the slug of the discovered character in that project) and `inputs` (JSON, the D-3 provenance: `project_id`, `discovery_id`, `character_version` = the version the project pinned when the look started, and `definition_sha256` = a hash of the definition it was made from) (Section 4.23). All three are NULL for a look made by hand in the lab, and **a non-NULL `project_id` is what makes a look a pipeline look**. (2) **No job type is added and no table**: the work is the lab's own jobs (`write_character_look_prompt`, then `lab_image` runs). (3) A pipeline look makes **one candidate** (a lab look still makes four), and once that picture is stored the look takes it as its master itself (D-5), then makes the four other angles as before. (4) When a pipeline look turns `ready`, in the same transaction that sets the status, `library_character.current_look_id` is set, `library_character_version` gets the next version (`source='ai'`, `job_id` = the look's prompt job, `inputs` = the `inputs` of the version the project pinned, so the Character Definition stage still reads its definition as current) and **the project's pin moves to it** (the pipeline's own change). A look made in the lab still writes a `manual` version and **never moves a pin**; redoing an angle of a pipeline look writes a new `ai` version and moves the pin again. (5) Whether images are `failed` (the look's own status, or the job of its prompt, its candidate or an angle failed) or `out_of_date` (the definition now pinned differs from the one the look recorded) is **computed on every read**, never stored. (6) No setting is added. New endpoints under `/api/projects/{id}/character-images` (read, run all, run one). See Sections 4.23, 5 and 7.

**Update (PHASE-047 character relations, 2026-10-20):** migration `0030`. The project says who is the same person at another age, a twin, or family of whom, and the definitions and the images use it. (1) New table `character_relations` (Section 4.29): the shape of `character_discovery`, one immutable row per version of the project's whole list of relations, found by the `discover_relations` job (`source` `ai`) or saved by the user (`manual`), keyed by the discovery slug ids; **a library character never carries a relation** (D-14, amended). (2) `job.type` gains `discover_relations`: the CHECK is rebuilt in batch mode, so `job` now has twelve types. (3) `character_look.status` gains `waiting` (Section 4.23): a pipeline look for a same-face variant that waits for its base's images; no job exists until it starts. The CHECK is rebuilt in batch mode. (4) The `inputs` of a definition version gain `relations_sha256` and, when the project has relations, a `character_relations` artifact (Section 4.27); the `inputs` of a pipeline look gain `relation_kind`, `base` and `resemblance_sha256` (Section 4.23). A row made before this has none of them and reads as having no relations. The downgrade drops the table, deletes `discover_relations` jobs and `waiting` looks, and restores both CHECKs. No data is touched on upgrade. Section 7 has the new row.

**Update (PHASE-012 environment library, 2026-10-20):** migration `0032`. The Character Lab gets a library of **environments** (places) with versions and a canonical reference picture. (1) `job.type` gains `write_environment_prompt`: the CHECK is rebuilt in batch mode, so `job` now has fourteen types. It is a lab job (`project_id` NULL, `provider='llm'`) that writes the prompt of one reference picture. (2) Four new tables, all global (no `project_id`): `library_environment` (Section 4.31, the editable head), `library_environment_version` (Section 4.32, one immutable profile snapshot per version, with the canonical picture `reference_image_id` chosen for it), `environment_reference` (Section 4.33, one attempt to make a version's picture) and `environment_reference_candidate` (Section 4.34, the four candidate pictures of an attempt, each a `lab_run`). (3) **A version freezes its text and its picture together**: an edit adds the next version with **no** picture, and the older version keeps its own; only the **newest** version's picture can be chosen or replaced (**tightened in PHASE-013:** a newest version that a project pins and that already has its picture is frozen too). There is no foreign key from the head to a version: the newest version is the one with the highest `version`. No column of an existing table changed, and no data is moved. See Sections 4.31 to 4.34, 5 and 7.

**Update (PHASE-011 character and narrator voices, 2026-10-20):** migration `0031`. The seventh story stage: **each defined character, and the narrator, gets a saved voice made by the pipeline**, with nobody choosing a sample. (1) `job.type` gains `design_voice`: the CHECK is rebuilt in batch mode, so `job` now has thirteen types. One job writes one voice description (one paid call to the story model); in the same transaction that marks it succeeded it queues **one design-mode Voice lab run**. (2) `lab_voice_run` gains five nullable columns: `project_id` (FK → `project.id`, `SET NULL`, indexed), `subject` (`character` or `narrator`), `discovery_id` (the slug of the discovered character), `design_job_id` (FK → `job.id`, `SET NULL`: the `design_voice` job that wrote the description) and `inputs` (JSON, the D-3 inputs the voice is compared with). A run made by hand has none of the five (Section 4.12). (3) New table `narrator_voice` (Section 4.30): the shape of `story_bible`, one immutable row per derivation (`ai`) or hand choice (`manual`) of the project's narrator voice. (4) When the run's speech is stored, `lab_voice` calls `story_voices.on_voice_finished`, which saves the `voice` row from the run and, for a character, sets `library_character.voice_id`, adds a new `ai` `library_character_version` and moves the project's pin to it (the same way PHASE-010 does for a look). A character has **no** new column: the voice is the library character's own `voice_id`. "Out of date" is never stored: a character voice is compared by `inputs.voice_facts_sha256`, a derived narrator voice by `inputs.narration_sha256`. See Sections 4.2, 4.12, 4.30, 5 and 7.

**Update (PHASE-013 environment definition and project link, 2026-10-21):** migration `0033`. A story project's discovered environments are **backed by library environments, the project pins one version of each**, and the eighth story stage **defines each environment with one model call and makes its canonical reference picture by itself**. (1) New table `project_environment_link` (Section 4.35): the shape of `project_character_link`, one row per linked discovered environment, found by `(project_id, discovery_id)`, naming the library environment, the **pinned version** (a plain number), `how` (`created` or `mapped`) and `discovery_version`; `UNIQUE (project_id, discovery_id)` and `UNIQUE (project_id, environment_id)`. (2) `library_environment` gains `origin_project_id` (FK → `project.id`, `SET NULL`), `origin_discovery_id` and a nullable JSON `definition` (Section 4.31). `library_environment_version` gains `definition`, `job_id` (FK → `job.id`, `SET NULL`) and `inputs` (the D-3 provenance, Section 4.32). The definition is `Path_ahead.md` Section 13's (architecture, layout, `visual_identity`, `important_landmarks`, `atmosphere.baseline`, `continuity_rules`) plus a top-level `era`; the shape is in Section 5. (3) `environment_reference` gains `project_id` (FK → `project.id`, `SET NULL`, indexed by `idx_environment_reference_project`) and `discovery_id` (Section 4.33): **a non-NULL `project_id` makes an attempt a pipeline attempt**, which starts **one** candidate (a lab attempt still starts four) and takes it as the version's canonical picture itself (D-5). (4) `job.type` gains `define_environment`: the CHECK is rebuilt in batch mode, so `job` now has fifteen types. It is **one job per environment** (`input.discovery_id` names it, `dedupe_key`), belongs to the project, is `provider='llm'` with the restart rule `never_rerun`, and uses the story model setting (D-12). (5) A definition run **overwrites the lab profile fields it fills** (`description`, `atmosphere`, `era_kind`, `era_years`, `era_setting`) and never `name` or `notes`; the text written over stays readable in the earlier version. The new version has `source='ai'`, and **the project's pin moves to it** (the pipeline's own change: a lab edit never moves a pin). A later lab edit carries the definition forward. An environment the user **chose from the library** is overwritten only after the request confirms it (`confirm_overwrite`); **Define all** skips it, and skips one that is already defined and current. (6) A definition needs an **up-to-date list of scenes** (the model works out from it which scenes use the place, D-15), so a newer list of scenes marks a definition out of date. Whether a definition is **out of date** is computed on every read from the pinned version's `inputs`, never stored. (7) **The picture's freeze rule is tightened** (it was "only the newest version's picture can change" in PHASE-012): a version is frozen when it is not the newest, **or** a project pins it and it already has a picture. The picture prompt is now written from the attempt's own version, not the head. (8) No setting is added and no data is moved. The downgrade deletes every link and every `define_environment` job, drops the new columns and restores the `job.type` CHECK. New endpoints: `/api/projects/{id}/environment-links` (read, link all, create, map, unlink), `/api/projects/{id}/environment-definitions` (read, run all, run one, retry the picture) and `GET /api/lab/environments/{id}/projects`. See Sections 4.31 to 4.35, 5 and 7.

**How to read this document:** every table and field name is taken directly from `ANALYSIS.md`. Where `ANALYSIS.md` describes behaviour in prose but doesn't spell out a concrete SQL type, default, index, or constraint, I chose a simple, standard convention and marked it. **Section 8 ("Assumptions and additions beyond ANALYSIS.md") lists every one of those choices in one place** so you can confirm or correct them before anything is built. Nothing in Sections 1–7 should surprise you if you've read `ANALYSIS.md`; it's the same model, just made concrete.

---

## Contents

1. [Engine and tooling](#1-engine-and-tooling)
2. [Design principles behind the structure](#2-design-principles-behind-the-structure)
3. [Entity-relationship overview](#3-entity-relationship-overview)
4. [Tables](#4-tables)
5. [JSON column shapes](#5-json-column-shapes)
6. [Global settings stored in `setting`](#6-global-settings-stored-in-setting)
7. [How the pipeline writes to these tables](#7-how-the-pipeline-writes-to-these-tables)
8. [Assumptions and additions beyond ANALYSIS.md](#8-assumptions-and-additions-beyond-analysismd)

---

## 1. Engine and tooling

(Source: `ANALYSIS.md` Section 4.1)

- **SQLite** for iteration 1 — one file on the Docker `data` volume, no separate database container, no credentials. PostgreSQL is dropped because the reason for it (a separate worker process, and the database doubling as a job queue) no longer applies with one backend process and no queue table.
- **SQLAlchemy 2.x** for models, **Alembic** for migrations, so the code stays portable if you move to PostgreSQL later.
- **WAL mode and foreign keys** turned on (`PRAGMA journal_mode=WAL;` and `PRAGMA foreign_keys=ON;`).
- **JSON columns** (SQLAlchemy's `JSON` type) hold the exact request/response payloads sent to providers. SQLite has no native JSON storage class — these are stored as `TEXT` and serialized/validated by SQLAlchemy at the application layer.
- **Switch to PostgreSQL when:** you host it, add users, or run more than one backend process (Section 4.1). The cost is a connection-string change, running the same Alembic migrations against Postgres, and copying data.

---

## 2. Design principles behind the structure

(Source: `ANALYSIS.md` Section 4.2, "Manual-first, AI-ready")

- **An artifact is the same thing no matter who made it.** A frame is an `asset` row whether you uploaded it or a model generated it — only a `source` field changes.
- **Every unit of background work is a `job` row** (a lab image, a lab clip, a lab speech, a prompt written by the language model) holding its input and output, so the UI can show activity.
- The principles about scenes, clips and frames that used to be here described the narration pipeline, which migration `0022` removed (see the update at the top).

### 2.1 Story artifact provenance (D-3)

*Added in PHASE-003; decision D-3 in `Implementation_phases.md`.* This convention applies to every table that holds the result of a story stage (the Story Bible, the discovered characters, environments and scenes, the definitions, events, shots and so on), starting with PHASE-004. It does not change any table that exists today. A stage's own section in this document says which columns below it uses and fills in the stage-specific ones.

Every artifact row has these columns:

| Column | Type | Null | Meaning |
|---|---|---|---|
| `source` | TEXT | NOT NULL | `ai` or `manual` (`CHECK (source IN ('ai', 'manual'))`). Who wrote the content: the language model, or a person. |
| `job_id` | INTEGER | NULL | The `job` that produced it (`REFERENCES job(id) ON DELETE SET NULL`). NULL for a manual artifact. The job holds the attempts, the token usage and the model's raw answer. |
| `version` | INTEGER | NOT NULL | 1 for the first artifact, then 2, 3 and so on. Each regeneration or edit is a **new row** with the next version: a stored version is never changed, so anything built from it can still say exactly what it was built from. A stage may instead keep one row per artifact and a separate version table; its section says which. |
| `inputs` | JSON | NOT NULL | What the artifact was built from: `{"story_sha256": "<hex>", "artifacts": [{"kind": "story_bible", "id": 12, "version": 3}]}`. `story_sha256` is the SHA-256 of the exact `project.script_text` the stage read (the story text itself is not versioned). `artifacts` lists each upstream artifact by kind, id and version. Either part may be empty when the stage did not read it. |
| `created_at` | DATETIME | NOT NULL | When the row was written. |

```sql
-- The shape every stage table starts from (stage-specific columns are added to it).
source      TEXT     NOT NULL CHECK (source IN ('ai', 'manual')),
job_id      INTEGER  REFERENCES job(id) ON DELETE SET NULL,
version     INTEGER  NOT NULL,
inputs      JSON     NOT NULL,
created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
```

Rules that go with it:

- **Staleness is computed when an artifact is read, never stored as a flag.** An artifact is out of date when the story text now hashes to something other than its `story_sha256`, or when any upstream artifact in `inputs.artifacts` has a newer version than the one recorded. This is the same "worked out when read" rule the app already uses (for example `job.input.inputs_sha256`). PHASE-039 reads these records; nothing has to be added to old rows later.
- **AI output never overwrites a manual artifact.** An AI run writes a new version next to the manual one, and a person chooses to use it. Author text is only replaced by an explicit action of the user.
- **Where a stage needs more than one row per run** (for example a set of discovered characters), the rows of one run share the run's `version` and `inputs`, or the set has a parent row that carries them. The stage's section says which.

---

## 3. Entity-relationship overview

A `project` owns its `asset` rows and, from PHASE-004, its `story_bible` rows and, from PHASE-005, its `character_discovery` and `environment_discovery` rows and, from PHASE-006, its `scene_discovery` rows and, from PHASE-008, its `project_character_link` rows (each links one of its discovered characters to a library character and pins a version of it) and, from PHASE-013, its `project_environment_link` rows (the same for its discovered environments) and, from PHASE-047, its `character_relations` rows (the relations between its discovered characters) and, from PHASE-011, its `narrator_voice` rows (the versions of its narrator's voice). Every other table is global and holds no `project_id`, except `job`, whose `project_id` is nullable: the tables are `setting`, `api_snapshot`, and, from Phase 13, `lab_run` and `lab_image`, from Phase 19, `lab_video_run`, from Phase 21, `voice` and `lab_voice_run` (since PHASE-011 a run the story pipeline made for a project names that project in its nullable `project_id`), and the Character lab's own tables (`library_character`, `character_look`, `character_look_candidate`, `character_reference`, `character_take` and, from PHASE-007, `library_character_version`, and, from PHASE-012, `library_environment`, `library_environment_version`, `environment_reference` and `environment_reference_candidate`). They describe the app, the GPU server or a manual test, not one video. The labs' jobs are rows of `job` too, with a NULL `project_id` (Phase 19). Migration `0022` dropped the tables of the narration pipeline: `transcript`, `scene`, `character`, `location` and `scene_character`.

```mermaid
erDiagram
    PROJECT {
        integer id PK
        text orientation
    }
    ASSET {
        integer id PK
        integer project_id FK
        text kind
    }
    JOB {
        integer id PK
        integer project_id FK
        integer result_asset_id FK
    }
    SETTING {
        text key PK
    }
    API_SNAPSHOT {
        integer id PK
    }
    LAB_VIDEO_RUN {
        integer id PK
        integer job_id FK
    }
    STORY_BIBLE {
        integer id PK
        integer project_id FK
        integer job_id FK
    }
    CHARACTER_DISCOVERY {
        integer id PK
        integer project_id FK
        integer job_id FK
    }
    ENVIRONMENT_DISCOVERY {
        integer id PK
        integer project_id FK
        integer job_id FK
    }
    SCENE_DISCOVERY {
        integer id PK
        integer project_id FK
        integer job_id FK
    }
    LIBRARY_CHARACTER {
        integer id PK
        integer voice_id FK
        integer current_look_id FK
        integer origin_project_id FK
    }
    PROJECT_CHARACTER_LINK {
        integer id PK
        integer project_id FK
        integer character_id FK
        integer pinned_version
    }
    CHARACTER_LOOK {
        integer id PK
        integer character_id FK
    }
    LIBRARY_CHARACTER_VERSION {
        integer id PK
        integer character_id FK
        integer voice_id FK
        integer look_id FK
    }
    PROJECT_ENVIRONMENT_LINK {
        integer id PK
        integer project_id FK
        integer environment_id FK
        integer pinned_version
    }
    LIBRARY_ENVIRONMENT {
        integer id PK
        integer origin_project_id FK
    }
    LIBRARY_ENVIRONMENT_VERSION {
        integer id PK
        integer environment_id FK
        integer reference_image_id FK
        integer job_id FK
    }
    ENVIRONMENT_REFERENCE {
        integer id PK
        integer environment_id FK
        integer version_id FK
        integer prompt_job_id FK
        integer project_id FK
    }
    ENVIRONMENT_REFERENCE_CANDIDATE {
        integer id PK
        integer reference_id FK
        integer lab_run_id FK
    }

    PROJECT ||--o{ ASSET         : "owns"
    PROJECT ||--o{ JOB           : "owns"
    PROJECT ||--o{ STORY_BIBLE   : "owns"
    PROJECT ||--o{ CHARACTER_DISCOVERY   : "owns"
    PROJECT ||--o{ ENVIRONMENT_DISCOVERY : "owns"
    PROJECT ||--o{ SCENE_DISCOVERY       : "owns"
    PROJECT ||--o{ PROJECT_CHARACTER_LINK : "owns"
    LIBRARY_CHARACTER ||--o{ PROJECT_CHARACTER_LINK : "used by"
    PROJECT ||--o{ PROJECT_ENVIRONMENT_LINK : "owns"
    LIBRARY_ENVIRONMENT ||--o{ PROJECT_ENVIRONMENT_LINK : "used by"
    LIBRARY_ENVIRONMENT }o--o| PROJECT : "origin_project_id"
    LIBRARY_ENVIRONMENT_VERSION }o--o| JOB : "job_id"
    ENVIRONMENT_REFERENCE }o--o| PROJECT : "project_id"
    LIBRARY_CHARACTER }o--o| PROJECT : "origin_project_id"
    JOB     }o--o| ASSET         : "result_asset_id"
    LAB_VIDEO_RUN }o--o| JOB     : "job_id"
    STORY_BIBLE }o--o| JOB       : "job_id"
    CHARACTER_DISCOVERY   }o--o| JOB : "job_id"
    ENVIRONMENT_DISCOVERY }o--o| JOB : "job_id"
    SCENE_DISCOVERY       }o--o| JOB : "job_id"
    LIBRARY_CHARACTER ||--o{ CHARACTER_LOOK : "has looks"
    LIBRARY_CHARACTER ||--o{ LIBRARY_CHARACTER_VERSION : "has versions"
    LIBRARY_CHARACTER }o--o| CHARACTER_LOOK : "current_look_id"
    LIBRARY_CHARACTER_VERSION }o--o| CHARACTER_LOOK : "look_id"
    LIBRARY_ENVIRONMENT ||--o{ LIBRARY_ENVIRONMENT_VERSION : "has versions"
    LIBRARY_ENVIRONMENT ||--o{ ENVIRONMENT_REFERENCE : "has attempts"
    LIBRARY_ENVIRONMENT_VERSION ||--o{ ENVIRONMENT_REFERENCE : "made for"
    ENVIRONMENT_REFERENCE ||--o{ ENVIRONMENT_REFERENCE_CANDIDATE : "has candidates"
```

`SETTING` and `API_SNAPSHOT` have no edges to `PROJECT` — they are global, as described in Sections 3.7 and 6.5.

**Foreign keys, precisely** (the diagram above is a visual aid; this list is authoritative):

| From | Column | To | Nullable |
|---|---|---|---|
| `asset` | `project_id` | `project.id` | No |
| `job` | `project_id` | `project.id` | Yes: a lab job belongs to no project, so it is NULL (Phase 19). A story job (`write_story_bible`, PHASE-004) belongs to its project. |
| `job` | `result_asset_id` | `asset.id` | Yes (until the job succeeds) |
| `story_bible` | `project_id` | `project.id` | No (`CASCADE`). PHASE-004 |
| `story_bible` | `job_id` | `job.id` | Yes (the `write_story_bible` job that wrote the version; `SET NULL` if that job row is ever removed, and NULL for a manual version). PHASE-004 |
| `character_discovery` | `project_id` | `project.id` | No (`CASCADE`). PHASE-005 |
| `character_discovery` | `job_id` | `job.id` | Yes (the `discover_characters` job that wrote the version; `SET NULL` if that job row is ever removed, and NULL for a manual version). PHASE-005 |
| `character_relations` | `project_id` | `project.id` | No (`CASCADE`). PHASE-047 |
| `character_relations` | `job_id` | `job.id` | Yes (the `discover_relations` job that wrote the version; `SET NULL`, and NULL for a manual version). PHASE-047 |
| `environment_discovery` | `project_id` | `project.id` | No (`CASCADE`). PHASE-005 |
| `environment_discovery` | `job_id` | `job.id` | Yes (the `discover_environments` job that wrote the version; `SET NULL` if that job row is ever removed, and NULL for a manual version). PHASE-005 |
| `scene_discovery` | `project_id` | `project.id` | No (`CASCADE`). PHASE-006 |
| `scene_discovery` | `job_id` | `job.id` | Yes (the `discover_scenes` job that wrote the version; `SET NULL` if that job row is ever removed, and NULL for a manual version). PHASE-006 |
| `lab_video_run` | `job_id` | `job.id` | Yes (the `lab_video` job that makes the run's clip; `SET NULL` if that job row is ever removed). Phase 19 |
| `lab_voice_run` | `job_id` | `job.id` | Yes (the `lab_voice` job that makes the run's speech; `SET NULL` if that job row is ever removed). Phase 21 |
| `lab_voice_run` | `voice_id` | `voice.id` | Yes (the saved voice that read the text; `SET NULL`). Phase 21 |
| `lab_voice_run` | `project_id` | `project.id` | Yes (the project the pipeline made the sample for; `SET NULL`; NULL for a run made by hand). PHASE-011 |
| `lab_voice_run` | `design_job_id` | `job.id` | Yes (the `design_voice` job that wrote the description; `SET NULL`). PHASE-011 |
| `narrator_voice` | `project_id` | `project.id` | No (`CASCADE`). PHASE-011 |
| `narrator_voice` | `voice_id` | `voice.id` | Yes (the saved voice; `SET NULL`). PHASE-011 |
| `narrator_voice` | `job_id` | `job.id` | Yes (the `design_voice` job of an `ai` version; `SET NULL`; NULL for a manual one). PHASE-011 |
| `lab_character` | `voice_id` | `voice.id` | Yes (the character's default saved voice; `SET NULL`). Phase 24 |
| `lab_talk_run` | `character_id` | `lab_character.id` | Yes (the cast character the take started from; `SET NULL`). Phase 24 |
| `lab_talk_run` | `voice_id` | `voice.id` | Yes (the saved voice that reads the line; `SET NULL`). Phase 24 |
| `lab_talk_run` | `prompt_job_id` | `job.id` | Yes (the `write_talk_prompts` job; `SET NULL`). Phase 24 |
| `lab_talk_run` | `voice_run_id` | `lab_voice_run.id` | Yes (the speech the take made or reuses; `SET NULL`). Phase 24 |
| `lab_talk_run` | `video_run_id` | `lab_video_run.id` | Yes (the lip-synced clip; `SET NULL`). Phase 24 |

(The five rows above for `lab_character` and `lab_talk_run` describe the Talking character lab's first tables, which migration `0016` replaced by the Character lab's tables below; see Sections 4.13 and 4.14.)

The Character lab's own foreign keys (documented in PHASE-007; the tables are Sections 4.22 to 4.27):

| From | Column | To | Nullable |
|---|---|---|---|
| `library_character` | `voice_id` | `voice.id` | Yes (the character's saved voice; `SET NULL`) |
| `library_character` | `current_look_id` | `character_look.id` | Yes (the look new takes are made from; `SET NULL`) |
| `character_look` | `character_id` | `library_character.id` | No (`CASCADE`) |
| `character_look` | `prompt_job_id` | `job.id` | Yes (the `write_character_look_prompt` job; `SET NULL`) |
| `character_look` | `reference_image_id` | `lab_image.id` | Yes (the author's own picture the look was started from; `SET NULL`) |
| `character_look` | `project_id` | `project.id` | Yes (the project the story pipeline made the look for; `SET NULL`). PHASE-010 |
| `character_look_candidate` | `look_id` | `character_look.id` | No (`CASCADE`) |
| `character_look_candidate` | `lab_run_id` | `lab_run.id` | Yes (`SET NULL`) |
| `character_reference` | `look_id` | `character_look.id` | No (`CASCADE`) |
| `character_reference` | `lab_run_id` | `lab_run.id` | Yes (`SET NULL`) |
| `character_reference` | `lab_image_id` | `lab_image.id` | Yes (`SET NULL`) |
| `character_take` | `character_id` | `library_character.id` | No (`CASCADE`) |
| `character_take` | `look_id` | `character_look.id` | Yes (the look the take was made from; `SET NULL`) |
| `character_take` | `prompt_job_id` | `job.id` | Yes (`SET NULL`) |
| `character_take` | `image_run_id`, `last_frame_run_id` | `lab_run.id` | Yes (`SET NULL`) |
| `character_take` | `voice_run_id` | `lab_voice_run.id` | Yes (`SET NULL`) |
| `character_take` | `video_run_id` | `lab_video_run.id` | Yes (`SET NULL`) |
| `library_character_version` | `character_id` | `library_character.id` | No (`CASCADE`). PHASE-007 |
| `library_character_version` | `voice_id` | `voice.id` | Yes (the voice the version froze; `SET NULL`). PHASE-007 |
| `library_character_version` | `look_id` | `character_look.id` | Yes (the look the version froze; `SET NULL`). PHASE-007 |
| `library_character_version` | `job_id` | `job.id` | Yes (the `define_character` job that wrote the version; NULL for a manual version; `SET NULL`). PHASE-009 |
| `library_character` | `origin_project_id` | `project.id` | Yes (the project the pipeline made the character for; NULL for a character made in the lab; `SET NULL`). PHASE-008 |
| `project_character_link` | `project_id` | `project.id` | No (`CASCADE`). PHASE-008 |
| `project_character_link` | `character_id` | `library_character.id` | No (`CASCADE`). PHASE-008. The pinned version is **not** a foreign key: it is the number `pinned_version`, found by `(character_id, pinned_version)` |
| `project_environment_link` | `project_id` | `project.id` | No (`CASCADE`). PHASE-013 |
| `project_environment_link` | `environment_id` | `library_environment.id` | No (`CASCADE`). PHASE-013. The pinned version is **not** a foreign key: it is the number `pinned_version`, found by `(environment_id, pinned_version)` |
| `library_environment` | `origin_project_id` | `project.id` | Yes (the project the pipeline made this environment for; `SET NULL`). PHASE-013 |
| `library_environment_version` | `environment_id` | `library_environment.id` | No (`CASCADE`). PHASE-012 |
| `library_environment_version` | `reference_image_id` | `lab_image.id` | Yes (the canonical picture chosen for this version; `SET NULL`). PHASE-012 |
| `library_environment_version` | `job_id` | `job.id` | Yes (the `define_environment` job that wrote this version; `SET NULL`). PHASE-013 |
| `environment_reference` | `project_id` | `project.id` | Yes (the project whose pipeline made the attempt; `SET NULL`; a non-NULL value marks a pipeline attempt). PHASE-013 |
| `environment_reference` | `environment_id` | `library_environment.id` | No (`CASCADE`). PHASE-012 |
| `environment_reference` | `version_id` | `library_environment_version.id` | No (the version the attempt was made for; `CASCADE`). PHASE-012 |
| `environment_reference` | `prompt_job_id` | `job.id` | Yes (the `write_environment_prompt` job; `SET NULL`). PHASE-012 |
| `environment_reference_candidate` | `reference_id` | `environment_reference.id` | No (`CASCADE`). PHASE-012 |
| `environment_reference_candidate` | `lab_run_id` | `lab_run.id` | Yes (the text-to-image run that makes the candidate; `SET NULL`). PHASE-012 |

Migration `0022` also removed the circular references the narration tables created (`project.voiceover_asset_id` and `asset`, `scene.description_job_id` and `job.scene_id`, and the project cast's): none is left.

---

## 4. Tables

Each table below shows: its purpose, a column reference table, and illustrative SQL DDL (SQLite dialect). Model names below match the PascalCase names used in `ANALYSIS.md` Section 4.3; table names are the lowercase `snake_case` SQL identifiers I'm proposing for them (see Section 8).

### 4.1 `project`

One row per project. Since migration `0022` it holds only the name, the orientation and the sizes it is made at, the frame rate and an optional story text (`script_text`, shown as "Story" in the app). From PHASE-003 the project page is the story workspace: it edits the story text and shows its estimated length (Section 6, group `Story`). The story's own stage artifacts follow the convention in Section 2.1.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | INTEGER | NOT NULL | auto | Primary key |
| `name` | TEXT | NOT NULL | — | The project's name |
| `created_at` | DATETIME | NOT NULL | now | |
| `orientation` | TEXT | NOT NULL | — | `portrait` \| `landscape` — chosen first (decision 2) |
| `gen_width` | INTEGER | NOT NULL | from orientation | The size a clip is made at; multiple of 64 |
| `gen_height` | INTEGER | NOT NULL | from orientation | Same rule as `gen_width` |
| `out_width` | INTEGER | NOT NULL | from orientation | Final video width |
| `out_height` | INTEGER | NOT NULL | from orientation | Final video height |
| `fps` | INTEGER | NOT NULL | 24 | Frame rate |
| `script_text` | TEXT | NULL | — | The story text, kept exactly as pasted (no trimming); `NULL` until then, and when it is only whitespace. At most 100,000 characters. The column keeps its name; the app calls it the story |

```sql
CREATE TABLE project (
    id                 INTEGER PRIMARY KEY,
    name               TEXT NOT NULL,
    created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    orientation        TEXT NOT NULL CHECK (orientation IN ('portrait', 'landscape')),
    gen_width          INTEGER NOT NULL,
    gen_height         INTEGER NOT NULL,
    out_width          INTEGER NOT NULL,
    out_height         INTEGER NOT NULL,
    fps                INTEGER NOT NULL DEFAULT 24,
    script_text        TEXT
);
```

The twelve columns migration `0022` dropped (`min_scene_seconds`, `max_scene_seconds`, `style_prefix`, `prompt_suffix`, `negative_prompt`, `clip_sound_volume`, `cut_instructions`, `description_instructions`, `video_model`, `language`, `voiceover_asset_id`, `voice_id`) are documented at the tag `narration-final`.

### 4.2 `asset`

Any file on disk — uploaded or generated — that belongs to one project. The Image lab's project-frames picker reads a project's `frame` assets. Since migration `0022` no code writes an `asset` row (`services/assets.add_asset` stays for a later phase), and the table is unchanged: its CHECK constraints keep every `kind` and `source`, so a `voiceover`, `clip`, `final` or `reference` asset made earlier stays valid, and its file stays on disk. (Source: Section 4.2 and 4.3.)

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | INTEGER | NOT NULL | auto | Primary key |
| `project_id` | INTEGER, FK → `project.id` | NOT NULL | — | Owning project |
| `kind` | TEXT | NOT NULL | — | `voiceover` \| `frame` \| `clip` \| `final` \| `reference` (`reference`: the reference picture of a cast member of the retired narration pipeline) |
| `path` | TEXT | NOT NULL | — | Server-generated (UUID) path on the `data` volume |
| `mime` | TEXT | NOT NULL | — | MIME type |
| `size_bytes` | INTEGER | NOT NULL | — | File size |
| `duration_s` | REAL | NULL | — | Audio/video kinds only |
| `width` | INTEGER | NULL | — | Image/video kinds only. For an uploaded frame: the size as displayed, after the EXIF orientation is applied (Phase 8) |
| `height` | INTEGER | NULL | — | Image/video kinds only. Same rule as `width` |
| `sha256` | TEXT | NOT NULL | — | Content hash |
| `source` | TEXT | NOT NULL | — | `upload` \| `ai` \| `derived` |
| `provenance` | JSON | NULL | empty | provider/model/prompt/seed — empty (NULL) for uploads. An asset made earlier by a model keeps the provenance it was written with (Section 5) |
| `created_at` | DATETIME | NOT NULL | now | |

```sql
CREATE TABLE asset (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL CHECK (kind IN ('voiceover', 'frame', 'clip', 'final', 'reference')),
    path        TEXT NOT NULL,
    mime        TEXT NOT NULL,
    size_bytes  INTEGER NOT NULL,
    duration_s  REAL,
    width       INTEGER,
    height      INTEGER,
    sha256      TEXT NOT NULL,
    source      TEXT NOT NULL CHECK (source IN ('upload', 'ai', 'derived')),
    provenance  JSON,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### 4.3 `transcript`

**Removed in migration `0022`.** The table held the transcription endpoint's word times and the script words matched onto them. The full text of this section is at the tag `narration-final`.

### 4.4 `scene`

**Removed in migration `0022`.** The table held one cut of a story with its description, frames and chosen clip. The full text of this section is at the tag `narration-final`.

### 4.5 `job`

Every unit of background work. This is where running-job information lives, so a restart never loses track of a 5–10 minute GPU job. Since migration `0022` the only job types were the six lab ones, migration `0023` (PHASE-004) added the first story job, `write_story_bible`, migration `0024` (PHASE-005) added `discover_characters` and `discover_environments`, migration `0025` (PHASE-006) added `discover_scenes`, migration `0028` (PHASE-009) added `define_character`, migration `0030` (PHASE-047) added `discover_relations`, migration `0031` (PHASE-011) added `design_voice`, migration `0032` (PHASE-012) added `write_environment_prompt`, and migration `0033` (PHASE-013) added `define_environment`. (Source: Section 3.3, 4.2, 4.3.)

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | INTEGER | NOT NULL | auto | Primary key |
| `project_id` | INTEGER, FK → `project.id` | NULL | — | Owning project. NULL for the labs' jobs, which belong to no project; the Activity page shows them under the lab's name (Phases 19 and 21). Set for a story job (`write_story_bible`, PHASE-004; `discover_characters` and `discover_environments`, PHASE-005; `discover_scenes`, PHASE-006; `define_character`, PHASE-009; `discover_relations`, PHASE-047; `design_voice`, PHASE-011), which the Activity page shows under the project's name |
| `type` | TEXT | NOT NULL | — | `lab_image` \| `lab_video` \| `write_lab_video_prompt` \| `lab_voice` \| `write_character_look_prompt` \| `write_character_take_prompt` \| `write_story_bible` \| `discover_characters` \| `discover_environments` \| `discover_scenes` \| `define_character` \| `discover_relations` \| `design_voice` \| `write_environment_prompt` \| `define_environment` (`lab_video` and `write_lab_video_prompt`: Phase 19, the Video lab; `lab_voice`: Phase 21, Breeze TTS; `lab_image`: Phase 22, a run of the Image lab on the GPU server; the two `write_character_*` types: the Character lab's prompt writers; `write_story_bible`: PHASE-004, the Story Bible stage; `discover_characters` and `discover_environments`: PHASE-005, character and environment discovery; `discover_scenes`: PHASE-006, scene discovery; `define_character`: PHASE-009, the definition of one character; `discover_relations`: PHASE-047, the relations between the characters; `design_voice`: PHASE-011, the description of one story voice; `define_environment`: PHASE-013, the definition of one story environment (a job of the project, `provider='llm'`); `write_environment_prompt`: PHASE-012, the prompt of a library environment's reference picture, a lab job with no project). The narration types (`transcribe`, `plan_scenes`, `draft_descriptions`, `write_image_prompt`, `generate_frame`, `generate_clip`, `render_final`, `auto_pipeline`, `generate_voiceover`, `write_last_frame_prompt`, `generate_last_frame`, `extract_cast`, `write_character_reference_prompt`, `generate_character_reference`, `assign_cast`) were removed in migration `0022`, with their rows |
| `status` | TEXT | NOT NULL | `'queued'` | `queued` \| `running` \| `succeeded` \| `failed` \| `cancelled` |
| `phase` | TEXT | NULL | — | Free-text UI label, e.g. "queued on cluster" |
| `provider` | TEXT | NOT NULL | — | `gpu` \| `llm` \| `image` (Phase 17: the image model at the Bitdeer address; **no job uses it since Phase 22**, and the CHECK keeps it) \| `local` (no job type is local now, and the CHECK keeps it) |
| `provider_job_id` | TEXT | NULL | — | The external server's job id, once submitted |
| `input` | JSON | NOT NULL | — | Exact request sent: prompt, seed, server URL, etc. |
| `output` | JSON | NULL | — | Raw provider answer (LLM JSON, token usage, etc.) |
| `result_asset_id` | INTEGER, FK → `asset.id` | NULL | — | Set on success |
| `attempt` | INTEGER | NOT NULL | 1 | Retry counter |
| `error` | TEXT | NULL | — | The server's error text, if failed |
| `created_at` | DATETIME | NOT NULL | now | |
| `started_at` | DATETIME | NULL | — | |
| `finished_at` | DATETIME | NULL | — | |
| `last_checked_at` | DATETIME | NULL | — | Last time the dispatcher polled this job |

```sql
CREATE TABLE job (
    id               INTEGER PRIMARY KEY,
    project_id       INTEGER REFERENCES project(id) ON DELETE CASCADE,
    type             TEXT NOT NULL CHECK (type IN ('lab_image', 'lab_video', 'write_lab_video_prompt', 'lab_voice', 'write_character_look_prompt', 'write_character_take_prompt', 'write_story_bible', 'discover_characters', 'discover_environments', 'discover_scenes', 'define_character', 'discover_relations', 'design_voice', 'write_environment_prompt', 'define_environment')),
    status           TEXT NOT NULL DEFAULT 'queued'
                       CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    phase            TEXT,
    provider         TEXT NOT NULL CHECK (provider IN ('gpu', 'llm', 'image', 'local')),
    provider_job_id  TEXT,
    input            JSON NOT NULL,
    output           JSON,
    result_asset_id  INTEGER REFERENCES asset(id) ON DELETE SET NULL,
    attempt          INTEGER NOT NULL DEFAULT 1,
    error            TEXT,
    created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at       DATETIME,
    finished_at      DATETIME,
    last_checked_at  DATETIME
);
```

The dispatcher loop (Section 3.3) is the main reader/writer of this table: each tick it checks every `running` job, starts downloads for finished ones, resubmits pre-empted ones, and starts `queued` jobs, oldest first, while their pool has a free slot. There are **two shared pools** (`jobs/pools.py`): `gpu`, every job whose handler's provider is `gpu` (the labs' images, clips and speeches), limited by the setting `max_parallel_gpu_jobs`; and `paid_api`, every job whose provider is `llm` or `image` (every language model call set to Bitdeer, the story stages included; one whose role is set to Qwen3.8 counts in `gpu` instead), limited by `max_parallel_paid_api_calls`. A job type has no limit of its own and no handler names a group: a new job type joins the pool of its provider. A `local` job type would be a pool of its own, and its handler's `concurrency_limit` says how many; none exists now. A queued job whose pool is full shows the phase "waiting for a free GPU server slot" or "waiting for a free paid API slot". Both limits are read at every tick, and a lower number never stops a job that is running.

### 4.6 `setting`

Global settings edited in the UI (Section 3.7) — a simple key/value table. **Project-scoped** settings are **not** stored here; they live as columns directly on `project` (Section 4.1 above). See Section 6 below for exactly which keys live in this table.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `key` | TEXT | NOT NULL (PK) | — | e.g. `gpu_api_base_url` |
| `value` | JSON | NOT NULL | — | The setting's value |
| `updated_at` | DATETIME | NOT NULL | now | |

```sql
CREATE TABLE setting (
    key        TEXT PRIMARY KEY,
    value      JSON NOT NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### 4.7 `api_snapshot`

The recorded GPU API contract (Section 6.5) — the guide, the OpenAPI spec, and any other swagger document you add. Checked before every submission so a server update can't silently change what gets sent.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | INTEGER | NOT NULL | auto | Primary key |
| `source` | TEXT | NOT NULL | — | `guide` \| `openapi` \| a custom name you add |
| `url` | TEXT | NOT NULL | — | The source's path, relative to the server URL its `base` names (so a new tunnel address doesn't invalidate it). Includes any query string, for example `/v1/guide?format=json`. (Phase 4) |
| `fetched_at` | DATETIME | NOT NULL | now | |
| `fingerprint` | TEXT | NOT NULL | — | The document's `content_hash` if present, else SHA-256 of the canonical JSON |
| `server_content_hash` | TEXT | NULL | — | The server's own hash field, if the document has one |
| `api_version` | TEXT | NULL | — | Version string from the guide, if present |
| `body` | JSON | NOT NULL | — | The fetched document |
| `state` | TEXT | NOT NULL | `'pending'` | `approved` \| `pending` |
| `approved_at` | DATETIME | NULL | — | Set when you click Approve |

```sql
CREATE TABLE api_snapshot (
    id                  INTEGER PRIMARY KEY,
    source              TEXT NOT NULL,
    url                 TEXT NOT NULL,
    fetched_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fingerprint         TEXT NOT NULL,
    server_content_hash TEXT,
    api_version         TEXT,
    body                JSON NOT NULL,
    state               TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('approved', 'pending')),
    approved_at         DATETIME
);
```

Older snapshots are kept as history (Section 6.5: "Older versions stay as history") — rows are never overwritten, only inserted. To find the current baseline for a source, read the most recently **approved** row with that `source` **and** `url`, ordered by `fetched_at` and then `id`. Matching on `url` as well means a source whose path changes has no baseline and is "not approved", instead of showing a huge difference against a different document. (Phase 4.)

A changed source is stored once as a `pending` row per version: the guard inserts a pending row only if none with the same `fingerprint`, `source` and `url` exists that is newer than the latest approved row. A pending row is never converted to approved. Approving inserts a new `approved` row, so a simulated or real change always leaves the earlier approved, pending and approved rows behind as history.

### 4.8 `lab_run`

One manual test of an image model from the Image lab page (Phase 13, extended in Phase 22). A **Seedream** run is one synchronous call and **not** a `job` in the sense of the other labs: a call of 25 to 40 s that the page waits for. A **Qwen-Image-2.1** run (Phase 22) takes minutes, so it is a `lab_image` job (`job_id` set, `job.project_id` NULL) and its row is created `running`; the job's `finish` step stores the image, sets `status='succeeded'`, `seconds` and `response`, and adds the `lab_image`, in one transaction with the finished job. **A job that fails or is cancelled leaves the row `running`**, so the page reads the job's status as well (`api/image_lab.py`). Which model made a run is its `endpoint`: `/v1/qwen-image21/images/generate`, or a Bitdeer path. A row keeps what is needed to compare runs later: the exact request, the raw response, the timing and the usage. Runs are never deleted in iteration 1.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | INTEGER | NOT NULL | auto | Primary key |
| `created_at` | DATETIME | NOT NULL | now | |
| `mode` | TEXT | NOT NULL | — | `text_to_image` \| `image_to_image` (the `image` field on `/images/generations`) \| `edit` (`POST /images/edits`, multipart). A Qwen run is always `text_to_image` |
| `endpoint` | TEXT | NOT NULL | — | The path called, for example `/images/generations` |
| `model` | TEXT | NOT NULL | — | The model sent, for example `seedream-5.0-lite` |
| `prompt` | TEXT | NOT NULL | — | |
| `params` | JSON | NOT NULL | — | What the form held besides the prompt: `size`, `watermark` (true, false or null for "not sent"), `seed`, `sequential_max_images`, `image_field_as`, `edit_field_name`, `extra`. A Qwen run holds `engine: "qwen"`, `qwen_mode` (`quality` or `fast`), `aspect_ratio`, `expected_size`, `seed` and `steps` instead |
| `reference_images` | JSON | NOT NULL | — | `[{"source": "lab" \| "asset", "id": 7}]`, in the order they were sent. Not named `references`, which is an SQL keyword |
| `status` | TEXT | NOT NULL | — | `running` (Phase 22: a Qwen run whose job has not finished it) \| `succeeded` \| `failed` |
| `http_status` | INTEGER | NULL | — | Absent when there was no answer at all (a timeout or a refused connection), and always absent for a Qwen run |
| `error` | TEXT | NULL | — | A readable message, including the Cloudflare and Bitdeer cases |
| `seconds` | REAL | NULL | — | How long the call took |
| `request_bytes` | INTEGER | NULL | — | The size of the body that was sent |
| `usage` | JSON | NULL | — | The `usage` block of the answer, as returned |
| `request` | JSON | NOT NULL | — | The request as sent, with every image replaced by `<image: N bytes>` |
| `response` | JSON | NULL | — | The answer, with every `b64_json` replaced by `<image: N bytes>`. For a Qwen run: the server's last status (`remote`), `expected_size` and `returned_size` |
| `job_id` | INTEGER, FK → `job.id` | NULL | — | The `lab_image` job that makes a run on the GPU server (Phase 22). NULL for a Seedream run. `ON DELETE SET NULL` |

```sql
CREATE TABLE lab_run (
    id               INTEGER PRIMARY KEY,
    created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    mode             TEXT NOT NULL CHECK (mode IN ('text_to_image', 'image_to_image', 'edit')),
    endpoint         TEXT NOT NULL,
    model            TEXT NOT NULL,
    prompt           TEXT NOT NULL,
    params           JSON NOT NULL,
    reference_images JSON NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    http_status      INTEGER,
    error            TEXT,
    seconds          REAL,
    request_bytes    INTEGER,
    usage            JSON,
    request          JSON NOT NULL,
    response         JSON,
    job_id           INTEGER REFERENCES job(id) ON DELETE SET NULL
);
```

### 4.9 `lab_image`

An image the lab holds: one the user uploaded, or one a run produced. Files live under `media/lab/` and are served at `/media/lab/...`. A project's frames are **not** copied here: a run refers to them by their `asset` id in `lab_run.reference_images`.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | INTEGER | NOT NULL | auto | Primary key |
| `created_at` | DATETIME | NOT NULL | now | |
| `origin` | TEXT | NOT NULL | — | `upload` \| `result` |
| `run_id` | INTEGER, FK → `lab_run.id` | NULL | — | The run that produced a result. NULL for an upload. `ON DELETE SET NULL` |
| `output_index` | INTEGER | NULL | — | The position among the run's results, from 0 |
| `path` | TEXT | NOT NULL | — | Relative to the media folder, for example `lab/3f9c....jpg` |
| `mime` | TEXT | NOT NULL | — | |
| `width`, `height` | INTEGER | NOT NULL | — | As displayed |
| `size_bytes` | INTEGER | NOT NULL | — | |
| `sha256` | TEXT | NOT NULL | — | |

```sql
CREATE TABLE lab_image (
    id           INTEGER PRIMARY KEY,
    created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    origin       TEXT NOT NULL CHECK (origin IN ('upload', 'result')),
    run_id       INTEGER REFERENCES lab_run(id) ON DELETE SET NULL,
    output_index INTEGER,
    path         TEXT NOT NULL,
    mime         TEXT NOT NULL,
    width        INTEGER NOT NULL,
    height       INTEGER NOT NULL,
    size_bytes   INTEGER NOT NULL,
    sha256       TEXT NOT NULL
);
```

### 4.10 `lab_video_run`

One video the Video lab made, or is making (Phase 19). The lab belongs to no project, so its work runs as `lab_video` jobs with a NULL `project_id`. The job holds the status, the phase, the exact request and the server's answers (so a run resumes after a restart or a pre-emption); this row holds what the page lists and compares. The runs that one "run on both models" click starts share a `group_key`, and have the same prompt, first frame, size, length, recipe and seed, so the clips differ only by the model. Nothing is deleted in this iteration. Files live under `media/lab/` and are served at `/media/lab/...`.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | INTEGER | NOT NULL | auto | Primary key |
| `created_at` | DATETIME | NOT NULL | now | |
| `job_id` | INTEGER, FK → `job.id` | NULL | — | The `lab_video` job. `ON DELETE SET NULL` |
| `group_key` | TEXT | NULL | — | Shared by the runs one click started (a random hex string) |
| `video_model` | TEXT | NOT NULL | — | `ltx-2.3` \| `ltx-2.5` |
| `endpoint` | TEXT | NOT NULL | — | The GPU server path the request goes to, for example `/v1/ltx25/videos/generate` |
| `prompt` | TEXT | NOT NULL | — | The prompt as sent (trimmed) |
| `params` | JSON | NOT NULL | — | What the form held and what was sent: `mode`, `orientation`, `width`, `height`, `fps`, `duration_s`, `num_frames`, `seed` and `negative_prompt` (only an LTX-2.3 run has one) |
| `first_frame` | JSON | NULL | — | `{"source": "lab" \| "asset", "id": n}`: an Image lab image, or a project's frame asset. NULL for text-to-video. Never copied: the run refers to it |
| `last_frame` | JSON | NULL | — | Same shape as `first_frame`. Only on a run that moves from a first to a last frame (needs a first frame): LTX-2.5 uses `POST /v1/ltx25/videos/interpolate`, LTX-2.3 keyframe interpolation. Phase 21 |
| `audio_input` | JSON | NULL | — | `{"source": "voice_run" \| "voice", "id": n}`: the recorded speech a lip-synced clip was made to match (`POST /v1/ltx/videos/audio-to-video`, LTX-2.3 only). NULL for every other clip. Never copied: the run refers to a Voice lab run, or to a saved voice. Phase 24. For a MiniMax H3 reference clip it holds the first of `audio_references`, or NULL when there is none |
| `audio_references` | JSON | NULL | — | A list of `{"source": "voice_run" \| "voice", "id": n}`: the audios of a MiniMax H3 reference clip, in the order the prompt names them (`<Audio 1>`, `<Audio 2>`), sent as `audio_asset_ids`. NULL for every other clip and for a reference clip made without audio. Migration `0020` |
| `path` | TEXT | NULL | — | The stored clip, relative to the media folder (`lab/<32 hex>.mp4`). NULL until the job has finished |
| `size_bytes` | INTEGER | NULL | — | |
| `sha256` | TEXT | NULL | — | |
| `width`, `height` | INTEGER | NULL | — | As ffprobe reads the clip |
| `frame_count` | INTEGER | NULL | — | Counted from the file |
| `duration_s` | REAL | NULL | — | |
| `audio` | JSON | NULL | — | `{codec, sample_rate, channels}`, NULL when the clip has no sound |

```sql
CREATE TABLE lab_video_run (
    id           INTEGER PRIMARY KEY,
    created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    job_id       INTEGER REFERENCES job(id) ON DELETE SET NULL,
    group_key    TEXT,
    video_model  TEXT NOT NULL CHECK (video_model IN ('ltx-2.3', 'ltx-2.5')),
    endpoint     TEXT NOT NULL,
    prompt       TEXT NOT NULL,
    params       JSON NOT NULL,
    first_frame  JSON,
    last_frame   JSON,
    audio_input  JSON,
    audio_references JSON,
    path         TEXT,
    size_bytes   INTEGER,
    sha256       TEXT,
    width        INTEGER,
    height       INTEGER,
    frame_count  INTEGER,
    duration_s   REAL,
    audio        JSON
);
```

### 4.11 `voice`

A saved voice (Phase 21): a clean recording and its exact transcript, which Breeze TTS 2 clones. A voice comes from an upload (`POST /api/voices`: the recording is received, checked with ffprobe: WAV, MP3, M4A or FLAC and audio only, and stored under `media/lab/`) or from a Voice lab run (`POST /api/lab/voices/runs/{id}/save-voice`: the voice points at the run's own file, nothing is copied). A voice is never deleted, like every stored file; its name and transcript can be edited, its recording never changes. A job copies the recording's path and the transcript into its own `input` when it is created, so editing a voice changes nothing for a speech already under way.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | INTEGER | NOT NULL | auto | Primary key |
| `created_at` | DATETIME | NOT NULL | now | |
| `name` | TEXT | NOT NULL | — | At most 80 characters |
| `path` | TEXT | NOT NULL | — | The stored recording, relative to the media folder (`lab/<32 hex>.<ext>`) |
| `mime` | TEXT | NOT NULL | — | `audio/wav`, `audio/mpeg`, `audio/mp4` or `audio/flac` |
| `size_bytes` | INTEGER | NOT NULL | — | |
| `sha256` | TEXT | NOT NULL | — | |
| `duration_s` | REAL | NOT NULL | — | |
| `transcript` | TEXT | NOT NULL | — | What the recording says, word for word (at most 1,000 characters: the server's limit for `reference_text`) |
| `origin` | TEXT | NOT NULL | — | `upload` \| `lab_run` |
| `lab_voice_run_id` | INTEGER | NULL | — | The run the recording came from (`origin='lab_run'`). Not a foreign key: only a note |

```sql
CREATE TABLE voice (
    id               INTEGER PRIMARY KEY,
    created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    name             TEXT NOT NULL,
    path             TEXT NOT NULL,
    mime             TEXT NOT NULL,
    size_bytes       INTEGER NOT NULL,
    sha256           TEXT NOT NULL,
    duration_s       REAL NOT NULL,
    transcript       TEXT NOT NULL,
    origin           TEXT NOT NULL CHECK (origin IN ('upload', 'lab_run')),
    lab_voice_run_id INTEGER
);
```

### 4.12 `lab_voice_run`

One speech the Voice lab made, or is making (Phase 21). Like `lab_video_run`, the lab belongs to no project, so its work runs as `lab_voice` jobs with a NULL `project_id`; the job holds the status, the phase and the exact request. A run is one request, so its text is at most 1,000 characters.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | INTEGER | NOT NULL | auto | Primary key |
| `created_at` | DATETIME | NOT NULL | now | |
| `job_id` | INTEGER, FK → `job.id` | NULL | — | The `lab_voice` job. `ON DELETE SET NULL` |
| `mode` | TEXT | NOT NULL | — | `design` (a voice made from a description), `clone` (a saved voice reads the text) \| `direction` (a saved voice, steered by the instruction) |
| `text` | TEXT | NOT NULL | — | The text to speak (trimmed) |
| `instruction` | TEXT | NULL | — | design: the voice description (optional). direction: how to say it. clone: NULL |
| `voice_id` | INTEGER, FK → `voice.id` | NULL | — | The saved voice (clone and direction). `ON DELETE SET NULL` |
| `params` | JSON | NOT NULL | — | `{"seed": n, "cfg_scale": x}`. The seed is random when the form left it empty; `cfg_scale` is 4 with an instruction and 1 without, as the server recommends |
| `path` | TEXT | NULL | — | The stored WAV, relative to the media folder (`lab/<32 hex>.wav`). NULL until the job has finished |
| `size_bytes` | INTEGER | NULL | — | |
| `sha256` | TEXT | NULL | — | |
| `duration_s` | REAL | NULL | — | As ffprobe reads the file |
| `project_id` | INTEGER, FK → `project.id` | NULL | — | PHASE-011 (migration `0031`). The project the story pipeline made this sample for. NULL for a run made by hand in the Voice lab or the Character Lab. `ON DELETE SET NULL` (named `fk_lab_voice_run_project_id_project`), indexed by `idx_lab_voice_run_project` |
| `subject` | TEXT | NULL | — | PHASE-011. `character` or `narrator` (`CHECK`, `ck_lab_voice_run_subject_valid`, NULL allowed): what the pipeline's sample is the voice of. NULL for a run made by hand |
| `discovery_id` | TEXT | NULL | — | PHASE-011. The slug of the discovered character a `character` sample is for. NULL otherwise |
| `design_job_id` | INTEGER, FK → `job.id` | NULL | — | PHASE-011. The `design_voice` job that wrote this run's description. `ON DELETE SET NULL` (named `fk_lab_voice_run_design_job_id_job`) |
| `inputs` | JSON | NULL | — | PHASE-011, the D-3 inputs of the voice that is made from this run: for a character `{"project_id", "discovery_id", "character_id", "character_version", "voice_facts_sha256"}`, for the narrator `{"project_id", "story_bible_version", "narration_sha256"}`. `voice_facts_sha256` and `narration_sha256` are the SHA-256 of the facts the model was shown. NULL for a run made by hand. It is what the voice's "out of date" is worked out from |

A run with `project_id` set is the sample the pipeline made. Its `design_job_id` job wrote `instruction`, and its `text` is the fixed sentence of a character (`voice_design_writer.CHARACTER_LINE`) or the start of the story (at most 300 characters) for the narrator. The saved voice made from it names the run in `voice.lab_voice_run_id`.

```sql
CREATE TABLE lab_voice_run (
    id           INTEGER PRIMARY KEY,
    created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    job_id       INTEGER REFERENCES job(id) ON DELETE SET NULL,
    mode         TEXT NOT NULL CHECK (mode IN ('design', 'clone', 'direction')),
    text         TEXT NOT NULL,
    instruction  TEXT,
    voice_id     INTEGER REFERENCES voice(id) ON DELETE SET NULL,
    params       JSON NOT NULL,
    path         TEXT,
    size_bytes   INTEGER,
    sha256       TEXT,
    duration_s   REAL,
    -- PHASE-011 (migration 0031); NULL for a run made by hand
    project_id    INTEGER REFERENCES project(id) ON DELETE SET NULL,
    subject       TEXT CHECK (subject IS NULL OR subject IN ('character', 'narrator')),
    discovery_id  TEXT,
    design_job_id INTEGER REFERENCES job(id) ON DELETE SET NULL,
    inputs        JSON
);
```

### 4.13 `lab_character`

**Replaced in migration `0016`:** this table no longer exists. Its place is taken by `library_character` and its looks (Sections 4.22 to 4.25). The text below is the original description, kept for history.

A character of the Talking character lab's cast (Phase 24): a name, the picture that pins how it looks, and what to say about it to the language model that writes a take's prompts (it cannot see the picture, so the description is all it knows). Like every lab table it belongs to no project. A character is created and edited, never deleted in this iteration.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | INTEGER | NOT NULL | auto | Primary key |
| `created_at` | DATETIME | NOT NULL | now | |
| `name` | TEXT | NOT NULL | — | At most 80 characters |
| `description` | TEXT | NOT NULL | `''` | Who they are and what they look like. At most 2,000 characters |
| `image` | JSON | NOT NULL | — | `{"source": "lab" \| "asset", "id": n}`: an Image lab image, or a project's frame asset. Never copied: the character refers to it |
| `voice_id` | INTEGER, FK → `voice.id` | NULL | — | The default saved voice (clone, or direction when `voice_instruction` is set). `ON DELETE SET NULL` |
| `voice_instruction` | TEXT | NULL | — | A description of the voice: with a saved voice it steers the delivery (direction); alone it makes a new voice (design). At most 500 characters |

```sql
CREATE TABLE lab_character (
    id                 INTEGER PRIMARY KEY,
    created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    name               TEXT NOT NULL,
    description        TEXT NOT NULL DEFAULT '',
    image              JSON NOT NULL,
    voice_id           INTEGER REFERENCES voice(id) ON DELETE SET NULL,
    voice_instruction  TEXT
);
```

### 4.14 `lab_talk_run`

**Replaced in migration `0016`:** this table no longer exists. Its place is taken by `character_take` (Section 4.26). The text below is the original description, kept for history.

One take of the Talking character lab (Phase 24): a line of dialogue spoken by a character picture. A take is made in up to three steps, each a job the other labs already run, so the take row only links them: `prompt_job_id` (a `write_talk_prompts` job), `voice_run_id` (a `lab_voice_run`, made for the take or reused from an earlier one) and `video_run_id` (a `lab_video_run` made by the audio-to-video endpoint). The speech and the clip are therefore also listed by the Voice lab and the Video lab. Each step is a paid call and starts only from a click; with `auto_continue` the backend starts the next one by itself when the prompts job finishes and when the speech is stored. Nothing is deleted in this iteration.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | INTEGER | NOT NULL | auto | Primary key |
| `created_at` | DATETIME | NOT NULL | now | |
| `dialogue` | TEXT | NOT NULL | — | The line the character says (trimmed, at most 1,000 characters: one request of the speech model) |
| `character_id` | INTEGER, FK → `lab_character.id` | NULL | — | The cast character the take started from. `ON DELETE SET NULL` |
| `image` | JSON | NOT NULL | — | `{"source": "lab" \| "asset", "id": n}`: the picture the speaker is made from (the video's literal first frame) |
| `character_note` | TEXT | NULL | — | What the author said about the character, word for word. It wins over the cast character's description; with neither, the prompt of the Image lab run that made the picture is used |
| `delivery_note` | TEXT | NULL | — | How the line is said |
| `voice_mode` | TEXT | NULL | — | `design` \| `clone` \| `direction` when the take makes a new speech. NULL when it reuses one |
| `voice_id` | INTEGER, FK → `voice.id` | NULL | — | The saved voice (clone and direction). `ON DELETE SET NULL` |
| `voice_instruction` | TEXT | NULL | — | What steers the speech model. Written by the author, or copied from the prompts job's output only where it was empty |
| `video_prompt` | TEXT | NULL | — | What the video model shows. Same rule as `voice_instruction` |
| `orientation` | TEXT | NOT NULL | — | `portrait` \| `landscape` |
| `video_seed` | INTEGER | NULL | — | NULL: a random seed for each clip |
| `negative_prompt` | TEXT | NULL | — | NULL: the pipeline's own default |
| `auto_continue` | BOOLEAN | NOT NULL | 0 | 1 for a take made with "run all" |
| `last_error` | TEXT | NULL | — | Why the take could not start its next step by itself. NULL when there is nothing to say |
| `prompt_job_id` | INTEGER, FK → `job.id` | NULL | — | The `write_talk_prompts` job. NULL when the prompts were written by hand. `ON DELETE SET NULL` |
| `voice_run_id` | INTEGER, FK → `lab_voice_run.id` | NULL | — | The take's speech. `ON DELETE SET NULL` |
| `video_run_id` | INTEGER, FK → `lab_video_run.id` | NULL | — | The take's clip. `ON DELETE SET NULL` |

Which step is next is never stored: it is worked out from the rows. The video prompt is always needed, and so is a voice instruction while a speech is still to be made from a description or directed; then the speech, then the clip.

```sql
CREATE TABLE lab_talk_run (
    id                 INTEGER PRIMARY KEY,
    created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dialogue           TEXT NOT NULL,
    character_id       INTEGER REFERENCES lab_character(id) ON DELETE SET NULL,
    image              JSON NOT NULL,
    character_note     TEXT,
    delivery_note      TEXT,
    voice_mode         TEXT CHECK (voice_mode IS NULL OR voice_mode IN ('design', 'clone', 'direction')),
    voice_id           INTEGER REFERENCES voice(id) ON DELETE SET NULL,
    voice_instruction  TEXT,
    video_prompt       TEXT,
    orientation        TEXT NOT NULL CHECK (orientation IN ('portrait', 'landscape')),
    video_seed         INTEGER,
    negative_prompt    TEXT,
    auto_continue      BOOLEAN NOT NULL DEFAULT 0,
    last_error         TEXT,
    prompt_job_id      INTEGER REFERENCES job(id) ON DELETE SET NULL,
    voice_run_id       INTEGER REFERENCES lab_voice_run(id) ON DELETE SET NULL,
    video_run_id       INTEGER REFERENCES lab_video_run(id) ON DELETE SET NULL
);
```

### Recommended indexes

Not specified explicitly in `ANALYSIS.md`, but implied by the access patterns it describes (the dispatcher repeatedly scanning jobs by status/type — Section 3.3):

```sql
CREATE INDEX idx_asset_project       ON asset (project_id);
CREATE INDEX idx_job_project         ON job (project_id);
CREATE INDEX idx_job_status          ON job (status);
CREATE INDEX idx_job_type_status     ON job (type, status);
CREATE INDEX idx_api_snapshot_source ON api_snapshot (source, fetched_at);
CREATE INDEX idx_lab_run_created     ON lab_run (created_at);
CREATE INDEX idx_lab_run_job         ON lab_run (job_id);
CREATE INDEX idx_lab_image_run       ON lab_image (run_id);
CREATE INDEX idx_lab_image_created   ON lab_image (created_at);
CREATE INDEX idx_lab_video_run_created ON lab_video_run (created_at);
CREATE INDEX idx_lab_video_run_group   ON lab_video_run (group_key);
CREATE INDEX idx_lab_video_run_job     ON lab_video_run (job_id);
CREATE INDEX idx_voice_created         ON voice (created_at);
CREATE INDEX idx_lab_voice_run_created ON lab_voice_run (created_at);
CREATE INDEX idx_lab_voice_run_job     ON lab_voice_run (job_id);
CREATE INDEX idx_lab_voice_run_project ON lab_voice_run (project_id);
CREATE INDEX idx_lab_character_created ON lab_character (created_at);
CREATE INDEX idx_lab_talk_run_created  ON lab_talk_run (created_at);
CREATE INDEX idx_lab_talk_run_voice_run ON lab_talk_run (voice_run_id);
CREATE INDEX idx_story_bible_project   ON story_bible (project_id);
CREATE INDEX idx_scene_discovery_project ON scene_discovery (project_id);
CREATE INDEX idx_library_character_created ON library_character (created_at);
CREATE INDEX idx_character_look_character ON character_look (character_id);
CREATE INDEX idx_character_look_project ON character_look (project_id);
CREATE INDEX idx_character_look_candidate_look ON character_look_candidate (look_id);
CREATE INDEX idx_character_take_character ON character_take (character_id);
CREATE INDEX idx_character_take_created ON character_take (created_at);
CREATE INDEX idx_library_character_version_character ON library_character_version (character_id);
CREATE INDEX idx_project_character_link_character ON project_character_link (character_id);
CREATE INDEX idx_project_environment_link_environment ON project_environment_link (environment_id);
CREATE INDEX idx_library_environment_created ON library_environment (created_at);
CREATE INDEX idx_library_environment_version_environment ON library_environment_version (environment_id);
CREATE INDEX idx_environment_reference_environment ON environment_reference (environment_id);
CREATE INDEX idx_environment_reference_project ON environment_reference (project_id);
CREATE INDEX idx_environment_reference_candidate_reference ON environment_reference_candidate (reference_id);
```

(The `lab_character` and `lab_talk_run` indexes above went with those tables in migration `0016`.)

### 4.15 `character`

**Removed in migration `0022`.** The table held a project's characters and their reference pictures. The full text is at the tag `narration-final`.

### 4.16 `location`

**Removed in migration `0022`.** The table held a project's places and their reference pictures. The full text is at the tag `narration-final`.

### 4.17 `scene_character`

**Removed in migration `0022`.** The table held the characters each scene showed. The full text is at the tag `narration-final`.

### 4.18 `story_bible`

*Added in PHASE-004 (migration `0023`).* The Story Bible stage's result: one row per **version** of a project's StoryBible (`Path_ahead.md` Section 6), written by the `write_story_bible` job. It follows the artifact provenance convention of Section 2.1: every run adds a new row with the next `version`, and a stored row is never changed, so version 1 stays readable after version 2 exists. A manual version (a later phase, PHASE-037) is another row with `source='manual'` and a NULL `job_id`.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | INTEGER | NOT NULL | auto | Primary key |
| `project_id` | INTEGER, FK → `project.id` | NOT NULL | — | The story project. `ON DELETE CASCADE` |
| `version` | INTEGER | NOT NULL | — | 1, 2, 3 and so on, per project (`UNIQUE (project_id, version)`). The job reads the highest version and adds one; one job runs per project at a time |
| `source` | TEXT | NOT NULL | — | `ai` \| `manual` |
| `job_id` | INTEGER, FK → `job.id` | NULL | — | The `write_story_bible` job. `ON DELETE SET NULL`. The job holds the attempts, the token usage and the request |
| `inputs` | JSON | NOT NULL | — | `{"story_sha256": "<hex>", "artifacts": []}`. `story_sha256` is the SHA-256 (hex, UTF-8) of the exact story text the job read, which is the text saved when Run was pressed. `artifacts` is empty: the bible reads nothing but the story |
| `content` | JSON | NOT NULL | — | The bible (see below) |
| `created_at` | DATETIME | NOT NULL | now | |

`content`, checked by `services/story_bible_writer.check_bible` before it is stored:

```json
{
  "title": "The Seventh Floor",
  "language": "en",
  "genre": ["supernatural horror", "psychological mystery"],
  "tone": ["slow burn", "ominous", "increasingly disturbing"],
  "visual_style": "photorealistic cinematic horror",
  "time_period": "present day",
  "storytelling_style": { "narration": "controlled storyteller whose tension increases gradually" },
  "world_rules": ["Supernatural events should initially appear plausible."]
}
```

| Field | Rule |
|---|---|
| `title` | text, 1 to 120 characters |
| `language` | always `"en"`, written by the code (the app works in English only); the model is not asked for it |
| `genre` | 1 to 4 texts of at most 60 characters |
| `tone` | 1 to 5 texts of at most 60 characters |
| `visual_style` | text, 1 to 300 characters |
| `time_period` | text, 1 to 120 characters |
| `storytelling_style.narration` | text, 1 to 400 characters |
| `world_rules` | 0 to 10 texts of at most 300 characters (a missing list is stored as `[]`) |

Every text is stored on one line (whitespace collapsed), and a repeat in a list that differs only in case is dropped. An answer that breaks a rule is not stored: the attempt counts as unusable and is retried within the job's two attempts.

```sql
CREATE TABLE story_bible (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    version     INTEGER NOT NULL,
    source      TEXT NOT NULL CHECK (source IN ('ai', 'manual')),
    job_id      INTEGER REFERENCES job(id) ON DELETE SET NULL,
    inputs      JSON NOT NULL,
    content     JSON NOT NULL,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (project_id, version)
);
```

**Out of date** is never stored. `GET /api/projects/{id}/story-bible` says the newest version is out of date when `sha256(project.script_text)` differs from its `inputs.story_sha256`, or when the story is now empty (`services/story_bible.is_out_of_date`).

### 4.19 `character_discovery`

*Added in PHASE-005 (migration `0024`).* The character discovery stage's result (`Path_ahead.md` Section 7): one row per **version of the project's list of characters**, written by the `discover_characters` job. It follows the artifact provenance convention of Section 2.1 exactly as `story_bible` does (Section 4.18): every run adds a new row with the next `version`, and a stored row is never changed, so version 1 stays readable after version 2 exists. The characters of one run are **one row**: the set carries the version, the provenance and the list, and there is no row per character. (A later phase that links a character to the Character Lab, PHASE-008, refers to a character by its `id` slug inside a version.)

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | INTEGER | NOT NULL | auto | Primary key |
| `project_id` | INTEGER, FK → `project.id` | NOT NULL | — | The story project. `ON DELETE CASCADE` |
| `version` | INTEGER | NOT NULL | — | 1, 2, 3 and so on, per project (`UNIQUE (project_id, version)`); separate from the environments' numbering. The job reads the highest version and adds one; one `discover_characters` job runs per project at a time |
| `source` | TEXT | NOT NULL | — | `ai` \| `manual` |
| `job_id` | INTEGER, FK → `job.id` | NULL | — | The `discover_characters` job. `ON DELETE SET NULL`. The job holds the attempts, the token usage and the request |
| `inputs` | JSON | NOT NULL | — | `{"story_sha256": "<hex>", "artifacts": [{"kind": "story_bible", "id": 7, "version": 2}]}`. `story_sha256` is the SHA-256 (hex, UTF-8) of the exact story text the job read (the text saved when Run was pressed). `artifacts` names the StoryBible version the job read |
| `content` | JSON | NOT NULL | — | `{"characters": [ {"id", "name", "description"}, ... ]}` (see below) |
| `created_at` | DATETIME | NOT NULL | now | |

`content`, checked by `services/discovery_writer.check_items` before it is stored:

```json
{
  "characters": [
    { "id": "arjun", "name": "Arjun", "description": "Young man who moves into the apartment." },
    { "id": "landlord", "name": "Landlord", "description": "Gives Arjun a strange warning about upstairs." },
    { "id": "arjuns_mother", "name": "Arjun's mother", "description": "Only heard, as the voice Arjun recognises at the end." }
  ]
}
```

| Field | Rule |
|---|---|
| list | 1 to 30 items |
| `id` | a slug: lower case letters, digits and underscores, starting with a letter, at most 48 characters. The model's text is trimmed and lower-cased first. Every id in the list is different (a repeat is an error, never merged silently) |
| `name` | text, 1 to 80 characters |
| `description` | text, 1 to 300 characters |

Every text is stored on one line (whitespace collapsed). Nothing else is asked for or stored: no appearance, wardrobe, voice or height (the definition stage, PHASE-009, adds those), and **no relation between characters** (a project's relations are their own artifact, Section 4.29, D-14). A character at another age ("Young Arjun") is a separate item. An answer that breaks a rule is not stored: the attempt counts as unusable and is retried within the job's two attempts. A bare list is accepted in place of the object.

```sql
CREATE TABLE character_discovery (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    version     INTEGER NOT NULL,
    source      TEXT NOT NULL CHECK (source IN ('ai', 'manual')),
    job_id      INTEGER REFERENCES job(id) ON DELETE SET NULL,
    inputs      JSON NOT NULL,
    content     JSON NOT NULL,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (project_id, version)
);
CREATE INDEX idx_character_discovery_project ON character_discovery (project_id);
```

**Out of date** is never stored. `GET /api/projects/{id}/discovery/characters` says the newest version is out of date when `sha256(project.script_text)` differs from its `inputs.story_sha256`, when the story is now empty, or when the project's newest `story_bible` version is higher than the one in `inputs.artifacts` (`services/discovery.is_out_of_date`).

### 4.20 `environment_discovery`

*Added in PHASE-005 (migration `0024`).* The environment discovery stage's result (`Path_ahead.md` Section 8), written by the `discover_environments` job. **Exactly the shape of `character_discovery`** (Section 4.19): the same columns, the same `UNIQUE (project_id, version)`, the same provenance and the same out-of-date rule, with its own version numbering and its own index (`idx_environment_discovery_project`). Only `content` differs:

```json
{
  "environments": [
    { "id": "arjun_apartment", "name": "Arjun's Apartment", "description": "Large, sparse apartment on the top floor." },
    { "id": "arjun_bedroom", "name": "Arjun's Bedroom", "description": "Bedroom where the footsteps are heard." }
  ]
}
```

The rules for the list and for each item are those of Section 4.19. An environment is a place a film would build and show again when the story returns to it; a room inside a larger place is its own item when the story spends time in it. States of an environment (night, fire damage) are a later phase (PHASE-016).

### 4.21 `scene_discovery`

*Added in PHASE-006 (migration `0025`).* The scene discovery stage's result (`Path_ahead.md` Section 9): one row per **version of the project's list of scenes**, written by the `discover_scenes` job. It has **exactly the columns, constraints and provenance** of `character_discovery` (Section 4.19): `id`, `project_id` (`CASCADE`), `version` (`UNIQUE (project_id, version)`, numbered separately from the other two lists), `source` (`ai` or `manual`), `job_id` (`SET NULL`), `inputs` and `created_at`; `inputs` is `{"story_sha256": "<hex>", "artifacts": [{"kind": "story_bible", "id": 7, "version": 2}]}`. The scenes of one run are one row, and a stored row is never changed. Only `content` differs. It is checked and built by `services/scene_discovery_writer.check_scenes`:

```json
{
  "scenes": [
    {
      "index": 1,
      "id": "scene_move_in",
      "title": "The Warning",
      "description": "Arjun moves in and the landlord warns him never to go upstairs.",
      "starts_with": "When Arjun moved into his new apartment",
      "start": 0,
      "end": 224,
      "text": "When Arjun moved into his new apartment, ... “Exactly.”\n\n"
    },
    {
      "index": 2,
      "id": "scene_first_night",
      "title": "The First Footsteps",
      "description": "At 2:17 AM Arjun hears footsteps above and a voice like his mother's.",
      "starts_with": "Then, at exactly 2:17 AM, Arjun heard",
      "start": 224,
      "end": 391,
      "text": "Then, at exactly 2:17 AM, Arjun heard footsteps ... exactly like his mother.\n"
    }
  ]
}
```

| Field | Set by | Rule |
|---|---|---|
| list | the model | 1 to 60 scenes, in story order. The prompt asks for no number of scenes (it defines a scene: one place during one unbroken stretch of time); 60 only refuses a broken answer |
| `id` | the model | a slug, as for the other discovery lists (lower case letters, digits and underscores, starting with a letter, at most 48 characters); every id in the list is different. A scene is referred to by this id, within a version |
| `title` | the model | text, 1 to 80 characters, on one line (the prompt asks for English) |
| `description` | the model | text, 1 to 300 characters, on one line (the prompt asks for English) |
| `starts_with` | the model | the scene's opening words copied from the story: 1 to 200 characters, and at least 5 words (fewer only when fewer words are left in the story). It is kept as the model gave it, so the record shows what the model pointed at |
| `index` | code | 1, 2, 3 ... in list order (any `index` the model sends is ignored) |
| `start`, `end` | code | character offsets into the story the row was made from (`inputs.story_sha256`); `[start, end)` |
| `text` | code | exactly `story[start:end]`. **Never written by the model** |

**How the slices are made.** Words are the runs of non-whitespace characters of the story. When the opening words are looked for, case, punctuation and the style of quotation marks and apostrophes are ignored (`“Exactly.”` matches `"exactly"`, and `don’t` matches `don't`), and a mark that is nothing but punctuation (a lone `…`) is not a word. Scene 1 starts at character 0, and its `starts_with` must be the first words of the story. Every later scene starts at the **first character of the word** where its `starts_with` is found, looking forward from the start of the scene before it, so an opening quotation mark stays with the scene it opens, and a scene may begin in the middle of a paragraph. Each scene ends where the next one starts, and the last ends at the end of the story. So **the `text` of all the scenes, joined in order, is the whole story, byte for byte**: no gap, no overlap, no word skipped, whitespace between scenes kept at the end of the earlier scene. `check_scenes` checks that on every run before a version is stored.

An answer fails (and is retried within the job's two attempts) when the list is empty, longer than 60 or not a list; an `id` is badly formed or repeated; a `title`, `description` or `starts_with` is missing, empty or too long; the opening words have fewer than 5 words; the first scene does not begin at the story's first words; or the opening words of a later scene are not found after the start of the scene before it, or only found before it (the scenes are out of order). Nothing is stored for a failed run. A bare list is accepted in place of the object.

**Why `text` is stored as well as `start` and `end`.** `project.script_text` is edited in place and has no versions. Once the story changes the offsets point into a different text, but an older version of the scenes must stay readable (Section 2.1). The slice keeps each version self-contained, and it is what later stages read as the scene's part of the story: PHASE-015 checks a scene's speech events against it. Scenes carry **no character or environment ids** (D-15).

```sql
CREATE TABLE scene_discovery (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    version     INTEGER NOT NULL,
    source      TEXT NOT NULL CHECK (source IN ('ai', 'manual')),
    job_id      INTEGER REFERENCES job(id) ON DELETE SET NULL,
    inputs      JSON NOT NULL,
    content     JSON NOT NULL,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (project_id, version)
);
CREATE INDEX idx_scene_discovery_project ON scene_discovery (project_id);
```

**Out of date** is never stored, and is worked out exactly as for the two lists of PHASE-005: `GET /api/projects/{id}/scenes` says the newest version is out of date when `sha256(project.script_text)` differs from its `inputs.story_sha256`, when the story is now empty, or when the project's newest `story_bible` version is higher than the one in `inputs.artifacts` (`services/discovery.is_out_of_date`).

### 4.22 `library_character`

*Documented in PHASE-007; the table was added by migration `0016` (Phase 25), and extended by `0027` (`origin_project_id`, `origin_discovery_id`) and `0028` (`definition`).* A character of the Character lab's library: reusable, and built once (profile, look, voice) to make pictures, speeches and clips from. Like every lab table it belongs to no project: a story project **links** its discovered characters to library characters and pins a version of each (Section 4.28), and a character the pipeline made for a project only records where it came from (`origin_*`). A character is never deleted, only archived (`archived`). The table is the **editable head** of the character: every change of what defines it for production is also kept as an immutable version (Section 4.27). The rules for the fields are in `services/character_library.py`.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | INTEGER | NOT NULL | auto | Primary key |
| `created_at` | DATETIME | NOT NULL | now | |
| `updated_at` | DATETIME | NOT NULL | now | Set by code on every change |
| `name` | TEXT | NOT NULL | — | At most 80 characters |
| `age` | INTEGER | NULL | — | 0 to 2,000 |
| `gender` | TEXT | NOT NULL | `''` | Free text, at most 40 characters. The API offers every value already used as a suggestion (computed, no table) |
| `species` | TEXT | NOT NULL | `''` | Free text, at most 40 characters. The form requires one. Suggested the same way as `gender`. Empty for a character the pipeline made from a discovered character, until PHASE-009 writes it (the lab form still asks for it when the character is edited) |
| `era_kind` | TEXT | NOT NULL | `'present'` | `present` \| `past` \| `future` (`CHECK`) |
| `era_years` | INTEGER | NULL | — | 1 to 10,000 years for `past` and `future`; NULL for `present` |
| `era_setting` | TEXT | NULL | — | What that time looks like. At most 200 characters |
| `appearance` | TEXT | NOT NULL | `''` | The form requires it. At most 2,000 characters. Empty for a character the pipeline made from a discovered character, until PHASE-009 writes it |
| `outfit` | TEXT | NULL | — | At most 500 characters |
| `personality` | TEXT | NULL | — | At most 1,000 characters |
| `notes` | TEXT | NULL | — | Anything else that keeps the character consistent. At most 1,000 characters. For a character made from a discovered character it starts as the discovery's one-line description |
| `has_visible_mouth` | BOOLEAN | NOT NULL | 1 | 0 for a character with no mouth to lip-sync (a robot's screen face, an animal) |
| `voice_id` | INTEGER, FK → `voice.id` | NULL | — | The saved voice. NULL: the character is mute. `ON DELETE SET NULL` |
| `voice_description` | TEXT | NULL | — | What a voice audition's samples are made from. At most 500 characters |
| `current_look_id` | INTEGER, FK → `character_look.id` | NULL | — | The look new takes are made from. NULL until a look is ready. `ON DELETE SET NULL`. A circular reference with `character_look.character_id`, added by a second `ALTER` in migration `0016` |
| `archived` | BOOLEAN | NOT NULL | 0 | |
| `origin_project_id` | INTEGER, FK → `project.id` | NULL | — | PHASE-008 (migration `0027`). The project the pipeline made this character for (`project_character_link.how = 'created'`). NULL for a character made in the lab. `ON DELETE SET NULL`. Provenance only: it does not say which projects use the character (Section 4.28 does) |
| `origin_discovery_id` | TEXT | NULL | — | PHASE-008. The slug `id` of the discovered character it was made from, in that project |
| `definition` | JSON | NULL | — | PHASE-009 (migration `0028`). The character's current **structured definition** (Section 5, "The character definition"), written by a project's `define_character` job together with the profile fields it fills, or NULL when none was written. Read-only in the lab: no form edits it (editing definitions is PHASE-037). A lab edit leaves it as it is, and the new version carries it forward (Section 4.27) |

```sql
CREATE TABLE library_character (
    id                 INTEGER PRIMARY KEY,
    created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    name               TEXT NOT NULL,
    age                INTEGER,
    gender             TEXT NOT NULL DEFAULT '',
    species            TEXT NOT NULL DEFAULT '',
    era_kind           TEXT NOT NULL DEFAULT 'present' CHECK (era_kind IN ('present', 'past', 'future')),
    era_years          INTEGER,
    era_setting        TEXT,
    appearance         TEXT NOT NULL DEFAULT '',
    outfit             TEXT,
    personality        TEXT,
    notes              TEXT,
    has_visible_mouth  BOOLEAN NOT NULL DEFAULT 1,
    voice_id           INTEGER REFERENCES voice(id) ON DELETE SET NULL,
    voice_description  TEXT,
    current_look_id    INTEGER REFERENCES character_look(id) ON DELETE SET NULL,
    archived           BOOLEAN NOT NULL DEFAULT 0,
    origin_project_id  INTEGER REFERENCES project(id) ON DELETE SET NULL,
    origin_discovery_id TEXT,
    definition         JSON
);
```

### 4.23 `character_look`

*Documented in PHASE-007; added by migration `0016`, with `reference_image_id` added by `0018` and `project_id`, `discovery_id` and `inputs` added by `0029` (PHASE-010).* One attempt at a library character's reference pictures: a master picture on a white backdrop, plus four more angles made by editing it. **`version` numbers a character's looks from 1 and is not the character's version** (Section 4.27): a look is one set of pictures, a character version is a snapshot of the whole character. `status` starts at `waiting` for a same-face variant the story pipeline makes while its base's images are still being made (PHASE-047; no job exists yet, and it moves to `writing_prompt` by one conditional update when the base's pin has moved, or is replaced by a newer run), then moves `writing_prompt` → `choosing` (the candidates are ready and wait for one to be picked as the master) → `making_angles` → `ready`, or `failed`. The look becomes the character's `current_look_id` each time it turns `ready`. Redoing one angle of a `ready` look sets it back to `making_angles` until the new picture is stored.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | INTEGER | NOT NULL | auto | Primary key |
| `created_at` | DATETIME | NOT NULL | now | |
| `character_id` | INTEGER, FK → `library_character.id` | NOT NULL | — | `ON DELETE CASCADE` |
| `version` | INTEGER | NOT NULL | — | The look's number within its character: the highest so far plus 1 |
| `status` | TEXT | NOT NULL | `'writing_prompt'` | `waiting` (PHASE-047) \| `writing_prompt` \| `choosing` \| `making_angles` \| `ready` \| `failed` (`CHECK`) |
| `prompt` | TEXT | NULL | — | The master prompt, once the language model has written it |
| `prompt_job_id` | INTEGER, FK → `job.id` | NULL | — | The `write_character_look_prompt` job. `ON DELETE SET NULL` |
| `error` | TEXT | NULL | — | Why the look failed |
| `reference_image_id` | INTEGER, FK → `lab_image.id` | NULL | — | The author's own picture the look was started from: its candidates are edits of it. NULL for a look made from the profile alone. `ON DELETE SET NULL` |
| `project_id` | INTEGER, FK → `project.id` | NULL | — | PHASE-010 (migration `0029`). The project the **story pipeline** made this look for. NULL for a look made in the lab. A look with a `project_id` makes one candidate, chooses its master by itself and, once `ready`, moves that project's pin (Section 7). `ON DELETE SET NULL` (the look then behaves as a lab look) |
| `discovery_id` | TEXT | NULL | — | PHASE-010. The slug id of the discovered character in that project. Together with `project_id` it finds the `project_character_link` to move |
| `inputs` | JSON | NULL | — | PHASE-010. The D-3 provenance of a pipeline look: `{"project_id", "discovery_id", "character_version", "definition_sha256"}`. NULL for a lab look. "Out of date" images are worked out by comparing `definition_sha256` with the definition the project pins now |

```sql
CREATE TABLE character_look (
    id                  INTEGER PRIMARY KEY,
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    character_id        INTEGER NOT NULL REFERENCES library_character(id) ON DELETE CASCADE,
    version             INTEGER NOT NULL,
    status              TEXT NOT NULL DEFAULT 'writing_prompt'
                        CHECK (status IN ('waiting', 'writing_prompt', 'choosing', 'making_angles', 'ready', 'failed')),
    prompt              TEXT,
    prompt_job_id       INTEGER REFERENCES job(id) ON DELETE SET NULL,
    error               TEXT,
    reference_image_id  INTEGER REFERENCES lab_image(id) ON DELETE SET NULL,
    project_id          INTEGER REFERENCES project(id) ON DELETE SET NULL,
    discovery_id        TEXT,
    inputs              JSON
);
CREATE INDEX idx_character_look_character ON character_look (character_id);
CREATE INDEX idx_character_look_project ON character_look (project_id);
```

### 4.24 `character_look_candidate`

*Documented in PHASE-007; added by migration `0016`.* One of the (usually four) master pictures made for a look to choose from. A pure link to the `lab_run` that made it: its status is read from that run, never copied here.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | INTEGER | NOT NULL | auto | Primary key |
| `created_at` | DATETIME | NOT NULL | now | |
| `look_id` | INTEGER, FK → `character_look.id` | NOT NULL | — | `ON DELETE CASCADE` |
| `lab_run_id` | INTEGER, FK → `lab_run.id` | NULL | — | The Image lab run that made the picture. `ON DELETE SET NULL` |

```sql
CREATE TABLE character_look_candidate (
    id          INTEGER PRIMARY KEY,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    look_id     INTEGER NOT NULL REFERENCES character_look(id) ON DELETE CASCADE,
    lab_run_id  INTEGER REFERENCES lab_run(id) ON DELETE SET NULL
);
CREATE INDEX idx_character_look_candidate_look ON character_look_candidate (look_id);
```

### 4.25 `character_reference`

*Documented in PHASE-007; added by migration `0016`.* One angle picture of a look: the master (`front`) or one of the four edited angles. `UNIQUE (look_id, angle)`: **redoing an angle updates this row in place**, so the character keeps its old picture of that angle until the new one is ready. That is why a character version (Section 4.27) copies the picture ids instead of pointing at this row.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | INTEGER | NOT NULL | auto | Primary key |
| `created_at` | DATETIME | NOT NULL | now | |
| `look_id` | INTEGER, FK → `character_look.id` | NOT NULL | — | `ON DELETE CASCADE` |
| `angle` | TEXT | NOT NULL | — | `front` \| `three_quarter` \| `profile` \| `back` \| `face` (`CHECK`) |
| `lab_run_id` | INTEGER, FK → `lab_run.id` | NULL | — | The run that is making, or made, the picture. `ON DELETE SET NULL` |
| `lab_image_id` | INTEGER, FK → `lab_image.id` | NULL | — | The picture exactly as the image model made it, on its white backdrop. NULL until it is stored. Later edits (another angle, a take's picture) are made from it. `ON DELETE SET NULL` |
| `cutout_path` | TEXT | NULL | — | The same picture with its backdrop removed, for display. NULL when the cut-out could not be made (the picture on white is still a usable reference) |
| `cutout_mime` | TEXT | NULL | — | |
| `cutout_width` | INTEGER | NULL | — | |
| `cutout_height` | INTEGER | NULL | — | |
| `cutout_size_bytes` | INTEGER | NULL | — | |
| `cutout_sha256` | TEXT | NULL | — | |

```sql
CREATE TABLE character_reference (
    id                 INTEGER PRIMARY KEY,
    created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    look_id            INTEGER NOT NULL REFERENCES character_look(id) ON DELETE CASCADE,
    angle              TEXT NOT NULL CHECK (angle IN ('front', 'three_quarter', 'profile', 'back', 'face')),
    lab_run_id         INTEGER REFERENCES lab_run(id) ON DELETE SET NULL,
    lab_image_id       INTEGER REFERENCES lab_image(id) ON DELETE SET NULL,
    cutout_path        TEXT,
    cutout_mime        TEXT,
    cutout_width       INTEGER,
    cutout_height      INTEGER,
    cutout_size_bytes  INTEGER,
    cutout_sha256      TEXT,
    UNIQUE (look_id, angle)
);
```

### 4.26 `character_take`

*Documented in PHASE-007; added by migration `0016`, extended by `0019` (MiniMax H3) and by `0026` (`character_version`).* One thing made from a library character in the Character lab: a line of dialogue spoken (`audio`), a picture (`image`), or a clip (`video`), with or without dialogue. A take is made in up to four steps, each a job or run the other labs already run, so the row only links them: `prompt_job_id` (a `write_character_take_prompt` job writing the texts the other steps need, stored in `prompts`), then `image_run_id` (the first frame), `last_frame_run_id` (an optional last frame made by editing the first), `voice_run_id` (the speech) and `video_run_id` (the clip). Which step is next is never stored: it is worked out from the rows. `look_id` freezes the look the take was made from, and `character_version` the character's version at that moment, so a later look or version never changes an old take. `auto_continue` is 1 for a take made with "run all": each step starts by itself when the one before it ends.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | INTEGER | NOT NULL | auto | Primary key |
| `created_at` | DATETIME | NOT NULL | now | |
| `character_id` | INTEGER, FK → `library_character.id` | NOT NULL | — | `ON DELETE CASCADE` |
| `look_id` | INTEGER, FK → `character_look.id` | NULL | — | The look the take was made from. `ON DELETE SET NULL` |
| `character_version` | INTEGER | NULL | — | The character's newest version number when the take was made (PHASE-007). NULL for a take made before the character had a version. A plain number, not a link: the version is found by `(character_id, character_version)` |
| `output` | TEXT | NOT NULL | — | `image` \| `audio` \| `video` (`CHECK`) |
| `action` | TEXT | NULL | — | What happens in the picture or clip, in the author's words. Ignored for audio |
| `dialogue` | TEXT | NULL | — | What the character says. NULL: no dialogue |
| `video_model` | TEXT | NULL | — | Video only: `ltx-2.3` \| `ltx-2.5` \| `minimax-h3` (`CHECK`, or NULL) |
| `lip_sync` | BOOLEAN | NOT NULL | 0 | |
| `framing` | TEXT | NOT NULL | `'medium'` | `close_up` \| `medium` \| `wide` (`CHECK`) |
| `orientation` | TEXT | NOT NULL | `'portrait'` | `portrait` \| `landscape` (`CHECK`) |
| `seed` | INTEGER | NULL | — | |
| `duration_s` | REAL | NULL | — | A clip with no dialogue (or an H3 clip not made to match its speech): its length in seconds. NULL when it follows the speech |
| `negative_prompt` | TEXT | NULL | — | LTX-2.3 only |
| `auto_continue` | BOOLEAN | NOT NULL | 0 | |
| `prompts` | JSON | NULL | — | `{"image_prompt", "last_frame_prompt", "video_prompt", "delivery_instruction"}`: only the texts this take's steps need, written by the language model or by hand |
| `prompt_job_id` | INTEGER, FK → `job.id` | NULL | — | The `write_character_take_prompt` job. `ON DELETE SET NULL` |
| `image_run_id` | INTEGER, FK → `lab_run.id` | NULL | — | The first frame the take made. `ON DELETE SET NULL` |
| `voice_run_id` | INTEGER, FK → `lab_voice_run.id` | NULL | — | The speech the take made. `ON DELETE SET NULL` |
| `video_run_id` | INTEGER, FK → `lab_video_run.id` | NULL | — | The clip. `ON DELETE SET NULL` |
| `audio_marker` | TEXT | NULL | — | MiniMax H3 with dialogue: `fully_copy` \| `partially_copy` \| `reference` \| `weak_reference` (`CHECK`, or NULL) |
| `match_audio_duration` | BOOLEAN | NOT NULL | 0 | The clip is as long as the speech |
| `num_inference_steps` | INTEGER | NULL | — | MiniMax H3: 4 to 100, or NULL for the pipeline's own default |
| `identity_refs` | BOOLEAN | NOT NULL | 0 | The look's pictures are sent as extra references after the frames |
| `first_frame` | JSON | NULL | — | `{"source": "lab" \| "asset", "id": n}` when the author picked the first frame instead of having one made |
| `make_last_frame` | BOOLEAN | NOT NULL | 0 | The last frame is made from the first |
| `last_frame` | JSON | NULL | — | The last frame, picked: the shape of `first_frame` |
| `last_frame_run_id` | INTEGER, FK → `lab_run.id` | NULL | — | The last frame the take made. `ON DELETE SET NULL` |
| `audio_input` | JSON | NULL | — | `{"source": "voice_run" \| "voice", "id": n}` when the author picked the speech instead of having one made |
| `last_error` | TEXT | NULL | — | Why the take could not start its next step by itself |

```sql
CREATE TABLE character_take (
    id                    INTEGER PRIMARY KEY,
    created_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    character_id          INTEGER NOT NULL REFERENCES library_character(id) ON DELETE CASCADE,
    look_id               INTEGER REFERENCES character_look(id) ON DELETE SET NULL,
    character_version     INTEGER,
    output                TEXT NOT NULL CHECK (output IN ('image', 'audio', 'video')),
    action                TEXT,
    dialogue              TEXT,
    video_model           TEXT CHECK (video_model IS NULL OR video_model IN ('ltx-2.3', 'ltx-2.5', 'minimax-h3')),
    lip_sync              BOOLEAN NOT NULL DEFAULT 0,
    framing               TEXT NOT NULL DEFAULT 'medium' CHECK (framing IN ('close_up', 'medium', 'wide')),
    orientation           TEXT NOT NULL DEFAULT 'portrait' CHECK (orientation IN ('portrait', 'landscape')),
    seed                  INTEGER,
    duration_s            REAL,
    negative_prompt       TEXT,
    auto_continue         BOOLEAN NOT NULL DEFAULT 0,
    prompts               JSON,
    prompt_job_id         INTEGER REFERENCES job(id) ON DELETE SET NULL,
    image_run_id          INTEGER REFERENCES lab_run(id) ON DELETE SET NULL,
    voice_run_id          INTEGER REFERENCES lab_voice_run(id) ON DELETE SET NULL,
    video_run_id          INTEGER REFERENCES lab_video_run(id) ON DELETE SET NULL,
    audio_marker          TEXT CHECK (audio_marker IS NULL OR audio_marker IN
                              ('fully_copy', 'partially_copy', 'reference', 'weak_reference')),
    match_audio_duration  BOOLEAN NOT NULL DEFAULT 0,
    num_inference_steps   INTEGER,
    identity_refs         BOOLEAN NOT NULL DEFAULT 0,
    first_frame           JSON,
    make_last_frame       BOOLEAN NOT NULL DEFAULT 0,
    last_frame            JSON,
    last_frame_run_id     INTEGER REFERENCES lab_run(id) ON DELETE SET NULL,
    audio_input           JSON,
    last_error            TEXT
);
CREATE INDEX idx_character_take_character ON character_take (character_id);
CREATE INDEX idx_character_take_created ON character_take (created_at);
```

### 4.27 `library_character_version`

*Added in PHASE-007 (migration `0026`) and extended by `0028` (`definition`, `job_id`, `inputs`).* One **immutable snapshot of what defines a library character for production**: its profile, its structured definition (PHASE-009), its voice and its current look with that look's exact pictures. A row is added (never changed) whenever one of those changes, so a project can later pin a version (PHASE-008) and still read exactly what it was. `library_character` (Section 4.22) stays the editable head; the newest version normally equals it. It follows the provenance convention of Section 2.1: `source`, `version` and `created_at`, and, since PHASE-009, `job_id` and `inputs`. Both are NULL for a version made by hand in the lab (nothing upstream), and set for a version a `define_character` job wrote: the job, and what the definition was made from. `UNIQUE (character_id, version)` numbers a character's versions from 1.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | INTEGER | NOT NULL | auto | Primary key |
| `character_id` | INTEGER, FK → `library_character.id` | NOT NULL | — | `ON DELETE CASCADE` |
| `version` | INTEGER | NOT NULL | — | 1 for the first, then the newest number plus 1 |
| `source` | TEXT | NOT NULL | `'manual'` | `ai` or `manual` (`CHECK`). `manual` for every change made in the lab. `ai` for the version 1 of a character the pipeline made from a discovered character (PHASE-008), and for every version a `define_character` job writes (PHASE-009), whose text came from the model |
| `created_at` | DATETIME | NOT NULL | now | |
| `profile` | JSON | NOT NULL | — | The twelve profile fields by their column names in `library_character`: `name`, `age`, `gender`, `species`, `era_kind`, `era_years`, `era_setting`, `appearance`, `outfit`, `personality`, `notes`, `has_visible_mouth` |
| `voice_id` | INTEGER, FK → `voice.id` | NULL | — | The saved voice at that moment (NULL: mute). `ON DELETE SET NULL` |
| `voice_description` | TEXT | NULL | — | The voice description at that moment |
| `look_id` | INTEGER, FK → `character_look.id` | NULL | — | The current look at that moment, when it was `ready`; NULL when the character had none. `ON DELETE SET NULL` |
| `look_references` | JSON | NOT NULL | — | The look's pictures as they were: `[{"angle": "front", "lab_image_id": 41, "cutout_path": "lab/ab12.png" or null}, ...]`, sorted by angle name; `[]` when there is no look. Copied, not linked, so a later redo of an angle (which updates `character_reference` in place) never changes it |
| `definition` | JSON | NULL | — | PHASE-009. The structured definition the character held at that moment (Section 5, "The character definition"), or NULL when it had none. A version made by a lab edit **carries forward** the definition the character already has |
| `job_id` | INTEGER, FK → `job.id` | NULL | — | PHASE-009. The `define_character` job that wrote this version. NULL for a version made by hand. `ON DELETE SET NULL` (named `fk_library_character_version_job_id_job`) |
| `inputs` | JSON | NULL | — | PHASE-009, the D-3 inputs (Section 2.1): `{"project_id", "discovery_id", "story_sha256", "entry_sha256", "artifacts": [{"kind": "story_bible", "id", "version"}, {"kind": "character_discovery", "id", "version"}]}`. `entry_sha256` is the SHA-256 of the entry's name and one-line description as the model saw them. Since PHASE-047 it also has `relations_sha256` (the SHA-256 of the relations that name this character, as the model saw them; a version without it reads as having none) and, when the project had relations, `{"kind": "character_relations", "id", "version"}` in `artifacts`. NULL for a version made by hand. It is what "out of date" is worked out from, and it also says which project and which character of its list the definition was written for |

```sql
CREATE TABLE library_character_version (
    id                 INTEGER PRIMARY KEY,
    character_id       INTEGER NOT NULL REFERENCES library_character(id) ON DELETE CASCADE,
    version            INTEGER NOT NULL,
    source             TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('ai', 'manual')),
    created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    profile            JSON NOT NULL,
    voice_id           INTEGER REFERENCES voice(id) ON DELETE SET NULL,
    voice_description  TEXT,
    look_id            INTEGER REFERENCES character_look(id) ON DELETE SET NULL,
    look_references    JSON NOT NULL,
    definition         JSON,
    job_id             INTEGER,
    inputs             JSON,
    UNIQUE (character_id, version),
    CONSTRAINT fk_library_character_version_job_id_job
        FOREIGN KEY (job_id) REFERENCES job(id) ON DELETE SET NULL
);
CREATE INDEX idx_library_character_version_character ON library_character_version (character_id);
```

**What adds a version** (`services/character_versions.record_version_if_changed`, called before the commit of the change itself, so the change and its version are saved together):

| Change | Where |
|---|---|
| The character is created | `character_library.create_character`: version 1 |
| The pipeline makes the character from a discovered character (PHASE-008) | `character_library.create_from_discovery`: version 1 with `source='ai'` |
| An existing character with no version is linked to a project (PHASE-008) | `character_links.map_to_existing`: version 1, so there is a version to pin |
| The profile is edited | `character_library.update_character` |
| The voice is set, cleared or chosen from an audition | `character_library.set_voice`, `choose_audition` |
| The voice description is edited | `character_library.set_voice_description` |
| A look turns `ready` (it becomes the current look), or an angle redone on a look turns it `ready` again | `character_looks._maybe_mark_ready` |
| An earlier ready look is made current again | `character_looks.use_look` (`PUT /api/lab/characters/{id}/current-look`) |
| A `define_character` job saves a definition (PHASE-009) | `character_definitions.save_definition`: writes `library_character.definition` and the profile fields it fills, then adds a version with `source='ai'`, `job_id` and `inputs`, in the same transaction that marks the job succeeded. It also moves the project's pin to that version |

The code builds the snapshot of the character as it is now and compares it with the newest version; a version is added **only when something differs**, so saving the same form twice adds none. The comparison includes the `definition`. When the caller passes `inputs` (a definition run), the `inputs` are compared too: the same definition made again from newer inputs (a changed story, a re-written StoryBible) is a new version, so the pinned version always says what it was made from. Archiving is not a version change. A look that is not `ready` is never frozen: while the current look is being redone (`making_angles`) its pictures are half old and half new, so the newest version's look part is carried forward, and the redo adds its own version when the look is ready again. **What a version changed** (`created`, `profile`, `definition`, `look`, `voice`) is worked out on read by comparing a version with the one before it (`character_versions.changes_between`), never stored. The newest number is also `CharacterOut.version` in the API. The version number is the newest plus 1, as looks are numbered, so two changes committed at the same instant could collide on the unique constraint and one of them would fail; with one backend process that is very unlikely and it is accepted. There is no backfill: a character made before this migration has no version (`version: null`) until its next change.

### 4.28 `project_character_link`

*Added in PHASE-008 (migration `0027`).* Links one of a story project's **discovered characters** (Section 4.19) to a **library character** (Section 4.22) and **pins one version** of it (Section 4.27), so the Character Lab can change a character without silently changing a project (`Path_ahead.md` Sections 11 and 38). A row is found by `(project_id, discovery_id)`: `discovery_id` is the slug `id` of the discovered character inside `character_discovery.content`, and it is the **only** thing that ties the link to the list. So when discovery is run again, every id that is still in the newest list keeps its link with no matching code, a new id starts unlinked, and a link whose id is no longer in the list is kept and reported as "not in the newest list" (it applies again if a later run brings the id back). The rules are in `services/character_links.py`.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | INTEGER | NOT NULL | auto | Primary key |
| `project_id` | INTEGER, FK → `project.id` | NOT NULL | — | `ON DELETE CASCADE` |
| `discovery_id` | TEXT | NOT NULL | — | The discovered character's slug `id` (`^[a-z][a-z0-9_]*$`, at most 48 characters) |
| `character_id` | INTEGER, FK → `library_character.id` | NOT NULL | — | The library character that backs it. `ON DELETE CASCADE` (a character is never deleted, only archived) |
| `pinned_version` | INTEGER | NOT NULL | — | The `library_character_version.version` the project uses. A plain number, found by `(character_id, pinned_version)`, as `character_take.character_version` is. **Never changed by a lab edit.** A mapping to a different character sets it to that character's newest version; moving it to a newer version of the same character is adoption (PHASE-042) |
| `how` | TEXT | NOT NULL | — | `created`: the pipeline made the library character from the discovery entry (`library_character.origin_*` name this project). `mapped`: the user chose an existing character (`CHECK`) |
| `discovery_version` | INTEGER | NOT NULL | — | The version of the discovered list (`character_discovery.version`) the link was made from. Provenance only |
| `created_at` | DATETIME | NOT NULL | now | |
| `updated_at` | DATETIME | NOT NULL | now | Set by code when an entry is mapped to another character |

```sql
CREATE TABLE project_character_link (
    id                INTEGER PRIMARY KEY,
    project_id        INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    discovery_id      TEXT NOT NULL,
    character_id      INTEGER NOT NULL REFERENCES library_character(id) ON DELETE CASCADE,
    pinned_version    INTEGER NOT NULL,
    how               TEXT NOT NULL CHECK (how IN ('created', 'mapped')),
    discovery_version INTEGER NOT NULL,
    created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_project_character_link_discovery UNIQUE (project_id, discovery_id),
    CONSTRAINT uq_project_character_link_character UNIQUE (project_id, character_id)
);
CREATE INDEX idx_project_character_link_character ON project_character_link (character_id);
```

`UNIQUE (project_id, discovery_id)`: a discovered character is linked once. `UNIQUE (project_id, character_id)`: a project uses a library character for one discovered character only, so "Young Arjun" and "Arjun" stay two characters (D-14: a relation between them is kept on the project, Section 4.29, never on the library character). The two unique keys are named explicitly because both would otherwise get the name `uq_project_character_link_project_id`.

**"A newer version is available"** is worked out on every read (`character_links.LinkInfo.newer_version_available`): the character's newest `library_character_version.version` is higher than `pinned_version`. It is information only and is never stored (Section 2.1). "Used by projects" in the lab is the same table read from the other side (`GET /api/lab/characters/{id}/projects`, `character_links.used_by`).

---

### 4.29 `character_relations`

*Added in PHASE-047 (migration `0030`).* The project's relations between its discovered characters: one row per **version of the whole list of relations**, written by the `discover_relations` job (`ai`) or saved by the user from the Character relations panel (`manual`). It follows Section 2.1 exactly as `character_discovery` does (Section 4.19): a stored row is never changed, a new run or edit adds the next version, and "out of date" is never stored. A relation is kept on the project and keyed by the discovery slug ids, **never on a library character** (D-14, amended), so reusing a library character in another project brings no relation along.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | INTEGER | NOT NULL | auto | Primary key |
| `project_id` | INTEGER, FK → `project.id` | NOT NULL | — | `ON DELETE CASCADE` |
| `version` | INTEGER | NOT NULL | — | 1, 2, 3 and so on, per project (`UNIQUE (project_id, version)`) |
| `source` | TEXT | NOT NULL | — | `ai` \| `manual` (`CHECK`) |
| `job_id` | INTEGER, FK → `job.id` | NULL | — | The `discover_relations` job. NULL for a manual version. `ON DELETE SET NULL` |
| `inputs` | JSON | NOT NULL | — | `{"story_sha256": "<hex>", "artifacts": [{"kind": "story_bible", "id", "version"}, {"kind": "character_discovery", "id", "version"}]}`: the story and the versions the list was made from (a manual version records the newest at the time of the edit) |
| `content` | JSON | NOT NULL | — | `{"relations": [ {"character", "kind", "of"}, ... ]}` (see below) |
| `created_at` | DATETIME | NOT NULL | now | |

`content`, checked by `services/character_relation_writer.check_relations` before it is stored (for the model's answer and for the user's edit alike):

```json
{
  "relations": [
    { "character": "young_arjun", "kind": "younger_self", "of": "arjun" },
    { "character": "mother", "kind": "parent", "of": "arjun" }
  ]
}
```

`{"character": A, "kind": K, "of": B}` reads "A is the K of B", and **B is the base**. Kinds: `younger_self`, `older_self` and `twin` (the same face: the picture is an edit of B's front picture), `parent`, `sibling` and `grandparent` (family: only B's traits are added to the prompt as words). `child` and `grandchild` are accepted and stored swapped (`parent`, `grandparent`).

| Rule | |
|---|---|
| ids | `character` and `of` are ids of the newest list of characters (slugs, trimmed and lower-cased first) |
| self | nobody is related to themselves |
| pair | one relation per pair of characters; the same fact written both ways (a twin or sibling, or a child and a parent) is kept once |
| same-face base | a character is the same-face variant of at most one other, and a base is never itself a variant, so there are no chains or loops |
| size | at most 60 relations |

```sql
CREATE TABLE character_relations (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    version     INTEGER NOT NULL,
    source      TEXT NOT NULL CHECK (source IN ('ai', 'manual')),
    job_id      INTEGER REFERENCES job(id) ON DELETE SET NULL,
    inputs      JSON NOT NULL,
    content     JSON NOT NULL,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (project_id, version)
);
CREATE INDEX idx_character_relations_project ON character_relations (project_id);
```

**Out of date** is never stored. `GET /api/projects/{id}/character-relations` says the newest version is out of date when the story, the Story Bible or the list of characters is newer than `inputs` says, and lists the relations that name a character no longer in the list as `dropped` (they stand for nothing). A definition (Section 4.27) is out of date when the hash of the relations that name its character (`inputs.relations_sha256`) changed; a ready look (Section 4.23) when its relation or its base's front picture changed, or when a relative's traits did.

### 4.30 `narrator_voice`

*Added in PHASE-011 (migration `0031`).* One **version of the project's narrator voice**: the saved voice the story is narrated in. It follows Section 2.1 exactly as `story_bible` does (Section 4.18): a stored row is never changed, every derivation or hand choice adds the next `version`, the newest row is the current one, and "out of date" is never stored. A project with no row has no narrator voice yet.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | INTEGER | NOT NULL | auto | Primary key |
| `project_id` | INTEGER, FK → `project.id` | NOT NULL | — | `ON DELETE CASCADE` |
| `version` | INTEGER | NOT NULL | — | 1, 2, 3, … per project. `UNIQUE (project_id, version)` |
| `source` | TEXT | NOT NULL | — | `ai` or `manual` (`CHECK`). `ai`: derived from the StoryBible by a `design_voice` job. `manual`: a saved voice the user chose |
| `voice_id` | INTEGER, FK → `voice.id` | NULL | — | The saved voice. `ON DELETE SET NULL` |
| `job_id` | INTEGER, FK → `job.id` | NULL | — | The `design_voice` job of an `ai` version. NULL for a manual one. `ON DELETE SET NULL` |
| `inputs` | JSON | NOT NULL | — | An `ai` version: `{"project_id", "story_bible_version", "narration_sha256"}`; `narration_sha256` is the SHA-256 of the narration style, tone and genres the model was shown. A `manual` version: `{}` |
| `created_at` | DATETIME | NOT NULL | now | |

```sql
CREATE TABLE narrator_voice (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    version     INTEGER NOT NULL,
    source      TEXT NOT NULL CHECK (source IN ('ai', 'manual')),
    voice_id    INTEGER REFERENCES voice(id) ON DELETE SET NULL,
    job_id      INTEGER REFERENCES job(id) ON DELETE SET NULL,
    inputs      JSON NOT NULL,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (project_id, version)
);
CREATE INDEX idx_narrator_voice_project ON narrator_voice (project_id);
```

**Out of date** is never stored. `GET /api/projects/{id}/narrator-voice` reports an `ai` version as out of date when the newest StoryBible's narration facts no longer hash to `inputs.narration_sha256`. A `manual` version is never out of date (the user chose it), and deriving a voice over it asks the user to confirm first. A character's voice has no table of its own: it is the library character's `voice_id` (Section 4.22), and its status is worked out on read from the newest `design_voice` job, the run it queued and the pinned version's `inputs`.

### 4.31 `library_environment`

*Added in PHASE-012 (migration `0032`).* The editable head of an **environment** in the Character Lab: a place that is kept, versioned and illustrated. It is global (no `project_id`); a story project links its discovered environments to library environments and pins a version of each (Section 4.35, PHASE-013). An environment is never deleted: `archived` hides it.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | INTEGER | NOT NULL | auto | Primary key |
| `created_at` | DATETIME | NOT NULL | now | |
| `updated_at` | DATETIME | NOT NULL | now | Set on every change |
| `name` | TEXT | NOT NULL | — | Required, at most 80 characters |
| `description` | TEXT | NOT NULL | `''` | What the place looks like. Required, at most 2,000 characters. The reference picture is drawn from it |
| `era_kind` | TEXT | NOT NULL | `'present'` | `present`, `past` or `future` (`CHECK`) |
| `era_years` | INTEGER | NULL | — | 1 to 10,000; needed when `era_kind` is `past` or `future`, and NULL for `present` |
| `era_setting` | TEXT | NULL | — | Optional, for example "Victorian London". At most 200 characters |
| `atmosphere` | TEXT | NULL | — | Optional, its usual mood and light. At most 500 characters |
| `notes` | TEXT | NULL | — | Optional. At most 1,000 characters |
| `archived` | BOOLEAN | NOT NULL | `0` | Hidden from the library list when true. Archiving is not a version change |
| `origin_project_id` | INTEGER, FK → `project.id` | NULL | — | PHASE-013 (migration `0033`). The project the pipeline made this environment for (`project_environment_link.how = 'created'`). NULL for an environment made in the lab. `ON DELETE SET NULL`. Provenance only: it does not say which projects use the environment (Section 4.35 does) |
| `origin_discovery_id` | TEXT | NULL | — | PHASE-013. The slug `id` of the discovered environment it was made from. Set together with `origin_project_id` |
| `definition` | JSON | NULL | — | PHASE-013. The **newest structured definition** the Environment Definition stage wrote (`Path_ahead.md` Section 13; the shape is in Section 5). NULL until one is written, and for an environment made by hand. It is the same document as the newest version's `definition`; the head carries it so the lab can show it without reading a version |

```sql
CREATE TABLE library_environment (
    id          INTEGER PRIMARY KEY,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    era_kind    TEXT NOT NULL DEFAULT 'present' CHECK (era_kind IN ('present', 'past', 'future')),
    era_years   INTEGER,
    era_setting TEXT,
    atmosphere  TEXT,
    notes       TEXT,
    archived    BOOLEAN NOT NULL DEFAULT 0,
    origin_project_id   INTEGER REFERENCES project(id) ON DELETE SET NULL,
    origin_discovery_id TEXT,
    definition  JSON
);
CREATE INDEX idx_library_environment_created ON library_environment (created_at);
```

The head is the **current** profile. Every change that alters one of the seven profile fields, or the definition, adds a row to `library_environment_version` (Section 4.32) in the same transaction. A definition run **overwrites the profile fields it fills** (`description`, `atmosphere` and the era, from the definition) and never `name` or `notes`; a later lab edit **carries the definition forward** into its own version, so a hand edit does not lose it.

### 4.32 `library_environment_version`

*Added in PHASE-012 (migration `0032`).* One **immutable snapshot of an environment's profile**, the same pattern as `library_character_version` (Section 4.27): `environment_versions.record_version_if_changed` adds the next `version` only when the profile differs from the newest one's (so saving the same form twice adds none), flushes and never commits. A stored row is never changed, except that `reference_image_id` is set when its canonical picture is chosen. What a version changed is **worked out on read**, never stored.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | INTEGER | NOT NULL | auto | Primary key |
| `environment_id` | INTEGER, FK → `library_environment.id` | NOT NULL | — | `ON DELETE CASCADE` |
| `version` | INTEGER | NOT NULL | — | 1, 2, 3, … per environment. `UNIQUE (environment_id, version)` |
| `source` | TEXT | NOT NULL | `'manual'` | `ai` or `manual` (`CHECK`). `manual` for every change made in the lab. `ai` (PHASE-013) for version 1 of an environment the pipeline created from a discovered environment, and for a version a definition run writes |
| `created_at` | DATETIME | NOT NULL | now | |
| `profile` | JSON | NOT NULL | — | The seven profile fields as they were: `name`, `description`, `era_kind`, `era_years`, `era_setting`, `atmosphere`, `notes` (Section 5) |
| `reference_image_id` | INTEGER, FK → `lab_image.id` | NULL | — | The **canonical picture** of this version: the candidate the author chose, or the one picture the pipeline made, for this version's text. NULL until one is set, and always NULL on a version just added by an edit. `ON DELETE SET NULL` |
| `definition` | JSON | NULL | — | PHASE-013 (migration `0033`). The structured definition as the head held it when this version was written (Section 5). NULL for a version with none. A lab edit copies the head's definition forward unchanged |
| `job_id` | INTEGER, FK → `job.id` | NULL | — | PHASE-013. The `define_environment` job that wrote this version. NULL for a manual version and for the first version of an environment the pipeline created. `ON DELETE SET NULL` |
| `inputs` | JSON | NULL | — | PHASE-013. The D-3 inputs of Section 2.1 the definition was made from: `project_id`, `discovery_id`, the story hash, the entry's hash and the artifacts read (the StoryBible, the list of environments and the scenes, each with its version). NULL for a version made by hand |

```sql
CREATE TABLE library_environment_version (
    id                 INTEGER PRIMARY KEY,
    environment_id     INTEGER NOT NULL REFERENCES library_environment(id) ON DELETE CASCADE,
    version            INTEGER NOT NULL,
    source             TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('ai', 'manual')),
    created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    profile            JSON NOT NULL,
    reference_image_id INTEGER REFERENCES lab_image(id) ON DELETE SET NULL,
    definition         JSON,
    job_id             INTEGER REFERENCES job(id) ON DELETE SET NULL,
    inputs             JSON,
    UNIQUE (environment_id, version)
);
CREATE INDEX idx_library_environment_version_environment ON library_environment_version (environment_id);
```

`environment_versions.record_version_if_changed` compares the profile and the `definition`, and, when a definition run passes `inputs`, those too: the same text made from newer inputs (the story changed) is a new version, so the pinned version always says what it was made from. What a version changed (`created`, `profile`, `definition`) is worked out on read.

**A picture belongs to the version it was made for.** An edit never copies the picture forward: the new version starts with none and the older version keeps its own. A picture can be chosen or replaced only while the version is **not frozen**, and a version is frozen when **either** holds (`environment_references.is_frozen` and the "newest" check): (1) it is no longer the environment's newest version, or (2) **a project pins it and it already has a picture**. So a pipeline picture cannot be swapped under a project, and a pinned version with no picture yet can still be given one. (`environment_references.choose` and the start of a lab attempt both refuse a frozen version.) The "chosen" candidate of an attempt is not stored: it is the candidate whose picture is the version's `reference_image_id`.

### 4.33 `environment_reference`

*Added in PHASE-012 (migration `0032`).* One **attempt to make the canonical picture** of one version: a model writes a prompt, then four pictures are drawn. The attempt belongs to the version it was started for (`version_id`), which is always the environment's newest version at that moment. Pressing the button again adds another attempt; none is ever changed after it is `ready` or `failed`.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | INTEGER | NOT NULL | auto | Primary key |
| `created_at` | DATETIME | NOT NULL | now | |
| `environment_id` | INTEGER, FK → `library_environment.id` | NOT NULL | — | `ON DELETE CASCADE` |
| `version_id` | INTEGER, FK → `library_environment_version.id` | NOT NULL | — | The version the picture is made for. `ON DELETE CASCADE` |
| `status` | TEXT | NOT NULL | `'writing_prompt'` | `writing_prompt`, `ready` or `failed` (`CHECK`). `ready` means the four pictures were started, not that they are finished: each candidate's own state is read live from its `lab_run` |
| `prompt` | TEXT | NULL | — | The image prompt the model wrote, set when it is written |
| `prompt_job_id` | INTEGER, FK → `job.id` | NULL | — | The `write_environment_prompt` job. `ON DELETE SET NULL` |
| `error` | TEXT | NULL | — | Why the attempt failed, in words for the user |
| `project_id` | INTEGER, FK → `project.id` | NULL | — | PHASE-013 (migration `0033`). The project whose Environment Definition stage made this attempt. **A non-NULL `project_id` is what makes it a pipeline attempt**: it starts one candidate (a lab attempt starts four) and, once that picture is stored, the version takes it as its canonical picture itself (D-5). NULL for an attempt made in the lab. `ON DELETE SET NULL`, indexed |
| `discovery_id` | TEXT | NULL | — | PHASE-013. The slug id of the discovered environment in that project. With `project_id` it finds the `project_environment_link` |

```sql
CREATE TABLE environment_reference (
    id             INTEGER PRIMARY KEY,
    created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    environment_id INTEGER NOT NULL REFERENCES library_environment(id) ON DELETE CASCADE,
    version_id     INTEGER NOT NULL REFERENCES library_environment_version(id) ON DELETE CASCADE,
    status         TEXT NOT NULL DEFAULT 'writing_prompt'
                   CHECK (status IN ('writing_prompt', 'ready', 'failed')),
    prompt         TEXT,
    prompt_job_id  INTEGER REFERENCES job(id) ON DELETE SET NULL,
    error          TEXT,
    project_id     INTEGER REFERENCES project(id) ON DELETE SET NULL,
    discovery_id   TEXT
);
CREATE INDEX idx_environment_reference_environment ON environment_reference (environment_id);
CREATE INDEX idx_environment_reference_project ON environment_reference (project_id);
```

An attempt is **frozen** when its version is no longer the environment's newest, **or** a project pins the version and it already has its picture (Section 4.32): this is worked out on read and not stored. The prompt of an attempt is written from **its own version's** frozen profile, not from the head, so a later edit never changes what a pinned version's picture was asked to show.

**Pipeline attempts.** A pipeline attempt reads as `ready` after its one candidate has been started. When that candidate's picture is stored (`jobs/generate_lab_image.py` calls `environment_references.on_candidate_image_stored`), the version's `reference_image_id` is set to it in the same step, if the version still has none. "Picture is `failed`" for a project is worked out on read from the attempt's own status and the jobs of its prompt and candidate (a `lab_image` job that fails leaves its `lab_run` `running`, so the job's status is the truth), and the author can press **Retry the picture**, which adds another attempt.

### 4.34 `environment_reference_candidate`

*Added in PHASE-012 (migration `0032`).* One of the **four candidate pictures** of an attempt. It holds nothing but the link to the text-to-image run: the run's status, error and picture are read live from `lab_run`, its `lab_image` and its job, the same way a character look's candidates are.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | INTEGER | NOT NULL | auto | Primary key |
| `created_at` | DATETIME | NOT NULL | now | |
| `reference_id` | INTEGER, FK → `environment_reference.id` | NOT NULL | — | `ON DELETE CASCADE` |
| `lab_run_id` | INTEGER, FK → `lab_run.id` | NULL | — | The Qwen-Image text-to-image run (16:9, its own random seed). `ON DELETE SET NULL` |

```sql
CREATE TABLE environment_reference_candidate (
    id           INTEGER PRIMARY KEY,
    created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reference_id INTEGER NOT NULL REFERENCES environment_reference(id) ON DELETE CASCADE,
    lab_run_id   INTEGER REFERENCES lab_run(id) ON DELETE SET NULL
);
CREATE INDEX idx_environment_reference_candidate_reference ON environment_reference_candidate (reference_id);
```

The candidates are also in the Image lab's history, as any run is. Choosing one does not copy it: the version points at its `lab_image`. A pipeline attempt (Section 4.33) has exactly one.

### 4.35 `project_environment_link`

*Added in PHASE-013 (migration `0033`).* The environment twin of `project_character_link` (Section 4.28). Links one of a story project's **discovered environments** (`environment_discovery.content`) to a **library environment** (Section 4.31) and **pins one version** of it (Section 4.32), so the Character Lab can change a place without silently changing a project. A row is found by `(project_id, discovery_id)`; `discovery_id` is the slug `id` of the discovered environment, the only thing that ties the link to the list, so a re-run of discovery that keeps an id keeps its link, a new id starts unlinked, and a link whose id has left the list is kept and reported as "not in the newest list". The rules are in `services/environment_links.py`.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | INTEGER | NOT NULL | auto | Primary key |
| `project_id` | INTEGER, FK → `project.id` | NOT NULL | — | `ON DELETE CASCADE` |
| `discovery_id` | TEXT | NOT NULL | — | The discovered environment's slug `id` (`^[a-z][a-z0-9_]*$`, at most 48 characters) |
| `environment_id` | INTEGER, FK → `library_environment.id` | NOT NULL | — | The library environment that backs it. `ON DELETE CASCADE` (an environment is never deleted, only archived) |
| `pinned_version` | INTEGER | NOT NULL | — | The `library_environment_version.version` the project uses. A plain number, found by `(environment_id, pinned_version)`. **Never changed by a lab edit.** It moves only when the pipeline writes a new version for this project (the definition is saved) and when the entry is mapped to another environment (which pins that environment's newest version) |
| `how` | TEXT | NOT NULL | — | `created`: the pipeline made the library environment from the discovery entry (`library_environment.origin_*` name this project). `mapped`: the user chose an existing environment (`CHECK`) |
| `discovery_version` | INTEGER | NOT NULL | — | The version of the discovered list (`environment_discovery.version`) the link was made from. Provenance only |
| `created_at` | DATETIME | NOT NULL | now | |
| `updated_at` | DATETIME | NOT NULL | now | Set by code when an entry is mapped to another environment or its pin moves |

```sql
CREATE TABLE project_environment_link (
    id                INTEGER PRIMARY KEY,
    project_id        INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    discovery_id      TEXT NOT NULL,
    environment_id    INTEGER NOT NULL REFERENCES library_environment(id) ON DELETE CASCADE,
    pinned_version    INTEGER NOT NULL,
    how               TEXT NOT NULL CHECK (how IN ('created', 'mapped')),
    discovery_version INTEGER NOT NULL,
    created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_project_environment_link_discovery UNIQUE (project_id, discovery_id),
    CONSTRAINT uq_project_environment_link_environment UNIQUE (project_id, environment_id)
);
CREATE INDEX idx_project_environment_link_environment ON project_environment_link (environment_id);
```

`UNIQUE (project_id, discovery_id)`: a discovered environment is linked once. `UNIQUE (project_id, environment_id)`: a project uses a library environment for one discovered environment only, so "Apartment" and "Apartment at night" stay two environments. The two unique keys are named explicitly because both would otherwise get the name `uq_project_environment_link_project_id`.

**"A newer version is available"** is worked out on every read (`environment_links.LinkInfo.newer_version_available`): the environment's newest `library_environment_version.version` is higher than `pinned_version`. It is information only and is never stored (Section 2.1). "Used by projects" in the lab is the same table read from the other side (`GET /api/lab/environments/{id}/projects`, `environment_links.used_by`), and a version's "pinned by" list is the same rows grouped by `pinned_version`.

---

## 5. JSON column shapes

The shapes of the narration jobs and of the assets they made were removed with migration `0022`: `transcript.words` and `script_words`, and the `job.input` and `job.output` of `transcribe`, `plan_scenes`, `draft_descriptions`, `write_image_prompt`, `generate_frame`, `write_last_frame_prompt`, `generate_last_frame`, `generate_clip`, `render_final`, `generate_voiceover`, the cast jobs and `auto_pipeline`. Their full text is at the tag `narration-final` (`git show narration-final:DATABASE_STRUCTURE.md`). The shapes of the lab jobs follow.

### `job.input` and `job.output` for a `lab_image` job (Phase 22)

A `lab_image` job is one run of the Image lab on Qwen-Image-2.1, with `project_id` NULL (so it is listed on the Activity page as "Image lab"). It is created together with its `lab_run` row (`lab_run.job_id`), with `dedupe=False`: each click is a GPU run of its own. The request is built and checked against the approved GPU API when the run is created, so `start` only submits it, and a later attempt sends the very same one:

```json
{
  "requested": "lab_image",
  "run_id": 14,
  "image_model": "qwen-image-2.1",
  "image_mode": "fast",
  "aspect_ratio": "9:16",
  "expected_size": { "width": 1536, "height": 2752 },
  "endpoint": "/v1/qwen-image21/images/generate",
  "request": { "prompt": "...", "mode": "fast", "seed": 91834, "aspect_ratio": "9:16" },
  "server_url": "http://host.docker.internal:8012"
}
```

`request` may also hold `num_inference_steps` (quality mode only, when the form set it) and `partition`. While it runs, `output` is the server's progress (`remote`). In one transaction at the end, the image goes into `media/lab/` as a `lab_image` (`origin='result'`, `output_index` 0, exactly as returned), the `lab_run` becomes `succeeded` (`seconds` is from the click, so it includes the wait for the GPU), and the job succeeds with `{"remote": {...}, "run_id": 14, "returned_size": {...}, "purge": {...}}`. At most 2 run at once (`jobs/generate_lab_image.CONCURRENCY_LIMIT`), in a pool of their own. The failure rules are those of `RemoteImageHandler` (`jobs/remote_image.py`).

### `asset.provenance`

An uploaded asset has no provenance. The shapes for an AI first frame, an AI last frame, the raw image behind them, a clip, a derived frame and the final video were removed with migration `0022`, because no code makes those assets now. An asset made earlier keeps the provenance it was written with. The shapes are at the tag `narration-final`.

### `job.input` and `job.output` for a `lab_video` job (Phase 19)

A `lab_video` job belongs to no project (`project_id` is NULL) and makes one clip on one model for the Video lab. It is a remote job (`provider='gpu'`: it is submitted, polled, downloaded, cleaned up and cancelled through the GPU server, with a retry after a pre-emption) and counts in the GPU pool (`max_parallel_gpu_jobs`) with every other GPU job. Its request is built and checked **when the run is created** (`services/video_lab.create_runs`, against the approved GPU API's limits, so a wrong request is refused before it costs a GPU run) and stored in `input` from the start. A resubmission sends that same request, with the same seed. Each click is a paid run of its own: none is merged into an earlier one.

```json
{
  "requested": "lab_video",
  "run_id": 2,
  "video_model": "ltx-2.5",
  "endpoint": "/v1/ltx25/videos/generate",
  "request": {
    "prompt": "A wide shot establishes ... A hard cut transitions to ...",
    "width": 1088, "height": 1920, "num_frames": 121, "frame_rate": 24.0, "seed": 42,
    "mode": "quality", "enhance_prompt": false
  },
  "first_frame": { "source": "lab", "id": 24 },
  "server_url": "http://host.docker.internal:8012",
  "uploads": [{ "filename": "lab-frame-lab-24.png", "remote_asset_id": "b8454c2be9594d408c8e4cb9c3157f76" }],
  "body": { "...": "request, plus images: [{asset_id, frame_idx: 0, strength: 1.0}] when there is a first frame" }
}
```

`first_frame` is null for text-to-video (no upload, and no `images` in the body). Since Phase 21 `last_frame` (same shape, null when there is none, and only with a first frame) names the image the clip ends on: both frames are fitted and uploaded, and the body goes to `/v1/ltx25/videos/interpolate` (`first_frame_asset_id`, `last_frame_asset_id`) or `/v1/ltx/videos/keyframe-interpolation` (`keyframes`). Each attempt fits the image to the run's size (centred) and uploads it again. An LTX-2.3 run has `negative_prompt` in `request` when the form gave one; an LTX-2.5 run never does. On success, in one transaction: `UPDATE lab_video_run` (`path`, `size_bytes`, `sha256`, `width`, `height`, `frame_count`, `duration_s`, `audio`), `UPDATE job` (`status='succeeded'`, `output`), and the clip is already in `media/lab/`:

```json
{
  "run_id": 2,
  "clip": { "frame_count": 121, "num_frames": 121, "width": 1088, "height": 1920, "fps": 24.0, "duration_s": 5.04,
            "size_bytes": 4119521, "audio": { "codec": "aac", "sample_rate": 48000, "channels": 2 } },
  "remote": { "status": "succeeded", "pipeline": "ltx25:text-to-video", "...": "..." },
  "purge": { "removed_asset_ids": [], "kept_asset_ids": [] }
}
```

The clip is not an `asset` (an asset belongs to a project): `lab_video_run.path` points at the file.

### `job.input` and `job.output` for a `write_lab_video_prompt` job (Phase 19)

One paid call to the language model that turns a short idea into a multi-shot prompt for LTX-2.5, for the Video lab. It belongs to no project, writes nothing to any table but its own `job` row, and is a local-style job (everything happens in `start`, no provider job id). It follows the other language model jobs: it starts only from a click, saves the exact request before the call and every answer the moment it arrives, tries at most twice (the second only for a rate limit, a server error, no answer or an unusable answer; a refusal is never retried), is never cached, and is never re-run by a restart (`never_rerun`). It uses `llm_base_url` and the `description_llm_model` setting.

```json
{
  "requested": "lab_video_prompt",
  "inputs": { "idea": "An old fisherman mends his net ...", "shots": 3, "duration_s": 9.0, "first_frame": "a grey harbour at dawn" },
  "profile": { "id": "ltx-2.5-multi-shot", "version": 1 },
  "instructions_sha256": "sha256:...",
  "server_url": "https://api-inference.bitdeer.ai/v1",
  "endpoint": "/chat/completions",
  "request": { "model": "zai-org/GLM-5.3", "messages": ["..."], "stream": true, "...": "..." }
}
```

`output` holds the attempts and token usage like the other model jobs, plus `answer` (the model's JSON, verbatim), and, on success, `prompt` (one line of text), `word_count`, `cuts` (how many cuts the prompt names), `warnings` (a list of text: the number of cuts differs from the shots asked for, a shot list, quoted words the idea did not give, a time, a word count outside 40 to 200) and `seconds`. The page puts `prompt` in the form only when the user chooses to.

**A lip-synced clip (Phase 24).** A `lab_video` job made for the Talking character lab has the endpoint `/v1/ltx/videos/audio-to-video` and one more key in `input`: `"audio": {"source": "voice_run" | "voice", "id": 3, "path": "lab/<32 hex>.wav", "mime": "audio/wav"}`, copied when the run is created (the same rule as a speech's reference voice). Its `request` has no `mode` and no `enhance_prompt` (the endpoint has neither), and `num_frames` is the smallest `8k + 1` that is at least as long as the speech. `start` uploads the first frame, then the speech, and sends `images` (the frame at index 0) and `audio_asset_id` with `audio_start_time: 0`; `submitted.uploads` lists both uploads. The finished clip keeps the speech as its sound, unchanged.

### `job.input` and `job.output` for a `write_talk_prompts` job (Phase 24)

One paid call to the language model that writes the two prompts of a take in the Talking character lab: `voice_instruction` (what steers Breeze TTS 2) and `video_prompt` (what the lip-sync video model shows: the speaker and the act of speaking, never the words, which it is given as audio). It belongs to no project and is a local-style job like `write_lab_video_prompt`, with the same rules (a click starts it, the request is saved before the call and every answer the moment it arrives, at most two tries, never cached, `never_rerun`). It is started by `POST /api/lab/talk/prompt-drafts` (the page fills its form from the output) or as the first step of a take, and then `lab_talk_run.prompt_job_id` points at it. When it finishes, the texts are copied onto that take where the take has none (what the author wrote stays), and a take set to continue by itself starts its next step.

```json
{
  "requested": "talk_prompts",
  "take_id": 7,
  "inputs": {
    "dialogue": "You shouldn't be up here after dark.",
    "character": "A lighthouse keeper in his sixties with a grey beard ...",
    "delivery": "Gruff but quietly worried.",
    "voice_kind": "design"
  },
  "profile": { "id": "ltx-2.3-audio-to-video", "version": 1 },
  "instructions_sha256": "sha256:...",
  "server_url": "https://api-inference.bitdeer.ai/v1",
  "endpoint": "/chat/completions",
  "request": { "model": "zai-org/GLM-5.3", "messages": ["..."], "stream": true, "...": "..." }
}
```

`take_id` is only there for a take's job. `character` is what the author wrote, else the cast character's description, else the prompt of the Image lab run that made the picture, else null. `voice_kind` is `design` (describe the voice and its delivery), `direction` (describe only the delivery) or `none` (a clone, or a reused speech: no instruction). `output` holds the attempts and token usage like the other model jobs, plus `answer` (the model's JSON, verbatim), and, on success, `voice_instruction` (empty when `voice_kind` is `none`), `video_prompt`, `word_count`, `warnings` (a list of text: a word count outside 40 to 140, quoted words, a cut or a time, subtitles) and `seconds`.

### `job.input` and `job.output` for a `lab_voice` job (Phase 21)

A `lab_voice` job is a remote job on the GPU server's Breeze TTS 2 endpoint (`POST /v1/breeze-tts/synthesize`), run by `jobs/synthesize_speech.py`. One request takes at most 1,000 characters of text, and makes about two minutes of speech at most (more is cut off by the server, not refused). The handler is written for a list of pieces made one after the other, each as a job on the server, all with the same recording, seed and guidance; a `lab_voice` run is always one piece. (Until migration `0022` a project's whole script was split into pieces here, to make its voiceover.)

`input` at creation (`reference` is null for `design`, and `instruction` null for `clone`):

```json
{
  "requested": "lab_voice",
  "run_id": 9,
  "mode": "clone",
  "chunks": ["The text to say."],
  "instruction": null,
  "seed": 42,
  "cfg_scale": 1.0,
  "reference": { "voice_id": 3, "path": "lab/5d1e...e2.wav", "mime": "audio/wav", "text": "Exactly what the recording says." }
}
```

`reference` copies the voice's path, mime and transcript as they are at that moment.

Each submission adds what was sent and where the job is:

```json
{
  "done": ["7a2c...", "b91d..."],
  "remote_reference_id": "3f2a9c1e4b7d4a6c9e8f1a2b3c4d5e6f",
  "server_url": "http://host.docker.internal:8012",
  "endpoint": "/v1/breeze-tts/synthesize",
  "body": { "text": "...", "seed": 42, "cfg_scale": 1.0,
            "reference_audio_asset_id": "3f2a...", "reference_text": "..." }
}
```

`done` holds the server's job ids of the pieces that are made, in order; `provider_job_id` is the piece being made. When it succeeds, `finish` adds it to `done` and submits the next piece (`UPDATE job` sets the new `provider_job_id` and `input` together), so a pre-emption (`requeue`, up to 3 attempts) or a restart continues with the first piece that is not in `done`, and the uploaded recording (`remote_reference_id`) is reused (a `400 invalid asset reference` uploads it again once). Nothing is purged on the server before the end, because purging a piece also deletes the uploads no other job uses.

After the last piece: every piece is downloaded to a temp file, joined with FFmpeg's concat demuxer into one mono 24 kHz 16-bit WAV (a single piece is used as it is), checked with ffprobe, and then, in one transaction, the file moves to `media/lab/`, `UPDATE lab_voice_run` (`path`, `size_bytes`, `sha256`, `duration_s`) and `UPDATE job` (`status='succeeded'`, `output`). Then every server job is purged and `output.purge` (one answer per piece) is merged in.

`output` of a `lab_voice` job is `{"run_id": 9, "speech": {"duration_s": 4.2, "sample_rate": 24000, "channels": 1, "size_bytes": 201644}}`. A job cannot be cancelled once it runs on the server.

### `job.input` and `job.output` for a `write_story_bible` job (PHASE-004)

A `write_story_bible` job belongs to a project (`project_id` set), is `provider='llm'` with the restart rule `never_rerun` (a backend restart fails it; the user presses Re-run), and is created with `dedupe=True`: while one is queued or running for the project, a second click returns that job. `services/story_bible.start_run` creates it with a **copy of the saved story**, so the version made is tied to the text saved when Run was pressed even if the story is edited while the job waits:

```json
{ "story_text": "When Arjun moved into his new apartment...", "story_sha256": "9f2c..." }
```

When the job starts it resolves the story model (`llm_target.resolve` with `STORY_MODEL_KEY`, the `llm_model` and `llm_provider` settings) and adds what it sent, before it sends it:

```json
{
  "story_text": "...", "story_sha256": "9f2c...",
  "instructions_sha256": "sha256:51ab...",
  "server_url": "https://api-inference.bitdeer.ai/v1",
  "endpoint": "/chat/completions",
  "request": { "model": "zai-org/GLM-5.3", "messages": [ {"role": "system", "content": "..."}, {"role": "user", "content": "<the story>"} ],
               "max_tokens": 12000, "stream": true, "response_format": {"type": "json_object"}, "reasoning_effort": "high" }
}
```

For Qwen3.8 `endpoint` is `/v1/qwen38/generate`, and only the messages of `request` are sent (the server uses its own token limit and always reasons). `jobs/llm_call.ask_model` makes at most two attempts: the second only for a rate limit, a server error, no answer, or an answer that cannot be used (cut off, not JSON, a missing field, a text over its limit). A refusal (HTTP 400, 401, 403, 404, 422) is never retried. After every attempt the job's `output` holds what is known so far:

```json
{
  "attempts": [ { "outcome": "answered", "http_status": 200, "message": null, "finish_reason": "stop",
                  "response_id": "...", "elapsed_s": 41.2,
                  "usage": { "prompt_tokens": 412, "completion_tokens": 903, "reasoning_tokens": 780 } } ],
  "answer": { "title": "...", "language": "en", "genre": ["..."], "...": "the checked content" },
  "answer_usable": true, "content": null, "usage": { "prompt_tokens": 412, "completion_tokens": 903, "reasoning_tokens": 780 }
}
```

`answer` is the **checked** content (the same object stored in `story_bible.content`), not the model's raw text; the raw text of the last unusable answer is kept in `content` (at most 20,000 characters) when no answer could be used. On success, in **one transaction**, the job inserts the `story_bible` row (the next version, `source='ai'`, `inputs.story_sha256` from the job's input) and finishes with `{...the output above, "content": null, "story_bible_id": 7, "version": 2, "seconds": 43.8}`. If the job was cancelled meanwhile, nothing is stored. If no answer could be used, the job fails with `error` = "The Story Bible could not be written: <why>", and no row is written.

### `job.input` and `job.output` for a `discover_characters` or `discover_environments` job (PHASE-005)

The two jobs have the same shape and differ only in the list they ask for. Each belongs to a project, is `provider='llm'` with the restart rule `never_rerun`, and is created with `dedupe=True`: while one of **its own type** is queued or running for the project, a second click returns that job. A character job and an environment job do not merge, so both can run at the same time. `services/discovery.start_run` creates the job only when the project has a saved story and a StoryBible that is up to date with it (otherwise the API answers 422), with a **copy of the saved story** and the **id and version of the StoryBible it will read**:

```json
{ "story_text": "When Arjun moved into his new apartment...", "story_sha256": "9f2c...",
  "story_bible_id": 7, "story_bible_version": 2 }
```

When the job starts it resolves the story model (the same `llm_model` and `llm_provider` settings as the Story Bible, D-12), loads the StoryBible row named by `story_bible_id` (a stored row never changes, so this is the bible that was current at the click; the job fails with "The Story Bible this run was started with could not be found." if it is missing), and adds what it sent, before it sends it: `instructions_sha256`, `server_url`, `endpoint` and `request`, as for the Story Bible. The `request` has the same fields as the Story Bible's; its system message is the kind's own instructions (minimal output, no appearance, wardrobe, voice or relations) and its user message is `STORY BIBLE (JSON):` followed by the bible's `content`, then `STORY:` followed by the story text. `jobs/llm_call.ask_model` makes at most two attempts under the rules described for the Story Bible, and `output` holds what is known after every attempt (`attempts`, `answer` = the **checked** content, `answer_usable`, `content`, `usage`). On success, in **one transaction**, the job inserts the row (`character_discovery` or `environment_discovery`: the next version, `source='ai'`, `inputs.story_sha256` from the job's input, `inputs.artifacts` = the StoryBible id and version) and finishes with `{...the output above, "content": null, "discovery_id": 3, "version": 2, "count": 4, "story_bible_version": 2, "seconds": 38.1}`. If the job was cancelled meanwhile, nothing is stored. If no answer could be used, the job fails with `error` = "The characters could not be found: <why>" (or "The environments could not be found: <why>"), and no row is written. The phase labels are `preparing the prompt`, `asking the language model (attempt N of 2)` and `saving the characters` or `saving the environments`.

For Qwen3.8 the limit of 32,000 characters of messages (Section 6) applies to the instructions (about 1,700 characters), the StoryBible (about 1,000) and the story together, so a story of more than about 29,000 characters is refused with a readable failure on the job.

### `job.input` and `job.output` for a `discover_scenes` job (PHASE-006)

The job is the third of the discovery family and shares its steps (`jobs/discovery_job.py`). Its `input` before it starts, its `output`, its restart rule, its phase labels and its `dedupe` rule are those of `discover_characters` above: the copy of the saved story, `story_sha256`, `story_bible_id` and `story_bible_version`; after the start, `instructions_sha256`, `server_url`, `endpoint` and `request`. It is its own job type, so a project's scene job, character job and environment job can all run at the same time (D-15), when the pools allow. Two things differ:

- The `request`'s system message is the scene instructions (`services/scene_discovery_writer.py`), and its user message is `STORY BIBLE (JSON):` and the bible's `content`, then `STORY:` and the story **exactly as saved, with no numbering or markers**. The model is asked for `id`, `title`, `description` and `starts_with` of each scene, and is never asked to copy the story.
- The checked content that is stored (and shown in `output.answer`) has the scenes placed in the story (Section 4.21), so `output.answer.scenes[].text` repeats each slice. `output` on success: `{...the attempts, answer, usage, "content": null, "discovery_id": 5, "version": 2, "count": 8, "story_bible_version": 2, "seconds": 41.0}`. An answer whose opening words cannot be placed is an unusable attempt (`attempts[].message` says which scene and why), retried once with the same request; if no answer could be used, the job fails with `error` = "The scenes could not be found: <why>" and no row is written. The phase labels are `preparing the prompt`, `asking the language model (attempt N of 2)` and `saving the scenes`.

For Qwen3.8 the limit of 32,000 characters of messages (Section 6) applies to the instructions (about 3,800 characters), the StoryBible (about 1,000) and the story together, so a story of more than about 27,100 characters is refused with a readable failure on the job.

### `job.input` and `job.output` for a `define_character` job (PHASE-009)

One job per character. It belongs to a project, is `provider='llm'` with the restart rule `never_rerun`, and is created with `dedupe_key="discovery_id"`: while a `define_character` job of **that character** (the same `input.discovery_id`) is queued or running for the project, a second click returns that job. A job for another character does not merge, so the characters of a story are defined side by side when the pool allows. `services/character_definitions.start_run` creates the job only when the project has a saved story, a StoryBible that is up to date with it, a list of characters, and a link for the character that is not archived (otherwise the API answers 422), with a copy of everything the job needs, **as it was when the button was pressed**:

```json
{ "story_text": "When Arjun moved into his new apartment...", "story_sha256": "9f2c...",
  "story_bible_id": 7, "story_bible_version": 2, "discovery_version": 3, "discovery_id": "arjun",
  "entry": { "id": "arjun", "name": "Arjun", "description": "A shy engineer in his thirties." },
  "others": [ { "id": "meera", "name": "Meera", "description": "..." } ],
  "character_id": 12,
  "inputs": { "project_id": 4, "discovery_id": "arjun", "story_sha256": "9f2c...", "entry_sha256": "51ab...",
              "artifacts": [ { "kind": "story_bible", "id": 7, "version": 2 },
                             { "kind": "character_discovery", "id": 9, "version": 3 } ] } }
```

`inputs` is written onto the version the job makes (Section 4.27). When the job starts it resolves the story model (D-12), loads the StoryBible row named by `story_bible_id` and the library character named by `character_id` (the job fails with "The Story Bible this run was started with could not be found." or "The Character Lab character this run was started with could not be found." if either is missing), and adds what it sent, before it sends it: `instructions_sha256`, `server_url`, `endpoint` and `request`. The `request` is built by `services/character_definition_writer.build_request`. Its system message is the definition instructions (4,200 characters, which give the model the answer form, the limit of each text field and the era rules). Its user message is, in this order: `STORY BIBLE (JSON):` and the bible's `content`; `CHARACTER TO DEFINE (JSON):` and `entry`; `OTHER CHARACTERS (JSON):` and `others` (the model reads the story and these, so a younger self or a mother and son can resemble each other: relations are not stored, D-14); `CURRENT PROFILE:` and the library character's profile as text (`character_library.character_card`), **only when the character already has an appearance**, so the definition keeps to what a person wrote; `TODAY'S YEAR:`; and `STORY:` and the story text. The `request` asks for JSON, with `max_tokens` 12,000 and `reasoning_effort` `high`. `jobs/llm_call.ask_model` makes at most two attempts under the rules in Section 5 for the Story Bible, and `output` holds what is known after every attempt (`attempts`, `answer` = the **checked** definition, `answer_usable`, `content`, `usage`).

On success, in **one transaction**, `character_definitions.save_definition` writes the definition and the profile fields onto the library character and adds a `library_character_version` row (`source='ai'`, `job_id`, `inputs`), moves `project_character_link.pinned_version` to it, and the job finishes with `{...the output above, "content": null, "character_id": 12, "version": 4, "seconds": 52.3}`. If the job was cancelled meanwhile, nothing is stored. If the link was removed or moved to another character while the model was answering, the job fails with "The definition of Arjun could not be saved: <why>" and nothing is stored. If no answer could be used, the job fails with "The definition of Arjun could not be written: <why>". The phase labels are `preparing the prompt`, `asking the language model (attempt N of 2)` and `saving the definition`.

For Qwen3.8 the limit of 32,000 characters of messages (Section 6) applies to the instructions (4,200 characters), the StoryBible (about 1,000), the character, the other characters, the current profile and the story together, so a long story or a large cast can be refused with a readable failure on the job (this is an estimate: a story above about 25,000 characters is likely to fail).

### `job.input` and `job.output` for a `design_voice` job (PHASE-011)

One job per voice (one character, or the narrator). It belongs to a project, is `provider='llm'` with the restart rule `never_rerun`, uses the **story model** (D-12) and is created with `dedupe_key="target"`: while a `design_voice` job with the same `input.target` (`character:<discovery_id>` or `narrator`) is queued or running for the project, a second click returns that job. `services/story_voices` creates it only when the voice may start (the rules of Section 7), with a copy of everything it needs as it was when the button was pressed:

```json
{
  "target": "character:arjun",
  "subject": "character",
  "project_id": 1,
  "discovery_id": "arjun",
  "character_id": 3,
  "name": "Arjun",
  "facts": {"sex": "...", "species": "...", "apparent_age": 27, "age_character": "...", "pitch": "...", "texture": "...", "accent": "...", "default_energy": "...", "baseline_behavior": "..."},
  "line": "The sentence the sample will read.",
  "inputs": {"project_id": 1, "discovery_id": "arjun", "character_id": 3, "character_version": 4, "voice_facts_sha256": "..."}
}
```

For the narrator, `target` is `narrator`, `subject` is `narrator`, `discovery_id` and `character_id` are null, `facts` is `{"narration_style", "tone", "genre"}`, `line` is the start of the story and `inputs` is `{"project_id", "story_bible_version", "narration_sha256"}`. When the handler starts it adds `instructions_sha256`, `server_url`, `endpoint` and the exact `request` (D-3). `output` has the attempts, the usage counts and the answer (as every paid call, `jobs/llm_call.py`), plus `instruction` (the checked voice description: one line of at most 500 characters, the Breeze TTS limit) and `run_id` (the `lab_voice_run` queued in the same transaction that marked the job succeeded). The job's phases are `preparing the prompt`, `asking_model` (from `jobs/llm_call.py`) and `saving the voice description`.

### The character definition (PHASE-009)

`library_character.definition` and `library_character_version.definition` hold this JSON (`services/character_definition_writer.check_definition` makes it from the model's answer). **Code sets `id`** to the discovered character's slug and never reads it from the model; only the fields below are kept, in this order, and each text is a single line with a character limit:

```json
{
  "id": "arjun",
  "visual_identity": {
    "apparent_age": 31, "sex": "male", "species": "human", "has_visible_mouth": true,
    "build": "lean", "height_character": "tall", "skin_tone": "olive", "face_shape": "oval",
    "hair": "short black hair", "eyes": "dark brown", "distinctive_features": "a scar on the left cheek"
  },
  "default_wardrobe": { "upper": "grey coat", "lower": "dark trousers", "footwear": "leather boots" },
  "voice_identity": { "age_character": "adult", "pitch": "low", "texture": "warm", "accent": "neutral", "default_energy": "calm" },
  "behavior": { "baseline": "watchful and quiet", "gesture_style": "small and careful" },
  "era": { "kind": "present", "years": null, "setting": null }
}
```

`apparent_age` is a whole number or null; `sex` and `species` are lower case; `has_visible_mouth` must be a true or false value; `era.kind` is `present`, `past` or `future`, and `years` (1 to 10,000) is needed for the last two (a present era that came with years is accepted with the years dropped). `visual_identity.species`, `visual_identity.has_visible_mouth` and the top-level `era` go beyond `Path_ahead.md` Section 11 (owner decision, 2026-10-20), because the lab profile needs them. The text limits are: `build` 80, `height_character` 80, `skin_tone` 120, `face_shape` 120, `hair` 200, `eyes` 120, `distinctive_features` 300; `upper` 150, `lower` 150, `footwear` 100; `age_character` 60, `pitch` 40, `texture` 120, `accent` 80, `default_energy` 60; `baseline` 300, `gesture_style` 200. They are chosen so that every profile field written from them fits that field's own limit in `services/character_library.py` (`check_definition` checks it).

**The mapping into the profile** (`character_definition_writer.to_profile`, pure: the same definition always gives the same text). It overwrites exactly these fields of `library_character` and never `name` or `notes`:

| Profile field | Written from |
|---|---|
| `age`, `gender`, `species`, `has_visible_mouth` | `apparent_age`, `sex`, `species`, `has_visible_mouth` |
| `appearance` | `Build: … Height: … Skin tone: … Face shape: … Hair: … Eyes: … Distinctive features: ….` |
| `outfit` | `Upper: …; Lower: …; Footwear: ….` |
| `personality` | `{baseline}. Gesture style: {gesture_style}.` |
| `voice_description` | `Age: … Pitch: … Texture: … Accent: … Default energy: ….` |
| `era_kind`, `era_years`, `era_setting` | `era.kind`, `era.years`, `era.setting` |

The longest the four text fields can be is 1,105 (`appearance`), 429 (`outfit`), 518 (`personality`) and 414 (`voice_description`) characters, all inside their limits. `character_card` and the lab's prompt writers read these fields as they always did, so a defined character works with them unchanged.

**When a definition is current.** A project's definition of a character is the **pinned version**, when that version has a `definition` and its `inputs` name this project and this character of the list. A pinned version made by hand, or defined for another project, is not shown as this project's definition. It is out of date when, **on this read**: the story text hashes differently from `inputs.story_sha256`; or the newest StoryBible is newer than the one in `inputs.artifacts` (or none is recorded); or `inputs.entry_sha256` differs from the hash of the entry's current name and description. Nothing of this is stored (Section 2.1).

### `library_environment_version.profile` (PHASE-012)

The profile as it was when the version was added. It always has all seven keys, whatever they hold:

```json
{
  "name": "Old apartment",
  "description": "A third-floor flat with peeling green wallpaper, a cast-iron radiator under a tall window and a worn oak floor.",
  "era_kind": "past",
  "era_years": 40,
  "era_setting": "A city in the 1980s",
  "atmosphere": "Dusty afternoon light, quiet",
  "notes": null
}
```

`era_kind` is `present`, `past` or `future`; `era_years` (1 to 10,000) is a whole number for `past` and `future` and null for `present`; the other optional fields are null when empty. The text is trimmed before it is stored (the optional fields also have their runs of spaces made single), so two forms that differ only in spaces make one version.

### `job.input` and `job.output` for a `write_environment_prompt` job (PHASE-012)

One job per attempt. It is a lab job (`project_id` NULL), `provider='llm'`, restart rule `never_rerun`, uses the **image-prompt model** (the same setting as the Character lab's prompt writers) and is created with `dedupe=False`, so two presses make two jobs (a press while a prompt is being written for the same version is refused before that). `input` starts as `{"environment_id", "reference_id", "version"}`; when the job starts it adds `profile` (`{"id": "qwen-image-2.1-environment-sheet", "version": 1}`, the prompt profile), `instructions_sha256`, `server_url`, `endpoint` and the exact chat `request`. `output` holds the model's answer record and: `image_prompt` (the text saved as `environment_reference.prompt`), `word_count`, `warnings` and `seconds`. The prompt describes the empty place only, wide and with no people, because the place is the background of later pictures. A failed job marks its attempt `failed` with the reason. Since PHASE-013 the job reads the profile of **the attempt's own version** (`environment_reference.version_id`) and not the head, so a version's picture is always drawn from the text that version froze; it falls back to the head only for an attempt with no version, which cannot be made.

### The environment definition (PHASE-013)

`library_environment.definition` and `library_environment_version.definition` hold this JSON (`services/environment_definition_writer.check_definition` makes it from the model's answer). **Code sets `id`** to the discovered environment's slug and never reads it from the model; only the fields below are kept, in this order, and each text is a single line with a character limit. It follows `Path_ahead.md` Section 13 and adds one top-level key, `era` (owner decision, 2026-10-21), because the lab profile needs it, as the character definition does. Section 13's "scenes using the environment" is **not stored**: scene discovery records no environment ids (D-15), so the model works out for itself in which scenes the place appears and designs it for all of them.

```json
{
  "id": "apartment",
  "architecture": "A small mid-century brick apartment block.",
  "layout": "One bedroom, a narrow hall and an open kitchen with a window onto the lane.",
  "visual_identity": {
    "walls": "Cream plaster, stained near the ceiling.",
    "floor": "Red oxide tiles.",
    "windows": "Two wooden shuttered windows.",
    "doors": "One heavy teak front door.",
    "furniture": "A steel cot and a small wooden table.",
    "color_palette": "Cream, red oxide, teak brown."
  },
  "important_landmarks": ["teak front door", "steel cot"],
  "atmosphere": { "baseline": "Quiet and warm, lit by soft daylight." },
  "continuity_rules": ["The teak door is always on the left."],
  "era": { "kind": "past", "years": 20, "setting": "2000s Mumbai" }
}
```

The text limits are: `architecture` 140, `layout` 240, `walls` 130, `floor` 90, `windows` 90, `doors` 90, `furniture` 160, `color_palette` 120, `atmosphere.baseline` 300; `important_landmarks` holds from 1 to 6 items of at most 50 characters and `continuity_rules` from 1 to 4 items of at most 100. `era.kind` is `present`, `past` or `future`, and `years` (1 to 10,000) is needed for the last two (a present era that came with years is accepted with the years dropped). They are chosen so that the two profile fields written from them fit the lab's own limits (`check_definition` checks it).

**The mapping into the profile** (`environment_definition_writer.to_profile`, pure: the same definition always gives the same text). It overwrites exactly these fields of `library_environment` and never `name` or `notes`:

| Profile field | Written from |
|---|---|
| `description` | `Architecture: … Layout: … Walls: … Floor: … Windows: … Doors: … Furniture: … Colour palette: … Landmarks: …; …. Continuity: …; ….` |
| `atmosphere` | `{atmosphere.baseline}.` |
| `era_kind`, `era_years`, `era_setting` | `era.kind`, `era.years`, `era.setting` |

The longest the description can be is 1,897 characters and the atmosphere 301, both inside their limits (2,000 and 500). The lab's prompt writer reads `description`, `atmosphere` and the era as it always did, so a defined environment works with it unchanged.

**When a definition is current.** A project's definition of an environment is the **pinned version**, when that version has a `definition` and its `inputs` name this project and this entry of the list. A pinned version made by hand, or defined for another project, is not shown as this project's definition. It is out of date when, **on this read**: the story text hashes differently from `inputs.story_sha256`; or the newest StoryBible is newer than the one in `inputs.artifacts`; or the newest list of scenes is newer than the one in `inputs.artifacts` (or none is recorded); or `inputs.entry_sha256` differs from the hash of the entry's current name and description. Nothing of this is stored (Section 2.1).

### `job.input` and `job.output` for a `define_environment` job (PHASE-013)

One job per environment. It belongs to a project, is `provider='llm'` with the restart rule `never_rerun`, uses the **story model** (D-12) and is created with `dedupe_key="discovery_id"`: while a `define_environment` job of **that environment** (the same `input.discovery_id`) is queued or running for the project, a second click returns that job; jobs for other environments run side by side when the pool allows. `services/environment_definitions.start_run` creates the job only when the project has a saved story, a StoryBible and a list of scenes that are up to date with it, a list of environments, and a link for the environment that is not archived (otherwise the API answers 422), with a copy of everything the job needs, **as it was when the button was pressed**:

```json
{ "story_text": "Maya lives in a small apartment in Mumbai...", "story_sha256": "9f2c...",
  "story_bible_id": 7, "story_bible_version": 2, "discovery_version": 3, "discovery_id": "apartment",
  "entry": { "id": "apartment", "name": "Apartment", "description": "Maya's flat." },
  "others": [ { "id": "bakery", "name": "Bakery", "description": "Where she works." } ],
  "scenes": [ { "index": 1, "id": "morning-walk", "title": "Morning walk", "description": "...", "starts_with": "Every morning" } ],
  "environment_id": 12,
  "inputs": { "project_id": 4, "discovery_id": "apartment", "story_sha256": "9f2c...", "entry_sha256": "51ab...",
              "artifacts": [ { "kind": "story_bible", "id": 7, "version": 2 },
                             { "kind": "environment_discovery", "id": 9, "version": 3 },
                             { "kind": "scene_discovery", "id": 5, "version": 1 } ] } }
```

`inputs` is written onto the version the job makes (Section 4.32). When the job starts it resolves the story model (D-12), loads the StoryBible row named by `story_bible_id` and the library environment named by `environment_id` (the job fails with "The Story Bible this run was started with could not be found." or "The Character Lab environment this run was started with could not be found." if either is missing), and adds what it sent, before it sends it: `instructions_sha256`, `server_url`, `endpoint` and `request`. The `request` is built by `services/environment_definition_writer.build_request`. Its system message is the definition instructions (about 3,700 characters, which give the model the answer form, the limit of each text field and the era rules). Its user message is, in this order: `STORY BIBLE (JSON):` and the bible's `content`; `ENVIRONMENT TO DEFINE (JSON):` and `entry`; `OTHER ENVIRONMENTS (JSON):` and `others` (so a room inside a building can share its style); `SCENES (JSON):` and `scenes` (the position, id, title, description and opening words of each scene, without its text); `CURRENT PROFILE:` and the library environment's profile as text (`environment_library.card_from_profile`), **only when the environment already has a definition or its newest version was made by hand**, so the definition keeps to what a person wrote and a brand-new pipeline environment is not tied to the placeholder era it started with; `TODAY'S YEAR:`; and `STORY:` and the story text. The `request` asks for JSON, with `max_tokens` 12,000 and `reasoning_effort` `high`. `jobs/llm_call.ask_model` makes at most two attempts, and `output` holds what is known after every attempt (`attempts`, `answer` = the **checked** definition, `answer_usable`, `content`, `usage`).

On success, in **one transaction**, `environment_definitions.save_definition` writes the definition and the profile fields onto the library environment, adds a `library_environment_version` row (`source='ai'`, `job_id`, `inputs`), moves `project_environment_link.pinned_version` to it, and, when that version has no picture, `INSERT environment_reference` (`project_id`, `discovery_id`, `status='writing_prompt'`, `version_id` = the new version) and `INSERT job` (`type='write_environment_prompt'`) for its canonical picture. The job finishes with `{...the output above, "content": null, "environment_id": 12, "version": 2, "seconds": 41.0}`. If the job was cancelled meanwhile, nothing is stored. If the link was removed or moved to another environment while the model was answering, the job fails with "The definition of Apartment could not be saved: <why>" and nothing is stored. If no answer could be used, the job fails with "The definition of Apartment could not be written: <why>". The phase labels are `preparing the prompt`, `asking the language model (attempt N of 2)` and `saving the environment definition`. If the picture cannot be started (for example the GPU image endpoint is missing), the definition is still saved, and the stage shows the picture as `failed` with a Retry button.

For Qwen3.8 the limit of 32,000 characters of messages (Section 6) applies to the instructions (about 3,700 characters), the StoryBible (about 1,000), the environment, the other environments, the scenes (roughly 250 characters each, estimated), the current profile and the story together, so a long story or many scenes can be refused with a readable failure on the job (this is an estimate, not measured: a story above about 20,000 characters is likely to fail).

---

## 6. Global settings stored in `setting`

(Source: Section 3.7.) Only the **globally** scoped rows from that section's table belong here. The **project**-scoped ones are columns on `project` (Section 4.1), not rows here.

| `key` | Example `value` | Default |
|---|---|---|
| `gpu_api_base_url` | `"http://host.docker.internal:8012"` | first-run default from `GPU_API_BASE_URL` env var |
| `transcription_url` | `""` | blank = same as `gpu_api_base_url` |
| `gpu_partition` | `""` | blank = cluster default |
| `llm_base_url` | `"https://api-inference.bitdeer.ai/v1"` | from `BITDEEP_BASE_URL` env var |
| `llm_provider` | `"bitdeer"` | where the **story role** ("Story provider") is answered: `bitdeer` (GLM, the model below) or `qwen38` (Qwen3.8-27B on the GPU server, `POST /v1/qwen38/generate`, reasoning on, at `gpu_api_base_url`). A fixed list of choices. Every story stage uses this one role (D-12): since PHASE-004 the Story Bible, and since PHASE-005 character and environment discovery. Qwen3.8 ignores `max_tokens` and accepts at most 32,000 characters of messages, so with the Story Bible's instructions (about 1,800 characters; discovery adds the bible, about 1,000 more, so its limit is about 29,000) a story of more than about 30,000 characters (roughly 5,000 words: about 33 minutes at the default pace, well above the 10-minute limit of D-13) is refused on Qwen3.8 and needs Bitdeer |
| `llm_model` | `"zai-org/GLM-5.3"` | the Bitdeer model for the story role (the full GLM-5.3, not Flash; the default was `zai-org/GLM-5.3-Flash` until PHASE-004, and a value already saved is kept); not used when `llm_provider` is `qwen38` |
| `description_llm_provider` | `"bitdeer"` | the same choice for the description role (the Video lab's prompt writer and the character take prompts) |
| `description_llm_model` | `"zai-org/GLM-5.3"` | the Bitdeer model that writes the Video lab and character take prompts; uses `llm_base_url`; not used when `description_llm_provider` is `qwen38` |
| `image_prompt_llm_provider` | `"bitdeer"` | the same choice for the image prompt role (the character look prompts) |
| `image_prompt_llm_model` | `"zai-org/GLM-5.3-Flash"` | the Bitdeer model that writes the image prompt of a character look; uses `llm_base_url`; not used when `image_prompt_llm_provider` is `qwen38` |
| `image_mode` | `"quality"` | how Qwen-Image-2.1 makes the Character lab's pictures (Phase 22; it replaces `image_model`, which named a Bitdeer model): `quality` (the base model, 40 steps) or `fast` (the Turbo model, 8 steps). A fixed list of choices. The two are different models, so one seed gives a different picture in each. The Image lab chooses its own mode |
| `h3_min_shot_seconds` | `1` | whole seconds, from 1 to 14. The shortest shot MiniMax H3 may be asked for (PHASE-002; 1 s = 39 frames, safe per PHASE-001 V1). A shot below it never reaches generation. Must be at or below `shot_target_min_seconds` |
| `shot_target_min_seconds` | `2` | whole seconds, from 1 to 14. The shortest shot the planning stages are asked for. Passed to prompts as a parameter, never written into prompt text. Must be between `h3_min_shot_seconds` and `shot_target_max_seconds` |
| `shot_target_max_seconds` | `10` | whole seconds, from 1 to 14. The longest shot the planning stages are asked for. Must be between `shot_target_min_seconds` and `h3_max_shot_seconds` |
| `h3_max_shot_seconds` | `14` | whole seconds, from 1 to 14. The longest shot H3 may be asked for. The upper limit is `H3_MAX_FRAMES // H3_FPS` (345 frames at 24 fps is 14.375 s); 15 s would need 362 frames. Must be at or above `shot_target_max_seconds` |
| `story_words_per_minute` | `150` | from 60 to 300 (PHASE-003, group `Story`). The speaking pace used to estimate a story's finished length: its word count divided by this. A common narration pace, a starting value and not a measurement. Affects only the estimate (`services/story_length.py`) |
| `story_max_minutes` | `10` | from 1 to 120 (PHASE-003, group `Story`; D-13). A story estimated above this many minutes shows a warning on the project page. It is never refused: the story still saves |
| `max_parallel_gpu_jobs` | `4` | from 1 to 100. How many jobs run on the GPU server at once, **all kinds together**: the labs' images, clips and speeches, and the language-model calls (the story stages included) set to the GPU server's Qwen3.8. Each image job loads about 31 GB of model weights first, so the number should be one your GPU server can handle. Replaces `max_parallel_generations` and `max_parallel_image_generations` |
| `max_parallel_paid_api_calls` | `8` | from 1 to 100. How many calls run on the paid inference API (Bitdeer) at once, **all kinds together**: the story stages and the Video lab and Character lab prompts, for the roles whose provider is Bitdeer |
| `poll_interval_seconds` | `15` | |
| `api_contract_sources` | `[{"name": "guide", "base": "gpu", "path": "/v1/guide?format=json"}, {"name": "openapi", "base": "gpu", "path": "/openapi.json"}]` | the two sources shown, no environment variable (Phase 4) |

`api_contract_sources` is a list, not a text or number, so it has its own endpoints (`PUT` and `DELETE /api/gpu/contract/sources`) and the generic settings API answers 404 for it. Each entry has a `name` (`[a-z0-9][a-z0-9_-]{0,39}`, unique, and it is what `api_snapshot.source` holds), a `base` (`gpu` means the GPU server URL, `transcription` means the transcription URL, which falls back to the GPU server URL when blank) and a `path` (starts with one `/`, at most 500 characters, no whitespace and no `#`; a query string is allowed). One to five entries, and no two with the same `base` and `path`. This replaces the earlier example `["guide", "openapi"]`, which could not say which server a source lives on.

Precedence, per Section 3.7: a value saved here wins; if no row exists for a key, the backend falls back to the matching environment variable (first-run default); if neither exists, a built-in default. Secrets (`BITDEEP_API_KEY`) are **never** stored in this table — they stay in `.env` only, per Section 3.7's rule that secrets stay out of the UI entirely.

**Internal rows (added in Phase 2).** The table also holds rows the app writes for itself. They are not settings: the settings API never lists, saves or resets them, and they are not in the table above. They live in the same table so that remembered state needs no new table or migration. The code lists them in `INTERNAL_KEYS` (`backend/app/core/settings.py`), and a new one must be added there.

| `key` | `value` | Written by |
|---|---|---|
| `gpu_connection_last_test` | `{reachable, called_url, elapsed_ms, http_status, default_partition, error, checked_at}` — the last GPU server connection test. `called_url` is the address after Docker mapping. The result counts only while it matches the address that would be called now, so a test of an old URL never stands in for the current one. | The Test connection button (Phase 2), through `app/services/gpu_status.py`. Phase 4's banner reads it, and later phases (the contract guard, the dispatcher) may write it through the same module (ANALYSIS.md Section 3.3, "Keeps the DB current"). |
| `gpu_contract_last_check` | `{status, checked_at, sources: [{name, called_url, status, message, approved_fingerprint, current_fingerprint}]}` — the last check of the recorded GPU API. `status` is `ok`, `changed`, `not_approved` or `unreachable` (per source also `unreadable`). It counts only while its sources and `called_url`s equal the ones that would be used now. "Not approved" is never read from here: it is computed from `api_snapshot` on every read. | `contract_guard.check()` and `approve()` (Phase 4), read through `gpu_status.system_status()` for the banner on every page. |

---

## 7. How the pipeline writes to these tables

Mapping the flow onto table writes, so the structure's fit with the actual workflow is traceable step by step. Since migration `0022` the rows below are the project's own and the labs'; the table writes of the narration steps (transcription, scene planning, descriptions, prompts, frames, clips, the render, the cast, the automatic run and the voiceover) are at the tag `narration-final`.

| Step (Section 1 flow) | Tables touched |
|---|---|
| Create project, pick orientation | `INSERT project` (orientation + size/fps defaults filled in per orientation) |
| Paste the story | `UPDATE project.script_text` (PHASE-003). The estimated length is not written: `GET /api/projects/{id}` works it out from the text and the two `Story` settings on every read |
| Test an image model by hand (Image lab) | **Run on Seedream** (Phase 13): one synchronous call, not a `job` (a call of 25 to 40 s that the page waits for; the Video lab below, whose runs take minutes, does use jobs). The endpoint validates the form, reads each reference (a `lab_image` or a `kind='frame'` `asset`, as an upright RGB JPEG at quality 90, scaled down above 36 megapixels), and ends its read transaction before the call. The call runs in a task of its own, so a browser that goes away does not lose it. **After the call**, in one transaction: `INSERT lab_run` (the form, the request and the answer with every image replaced by its size, `http_status`, `seconds`, `usage`, `error`) and one `INSERT lab_image` (`origin='result'`) for each returned image, whose file was first checked with Pillow and moved to `media/lab/`. A call that failed, was refused or was ignored is a `lab_run` too (`status='failed'`, with `error`). **Upload**: `INSERT lab_image` (`origin='upload'`) after the image is checked. Nothing is retried, cached or deleted, and no `asset` row is written: a project's frame is only read, by its `asset` id. **Run on Qwen-Image-2.1** (Phase 22): not a synchronous call, because it takes minutes. `POST /api/lab/images/qwen-runs` validates the form and checks that the approved GPU API has the image endpoint (422 otherwise), then, in one transaction: `INSERT lab_run` (`status='running'`, `endpoint='/v1/qwen-image21/images/generate'`, `params`, the request), `INSERT job` (`type='lab_image'`, `provider='gpu'`, `project_id` NULL, `dedupe=False`, `input.run_id`) and `UPDATE lab_run.job_id`. It answers 202 at once, and the page polls the run. The job submits, is polled, and its `finish` step, in one transaction, does `INSERT lab_image` (`origin='result'`, the file moved to `media/lab/`), `UPDATE lab_run` (`status='succeeded'`, `seconds`, `response`) and `UPDATE job` (`succeeded`). A job that fails or is cancelled leaves `lab_run.status='running'`; the API reports such a run as `failed` from the job's status and error. |
| Try prompts on both models, with cuts (Video lab) | **Run** (Phase 19): `INSERT lab_video_run` and `INSERT job` (`type='lab_video'`, `provider='gpu'`, `project_id` NULL) for each chosen model, in **one transaction**, only from a click. Every request is built and checked first, against the limits of the approved GPU API (a model the approved API has no endpoint for refuses the whole click), with the same seed, size, length, recipe, prompt and first frame for both, and `lab_video_run.job_id` is set. The dispatcher starts the jobs while the GPU pool (`max_parallel_gpu_jobs`) has free slots. **Start**: the first frame (if any) is fitted to the run's size and uploaded, and the job is submitted to the stored endpoint, `UPDATE job` setting `provider_job_id` and the exact body. **On success**, in one transaction: the file moves to `media/lab/`, `UPDATE lab_video_run` (the file and what ffprobe read) and `UPDATE job` (`status='succeeded'`, `output`); then the server's job is purged. Nothing is retried beyond pre-emption and an expired result, cached, merged or deleted, and no `asset` row is written. **Write a multi-shot prompt**: `INSERT job` (`type='write_lab_video_prompt'`, `provider='llm'`, `project_id` NULL) with the idea in `input.inputs`; its answer is `job.output.prompt`, and nothing else is written. The Activity page lists both under "Video lab". |
| Write the Story Bible (PHASE-004) | `POST /api/projects/{id}/story-bible/run`: `INSERT job` (`type='write_story_bible'`, `provider='llm'`, `project_id` set, `dedupe=True`, `input` = a copy of `script_text` and its SHA-256). Nothing is written to `story_bible` yet. **Start**: `UPDATE job.input` with the exact request, then the paid call (`jobs/llm_call.ask_model`, at most two attempts, `output` updated after every attempt). **On success**, in one transaction: `INSERT story_bible` (the next version, `source='ai'`, `inputs.story_sha256`, `content`) and `UPDATE job` (`succeeded`, `output.story_bible_id`, `output.version`). A job that fails writes no row. Re-running adds a version and changes no earlier row. **Out of date** is computed by `GET .../story-bible` on every read: nothing is written when the story is edited |
| Find the characters and the environments (PHASE-005) | `POST /api/projects/{id}/discovery/{kind}/run` (`kind` is `characters` or `environments`): refused with 422 when there is no saved story, no `story_bible` row, or the newest `story_bible` is out of date with the story. Otherwise `INSERT job` (`type='discover_characters'` or `'discover_environments'`, `provider='llm'`, `project_id` set, `dedupe=True` per type, `input` = a copy of `script_text`, its SHA-256 and the StoryBible's id and version). Nothing is written to the discovery tables yet. The two jobs may run at the same time. **Start**: load the `story_bible` row, `UPDATE job.input` with the exact request, then the paid call (`jobs/llm_call.ask_model`, at most two attempts). **On success**, in one transaction: `INSERT character_discovery` (or `environment_discovery`: the next version, `source='ai'`, `inputs`, `content`) and `UPDATE job` (`succeeded`, `output.discovery_id`, `output.version`). A job that fails writes no row. Re-running adds a version and changes no earlier row. **Out of date** is computed by `GET .../discovery/{kind}` on every read: nothing is written when the story is edited or the StoryBible is re-run |
| Divide the story into scenes (PHASE-006) | `POST /api/projects/{id}/scenes/run`: refused with 422 on the same conditions as the discovery runs above (no saved story, no `story_bible` row, or the newest one out of date). Otherwise `INSERT job` (`type='discover_scenes'`, `provider='llm'`, `project_id` set, `dedupe=True`, `input` = a copy of `script_text`, its SHA-256 and the StoryBible's id and version). It may run at the same time as the two discovery jobs. **Start**: load the `story_bible` row, `UPDATE job.input` with the exact request, then the paid call (`jobs/llm_call.ask_model`, at most two attempts). Each answer is checked and **placed in the story by code** (`scene_discovery_writer.check_scenes`: the opening words are located, and every scene's `start`, `end` and `text` are cut from the saved story). **On success**, in one transaction: `INSERT scene_discovery` (the next version, `source='ai'`, `inputs`, `content`) and `UPDATE job` (`succeeded`, `output.discovery_id`, `output.version`). A job that fails writes no row. Re-running adds a version and changes no earlier row. **Out of date** is computed by `GET .../scenes` on every read: nothing is written when the story is edited or the StoryBible is re-run |
| Make speech in the Voice lab, and save voices | **Run** (Phase 21): `INSERT lab_voice_run` and `INSERT job` (`type='lab_voice'`, `provider='gpu'`, `project_id` NULL) in **one transaction**, only from a click, after the form is checked (mode and its fields, 1,000 characters of text, a saved voice for clone and direction); `lab_voice_run.job_id` is set. **Start**: the saved voice's recording is uploaded once, the job is submitted and `UPDATE job` sets `provider_job_id` and the exact body. **On success**: see Section 5. **Save a voice**: `INSERT voice` from an upload (the file goes to `media/lab/` after ffprobe accepts it) or from a finished run (the voice points at the run's file; the transcript starts as the run's text). Editing a voice is `UPDATE voice` of `name` and `transcript` only. Nothing is retried beyond pre-emption, cached, merged or deleted. The Activity page lists the jobs under "Voice lab". |
| Make and change a library character (Character lab; versions: PHASE-007) | `POST /api/lab/characters`: `INSERT library_character` and, in the same transaction, `INSERT library_character_version` (version 1). Every later change calls `character_versions.record_version_if_changed` **before its own commit**: it builds a snapshot of the character (the twelve profile fields, `voice_id`, `voice_description`, and the current look with the `lab_image_id` and `cutout_path` of each angle), compares it with the newest version, and does `INSERT library_character_version` (the next number, `source='manual'`) only if something differs. The changes that call it: `PATCH /api/lab/characters/{id}` with profile fields (`UPDATE library_character`), `PUT .../voice` and `PUT .../voice/description` (`UPDATE library_character.voice_id` or `voice_description`), a look turning `ready` (`character_looks._maybe_mark_ready`: `UPDATE character_look.status`, `UPDATE library_character.current_look_id`), and `PUT .../current-look` (`UPDATE library_character.current_look_id` to an earlier `ready` look). **Archiving** (`PATCH` with `archived`) writes no version. **Redo an angle**: `UPDATE character_reference` in place (the old picture stays until the new one is stored), and never a version row; when the look is `ready` again, a new version records the new pictures, and every older version still names the pictures it had. **Take**: `POST .../takes` does `INSERT character_take` with `look_id` = the current look and `character_version` = the newest version number (NULL if none). A version is read, never edited: `GET .../versions` lists them newest first, and what each changed is computed on read. |
| Link the story's characters to the Character Lab (PHASE-008) | Every action is a database write that is done before the answer (no job, no model call) and commits once. All of them read the newest `character_discovery` row and refuse (422) when there is none or the id is not in it. **Create** (`POST /api/projects/{id}/character-links/{discovery_id}/create`) and **Link all** (`POST .../link-all`, every unlinked entry, in one transaction): `INSERT library_character` (`name` from the discovery, `notes` from its description, empty `species` and `appearance`, `origin_project_id`, `origin_discovery_id`), `INSERT library_character_version` (version 1, `source='ai'`) and `INSERT project_character_link` (`how='created'`, `pinned_version=1`, `discovery_version`). **Map** (`PUT .../{discovery_id}` with `character_id`): refused for a missing or archived character, or one the project already uses for another entry. If the character has no version, `INSERT library_character_version` (version 1) first. Then `INSERT project_character_link` (`how='mapped'`, `pinned_version` = the character's newest version) or, when the entry was already linked to another character, `UPDATE` that row (`character_id`, `pinned_version`, `how`, `updated_at`). Mapping to the character the entry already has changes nothing. **Unlink** (`DELETE .../{discovery_id}`): `DELETE project_character_link`; the library character stays. A unique key broken by a concurrent request rolls the change back with a readable message. **A lab edit never writes to `project_character_link`**: the pin stays, and `GET .../character-links` and `GET /api/lab/characters/{id}/projects` work out "a newer version is available" on every read. **Re-running discovery** writes nothing here: links are found by the slug id, so a kept id keeps its link. |
| Define the characters (PHASE-009) | `POST /api/projects/{id}/character-definitions/{discovery_id}/run` (one character) or `POST .../run` (Define all): refused with 422 when there is no saved story, no `story_bible` row, a `story_bible` that is out of date with the story, no list of characters, an entry that is not linked to a library character, or a linked character that is archived. A character the user **chose from the library** (`project_character_link.how='mapped'`) is also refused unless the body has `confirm_overwrite: true`, and Define all skips it (it is listed in `skipped` with the reason). Otherwise `INSERT job` (`type='define_character'`, `provider='llm'`, `project_id` set, `dedupe_key='discovery_id'`, `input` = a copy of the story, the StoryBible and list versions, the character's `entry`, the `others` and the `inputs` to record). Nothing is written to `library_character` yet. **Start**: `UPDATE job.input` with the exact request, then the paid call (`jobs/llm_call.ask_model`, at most two attempts, `output` updated after every attempt). On an answer that checks: one transaction does `UPDATE library_character` (the profile fields the definition fills, and `definition`), `INSERT library_character_version` (`source='ai'`, `definition`, `job_id`, `inputs`), `UPDATE project_character_link.pinned_version` to the new number, and finishes the job. The link is read again inside that transaction, so a link removed or moved meanwhile fails the job and writes nothing. `GET .../character-definitions` writes nothing: it reads the newest list with each link, the pinned version, and the newest job of each character, and works out each status (`unlinked`, `not_defined`, `defined`, `out_of_date`) and the reasons on every read |
| Make the characters' canonical images (PHASE-010) | `POST /api/projects/{id}/character-images/{discovery_id}/run` (one character) or `POST .../run` (Make images for all): refused with 422 when there is no list of characters, an entry that is not linked, a linked character that is archived, an entry with no definition or one that is out of date, or a definition being written. A character the user **chose from the library** (`how='mapped'`) is also refused unless the body has `confirm_overwrite: true`, and Make images for all skips it, as it skips a character whose images are `ready` or already being made. A press for a character whose look is being made returns that look and starts nothing. Otherwise one transaction does `INSERT character_look` (`status='writing_prompt'`, `project_id`, `discovery_id`, `inputs`) and `INSERT job` (`type='write_character_look_prompt'`, `requested='master'`, `project_id` NULL as in the lab, `dedupe=False`), then `UPDATE character_look.prompt_job_id`. The prompt is written from the character's card, which the definition filled. **When the prompt job finishes** (`on_look_prompt_written`): `UPDATE character_look` (`prompt`, `status='choosing'`) and one candidate, `INSERT lab_run` + `INSERT job` (`lab_image`) + `INSERT character_look_candidate` (a lab look makes four). **When the candidate's picture is stored** (`on_candidate_image_stored`, called by the `lab_image` job): the look's status is claimed (`choosing` → `making_angles` in one conditional `UPDATE`), `INSERT character_reference` (`front`) and four angle edit runs (`lab_run` + `lab_image` job + `character_reference`), exactly as a manual choice does. **When the fifth angle's picture is stored** (`_maybe_mark_ready`): `UPDATE character_look.status='ready'`, `UPDATE library_character.current_look_id`, `INSERT library_character_version` (`source='ai'`, `job_id` = the prompt job, `inputs` = the pinned version's `inputs`), `UPDATE project_character_link.pinned_version`, in one transaction. If the link was removed or moved to another character meanwhile, the look is only a lab look: a `manual` version and no pin move. A failed prompt job marks the look `failed` (`error`); a failed candidate or angle job writes nothing here: `GET .../character-images` finds it through the run's job and reports `failed`. **Retry** is a fresh look; **Redo angle** is the lab's own `POST /api/lab/characters/looks/{look_id}/angles/{angle}`. `GET .../character-images` writes nothing: it reads the newest look the pipeline made for each linked character, its candidate and angle jobs, and works out each status (`unavailable`, `none`, `in_progress`, `failed`, `ready`, `out_of_date`), the stage and the reasons on every read |
| Find and edit the characters' relations (PHASE-047) | `POST /api/projects/{id}/character-relations/run` queues one `discover_relations` job (a second click returns it; refused with 422 when there is no saved story, up-to-date Story Bible or list of characters, and, when the newest version is a manual one, unless the body says `confirm_replace_manual: true`). The job asks the story model once, checks the answer (`check_relations`) and, in the same transaction that marks the job succeeded, adds the next `character_relations` version (`ai`). `PUT .../character-relations` checks the user's whole list the same way and adds a `manual` version. `GET` writes nothing: it reads the newest version and works out `dropped`, `reasons`, `can_run` and `needs_confirmation` on every read. The definition stage then passes each other character's `relation_to_this` to the model. **Make images for all** starts bases first; a same-face variant whose base is being made gets a `waiting` `character_look` and no job. When the base's look turns `ready` and its pin has moved, `character_images.release_waiting` (called from the `lab_image` job's hook) claims the waiting look with one conditional update (`waiting` → `writing_prompt`), sets `reference_image_id` to the base's front picture and queues the prompt job. A variant whose base has no picture and none in progress is refused with 422 |
| Make the characters' and the narrator's voices (PHASE-011) | `POST /api/projects/{id}/character-voices/{discovery_id}/run` (one character), `POST .../character-voices/run` (Make voices for all, which also makes the narrator's) or `POST .../narrator-voice/run`: refused with 422 when there is no list of characters (or no saved story and up-to-date StoryBible for the narrator), an entry that is not linked, a linked character that is archived, an entry with no definition or one that is out of date. A character chosen from the library (not made by the pipeline) or a narrator voice chosen by hand is replaced only when the body says `confirm_overwrite: true` or `confirm_replace_manual: true`; Make voices for all skips both. Each start does `INSERT job` (`type='design_voice'`, `provider='llm'`, `dedupe_key='target'`) and commits, so a second click returns the same job. **Start** (`jobs/design_voice.py`): one paid call to the story model writes the voice description (Section 5); then, in the **same transaction that marks the job succeeded**, `story_voices.queue_sample` does `INSERT lab_voice_run` (`mode='design'`, the description as `instruction`, `project_id`, `subject`, `discovery_id`, `design_job_id`, `inputs`) and `INSERT job` (`type='lab_voice'`, `provider='gpu'`), so a job never succeeds without its sample. **When the speech is stored** (`lab_voice` after `UPDATE lab_voice_run`), `story_voices.on_voice_finished(run_id)` runs best effort and in **one transaction**: `INSERT voice` from the run (`voices.create_from_run(commit=False)`), then for a character `UPDATE library_character.voice_id`, `INSERT library_character_version` (`source='ai'`, `job_id` of the design job, `definition` and `inputs` carried over from the pinned version so the definition still reads "Defined") and `UPDATE project_character_link.pinned_version` (`character_looks.pin_new_version`), and for the narrator `INSERT narrator_voice` (`source='ai'`). It does nothing for a run made by hand, a run already saved, or a character whose link moved to another library character meanwhile. `GET .../character-voices` and `GET .../narrator-voice` work the status out on every read: `in_progress` while a design job runs or a sample is queued or running, `failed` when the job or the sample failed (or the speech succeeded more than 30 seconds ago and no voice was saved), `ready`, or `out_of_date` when the facts hash differs. `PUT .../narrator-voice` with `{"voice_id"}` adds a `manual` `narrator_voice` version (no job; the same voice twice adds none) |
| Make and change a library environment, and make its picture (PHASE-012) | `POST /api/lab/environments`: `INSERT library_environment` and, in the same transaction, `INSERT library_environment_version` (version 1, `source='manual'`). `PATCH /api/lab/environments/{id}` merges the fields sent over the current profile, checks the whole result, does `UPDATE library_environment` and calls `environment_versions.record_version_if_changed` **before its own commit**: the next `library_environment_version` is added (with no `reference_image_id`) only if a profile field differs from the newest version's. **Archiving** (`archived`) writes no version. **Make the picture** (`POST .../environments/{id}/references`, 202): refused with 422 when the environment is archived or a prompt is already being written for its newest version; otherwise one transaction does `INSERT environment_reference` (`status='writing_prompt'`, `version_id` = the newest version) and `INSERT job` (`type='write_environment_prompt'`, `project_id` NULL, `dedupe=False`), then `UPDATE environment_reference.prompt_job_id`. **When the job succeeds** (`environment_references.on_prompt_written`, after the job's own commit): `UPDATE environment_reference` (`prompt`, `status='ready'`) and four candidates, each `INSERT lab_run` + `INSERT job` (`lab_image`, text-to-image at 16:9, its own random seed) + `INSERT environment_reference_candidate`, in one transaction; if they cannot be started the attempt is marked `failed`. A failed prompt job marks the attempt `failed` (`on_prompt_failed`). **Choose** (`POST .../environments/references/{reference_id}/choose` with `{candidate_id}`): refused with 422 when the attempt's version is frozen (it is not the environment's newest, **or** a project pins it and it already has its picture, PHASE-013), or the candidate is not of this attempt or its picture is not stored yet; otherwise `UPDATE library_environment_version.reference_image_id` (replacing an earlier choice). Nothing else is written, and no version is added. `GET` calls write nothing: the candidates' state, the list of versions with what each changed and which projects pin it, and whether an attempt is frozen are all worked out on read. **Make the picture** also refuses a frozen newest version (the same rule) |
| Link the story's environments to the Character Lab (PHASE-013) | The same as the characters' links, with the environment tables: every action is a database write done before the answer (no job, no model call), commits once, reads the newest `environment_discovery` row and refuses (422) when there is none or the id is not in it. **Create** (`POST /api/projects/{id}/environment-links/{discovery_id}/create`) and **Link all** (`POST .../link-all`, every unlinked entry, in one transaction): `INSERT library_environment` (`name` from the discovery, `description` from its one-line description, the era `present`, `origin_project_id`, `origin_discovery_id`), `INSERT library_environment_version` (version 1, `source='ai'`) and `INSERT project_environment_link` (`how='created'`, `pinned_version=1`, `discovery_version`). **Map** (`PUT .../{discovery_id}` with `environment_id`): refused for a missing or archived environment, or one the project already uses for another entry; the link pins the environment's newest version (writing version 1 first if it has none), and a link that is already there is moved to the new environment. **Unlink** (`DELETE .../{discovery_id}`): `DELETE project_environment_link`; the library environment and its versions are never deleted. A link whose id is no longer in the newest list is kept and reported as orphaned. `GET` writes nothing: "a newer version is available" is worked out on read |
| Define the environments and make their pictures (PHASE-013) | `POST /api/projects/{id}/environment-definitions/{discovery_id}/run` (one environment) or `POST .../run` (Define all): refused with 422 when there is no saved story, no `story_bible` row, a `story_bible` that is out of date with the story, no list of scenes or one that is out of date, no list of environments, an entry that is not linked, or a linked environment that is archived. An environment the user **chose from the library** (`project_environment_link.how='mapped'`) is also refused unless the body has `confirm_overwrite: true`; Define all skips it, skips one that is already defined and current, and skips one that is already being defined (each is listed in `skipped` with the reason). Otherwise `INSERT job` (`type='define_environment'`, `provider='llm'`, `project_id` set, `dedupe_key='discovery_id'`, `input` as in Section 5). Nothing is written to `library_environment` yet. **Start**: `UPDATE job.input` with the exact request, then the paid call. **When the answer is usable**, one transaction does `UPDATE library_environment` (`definition` and the profile fields written from it, never `name` or `notes`), `INSERT library_environment_version` (`source='ai'`, `job_id`, `inputs`, `definition`), `UPDATE project_environment_link.pinned_version` to it, then `INSERT environment_reference` (`project_id`, `discovery_id`, `version_id`) and `INSERT job` (`write_environment_prompt`) for the picture, and finishes the job. **Then the lab's own machinery runs**: the prompt job writes the prompt from the new version's frozen profile, `on_prompt_written` starts **one** candidate (`INSERT lab_run` + `INSERT job` `lab_image` + `INSERT environment_reference_candidate`), and when its picture is stored `UPDATE library_environment_version.reference_image_id` makes it the canonical picture. `POST .../{discovery_id}/picture` starts another attempt for the pinned version when it has no picture (a failed or never-started one), and is refused otherwise. `GET` writes nothing: each entry's status (`unlinked`, `not_defined`, `defined`, `out_of_date` and why), its definition and its picture state (`unavailable`, `none`, `in_progress` with the stage, `failed` with the reason, `ready`) are worked out on read from the pinned version, its `inputs`, the newest definition job and the newest attempts |

Throughout, the **GPU API contract guard** (Section 6.5) reads/writes `api_snapshot` independently of any one project, and the **Settings page** (Section 3.7) reads/writes `setting` independently of any one project.

---

## 8. Assumptions and additions beyond ANALYSIS.md

`ANALYSIS.md` Section 4.3 gives field names and a one-line purpose for each; it does not specify SQL-level detail. Everything below is my addition to make the model concrete, listed here instead of buried silently in the tables above, so you can tell what's sourced versus what's a convention I picked:

1. **Primary keys:** plain `INTEGER PRIMARY KEY` (SQLite rowid) on every table except `setting` (keyed by `key`). This is the simplest option for a single-file SQLite database. `ANALYSIS.md` only mentions UUIDs for on-disk **file names** (Section 3.5), not database primary keys.
2. **Table names:** lowercase `snake_case`, singular (`project`, `asset`, `job`, `setting`, `api_snapshot`), mapped from the PascalCase model names in `ANALYSIS.md`.
3. **Cascade rules:** `ON DELETE CASCADE` from `project` to its owned rows (`asset`, `job`), and `ON DELETE SET NULL` for the optional asset reference on `job` (so deleting one asset doesn't delete a whole job). `ANALYSIS.md` doesn't state delete behaviour anywhere; this is a reasonable default, not a documented rule.
4. **Indexes** beyond the primary/foreign keys (Section 4, "Recommended indexes") are my suggestions based on the dispatcher's described access patterns (Section 3.3), not a list given in `ANALYSIS.md`.
5. **`job.input` / `job.output` JSON shapes.** Those of the labs' jobs were built in Phases 19 to 22 (the `lab_video` and `write_lab_video_prompt` shapes of Phase 19 were checked against mock servers that answer like the real ones, not yet against the real GPU server; the `lab_voice` shape of Phase 21 was run on a scratch database against a mocked GPU server, including a pre-emption of the second of three pieces, not yet against the real Breeze TTS endpoint); the rest are my reasonable fill-ins consistent with the prose description and should be treated as a starting point, not a spec.
6. **Timestamp population** (`DEFAULT CURRENT_TIMESTAMP`) is a SQLite/SQLAlchemy convention I chose; `ANALYSIS.md` doesn't describe how timestamp columns get their values.
7. **`CHECK` constraints** for the enum-like fields (`kind`, `source`, `status`, `type`, `provider`, `state`) enforce exactly the allowed values listed in `ANALYSIS.md` Section 4.3 — these values are sourced, the `CHECK` mechanism itself is my addition for data integrity at the database level (SQLite has no native enum type).

None of the above requires a different design — they're implementation choices within the model `ANALYSIS.md` already settled on. If you'd prefer different choices (e.g., UUID primary keys, plural table names, no `CHECK` constraints), they're easy to change before any migration is written, since no code exists yet.
