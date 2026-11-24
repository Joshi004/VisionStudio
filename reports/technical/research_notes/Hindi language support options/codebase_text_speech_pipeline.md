# Codebase audit: English assumptions in Visio Studio's text, language-model and speech pipeline

Scope: a read-only audit of `backend/app` (services, jobs, providers, db, core), plus the design docs, done on 18 Nov 2026. Every citation is `path:line`, relative to the repository root. The links resolve from this notes folder. "Verified" means I ran a small Python check outside the repository (Python 3, `unicodedata`/`re`/`fontTools`). "Inference" marks a conclusion I drew rather than read in the code. Statements about the external models (Parakeet, Breeze TTS 2, MiniMax H3, GLM, Qwen) that are not written in the repository are flagged as coming from outside the code.

Size scale used throughout:
- **S**: a constant, a regex, or a prompt line, with no schema change. About a day or less.
- **M**: several files, or a new setting/column with a migration and UI. A few days.
- **L**: a new model or provider, a new pipeline stage, or a cross-cutting redesign. A week or more.

---

## 1. How does story text flow from input to captions, and which artifacts must hold verbatim source-language text?

### Takeaway
The pipeline already keeps every spoken string as a byte-exact copy of the author's text: scene slices are cut by code, event speech is checked against the slice, speech units must hold exactly the event's words, and the H3 prompt must hold each unit's words exactly. So any architecture that speaks Hindi needs that chain to be in Hindi from the scene slice onward. Descriptions, definitions, shot specs and prompts are free-form English.

