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

Three model calls follow the director call (the template spec serves two engines). A run therefore costs four paid calls, plus at most one retry each (the block scene may take one more: its layout ask, §4.5.2).

### 4.2 Runs and renders

- A **run** is one line, one orientation and, optionally, one voice. Its brief and its timing belong to it. **Ask again** on the brief makes a new run with the same line, so a brief never changes under the renders made from it.
- A **render** is one engine's attempt for a run: its input (spec, scene or code), the job that wrote that input, the render job, the video, its metrics and warnings, and the verdict. **Ask again** on an engine makes a new render for that engine (a new model call). The two template engines share one spec call, so **Ask again** on either of them makes a new attempt on both. **Render again** makes a new render with the same input and no model call, to check that the result is repeatable (§4.7).
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

**The text layout (decided in GFX-006).** GFX-006's checks also decide how every text is laid out, so that GFX-007 and GFX-008 draw exactly the same text and only the renderer differs (G-5). The result is stored in the spec under `text`, keyed by the field path (`title`, `caption`, `bars.0.label`, `points.1.label`, `nodes.2.label`, `items.0.text`), as `{font, size, lines}`: `font` is `display` or `text` (the two fonts of G-11), `size` the font size in pixels and `lines` the text split onto one or two lines. A renderer draws those sizes and lines and makes no fitting decision of its own. A line of text is `1.2` times its size high.

