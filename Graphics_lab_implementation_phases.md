# Vision Studio — Graphics Lab Phases

The Graphics lab is a trial lab for **deterministic graphics**: charts, diagrams and text cards drawn by code instead of by H3. The owner types one line of an explainer script. A language model decides what the graphic should show and how it should move. The same graphic is then made by four engines, and the owner compares the four videos side by side.

- The four engines are **Remotion with building blocks**, **Remotion with templates**, **Python templates** and **a component written by GLM-5.3**. They are described in §3 and §4.
- The lab answers two questions before anything goes into the explainer pipeline: which renderer (Remotion or Python), and which way of authoring (templates, building blocks, or code written by the model).
- The conventions of `Implementation_phases.md` (§3.3 to §3.5, §6) apply unchanged. Table and column details go in `DATABASE_STRUCTURE.md`. The newest migration when this was written was `0078`.
- Written 2026-11-02, from a design discussion with the owner about deterministic graphics for finance, AI and general explainers.

---

## How to use this document

### Opus → Sonnet workflow

1. Pick a phase whose status is **Not Started** and whose hard dependencies are met (§5).
2. Give Opus this document, `Implementation_phases.md` and a request such as:

   > Plan **GFX-0XX — <title>** only. Respect its Scope and Out of scope, the decisions in §3 and the design in §4 of `Graphics_lab_implementation_phases.md`, the conventions in §3.4 and §3.5 of `Implementation_phases.md`, and the Completion notes of every phase it depends on. Resolve every "Planning decides" item explicitly in the plan. Do not pull work from later phases. List the files to change, the API and UI changes, the settings, and how each Verification criterion will be checked.

3. Give the resulting plan to Sonnet for execution.
4. When the phase is done, update it as described in §7. Fill in its **Completion notes**: later phases read them to learn the real names of modules, job types, endpoints and settings.

### Reading a phase

Every phase has the same fields: Objective, Current state (with starting points in the code), Scope, Out of scope, Dependencies, Expected outcome, Verification criteria, Completion checklist and Completion notes. Items marked **Planning decides** are left open on purpose and must be settled in the plan.

Manual phases (GFX-001, GFX-013) are done by the owner. The agent prepares material and records the results.

### Why the phases can run in parallel

