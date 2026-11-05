# Shot generation issues: analysis and recommendations

Written 2026-11-03. The evidence comes from project 48, "THE MAN NOBODY IN THE ROOM KNEW" (35 scenes, 673 shots, 761 takes, no narration, portrait). It was gathered three ways: read-only queries on the app database, frames pulled from the selected clips, and the code. No code or data was changed.

---

## Summary

| # | Issue | Main cause | Recommended fix | Effort |
|---|---|---|---|---|
| 1 | Speech in an invented language, not caught | Silent shots ask H3 for talking ("he talks", "murmur of conversation") but give it no words, and silent shots are never transcribed | Stop asking for talking in silent shots (rules plus a code check), and say who stays silent in dialogue shots | Small |
| 2 | Short lines fail the transcription check | The check is word-exact. Spelling ("tyre"/"tire"), digits ("six"/"6") and homophones ("too"/"two") all count as wrong, and one different word on a line of 4 words or fewer always falls below 80% | Smarter word matching, a rule for short lines, and no more retries when every take hears the same thing | Small |
| 3 | Car interiors have no roof | The garage scene sends only a garage picture as "the place". The car is never a reference, and the prompt puts the garage and its ceiling lights around the people | Use the existing "John's Corolla" environment for in-car shots, then allow a per-shot environment later | Small now, Medium later |
| 4 | One clip per short line feels choppy | The planner is told to prefer one line per shot and to use the multi-shot "rapid exchange" rarely | Let the planner group runs of short lines into rapid exchanges, which already work well | Small, then Medium |
| 5 | People missing from group shots | The shot definer lists only the people who act, so the others get no picture and no description and H3 leaves their chairs empty. When everyone is listed, H3 invents extra guests | Code decides who is in frame from the scene's staging, and the prompt states the exact head count | Medium |

---

## How a shot is made today (context)

1. **Shot planning** (language model, one call per scene): the list of shots, the events and lines each one carries, its length, and the `rapid_exchange` flag. File: `services/shot_planning_writer.py`.
2. **Shot definition** (language model, one call per shot): who is visible, the composition, which view of the place is behind, the action, and the ambient sound and sound events. File: `services/shot_definition_writer.py`.
3. **Reference pictures** (code): the pictures of each visible character plus one picture of the scene's environment, at most 9. File: `services/reference_selection.py`.
4. **Generation request** (code): the pictures, the dialogue audios (the recorded voice lines, at most 3) and the clip length. File: `services/generation_planner.py`.
5. **Prompt** (language model plus code): MiniMax H3's six-part prompt. File: `services/shot_prompt_writer.py`.
6. **H3** makes the picture and the sound together. The speech is H3's own rendition of the reference audio (`partially_copy`), not the recording itself.
7. **Checks.** First a technical check. Then, **only for shots with dialogue lines**, Parakeet transcribes the clip and its words are compared with the lines (`services/dialogue_check.py`), passing at 80% or more. A take that fails is made again automatically, up to 2 times.

---

## Issue 1: Speech in an invented language that the check does not catch

### What you see
In some clips, mostly with several people in frame, someone talks, but not a single word can be understood. The transcription check does not flag it.

### What we found
- **Silent shots are never transcribed.** The dialogue check only runs when a shot has dialogue lines (`shot_takes._needs_dialogue_check` returns false when there are none). Project 48 has 244 silent shots, and nothing H3 says in them is ever checked.
- **About 50 of those 244 silent shots ask H3 for talking or voice-like sound, with no words to say.** A few matches are harmless ("before answering"), but most are not:
  - `scene_dinner_begins/shot_7`: the prompt says "Through the clip he talks with easy gesturing hands". The planned shot is "Richard explains the warehouse automation while John listens", but that event has no recorded line.
  - `scene_dinner_begins/shot_22` (5 people): the soundscape is "a warm blur of indistinct table conversation".
  - `scene_dining_room_arrival/shot_1` (3 people): "soft indistinct murmur of Richard's conversation with the two guests … a low easy chuckle".
  - `scene_richards_call/shot_6` (5 people): "chatter" and "conversation".
  - `scene_john_sidelined/shot_1`: "the engineer's compressed voice" on the speakerphone, with no line for it.
  - `scene_dinner_begins/shot_3`: the sound event "John's murmured request, barely above a whisper".