- **Sizes.** A title is the display font at `round(0.06 h)` (landscape, 65 px) or `round(0.036 h)` (portrait, 69 px). Body text is the text font at `round(0.032 h)` (35 px) or `round(0.024 h)` (46 px). A `statement` item is the display font at the title size.
- **Spaces** (the width a text has, as a share of the safe area's width W): a title and a `statement` item, W; a `kpi_card` caption, W (`center`) or W/2 (`split`); a `bar_comparison` label, 0.9 W / n (`vertical`) or 0.3 W (`horizontal`); a `line_trend` label, W / n; a `flow_diagram` label, 0.85 of the node's width, which is `(W - (n - 1) x 0.06 W) / n` (`horizontal`), or 0.7 W (`vertical`); a `bullet_build` item in a `list`, 0.92 W. The on-screen text of a number is written by code and is not fitted. Only widths are checked: where a text sits vertically, inside the safe area and out of the caption area, is for the renderer.
- **The fit rule.** A text is measured in its font file (Pillow, at the size it is drawn at) and must be within 97 percent of the width of its space; the rest leaves room for the small differences between two renderers' kerning. It is tried on one line at the largest whole-pixel size from 100 down to 70 percent of its size. If that fails, it is tried on two lines, split at the word break that keeps the longer line shortest, again from 100 down to 70 percent. If that fails too, or the text is one word, the spec is refused with the text and the width of its space.
- **The spec shape of each template** (all but the template and the beats are checked; an unknown key is refused; a `null` key counts as absent):

| Template | `fields` | `beats` |
|---|---|---|
| `kpi_card` | `title`, `value` (ref), `change?` (ref), `caption?` | `title`, `value`, and `change` and `caption` when the field is given |
| `bar_comparison` | `title`, `bars` (2 to 6 of `{label, value, emphasis?}`), `highlight?` (`{value, beat}`) | `title`, `bars` (one beat id for each bar, never going backwards) |
| `line_trend` | `title`, `points` (3 to 12 of `{label, value}`), `end_label?` (ref) | `title`, `points` (one beat id for each), `end_label` when given |
| `flow_diagram` | `title`, `nodes` (2 to 6 of `{label, beat}`, never going backwards) | `title` |
| `bullet_build` | `title?`, `items` (1 to 4 of `{text, beat}` for `list`, exactly 1 for `statement`) | `title` when the title is given |

`variant` may be left out: the first one is used, and `vertical` for a `flow_diagram` in a portrait video. The stored spec is `{template, variant, fields, beats, text, catalogue_version}`, or `{template: null, reason, catalogue_version}` when no template fits.

**The template layout (decided in GFX-007).** The look rules above leave out where each part sits, so GFX-007 fixes it here and GFX-008 draws the same picture. Names: the safe area is `L, T, R, B`, its width `W = R - L`, the video's height `h`; `body` is the body size and `title` the title size of the look rules (the sizes in `text` may be smaller). All lengths are in pixels and rounded as the code does (`motion/src/templates/layout.ts` and the template files are the reference).

- **The content box.** It runs from `T + title block + round(0.04 h)` down to `caption_zone.top - round(0.03 h)`. With no title it starts at `T`. The title block is `lines x size x 1.2` high and is drawn at `(L, T)`, left aligned, in `text`. **Nothing except the background is drawn below the content box's bottom.** A template whose parts do not fit above it is refused when drawn (the render fails with a message).
- **Numbers.** A number is in the display font, drawn at the size the template says, or at the largest whole pixel size below it at which its final text is within 97 percent of its space. Its box has the width of its final text, and the digits count up inside the box from its left edge (the box is aligned as the template says). A number counts only its digits (from 0 to the target, with the target's decimals and commas, half up); the sign, `$`, the letter `K`, `M`, `B` or `T`, and the suffix stay. A number whose unit is `none` (a year) does not count. On its last frame the text is exactly `display`.
- **Entering.** `p = ease(clamp((frame - beat_frame + 1) / D, 0, 1))`, with `D` of 12, 18 or 24 and `ease(t) = 1 - (1 - t)^3`. A part draws nothing while `p = 0`; then it has opacity `p` and is `(1 - p) x 0.03 h` too low. A bar or a line segment grows with `p`; a number counts with `p`.
- **A pill** (the highlight, the end label) is a rounded rectangle in `accent`, as high as `1.2 x size + 2 x round(0.3 size)` with full-height corners, with the number in `background` colour at `size = body` (smaller to fit 30 percent of `W`), and `round(0.6 size)` of space left and right of it. It is at the right edge `R`, at the top of the content box, and the plot below it starts `round(0.02 h)` lower.
- **`kpi_card`.** The number is `text`, at `round(0.14 h)` (landscape) or `round(0.07 h)` (portrait), fitted to `W` (`center`) or `0.45 W` (`split`). The change is at `title` size, fitted the same way, and is `positive` when its value is above zero, `negative` below it and `text` at zero. The caption is `muted`. The gap between parts is `round(0.02 h)`. `center`: the three are centred horizontally and stacked, the stack centred in the content box. `split`: the number is left aligned at `L`; the change and the caption are left aligned at `L + W/2` and stacked; both columns are centred vertically in the content box.
- **`bar_comparison`, `vertical`.** Slots of `W / n`; a bar is `min(0.6 slot, 0.2 W)` wide, centred in its slot, `accent` when it has `emphasis` or when no bar has it, otherwise `muted`, with corners of `round(h / 270)`. The range is from `min(0, lowest value)` to `max(0, highest value)`, so the baseline is the value 0 (a `muted` line `round(h / 540)` thick across `W`, which appears with the first bar). Bars grow from the baseline (downwards when negative). Each value is in `text` at `body`, centred above its bar's end (below it when negative), `round(0.01 h)` away. The labels are in `muted`, centred in their slots, at the bottom of the content box. The plot is between the value row (one line of values) at the top and the label row at the bottom, and is at least `round(0.15 h)` high.
- **`bar_comparison`, `horizontal`.** `n` equal rows in the content box. The label column is `0.3 W` wide at `L`, right aligned, centred in its row, in `muted`. The bars start `round(0.015 W)` to the right of it (and, when a value is negative, after room for a value to their left); the longest value's width plus `round(0.015 W)` is kept free at the right edge. A bar is `min(0.6 row, round(0.09 h))` thick, centred in its row; the value is in `text` at `body` (fitted to `0.2 W`), `round(0.015 W)` after the bar's end.
- **`line_trend`.** A point's x is the centre of its slot (`W / n`); the plot is between the value row and the label row (a label is centred in its slot, `muted`) and at least `round(0.15 h)` high. The y of a value is linear over the axis (the data with 10 percent of its spread on each side, or `max(1, 0.1 x |highest|)` of spread when all values are equal). Three `surface` lines, `round(h / 540)` thick, at the top, the middle and the bottom of the plot. The line is `accent`, `max(3, round(0.004 h))` thick with round ends. Its first dot (radius `round(0.008 h)`, growing with `p`) appears on the first beat; the segment to each later point is drawn from the point before to it as far as `p` of that point's beat. Each point's value is `text` at `body`, centred above its dot. `area` fills from the line down to the bottom of the plot with `accent` at 20 percent opacity, as far as the line has been drawn. The end label is a pill.
- **`flow_diagram`.** A node is a rounded box (corners `round(0.3 x size)`) in `surface` with a border of `accent` `max(2, round(h / 360))` thick, as high as its tallest label plus `2 x round(0.35 x size)` (all nodes have one height), its label centred in it, in `text`. `horizontal`: the nodes are `(W - (n - 1) x 0.06 W) / n` wide in a row at `L`, the row centred vertically. `vertical`: the nodes are `0.7 W / 0.85` wide, centred horizontally, stacked, with a gap of `min(round(0.05 h), what is left)`, at least `round(0.02 h)`, the stack centred vertically. The arrow to a node (none to the first) is `muted`, `max(2, round(h / 270))` thick, with a head `round(0.012 h)` long; it runs across the gap, keeping 15 percent of the gap free at both ends, and is drawn as far as `p` of the node's beat.
- **`bullet_build`, `list`.** Items from the top of the content box, each as high as its lines, with `round(0.6 x size)` between them. The dot is `accent` with a radius of `round(0.18 x size)`, centred at `L + 0.04 W` and on the middle of the item's first line. The text is `text`, left aligned at `L + 0.08 W`. **`statement`**: the one item is in `text`, centred horizontally and vertically in the content box.
- **Backgrounds** (over the whole frame, still): `solid` is `background`. `gradient` is vertical, from `background` at the top to `surface` at the bottom. `grid` is `background` with `surface` lines `max(1, round(h / 540))` thick every `round(0.08 h)`, from the top left corner. `glow` is `background` with a circular gradient at the centre of the frame, of radius `round(0.6 x max(width, height))`, from `accent` at 8 percent opacity to `accent` at 0.

#### 4.5.2 Block scene (GFX-009)

The model designs the scene freely from blocks we wrote once. Code checks it, and the motion service measures it.

```json
{
  "elements": [
    { "id": "title", "block": "text", "style": "title", "text": "Acme revenue",
      "region": [1, 1, 8, 2], "enter": { "beat": "b1", "effect": "slide_up" } },
    { "id": "bars", "block": "bar_series", "values": ["f1", "f2", "f3"], "labels": ["2023", "2024", "2025"],
      "orientation": "vertical", "emphasis": ["f3"],
      "region": [1, 3, 7, 9], "enter": { "beats": ["b2", "b3", "b4"], "effect": "grow" } },
    { "id": "growth", "block": "badge", "value": "d1", "role": "positive",
      "region": [9, 4, 12, 6], "enter": { "beat": "b5", "effect": "pop" } },
    { "id": "link", "block": "arrow", "from": "bars", "to": "growth",
      "enter": { "beat": "b5", "effect": "draw" } }
  ]
}
```

- **Blocks (`blocks_version` 1):** `text` (styles `title`, `label`, `body`), `counter`, `bar_series` (2 to 6 bars, vertical or horizontal, from zero), `line_series` (3 to 12 points, optional area), `node`, `arrow`, `table` (up to 5 rows and 4 columns), `badge`, `highlight` (a box around another element) and `progress_ring` (a percent from 0 to 100). There are **no icons** in this phase: they need an icon set and its licence, so they stay a later option.
- **Effects.** Any block: `fade`, `slide_up`, `slide_left`, `pop`. Per block: `grow` (bars, ring), `draw` (line, arrow, highlight, ring), `count_up` (counter, badge with a value, ring), `typewriter` (text). A `line_series` takes only `draw` or `fade`; a `bar_series` takes `grow`, `fade`, `slide_up`, `slide_left` or `pop`. A series enters part by part (`enter.beats`, one beat for each value, never backwards in the line). An optional `exit` is `{beat, effect}` with one of the four general effects only, played backwards, at a beat after the entrance.
- **Roles.** One set for every block: `text`, `muted`, `accent`, `positive`, `negative`, `number`.
- **Regions:** `[first column, first row, last column, last row]` on a 12 x 12 grid inside the safe area, counted from 1. Rows above the caption area only: 10 in landscape and 8 in portrait (a cell is 144 x 81 px in landscape and 81 x 144 px in portrait). `arrow` and `highlight` have no region: they follow other elements (`from`/`to`, `target`) and must not enter before them. Two elements an arrow joins need an empty column or row between them.
- **Code checks** (`graphics_blocks.check_scene`): at most 12 elements and 6 text elements; known blocks, effects for the block, beats and refs; one unit in a series; regions inside the grid and above the caption area; texts within their length limits; the number rule (G-7) on every text. It returns `{blocks_version, elements}`.
- **Layout check:** the motion service reports the box and the text of every text at each beat's frame (where an element enters or leaves) and at the last frame (§4.6, `POST /layout`). `graphics_blocks.layout_problems` lists a text outside the safe area, inside the caption area, overlapping the text of another element, smaller than 2 percent of the height, and the service's own issues (a plot under 5 percent of the height, an arrow with no room). At most 12 problems are listed.
- **The second ask.** With problems, the model is asked once more with its scene and the list (`layout_retry_request`). That call has an attempt of its own (`ask_model(..., max_attempts=1)`), so a scene costs up to 3 paid attempts: 2 for the code checks and 1 for the layout. A usable new scene is measured again and replaces the first unless it has more problems; a failed or unusable answer keeps the first scene.
- **Stored input** of the render row: `{blocks_version, elements, layout: {checked, problems, asked_again, kept_first?, reason?}}`. `layout.checked` is false when the motion service could not be reached; the scene is saved anyway and the render reports the service's message. The problems are the first warnings of the render and `metrics.layout_problems` counts them.

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

- Imports come only from an allowed list (**decided in GFX-010**): `react`, `remotion`, `@remotion/shapes` and `@remotion/paths`. `import` and `export ... from` of any other module, and a bare `import "x"`, are refused. The browser side is a second guard: the component is evaluated with a `require` that knows only these four (and `react/jsx-runtime`, which the JSX transform needs).
- There is exactly one default export.
- None of these appear: `fetch`, `XMLHttpRequest`, `WebSocket`, `EventSource`, `eval`, `Function(`, `import(`, `require(`, `localStorage`, `sessionStorage`, `indexedDB`, `document.cookie`, `window.open`, `navigator`, `<iframe`, `<script`, or any `http:`, `https:` or `//` address.
- At most 40,000 characters.

**The compile check** follows: the motion service transpiles the code and renders still frames at the first, middle and last frame (`POST /checks`, §4.6). An error goes back to the model once, with the code and the error text, and the new code is checked the same way. If it still fails, the job fails and the card shows the code and the errors; no render is made.

**Warnings, not refusals (decided in GFX-010):** a number literal in the code equal to a fact's or a derived value's value (the full value, the value as the line says it, or a number of its `display`; a whole number under 10 is not reported, because it is too common as a size or an opacity), and any number in the text on screen at the three checked frames that the line does not say and no fact's `display` shows. The text is what the browser reports (`/checks` `texts`). They are stored in `input.warnings`, are the first warnings of the render, and `metrics.untraced_numbers` counts them.

The static checks are not the security boundary. The container is (G-8, GFX-005, GFX-010).

### 4.6 The motion service (GFX-005)

A new folder `motion/` holds a Node project with Remotion. It builds into a third container, `motion`. One HTTP server inside it takes render work from the backend.

| Endpoint | Phase | What it does |
|---|---|---|
| `GET /health` | 005 | Versions of Remotion, Chrome, the template catalogue and the block library |
| `POST /renders` | 005 | Starts a render: `{engine, width, height, fps, frames, resolved, input, code?, encoding?, time_limit_s?}`. `engine` is `test_card`, `remotion_templates`, `remotion_blocks` or `generated_component`. Answers `202 {render_id}` |
| `GET /renders/{id}` | 005 | `queued`, `rendering`, `done` or `failed`, with progress, the error and the times |
| `GET /renders/{id}/file` | 005 | The finished MP4 |
| `DELETE /renders/{id}` | 005 | Removes the file from the service |
| `POST /layout` | 009 | The boxes of the texts of a block scene at the given frames: `{width, height, fps, frames, resolved, input, at_frames}` (at most 32 frames). Answers `200 {frames: [{frame, texts: [{element, part, text, font, size, box}]}], issues}`, or `422 {error}` for a scene that cannot be drawn. It uses `selectComposition` on the `BlocksLayout` composition, which measures in the browser; one at a time, 0.2 to 0.7 s, 60 s limit |
| `POST /checks` | 010 | `{width, height, fps, frames, resolved, code}` (code at most 40,000 characters). Transpiles the component with esbuild and renders PNG stills at the first, middle and last frame in a browser of its own (one check at a time, 60 s limit; closing that browser ends a page stuck in a loop). Answers `200 {ok, stage, errors: [{frame, message}], texts: [{frame, text}], check_s}`: `stage` is `transpile` or `render` for the first error. A component that does not compile or draw is `ok: false`, not an HTTP error; `422 {error}` only when no browser can be started |

- **Compositions:** `TestCard` (GFX-005), `Templates` (GFX-007), `Blocks` (GFX-009), `Generated` (GFX-010). GFX-005 registers all four, with the last three showing a "not built yet" card, so each engine phase only fills in its own folder.
- **Isolation:** the container is only on an `internal: true` Docker network that the backend also joins. It has a read-only root filesystem, a `tmpfs` for its work, a non-root user, CPU, memory and time limits, and no environment secrets. The browser is downloaded when the image is built, because the container has no internet when it runs.
- **Concurrency:** one render at a time by default (the `graphics_max_parallel_renders` setting, 1 to 4, limits the backend's jobs). The service itself runs at most four at once and queues the rest.
- **Sandbox (built in GFX-005):** Chrome's own sandbox cannot be on, because Remotion always starts it with `--no-sandbox`; the container is the boundary.

### 4.7 The render job and its checks (GFX-005)

One job type, `render_lab_graphic`, makes every engine's video:

1. It sends the work to the engine's renderer: the motion service for the three Remotion engines, or the Python renderer in the backend for `python_templates` (GFX-008).
2. It checks the file with `ffprobe`: exact frame count, size, 24 fps, H.264 `yuv420p`. A check that fails is a warning on the render, not a failure.
3. When the run has a voice, it adds the voice with FFmpeg, copying the video stream. Every engine gets the same audio. A run without a voice gives a video with no audio track.
4. It stores the video as lab media and records the metrics.

All engines encode with the same settings, decided in GFX-005: libx264, CRF 18, preset medium, `yuv420p`, BT.709, PNG frames, no audio (`services/graphics_render.ENCODING`). GFX-008 uses the same ones.

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
| GFX-005 | Motion service and the render job | Code | 002 | In Progress (built and checked; the owner's rebuild and click on the Docker stack is open) |
| GFX-006 | Template catalogue and the template-spec call | Code | 003 | In Progress (built and checked; the live check with the real model is open) |
| GFX-007 | Remotion templates | Code | 005, 006 | In Progress (built and checked on the host motion service and a throwaway backend; the owner's rebuild and the live check with the real model are open) |
| GFX-008 | Python templates | Code | 005, 006 | In Progress (built and checked on the host and on a throwaway backend; the owner's rebuild and the live check with the real model are open) |
| GFX-009 | Building blocks | Code | 003, 005 | In Progress (built and checked on the host and on a throwaway backend; the owner's rebuild and the live check with the real model are open) |
| GFX-010 | Generated components | Code | 003, 005 | In Progress (built and checked on the host motion service and a throwaway backend; the owner's rebuild and the live check with the real model are open) |
| GFX-011 | Comparison view | Code | 003, 005 | In Progress (built and checked on the host, a throwaway backend and headless Chrome; the owner's rebuild and a look at a live run are open) |
| GFX-012 | Trial batch and summary | Code | 007, 008, 009, 010, 011 | In Progress (built and checked on a throwaway backend with a stand-in model and headless Chrome; the owner's rebuild and the first real trial are open) |
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

**Status:** In Progress (built and checked on 2026-11-03: the image was built and run as `linux/arm64`, and the job and the page were checked on a throwaway database; the owner's rebuild of the real stack and one click of the test card are open)

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

- [x] `motion/` project, server, compositions, fonts
- [x] Compose service, internal network, hardening
- [x] Provider, `render_lab_graphic`, `ffprobe` checks, voice, metrics
- [x] Test card button, docs, standard checks (ruff, ESLint, `tsc`, `gen:api` and the production builds pass)
- [ ] Live check on the owner's Docker stack (`docker compose up -d --build`, then the **Motion service test card** on the Graphics tab, in both orientations)

**Completion notes.** Built on 2026-11-03. No migration. Two new settings (`motion_service_url`, `graphics_max_parallel_renders`). The "Planning decides" items:

- **HTTP framework:** Fastify 5, run with Node 24's built-in type stripping (`node src/server/index.ts`, no build step for the server). The compositions are bundled with `@remotion/bundler` when the image is built.
- **Fonts:** the compose file adds the backend's font folder as a named build context (`additional_contexts: fonts: ./backend/app/assets/fonts`), and the `Dockerfile` copies `Montserrat-ExtraBold.ttf` and `Inter-Medium.ttf` from it. They are the same files the backend uses (G-11). The compositions load them with `@remotion/fonts` and wait for them before the first frame. `npm run fonts` copies them for a run outside Docker.
- **Encoding for every engine:** libx264, CRF 18, preset medium, `yuv420p`, BT.709, PNG frames, no audio. It is defined once as `services/graphics_render.ENCODING` and sent with every render; GFX-008 must use the same values.
- **Pool:** a `local` job with its own pool of `graphics_max_parallel_renders` slots (default 1, up to 4). The motion service has its own queue (at most `MAX_PARALLEL`, default 4, at once, and 2 browser tabs for each render).
- **Time limit:** 300 s a render in the service (a request can ask for 10 to 900 s with `time_limit_s`); the backend waits up to 60 s longer. A render over the limit is stopped and the job says "The render ran past its time limit of 300 s and was stopped."
- **Chrome sandbox:** it cannot stay on. Remotion always starts Chrome with `--no-sandbox`, and the container does not give Chrome the permissions its sandbox needs (all capabilities are dropped). The container is the boundary (G-8): no internet (`internal: true` network), no volume, no secrets, a read-only root with a 1 GB `tmpfs`, a non-root user (uid 10002), `cap_drop: ALL`, `no-new-privileges`, 4 CPUs, 4 GB of memory and 512 processes.
- **Where the test card's result is stored:** in its job's `output` (the file under `media/lab/` and the metrics), because it belongs to no run. **Only the newest test card is kept** (the owner's decision): storing a new one deletes the older files (`graphics_lab.prune_test_cards`, which checks that nothing else uses a file).

What was built:

- **`motion/`:** `package.json` (Remotion 4.0.540, Fastify, Node 24), `Dockerfile` (`node:24-bookworm-slim`, the libraries Chrome needs, `npm ci`, the fonts, `scripts/bundle.ts`, which bundles the compositions, downloads Chrome Headless Shell for the image's architecture and writes `build/versions.json`), `src/Root.tsx` (compositions `TestCard`, `Templates`, `Blocks` and `Generated`; the last three show a "not built yet" card; each takes its size, frame rate and length from the render's props), `src/TestCard.tsx` (deterministic: the safe-area box, the caption zone, the title, size and rate, a frame counter and a progress bar), `src/server/` (`index.ts` routes, `schema.ts` validation, `renders.ts` the queue, the time limit and the sweep of old files after 30 minutes, `versions.ts`).
- **Endpoints:** `GET /health` (`ok`, `remotion`, `chrome`, `node`, `templates` and `blocks` null until GFX-006 and GFX-009, `max_parallel`, `queued`, `rendering`), `POST /renders` (202 `{render_id}`; 400 for a body that does not fit the schema: even sizes 64 to 4096, 1 to 60 fps, at most 720 frames, 1 MB), `GET /renders/{id}`, `GET /renders/{id}/file`, `DELETE /renders/{id}` (204).
- **Backend:** `providers/motion_renderer.py` (health, start, status, download, delete; an unreachable service gives "The motion service (URL) did not answer: ... Check that it is running"), `services/graphics_render.py` (the encoding, the request body, the checks of the probe, and `python_renderer`, the hook GFX-008 fills in), `jobs/render_lab_graphic.py` (the job), `services/graphics_lab.py` (`queue_render` for GFX-007 to GFX-010 to call, `start_test_card`, `newest_test_card`, `prune_test_cards`), `services/ffmpeg.probe_video` now also returns `codec_name` and `pix_fmt`, and the phases of the job (sending, drawing with a percent, downloading, checking, adding the voice, saving).
- **API:** `POST /api/lab/graphics/test-cards` (`{orientation, frames}`, frames 72 to 360, 201, 409 while one is active, 422) and `GET /api/lab/graphics/test-cards/newest` (the newest job and the newest stored video).
- **Frontend:** `GraphicsTestCardPanel` (orientation, frames, **Render test card**, the job's phase or error, the video, and badges for the frame count, size, frame rate, codec and pixel format, with the render time and file size) in a "Motion service test card" box on the Graphics tab, polled while the job runs. `schema.d.ts` regenerated.

**Checked.**

- **Apple silicon (GQ-2):** the image builds and runs as `linux/arm64`, and Chrome Headless Shell for `linux-arm64` downloads and renders in the container.
- **Repeatability (GQ-3):** the same 101-frame test card rendered twice in the container gave identical `framemd5` (same machine, same container image).
- **Isolation:** from inside the `motion` container an outside address fails, `/data` does not exist, the root is read-only, and the service stays healthy after a render was stopped by its time limit.
- **Through the backend**, on a throwaway `DATA_DIR` with the motion service run on the host: a 101-frame test card at 1920 x 1080 and at 1080 x 1920 had exactly 101 frames, the right size, 24 fps, H.264 and `yuv420p` (all five checks true, no warnings); a second press while one was active gave 409; storing the portrait card deleted the landscape file; a run with a voice (an 8 s tone as its speech) gave a video of 101 frames with an AAC track of 4.208 s (101 / 24, cut to the frame count) and a run without one had no audio track; `remotion_templates` and `remotion_blocks` renders drew the "not built yet" compositions and stored their metrics (`composition` `Templates` or `Blocks`, `voice` true or false); a `python_templates` render failed with "The Python renderer is not built yet (GFX-008)."; an unreachable motion service failed the job with a message that names it. The real database and the real stack were not touched.

**Still to do for this phase.** The owner has to rebuild (`docker compose up -d --build`; the first build downloads the browser and takes a few minutes; Docker needs at least 4 GB of memory for `motion`), then press **Render test card** on the Graphics tab in both orientations. There is no migration. Update the status when it is done.

**For the later phases.**

- GFX-007 to GFX-010 call `graphics_lab.queue_render(session, render)` (no commit; deduped by `render_id`) after they have stored the render row's `input`. The job reads the run's `resolved` brief, so the run must have one.
- A composition gets `{engine, width, height, fps, frames, resolved, input, code}` as its props (`motion/src/types.ts` `GraphicInput`). Replace the body of `Templates`, `Blocks` or `Generated` in `Root.tsx` and add its own folder; compositions import without file extensions (the bundler), the server code with `.ts`.
- The motion service has no `POST /layout` or `POST /checks` yet (GFX-009, GFX-010), and `/health` reports `templates` and `blocks` as null until GFX-006 and GFX-009 fill them in.
- GFX-008 sets `graphics_render.python_renderer` to an async `(body, dest)` that writes an H.264 MP4 with no audio, using `graphics_render.ENCODING`; the job checks the file and adds the voice as for Remotion.
- A check that is false is a warning on the render, not a failure (§4.9 counts them). The metrics already hold `checks`, `render_s`, `size_bytes`, `timing_source` and `voice`.
- "Render again" and the repeatability check (§4.7) are not built here; they need only another call of `queue_render` and `ffmpeg -f framemd5` on the two files.

### GFX-006 — Template catalogue and the template-spec call

**Status:** In Progress (built and checked against a stand-in model server on 2026-11-03; the live check on excerpts 1, 5, 8 and 9 with the real model is open)

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

- [x] Catalogue and checks
- [x] Writer, job, registry entries, cards show the spec
- [x] Docs, standard checks (ruff, ESLint, `tsc`, `gen:api` and the production build pass)
- [ ] Live check: excerpts 1, 5, 8 and 9 with the real model (four spec calls, plus any brief not written yet; owner's click)

**Completion notes.** Built on 2026-11-03. No migration, no new setting. The "Planning decides" items are settled in §4.5.1 (the text layout, the fit rule, the sizes and spaces). The rest:

- **Modules.** `services/graphics_templates.py` (pure: `CATALOGUE`, `TEMPLATES`, `measure`, `fit_text`, `check_spec(answer, line, resolved)`, `default_variant`, `CATALOGUE_VERSION` 1), `services/graphics_template_spec_writer.py` (pure: the instructions and `build_request(line, orientation, brief, resolved, model=...)`), `services/graphics_template_engine.py` (`start`), `jobs/write_lab_graphic_template_spec.py`. `check_spec` takes the resolved brief only, not the brief: refs, units, beat ids and frames, safe area and size are all in it.
- **Text measuring.** `font_metrics.measure` was not reused (it measures ASS cell sizes and knows only Montserrat). `graphics_templates.measure(text, role, size)` loads `Montserrat-ExtraBold.ttf` and `Inter-Medium.ttf` with Pillow at 1000 px and scales: the width at a font size in pixels (the em), as a browser and Pillow draw it. Pillow's basic layout applies the font's kerning table only, which is why a text may fill only 97 percent of its space. GFX-007 should compare a long label's width in Chrome with `text[path].lines` once it exists, and say in its notes if the margin has to change.
- **`max_tokens`** 32,000 and `reasoning_effort` `high`, as for the brief.
- **Job** `write_lab_graphic_template_spec`: `llm`, `never_rerun`, the story model, no project, deduped by `run_id`. Input `{requested, run_id}`; the line, the orientation, the brief and the resolved brief are read from the run when it starts. In one transaction with `finish_job` the answer becomes the `input` of every render row whose `input_job_id` is the job, and a render job is queued (`graphics_lab.queue_render`) for each of those rows whose engine has `renderer_built` when the answer has a template. A failure puts its message on those rows' `last_error`. The phase `saving the template spec` is new (`phases.SAVING_TEMPLATE_SPEC`).
- **One call, two rows.** `graphics_template_engine.start` is the `start` of both template entries of the registry. Whichever is called first checks whether a template-engine render of the run already has a spec job; if so it returns that job. Otherwise it creates the job and one render row for each template engine, both with `input_job_id` set. So **Make all** makes one call, and a second click makes nothing.
- **A change to the registry (for GFX-007 and GFX-008).** `Engine` has a new flag `renderer_built` (default false). `built` still means "can be started" (`start` is set), and both template engines are `built` now. **GFX-007 and GFX-008 do not set `start`: each only sets `renderer_built=True` on its entry** (and `python_renderer` or the `Templates` composition), and the spec job then queues its render. A card with `built` and no `renderer_built` shows the spec and a "Renderer not built yet" badge. The API's `GraphicEngineOut` has `renderer_built`.
- **GFX-007 and GFX-008 read** `render.input` (the spec with `text`) and the run's `resolved`; the look rules and the text layout of §4.5.1 are the contract between them. If a renderer finds a spec it cannot draw, the card shows the failure like any other render.
- **Frontend.** `GraphicsTemplateSpec` (on the two template cards: "Writing the template spec" with the job's phase while the call runs, the template and variant, the spec as folded JSON, or "No template fits" with the reason), `readTemplateInput` and `TEMPLATE_LABELS` in `graphicsLabView.ts`, the badge in `GraphicsEngineCard`, and `schema.d.ts` regenerated.

**Checked.** `ruff check`, `ruff format --check`, `npm run lint`, `typecheck` and `build` pass. Pure checks on excerpt 1's brief and resolved brief (landscape and portrait): a good `bar_comparison` is accepted (title 65 px landscape and 69 px portrait, labels 35 px); an unknown template, seven bars, a bar label "2022 sales" (a number the line does not say), an unknown beat, beats that go backwards, bars of two units, an extra key, an unknown variant, a title over 32 characters, a title that does not fit even on two lines (portrait) and a refusal with no reason are each refused with a message; a `kpi_card`, a `line_trend` with an end label, a vertical `flow_diagram` in portrait (the default variant) and a `statement` were accepted, and a `statement` with two items was refused. On a throwaway `DATA_DIR`, with the language-model URL pointed at a stand-in server that answered fixed JSON: Make all on a ready brief made one spec job and two render rows sharing `input_job_id`; the stand-in's first answer (a label "2022 sales") was refused and the corrected retry (the reason was in the request) was saved as the same `input` on both rows; a second Make all made nothing; no render job was queued; a "no template fits" answer showed its reason on both cards (portrait run); two refused answers failed the job with the reason on both cards. In headless Chrome the cards showed the badge, the template, "Show the spec" and the reason. No paid call was made, and the real database was not touched.

**Still to do for this phase.** The live check: with the real model, press Make all on excerpts 1, 5, 8 and 9 and read the specs (excerpt 1 should give a `bar_comparison` with three bars and the highlight on `d1`, 5 a `flow_diagram`, 8 "no template fits" with a reason, 9 a `bullet_build`). Each run is one brief call and one spec call. Update the status when it is done. The owner has to rebuild the Docker backend (`docker compose up -d --build backend`); there is no migration.

**For the later phases.**

- GFX-007 and GFX-008: set only `renderer_built=True` (see above), and draw `input.text[path]` exactly.
- GFX-011's **Ask again** on a template engine cannot just call `start` again: `start` returns the run's existing spec job and adds nothing, so that Make all never makes a second call. GFX-011 has to add its own way to make a new spec job and a new pair of render rows (the next `attempt`), for example a `force` argument to `graphics_template_engine.start`.

### GFX-007 — Remotion templates

**Status:** In Progress (built and checked on 2026-11-03 on the host motion service and on a throwaway backend; the owner's rebuild of the Docker stack and the live check with the real model are open)

**Objective.** The motion service draws the five templates from a template spec and the resolved brief, following the look rules of §4.5.1.

**Current state.** The `Templates` composition is a "not built yet" card (GFX-005). The spec exists (GFX-006).

**Scope.**

- **`motion/src/templates/`:** the five templates and their variants, the four background styles, the effects and their timing from beats, text fitting, and the colour roles.
- **The `Templates` composition** reads `{resolved, input}`.
- **Registry:** `remotion_templates` sets `renderer_built=True` (its `start` is GFX-006's), and the spec job queues `render_lab_graphic` once the spec is saved. The renderer draws `input.text` exactly (§4.5.1).
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

- [x] Five templates, variants, backgrounds, effects
- [x] Composition, registry, docs, standard checks (ruff, `tsc` of `motion/` and ESLint and `tsc` of the frontend pass; no API change, so no `gen:api`)
- [ ] Live check: Make all on excerpts 1, 2, 3, 5 and 9 with the real model, then play the Remotion templates card (paid calls, owner's click)

**Completion notes.** Built on 2026-11-03. No migration, no new setting, no API or frontend change, no new npm package. The "Planning decides" items:

- **Look rules and layout.** No look rule was changed. The exact layout, which §4.5.1 did not fix, is now written in §4.5.1 under "The template layout (decided in GFX-007)", for GFX-008 to copy.
- **The axis of `line_trend`.** No tick numbers (every number on screen comes from the line, G-7). Each point shows its own value above itself; the plot has three faint `surface` grid lines. The axis range is the data with 10 percent of its spread on each side.
- **A number that counts up** and **a number's size** are decided in §4.5.1 too (the box of a number has the width of its final text; a number is made smaller when its final text would not fit its space).

What was built (`motion/src/templates/`):

- `spec.ts` (the spec types, `CATALOGUE_VERSION` 1, `readSpec`, which refuses a `{template: null}` input, another catalogue version and an unknown variant; the server imports it for `/health`), `motion.ts` (durations, ease, `progressAt`, `countedText`), `layout.ts` (the shared geometry `Ctx`, the content box, measuring numbers with the browser's canvas in the font files, `fitNumber`, `cannotDraw`), `Text.tsx` (`Enter`, `Lines`, `TextAt`, `Num`, `Pill`), `Background.tsx`, `Templates.tsx` (the composition), and one file for each of `KpiCard`, `BarComparison`, `LineTrend`, `FlowDiagram` and `BulletBuild`.
- `Root.tsx`: `Templates` draws the composition. `/health` reports `templates: 1`. `types.ts`: `Resolved` gains `facts`, `derived` and `beats`.
- `fonts.ts`: exports `fontsLoaded` and `useFontsReady()`. The composition measures text, so it draws nothing until the fonts are loaded and holds back the frame until the measured text has been drawn (the render would otherwise measure with a fallback font).
- `graphics_engines.py`: `renderer_built=True` on `remotion_templates`. The spec job then queues `render_lab_graphic` for that engine's render row. `python_templates` is not changed: its row keeps the "Renderer not built yet" badge until GFX-008.
- **A template that does not fit** fails the render with "The template cannot be drawn: ..." (the card shows it): a template whose parts are too tall for the space above the caption area, or a vertical flow whose gaps would shrink under 2 percent of the height.
- **One change to the motion service outside the templates** (`server/renders.ts`): twice in about 60 consecutive renders, Remotion's own file server of the next render hit the closing server of the one before and the browser got `net::ERR_CONNECTION_RESET`. That error (and only that one) now makes the service draw the render once more. The input was not at fault, and every other error is final. This is GFX-005 code; if it is ever seen to hide something, take it out and the render fails as before.

**Checked.** `ruff check`, `ruff format --check`, `tsc --noEmit` in `motion/`, and `npm run lint` and `typecheck` pass. Hand-written specs, passed through `graphics_templates.check_spec` with resolved briefs of estimated timing, were rendered by the motion service run on the host (`npm run fonts && npm run bundle`, then `node src/server/index.ts`): excerpts 1 (vertical and horizontal), 2 (`center` and `split`), 3 (`area` and `line`), 5 (`horizontal` and `vertical`, and the portrait default), 7 (horizontal bars with an emphasis, and vertical with the longest title), 9 (`list`) and 10 (`statement`), each in landscape and portrait, with the backgrounds `solid`, `gradient`, `grid` and `glow` and both palettes, and each again with a `solid` background for the checks below.

- **Frames.** All 44 videos checked had exactly the frame count of the resolved brief, the right size, 24 fps, H.264 and `yuv420p` (`ffprobe -count_frames`).
- **Beats.** For every beat frame `f` of every video, frame `f` differs from frame `f - 1` (a part arrives), and the frame before it was unchanged except where another part was still arriving or at one thin column of encoder noise (checked by decoding every frame; for excerpt 1 landscape, beat 109: frame 108 had 16 pixels in one column over 12 levels, frame 109 had 25,219).
- **Caption area.** With a `solid` background, every pixel of the caption band of every frame of the 32 videos with that background was within 3 levels of the background (the encoder's noise).
- **Bars from zero.** The baseline is the value 0 (both variants, negative values drawn the other way); seen on excerpts 1 and 7.
- **The longest title and label.** A 32-character title ("Coding benchmark scores by model") in portrait was made smaller to 49 px by GFX-006 and its ink was 937 px wide in the frame, against 942 px measured by Pillow and a limit of 943 px (97 percent of the 972 px safe width): the margin of GFX-006's `FIT_SHARE` held, and Chrome and Pillow differed by about 0.5 percent. The 16-character label "Previous version" was drawn inside its space in both orientations and both variants.
- **Render again.** Three renders (excerpt 3 landscape with a grid and an area, excerpt 1 and excerpt 5 portrait) were each drawn twice: all frames' `framemd5` were identical.
- **Through the backend.** On a throwaway `DATA_DIR`, with a stand-in model server (answering the brief and the spec of excerpt 1) and the motion service on the host: Make all wrote the brief, wrote one spec, made two render rows, and queued a render job for `remotion_templates` only; it succeeded (255 frames, all five checks true, no warnings, 86 KB, 6.7 s) and the row had its video; `python_templates` kept its spec and no render. No paid call was made, and the real database was not touched. Stand-in servers had to be reached by the machine's own address, because the backend maps `localhost` to `host.docker.internal`.

**Still to do for this phase.** The owner has to rebuild (`docker compose up -d --build motion backend`; there is no migration), then press **Make all** on excerpts 1, 2, 3, 5 and 9 with the real model (one brief call and one spec call each) and look at the Remotion templates cards. A run whose spec was saved before this phase has no render job: make a new run with **Ask again**, because **Render again** comes in GFX-011.

**For the later phases.**

- GFX-008 draws the same picture from the layout of §4.5.1. Where the two renderers differ by a few pixels, say so in GFX-008's notes rather than changing the layout.
- GFX-011's **Render again** needs only `graphics_lab.queue_render` on the render row and `ffmpeg -f framemd5` on the two files (see GFX-005); this phase checked that the Remotion templates render the same frames twice on one machine.
- A beat's part is fully visible `duration - 1` frames after its beat's frame (11, 17 or 23); it is already partly visible on the beat's frame.
- The caption area is kept clear by the content box ending 3 percent of the height above it. The background still covers it.

### GFX-008 — Python templates

**Status:** In Progress (built and checked on 2026-11-03 on the host and on a throwaway backend; the owner's rebuild of the Docker stack and the live check with the real model are open)

**Objective.** The backend draws the same five templates from the same template spec, following the same look rules, frame by frame into FFmpeg, so Remotion and Python can be compared on identical input.

**Current state.** `render_lab_graphic` has a Python hook that fails with "not built yet" (GFX-005). Pillow and NumPy are installed. FFmpeg is in the image.

**Scope.**

- **`services/graphics_python/`:**
  - the five templates, variants, backgrounds, effects, text fitting and colour roles of §4.5.1, using the G-11 font files;
  - frames sent as raw video into FFmpeg, encoded with GFX-005's settings.
- **The drawing runs off the event loop** (a thread or a process), so the API keeps answering during a render.
- **Registry:** `python_templates` sets `renderer_built=True` (its `start` is GFX-006's), and the spec job queues `render_lab_graphic` once the spec is saved. The renderer draws `input.text` exactly (§4.5.1).
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

- [x] Five templates in Python, FFmpeg pipe, same encoding
- [x] Off the event loop, registry, docs, standard checks (`ruff check` and `ruff format --check` pass; no API, frontend or migration change, so no `gen:api`)
- [ ] Live check: Make all on excerpts 1, 2, 3, 5 and 9 with the real model, then compare the Python and Remotion template cards (paid calls, owner's click)

**Completion notes.** Built on 2026-11-03. No migration, no new setting, no API or frontend change, no new package (Pillow and NumPy were already installed). The "Planning decides" items:

- **Drawing library: Pillow with 3x supersampling.** Each frame is drawn at three times its size and reduced with a box filter. `skia-python` and `pycairo` were not needed: Pillow is already in the image and, with the raqm layout, it draws the two font files of G-11 as the browser does. Shapes and text are drawn on an RGB image with `ImageDraw` in RGBA mode, so transparency blends as in CSS. A part that fades or slides is drawn on a copy of the frame and blended back.
- **Process, not thread.** The backend runs `python -m app.services.graphics_python <dest>` as a child process (`nice -n 10`) and sends the render body as JSON on its standard input; the child writes raw `rgb24` frames into FFmpeg. The API process only waits (`asyncio`), so a render cannot hold up a request. The time limit is the body's `time_limit_s`; on a timeout or a cancel the child is killed. Exit code 2 means "the template cannot be drawn" and the last line of its error output becomes the card's message; any other failure reports the tail of the output.
- **Colour conversion.** FFmpeg gets the same arguments that Remotion 4.0.540 gives it (read from its `ffmpeg-args.js`): `-vf zscale=matrix=709:range=limited:primariesin=709:primaries=709:transferin=709:transfer=709`, BT.709 tags, `-color_range tv`, `-pix_fmt yuv420p`, libx264 CRF 18, preset medium, `-video_track_timescale 90000`, plus the values of `graphics_render.ENCODING`. Flat colours come out identical to Remotion's in YUV.
- **Look rules and layout.** No look rule and no part of the layout was changed. Every file of `graphics_python/` is a line-by-line port of the file of the same name in `motion/src/templates/` (`motion`, `spec`, `layout`, `background`, `text`, the five templates, `templates`), with JavaScript's `Math.round` ported as `js_round`. Text boxes are laid out as the browser does (a line is 1.2 times its size high; the baseline follows from the font's ascent and descent).
- **Unchanged frames are not drawn again.** A frame is a function of the progress of every beat, so when no part is moving the previous frame's bytes are written again. The first frame is drawn before FFmpeg starts, so a template that cannot be drawn fails without leaving a file.
- **The hook.** `jobs/render_lab_graphic.py` sets `graphics_render.python_renderer = graphics_python.render` (so `graphics_render` does not import the renderer). A `PythonRenderFailed` becomes `RenderFailed` with its message. The row's `versions` for this engine are `{"pillow": ...}`. `graphics_engines.py`: `renderer_built=True` on `python_templates`.

What was built (`backend/app/services/graphics_python/`): `__init__.py` (the async `render(body, dest)` that runs the child), `__main__.py` (the child: reads the body, draws, pipes into FFmpeg), `encode.py` (the FFmpeg arguments), `canvas.py` (`Canvas`: rectangles, polygons, ellipses, lines and text at 3x, and `layer` for fade and slide), `background.py`, `text.py`, `motion.py`, `spec.py`, `layout.py`, `templates.py`, and `kpi_card.py`, `bar_comparison.py`, `line_trend.py`, `flow_diagram.py`, `bullet_build.py`. `graphics_render.py` gains `PythonRenderFailed`.

**Checked.** Throwaway scripts (not kept) drew hand-written specs through `graphics_templates.check_spec`, in both orientations, on excerpts 1, 2, 3, 5, 7, 9 and 10 (all variants) with the four backgrounds and both palettes, each also with a `solid` background. The checks below were run on 88 videos that were re-encoded losslessly (CRF 0), so that the source frames can be compared without encoder noise: 88 of 88 passed.

- **Frames.** Exact frame count, size, 24 fps, H.264 and `yuv420p` (`ffprobe -count_frames`).
- **Beats.** On every beat frame a part arrives (the frame differs from the one before), and a frame with no part arriving equals the one before it.
- **Caption area.** With a `solid` background every pixel of the caption band was within 3 levels of the background.
- **Render again.** Excerpt 1 portrait rendered three times (once through the backend, twice directly): all frames' `framemd5` were identical.
- **The API during a render.** `GET /api/health` polled every 200 ms during the 255-frame portrait render through the backend: 192 answers, the slowest 18 ms.
- **Through the backend.** On a throwaway `DATA_DIR`, with a stand-in model server (answering the brief and the spec of excerpt 1) and the motion service on the host: Make all wrote the brief and the spec, made two render rows and rendered both. The Python row had 255 frames, all five checks true, no warnings, 133 KB, `composition` `python`, `versions` `{"pillow": "12.3.0"}` and `render_s` 2.3 s; the Remotion row had 126 KB and `render_s` 6.7 s. A spec whose text layout lacked an entry failed with "The template cannot be drawn: the spec has no layout for the text "bars.0.label"." and left no file. No paid call was made and the real database was not touched.

**Measured differences from Remotion** (the same spec drawn by both, compared frame by frame on excerpts 1, 3 and 5):

- Flat colours (backgrounds, bars, pills) are identical. Edges of boxes and text are within about 2 to 4 px of Remotion's. Chrome's text looks slightly heavier than Pillow's.
- Speed: 1.2 to 4.6 s for a video in Python against about 6 to 7 s in Remotion (both on the same machine).
- **Encoder noise is common to both.** x264 places a keyframe at frame 250 and alternates its noise on static frames; a frame-to-frame check of either engine's video shows small changes at those frames when nothing moves. A lossless re-encode of the Python source frames shows they are static. The encoding settings were not changed (G-4).

**Still to do for this phase.** The owner has to rebuild (`docker compose up -d --build backend`; there is no migration and the motion service is unchanged), then press **Make all** on excerpts 1, 2, 3, 5 and 9 with the real model and compare the two template cards. A run whose spec was saved before this phase has no Python render job: make a new run with **Ask again**, because **Render again** comes in GFX-011.

**For the later phases.**

- GFX-011's **Render again** on the Python card needs only `graphics_lab.queue_render` on the render row and `ffmpeg -f framemd5` on the two files; this phase checked that the Python renderer draws the same frames three times on one machine.
- A part's timing is the same as in Remotion: fully visible `duration - 1` frames after its beat's frame.
- The docker image's FFmpeg (7.1.5) and the host's (8.0) gave the same pictures and the same encoder noise.

### GFX-009 — Building blocks

**Status:** In Progress (built and checked on the host motion service and a throwaway backend; the owner's rebuild and the live check with the real model are open)

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

- [x] Blocks, effects, grid, composition
- [x] Layout endpoint
- [x] Schema, checks, writer, job, layout retry
- [x] Registry, frontend card, docs, standard checks (`ruff check`, `ruff format --check`, `tsc --noEmit` in `motion/`, and `lint`, `typecheck` and `build` in the frontend pass; no API shape or migration change, so no `gen:api`)
- [ ] Live check: Make all on excerpts 1, 5, 7 and 8 with the real model, then look at the block cards (paid calls, owner's click)

**Completion notes.** Built on 2026-11-03. No migration, no new setting, no API change, no new package. The `job.type` `write_lab_graphic_block_scene` was added in GFX-002. The "Planning decides" items:

- **Icons: none in this phase.** Recorded as a later option (they need an icon set and its licence).
- **Measuring text.** Text is fitted in the browser with the same font loading as the templates (`fitText`: the largest whole-pixel size within 97 percent of the width, no lower limit). The `BlocksLayout` composition lays the scene out in `calculateMetadata` and returns the report in its `props`, so the backend reads it with `selectComposition` and nothing is drawn.
- **The second ask.** The code checks use `ask_model`'s 2 attempts; the layout ask is a separate call with `max_attempts=1` (a new keyword of `ask_model`), so a scene uses up to 3 paid attempts (the owner chose this over sharing the two).
- **`max_tokens`.** 32,000 (as the other story calls; tokens are paid as used), `reasoning_effort` high.

What was built: `motion/src/blocks/` (`scene.ts` types and `readScene`, `ctx.ts`, `fit.ts`, `effects.tsx`, `Item.tsx`, the layout and drawing of each block in `TextBlocks.tsx`, `Series.tsx`, `Table.tsx` and `Shapes.tsx`, `layout.ts`, `report.ts`, `Blocks.tsx`), the `BlocksLayout` composition in `Root.tsx`, `server/layout.ts` and `POST /layout` (`/health` reports `blocks: 1`), `services/graphics_blocks.py` (pure: schema, `check_scene`, `grid_rows`, `layout_frames`, `layout_problems`, `LIMIT_NAMES`), `services/graphics_block_scene_writer.py` (pure: the instructions, `build_request`, `layout_retry_request`), `services/graphics_block_engine.py` (`start`: one scene job and one `remotion_blocks` render row), `jobs/write_lab_graphic_block_scene.py` (`llm`, `never_rerun`, story model, deduped by `run_id`; the scene and the render are saved in one transaction with `finish_job`, then `queue_render`), `providers/motion_renderer.layout`, the phases `CHECKING_BLOCK_LAYOUT` and `SAVING_BLOCK_SCENE`, `graphics_render.input_warnings` (the layout problems become the first warnings of the render, `metrics.layout_problems`), and on the frontend `GraphicsBlockScene` (the blocks of the scene, the layout verdict, the scene as JSON) with `readBlockInput`. Public names changed in the template modules so this phase can reuse them: `graphics_templates.object_of`, `items_of`, `line_of_text` and `graphics_template_spec_writer.brief_for_model` lost their leading underscore.

**Deviations and extensions to §4.5.2.**

- One role set for every block; `highlight` and `arrow` have no region; effects are limited per block (above).
- Exits are the four general effects, played backwards (a later exit leaves a part out of the layout report once it has started to leave).
- Overlap is checked between texts of different elements only; boxes are the tight boxes of the text, so two left-aligned texts of different widths in one region may not overlap.
- A text is never refused for being small: it is made smaller to fit and the layout check lists it when it is under 2 percent of the height. The writer is told to give such a text a larger region.
- The highlight is drawn inside the gutter of its target's region (so it never reaches the caption area or the next region).
- A new scene from the layout ask replaces the first only when it has no more problems; otherwise `layout.kept_first` is true.

**Checked.** Throwaway scripts (not kept) on the host motion service and on a throwaway backend (`DATA_DIR` in `/tmp`, a stand-in model server, the real database and Docker stack untouched; no paid call):

- **Renders.** Excerpts 1, 5, 7 and 8 in both orientations, plus a gallery scene with every block, went end to end through the backend: exact frame count, size, 24 fps, H.264 and `yuv420p`. `/layout` took 0.2 to 0.7 s; a render about 7 s.
- **Beats and caption area.** On every beat frame a part arrives. On a `solid` background the caption area is the background colour in every frame (max difference 2 of 255).
- **Render again.** Two renders of the same input have identical `framemd5` (landscape and portrait).
- **Refusals** (`check_scene`): a number the line does not say, an unknown block, a region in row 11 (landscape) or row 9 (portrait), an unknown beat or ref, mixed units, an effect the block does not take, a duplicate id, an arrow to nothing or before its target, 13 elements, beats going backwards, an exit before the entrance, an extra key, a text over its limit. Each message names the element.
- **The layout ask** with a stand-in server: overlapping texts are sent back with the list and come back fixed (2 calls, no problems); still overlapping (2 calls, problems kept as warnings on the card); an unusable second answer (first scene kept); a second answer with more problems (first scene kept); an unusable first answer then a usable one then the layout ask (3 attempts, no more).
- **Motion service down:** the scene is saved with `layout.checked` false and the reason, and the render fails with the motion-service message on the card.

**Notes for later phases.**

- GFX-011's **Render again** on a block card is `queue_render` on the row, as for the other engines. **Ask again** makes a new run, so a new scene.
- A model that leaves two connected elements next to each other gets "no room" for the arrow: the writer tells it to leave an empty column or row.
- The motion bundle must be rebuilt (`npm run bundle`, or the image) after any change in `motion/src`.


### GFX-010 — Generated components

**Status:** In Progress (built and checked on 2026-11-03 on the host motion service and on a throwaway backend; the owner's rebuild of the Docker stack and the live check with the real model are open)

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

- [x] Writer, static checks, `/checks`, host composition
- [x] Job with repair, registry, card
- [x] Hardening review, docs, standard checks (`ruff check` and `ruff format --check`, `tsc --noEmit` in `motion/`, and ESLint, `tsc` and the production build of the frontend pass; no API shape change, so no `gen:api`)
- [ ] Live check: Make all on excerpts 1, 5 and 8 with the real model, then play the generated-component card (paid calls, owner's click)

**Completion notes.** Built on 2026-11-03. No migration (the job type was added in GFX-002), no new setting, no API change. Three new direct npm packages in `motion/package.json` (`@remotion/shapes` 4.0.540, `@remotion/paths` 4.0.540, `esbuild` 0.28.1; the last two were already in the tree through the bundler and are now pinned). The "Planning decides" items:

- **How the code reaches the browser: one host bundle.** The server transpiles the TSX with `esbuild.transform` (loader `tsx`, CommonJS, automatic JSX) and passes the result as the `compiled` prop. The `Generated` composition evaluates it with `new Function("require", "module", "exports", js)` and a `require` that knows only the allowed modules, then draws the default export. Measured on the host (warm cache): transpiling a 1.6 KB component took 28 ms; a `@remotion/bundler` bundle of the whole project took 0.5 to 0.8 s and would also write its output on every render, which the read-only container root does not allow without more `tmpfs`. A bundle per render was not built.
- **Allowed imports:** `react`, `remotion`, `@remotion/shapes`, `@remotion/paths` (recorded in §4.5.3).
- **`max_tokens`:** 48,000 (under Qwen3.8's 49,152) and `reasoning_effort` high; tokens are paid as used. The answer is one fenced `tsx` block (the first block with a default export; the whole answer when there is no fence). An answer cut off at the limit is refused.
- **The second ask:** the static checks run inside the reader of `ask_model`, so they use its 2 attempts (the second is told the reason). The browser check's error gets one more ask of its own (`max_attempts=1`) with the code and the errors, so a component costs up to 3 paid attempts, as a scene does in GFX-009.

What was built:

- **`motion/`:** `src/generated/` (`modules.ts`, the allowed `require`; `props.ts`, `GraphicProps` of §4.5.3 with derived values merged into `facts` and the font families added to the theme; `Generated.tsx`, the composition; `marker.ts` and `version.ts`, plain files the server can import), `src/server/transpile.ts`, `src/server/checks.ts` and `POST /checks` (§4.6; `/health` reports `generated: 1`), and `renders.ts`, which transpiles a generated component before the browser starts ("The component does not compile: ..."). The composition paints the theme's background under the component, so a component that paints nothing is still on the lab's background. In check mode (`report_text`) it writes the visible text (`innerText` and the text of SVG labels) to the browser's console for each still, and the server reads it with `onBrowserLog`. The unused `NotBuiltYet.tsx` was removed.
- **Backend:** `services/graphics_code_checks.py` (pure: `check_code`, `code_warnings`, `text_warnings`), `services/graphics_component_writer.py` (pure: the instructions, `build_request`, `parse_code`, `repair_request`), `services/graphics_component_engine.py` (`start`: one component job and one `generated_component` render row), `jobs/write_lab_graphic_component.py` (`llm`, `never_rerun`, story model, deduped by `run_id`; the component and the render are saved in one transaction with `finish_job`, then `queue_render`), `providers/motion_renderer.checks`, the phases `CHECKING_COMPONENT` and `SAVING_COMPONENT`, `graphics_render.component_warnings`, and `metrics.untraced_numbers` on the render. Stored input: `{code, checks: {checked, passed, stage, errors, check_s, asked_again, reason?}, warnings}`. A component that fails its checks twice is saved on the row with its errors and `last_error`, and no render is queued.
- **Frontend:** `GraphicsComponentCode` (the check result, the warnings and the code, folded) with `readComponentInput`.

**Deviations and details.**

- **The static checks read the code with its comments removed** (`strip_comments`: strings and template literals are kept, and a quote not closed on its line is taken as an apostrophe in JSX text), so a comment that says "no fetch" does not refuse a component. The `//` rule means any `//` left outside a comment. Banned names are matched as whole words.
- **`ERR_CONNECTION_RESET`** gets the same one repeat as a render and a layout check.
- **A change to the service's process (`server/index.ts`):** closing the check's browser while Remotion was still closing one of its pages (after a component that threw) made Remotion reject a promise nobody awaits, and Node stopped the whole service (seen on the third request). Only that rejection (a "Target closed" error) is now logged and ignored; any other still stops the process. If it is ever seen to hide something, take it out and the check closes its browser later.
- Numbers under 10 are not reported as a typed fact (see §4.5.3). A visible number word such as "one" counts as a number in the on-screen text, as it does for block texts.

**Hardening review** (host motion service, `linux/arm64` image not re-run):

- **An endless loop in a render:** `while (true) {}` with a 10 s limit failed with "The render ran past its time limit of 10 s and was stopped." after 10.1 s; the next render of a good component worked, `/health` answered, and no browser process was left behind. Remotion's cancel signal does end a page whose main thread is stuck, so no browser of the render's own was needed.
- **An endless loop in a check:** stopped by Remotion's own frame wait after 28 s with "waiting for the page to render the React component failed: timeout 23000ms exceeded" and a note that the component probably never finishes drawing. The check's own 60 s limit and the closing of its browser are the backstop. No browser process was left behind.
- **A component that crashes:** a thrown error, an import of `fs` and a syntax error each came back as an error with its message (the thrown error with the frame), and the service stayed healthy after repeated crashes.
- **The browser's strictest setting:** Chrome's own sandbox cannot be on (GFX-005); the container is the boundary. Nothing stricter was found that Remotion's options allow. A component runs in the same origin as the composition, with no network (the container has none), no volume and no secrets.

**Checked.** Throwaway scripts (not kept) on the host motion service (`npm run fonts && npm run bundle`, then `node src/server/index.ts`) and on a throwaway backend (`DATA_DIR` in `/tmp`, a stand-in model server answering the brief and the component, the real database and Docker stack untouched; no paid call):

- **Refused before any render** (`check_code` and `/checks`): a `fetch` call, an import of `fs`, an `https://` address, a `//` address, a missing default export, two default exports, a re-export from another module, a file over 40,000 characters and an empty answer (each message names the rule); a syntax error (`line 1, column 45: ...`, from the transpiler).
- **The repair, through the job:** `fetch` then good (the second attempt of the first call, with the reason in the request); a syntax error then good (the repair ask carried the code and the compile error; `asked_again` true); an import of `fs` twice (the job failed with the reason on the card, `checks` null); a component that throws twice (the job failed, the code and "Drawing frame 0 failed: boom in component" saved on the row, no render queued); an endless loop then good (repaired).
- **Warnings:** a typed `31` gave "The code has the number 31, the value of f3"; a text "up 42 times" in an SVG label gave "The text on screen at 0.0 s shows the number 42". Both are in `input.warnings` and the render's warnings, and `metrics.untraced_numbers` was 2.
- **Renders:** a landscape and a portrait run went end to end through the backend: 201 frames, the right size, 24 fps, H.264 and `yuv420p` (all five checks true), about 5 s each. (The excerpts' own briefs were not used: the stand-in answered the brief of excerpt 1's line for every run.)
- **Render again:** the same component rendered twice by the service gave identical `framemd5` (120 frames).
- **Motion service down:** the code was saved as "not checked" with the service's message, and the render failed with that message on the card.

**Still to do for this phase.** The owner has to rebuild (`docker compose up -d --build motion backend`; `motion` gets new npm packages, so `npm ci` runs again; there is no migration), then press **Make all** on excerpts 1, 5 and 8 with the real model (one brief call and one component call, up to three attempts, each) and play the generated-component card. A run made before this phase has no component job: make a new run with **Ask again**, because **Render again** comes in GFX-011. The first live run shows how well GLM-5.3 writes Remotion code (GQ-5); a long component may need a longer `REQUEST_TIMEOUT_S` (900 s now). Update the status when it is done.

**For the later phases.**

- GFX-011's **Render again** on the generated card is `graphics_lab.queue_render` on the row and `ffmpeg -f framemd5` on the two files, as for the other engines. **Ask again** makes a new run, so a new component.
- GFX-012 counts "every number traced" for this engine as `metrics.untraced_numbers == 0`, and the failures that were saved with no render (`last_error`, `input.checks.passed == false`) as an engine that made no video.
- The motion bundle must be rebuilt (`npm run bundle`, or the image) after any change in `motion/src`.


### GFX-011 — Comparison view

**Status:** In Progress (built and checked on 2026-11-03 on the host motion service, a throwaway backend and headless Chrome; the owner's rebuild of the Docker stack and a look at a live run are open)

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

- [x] Grid, synced control, overlays
- [x] Cards with metrics, input, verdict
- [x] Ask again, Render again with frame comparison
- [x] Docs, standard checks (`ruff check` and `ruff format --check`, ESLint, `tsc -b`, the production build and `gen:api` pass; no change to `motion/`)
- [ ] Look at a live run on the owner's Docker stack after the rebuild (`docker compose up -d --build backend frontend`; there is no migration and the motion service is unchanged)

**Completion notes.** Built on 2026-11-03. No migration, no new setting, no new package, no change to the motion service. The two "Planning decides" items:

- **Keeping the videos in sync: one leader.** The first card that has a video is the leader (`frontend/.../useSyncedVideos.ts`). It is the only video with sound; the others are muted, because every video carries the same voice. While playing, a `requestAnimationFrame` loop reads the leader's `currentTime` and moves any other video that is more than one frame away to that time. A seek or a step pauses every video and sets `currentTime = (frame + 0.5) / 24` on each, in the middle of the frame, so every browser shows exactly that frame. The native controls are gone; the playback bar is the only control. At the end every video pauses, and Play at the end starts again from the first frame.
- **Where the frame comparison runs: a step of `render_lab_graphic`**, taken when the render row has `repeat_of`. No new job type, so no migration.

**A conflict in this document, and how it was settled.** The GFX-009 and GFX-010 notes say "Ask again makes a new run". That is the run-level **Ask again** of the brief, which is unchanged. The Scope of this phase and §4.2 say that **Ask again** on an engine's card makes a new render for that engine on the same run and brief, and that is what the card's button does. For the two template engines it makes a new attempt on both cards (they share one spec call, G-5), and the button says so.

What was built:

- **Backend.**
  - `StartFn` (the registry's `start`) takes `again: bool = False`. The three engine `start` modules skip their "this run already has a job" check when it is true and make a new job and a new render row (the next attempt) for each engine they own. **Make all** still passes `False`, so it never makes a second call.
  - `graphics_lab.ask_engine_again(session, run_id, engine_key)`: 409 when the engine is not built, the brief is not written, or any attempt of the engine (for a template engine: of either template engine) has a waiting or running model call or render. Otherwise it calls `start(..., again=True)` and commits.
  - `graphics_lab.render_again(session, render_id)`: 409 when the renderer is not built, the render has no video or no input, or the engine has a waiting or running attempt. Otherwise a new row (same run and engine, the next attempt, a copy of `input`, no `input_job_id`, `repeat_of` set) is queued with `queue_render`. A second press while it runs gives 409, not a second row.
  - `graphics_lab.input_call_of(job)` (pure) turns the input job's `output.calls` and `output.usage` into the seconds, the attempts and the tokens of the model call. A repeat has none.
  - `ffmpeg.frame_md5s(path)` (`ffmpeg -f framemd5`, the first video stream only, so a voice track does not matter; None when FFmpeg cannot read the file) and `graphics_render.frame_difference(a, b)` (`{frames, differing}`). The job's new step, after the probe and before the voice, notes the phase `comparing the frames` (`phases.COMPARING_GRAPHIC_FRAMES`) and stores `metrics.repeat` as `{of, of_attempt, frames, differing}`. A comparison that cannot be made (the original's file is gone or unreadable) is stored as `{of, of_attempt, compared: false, reason}` with a warning, and the render still succeeds.
- **API** (`api/graphics_lab.py`): `POST /lab/graphics/runs/{run_id}/engines/{engine}/ask-again` (201, the run; 404, 409, 422 for an unknown engine), `POST /lab/graphics/renders/{render_id}/render-again` (201, the run; 404, 409), and a new field `input_call` on every render (`seconds`, `attempts`, `prompt_tokens`, `completion_tokens`, `reasoning_tokens`). `schema.d.ts` regenerated.
- **Frontend** (`components/graphicsLab/`): `useSyncedVideos`, `GraphicsPlaybackBar` (sticky below the header: Play or Pause, one frame back and forward, previous and next beat, a slider with a mark on each beat, "Frame f of N, t s", and the two overlay switches), `GraphicsVideoFrame` (the video, and over it the safe area as a dashed box and the caption area as a band, drawn in percent of the video's size from the resolved brief), `GraphicsRenderMetrics`, `GraphicsAttemptList`, and the reworked `GraphicsEngineCard` and `GraphicsRunPage` (which holds the chosen attempt of each engine, so the videos in the sync are the ones shown). Helpers in `graphicsLabView.ts`: `beatFrames`, `formatBytes`, `readMetrics`, `repeatText`, `renderState`, `callText`. Mutations `useAskEngineAgain` and `useRenderGraphicAgain`.
  - Each card shows, from the top: the state (writing the input, rendering with the job's phase, done, failed, no template fits), the video, the attempt number, the engine's input (as before, folded), the five checks, the render time, size, voice and timing source, the layout problems and untraced numbers, the model call's time, attempts and tokens (or "No model call: the input is the same as attempt N"), the repeat result ("Identical to attempt 2 (all 255 frames)" or "D of M frames differ from attempt N"), the warnings, the error, the verdict and note, **Ask again** and **Render again**, and the list of attempts with **Show** (which puts an older attempt in the card; its video joins the sync and the verdict is its own).
  - The grid is the one that was there: two by two for landscape, four columns for portrait.

**Checked.** Throwaway scripts in `/tmp` (not kept) on the host: the motion service from the host, a throwaway backend with `DATA_DIR` in `/tmp`, a stand-in model server answering the brief, spec, scene and component of excerpt 1 (no paid call), and headless Google Chrome (Playwright) on the built frontend. The real database and the Docker stack were not touched.

- **Ask again.** On `remotion_blocks`: a new attempt beside the old one (both listed), one scene job (two model calls, as for Make all: the layout ask); a second press while it worked gave 409 with the reason. On `python_templates`: one spec call gave both template engines attempt 2 from the same spec job, and the old attempts stayed. An unknown engine gave 422, an unknown run and an unknown render 404.
- **Render again.** On all four engines (`remotion_templates`, `python_templates`, `remotion_blocks`, `generated_component`) the new attempt had `repeat_of` set, the same input, no input job and no model call, and `metrics.repeat` was `{frames: 255, differing: 0}`: identical. A second press while it worked gave 409. With the original's file moved away, the new render still succeeded with `compared: false`, the reason and a warning.
- **In the browser** (landscape run with all four videos): the four videos had the same frame after playing and pausing (spread 0 s), after a seek to the middle, after a step forward twice and back once, after the next and previous beat, and everything was paused at the end of the clip; only the first video was unmuted. The overlays: the safe area box was 5 percent from each edge (0.050, 0.050, 0.900, 0.900 of the video) and the caption band `top 0.8129, height 0.1296` of the height, which is 878 to 1018 of 1080 (`caption_zone`). A verdict and a note were still there after a reload. The attempts list showed all attempts with "repeat of" and **Show**.

### GFX-012 — Trial batch and summary

**Status:** In Progress (built and checked on 2026-11-03 on a throwaway backend with a stand-in model server and headless Chrome; the owner's rebuild of the Docker stack and the first real trial are open)

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

- [x] Excerpt list, Run the trial, cost shown
- [x] Summary page, Copy as Markdown
- [x] Docs, standard checks (`ruff check` and `ruff format --check`, ESLint, `tsc -b`, the production build and `gen:api` pass; no change to `motion/`)
- [ ] A real trial on the owner's Docker stack after the rebuild (`docker compose up -d --build backend frontend`; there is no migration): about 40 to 100 paid calls, owner's click

**Completion notes.** Built on 2026-11-03. No migration, no new setting, no new job type, no new package, and no change to any engine or to the motion service. The "Planning decides" items:

- **How a set is grouped: a set number inside `trial_case_key`.** The column holds `"<set>:<case>"` (`3:T05`). The next set is one more than the highest number found, so a set can be found with `LIKE '3:%'` and the existing index serves it. `DATABASE_STRUCTURE.md` says so.
- **Where the excerpts live: in code** (`services/graphics_trial.EXCERPTS`, a tuple), not in a JSON file. The text is Appendix A as it stands: GFX-001 has not approved the list yet, and if it changes only that tuple changes.
- **The orientation of each excerpt** (Appendix A has a new column, the owner's decision): T03, T06, T07 and T09 run in portrait and the other six in landscape, so a line chart, a vertical flow, benchmark bars and a list are each tried in portrait. The form can also make all ten landscape or all ten portrait.
- **Which attempt counts: the newest render of an engine that is not a Render again** (the owner's decision), which is what the card shows and what is judged. Renders made by Render again feed only the repeat counts.

What was built:

- **`services/graphics_trial.py`.** `EXCERPTS`, `case_key` and `parse_case_key`, `trial_cost` (10 runs, 40 paid calls, at most 100, and 10 speeches with a voice), `start_trial`, `start_after_timing`, `list_sets` and `summarize` (`summarize_rows` is pure). `graphics_lab.create_run` has a new `trial_case_key` argument, and `graphics_lab.trial_runs` and `check_line_fits` are new.
- **Starting.** `start_trial(session, voice_id, orientation)` checks the voice and that every excerpt's estimated speech fits one graphic, before anything is made; refuses (409) while the newest set still has a run whose voice is being made or timed or whose brief is being written (a second click would pay for a second set); makes the ten runs; and, without a voice, presses **Make all** on each. A failure on one run is kept in that run's `last_error` and never stops the others. **With a voice** the speech is made at once for each run and the brief waits for its timing (GFX-004), so `jobs/time_lab_graphic_words.py` calls `graphics_trial.start_after_timing(run_id)` after it has saved the timing: for a run that has a trial key and no brief job it starts the brief and then the engines. Any other run is left alone, so the owner's click is still what starts the brief of an ordinary run. The click on **Run the trial** is the click G-13 asks for.
- **The summary** (`GET .../trials/{set}`), per engine over the set's runs: the runs, the videos, "no template fits" (the input has `template` null), failed, and not finished (working or not started); out of the videos, how many passed the frame, size and frame rate checks (`metrics.checks`), had no layout warning (`metrics.layout_problems == 0`) and had every number traced; the median render time (`metrics.render_s`); the median tokens (prompt plus completion tokens of the input job's calls, over every counted render that has a call); the Render again results (identical, differing, not compared, from `metrics.repeat` of every repeat in the set); and the verdict counts, with "not judged". **Every number traced** is `metrics.untraced_numbers == 0` for the generated component (as GFX-010 asked). The other engines refuse an untraced number before they draw (G-7), so each of their videos counts, and the page and the Markdown say so. A render counts as *failed* when it has `last_error`, a failed or cancelled job, or a component whose checks did not pass. Each run's outcome on each engine is returned too, with its verdict and attempt.
- **API** (`api/graphics_lab.py`): `GET /api/lab/graphics/trials` (the excerpts, the cost with and without a voice, and the sets), `POST /api/lab/graphics/trials` (`{voice_id, orientation: own | landscape | portrait}`; 201 `{set_no, run_ids}`, 409 while the newest set is being made, 422 for an unknown voice or a line that is too long) and `GET /api/lab/graphics/trials/{set_no}` (404 for an unknown set). `schema.d.ts` regenerated.
- **Frontend** (`components/graphicsLab/`): `GraphicsTrialPanel` (a "Trial batch" box on the Graphics tab: the excerpts folded, the voice and orientation, the cost line, **Run the trial** with a confirmation that names the paid calls and the speeches, and the list of sets), `GraphicsTrialSummary` (a set switcher, one table with a row for each measure and a column for each engine, a table of the runs with each engine's outcome, verdict and **Open run**, **Copy as Markdown**, and polling while any part of the set is still going), `graphicsTrialView.ts` (`measureRows`, `trialMarkdown`), and `useOpenGraphicsTrial` (`?trial=<set>`). A run opened from a summary goes over it (`?trial=3&run=12`), and closing the run returns to the summary. The trial's engine counts are in one table with the engines as columns rather than one table for each engine, so that two engines can be read side by side.

**Checked.** A throwaway backend (`DATA_DIR` in `/tmp`, the model URL pointed at a stand-in server that answered any line's brief as a concept with no numbers and the spec as "no template fits", and refused the scene and component calls; no paid call, and the real database and Docker stack were not touched) and headless Google Chrome on the built frontend:

- One trial made ten runs with the keys `1:T01` to `1:T10`, each with its own orientation, a brief, and a render of every engine that is built (10 briefs and 10 specs were asked; the scene and component calls were refused). A second click at once got 409 with the reason; an unknown voice got 422 and a bad orientation 422; an unknown set got 404. With every run done, `active` was false.
- **The counts, by hand.** Renders were added to the database by hand for three runs (a good block video with a Render again that was identical; a bad component video with a Render again that differed by 3 frames; a component video with no untraced numbers and a Render again that could not be compared). The summary counted, as worked out on paper: 1 video for the blocks (checks 1, layout 1, traced 1, median 6.0 s, 1 identical, 1 good) and 2 for the component (checks 1, layout 1, traced 1, median 15.0 s, 1 differing, 1 not compared, 1 bad, 1 not judged); the Render again attempts were not counted as videos, and the attempt shown for each run was the newest one that is not a repeat.
- **A trial with a voice** was checked on the hook only (a real voice needs the GPU server): `start_after_timing` on a run with a trial key and a stored timing started the brief and then the engines; on an ordinary run it did nothing; a second call did nothing.
- **A second trial** got set 10 (the highest number was 9, from a run made by hand), and the switcher moved between sets.
- **In the browser:** the panel showed the cost line "10 runs, 40 paid model calls (up to 100 when answers are retried)", the confirmation said the same and Cancel started nothing, the summary opened at `?trial=10`, **Copy as Markdown** put the heading and the two tables on the clipboard, **Open run** went to `?trial=10&run=13`, and **All runs** went back to the summary and then to the list.

**Still to do for this phase.** The owner has to rebuild (`docker compose up -d --build backend frontend`; there is no migration), then press **Run the trial** (with a voice or without), confirm the calls, and watch the summary fill in. The first real trial also answers GQ-5 (how well GLM-5.3 writes Remotion code) and GQ-8 (lines without numbers). Update the status when it is done.

**For the later phases.**

- GFX-013 copies the summary with **Copy as Markdown** into Appendix B, then judges each run: the verdict counts in the summary come from the verdicts set on the run pages.
- A trial run is an ordinary run with a trial key: it can be opened, asked again, judged and deleted like any other, and deleting it removes it from its set's counts.
- The summary reads the newest attempt that is not a Render again. Asking an engine again on a trial run therefore changes that engine's counts for the run.

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
| GQ-2 | **Apple silicon.** The motion image must run as `linux/arm64`, and the headless browser Remotion downloads must exist for it. **Closed in GFX-005:** the image builds and runs as `linux/arm64`, and Chrome Headless Shell for `linux-arm64` renders in it. | GFX-005 (done) |
| GQ-3 | **Repeatability of browser rendering.** The same machine should give identical frames. Another machine (a different CPU or browser build) may not. The trial checks the same machine only. GFX-005 checked it for the test card: two renders in the same container gave identical `framemd5`. | GFX-005 (test card), GFX-011 |
| GQ-4 | **Generated code is the riskiest engine.** The static checks can be bypassed by clever code. The real protection is the container (no internet, no files, no secrets, limits). A browser escape inside the container would still be contained, but this is not a guarantee. | GFX-005, GFX-010 |
| GQ-5 | **GLM-5.3's skill at Remotion code is unknown.** The trial measures it. A long component may need a large `max_tokens`, and each call costs more than the other engines' calls. | GFX-010, GFX-012 |
| GQ-6 | **Python drawing quality.** Without a vector library, edges and text may look rougher than in the browser. The library choice decides this. | GFX-008 |
| GQ-7 | **Estimated timing drifts** from a real voice by a few tenths of a second over a long line. With a voice, the beats follow the real words. | GFX-003, GFX-004 |
| GQ-8 | **Lines without numbers** (AI concepts) may get "no template fits". That is a result of the trial, not a defect, and it shows where blocks or generated code are needed. | GFX-006, GFX-012 |
| GQ-9 | **The number reader's known limits** (ordinals, "half", ranges, years said in two parts) can refuse a correct fact. A refusal names the fact, so the owner can reword the line. | GFX-003 |
| GQ-10 | **Cost.** A run is four paid calls plus at most one retry each (up to 3 attempts for the block scene), so a trial is 40 calls when every answer is usable the first time and at most 100 (10 runs times 2 + 2 + 3 + 3 attempts). GFX-012 shows both counts, and asks for a confirmation, before it starts. | GFX-012 |

**Out of scope for the whole lab:** data you upload and live market data (both planned for the pipeline, not needed to compare engines), captions or callouts burned into the lab videos, music, and a live Remotion preview in the browser.

---

## Appendix A — Trial excerpts

The companies and numbers are made up. The owner approves or changes the list in GFX-001.

| Key | Domain | Orientation | Excerpt | What it tests |
|-----|--------|-------------|---------|---------------|
| T01 | Finance | Landscape | "Acme's revenue has exploded. It made 12 billion dollars in 2023, 19 billion in 2024, and 31 billion in 2025. That's more than double in two years." | Bars, a derived percent change, a beat per year |
| T02 | Finance | Landscape | "Northwind's stock closed at 84 dollars on Friday, down 6.5 percent in a single day, its worst drop since March." | A KPI with a negative change |
| T03 | Finance | Portrait | "Over the last five quarters, Globex's operating margin went from 18 percent to 21, then 24, dipped to 22, and reached 27 percent this quarter." | A line through five points, an axis that does not start at zero |
| T04 | Finance | Landscape | "Initech trades at 45 times earnings, while its closest rival, Umbrella, trades at just 19 times. Investors pay more than twice as much for every dollar Initech earns." | A comparison of multiples, a derived ratio |
| T05 | AI | Landscape | "A large language model works in three steps. It splits your text into tokens, turns each token into a vector, and then predicts the next token, one at a time." | A three-step flow |
| T06 | AI | Portrait | "Retrieval augmented generation adds one step before the answer: your question searches your documents, the best matches are added to the prompt, and only then does the model write its reply." | A four-step flow with longer labels |
| T07 | AI | Portrait | "On the coding benchmark, the new model scored 71 percent, up from 48 percent for the previous version, and ahead of the 64 percent of its closest competitor." | Benchmark bars with an emphasis |
| T08 | AI | Landscape | "Attention lets every word look at every other word in the sentence, so 'it' can learn that it means 'the animal' and not 'the street'." | A concept with no numbers: no template should fit |
| T09 | General | Portrait | "There are three reasons this matters: it is cheaper, it is faster, and it works offline." | A list that builds item by item |
| T10 | General | Landscape | "Here is the part nobody talks about." | A very short line (the 3 s minimum), a statement card |

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
| 2026-11-03 | GFX-005 | In Progress | Motion service and render job built: the `motion` container (Remotion 4.0.540, Fastify, isolated, hardened), the provider, job `render_lab_graphic` (checks, voice, metrics), two settings, the test card button. Checked on a throwaway database and in the arm64 image; the owner's rebuild and click are open. Notes for the later phases are in the completion notes. |
| 2026-11-03 | GFX-006 | In Progress | Template catalogue (five templates, the checks, the text-fit rule with both fonts), the spec writer, job `write_lab_graphic_template_spec`, one call and two render rows for the two template engines, `renderer_built` on the registry, spec and "no template fits" on the cards. Checked against a stand-in model server; the live check on excerpts 1, 5, 8 and 9 is open. Notes for the later phases are in the completion notes. |
| 2026-11-03 | GFX-007 | In Progress | Remotion templates built: the `Templates` composition draws the five templates and their variants, the four backgrounds, the beat motion and the number count-up from the spec of GFX-006; `remotion_templates` has `renderer_built`; the exact layout is written into §4.5.1 for GFX-008. Checked on the host motion service (excerpts 1, 2, 3, 5, 7, 9 and 10, both orientations) and through a throwaway backend with a stand-in model server; the owner's rebuild and the live check are open. Notes for the later phases are in the completion notes. |
| 2026-11-03 | GFX-008 | In Progress | Python templates built: `services/graphics_python/` draws the five templates, their variants, the four backgrounds and the beat motion with Pillow at 3x supersampling, in a child process that pipes raw frames into FFmpeg with Remotion's encoding and colour arguments; `python_templates` has `renderer_built`. Checked on 88 videos on the host (frames, beats, caption area, identical frames on render again), and through a throwaway backend with a stand-in model server (Python row 2.3 s against Remotion's 6.7 s; the API answered within 18 ms during the render). The owner's rebuild and the live check are open. Differences from Remotion are in the completion notes. |
| 2026-11-03 | GFX-009 | In Progress | Building blocks built: ten blocks and their effects on a 12 x 12 grid (`motion/src/blocks/`), `POST /layout` that measures texts in the browser, the scene checks, the scene writer, job `write_lab_graphic_block_scene` with one layout ask (up to 3 attempts), `remotion_blocks` marked built, the block card. Checked on the host motion service and a throwaway backend with a stand-in model; the owner's rebuild and the live check with the real model are open. |
| 2026-11-03 | GFX-011 | In Progress | Comparison view built: one playback bar plays, pauses, steps and seeks all four videos in sync (a leader video, the others follow), safe-area and caption-area overlays, cards with metrics, the model call's cost, warnings, input, verdict and the list of attempts, **Ask again** on one engine (a new attempt; both template cards for the template engines) and **Render again** (same input, no model call, frames compared with `framemd5` as a step of `render_lab_graphic`, `metrics.repeat`). Checked on the host, a throwaway backend with a stand-in model and headless Chrome; the owner's rebuild and a look at a live run are open. |
| 2026-11-03 | GFX-012 | In Progress | Trial batch built: ten excerpts (each with its own orientation) through every engine as a numbered set (`trial_case_key` `<set>:<case>`), the paid calls shown and confirmed first, a voice trial starting each brief when its timing is stored, and a summary page with the counts and medians of §4.9 per engine, a table of the runs, and **Copy as Markdown**. Checked on a throwaway backend with a stand-in model and headless Chrome; the owner's rebuild and the first real trial are open. |