- **One migration for the whole lab.** GFX-002 creates every table, column and job type the lab needs (§4.8). Later phases add no migration, so phases that run at the same time never fight over Alembic revision numbers. If a later phase still needs one, it takes the next free number when it is written and says so in its notes.
- **Contracts are in this document.** The shapes every engine reads (§4.3 to §4.5) and the motion service API (§4.6) are written here, so an engine phase can be planned before the phases next to it are done.
- **Each engine has its own folder and its own job type.** The engines meet only in the engine registry (§4.5) and in the render job (§4.7).

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
- [Appendix A — Trial excerpts](#appendix-a--trial-excerpts)
- [Appendix B — Trial results (filled by GFX-013)](#appendix-b--trial-results-filled-by-gfx-013)
- [Appendix C — Progress log](#appendix-c--progress-log)

---

## 1. Goal

The owner types a line such as:

> "Acme's revenue has exploded. It made 12 billion dollars in 2023, 19 billion in 2024, and 31 billion in 2025. That's more than double in two years."

and gets, on one page:

- what the model decided: the kind of graphic, what it shows, the numbers it uses, and the moments in the line where each part appears;
- four videos of that graphic, one per engine, all the same size and length, played in sync, with the line's voice when a voice was chosen;
- for each video: whether it was made, how long it took, what the model call cost, any check it failed, and the owner's verdict.

A fixed set of ten excerpts (Appendix A) is run through all four engines, and the summary tells the owner which approach to build into the explainer pipeline.

---

## 2. Current state

What exists and is reused:

- **Labs.** One Lab page with a tab per lab (`frontend/src/pages/LabPage.tsx`, `TABS`). The Music lab is the closest pattern: a project-independent run table (`lab_music_run`), a `verdict` of `good`, `usable` or `bad` with a `note`, trials shown side by side (`components/musicLab/MusicTrialsPanel.tsx`, `musicTrialsView.ts`), and paid calls that start only from a click (`jobs/write_lab_music_prompt.py`).
- **Model calls.** `jobs/llm_call.ask_model` (two attempts, the second told why the first failed, the answer saved the moment it arrives). `services/llm_target` gives the story role (`STORY_MODEL_KEY`, GLM-5.3 on Bitdeer).
- **Numbers and phrases.** `services/number_words.numbers_in(text)` reads digits and English number words. `services/callout_plan_writer.locate_phrase(words, phrase)` finds a phrase among words (`PHRASE_MATCH_MIN` 0.6).
- **Speech and timing.** `services/voice_lab.create_run` speaks a text in a saved voice (`Voice` rows). `jobs/time_lab_speech_words.py` (Audio video lab) runs Parakeet on a lab speech and matches the words with `services/word_timings.align`, using the setting `word_timing_match_threshold`.
- **Look and zones.** `services/caption_plan.style_for(width, height)` gives the caption layout of an explainer, so the caption area is known. The callout colour roles are in `services/callout_render.py` (`number` `#FFB000`, `negative` `#FF4D4D`, `positive` `#2ED573`), and `callout_plan_writer.check_accent` checks an accent colour. The bundled font is `backend/app/assets/fonts/Montserrat-ExtraBold.ttf`, and `services/font_metrics.measure` measures it.
- **Sizes and frame rate.** `services/projects.ORIENTATION_DEFAULTS` gives output sizes of 1920 x 1080 (landscape) and 1080 x 1920 (portrait). H3 and the render work at 24 fps (`frame_counts.H3_FPS`).
- **Containers.** `docker-compose.yml` has two services, `backend` (Python 3.13 slim, FFmpeg) and `frontend` (nginx). There is no Node service at runtime.
- **Jobs.** One handler module per job type, registered in `jobs/__init__.py`. Job types are a CHECK on `job.type`, so a new type needs a migration (`Implementation_phases.md` §3.4). Pools are in `jobs/pools.py` (`gpu`, `paid_api`).

What does not exist: Remotion, any Node runtime in the backend, any frame-drawing code, and any graphic artifact.

---

## 3. Decisions

| # | Decision |
|---|----------|
| G-1 | The Graphics lab is a new **Graphics** tab of the Lab. It belongs to no project. Nothing in it changes explainers or stories. Building graphics into the explainer pipeline is a later document, written after GFX-013. |
| G-2 | **The owner types only a line.** The form has the line (1 to 300 characters), the orientation (landscape or portrait), and an optional voice, which may be any saved voice of the Voice lab (GFX-004). Nothing else is needed to make all four videos. |
| G-3 | **One director call writes an engine-neutral brief** (§4.3): the kind of graphic, what it should show and how it moves (in words), the numbers it uses, the beats (each tied to a phrase of the line), and a theme. Every engine starts from the same brief. |
| G-4 | **Fair comparison.** All four engines get the same brief, the same resolved timing, the same size, frame rate (24) and frame count, the same fonts, colours, safe area and caption area (§4.4). Their output is encoded the same way (§4.7). |
| G-5 | **Four engines**, each answering one question: **Remotion templates** and **Python templates** render the *same* template spec, so they compare the renderer alone. **Remotion building blocks** and Remotion templates use the same renderer, so they compare the way of authoring. **Generated component** and building blocks compare free code with checked blocks. |
| G-6 | **The generated component is a Remotion React component (TSX)**, never Python. It runs only inside the motion service's browser, in an isolated container (G-8), never in the backend process. |
| G-7 | **Every number on screen comes from the line.** A fact must be said in the line (`number_words.numbers_in`). A derived value (a percent change, a difference, a ratio, a sum) is computed by code from facts, never by a model. Code writes every number's on-screen text (US style: `$31B`, `+158%`, `45x`, `2.5M`). Engines refer to numbers by id. A generated component gets them as props, and a number written directly into its code is a warning. |
| G-8 | **The motion service is a separate container** (Node, Remotion, headless Chrome) on an internal Docker network with no internet. It has no media volume and no secrets. The backend sends it the input and downloads the finished file. |
| G-9 | **Models never write times or frame numbers.** Beats name a phrase of the line. Code turns phrases into frames, from estimated timing without a voice, and from Parakeet word timings with a voice (GFX-004). |
| G-10 | Output: 24 fps, 1920 x 1080 or 1080 x 1920, an exact frame count, H.264 `yuv420p`. When a voice was chosen, the voice is added to every engine's video by the backend in the same way. |
| G-11 | **Same fonts everywhere**, loaded from files and never from the internet: Montserrat ExtraBold for titles and numbers, plus one text font under the SIL Open Font License: **Inter Medium** (decided in GFX-002, 2026-11-02; `Inter-Medium.ttf` and `Inter-OFL.txt`, from the Inter 4.1 release). |
| G-12 | **Every model call uses the story role** (`STORY_MODEL_KEY`, GLM-5.3), like the story stages. Each call sets its own `max_tokens`. |
| G-13 | Paid calls start only from a click (one click may start several calls, for example **Make all**). They are `never_rerun` and use `llm_call.ask_model`. |
| G-14 | The owner rates each video `good`, `usable` or `bad`, with a note, as in the Music lab. |
| G-15 | English only. No automated tests (D-11 of `Implementation_phases.md`). |

---

## 4. Design

### 4.1 How it works

```text
the owner types a line (and optionally picks a voice)
  -> [GFX-004] voice: speak the line, Parakeet times the words     (optional)
  -> [GFX-003] director call: the brief; code checks it
  -> [GFX-003] code resolves it: timing, beat frames, number text,
               colours, safe area, caption area                    ("resolved", §4.4)
  -> one call per engine family, all from the same brief:
       [GFX-006] template spec    -> [GFX-007] Remotion templates
                                  -> [GFX-008] Python templates
       [GFX-009] block scene      -> Remotion building blocks
       [GFX-010] component code   -> Remotion generated component
  -> [GFX-005] render job: render, check, add the voice, store
  -> [GFX-011] comparison view: four videos in sync, metrics, verdicts
  -> [GFX-012] trial: ten excerpts through every engine, summary
```

Three model calls follow the director call (the template spec serves two engines). A run therefore costs four paid calls, plus at most one retry each.

### 4.2 Runs and renders

- A **run** is one line, one orientation and, optionally, one voice. Its brief and its timing belong to it. **Ask again** on the brief makes a new run with the same line, so a brief never changes under the renders made from it.
- A **render** is one engine's attempt for a run: its input (spec, scene or code), the job that wrote that input, the render job, the video, its metrics and warnings, and the verdict. **Ask again** on an engine makes a new render for that engine (a new model call). **Render again** makes a new render with the same input and no model call, to check that the result is repeatable (§4.7).
- The two template engines share one template spec: one call, two renders.
- States are worked out when read, from the jobs and the stored fields, as in the Audio video lab (`services/av_lab.py`). Only `last_error` is stored.

### 4.3 The brief (written by the director call)

The director call reads the line and answers one JSON object:

```json
{
  "kind": "comparison",
  "intent": "Show that Acme's revenue more than doubled in two years.",
  "visual_brief": "Three bars for 2023, 2024 and 2025 that grow as each year is said. The 2025 bar is the tallest and green. At the end a +158% badge pops in next to it.",
  "facts": [
    { "id": "f1", "label": "2023 revenue", "value": 12, "unit": "usd", "scale": "billion", "said_as": "12 billion dollars in 2023" },
    { "id": "f2", "label": "2024 revenue", "value": 19, "unit": "usd", "scale": "billion", "said_as": "19 billion in 2024" },
    { "id": "f3", "label": "2025 revenue", "value": 31, "unit": "usd", "scale": "billion", "said_as": "31 billion in 2025" }
  ],
  "derived": [
    { "id": "d1", "label": "Growth 2023 to 2025", "op": "pct_change", "of": ["f1", "f3"] }
  ],
  "beats": [
    { "id": "b1", "phrase": "Acme's revenue has exploded", "shows": "The title appears." },
    { "id": "b2", "phrase": "12 billion dollars in 2023", "shows": "The 2023 bar grows.", "refs": ["f1"] },
    { "id": "b3", "phrase": "19 billion in 2024", "shows": "The 2024 bar grows.", "refs": ["f2"] },
    { "id": "b4", "phrase": "31 billion in 2025", "shows": "The 2025 bar grows, in green.", "refs": ["f3"] },
    { "id": "b5", "phrase": "more than double", "shows": "The growth badge pops in.", "refs": ["d1"] }
  ],
  "theme": { "palette": "dark", "accent": "#2ED573", "background": "grid", "motion": "snappy", "mood": "confident" }
}
```

Fields and the code checks (a failing answer is refused with the reasons, and `ask_model` asks once more):

- `kind`: one of `kpi`, `comparison`, `trend`, `process`, `list`, `statement`, `concept`. `concept` means an idea no data chart fits (for example, how attention works).
- `intent`: at most 160 characters. `visual_brief`: at most 600 characters, in words. It is the "prompt for what is needed", and every engine's call receives it.
- `facts`: 0 to 12. `unit` is one of `usd`, `percent`, `points`, `multiple`, `count`, `none`. `scale` is one of `none`, `thousand`, `million`, `billion`, `trillion`. `said_as` must be found in the line (`locate_phrase`), and the fact's value must be a number that `numbers_in` reads in that phrase, either as written (`12`) or with its scale applied (`12,000,000,000`). **The matching rule (decided in GFX-003).** The line is split on whitespace into words, and each word into the tokens `normalize_words` makes. `said_as` is found among the tokens with `locate_phrase`. The fact's number must then be one that `numbers_in` reads in the *original words* behind the found tokens (not in the tokens, because normalising turns `6.5` into `6 5`): the value as written or with its scale applied. The sign is ignored, so a fall said as "down 6.5 percent" is a fact with the value -6.5. A scale (other than `none`) only goes with the units `usd` and `count`. A derived value's facts all have one unit, `pct_change` needs a first fact that is not zero and `ratio` a second one that is not zero. Ids are 1 to 16 letters, digits or underscores starting with a letter, and are unique among the facts and derived values. A beat's phrase is searched from the start of the beat before it: found there, it is placed there; found only earlier, the brief is refused as out of order; not found, as not in the line. Two beats may start on the same word.
- `derived`: 0 to 4. `op` is one of `pct_change`, `difference`, `ratio`, `sum`, and `of` lists existing fact ids (two facts, or two or more for `sum`). The model never gives the value: code computes it.
- `beats`: 1 to 8. Each `phrase` must be found in the line, and the phrases must come in the order of the line (a later beat never starts before an earlier one). `shows` is at most 120 characters. `refs` names facts or derived values.
- `theme`: `palette` is `dark` or `light`. `accent` is a `#RRGGBB` colour that is readable on the palette's background, otherwise code replaces it with a default and adds a note (the contrast rule is in §4.4: at least 3.0 against the palette's background; `check_accent` is not used, because it measures against black). `background` is one of `solid`, `gradient`, `grid`, `glow`. `motion` is one of `snappy`, `smooth`, `calm`. `mood` is at most 40 characters.

No text that appears on screen (titles, labels) is in the brief. The engine calls write it, and the number rule (G-7) applies to that text: any number shown must be a fact or a derived value.

### 4.4 Timing and the resolved brief (written by code)

**Timing.** Without a voice, each word gets an estimated time from a words-per-minute setting (default 160, near the measured presenter pace), shared by character count as in EXPLAINER-007's estimated timing. With a voice (GFX-004), the times are the Parakeet times of the line's speech. The run records which one it used (`estimated` or `parakeet`).

**Length.** The graphic starts at the start of the speech and lasts until the end of the last word plus 0.5 s, at least 3 s (72 frames) and at most 15 s (360 frames). A line whose speech would be longer than 15 s is refused before the director call, with a message that the line is too long for one graphic.

**Beat frames.** A beat's frame is the frame of the first word of its phrase: `round(start_s * 24)`. When a voice's timing arrives after the brief, the beat frames are worked out again from the stored phrases, with no new model call.

**The resolved brief** is what every engine's input is checked against and what every renderer receives besides its own input:

```json
{
  "width": 1920, "height": 1080, "fps": 24, "frames": 161,
  "timing_source": "estimated",
  "facts":   { "f1": { "label": "2023 revenue", "value": 12, "display": "$12B" } },
  "derived": { "d1": { "label": "Growth 2023 to 2025", "value": 158.33, "display": "+158%" } },
  "beats":   { "b1": { "frame": 0, "shows": "The title appears." } },
  "theme": {
    "background": "#0B0F17", "surface": "#161C28", "text": "#FFFFFF", "muted": "#9AA4B2",
    "accent": "#2ED573", "positive": "#2ED573", "negative": "#FF4D4D", "number": "#FFB000",
    "background_style": "grid", "motion": "snappy"
  },
  "fonts": { "display": "Montserrat ExtraBold", "text": "<the text font of G-11>" },
  "safe_area":    { "left": 96, "top": 54, "right": 1824, "bottom": 1026 },
  "caption_zone": { "top": 860, "bottom": 1000 }
}
```

- The `display` text is written by code (G-7). **The rounding (decided in GFX-003).** `$` before dollars; `%`, `x` and ` pts` after percents, multiples and points; `K`, `M`, `B` and `T` for the units `usd` and `count` from 1,000 up (any other unit shows its plain number, with commas from 10,000); a minus sign when negative. A fact shows at most two decimals. A derived value shows no decimals at 10 or more and one below 10. Trailing zeros are dropped, and rounding is half up. A change (`pct_change`, `difference`) has its sign when it is not zero (`+158%`, `-6.5%`). The difference of two `percent` facts is in `pts`, and a `ratio` is a `multiple`. In the resolved brief, `value` is the full number (the scale applied) and each entry also has its `unit`, and `notes` lists what code changed (for example a replaced accent).
- The palette colours, the safe area and the caption area are worked out by code (decided in GFX-003). **Colours:** dark `#0B0F17` background, `#161C28` surface, `#FFFFFF` text, `#9AA4B2` muted, `#2ED573` positive, `#FF4D4D` negative, `#FFB000` number, `#4DA3FF` default accent; light `#F7F8FA`, `#E6E9EF`, `#0B0F17`, `#5B6472`, `#15803D`, `#C62828`, `#B45309`, `#1D4ED8`. Every colour except the surface measures at least 4.5 against its background. The director's accent must reach a contrast of 3.0 (the WCAG minimum for large text and graphics) on the background, otherwise the palette's default is used and a note says so. **Safe area:** 5 percent from every edge (landscape 96, 54, 1824, 1026; portrait 54, 96, 1026, 1824). **Caption area:** from `caption_plan.style_for` for the same size, the one-line band `top = height - margin_v - font_size - round(font_size / 2)` to `bottom = height - margin_v + round(font_size / 2)` (landscape 878 to 1018, portrait 1261 to 1422), so a graphic made in the lab leaves room for explainer captions. **Timing:** the estimated timing has one entry for each whitespace-separated word of the line; the speech lasts `words x 60 / pace`, and the pace is the setting `graphics_words_per_minute` (160).

### 4.5 Engine inputs

The **engine registry** (created in GFX-002) lists the four engines: `remotion_templates`, `python_templates`, `remotion_blocks` and `generated_component`. Each entry has a key, a label and a `start` function that its phase fills in (`start(session, run)`, async, adds the engine's rows and job and returns the first job; it does not commit). `start` is `None` until the engine is built, and `built` is true when it is set. **Make all** (GFX-003) starts the brief, then calls `start` for every engine that is built.

#### 4.5.1 Template spec (GFX-006, rendered by GFX-007 and GFX-008)

One call reads the brief and the catalogue and answers either a template spec or `{"template": null, "reason": "..."}` when no template fits (for example, for `kind: concept`). "No template fits" is a valid outcome and is shown and counted, not treated as a failure.

```json
{
  "template": "bar_comparison",
  "variant": "vertical",
  "fields": {
    "title": "Acme revenue",
    "bars": [
      { "label": "2023", "value": "f1" },
      { "label": "2024", "value": "f2" },
      { "label": "2025", "value": "f3", "emphasis": true }
    ],
    "highlight": { "value": "d1", "beat": "b5" }
  },
  "beats": { "title": "b1", "bars": ["b2", "b3", "b4"] }
}
```

The catalogue (field limits are checked by code, and long text is never cut):

| Template | Variants | Fields | Rules |
|---|---|---|---|
| `kpi_card` | `center`, `split` | title (32), value (ref), change (optional ref), caption (optional, 60) | The colour of a change follows its sign |
| `bar_comparison` | `vertical`, `horizontal` | title (32), 2 to 6 bars (label 16, value ref, emphasis), optional highlight (ref, beat) | Bars start at zero, and every bar has the same unit |
| `line_trend` | `line`, `area` | title (32), 3 to 12 points (label 10, value ref), optional end label (ref) | The axis is fitted to the data with 10 percent padding and always shows its values. The line draws through each point as its beat arrives |
| `flow_diagram` | `horizontal`, `vertical` | title (32), 2 to 6 nodes (label 24, beat) | Nodes in a chain. The arrow to a node appears with it. Portrait defaults to `vertical` |
| `bullet_build` | `list`, `statement` | optional title (32), 1 to 4 items (text 48, beat) | `statement` is one large centred line |

**The look rules.** GFX-007 and GFX-008 build to these rules independently, so the two renderers can be compared on equal terms:

- The title sits at the top left of the safe area, in the display font at 6 percent of the height (landscape) or 3.6 percent (portrait). Body text uses the text font at 3.2 percent or 2.4 percent.
- Everything stays inside the safe area and out of the caption area. A text that does not fit is made smaller down to 70 percent of its size, then split onto two lines. Past that, the spec is refused (in GFX-006, using `font_metrics`-style measuring).
- An element enters on its beat: a fade, plus a slide up of 3 percent of the height, over 12 frames (`snappy`), 18 frames (`smooth`) or 24 frames (`calm`), with an ease-out cubic curve (`1 - (1 - t)^3`). Bars and lines grow over the same time. A number counts up over the same time.
- Colours follow the roles in the resolved theme: `emphasis` and the highlight use `accent`, a change uses `positive` or `negative`, other numbers use `text`.
- The background is drawn in the theme's `background_style`: a flat colour, a vertical gradient from `background` to `surface`, a faint grid of `surface` lines every 8 percent of the height, or a soft radial glow of `accent` at 8 percent opacity.

A phase that has to change a look rule records the change in this section and in its notes. The other template phase follows it.

#### 4.5.2 Block scene (GFX-009)

The model designs the scene freely from blocks we wrote once. Code checks it, and the motion service measures it.

```json
{
  "elements": [
    { "id": "title", "block": "text", "style": "title", "text": "Acme revenue",
      "region": [1, 1, 8, 2], "enter": { "beat": "b1", "effect": "slide_up" } },
    { "id": "bars", "block": "bar_series", "values": ["f1", "f2", "f3"], "labels": ["2023", "2024", "2025"],
      "orientation": "vertical", "emphasis": ["f3"],
      "region": [1, 3, 8, 11], "enter": { "beats": ["b2", "b3", "b4"], "effect": "grow" } },
    { "id": "growth", "block": "badge", "value": "d1", "role": "positive",
      "region": [9, 3, 12, 5], "enter": { "beat": "b5", "effect": "pop" } },
    { "id": "link", "block": "arrow", "from": "bars", "to": "growth",
      "enter": { "beat": "b5", "effect": "draw" } }
  ]
}
```

- **Blocks:** `text` (styles `title`, `label`, `body`), `counter`, `bar_series`, `line_series`, `node`, `arrow`, `table` (up to 5 rows and 4 columns), `badge`, `highlight` (a box around another element), `progress_ring`. Whether to add icons, which need an icon set and its licence, is **Planning decides** (GFX-009).
- **Effects:** `fade`, `slide_up`, `slide_left`, `grow`, `pop`, `draw`, `count_up`, `typewriter`. An optional `exit` takes the same effects.
- **Regions:** `[first column, first row, last column, last row]` on a 12 x 12 grid inside the safe area, counted from 1. An `arrow` has no region: it runs between two elements.
- **Code checks:** at most 12 elements and 6 text elements; known blocks, effects, beats and refs; regions inside the grid; no region in the caption area; bars from zero; the number rule (G-7) on every text.
- **Layout check:** the motion service reports the box of every text element at each beat's frame and at the last frame (§4.6, `POST /layout`). A text outside the safe area, inside the caption area, overlapping another text, or smaller than 2 percent of the height is listed and sent back to the model once.

#### 4.5.3 Generated component (GFX-010)

The model writes one TSX file whose default export is a component taking these props:

```ts
type GraphicProps = {
  width: number; height: number; fps: number; durationInFrames: number;
  theme: { background: string; surface: string; text: string; muted: string;
           accent: string; positive: string; negative: string; number: string;
           fontDisplay: string; fontText: string };
  facts: Record<string, { label: string; value: number; display: string }>;
  beats: Record<string, { frame: number; shows: string }>;
  safeArea: { left: number; top: number; right: number; bottom: number };
  captionZone: { top: number; bottom: number };
};
```

The instructions tell the model:

- animate only with Remotion's frame tools (`useCurrentFrame`, `interpolate`, `spring`, `Sequence`);
- show numbers only from `facts[id].display` (derived values are in `facts` too);
- time everything from `beats[id].frame`;
- stay inside `safeArea` and out of `captionZone`;
- use the given fonts and colours, and no outside assets.

**Static checks** run in the backend before anything renders. A failure goes back to the model once, with the reasons.

- Imports come only from an allowed list (**Planning decides**: at least `react` and `remotion`, perhaps `@remotion/shapes` and `@remotion/paths`).
- There is exactly one default export.
- None of these appear: `fetch`, `XMLHttpRequest`, `WebSocket`, `EventSource`, `eval`, `Function(`, `import(`, `require(`, `localStorage`, `sessionStorage`, `indexedDB`, `document.cookie`, `window.open`, `navigator`, `<iframe`, `<script`, or any `http:`, `https:` or `//` address.
- At most 40,000 characters.

**The compile check** follows: the motion service transpiles the code and renders still frames at the first, middle and last frame (`POST /checks`). An error goes back to the model once, with the error text.

**Warnings, not refusals:** a number literal in the code equal to a fact's value, and, when GFX-009's layout report exists, any text on screen containing a number that is not a fact's `display`.

The static checks are not the security boundary. The container is (G-8, GFX-005, GFX-010).

### 4.6 The motion service (GFX-005)

A new folder `motion/` holds a Node project with Remotion. It builds into a third container, `motion`. One HTTP server inside it takes render work from the backend.

| Endpoint | Phase | What it does |
|---|---|---|
| `GET /health` | 005 | Versions of Remotion, Chrome, the template catalogue and the block library |
| `POST /renders` | 005 | Starts a render: `{engine, width, height, fps, frames, resolved, input, code?}`. Answers `{render_id}` |
| `GET /renders/{id}` | 005 | `queued`, `rendering`, `done` or `failed`, with progress, the error and the times |
| `GET /renders/{id}/file` | 005 | The finished MP4 |
| `DELETE /renders/{id}` | 005 | Removes the file from the service |
| `POST /layout` | 009 | The boxes of the text elements at the given frames |
| `POST /checks` | 010 | Transpiles a component and renders still frames, answering the errors |

- **Compositions:** `TestCard` (GFX-005), `Templates` (GFX-007), `Blocks` (GFX-009), `Generated` (GFX-010). GFX-005 registers all four, with the last three showing a "not built yet" card, so each engine phase only fills in its own folder.
- **Isolation:** the container is only on an `internal: true` Docker network that the backend also joins. It has a read-only root filesystem, a `tmpfs` for its work, a non-root user, CPU, memory and time limits, and no environment secrets. The browser is downloaded when the image is built, because the container has no internet when it runs.
- **Concurrency:** one render at a time by default. A setting can raise it.

### 4.7 The render job and its checks (GFX-005)

One job type, `render_lab_graphic`, makes every engine's video:

1. It sends the work to the engine's renderer: the motion service for the three Remotion engines, or the Python renderer in the backend for `python_templates` (GFX-008).
2. It checks the file with `ffprobe`: exact frame count, size, 24 fps, H.264 `yuv420p`.
3. When the run has a voice, it adds the voice with FFmpeg, copying the video stream. Every engine gets the same audio. A run without a voice gives a video with no audio track.
4. It stores the video as lab media and records the metrics.

All engines encode with the same settings (codec, CRF, preset). **Planning decides** (GFX-005) the values, and GFX-008 uses the same ones.

**Metrics kept with each render:**

- the model call's time, tokens and attempts;
- the render time and the file size;
- whether the frame count, size and frame rate are correct;
- whether every number traced;
- the layout warnings;
- whether a repeat render matched.

**Repeatability (Render again).** The same input is rendered again, and the decoded frames of both videos are compared with `ffmpeg -f framemd5`. The result is "identical" or "N of M frames differ".

### 4.8 Storage (all of it in GFX-002's migration)

The names below are the sketch. The final names and columns, as built in GFX-002 (migration `0079`), are in the GFX-002 completion notes and in `DATABASE_STRUCTURE.md` Sections 4.73 and 4.74. The built tables have two more `lab_graphic_run` columns than the sketch: `timing_job_id` (the `time_lab_graphic_words` job, GFX-004) and `resolved` (the resolved brief, GFX-003); and `UNIQUE (run_id, engine, attempt)` on `lab_graphic_render`.

- `lab_graphic_run`:
  - `id`, `created_at`;
  - `line_text`, `orientation`;
  - `voice_id` (nullable, `SET NULL`) and `speech_run_id` (nullable link to the `lab_voice_run`, `SET NULL`);
  - `timing` (JSON, nullable: words with times, `source`, `duration_s`);
  - `brief` (JSON, nullable) and `brief_job_id`;
  - `trial_case_key` (nullable, GFX-012);
  - `last_error`.
- `lab_graphic_render`:
  - `id`, `created_at`;
  - `run_id` (`CASCADE`);
  - `engine` (CHECK, the four engine keys) and `attempt`;
  - `input` (JSON: the spec, the scene, or the code) and `input_job_id`;
  - `repeat_of` (nullable: the render a Render again was made from);
  - `render_job_id`, `media_path`;
  - `metrics` (JSON), `warnings` (JSON);
  - `verdict` (CHECK `good`, `usable`, `bad`, nullable), `note`.
- **Job types** added to the `job.type` CHECK: `write_lab_graphic_brief`, `write_lab_graphic_template_spec`, `write_lab_graphic_block_scene`, `write_lab_graphic_component`, `render_lab_graphic`, `time_lab_graphic_words`. All six are added in GFX-002, even though later phases write their handlers.

### 4.9 The comparison view and the trial summary

- **Run page (GFX-011).** It shows the line and the brief, then four engine cards in a grid (two by two for landscape, four columns for portrait). One control plays, pauses and seeks all four videos together. Overlays show the safe area and the caption area. Each card shows its state, metrics, warnings, its input (JSON or code, folded), the verdict and note, **Ask again** and **Render again**.
- **Trial summary (GFX-012).** For each engine, over the ten excerpts:
  - how many made a video, and how many said "no template fits";
  - how many passed the frame, size and frame rate checks;
  - how many had no layout warning, and how many had every number traced;
  - the median render time and the median tokens;
  - the repeat results;
  - the verdict counts.

  The summary can be copied as Markdown for Appendix B.

---

## 5. Phase overview

| Id | Title | Kind | Hard dependencies | Status |
|----|-------|------|-------------------|--------|
| GFX-001 | Owner checks: Remotion licence, excerpts, voice | Manual | none | In Progress (licence and voice done; excerpts open) |
| GFX-002 | Lab foundation: storage, run form, engine slots | Code | none | Done (2026-11-02) |
| GFX-003 | Director call: the brief and its timing | Code | 002 | In Progress (built; the live check with the real model is open) |
| GFX-004 | Voice and word timings | Code | 003 | In Progress (built; the live check with a real voice is open) |
| GFX-005 | Motion service and the render job | Code | 002 | Not Started |
| GFX-006 | Template catalogue and the template-spec call | Code | 003 | Not Started |
| GFX-007 | Remotion templates | Code | 005, 006 | Not Started |
| GFX-008 | Python templates | Code | 005, 006 | Not Started |
| GFX-009 | Building blocks | Code | 003, 005 | Not Started |
| GFX-010 | Generated components | Code | 003, 005 | Not Started |
| GFX-011 | Comparison view | Code | 003, 005 | Not Started |
| GFX-012 | Trial batch and summary | Code | 007, 008, 009, 010, 011 | Not Started |
| GFX-013 | Owner judges the trial and decides | Manual | 001, 012 | Not Started |

### 5.1 Dependency graph

```text
GFX-001 (owner) ───────────────────────────────────────────────┐
GFX-002 ─┬─ GFX-003 ─┬─ GFX-004                                 │
         │           ├─ GFX-006 ─┬─ GFX-007 ─┐                  │
         │           │           └─ GFX-008 ─┤                  │
         │           ├─ GFX-009 ─────────────┤                  │
         │           ├─ GFX-010 ─────────────┼─ GFX-012 ─ GFX-013
         │           └─ GFX-011 ─────────────┘
         └─ GFX-005 ── (needed by 007, 008, 009, 010, 011)
```

### 5.2 Parallel work

- **Start immediately:** GFX-001 (owner) and GFX-002.
- **After GFX-002:** GFX-003 and GFX-005 at the same time (the brief and the motion service share nothing but the tables).
- **After GFX-003 and GFX-005:** GFX-004, GFX-006, GFX-009, GFX-010 and GFX-011 at the same time.
- **After GFX-006:** GFX-007 and GFX-008 at the same time.
- Files that several of these touch, kept small on purpose: `jobs/__init__.py` (one line per handler), the engine registry (one entry per engine), and `motion/src/Root.tsx` (one composition per engine, all registered by GFX-005).

---

## 6. Phases

### GFX-001 — Owner checks: Remotion licence, excerpts, voice (manual)

**Status:** In Progress (the licence and the voice were settled on 2026-11-02; the excerpts are still to be approved)

**Objective.** Settle the three things code cannot: whether the owner may use Remotion, which excerpts the trial runs, and which voice it uses.

**How:**

1. Read Remotion's current licence on its website. Older information says it is free for individuals and very small companies, and that larger companies need a company licence. **This may have changed**, so the owner checks the current terms and records the answer below.
2. Read the ten excerpts in Appendix A. Replace or reword any, keeping a mix of finance, AI and general lines, and lines with and without numbers.
3. Pick a saved voice from the Voice lab for the trial, or decide to run it without a voice (estimated timing).

**Dependencies.** None. GFX-012 needs the excerpts, and the Remotion engines must not be used beyond the trial if the licence does not fit.

**Result (owner fills in):**

- **Licence:** confirmed by the owner on 2026-11-02. The owner may use Remotion, and there is no licence issue.
- **Voice:** decided by the owner on 2026-11-02. Any saved voice of the Voice lab may be used, chosen on each run and on each trial (or none). There is no fixed trial voice.
- **Excerpts approved on:** …

### GFX-002 — Lab foundation: storage, run form, engine slots

**Status:** Done (2026-11-02)

**Objective.** A Graphics tab where the owner makes a run from a line, sees it in a list, opens it and deletes it, with four engine cards that say "not built yet". All the lab's storage and job types exist after this phase.

**Current state.**

- The Lab page and its tabs are in `frontend/src/pages/LabPage.tsx` (`TABS`).
- The Music lab is the pattern for a project-independent run table with a verdict (`LabMusicRun` in `db/models.py`, `services/music_lab.py`, `api/music_lab.py`, `components/lab/MusicLabPanel.tsx`).
- The newest migration is `0078`. `job.type` is a CHECK (`Implementation_phases.md` §3.4).
- Output sizes are in `projects.ORIENTATION_DEFAULTS`.

**Scope.**

- **The lab's one migration** (§4.8): both tables, the engine and verdict CHECKs, and all six job types.
- **`services/graphics_lab.py`:**
  - the form checks: a line of 1 to 300 characters after trimming, and an orientation;
  - create, list, get and delete a run;
  - the engine registry (§4.5) with the four entries marked as not built;
  - `voice_audio_of(run)`, which returns None until GFX-004 fills it in;
  - saving a verdict and a note on a render.
- **API** under `/api/lab/graphics/`: create, list, get and delete runs, and `PATCH` the verdict and note of a render.
- **Frontend:** the Graphics tab with the form (line and orientation; the voice field comes in GFX-004), the run list, and a run page with an empty brief area and the four engine cards.
- **The text font** of G-11 and its licence, in `backend/app/assets/fonts/` and `backend/app/assets/licenses/`. Only font files go in the fonts folder (EXPLAINER-008 found that libass logs an error for any other file there).
- `DATABASE_STRUCTURE.md`.
- **Planning decides:**
  - the final table and column names;
  - how deleting a run removes its media, following the other labs;
  - whether the run list shows a run's state in words or as a badge.

**Out of scope.** Any model call, any rendering, the voice.

**Dependencies.** None.

**Expected outcome.** The owner can open Lab → Graphics, type a line, make a run and see it with four empty engine cards.

**Verification criteria.**

- Migration up, down and up again; `alembic check` shows no new difference.
- A run is created, listed, opened and deleted. An empty line, a line over 300 characters and an unknown orientation are refused with a message.
- A verdict and a note can be saved on a render row made by hand in a throwaway database.
- The other Lab tabs still work.
- Standard checks.

**Completion checklist.**

- [x] Migration, models, `DATABASE_STRUCTURE.md`
- [x] Service, engine registry, API, `schema.d.ts`
- [x] Graphics tab, form, run list, run page with engine cards
- [x] Text font and licence
- [x] Standard checks

**Completion notes.** Done on 2026-11-02. Migration `0079` (down revision `0078`) creates both tables and adds the six job types to the `job.type` CHECK (47 + 6 = 53; the CHECK is rebuilt in batch mode, and the downgrade deletes the six types and restores the old CHECK). Decisions made in planning:

- **Final tables** (`DATABASE_STRUCTURE.md` Sections 4.73 and 4.74). `lab_graphic_run`: `id`, `created_at`, `line_text`, `orientation` (CHECK `landscape` or `portrait`), `voice_id` (`SET NULL`), `speech_run_id` (to `lab_voice_run`, `SET NULL`), `timing_job_id` (`SET NULL`), `timing`, `brief_job_id` (`SET NULL`), `brief`, `resolved`, `trial_case_key`, `last_error`; indexes `idx_lab_graphic_run_created` and `idx_lab_graphic_run_trial_case`. `lab_graphic_render`: `id`, `created_at`, `run_id` (`CASCADE`), `engine` (CHECK, the four keys), `attempt`, `input_job_id`, `input`, `repeat_of` (self reference, `SET NULL`), `render_job_id`, `media_path`, `metrics`, `warnings`, `verdict` (CHECK `good`, `usable`, `bad`, nullable), `note`, `last_error`; `UNIQUE (run_id, engine, attempt)` and the index `idx_lab_graphic_render_run_engine`. Two columns were added to the sketch: `timing_job_id` and `resolved`.
- **Run state in words.** The run list and the run page show the state as a sentence (`services/graphics_lab.run_state`: `new`, `writing_brief`, `brief_ready`, `brief_failed`), worked out on every read from the brief and the brief job. Only `last_error` is stored. The list polls while a run is `writing_brief`, and the run page while any of its jobs is active.
- **Deleting a run** reuses the shared lab-sample delete: new kind `graphic_run` in `services/lab_deletion` and `api/deletion` (`GET /api/lab/samples/graphic_run/{id}/deletion-preview` and `DELETE /api/lab/samples/graphic_run/{id}`), shown by `DeleteLabSampleButton`. It refuses (409) while one of the run's jobs (brief, timing, an engine's input or render) is running; otherwise it deletes the renders and the run, then each video file under `media/lab/` that no remaining row uses (`library_deletion.path_in_use` now also looks at `lab_graphic_render.media_path`). The GPU-server clean-up checkbox is hidden for this kind. There is no `DELETE` under `/api/lab/graphics/`.
- **API** (`api/graphics_lab.py`, tag `graphics-lab`): `POST /api/lab/graphics/runs` (201; body `line_text`, `orientation`, no other key), `GET /api/lab/graphics/runs?before_id&limit` (newest first, 20 by default, at most 50), `GET /api/lab/graphics/runs/{run_id}` and `PATCH /api/lab/graphics/renders/{render_id}` (`verdict` and/or `note`; only the fields sent change). An empty line, a line over 300 characters after trimming and an unknown orientation get 422 with a sentence (the checks are in the service, because the frontend shows only a string `detail`). A note is trimmed and at most 1000 characters. The size of a run is not stored: landscape 1920 x 1080, portrait 1080 x 1920, 24 frames a second (`graphics_lab.size_of`, from `projects.ORIENTATION_DEFAULTS`).
- **Engine registry** (`services/graphics_engines.py`): `Engine(key, label, start=None)` and `ENGINES` in the order Remotion templates, Python templates, Remotion building blocks, Generated component. `start(session, run)` is async, adds rows and jobs, returns the first job and leaves the commit to its caller. `built` is true when `start` is set; every engine is `None` now.
- **`voice_audio_of(session, run)`** (not `voice_audio_of(run)` as the scope wrote it: it needs the session to read the speech). It returns `None` until GFX-004.
- **Text font G-11:** **Inter Medium** (`backend/app/assets/fonts/Inter-Medium.ttf`, family "Inter", style Medium, full name "Inter Medium", from the Inter 4.1 release; licence `backend/app/assets/licenses/Inter-OFL.txt`). `graphics_lab.TEXT_FONT_NAME` and `TEXT_FONT_FILE` name it, and `DISPLAY_FONT_NAME` and `DISPLAY_FONT_FILE` name Montserrat ExtraBold. Only font files are in the fonts folder.
- **Frontend:** a Graphics tab in `LabPage` (the form is kept in `LabPage`, like the other labs), `components/lab/GraphicsLabPanel.tsx`, and `components/graphicsLab/` (`GraphicsLabForm`, `GraphicsRunList`, `GraphicsRunPage`, `GraphicsEngineCard`, `GraphicsRenderVerdict`, `graphicsLabView.ts`, `useOpenGraphicsRun.ts`). A run is opened at `/lab/graphics?run=<id>`. The run page shows the line, an empty brief area and four engine cards with the video's shape (two by two for landscape, four columns for portrait). `api/graphicsLab.ts` has the hooks, and the Activity page has labels for the six job types (`jobFormat.ts`, which links them to `/lab/graphics`).

**Checked.** `ruff check`, `ruff format --check`, `npm run lint`, `typecheck` and `build` pass. Migration `0079` upgrade, downgrade and upgrade again on a throwaway `DATA_DIR`; the stored schema has the constraints above. `alembic check` still reports seven FLOAT to REAL differences on tables older than this phase (none on the new tables). A temporary backend on a throwaway database answered: create (trimmed line, 201), portrait size 1080 x 1920, an empty line, 301 characters and a bad orientation (422 with a message), 300 characters accepted, an extra key refused, list and `before_id` paging, get of a missing run (404), `PATCH` of a verdict and a note on a render row made by hand (clear the verdict and the note stays; a bad verdict and a 1001-character note are 422; a missing render is 404), the delete preview showing why it is refused while a job runs, `DELETE` 409 while a job runs, 204 after it ended, the renders gone, a `lab/<32 hex>.mp4` file removed and a file whose name is not a stored name left alone, a second delete 404, and the other kinds of lab sample still answered. In headless Chrome (a Vite server in front of the temporary backend) a landscape and a portrait run were made from the form, opened, and deleted from the run page; the list refreshed; a missing run in the address shows "Run 99999 does not exist"; the other Lab tabs and every other Lab list route answer. A caption regression check burned an ASS file with the styles "Montserrat ExtraBold" and "Inter Medium" with `fontsdir` set to `assets/fonts`: libass picked `Montserrat-ExtraBold` and `Inter-Medium` for them and logged no font error, so the explainer captions are unchanged.

**For the later phases.**

- `store.owner_name` does not know the six Graphics job types yet, so the Activity page would show such a job under "Video lab"; GFX-003 should add them when it adds the first handler.
- `lab_deletion._voice_run_uses` does not list a Graphics run as a user of a speech; GFX-004, which sets `speech_run_id`, must add it so that deleting a speech used by a run is refused or explained.
- No handler is registered for any of the six job types, and every `start` is `None`: nothing can queue a Graphics job yet.
- Voice field of the form: not added (GFX-004).
- The `schema.d.ts` was generated with `npx openapi-typescript` against the temporary backend (`npm run gen:api` does the same against a running backend). The owner has to rebuild the Docker backend (`docker compose up -d --build backend`) so that migration `0079` is applied to the real database; nothing was reset or deleted there.

### GFX-003 — Director call: the brief and its timing

**Status:** In Progress (built and checked against a stand-in model server on 2026-11-03; the live check on excerpts 1 and 8 with the real model is open)

**Objective.** One click asks the model for the brief of a run's line. Code checks the brief and resolves it (timing, beat frames, number text, colours, zones), and the run page shows it. **Make all** starts the brief and then every engine that is built.

**Current state.** `jobs/llm_call.ask_model`, `services/llm_target` (`STORY_MODEL_KEY`), `services/number_words.numbers_in`, `services/callout_plan_writer.locate_phrase` and `check_accent`, `services/caption_plan.style_for`, and the colour roles in `services/callout_render.py`. The lab's prompt-writing jobs (`jobs/write_lab_music_prompt.py`) are the pattern for a paid job that belongs to no project.

**Scope.**

- **`services/graphics_brief_writer.py`** (pure): the instructions, `build_request`, and the reading and checks of §4.3.
- **`services/graphics_resolve.py`** (pure):
  - estimated timing at a words-per-minute setting (default 160);
  - the length rules and beat frames of §4.4;
  - the number text (US style), the derived values and the theme colours;
  - the safe area and the caption area.
- **Job `write_lab_graphic_brief`:** `llm` provider, `never_rerun`, the story role. It saves the brief on the run.
- **Before the call:** a line whose estimated speech is longer than 15 s is refused before any paid call.
- **API:** start the brief, and **Make all**. Getting a run includes the brief and the resolved brief.
- **Run page:** the kind, intent and visual brief; the facts and derived values with their on-screen text; the beats with their times; the theme as colour swatches; **Ask again**, which makes a new run with the same line.
- **Make all:** starts the brief. When the brief is saved, it calls `start` for each engine the registry marks as built (best effort, with each failure kept on that engine's card). Engines that are not built are skipped.
- **Planning decides:**
  - the matching rule for facts and `said_as`;
  - the rounding of the number text;
  - the palette colours and the contrast rule for the accent;
  - the safe-area margins;
  - how the caption area is worked out from `style_for`;
  - the name and group of the words-per-minute setting;
  - `max_tokens`.

**Out of scope.** The voice (GFX-004). Any engine call (GFX-006, GFX-009, GFX-010).

**Dependencies.** GFX-002.

**Expected outcome.** For each excerpt in Appendix A, the run page shows a brief the owner can read in a few seconds, with every number traced to the line and every beat at a time.

**Verification criteria.**

- The brief for excerpt 1 has three facts and a derived value shown as `+158%`.
- A brief with a number the line does not say, a beat phrase not in the line, beats out of order, or an unknown kind is refused and asked again (checked by feeding fixed answers to the reader).
- A line estimated at over 15 s is refused before the call.
- Excerpt 8 (no numbers) gives a brief with no facts and `kind: concept`, or a reasoned other kind.
- **Make all** with no engine built makes only the brief.
- Standard checks.

**Completion checklist.**

- [x] Writer, checks, resolver
- [x] Job, API, run page, Make all
- [x] Setting, docs, standard checks (ruff, ESLint, `tsc`, `gen:api` and the production build pass)
- [ ] Live check: excerpt 1 (three facts and `+158%`) and excerpt 8 (no facts, `concept`) with the real model (two paid calls, owner's click)

**Completion notes.** Built on 2026-11-03. No migration. The "Planning decides" items are settled in §4.3 (matching rule) and §4.4 (rounding, colours, safe area, caption area, timing). The rest:

- **Modules.** `services/graphics_brief_writer.py` (instructions, `build_request`, `line_words`, `line_tokens`, `phrase_starts`, `check_brief`, the enums), `services/graphics_resolve.py` (`estimated_timing`, `ensure_fits`, `frames_of`, `display_text`, `derived_value`, `theme_for`, `safe_area`, `caption_zone`, `resolve(brief, timing, width, height, fps, fonts)`), `jobs/write_lab_graphic_brief.py`. `resolve` finds the beat phrases again in the timing's words, so GFX-004 calls it again with Parakeet timing and no model call. The timing has one entry (`{text, start, end}`) for each word of `line.split()`; GFX-004's timing must keep that shape.
- **`max_tokens`** 32,000 and `reasoning_effort` `high` (the brief is about 2,000 tokens; the cap only bounds the call).
- **Setting** `graphics_words_per_minute` (160, 60 to 300, group `Graphics lab`). A run keeps the timing it was first given (stored in `lab_graphic_run.timing` when the brief is first asked for), so a changed setting applies to the next run.
- **Job** `write_lab_graphic_brief`: `llm`, `never_rerun`, the story model, no project, deduped by `run_id`. Input `{run_id, line_text, orientation, timing, then_start_engines}`. The brief and the resolved brief are saved on the run in the same transaction as `finish_job`. A failure sets `run.last_error`; the panel also shows the job's own error when a restart or a cancel ended it. The Activity page names all six Graphics job types "Graphics lab" (`store.owner_name`, `GRAPHICS_LAB_JOB_TYPES`).
- **API** (all in `api/graphics_lab.py`): `POST /api/lab/graphics/runs/{id}/brief` (200; 409 while the brief is being written or is written; 422 for a line whose estimated speech is over 15 s, before any job is made), `POST .../make-all` (200; writes the brief and starts the built engines, or with a ready brief only the built engines that have no render) and `POST .../ask-again` (201; a new run with the same line and orientation and its brief started; the old run is not changed). `GET .../runs/{id}` has typed `brief` and `resolved`.
- **Make all and engine failures.** `graphics_lab.start_engines(session, run_id)` starts each built engine that has no render, committing after each one, so one failure never undoes another (a savepoint was not used, to stay clear of SQLite's savepoint quirks). A failed start becomes a render row of that engine with `last_error` ("The engine could not be started: ..."), which its card already shows. An engine phase fills in its `start` in `graphics_engines.ENGINES` and gets this for free. No engine is built yet, so that path was checked with stand-in engines only.
- **One extension of the plan:** a derived value's facts must all have the same unit, for all four operations (the plan named `difference` and `sum`), because a percent change or ratio across units means nothing.
- **Frontend:** `components/graphicsLab/GraphicsBriefPanel.tsx` (buttons, the brief, facts and derived values with their on-screen text, beats with their time, theme swatches, notes), `useStartGraphicsBrief`, `useMakeAllGraphics` and `useAskGraphicsAgain` in `api/graphicsLab.ts`, and `schema.d.ts` regenerated.

**Checked.** `ruff check`, `ruff format --check`, `npm run lint`, `typecheck` and `build` pass. Pure checks: excerpt 1's brief gives `$12B`, `$19B`, `$31B` and `+158%`, 255 frames and beats at frames 0, 63, 109, 148 and 192; a number the line does not say, a phrase not in the line, beats out of order, an unknown kind and a scale on a percent are each refused with a reason; rounding cases (`2.4x`, `+$7B`, `-3.2 pts`, `1M` for 999,999). On a throwaway `DATA_DIR`, with the language-model URL pointed at a stand-in server that answered fixed briefs: a 45-word line got 422 from the brief, Make all and Ask again with no job made; Make all on excerpt 1 queued one job, a second click got 409, the stand-in's first answer (a fact of 13 billion) was refused and the corrected retry (the reason was sent in the request) was saved, the run showed `brief_ready` with the resolved brief above; Write the brief on a ready brief got 409; Make all on a ready brief with no engine built made no render; excerpt 8's stand-in answer (`concept`, no facts) showed "No numbers" and an unreadable accent was replaced with a note; Ask again made a new run and a new job. Make all with stand-in engines (one ok, one raising) kept the failure as a render row and skipped engines that had one on the second click. In headless Chrome the run page showed the brief panel. No paid call was made, and the real database was not touched.

**Still to do for this phase.** The live check: with the real model, press Write the brief (or Make all) on excerpt 1 and on excerpt 8 and read the briefs. Each is one paid call (two at most). Update this status when it is done.

**For the later phases.**

- GFX-004 sets `speech_run_id`, so it must add a Graphics run to `lab_deletion._voice_run_uses` (done in GFX-004). It stores its timing in `lab_graphic_run.timing` in the shape above (`source` `parakeet`, one entry per word of `line.split()`), then calls `graphics_resolve.resolve` again and saves `run.resolved`. `graphics_lab.start_brief` already reuses a stored timing and refuses one whose speech is over 15 s.
- An engine phase (GFX-006 onwards) reads `run.brief` and `run.resolved` and fills in its `Engine.start`; Make all calls it through `graphics_lab.start_engines`. `start` must add its rows and job and not commit.
- The facts of a brief keep the model's `value` and `scale`; `resolved.facts[id].value` is the full number. Engines refer to numbers by id and show `display`.

### GFX-004 — Voice and word timings

**Status:** In Progress (built and checked on a throwaway database on 2026-11-03; the live check with a real saved voice, one GPU speech and one Parakeet call, is open)

**Objective.** When a saved voice is chosen, the line is spoken in it, Parakeet times the words, beat frames follow the real voice, and the voice is added to every engine's video.

**Current state.** `services/voice_lab.create_run` speaks a text in a saved voice. `jobs/time_lab_speech_words.py` (a subclass of `TimeSpeechWordsHandler`) times an Audio video lab speech with `word_timings.align` and the `word_timing_match_threshold` setting. GFX-002's `voice_audio_of(run)` returns None.

**Scope.**

- **Form:** a voice field listing every saved voice of the Voice lab. It is optional.
- **On creating a run with a voice:** the speech is made (as a Voice lab run, the way the Audio video lab does it), then the job `time_lab_graphic_words` times it and stores the timing on the run with `source: parakeet`. Below the match threshold, the timing is the estimated one with `source: estimated` and a note.
- **Beat frames** are worked out again from the stored phrases when the timing arrives, with no new model call. The graphic's length follows the real speech (§4.4).
- **`voice_audio_of(run)`** returns the speech file. Engine renders wait until the timing is stored. Each render records the timing source it used.
- **Run page:** the voice, its timing state and the match percentage, and a player for the speech alone.
- **Planning decides:**
  - whether the speech starts when the run is created or on **Make all**;
  - whether a run's voice can be changed (a suggested no: make a new run);
  - the delivery instruction for the speech, for example `explainer.DEFAULT_PRESENTER_DELIVERY`.

**Out of scope.** Adding the voice to the video (it belongs to the render job, GFX-005, which reads `voice_audio_of`). Captions.

**Dependencies.** GFX-003.

**Expected outcome.** With a voice, each beat lands on its spoken phrase. Without one, nothing changes.

**Verification criteria.**

- For excerpt 1 spoken in a saved voice, the stored beat times land on the spoken words, within about 0.1 s when played.
- A forced wrong match falls back to estimated timing, with a note.
- A run without a voice behaves exactly as in GFX-003.
- Standard checks.

**Completion checklist.**

- [x] Voice field, speech, timing job
- [x] Beats worked out from the timing, `voice_audio_of`
- [x] Run page, docs, standard checks (ruff, ESLint, `tsc`, `gen:api` and the production build pass)
- [ ] Live check: excerpt 1 in a saved voice, beat times within about 0.1 s of the spoken words (one GPU speech and one Parakeet call, owner's click)

**Completion notes.** Built on 2026-11-03. No migration, no new setting (the job uses `word_timing_match_threshold` and `transcription_url`). The "Planning decides" items:

- **When the speech starts:** when the run is made (the click on **Make run**). The brief waits for the voice: `Write the brief`, `Make all` and `Ask again` are refused with 409 while the speech is made or its words timed, and when the voice failed. The brief is therefore resolved once, from the voice timing, with no race between two jobs and no new model call.
- **Changing a run's voice:** not possible; a different voice is a new run. **Ask again** on a run with a voice makes a run that shares the same `lab_voice_run` and copies the timing, so it costs no new speech and its brief starts at once.
- **Delivery:** `direction` mode with `explainer.DEFAULT_PRESENTER_DELIVERY` (`graphics_lab.SPEECH_DELIVERY`), the line as the text, a random seed.
- **Below the match threshold:** `word_timings.align` gives estimated times over the *real* speech length; the timing keeps `source: estimated`, `match_percent`, `threshold` and a `note`.

What was built:

- **`services/graphics_lab.py`.** `create_run(session, line_text, orientation, voice_id=None)` (an unknown voice is 422; a line whose estimated speech is over 15 s is refused before any speech is made). `on_voice_finished(speech_run_id)` queues the timing job for each run with that speech and no timing. `speech_for_timing`, `voice_timing(alignment, threshold, duration_s)`, `store_timing` (no commit; false when the run already has a timing). `RunRow` gains `speech`, `voice`, `speech_job` and `timing_job`, `voice_status` (`speaking`, `timing`, `ready` or `failed`, with the error) and the run states `making_voice` and `voice_failed`. `voice_audio_of(session, run)` returns the speech's stored path, or None.
- **Job `time_lab_graphic_words`** (`jobs/time_lab_graphic_words.py`): a subclass of `TimeSpeechWordsHandler`, `gpu` provider on the Parakeet pool, deduped by `run_id`. It aligns the line with what was heard and writes the run's `timing` in the transaction that finishes the job. `jobs/lab_voice.py` queues it after storing the speech (best effort, like the Audio video lab).
- **Timing shape** (`lab_graphic_run.timing`): `{source, duration_s, match_percent, threshold, heard_text, words, note?}`, one word for each `line.split()` word, as GFX-003 asked. `duration_s` is the measured length of the speech file, so a speech over 15 s is stored but the brief is refused (422).
- **API:** `POST /api/lab/graphics/runs` takes `voice_id`; a run has `voice` (`voice_name`, `speech_url`, `speech_job`, `timing_job`, `state`, `error`, `timing_source`, `match_percent`, `threshold`, `note`), null without a voice; `ask-again` can answer 409.
- **Deleting:** a Graphics run is a user of its speech (`lab_deletion._voice_run_uses`, the carried-over item), so deleting a speech a run uses is refused with "Graphics run N"; deleting a run also removes its speech once nothing else uses it, and is refused while the speech's job or the timing job is running.
- **Frontend:** a voice select on the form (clearable, searchable), `GraphicsVoicePanel` on the run page (voice name, stage, timing source with the match percent, the note, the error, a player for the speech alone), no brief buttons while the voice is made or failed, and polling of the list and the page while a voice is made. `schema.d.ts` regenerated.

**Checked.** `ruff check`, `ruff format --check`, `npm run lint`, `typecheck` and `build` pass. On a throwaway `DATA_DIR` (the GPU server URL pointed at an unresolvable host, so nothing real was called; the speech and timing steps were simulated by writing the speech file path and calling the handler's `_match_and_store` with made-up Parakeet words): an unknown voice and a long line were refused and left no speech; a run with a voice was `making_voice`, and `Write the brief`, `Make all` and `Ask again` got 409; the speech stored queued one timing job (a second call queued none); a matching transcript gave `parakeet`, 100 percent and 27 words, and `resolve` then put beat `b2` on the frame of its spoken word (53, against 63 estimated) and gave 215 frames (255 estimated); a made-up wrong transcript gave `estimated`, 0 percent, a note, and the last word ending at the speech's end; a 16 s speech was stored and the brief refused (422); a failed speech job gave `voice_failed` with its message; the brief job's input carried the Parakeet timing; Ask again shared the speech and copied the timing; deleting the speech was listed as used by two Graphics runs; deleting one run kept the speech and deleting the last removed it; a run without a voice behaved as in GFX-003. Through the API on a temporary backend: create with and without a voice, 422 for an unknown id and for `voice_id` 0, 409 for the three clicks, the list state, and the delete preview blocked while the speech runs. In headless Chrome the form showed the voice field and the run page the voice panel ("The line is being spoken", the brief waiting). No paid call was made, the real GPU server was not reached, and the real database was not touched.

**Still to do for this phase.** The live check: pick a saved voice, make a run with excerpt 1, wait for "Voice ready", play the speech, then press Write the brief and compare each beat's time with the spoken words (about 0.1 s). That is one GPU speech, one Parakeet call and one paid model call. Update the status when it is done. The owner has to rebuild the Docker backend (`docker compose up -d --build backend`) for the new code; there is no migration.

**For the later phases.**

- GFX-005 reads `graphics_lab.voice_audio_of(session, run)` for the speech and adds it to every engine's video. The speech file can be longer than the graphic (the graphic ends 0.5 s after the last word), so the render must cut the audio to the video's frame count (`resolved.frames`).
- Each render should record `resolved.timing_source` (`estimated` or `parakeet`) in its metrics. With a voice, the run's `timing.note` explains an estimated fallback.
- A run with a voice always has its timing stored before its brief, so `resolved.timing_source` is `parakeet` or `estimated` (the fallback), and the beat frames already follow it. No later phase has to work the frames out again.

### GFX-005 — Motion service and the render job

**Status:** Not Started

**Objective.** A third container that renders a Remotion composition to an exact MP4 while isolated from the internet and from the app's files. Also the one render job every engine uses, proven with a test card.

**Current state.** `docker-compose.yml` has `backend` and `frontend`. The backend has FFmpeg and `ffprobe`. Lab media is stored through `services/storage.get_storage()`. There is no Node runtime outside the frontend build stage (`node:24-slim`).

**Scope.**

- **`motion/`:**
  - a Node project with Remotion (the current stable version when planned) and the HTTP server of §4.6 (`/health`, `/renders`, `/renders/{id}`, `/renders/{id}/file`, `DELETE`);
  - the compositions `TestCard`, `Templates`, `Blocks` and `Generated`, the last three showing "not built yet";
  - the G-11 fonts loaded from files.
- **`docker-compose.yml`:**
  - the `motion` service on a new `internal: true` network that the backend also joins (the backend keeps the default network);
  - a read-only root, a `tmpfs`, a non-root user, CPU and memory limits, no `env_file`, and no `data` volume.
- **`providers/motion_renderer.py`:** start, poll, download and delete a render. Its address is a setting (default `http://motion:<port>`).
- **Job `render_lab_graphic`** (§4.7):
  - sends the work to the motion service for the Remotion engines, or to a Python hook that GFX-008 fills in (until then it fails with "not built yet");
  - checks the file with `ffprobe`, adds the voice when `voice_audio_of(run)` has one, stores the video and records the metrics;
  - puts a clear message on the job when the motion service is down.
- **Test card:** a button on the Graphics tab that renders `TestCard` at a chosen size and length and shows the result.
- **Planning decides:**
  - the HTTP framework of the server;
  - how the fonts reach the image (the build context is `motion/`, so the files are copied into it or the context is widened; either way they must be the same files the backend uses);
  - the encoding settings for every engine;
  - the job's provider and pool (for example a new pool with one slot);
  - the render time limit;
  - whether the Chrome sandbox can stay on inside the container;
  - how the test card's result is stored.

**Out of scope.** Templates, blocks and generated code (their compositions only show "not built yet"). The Python renderer (GFX-008). The layout and check endpoints (GFX-009, GFX-010).

**Dependencies.** GFX-002.

**Expected outcome.** The test card renders in both orientations at an exact frame count. The motion service cannot reach the internet or the app's media.

**Verification criteria.**

- `GET /health` lists the versions.
- A 101-frame test card at 1920 x 1080 and at 1080 x 1920 has exactly 101 frames, the right size, 24 fps, H.264 and `yuv420p`.
- The same test card rendered twice gives identical `framemd5`.
- From inside the `motion` container, a request to an outside address fails, and `/data` does not exist. The backend reaches the service.
- With `motion` stopped, the job fails with a message that names the motion service.
- The image builds and runs on the owner's machine (Apple silicon runs `linux/arm64` containers; the browser Remotion downloads must run there).
- Standard checks.

**Completion checklist.**

- [ ] `motion/` project, server, compositions, fonts
- [ ] Compose service, internal network, hardening
- [ ] Provider, `render_lab_graphic`, `ffprobe` checks, voice, metrics
- [ ] Test card button, docs, standard checks

**Completion notes.** _To be filled in._

### GFX-006 — Template catalogue and the template-spec call

**Status:** Not Started

**Objective.** The five templates' field schemas (§4.5.1), and one model call that turns a brief into a checked template spec, or into a reasoned "no template fits". The two template engines share that spec.

**Current state.** The brief and the resolved brief exist (GFX-003). The engine registry has entries for `remotion_templates` and `python_templates` (GFX-002).

**Scope.**

- **`services/graphics_templates.py`** (pure): the catalogue (templates, variants, fields, limits, beats) and the checks of §4.5.1:
  - known template, variant and fields;
  - limits and counts;
  - refs to existing facts, derived values and beats;
  - the number rule (G-7) on every text field;
  - same unit for every bar;
  - text that fits, measured with the bundled fonts in the way `font_metrics.measure` does.
- **`services/graphics_template_spec_writer.py`** (pure): the instructions (the brief, the catalogue, what each template is for), `build_request` and the reader.
- **Job `write_lab_graphic_template_spec`** (story role, `never_rerun`). One spec makes two render rows, one per template engine, sharing the same `input` and `input_job_id`.
- **Registry:** `start` for both template engines (one call per run, whichever engine starts it). While a renderer is not built, its card shows the spec and "renderer not built yet". A "no template fits" answer shows its reason on both cards.
- **Planning decides:**
  - how the text-fit check measures the text font (`font_metrics` covers only Montserrat ExtraBold today);
  - `max_tokens`.

**Out of scope.** Drawing anything (GFX-007, GFX-008).

**Dependencies.** GFX-003.

**Expected outcome.** For each excerpt, both template cards show a checked spec, or why no template fits.

**Verification criteria.**

- Excerpt 1 gives a `bar_comparison` with three bars and the highlight on `d1`.
- Excerpt 5 gives a `flow_diagram`, and excerpt 9 a `bullet_build`.
- Excerpt 8 gives "no template fits" with a reason.
- An unknown template, seven bars, a bar label with a number the line does not say, an unknown beat and a title too long to fit are each refused and asked again (checked with fixed answers).
- Standard checks.

**Completion checklist.**

- [ ] Catalogue and checks
- [ ] Writer, job, registry entries, cards show the spec
- [ ] Docs, standard checks

**Completion notes.** _To be filled in._

### GFX-007 — Remotion templates

**Status:** Not Started

**Objective.** The motion service draws the five templates from a template spec and the resolved brief, following the look rules of §4.5.1.

**Current state.** The `Templates` composition is a "not built yet" card (GFX-005). The spec exists (GFX-006).

**Scope.**

- **`motion/src/templates/`:** the five templates and their variants, the four background styles, the effects and their timing from beats, text fitting, and the colour roles.
- **The `Templates` composition** reads `{resolved, input}`.
- **Registry:** `remotion_templates` is marked as built, and its `start` queues `render_lab_graphic` once the spec is saved.
- **Planning decides:** any change to a look rule (recorded in §4.5.1 for GFX-008).

**Out of scope.** Blocks and generated code. The Python renderer.

**Dependencies.** GFX-005, GFX-006.

**Expected outcome.** Every template renders for its excerpt in both orientations, with each part appearing on its beat.

**Verification criteria.**

- Excerpts 1, 2, 3, 5 and 9 each render in landscape and portrait with the exact frame count.
- Each element appears on its beat's frame (within one frame, checked by stepping through frames).
- Nothing is drawn in the caption area.
- Bars start at zero.
- A 16-character bar label and a 32-character title fit without overflowing.
- Render again gives identical frames.
- Standard checks.

**Completion checklist.**

- [ ] Five templates, variants, backgrounds, effects
- [ ] Composition, registry, docs, standard checks

**Completion notes.** _To be filled in._

### GFX-008 — Python templates

**Status:** Not Started

**Objective.** The backend draws the same five templates from the same template spec, following the same look rules, frame by frame into FFmpeg, so Remotion and Python can be compared on identical input.

**Current state.** `render_lab_graphic` has a Python hook that fails with "not built yet" (GFX-005). Pillow and NumPy are installed. FFmpeg is in the image.

**Scope.**

- **`services/graphics_python/`:**
  - the five templates, variants, backgrounds, effects, text fitting and colour roles of §4.5.1, using the G-11 font files;
  - frames sent as raw video into FFmpeg, encoded with GFX-005's settings.
- **The drawing runs off the event loop** (a thread or a process), so the API keeps answering during a render.
- **Registry:** `python_templates` is marked as built, and its `start` queues `render_lab_graphic` once the spec is saved.
- **Planning decides:**
  - the drawing library (Pillow with supersampling for smooth edges, `skia-python`, or `pycairo`; check each one's licence, and whether it needs system packages in the image);
  - thread or process;
  - the colour conversion to `yuv420p`, so the colours match Remotion's.

**Out of scope.** Building blocks and generated code in Python.

**Dependencies.** GFX-005, GFX-006.

**Expected outcome.** The Python and Remotion template videos of one run look the same in layout and timing. The comparison shows the differences in edge quality, text rendering and speed.

**Verification criteria.**

- The same excerpts and checks as GFX-007.
- The API answers during a Python render.
- The render time is recorded.
- Render again gives identical frames.
- Standard checks.

**Completion checklist.**

- [ ] Five templates in Python, FFmpeg pipe, same encoding
- [ ] Off the event loop, registry, docs, standard checks

**Completion notes.** _To be filled in._

### GFX-009 — Building blocks

**Status:** Not Started

**Objective.** The model designs each graphic freely from building blocks (§4.5.2). Code checks the scene, the motion service measures it, the model gets one chance to fix any layout problem, and the scene is rendered.

**Current state.** The `Blocks` composition is a "not built yet" card (GFX-005). The brief and the resolved brief exist (GFX-003).

**Scope.**

- **`motion/src/blocks/`:** the blocks and effects of §4.5.2, the 12 x 12 grid inside the safe area, and the `Blocks` composition.
- **`POST /layout`** on the motion service (§4.6): the box and the text of every text element at the given frames.
- **`services/graphics_blocks.py`** (pure): the scene schema and the code checks of §4.5.2.
- **`services/graphics_block_scene_writer.py`** (pure): the instructions, `build_request` and the reader.
- **Job `write_lab_graphic_block_scene`** (story role, `never_rerun`):
  - asks for the scene and checks it, then asks the motion service for the layout;
  - when there are layout problems, asks once more with the list;
  - saves the scene on a new render row.
- **Registry:** `remotion_blocks` is marked as built, and its `start` queues the scene job and then `render_lab_graphic`.
- **Planning decides:**
  - icons (and their licence);
  - how the layout report measures text in the browser;
  - how the second ask fits within `ask_model`'s two attempts, given that the layout check is an HTTP call after the answer arrives;
  - `max_tokens`.

**Out of scope.** Generated code. Python blocks.

**Dependencies.** GFX-003, GFX-005.

**Expected outcome.** The block scenes vary from excerpt to excerpt in layout and motion, and keep every number traced, the caption area clear and the text from overlapping.

**Verification criteria.**

- Excerpts 1, 5, 7 and 8 render in both orientations.
- A scene with two overlapping titles is sent back with the problem listed and comes back fixed, or the card shows the problem after the second answer.
- A block with a number the line does not say is refused.
- Render again gives identical frames.
- Standard checks.

**Completion checklist.**

- [ ] Blocks, effects, grid, composition
- [ ] Layout endpoint
- [ ] Schema, checks, writer, job, layout retry
- [ ] Registry, docs, standard checks

**Completion notes.** _To be filled in._

### GFX-010 — Generated components

**Status:** Not Started

**Objective.** GLM-5.3 writes a whole Remotion component for each graphic (§4.5.3). It passes static checks and a compile check, gets one chance to be repaired, and is rendered in the isolated motion service.

**Current state.** The `Generated` composition is a "not built yet" card, and the container is isolated (GFX-005). The brief and the resolved brief exist (GFX-003).

**Scope.**

- **`services/graphics_component_writer.py`** (pure): the instructions with the props contract and the rules of §4.5.3, `build_request` and the reader (one TSX file).
- **`services/graphics_code_checks.py`** (pure): the static checks of §4.5.3.
- **`POST /checks`** on the motion service: transpile, then render still frames at the first, middle and last frame, and answer the errors.
- **The `Generated` composition:** runs the checked code with the props of §4.5.3 (derived values merged into `facts`).
- **Job `write_lab_graphic_component`** (story role, `never_rerun`):
  - asks for the code and runs the static checks, then `/checks`;
  - on a failure, asks once more with the errors;
  - saves the code on a new render row.
- **Registry:** `generated_component` is marked as built, and its `start` queues the component job and then `render_lab_graphic`.
- **Hardening review:** the render time limit kills a component that hangs; the service stays healthy after a component crashes; the browser runs with the strictest setting the container allows. The result is recorded in the notes.
- **The card** shows the code (folded) and the warnings.
- **Planning decides:**
  - how the code reaches the browser (a bundle per render, or one host bundle that transpiles and runs the code it is given; record the time each takes);
  - the allowed imports;
  - `max_tokens` (a component is long);
  - how the second ask fits within `ask_model`'s two attempts.

**Out of scope.** Model-written Python. Running model code anywhere but the motion service.

**Dependencies.** GFX-003, GFX-005.

**Expected outcome.** For most excerpts, a component that compiles, fits the clip length and looks designed, with any failure shown clearly instead of breaking the lab.

**Verification criteria.**

- Excerpts 1, 5 and 8 render in landscape.
- Fixed bad answers are refused before any render: a syntax error, a `fetch` call, an import of `fs`, an `https://` address and a missing default export.
- A component with an endless loop is stopped by the time limit with a clear message, and the next render still works.
- A number written directly into the code that equals a fact gives a warning.
- Render again (same code) gives identical frames.
- Standard checks.

**Completion checklist.**

- [ ] Writer, static checks, `/checks`, host composition
- [ ] Job with repair, registry, card
- [ ] Hardening review, docs, standard checks

**Completion notes.** _To be filled in._

### GFX-011 — Comparison view

**Status:** Not Started

**Objective.** The run page becomes the comparison of §4.9: the four videos side by side and in sync, each with its input, metrics, warnings and verdict, plus Ask again and Render again.

**Current state.** The run page shows the brief and four engine cards (GFX-002, GFX-003). Renders are made and stored by `render_lab_graphic` (GFX-005). The verdict and note can be saved (GFX-002).

**Scope.**

- **The grid:** two by two for landscape, four columns for portrait.
- **One shared control** to play, pause, seek and step a frame across all four videos.
- **Overlays:** the safe area and the caption area, from the resolved brief.
- **Each card:**
  - the engine's state, metrics (§4.7) and warnings;
  - the input, folded (JSON or code);
  - verdict buttons and a note;
  - older attempts listed under the newest.
- **Ask again** makes a new render for that engine through the registry's `start`.
- **Render again** makes a new render with the same input and compares the frames (§4.7), showing "identical" or "N of M frames differ" on the card.
- **Planning decides:**
  - how the videos are kept in sync (one leader video and the others following, or a shared clock);
  - where the frame comparison runs (a step of `render_lab_graphic` when `repeat_of` is set, or a small job of its own; a new job type would need a migration, so a step is preferred).

**Out of scope.** The trial batch (GFX-012). A live Remotion preview in the browser.

**Dependencies.** GFX-003, GFX-005. It is built against whichever engines exist, and the other cards say "not built yet".

**Expected outcome.** The owner can judge a run in under a minute: play once, step through the beats, and rate each video.

**Verification criteria.**

- The four videos (or the ones built) start, pause and seek together.
- The overlays line up with the caption area of `caption_plan.style_for` at both sizes.
- A verdict and a note are saved and shown again after a reload.
- Render again on a Remotion render and on a Python render gives "identical".
- Ask again keeps the earlier attempt in the list.
- Standard checks.

**Completion checklist.**

- [ ] Grid, synced control, overlays
- [ ] Cards with metrics, input, verdict
- [ ] Ask again, Render again with frame comparison
- [ ] Docs, standard checks

**Completion notes.** _To be filled in._

### GFX-012 — Trial batch and summary

**Status:** Not Started

**Objective.** One click runs the Appendix A excerpts through every engine. A summary page counts the results per engine (§4.9) and copies them as Markdown for Appendix B.

**Current state.** Every engine is built (GFX-007 to GFX-010), and the comparison view exists (GFX-011). The Music lab's trial panel is the pattern (`MusicTrialsPanel.tsx`, `musicTrialsView.ts`).

**Scope.**

- **The excerpts** of Appendix A as a fixed list in the backend, each with a key, its text and the orientation it runs in.
- **Run the trial:**
  - a form with the voice (any saved voice of the Voice lab, or none) and the orientation (each excerpt's own, or one for all);
  - before it starts, the number of paid calls it will make is shown and confirmed;
  - it makes one run per excerpt, marks it with `trial_case_key`, and starts **Make all** on each.
  - Calls go through the existing paid-call pool.
- **The summary page:** a table per engine with the counts and medians of §4.9, a link to each run, and **Copy as Markdown**.
- **Running the trial again** makes a new set of runs. The summary can be switched between sets.
- **Planning decides:**
  - how a set of trial runs is grouped (a shared creation time, or a set key in `trial_case_key`);
  - whether the excerpts live in code or in a JSON file next to them.

**Out of scope.** Judging (GFX-013). Changing any engine.

**Dependencies.** GFX-007, GFX-008, GFX-009, GFX-010, GFX-011. GFX-001's approved excerpts are recommended. GFX-004 is needed only for a trial with a voice.

**Expected outcome.** Forty videos (ten excerpts × four engines, minus any "no template fits") on one summary page, ready to be judged.

**Verification criteria.**

- One trial makes ten runs and starts every engine on each.
- The paid-call count is shown before it starts.
- The summary counts match the cards when checked by hand on two runs.
- The Markdown copy pastes into Appendix B as a table.
- Standard checks.

**Completion checklist.**

- [ ] Excerpt list, Run the trial, cost shown
- [ ] Summary page, Copy as Markdown
- [ ] Docs, standard checks

**Completion notes.** _To be filled in._

### GFX-013 — Owner judges the trial and decides (manual)

**Status:** Not Started

**Objective.** Turn the trial into decisions for the explainer pipeline.

**How:**

1. Open every trial run, play the four videos, step through the beats, and set a verdict and a note on each video.
2. Copy the summary into Appendix B.
3. Answer, in Appendix B:
   - Remotion or Python for the renderer?
   - Templates, building blocks, or both?
   - Is the generated component worth its cost and risk, for which kinds of line, and as an option or never?
   - Is anything missing from the brief, the catalogue or the blocks?
4. Ask for the pipeline document (graphic shots in explainers, the decisions of the design discussion of 2026-11-02) to be written from these answers.

**Dependencies.** GFX-001, GFX-012.

**Result (owner fills in):** _See Appendix B._

---

## 7. Progress tracking

The rules of `Implementation_phases.md` §6 apply. Update a phase's **Status** line and its row in §5 together, tick checklist items as they are done, write the **Completion notes** before marking a phase Completed, and add a row to Appendix C. Never renumber a phase. A dropped phase keeps its section with the status "Dropped: reason".

---

## 8. Open questions and risks

| # | Question or risk | Where it is settled |
|---|------------------|---------------------|
| GQ-1 | **Remotion's licence.** Closed on 2026-11-02: the owner confirmed there is no licence issue. | GFX-001 (done) |
| GQ-2 | **Apple silicon.** The motion image must run as `linux/arm64`, and the headless browser Remotion downloads must exist for it. Not checked. | GFX-005 |
| GQ-3 | **Repeatability of browser rendering.** The same machine should give identical frames. Another machine (a different CPU or browser build) may not. The trial checks the same machine only. | GFX-005, GFX-011 |
| GQ-4 | **Generated code is the riskiest engine.** The static checks can be bypassed by clever code. The real protection is the container (no internet, no files, no secrets, limits). A browser escape inside the container would still be contained, but this is not a guarantee. | GFX-005, GFX-010 |
| GQ-5 | **GLM-5.3's skill at Remotion code is unknown.** The trial measures it. A long component may need a large `max_tokens`, and each call costs more than the other engines' calls. | GFX-010, GFX-012 |
| GQ-6 | **Python drawing quality.** Without a vector library, edges and text may look rougher than in the browser. The library choice decides this. | GFX-008 |
| GQ-7 | **Estimated timing drifts** from a real voice by a few tenths of a second over a long line. With a voice, the beats follow the real words. | GFX-003, GFX-004 |
| GQ-8 | **Lines without numbers** (AI concepts) may get "no template fits". That is a result of the trial, not a defect, and it shows where blocks or generated code are needed. | GFX-006, GFX-012 |
| GQ-9 | **The number reader's known limits** (ordinals, "half", ranges, years said in two parts) can refuse a correct fact. A refusal names the fact, so the owner can reword the line. | GFX-003 |
| GQ-10 | **Cost.** A run is four paid calls plus at most one retry each, so a trial is about 40 to 80 calls. GFX-012 shows the count before it starts. | GFX-012 |

**Out of scope for the whole lab:** data you upload and live market data (both planned for the pipeline, not needed to compare engines), captions or callouts burned into the lab videos, music, and a live Remotion preview in the browser.

---

## Appendix A — Trial excerpts

The companies and numbers are made up. The owner approves or changes the list in GFX-001.

| Key | Domain | Excerpt | What it tests |
|-----|--------|---------|---------------|
| T01 | Finance | "Acme's revenue has exploded. It made 12 billion dollars in 2023, 19 billion in 2024, and 31 billion in 2025. That's more than double in two years." | Bars, a derived percent change, a beat per year |
| T02 | Finance | "Northwind's stock closed at 84 dollars on Friday, down 6.5 percent in a single day, its worst drop since March." | A KPI with a negative change |
| T03 | Finance | "Over the last five quarters, Globex's operating margin went from 18 percent to 21, then 24, dipped to 22, and reached 27 percent this quarter." | A line through five points, an axis that does not start at zero |
| T04 | Finance | "Initech trades at 45 times earnings, while its closest rival, Umbrella, trades at just 19 times. Investors pay more than twice as much for every dollar Initech earns." | A comparison of multiples, a derived ratio |
| T05 | AI | "A large language model works in three steps. It splits your text into tokens, turns each token into a vector, and then predicts the next token, one at a time." | A three-step flow |
| T06 | AI | "Retrieval augmented generation adds one step before the answer: your question searches your documents, the best matches are added to the prompt, and only then does the model write its reply." | A four-step flow with longer labels |
| T07 | AI | "On the coding benchmark, the new model scored 71 percent, up from 48 percent for the previous version, and ahead of the 64 percent of its closest competitor." | Benchmark bars with an emphasis |
| T08 | AI | "Attention lets every word look at every other word in the sentence, so 'it' can learn that it means 'the animal' and not 'the street'." | A concept with no numbers: no template should fit |
| T09 | General | "There are three reasons this matters: it is cheaper, it is faster, and it works offline." | A list that builds item by item |
| T10 | General | "Here is the part nobody talks about." | A very short line (the 3 s minimum), a statement card |

---

## Appendix B — Trial results (filled by GFX-013)

_The summary copied from the trial page, then the owner's answers to GFX-013's questions._

---

## Appendix C — Progress log

| Date | Phase | Event | Notes |
|------|-------|-------|-------|
| 2026-11-02 | — | Document written | From the design discussion with the owner. |
| 2026-11-02 | GFX-001 | In Progress | The owner confirmed the Remotion licence (GQ-1 closed) and that any Voice lab voice may be used. The excerpts are still to be approved. |
| 2026-11-02 | GFX-002 | Done | Migration `0079` (two tables, six job types), service, engine registry, API, Graphics tab with form, run list and run page, shared delete with the `graphic_run` kind, Inter Medium as the text font (G-11). Notes for the later phases are in the completion notes. |
| 2026-11-03 | GFX-003 | In Progress | Director call built: brief writer and checks, resolver (timing, frames, number text, theme, zones), job `write_lab_graphic_brief`, the three clicks (brief, Make all, Ask again), brief panel on the run page, setting `graphics_words_per_minute`. Checked against a stand-in model server; the live check on excerpts 1 and 8 is open. Notes for the later phases are in the completion notes. |
| 2026-11-03 | GFX-004 | In Progress | Voice built: optional saved voice on the form, speech made when the run is made, job `time_lab_graphic_words` (Parakeet), the brief waits for the timing, estimated fallback with a note, `voice_audio_of`, Graphics runs counted as users of a speech, voice panel on the run page. Checked on a throwaway database; the live check with a real voice is open. Notes for the later phases are in the completion notes. |