- **The prompt contradicts itself.** After that text, the app adds "Nobody speaks, and every mouth stays closed." H3 follows the action, so a person who "talks" or "explains" with no words gets made-up words.
- Most of these shots are in the dinner and phone-call scenes, where several people are in the room even when the shot shows only one of them.
- **Dialogue shots with listeners have a gap too.** Of 81 dialogue shots with listeners in frame, the app never writes a sentence telling the listeners to stay silent. The language model added one on its own in 53 of them, so about 28 rely on luck.

### Why it happens
1. **The story has speech with no words.** Events such as "Richard explains…", "a guest asks…" and "the engineer's voice continues" have no recorded line. The planner makes a silent shot of them, and the definer describes the person as talking.
2. **Voice-like ambience is allowed.** "Murmur of conversation", "voices", "chatter" and "chuckle" pass the "no speech" rule because the model reads them as background, but H3 turns them into speech.
3. **Nothing checks it.** Silent shots are not transcribed at all. *Not verified:* what Parakeet returns for invented-language babble. It may return nothing, which would also hide babble in dialogue shots.

### Options

| Option | Pros | Cons |
|---|---|---|
| **A.** Rules: a silent shot never shows anyone talking, and voice-like ambience is not allowed (conversation, voices, chatter, laughter, phone voices). Add this to the shot definition and the prompt writer. | Cheap, and removes the main trigger | A language model does not always obey a rule |
| **B.** A code check in the prompt compiler that refuses a silent-shot prompt containing talking words and asks the model again (the same way labels and `<d>` tags are checked today) | Reliable, and uses the existing retry | The word list needs care, because "before he answers" is fine |
| **C.** A code-written sentence in every dialogue shot: "Only <Subject 2> speaks. <Subject 1> and <Subject 3> listen with their mouths closed." | Deterministic, tiny change | None worth noting |
| **D.** A planner rule: an event that implies speech but has no recorded line is shown from a listener or as a reaction, never with the speaker talking on screen | Fixes it at the source | Changes how some scenes are cut |
| **E.** Transcribe silent shots too, and fail them when words are heard. In dialogue shots, report words heard outside a line's time window. | Catches what slips through | One more short GPU job per silent take, and it may miss babble if Parakeet ignores it (not verified) |
| **F.** Replace H3's sound in silent shots with a room-tone bed | Guarantees there are no voices | Loses H3's in-sync sound (clinks, footsteps) and needs a new render step |

### Recommendation
Do **A + B + C** now; they are all prompt text and one code check in `shot_definition_writer.py` and `shot_prompt_writer.py`. Add **D** to the planner. Then add **E**, but first run one known bad take through Parakeet to see whether it returns words for the babble. If it returns nothing, E needs a different signal, such as voice activity detection.

---

## Issue 2: Short lines fail the transcription check even when they are right

### What you see
When a line is short, the check fails even when the speech is correct, so you have to choose a clip by hand.

### What we found
In project 48, 513 takes were checked and 91 failed. Sorting every failure by what Parakeet heard:

| What happened | Failed takes | Was the speech right? |
|---|---|---|
| Spelling or digits: "tyre" heard as "tire", "six" as "6", "fifteen percent" as "15" | 19 | Yes |
| Homophones: "you too" heard as "you two", "by your shirt" as "buy your shirt" | 10 | Yes |
| One tiny sound difference: "him" as "em", "want it to" as "wanted to", "the" as "a", "IT" as "i t" | 18 | Almost certainly acceptable |
| Nothing heard on a 1- or 2-word line: "oh", "why", "hey", "I did", "I work" | 26 | Unknown: either H3 said nothing or Parakeet missed it |
| H3 added or changed words, mostly on one-word fragments: "Don't" became "Don't you think that's the first one", "When" became "When we're going to be able to do it" | 18 | No (real failures) |

- **12 shots went through 6 takes each.** 7 of them failed only on spelling, a homophone or a one-sound difference. For example, all six takes of `scene_parking_garage/shot_11` ("The tyre's fine.") were heard as "the tires fine". That is about 35 unnecessary H3 runs, roughly 6 to 12 GPU hours at 10 to 20 minutes each.
- **Short lines leave no margin.** The score is word-for-word similarity, and the threshold is 80%. On a line of 4 words or fewer, one different word gives 75% or less, so the take always fails. On "oh" or "why", a missed word scores 0%.
- **The retry never notices it keeps getting the same answer.** Six identical transcripts in a row is a strong sign that the check is wrong, not the clip.
- **The lines H3 "finishes" are one-word fragments**, interruptions such as "Don't—", "And—" and "That—", each alone in a 3-second clip. Some prompts even describe a beat "before he speaks again", which invites more speech.