### Cited Findings
**Input and length estimate**
- The story is stored as `project.script_text` ([models.py:61](../../backend/app/db/models.py#L61)). Its length estimate is whitespace word count ÷ a words-per-minute setting ([story_length.py:45-49](../../backend/app/services/story_length.py#L45), [story_length.py:52-66](../../backend/app/services/story_length.py#L52)). The browser repeats the rule in `frontend/src/components/story/storyLength.ts` ([story_length.py:7-8](../../backend/app/services/story_length.py#L7)).

**Story Bible (free-form English)**
- The model gets the raw story as the user message ([story_bible_writer.py:117-133](../../backend/app/services/story_bible_writer.py#L117)) and is told "Write everything in English" ([story_bible_writer.py:61](../../backend/app/services/story_bible_writer.py#L61)). Code writes `"language": "en"` ([story_bible_writer.py:30](../../backend/app/services/story_bible_writer.py#L30), [story_bible_writer.py:216](../../backend/app/services/story_bible_writer.py#L216)); the docstring says "the app works in English only, so it is always `en`" ([story_bible_writer.py:10-12](../../backend/app/services/story_bible_writer.py#L10)).

**Scenes (verbatim slices)**
- The model returns `starts_with`, "copied from the story exactly as they are written there, in the story's own language" ([scene_discovery_writer.py:122-127](../../backend/app/services/scene_discovery_writer.py#L122)). Code cuts `text = story_text[start:end]` ([scene_discovery_writer.py:340](../../backend/app/services/scene_discovery_writer.py#L340)) and guards that the slices joined equal the story ([scene_discovery_writer.py:347-349](../../backend/app/services/scene_discovery_writer.py#L347); docstring [scene_discovery_writer.py:13-24](../../backend/app/services/scene_discovery_writer.py#L13)).
- The scene `title` and `description` must be "in English" ([scene_discovery_writer.py:119-121](../../backend/app/services/scene_discovery_writer.py#L119)).

**Events (verbatim speech, English descriptions)**
- `narration` and `dialogue` `text` are "copied from the scene text exactly as written there, without changing, shortening, rephrasing or translating them" ([event_extraction_writer.py:131-135](../../backend/app/services/event_extraction_writer.py#L131), [event_extraction_writer.py:147-154](../../backend/app/services/event_extraction_writer.py#L147)). The rules say: 'Write "description" and "emotion" in English … "text" stays in the story's own language' ([event_extraction_writer.py:282-283](../../backend/app/services/event_extraction_writer.py#L282)).
- `action` and `sound_event` descriptions are "one plain sentence in English" ([event_extraction_writer.py:156-177](../../backend/app/services/event_extraction_writer.py#L156)).
- `check_coverage` requires each speech event's words to be found, in order, in the scene slice ([event_extraction_writer.py:505-559](../../backend/app/services/event_extraction_writer.py#L505)). Speech text over 2,000 characters is refused, never cut ([event_extraction_writer.py:87](../../backend/app/services/event_extraction_writer.py#L87), [event_extraction_writer.py:383-391](../../backend/app/services/event_extraction_writer.py#L383)).

**Speech units (verbatim pieces of events)**
- Each narration/dialogue event becomes one or more units cut at sentence ends, then clauses ([speech_unit_planner.py:123-141](../../backend/app/services/speech_unit_planner.py#L123)). `check_coverage` refuses units that do not hold the event text exactly, whitespace aside ([speech_unit_planner.py:217-240](../../backend/app/services/speech_unit_planner.py#L217)). A user's own cuts must keep the same words in order ([speech_unit_planner.py:180-186](../../backend/app/services/speech_unit_planner.py#L180)).

**Text-to-speech**
- The unit text is split into ≤1,000-character chunks ([speech_synthesis.py:835](../../backend/app/services/speech_synthesis.py#L835), [speech_chunks.py:34-48](../../backend/app/services/speech_chunks.py#L34)). The voice's `transcript` goes as the cloning `reference_text` ([speech_synthesis.py:840-845](../../backend/app/services/speech_synthesis.py#L840), [speech_synthesizer.py:65-67](../../backend/app/providers/speech_synthesizer.py#L65)). A unit with an emotion gets the English instruction `"Speak with this emotion: {emotion}."` ([speech_synthesis.py:222-227](../../backend/app/services/speech_synthesis.py#L222)).

**H3 prompt (verbatim words inside `<d>`)**
- The model must write `<d>[English] the words</d>`, where the words are exactly the audio's words "with nothing added, changed or translated" ([shot_prompt_writer.py:729-740](../../backend/app/services/shot_prompt_writer.py#L729), [shot_prompt_writer.py:810-815](../../backend/app/services/shot_prompt_writer.py#L810)). Code refuses a prompt unless `speaker.text in spoken` ([shot_prompt_writer.py:1287-1292](../../backend/app/services/shot_prompt_writer.py#L1287)).

**Dialogue check (story projects)**
- Parakeet transcribes the take's clip, and its words are compared with the lines; below `dialogue_match_threshold` the clip fails and is regenerated ([dialogue_check.py:1-30](../../backend/app/services/dialogue_check.py#L1)). The default threshold is 80%, and each retry is "a new remote server job of 10 to 20 minutes" ([settings.py:576-592](../../backend/app/core/settings.py#L576)).

**Word timings and captions (explainers only)**
- Word timings are made only for explainers; "A story never does" ([word_timings.py:276-281](../../backend/app/services/word_timings.py#L276)). The render has no caption track for a story ([story_render_plan.py:964](../../backend/app/services/story_render_plan.py#L964)).
- For an explainer, Parakeet's heard words are aligned to the script; below the threshold the times are estimated by character share ([word_timings.py:3-31](../../backend/app/services/word_timings.py#L3), [word_timings.py:226-263](../../backend/app/services/word_timings.py#L226)). Captions are built from script words ([caption_plan.py:1-30](../../backend/app/services/caption_plan.py#L1)).
- A continuous explainer's take with estimated timing "is blocked and has to be made again" ([take_timings.py:13-15](../../backend/app/services/take_timings.py#L13), [take_timings.py:156-162](../../backend/app/services/take_timings.py#L156)). A recorded explainer is `refused` when "too few of the script's words were heard" ([full_recordings.py:16](../../backend/app/services/full_recordings.py#L16)).

**Verbatim vs free-form**
- Verbatim source-language fields: `scene.text` and `scene.starts_with`; `event.text`; `speech_unit.text`; `SpeechUnitAudio.text` ([speech_synthesis.py:861](../../backend/app/services/speech_synthesis.py#L861)); the `<d>` words in H3 prompts; `Voice.transcript` ([models.py:1945-1967](../../backend/app/db/models.py#L1945)); and caption `raw` words ([caption_plan.py:92-94](../../backend/app/services/caption_plan.py#L92)).
- Free-form English fields: Story Bible fields; character/environment `name` and `description` ([discovery_writer.py:57](../../backend/app/services/discovery_writer.py#L57)); definitions; event `description` and `emotion`; scene `title` and `description`; shot plans, definitions and continuity notes; H3 and image prompt bodies; voice-design instructions.

### Inferences
- The guarantees "scenes join back to the story byte for byte" and "speech is copied, never rewritten" hold for whatever language the story arrives in. Under C (the hybrid), the verbatim chain needs no structural change.
- Under B (English pivot), the slices, events and units would be the English translation, not the author's Hindi. A Hindi version would then have to come from back-translation at the speech-unit stage, because TTS, the H3 `<d>` check and the dialogue check all read `speech_unit.text`. The author's original Hindi words would never be spoken verbatim unless a separate alignment from English units back to Hindi spans is built.
- Scene titles are displayed: explainer section titles are shown, and captions hide while one is up ([story_render_plan.py:52](../../backend/app/services/story_render_plan.py#L52)). Under C they count as "displayed text" and would need Hindi.

### Gaps
- I did not trace the frontend to list every place a scene title or character `name` is shown to viewers (as opposed to the owner).

---

## 2. Which LLM prompt writers carry explicit English instructions or English-only examples, and which validations would break on Devanagari?

### Takeaway
About 20 writers tell the model "Write everything in English". All of them write internal or visual fields, which the hybrid design wants in English anyway. Event extraction and scene discovery already tell the model to keep speech "in the story's own language". The validations that matter are the exact-match checks. Two of them normalise text and work on Devanagari (verified). The H3 `<d>` check uses a raw substring test, which is exposed to Unicode-normalisation differences (verified). Several English-word regex guards would be blind to Hindi prose.

### Cited Findings
**Explicit "English" instructions in the core story path**
- "Write everything in English":
  - [story_bible_writer.py:61](../../backend/app/services/story_bible_writer.py#L61)
  - [discovery_writer.py:57](../../backend/app/services/discovery_writer.py#L57) (characters and environments)
  - [scene_definition_writer.py:110](../../backend/app/services/scene_definition_writer.py#L110)
  - [character_definition_writer.py:150](../../backend/app/services/character_definition_writer.py#L150)
  - [environment_definition_writer.py:158](../../backend/app/services/environment_definition_writer.py#L158)
  - [scene_staging_writer.py:117](../../backend/app/services/scene_staging_writer.py#L117)
  - [shot_definition_writer.py:156](../../backend/app/services/shot_definition_writer.py#L156)
  - [shot_continuity_writer.py:113](../../backend/app/services/shot_continuity_writer.py#L113)
  - [shot_cut_repair_writer.py:88](../../backend/app/services/shot_cut_repair_writer.py#L88)
- "in English" for one field:
  - [scene_discovery_writer.py:119-120](../../backend/app/services/scene_discovery_writer.py#L119) (title, description)
  - [shot_planning_writer.py:121](../../backend/app/services/shot_planning_writer.py#L121)
  - [cut_planning_writer.py:183](../../backend/app/services/cut_planning_writer.py#L183), [cut_planning_writer.py:312](../../backend/app/services/cut_planning_writer.py#L312)
  - [event_extraction_writer.py:156-177](../../backend/app/services/event_extraction_writer.py#L156), [event_extraction_writer.py:282-283](../../backend/app/services/event_extraction_writer.py#L282)
- H3 prompt compile:
  - "Everything is English, except the words people speak." ([shot_prompt_writer.py:658](../../backend/app/services/shot_prompt_writer.py#L658))
  - "Plain, concrete, present-tense English prose" ([shot_prompt_writer.py:678](../../backend/app/services/shot_prompt_writer.py#L678)); "Camera: natural English" ([shot_prompt_writer.py:682](../../backend/app/services/shot_prompt_writer.py#L682), [shot_prompt_writer.py:807](../../backend/app/services/shot_prompt_writer.py#L807))
  - The template `<d>[English] the words</d>` and "[English] names the language of the words, in English" ([shot_prompt_writer.py:731-738](../../backend/app/services/shot_prompt_writer.py#L731), [shot_prompt_writer.py:812-814](../../backend/app/services/shot_prompt_writer.py#L812))
- Character Lab take prompts:
  - "350-500 English words" ([character_take_prompt_writer.py:88](../../backend/app/services/character_take_prompt_writer.py#L88)); English prose ([character_take_prompt_writer.py:299](../../backend/app/services/character_take_prompt_writer.py#L299), [character_take_prompt_writer.py:311](../../backend/app/services/character_take_prompt_writer.py#L311), [character_take_prompt_writer.py:328](../../backend/app/services/character_take_prompt_writer.py#L328), [character_take_prompt_writer.py:443](../../backend/app/services/character_take_prompt_writer.py#L443), [character_take_prompt_writer.py:463](../../backend/app/services/character_take_prompt_writer.py#L463), [character_take_prompt_writer.py:534](../../backend/app/services/character_take_prompt_writer.py#L534))
  - `<d>[Language] the words</d>` "where [Language] is the language of the words, named in English" ([character_take_prompt_writer.py:467-468](../../backend/app/services/character_take_prompt_writer.py#L467))
  - "Everything is English, except the words people speak." ([character_take_prompt_writer.py:479](../../backend/app/services/character_take_prompt_writer.py#L479))
- Voice design:
  - "Write one plain English description of the sound of the voice … the accent" ([voice_design_writer.py:73-74](../../backend/app/services/voice_design_writer.py#L73), narrator [voice_design_writer.py:91-93](../../backend/app/services/voice_design_writer.py#L91))
- YouTube draft: "Write in English." ([youtube_draft_writer.py:68-69](../../backend/app/services/youtube_draft_writer.py#L68)); hashtag regex `[A-Za-z0-9_]+` ([youtube_draft_writer.py:60](../../backend/app/services/youtube_draft_writer.py#L60))

**Writers that already follow the source language**
- Scene discovery `starts_with` is "in the story's own language" ([scene_discovery_writer.py:123](../../backend/app/services/scene_discovery_writer.py#L123)). Event `text` "stays in the story's own language" ([event_extraction_writer.py:282-283](../../backend/app/services/event_extraction_writer.py#L282)).
- Thumbnail headline: "in the language of the video" ([thumbnail_concept_writer.py:103](../../backend/app/services/thumbnail_concept_writer.py#L103)). Callout text: "in the language of the script" ([callout_plan_writer.py:199](../../backend/app/services/callout_plan_writer.py#L199)).

**English-only examples (harmless as examples)**
- "Arjun laughs.", "One heavy thump above the ceiling." ([event_extraction_writer.py:110-111](../../backend/app/services/event_extraction_writer.py#L110))
- Story Bible JSON example ([story_bible_writer.py:86-91](../../backend/app/services/story_bible_writer.py#L86)); "the landlord", "Young Arjun" ([discovery_writer.py:76-80](../../backend/app/services/discovery_writer.py#L76))
- "soft regional accent" ([character_definition_writer.py:117](../../backend/app/services/character_definition_writer.py#L117)); Path_ahead's example accent is "neutral Indian English" ([Path_ahead.md:622](../../Path_ahead.md#L622))

**Validations, and how they behave on Devanagari**
- **Scene discovery `normalise`** keeps only `isalnum()` characters ([scene_discovery_writer.py:177-182](../../backend/app/services/scene_discovery_writer.py#L177)). Verified: Devanagari vowel signs (category Mc), virama and nukta (Mn) are not `isalnum`, so `किताब` normalises to `कतब`. The same function runs on the story and on the quote, so matching still works. It is lossy, and `MIN_QUOTE_WORDS = 5` ([scene_discovery_writer.py:59](../../backend/app/services/scene_discovery_writer.py#L59)) limits false matches.
- **Event coverage** uses the same `normalise` ([event_extraction_writer.py:496-498](../../backend/app/services/event_extraction_writer.py#L496)), so it behaves the same way.
- **The H3 `<d>` check is a raw substring test**: `if speaker.text not in spoken` ([shot_prompt_writer.py:1288](../../backend/app/services/shot_prompt_writer.py#L1288)), with only whitespace collapsed ([shot_prompt_writer.py:1275](../../backend/app/services/shot_prompt_writer.py#L1275)). Verified: precomposed `क़` (U+0958) ≠ `क` + `़` (U+0915 U+093C) as raw strings, but they are equal after NFC/NFKC.
- **The `<d>` parser accepts any language tag**: `<d>\s*\[[^\]\n]+\]\s*(.*?)\s*</d>` ([shot_prompt_writer.py:116](../../backend/app/services/shot_prompt_writer.py#L116)). So `[Hindi]` parses; only the instruction text hard-codes `[English]`.
- **English-word guards on prompt prose**: the music-word regex ([shot_prompt_writer.py:122](../../backend/app/services/shot_prompt_writer.py#L122)), the talking/voice-ambience regexes and allowed phrases ([shot_prompt_writer.py:125-197](../../backend/app/services/shot_prompt_writer.py#L125)), and the take begin/end regexes ([character_take_prompt_writer.py:128-129](../../backend/app/services/character_take_prompt_writer.py#L128)).
- **The name-leak warning** tokenises names with `[^\W\d_]{3,}` ([shot_prompt_writer.py:1374](../../backend/app/services/shot_prompt_writer.py#L1374)). Verified: for `अर्जुन Arjun` it returns only `['Arjun']`, because Python's `\w` excludes Devanagari combining marks.
- **Prompt word counts** use `len(x.split())` ([shot_prompt_writer.py:1449-1455](../../backend/app/services/shot_prompt_writer.py#L1449), [character_take_prompt_writer.py:866](../../backend/app/services/character_take_prompt_writer.py#L866)). These are calibrated to English prose ("350 to 500 words", [shot_prompt_writer.py:726](../../backend/app/services/shot_prompt_writer.py#L726)).
- **ASCII-only ids**: `^[a-z][a-z0-9_]*$` ([discovery_writer.py:48](../../backend/app/services/discovery_writer.py#L48), [discovery_writer.py:295-307](../../backend/app/services/discovery_writer.py#L295)); the explainer `slug_of` uses `[^a-z0-9]+` ([explainer.py:47](../../backend/app/services/explainer.py#L47), [explainer.py:152-162](../../backend/app/services/explainer.py#L152)).
- **Character-count limits** (`len()`, code points) are applied to model text ([text_limits.py:56-68](../../backend/app/services/text_limits.py#L56)), and `cut_at_word` cuts at spaces ([text_limits.py:44-53](../../backend/app/services/text_limits.py#L44)). Both work on Hindi, which is space-delimited.
- Request bodies serialise with `ensure_ascii=False` ([discovery_writer.py:183](../../backend/app/services/discovery_writer.py#L183), [event_extraction_writer.py:337-341](../../backend/app/services/event_extraction_writer.py#L337)), so Devanagari is sent as-is.

### Inferences
- Under C, the English instructions are correct as they stand. The prompt changes are: name `[Hindi]` in the `<d>` template from a project language, ask for scene titles in the story language (or add a separate display title), and possibly tell the H3 writer that the words are Hindi. All S.
- Under A, every "Write everything in English" line would flip, and the English regex guards would stop catching anything in Hindi prose. Hindi image and H3 prompt bodies would be sent to models that the repository treats as English-prompted (the H3 guide's "English words" target, [character_take_prompt_writer.py:88](../../backend/app/services/character_take_prompt_writer.py#L88)). Inference: A would likely need a translate-to-English step before image and video prompts anyway, which turns it back into C for the visual half.
- The `<d>` raw substring check is the most likely Devanagari-specific retry cause. A model may write nukta letters precomposed while the story has them decomposed, or the reverse. Applying NFC to both sides is an S fix.
- The ASCII id rule works under every architecture as long as the model romanises ids. Under A a model writing in Hindi may try Devanagari ids, which would be refused and cost a retry (inference).

### Gaps
- I found no measurement in the repository of how GLM-5.3 or Qwen3.8 handle Devanagari copy-exactness (`starts_with`, event `text`, `<d>` words). The retry rate on Hindi is unknown.

---

## 3. Text helpers: which regexes, splits and word lists assume English?

### Takeaway
Three helpers have real English defects for Hindi. Sentence splitting ignores the danda `।`, so a Hindi paragraph is one "sentence" (verified). Speaking-pace estimates use one English-calibrated words-per-minute value. The dialogue-matching word lists (number words, UK/US spelling, homophones, interjections) are English-only. Most other helpers are whitespace- and code-point-based and language-neutral.

### Cited Findings
**`speech_chunks.py` (TTS chunking and speech-unit sentence/clause cuts)**
- Sentence end is `(?<=[.!?\u2026])\s+|\n+|(?<=[\u3002\uff01\uff1f])`: Latin, ellipsis and CJK stops only, no danda U+0964 or double danda U+0965 ([speech_chunks.py:20-21](../../backend/app/services/speech_chunks.py#L20)). Verified: `वह कमरे में आई। उसने दरवाज़ा बंद किया। फिर वह रोने लगी।` gives 1 sentence; the English equivalent gives 3.
- The clause regex covers Latin and CJK commas, semicolons and colons ([speech_chunks.py:22-23](../../backend/app/services/speech_chunks.py#L22)). Hindi normally uses the Latin comma, so this works (inference).
- Cost counts CJK as double and everything else as 1 per code point ([speech_chunks.py:25-31](../../backend/app/services/speech_chunks.py#L25)). The 1,000-character budget was calibrated as "1000 English characters measured about 92 seconds" ([speech_chunks.py:3-6](../../backend/app/services/speech_chunks.py#L3)).
- `sentences()` and `clauses()` feed the speech-unit planner ([speech_unit_planner.py:130](../../backend/app/services/speech_unit_planner.py#L130), [speech_unit_planner.py:141](../../backend/app/services/speech_unit_planner.py#L141)).

**`speech_unit_planner.py`**
- Estimated seconds = `len(text.split())` × 60 ÷ words-per-minute × factor ([speech_unit_planner.py:75-76](../../backend/app/services/speech_unit_planner.py#L75)).
- The delivery factor matches English emotion stems ("whisper", "sad", "excit", …) on `[a-z]+` tokens after `.lower()` ([speech_unit_planner.py:34-41](../../backend/app/services/speech_unit_planner.py#L34), [speech_unit_planner.py:59-72](../../backend/app/services/speech_unit_planner.py#L59)).
- Dialogue is cut "only at sentence ends" ([speech_unit_planner.py:134-141](../../backend/app/services/speech_unit_planner.py#L134)). With no danda support, a long Hindi line stays whole with a warning ([speech_unit_planner.py:203-212](../../backend/app/services/speech_unit_planner.py#L203)).

**`story_length.py`**
- Words are counted with `text.split()` ([story_length.py:45-49](../../backend/app/services/story_length.py#L45)), at the `story_words_per_minute` pace (default 150, "a common pace for narration", [settings.py:761-775](../../backend/app/core/settings.py#L761)).

**`number_words.py`**
- It reads digits and **English** number words only ([number_words.py:1-17](../../backend/app/services/number_words.py#L1), tables [number_words.py:23-69](../../backend/app/services/number_words.py#L23)). It tokenises with `[a-z]+` after `.lower()` ([number_words.py:81](../../backend/app/services/number_words.py#L81), [number_words.py:104](../../backend/app/services/number_words.py#L104)).
- Verified: Python's `\d` matches Devanagari digits and `Decimal('३५') == 35`, so `३५` parses. Hindi number words (पंद्रह, लाख in Devanagari) do not.
- Callers treat a missing number as a warning ([number_words.py:14-16](../../backend/app/services/number_words.py#L14)).

**`dialogue_matching.py`** (docstring: "English only (S-12)", [dialogue_matching.py:20](../../backend/app/services/dialogue_matching.py#L20))
- English interjections ([dialogue_matching.py:38-65](../../backend/app/services/dialogue_matching.py#L38)), fillers ([dialogue_matching.py:70-72](../../backend/app/services/dialogue_matching.py#L70)), weak forms ([dialogue_matching.py:74-84](../../backend/app/services/dialogue_matching.py#L74)), UK→US spellings ([dialogue_matching.py:87-138](../../backend/app/services/dialogue_matching.py#L87)), homophones ([dialogue_matching.py:142-186](../../backend/app/services/dialogue_matching.py#L142)).
- `%` becomes `" percent "` ([dialogue_matching.py:194-198](../../backend/app/services/dialogue_matching.py#L194)); number folding uses `number_words` ([dialogue_matching.py:201-226](../../backend/app/services/dialogue_matching.py#L201)).

**`dialogue_check.py`** (Unicode-aware)
- `normalize_words` applies NFKC and casefold, keeps letters, digits *and combining marks* (`category startswith "M"`), and turns everything else into a space ([dialogue_check.py:172-185](../../backend/app/services/dialogue_check.py#L172)). Devanagari words survive whole, and the danda (category Po, verified) becomes a space.
- The forgiving steps are English-specific ([dialogue_check.py:83](../../backend/app/services/dialogue_check.py#L83), [dialogue_check.py:483-496](../../backend/app/services/dialogue_check.py#L483)).

**`word_timings.py`, `take_timings.py`, `recording_boundaries.py`, `recording_patches.py`, `full_recordings.py`**
- `align` splits the script on whitespace and tokenises with `normalize_words` ([word_timings.py:230-238](../../backend/app/services/word_timings.py#L230)); the estimated fallback shares time by character count ([word_timings.py:119-122](../../backend/app/services/word_timings.py#L119)).
- Unit and scene spans take the next `len(text.split())` words ([take_timings.py:89-121](../../backend/app/services/take_timings.py#L89), [recording_boundaries.py:84-109](../../backend/app/services/recording_boundaries.py#L84)).
- A boundary is tight when a neighbouring word "was not actually heard" ([recording_boundaries.py:9-12](../../backend/app/services/recording_boundaries.py#L9), [recording_boundaries.py:112-114](../../backend/app/services/recording_boundaries.py#L112)). A patch must have its first and last words heard ([recording_patches.py:13-15](../../backend/app/services/recording_patches.py#L13)).
- None of these hold an English rule. All of them depend on the recogniser hearing the script's words.

**Language-neutral helpers**
- `h3_lengths.py` works only on frame counts and measured durations ([h3_lengths.py:1-27](../../backend/app/services/h3_lengths.py#L1)).
- `script_ranges.py` works on code-point positions and whitespace ([script_ranges.py:4-5](../../backend/app/services/script_ranges.py#L4), [script_ranges.py:11-25](../../backend/app/services/script_ranges.py#L11)).

**`voice_design_writer.py`**
- Every character sample reads a fixed English sentence: `CHARACTER_LINE = "I never thought we would end up here, but the night is quiet now, and I am ready to tell you everything."` ([voice_design_writer.py:53-58](../../backend/app/services/voice_design_writer.py#L53)). It is queued as the sample line ([story_voices.py:10-12](../../backend/app/services/story_voices.py#L10), [story_voices.py:430](../../backend/app/services/story_voices.py#L430)).
- The narrator sample reads `opening_line(story)` ([story_voices.py:693](../../backend/app/services/story_voices.py#L693)), which splits on `(?<=[.!?])\s+`, so there is no danda support ([voice_design_writer.py:63](../../backend/app/services/voice_design_writer.py#L63), [voice_design_writer.py:139-158](../../backend/app/services/voice_design_writer.py#L139)).
- The saved voice then clones from that sample, with its transcript as `reference_text` ([speech_synthesis.py:840-845](../../backend/app/services/speech_synthesis.py#L840)).

**`character_definition_writer.py` (`voice_identity`)**
- `voice_identity` has `age_character`, `pitch`, `texture`, `accent` (≤80 characters) and `default_energy`, but no language field ([character_definition_writer.py:56-61](../../backend/app/services/character_definition_writer.py#L56)).
- The voice description is built from English labels "Age: … Accent: …" ([character_definition_writer.py:465-470](../../backend/app/services/character_definition_writer.py#L465)).

**`story_bible_writer.py`**
- A `language` field exists in the content, but code always writes `"en"` and the model is not asked ([story_bible_writer.py:10-12](../../backend/app/services/story_bible_writer.py#L10), [story_bible_writer.py:216](../../backend/app/services/story_bible_writer.py#L216); [story_bible.py:173](../../backend/app/services/story_bible.py#L173); [DATABASE_STRUCTURE.md:1302](../../DATABASE_STRUCTURE.md#L1302)). A search for anything reading `bible["language"]` found no reader.

**`discovery_writer.py`**
- Character `name` is "what the story calls it", under a blanket "Write everything in English" ([discovery_writer.py:57](../../backend/app/services/discovery_writer.py#L57), [discovery_writer.py:61-62](../../backend/app/services/discovery_writer.py#L61)).

**Captions (explainer)**
- Font "Montserrat ExtraBold" ([caption_plan.py:45-46](../../backend/app/services/caption_plan.py#L45), [font_metrics.py:23-24](../../backend/app/services/font_metrics.py#L23)). Verified with fontTools: `Montserrat-ExtraBold.ttf` and `Inter-Medium.ttf` in `backend/app/assets/fonts/` and `motion/public/fonts/` have **0 glyphs** in U+0900–U+097F and no danda.
- The caption break regex `[.,!?;:…—–]…$` has no danda ([caption_plan.py:62](../../backend/app/services/caption_plan.py#L62)); the SRT one is the same ([caption_srt.py:39](../../backend/app/services/caption_srt.py#L39)).
- `caption_text` strips Latin punctuation but would keep `।` ([caption_plan.py:173-188](../../backend/app/services/caption_plan.py#L173)). `.upper()` does nothing on Devanagari (verified).
- Group width uses code-point `len()` against `max_chars` 14/28 ([caption_plan.py:149](../../backend/app/services/caption_plan.py#L149), [caption_plan.py:163](../../backend/app/services/caption_plan.py#L163), [caption_plan.py:240](../../backend/app/services/caption_plan.py#L240)).
- `font_metrics.measure` measures callout widths with Montserrat through Pillow ([font_metrics.py:42-45](../../backend/app/services/font_metrics.py#L42)).
- The font-name validator only allows `[A-Za-z0-9 ]` ([caption_plan.py:61](../../backend/app/services/caption_plan.py#L61)). A Devanagari font with an ASCII family name (for example "Noto Sans Devanagari") passes (inference).

**Other explainer bits**
- Evidence text glue mentions English hyphen forms ([evidence_text.py:17](../../backend/app/services/evidence_text.py#L17)).
- The graphics briefs copy `said_as` "exactly as written, with the number" ([graphics_brief_writer.py:138](../../backend/app/services/graphics_brief_writer.py#L138), [shot_graphic_brief_writer.py:193](../../backend/app/services/shot_graphic_brief_writer.py#L193)), checked through `number_words`.

### Inferences
- Adding `\u0964\u0965` to the sentence-end regexes is S, but it touches four places: `speech_chunks` (line 21), `voice_design_writer` (line 63), `caption_plan` (line 62) and `caption_srt` (line 39).
- Without that fix, the speech-unit planner cannot split long Hindi narration at sentences. It falls to commas, and then keeps over-long units whole with a warning. This produces longer speech units than shots allow; the timeline checks and re-plans should catch it, but at extra paid calls (inference).
- A Hindi speaking rate in whitespace words is unmeasured. Hindi writes many postpositions and auxiliaries (का, में, है) as separate words, so its words-per-minute may differ from English's 150 (inference from general linguistic knowledge, not from the repository). One global value is used for both languages.
- Hindi dialogue-check tolerance has its own needs, which are not English's: nukta/no-nukta spellings (ज़/ज), chandrabindu vs anusvara, Devanagari vs Latin digits, Urdu-origin spelling variants. Inference: a Hindi "fair matching" list would be M, and only if the recogniser can transcribe Hindi at all.
- Every character voice is designed from an English reading, so a Hindi project's speech would be cross-lingual cloning from an English reference. Whether Breeze TTS 2 does that well is unknown (see Section 4). A per-language `CHARACTER_LINE` is S. Keeping one voice per language per library character is M (Section 5).

### Gaps
- No measured Hindi words-per-minute, and no Hindi characters-per-second figure for Breeze TTS, exist in the repository.

---

## 4. Providers: what do llm.py, qwen38.py, speech_synthesizer.py, transcriber.py and video_generator.py assume?

### Takeaway
None of the speech, transcription or video adapters sends a language parameter. Whether Hindi works is decided by the GPU-server models, which the repository never documents. The biggest risk is the recogniser. If Parakeet does not transcribe Hindi, the story dialogue check fails every Hindi take and auto-regenerates it (10 to 20 GPU minutes each), and explainer timings, continuous takes and recorded explainers stop working. The language-model byte and character budgets are low risk.

### Cited Findings
**`transcriber.py`**
- `POST /v1/parakeet/transcribe` with `{"audio_asset_id": ...}`; "There is no language field (Parakeet detects it)" ([transcriber.py:8-9](../../backend/app/providers/transcriber.py#L8); body [transcriber.py:61-70](../../backend/app/providers/transcriber.py#L61)).
- Design decision E-20: "Scripts are in English only. Parakeet's word timings are trusted for English." ([Explainer_implementation_phases.md:131](../../Explainer_implementation_phases.md#L131)). Explainer scope excludes "Any language other than English" ([Explainer_implementation_phases.md:204](../../Explainer_implementation_phases.md#L204)).

**`speech_synthesizer.py`**
- Breeze TTS 2 body: `text`, optional `instruction`, `reference_audio_asset_id` + `reference_text`, `seed`, `cfg_scale`, `partition`. No language field ([speech_synthesizer.py:45-70](../../backend/app/providers/speech_synthesizer.py#L45)).
- `TEXT_MAX_CHARS = 1000`, `INSTRUCTION_MAX_CHARS = 500`, `REFERENCE_TEXT_MAX_CHARS = 1000` ([speech_synthesizer.py:29-31](../../backend/app/providers/speech_synthesizer.py#L29)).
- The chunker's docstring cites the server guide only for Chinese density ("about half as many characters per request") ([speech_chunks.py:3-6](../../backend/app/services/speech_chunks.py#L3)).
- Licence: "research and non-commercial use only" ([speech_synthesizer.py:18](../../backend/app/providers/speech_synthesizer.py#L18)).

**`video_generator.py`**
- No language parameter. A search for "language|english" found only "language model" mentions ([video_generator.py:452-454](../../backend/app/providers/video_generator.py#L452)).
- The spoken language reaches H3 only through the prompt's `<d>[Language] …</d>` and the attached TTS audio (Section 2). Lip sync is an option on the audio-to-video endpoints ([video_generator.py:39-43](../../backend/app/providers/video_generator.py#L39)).

**`llm.py`**
- `ANSWER_MAX_BYTES = 24 MiB`, with the comment "every piece is wrapped in about 250 bytes of JSON for roughly one token (measured on Bitdeer). The largest request asks for 32,000 tokens, which is about 8 MB" ([llm.py:34-37](../../backend/app/providers/llm.py#L34)).
- Verified: `किताब` is 5 code points and 15 UTF-8 bytes (3 bytes per character).

**`qwen38.py`**
- `MAX_TOKENS_CAP = 49152` (including reasoning) ([qwen38.py:36-37](../../backend/app/providers/qwen38.py#L36)). `MESSAGES_MAX_CHARS = 45000`, counted in characters with `len(content)` ([qwen38.py:41-42](../../backend/app/providers/qwen38.py#L41), [qwen38.py:50-60](../../backend/app/providers/qwen38.py#L50)). Over that limit the call is refused with "Use Bitdeer for this one, or shorten the script" ([qwen38.py:147-152](../../backend/app/providers/qwen38.py#L147)).

**Writer token budgets that grow with Hindi speech**
- Event extraction's `MAX_TOKENS = 48000`, because "the answer repeats the scene's speech" ([event_extraction_writer.py:56-61](../../backend/app/services/event_extraction_writer.py#L56)).
- Story Bible and discovery use 12,000 ([story_bible_writer.py:24-28](../../backend/app/services/story_bible_writer.py#L24), [discovery_writer.py:36-39](../../backend/app/services/discovery_writer.py#L36)).

### Inferences
- The 250-bytes-per-token figure is SSE framing overhead per streamed piece, not text size. A Devanagari token adds at most a few bytes (3 bytes per character raw, or 6 if the server escapes as `\uXXXX`), so the 24 MiB cap is not at risk. S, or no change.
- The Qwen3.8 45,000-character cap counts code points. In a tiny verified sample, Hindi averaged 3.7 code points per word and English 3.8, so the character cap is roughly language-neutral.
- Token cost is different. From general knowledge outside the repository, and unmeasured here: GLM- and Qwen-family tokenizers usually spend more tokens per Hindi word than per English word. Event extraction repeats every spoken line, so its 48,000 budget and Qwen's 49,152 cap get tighter under A and C, and B doubles the calls with translation passes.
- **Parakeet** (outside the code, from training knowledge; verify on the server): NVIDIA's public Parakeet TDT checkpoints are English (v2) or 25 European languages (v3), and to my knowledge do not include Hindi. If the server runs one of those, then for any architecture that outputs Hindi audio:
  - The story dialogue check fails every take and triggers automatic retries up to `shot_take_max_retries` (default 2, [settings.py:560-575](../../backend/app/core/settings.py#L560)) at 10 to 20 GPU minutes each. A threshold of 0 "accepts any speech" ([settings.py:576-592](../../backend/app/core/settings.py#L576)), which is the only switch.
  - Explainer word timings fall to "estimated".
  - Continuous-explainer takes are blocked ([take_timings.py:156-162](../../backend/app/services/take_timings.py#L156)).
  - Recorded explainers are refused ([full_recordings.py:16](../../backend/app/services/full_recordings.py#L16)).
  - Fixing it means a Hindi-capable recogniser on the GPU server plus a `language` field in `transcriber.build_body`: L for the server, S for the adapter.
- **Breeze TTS 2** (outside the code): the name suggests MediaTek Research's Breeze family, which targets Traditional Chinese and English. Hindi support is unconfirmed. If it does not speak Hindi, every architecture that outputs Hindi needs a new TTS backend (L). Even if it does, whether an English instruction ("Speak with this emotion: …") and an English reference recording steer Hindi speech well is unknown.
- **MiniMax H3**: whether H3's lip sync and `<d>[Hindi]` handling work for Hindi is not documented in the repository.

### Gaps
- No repository document (including `UPSTREAM_API_0.13_INTEGRATION.md`, lines 56-57) states the languages that Parakeet, Breeze TTS 2 or H3 support on the owner's GPU server. This needs the GPU-server guide or a test run.
- No measured Hindi token counts exist for GLM-5.3 or Qwen3.8.

---

## 5. Data model and settings: is there any language field, and what would a per-project language touch?

### Takeaway
No table has a language column. The only language value is the constant `"en"` inside the Story Bible JSON, and nothing reads it. Pace, dialogue-match and timing thresholds are global settings. Voices belong to library characters shared across projects, with no language. A per-project language setting is M: one column and its plumbing. A per-language voice is a further M.

### Cited Findings
**`Project` model**
- `Project` ([models.py:32-129](../../backend/app/db/models.py#L32)) has `speech_mode`, `kind`, `voice_track`, `caption_mode`, `take_source` and others. Each is set at creation, with CHECK constraints ([models.py:40-50](../../backend/app/db/models.py#L40)). There is no `language`.
- `speech_mode`, `kind` and `voice_track` are "chosen when the project is created and never changed" ([models.py:62-67](../../backend/app/db/models.py#L62), [models.py:91-94](../../backend/app/db/models.py#L91)). This is the existing pattern a `language` column would follow (inference).

**Story Bible**
- `StoryBible.content` holds "title, language, genre, …" ([models.py:265](../../backend/app/db/models.py#L265)); the value is always `en` (Section 3).

**Voices**
- `Voice` is "a clean recording and its exact transcript, which Breeze TTS clones" ([models.py:1945-1967](../../backend/app/db/models.py#L1945)); there is no language.
- Story voices are saved onto the library character's next version, and the project's pin moves to it ([story_voices.py:13-16](../../backend/app/services/story_voices.py#L13)). An explainer presenter must have a saved voice on its newest version ([explainer.py:77-80](../../backend/app/services/explainer.py#L77)).

**Global settings (key/value table `Setting`, [models.py:1782](../../backend/app/db/models.py#L1782))**
- `story_words_per_minute` (default 150) ([settings.py:164](../../backend/app/core/settings.py#L164), [settings.py:761-775](../../backend/app/core/settings.py#L761))
- `speech_words_per_minute` (default 150; changing it marks units out of date) ([settings.py:170](../../backend/app/core/settings.py#L170), [settings.py:610-624](../../backend/app/core/settings.py#L610))
- `dialogue_match_threshold` (default 80) ([settings.py:193](../../backend/app/core/settings.py#L193), [settings.py:576-592](../../backend/app/core/settings.py#L576))
- `word_timing_match_threshold` (default 70) ([settings.py:197](../../backend/app/core/settings.py#L197), [settings.py:653-670](../../backend/app/core/settings.py#L653))
- `graphics_words_per_minute` ([settings.py:221](../../backend/app/core/settings.py#L221))
- The speech-unit rules record the pace they were planned with ([speech_units.py:57](../../backend/app/services/speech_units.py#L57), [speech_units.py:138-150](../../backend/app/services/speech_units.py#L138)).

**YouTube output**
- `LANGUAGE = "en"` sent as `default_language` and `default_audio_language` ([youtube_publish.py:45](../../backend/app/services/youtube_publish.py#L45), [youtube_publish.py:321-322](../../backend/app/services/youtube_publish.py#L321)).
- Captions are uploaded as language `en`, named "English" ([youtube_api.py:40-41](../../backend/app/services/youtube_api.py#L40), [youtube_api.py:60](../../backend/app/services/youtube_api.py#L60), [youtube_api.py:237-245](../../backend/app/services/youtube_api.py#L237)).

### Inferences
A per-project `language` (for example `en` or `hi`, set at creation like `speech_mode`) would touch:
1. A migration, the model, the create-project API and the form (M).
2. `story_bible_writer` writing the project's language instead of `"en"` (S).
3. Passing the language into the writers that template it: the H3 `<d>` tag, take prompts, scene titles (S each).
4. Speech-chunk and caption punctuation by language (S).
5. Per-language words-per-minute: either new keys like `speech_words_per_minute_hi`, or a per-project override (S-M).
6. Choosing a caption font by script, and bundling a Devanagari font (M).
7. The YouTube language codes (S).
8. The transcriber `language` field, once the server supports one (S adapter).
9. Voice selection by language (M): either a `language` on `Voice` and per-language voice slots on library character versions, or one voice per character accepted for both languages.

Under B, the same column would also drive a new translate-in and translate-out stage (Section 6).

### Gaps
- I did not inspect the frontend create-project form or the API schema for the size of the UI change.

---

## 6. Does anything in the story pipeline orchestration mention language?

### Takeaway
No. `jobs/story_pipeline.py`, `services/story_pipeline.py` and `services/story_pipeline_targets.py` mention "language" only as "language model". The jobs I checked (the extraction, discovery, speech, timing and dialogue-check jobs) are language-neutral; the English assumptions all sit in services and providers. Architecture B is the only one that needs new pipeline steps.

### Cited Findings
- `services/story_pipeline.py` mentions "paid language model" only ([story_pipeline.py:13](../../backend/app/services/story_pipeline.py#L13)). `story_pipeline_targets.py` mentions "the language model" only ([story_pipeline_targets.py:2353](../../backend/app/services/story_pipeline_targets.py#L2353), [story_pipeline_targets.py:2408](../../backend/app/services/story_pipeline_targets.py#L2408)).
- A search of `check_take_dialogue`, `time_speech_words`, `time_voice_recording`, `split_voice_recording`, `splice_voice_recording`, `synthesize_speech*`, `design_voice`, `lab_voice`, `extract_events`, `discover_scenes`, `discovery_job`, `write_story_bible`, `llm_call` and `story_pipeline` in `backend/app/jobs` found no English or language logic. The only `.lower()` calls are on error messages and file suffixes ([synthesize_speech.py:227](../../backend/app/jobs/synthesize_speech.py#L227), [synthesize_speech.py:254](../../backend/app/jobs/synthesize_speech.py#L254)).
- Event runs record `scene_text_sha256` over UTF-8 ([event_extraction_writer.py:309-311](../../backend/app/services/event_extraction_writer.py#L309)), so staleness follows the exact scene text.
- English-only design decisions: [Path_ahead.md:326](../../Path_ahead.md#L326) ("The system works in English only, so every story, narration line and dialogue line is in English."), S-12 ([Scene_pipeline_implementation_phases.md:100](../../Scene_pipeline_implementation_phases.md#L100)), E-20 ([Explainer_implementation_phases.md:131](../../Explainer_implementation_phases.md#L131)), and the vision statement "a normal written English story" ([Implementation_phases.md:48](../../Implementation_phases.md#L48), [Implementation_phases.md:636](../../Implementation_phases.md#L636), [Implementation_phases.md:676](../../Implementation_phases.md#L676)).

### Inferences
- Under B, a "translate story" step must come before the Story Bible, and a "translate speech back" step after speech-unit planning and before TTS. TTS, the H3 `<d>` check, the dialogue check and captions all consume `speech_unit.text`. That means new job types (a `job.type` CHECK migration like other phases), new targets and staleness rules in `story_pipeline_targets.py`, and provenance for the translation. L.
- Under B, any re-translation that is not deterministic would change the English story. Its hash then makes every downstream stage stale, because scene discovery, events and units key off the exact text (inference).
- Under A and C, no new pipeline step is needed; the changes are inside existing writers and helpers.

### Gaps
- I did not read all 2,936 lines of `story_pipeline_targets.py`. The search for "language/English/Hindi" is the evidence for "no mention".

---

## 7. Inventory and classification under architectures A, B and C (objective)

### Takeaway
C (Hindi story read directly; English internals; verbatim Hindi speech and displayed text) matches what the code already half-does: event text and `starts_with` already stay "in the story's own language". In the code, C is mostly S items plus a project language column, fonts and voices (M). Its real cost sits outside the code: whether the GPU server's ASR, TTS and H3 handle Hindi. A adds an L rewrite of every internal prompt and its English guards, and probably still needs English visual prompts. B adds L translation stages and loses the author's verbatim Hindi.

### Cited Findings
Sizes per architecture. "—" means no change needed. All citations are in Sections 1–6.

| # | Item (path:line) | A native Hindi | B English pivot | C hybrid |
|---|---|---|---|---|
| 1 | No `language` on `Project` (models.py:32-129); Bible `language="en"` (story_bible_writer.py:30,216) | M | M | M |
| 2 | Blanket "Write everything in English" in about 12 internal writers (Section 2 list) | L (flip all) | — | — |
| 3 | English regex guards on prompt prose (shot_prompt_writer.py:122,125-197; character_take_prompt_writer.py:128-129) | L (blind on Hindi) | — | — |
| 4 | Prompt word-count targets of 350–500 English words (shot_prompt_writer.py:726,1449-1455; character_take_prompt_writer.py:88,866) | M | — | — |
| 5 | Scene `title`/`description` in English (scene_discovery_writer.py:119-120) | S | S (back-translate titles) | S (Hindi display title) |
| 6 | `starts_with` and slice cutting (scene_discovery_writer.py:122-127,340,347-349) | — | L (slices are of the English translation; Hindi alignment lost) | — |
| 7 | Event `text` verbatim; `description`/`emotion` English (event_extraction_writer.py:131-177,282-283) | S (emotion would turn Hindi and break #14) | L (text is English; Hindi only by back-translation) | — |
| 8 | `normalise` drops matras (scene_discovery_writer.py:177-182; event_extraction_writer.py:496-498) | S (optional: keep marks) | — | S (optional) |
| 9 | `<d>[English]` template (shot_prompt_writer.py:731-738,812-814; character_take_prompt_writer.py:467-468) | S | S (and the `<d>` words must be back-translated Hindi) | S |
| 10 | Raw `in` check on `<d>` words (shot_prompt_writer.py:1288) | S (NFC both sides) | S | S |
| 11 | Name-leak tokeniser misses Devanagari (shot_prompt_writer.py:1374) | S | — | — (names romanised) |
| 12 | ASCII ids/slugs (discovery_writer.py:48,295-307; explainer.py:47,152-162) | S (insist on Latin ids) | — | S (library names in Devanagari get fallback ids) |
| 13 | Sentence end has no danda (speech_chunks.py:21; voice_design_writer.py:63; caption_plan.py:62; caption_srt.py:39) | S | S | S |
| 14 | English emotion stems (speech_unit_planner.py:34-41,59-72) | S | — | — |
| 15 | One global WPM for estimates (speech_unit_planner.py:75-76; story_length.py:45-49; settings.py:170,164) | S-M | S-M (English units, Hindi audio) | S-M |
| 16 | TTS chunk budget calibrated on English (speech_chunks.py:3-6,25-31; speech_synthesizer.py:29) | S (measure) | S | S |
| 17 | English `CHARACTER_LINE` sample (voice_design_writer.py:53-58; story_voices.py:430) | S | S | S |
| 18 | Voices shared across projects with no language (models.py:1945-1967; story_voices.py:13-16) | M | M | M |
| 19 | `voice_identity.accent` with no language (character_definition_writer.py:56-61,117,465-470) | S | S | S |
| 20 | English TTS instruction "Speak with this emotion" (speech_synthesis.py:222-227) | S (if emotion is Hindi) | — | — (unless Breeze needs it in Hindi: gap) |
| 21 | Transcriber has no language field; Parakeet Hindi coverage unknown (transcriber.py:8-9,61-70) | L server / S adapter | L / S | L / S |
| 22 | Dialogue check English folds (dialogue_matching.py:20-226; dialogue_check.py:83,483-496) | M (Hindi folds) | M | M |
| 23 | `number_words` English only; Devanagari digits do parse (number_words.py:1-17,81,104) | M | — (units are English) / M at the check | M (explainer graphics and the dialogue check) |
| 24 | Explainer timings, takes and recordings depend on the ASR hearing words (word_timings.py:226-263; take_timings.py:156-162; full_recordings.py:16) | depends on #21 | depends on #21 | depends on #21 |
| 25 | Caption font has no Devanagari; char-count layout; punctuation (caption_plan.py:45-62,149,163,173-188,240; font_metrics.py:23-45) | M | M | M |
| 26 | Breeze TTS 2 Hindi support unknown; no language field (speech_synthesizer.py:45-70) | L if unsupported | L if unsupported | L if unsupported |
| 27 | H3 Hindi lip sync unknown (video_generator.py; `<d>` tag) | gap | gap | gap |
| 28 | LLM byte/char budgets (llm.py:34-37; qwen38.py:37,42,50-60; event_extraction_writer.py:56-61) | S | S (two extra calls per story) | S |
| 29 | YouTube metadata `en` and "Write in English" (youtube_publish.py:45,321-322; youtube_api.py:40-41,60,245; youtube_draft_writer.py:60,68-69) | S | S | S |
| 30 | New translate-in and translate-out pipeline stages (story_pipeline_targets.py; jobs) | — | L | — |
| 31 | Music writers in English; story music instrumental (music_cue_writer.py:95; music_theme_writer.py:52) | — | — | — |

### Inferences
- **C** fits the current design best. Speech and slice fields are already language-preserving. The "English internals" rule is already in place, and the validators run on normalised text, except item 10.
  - Code changes for C: items 1, 5, 9, 10, 12, 13, 15, 16, 17, 18, 19, 22, 23, 25 and 29 (mostly S, with M for the language column, voices, captions/fonts and Hindi match folds).
  - Blocking unknowns: items 21, 26 and 27. These are GPU-server capabilities, not code.
- **A** is C plus items 2, 3, 4, 7 and 14, turning Hindi throughout. It would send Hindi prose to image and video models the repository treats as English-prompted. Inference: A would likely end up translating visual prompts back to English, which is C with extra cost.
- **B** keeps the internal prompts but breaks the verbatim chain (items 6, 7, 30). Scene slices, events and units would be machine-translated English, and the spoken and displayed Hindi would be a back-translation, not the author's words. Speech-unit estimates would be made on English words while the audio is Hindi. The `<d>` words, the dialogue check and captions would need the back-translated Hindi. B also adds two paid model stages per story and new staleness rules. Only B needs new pipeline stages.
- Under every architecture, the ASR question (item 21) decides whether the dialogue check and all explainer timing features survive. Until it is answered, a Hindi story project should run with `dialogue_match_threshold = 0` to avoid automatic GPU re-generations (inference from [settings.py:576-592](../../backend/app/core/settings.py#L576)).

### Gaps
- Sizes are my estimates from reading the code, not from a plan or a prototype.
- The frontend (`frontend/src`) and the Remotion renderer (`motion/`) were out of scope, beyond the font files checked. The Remotion fonts also lack Devanagari, so callouts and graphics there will need fonts too (verified for `motion/public/fonts`).
- Not audited in depth: the Music, Graphics, Evidence and Thumbnail writers, beyond the lines cited.