### Why it happens
1. The comparison is too literal: it does not handle numbers, UK and US spelling, homophones or casual reductions.
2. One threshold is used for every line length, so short lines have no room for any difference.
3. Parakeet is weak on isolated interjections and single short words.
4. A one-word line alone in a 3-second clip leaves H3 about 2 seconds of silence to fill, and it sometimes fills it with words (see Issue 4).
5. The retry does not notice that it keeps getting the same transcript.

### Options

| Option | Pros | Cons |
|---|---|---|
| **A.** Better word matching on both sides: numbers in one form (`number_words.py` already exists), "%" read as "percent", a short UK/US spelling list (tyre/tire, colour/color, …) and homophone groups (to/too/two, by/buy/bye, for/four, there/their/they're, …) | Removes about 29 of the 91 failures outright | Folding homophones could hide a rare real swap |
| **B.** A rule for short lines: a line of 1 to 4 words passes when at most one word differs and the two words sound alike (or compare letters instead of whole words) | Fixes most near-misses | Slightly more lenient |
| **C.** Interjections and one-word lines ("oh", "ah", "hmm", "why"): an empty transcript does not fail the take. The take is marked "speech not verifiable", selected, and shown with a badge. | Ends the 6-take loops on "oh" | Lets a truly silent take through on one-word lines |
| **D.** Compare only the words heard inside the line's own time window (its start to its end plus about 0.7 s), and report words outside it separately as "extra speech" | Separates "right words" from "the model kept talking", and the message is clearer | A little more logic |
| **E.** Stop retrying when two takes in a row hear the same text, and mark the shot "needs your review" | Saves GPU hours immediately | None worth noting |
| **F.** A prompt rule: after the last line, nobody speaks again until the clip ends | Cuts the added words | The rule may sometimes be ignored |
| **G.** Fix the planning (Issue 4) so a one-word line is never alone in a 3-second clip | Fixes the real failures at the source | A bigger change |

### Recommendation
Do **A + B + C + E** now. They live in `dialogue_check.py` and `shot_takes.queue_retry`, with no change to the GPU side or the language model. Add **D** and **F** next; **G** comes with Issue 4. Based on the failures above, this should remove nearly all 47 false failures and the 26 empty-transcript loops. The real effect depends on how strict the new rules end up.

---

## Issue 3: Car interiors with no car body (hotel parking garage)

### What you see
In the hotel parking garage scene, most shots inside the car show the seats but no car body or roof above them. It looks like an open vehicle with just seats.

### What we found
- **The scene has one environment, the Hotel Parking Garage.** Most of `scene_parking_garage`'s 45 shots are inside John's Corolla, but each one is sent a single place picture: a view of the garage ("Corolla's bay and pillars" or "Aisle with far-wall pipes"). No picture of the car is ever sent.
- **The project already has a car-interior environment.** "John's Corolla" (grey fabric seats, with "driver side profile" and "passenger side profile" views) is used only by `scene_final_drive`, because a scene can have only one environment.
- **The prompt describes the garage, not the car.** It spends many words on the garage (pillars, bay lines, "cool grey tube light falling from the low beams") and four words on the car ("inside a parked car"). One rule also tells the prompt writer that the view "says what is seen behind the people", so the garage is placed behind them instead of being seen through the windows.
- **The frames confirm it.** In the selected takes of shots 11 and 6, the door and window are there, but the garage ceiling and its tube lights sit directly above the people's heads, with no roof or headliner. The interior also changes from shot to shot: black leather in shot 6, beige in shot 3, while the car is defined with grey fabric.
- **Your three feedback notes could not fix it.** The notes ("car should be visible properly …") can only change the prompt's words; the reference picture stayed the garage.

### Why it happens
H3 is shown a garage, told to keep it ("partially_preserved"), and told to light the people from overhead tube lights. With no picture of the car and almost no description of it, it builds the seats into the garage and removes the roof.

### Options

| Option | Pros | Cons |
|---|---|---|
| **A.** Change this scene's environment to John's Corolla, with the state "parked on garage level P1, garage seen through the windows", and redo its shots | Uses what already exists, and fixes the roof and the seat colour | The garage-only shots (water dripping, the car rolling in, the valet seen through the windscreen) lose their garage picture |
| **B.** Split the scene: the outside shots in one scene, the in-car shots in another | Each part gets the right environment | Changes the story structure and needs manual work |
| **C.** Allow a second environment per scene, so each shot chooses "inside" or "outside" (for example the car interior, with the garage seen through the glass) | The right long-term model, which also covers lifts, trains and planes | A larger change across scene definition, staging, views, reference selection and the prompt |
| **D.** Treat the car as a prop: send a picture of the car interior as an extra subject in in-car shots | Works within the current one-environment model | Needs a new "prop" kind, and still needs prompt rules |
| **E.** A prompt rule for enclosed spaces: inside a vehicle or a small room, describe the enclosure first (roof and headliner above, pillars, windscreen frame, dashboard, door panels), show the outside only through the glass, and let the light come in through the windows | Cheap, and helps every vehicle shot | Without a picture, the car still varies from shot to shot |

### Recommendation
Now: **A** for `scene_parking_garage` plus **E**. Also check the other garage scenes (`scene_emily_admits`, `scene_garage_confrontation`, `scene_johns_flaw`, `scene_money_question_garage`) for in-car shots. Later: **C**, which turns "one place per scene" into "a main place, plus an inside or outside place per shot".

---

## Issue 4: One clip per short line feels choppy, and multi-shot is hardly used

### What you see
Each short line gets its own shot, so conversations feel discontinuous. Multi-shot generation is almost never used.

### What we found
- **Almost every dialogue shot is a single short line.** 429 shots carry speech, and 409 of them carry exactly one line. Of those, 302 are at the shortest planned length (3.04 s).
- **The parking garage scene shows it most.** `scene_parking_garage` has 45 shots, 31 of them single-line dialogue shots of about 3 seconds in a row: "Yeah.", "I did.", "And?", "What?", "Okay.", "Ah.". A 1-second line in a 3-second clip leaves about 2 seconds of silence each time. Each clip is also a separate generation with its own seed, so the car, the light and the positions shift at every cut.
- **The multi-shot form already exists but is rarely used.** A **rapid exchange** is one clip in which H3 cuts internally (`[Shot 1]`, `[Shot 2] At 00:01.200`, …). Only 16 shots in project 48 use it, about 4% of the shots with speech.
- **Rapid exchanges work well.** All 16 passed the dialogue check, 15 of them on the first take, and the one first-take failure was a false alarm ("IT" heard as "i t"). Frames from `scene_daniel_greeting/shot_20` show a wide three-shot cutting to an over-the-shoulder shot of the speaker, with the same faces across the cut.
- **The planner is told to avoid it.** Its instructions say "Use false for almost every shot … Most dialogue is better as a sequence of short dialogue shots" and "Prefer one line of dialogue per shot". The feature (PHASE-043) shipped as "use rarely", and its live owner check (V6b) is still open.
- **The current exchange has hard limits:** 2 or 3 lines, exactly two speakers taking turns, both visible, no continuity with the previous shot, and no off-screen voice. The cap of 3 lines comes from H3 taking at most 3 audio references.

### Why it happens
The planner is told to avoid exchanges, and the shortest shot (3 s) is much longer than most short lines.

### Options

| Option | Pros | Cons |
|---|---|---|
| **A.** Change the planner instructions: group consecutive short lines between the same two people into a rapid exchange, and keep single shots for long or important lines | A tiny change that uses a route that already works | The model still decides, and may still under-use it |
| **B.** A code pass after planning: merge runs of 2 or 3 alternating short lines (for example each under 2 s, together under about 8 s) into one exchange shot | Predictable, with no model judgement | Can override a deliberate cut, and must keep the event-order checks |
| **C.** Allow listener reactions and silent beats inside an exchange (for example [Shot 1] a two-shot, [Shot 2] A speaks, [Shot 3] B reacts) | More natural coverage | More prompt rules, and untested |
| **D.** Lift the 3-line cap with one audio per *speaker* that holds all their lines at the right times with silence between (the explainer already places audio inside silence) | Longer exchanges, 4 to 6 lines in one clip | Untested whether H3 copies a long, gappy reference cleanly, and an audio reference is limited to 15 s |
| **E.** Allow three speakers, or an off-screen voice, in an exchange | Fits group and phone scenes | More risk of the wrong person speaking, and untested |

### Recommendation
Do **A** first, and mark PHASE-043 done after one more live check. Add **B** if the model still under-uses exchanges. Try **D** in the Video lab before building it. **C** and **E** come later.

---

## Issue 5: People missing from group shots (5 people at a table)

### What you see
In dining or conference scenes with 5 people seated, some shots show only one or two of them, and the others silently disappear.

### What we found
- **Every character the shot definition lists as visible gets a picture.** There is room for all of them: 5 people plus the place is 6 of the 9 pictures H3 takes. The people go missing **before** that step, because the definer leaves them out.
- **49 group-size shots leave people out.** In scenes with 4 or more characters, 49 medium-wide or wide shots list fewer people than the scene has. Some are correct (a character has left, or is only a voice on the phone), but many are not:
  - `scene_dinner_begins/shot_7` and `shot_12` (medium-wide, 2 of 5 listed): the frames show John and Richard alone at a long table set for many, with every other chair empty.
  - `scene_daniel_prods_john/shot_3` ("The others at the table listen…", 2 of 5 listed): only Richard and Laura appear.
  - Also `scene_dining_room_arrival/shot_7` (2 of 5), `scene_exfiltration/shot_12` (2 of 6) and `scene_john_takes_control/shot_12` (2 of 6).
- **The opposite also happens.** `scene_daniel_prods_john/shot_14` lists all 5 people, and the frame shows well over a dozen. The room is defined with a long table and twelve chairs, and the prompt never says how many people are there or that nobody else is.
- **Visibility is left to the model.** The definer's rule is "one entry for each character who is VISIBLE in this shot", so the model has to imagine who is in frame. The scene's staging already knows where everyone sits (zones and screen sides), but no code uses it to decide who must appear in a group shot.

### Why it happens
Visibility is the language model's guess, and H3 draws only the people it is told about. When the place picture shows a big table, H3 fills or empties the chairs as it likes, because the head count is never stated.

### Options

| Option | Pros | Cons |
|---|---|---|
| **A.** A rule in the shot definition: in a wide or medium-wide shot, or any shot framed on the group's view, list every character who is present in the place at that moment | Cheap | The model may still skip people |
| **B.** A code check from the staging: for group-size shots, refuse a definition that leaves out a present, on-screen character (off-screen voices excluded) and ask again | Reliable | Needs a rule for who is "present" when people enter or leave |
| **C.** The prompt states the head count, written by code: "Exactly N people are in the room: <Subject 1> … <Subject N>. No one else is present, and the other chairs are empty." | Stops both the invented extras and the empty seats | None worth noting |
| **D.** An environment state for the dinner, such as "table set for five" (or a picture of that state), so the place picture does not show twelve settings | Removes the cue to fill the chairs | Needs a new state picture |
| **E.** A group keyframe: one still image of the whole group made by the image model, sent as a "keep this composition" picture (like the continuity anchor) | The strongest control over who sits where | A new step, and the image model must keep 5 identities (Qwen-Image-Edit-2511 is not set up yet) |

### Recommendation
Do **A + B + C** now. Use **D** for scenes in big rooms. Add **E** later, once Qwen-Image-Edit is set up (items 10 and 11 in `tasks.md`).

---

## Suggested order of work

1. **Issue 2 check fixes** (A, B, C, E). The quickest win, and it saves GPU time from the first day.
2. **Issue 1** rules, code check and listener sentence (A, B, C), plus the planner rule (D).
3. **Issue 4** planner change to use rapid exchanges (A), then the merge in code (B).
4. **Issue 5** group presence from staging plus the head count (A, B, C).
5. **Issue 3**: switch the garage scene to the car environment now (A, E). The per-shot environment (C) comes later.
6. Later: transcribe silent shots (Issue 1 E), one audio per speaker (Issue 4 D) and group keyframes (Issue 5 E).

## What was not verified

- What Parakeet returns for invented-language babble. This needs checking before relying on Issue 1 option E.
- For the 26 empty transcripts, whether H3 said nothing or Parakeet missed the word. Listening to `scene_token_analysis/shot_12` ("Oh") and `scene_garage_confrontation/shot_14` ("I work") would tell.
- One audio per speaker (Issue 4 D) and three-speaker exchanges (Issue 4 E) have not been tried on H3.
- All the numbers come from project 48 only.

## Appendix: how this was checked

- **Database:** read-only queries on the app database (`/data/app.db`) covering the newest shot plans, shot definitions, reference manifests, generation requests, prompts, takes and dialogue checks of project 48.
- **Frames:** one frame from each of 8 selected clips, extracted with ffmpeg and looked at by eye. The clips were parking garage shots 3, 6 and 11, dinner shots 7 and 12, `scene_daniel_prods_john` shots 3 and 14, and the rapid exchange `scene_daniel_greeting/shot_20`.
- **Code read:** `shot_planning_writer.py`, `shot_definition_writer.py`, `reference_selection.py`, `generation_planner.py`, `shot_prompt_writer.py`, `dialogue_check.py`, `shot_takes.py`, `jobs/check_take_dialogue.py`, and the PHASE-043 notes in `Implementation_phases.md`.
