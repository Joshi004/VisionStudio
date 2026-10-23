# Music Lab trials: tracker (temporary, to be discarded)

How to use this: open the Music Lab page, find the group whose description starts with the case id (for example `[B1]`), listen, and set Good / Usable / Bad plus a note on each run card (those are saved in the app). Write your findings after each `Notes:` below. The run table under every case is filled by `python3 trigger.py tracker`, and only the text between the `RUNS` markers is rewritten, so your notes are safe.

All runs use seed 1717 unless the case says otherwise, so models are compared on equal terms. The exact fields sent are in "What was sent" on each run card. Hand-written prompts are the same text for every model of a case, written in the style each model expects.

Nothing here has been judged by the assistant.

## Checks for every run (apply to all cases)

1. Length: the length shown on the card against the length asked for. Note silent padding at the end or an abrupt cut. Notes:
2. Start and end: clean start, no click, no chopped note, a natural or deliberate ending. Notes:
3. Artifacts: distortion, clipping, metallic or watery sound, glitches. Notes:
4. Leakage: vocals in an instrumental, or music in a sound effect or ambience. Notes:
5. Prompt match, 1 to 5. Notes:
6. Verdict in the lab (good, usable, bad) and roughly how long it took. Notes:

The cases below only list what is specific to them.

---

# A. Score: length and a single emotion

## A1. 6Fingers, 30 s, curious and playful, under narration
Models: Stable Audio 3, ACE-Step. Instrumental score at 100 BPM, marimba and pizzicato, no lead melody.
<!-- RUNS:A1 -->
Group key `1e198e1bf6d966a5`, triggered 2026-10-23T13:48:33+00:00. In the Music Lab, look for the group whose description starts with `[A1]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 7 | stable-audio-3 | 1717 | succeeded | 30.0 |  |
| 8 | ace-step-1.5 | 1717 | succeeded | 30.0 |  |
<!-- /RUNS:A1 -->
- Sparse enough to put a narrator over it, with nothing crowding the middle? Notes:
- Reads as "tech and curious", not generic cheerful stock music? Notes:
- Ends at 30 s, and how does it end (fade, cut, resolve)? Notes:
- ACE: does it hold the 100 BPM you asked for (tap it)? Notes:

## A2. First Light, 60 s, wonder rising to awe, under narration
Models: Stable Audio 3, ACE-Step. Slow pads, sparse piano, celesta, low strings swelling.
<!-- RUNS:A2 -->
Group key `46c7f6f06ef73389`, triggered 2026-10-23T13:48:33+00:00. In the Music Lab, look for the group whose description starts with `[A2]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 9 | stable-audio-3 | 1717 | succeeded | 60.0 |  |
| 10 | ace-step-1.5 | 1717 | succeeded | 60.0 |  |
<!-- /RUNS:A2 -->
- Is the arc audible: quiet mystery at the start, awe at the end? Notes:
- Cosmic without cliché (no big movie-trailer boom)? Notes:
- Sparse enough under a voice? Notes:
- Ends at 60 s? Notes:

## A4. Arjun, whole story as one 180 s piece
Models: Stable Audio 3, ACE-Step. Dread escalates, last minute hollow and tragic.
<!-- RUNS:A4 -->
Group key `21726df46157d2bc`, triggered 2026-10-23T13:48:33+00:00. In the Music Lab, look for the group whose description starts with `[A4]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 11 | stable-audio-3 | 1717 | succeeded | 180.0 |  |
| 12 | ace-step-1.5 | 1717 | succeeded | 180.0 |  |
<!-- /RUNS:A4 -->
- Does 3 minutes hold together, or does it loop, repeat a pattern, or wander? Notes:
- Does the dread actually escalate over time? Notes:
- Is the last minute hollow and tragic as asked, or just louder? Notes:
- Where does quality drop, if it does (time stamp)? Notes:

---

# B. Timestamp and duration adherence

For every cue, write the second it actually happens and the error against the request.

## B1. First Light, 60 s with exact cues
Cues: 0:00-0:15 dense hot rumble. 0:15-0:24 rising tension. 0:24 sudden bright swell. 0:24-0:48 calm travelling pad. 0:48-1:00 resolve and fade.
Models: Stable Audio 3 (cues written as a timeline), ACE-Step (section tags, 120 BPM, 60 s).
<!-- RUNS:B1 -->
Group key `460a2ef9f1350175`, triggered 2026-10-23T13:54:08+00:00. In the Music Lab, look for the group whose description starts with `[B1]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 13 | stable-audio-3 | 1717 | succeeded | 60.0 |  |
| 14 | ace-step-1.5 | 1717 | succeeded | 60.0 |  |
<!-- /RUNS:B1 -->
- When does the rumble stop and the tension start (target 0:15)? Notes:
- When does the swell land (target 0:24), and how sharp is it? Notes:
- When does the calm pad start and end (targets 0:24 and 0:48)? Notes:
- Does it fade to silence at 1:00? Notes:
- Are the sections in the right order, even if the times are off? Notes:

## B2. Arjun, The Voice scene, 36 s matched to the real narration
Cues: 0:00-0:08 near silence. 0:08 one heavy hit. 0:08-0:20 building pulse. 0:20 cold string stab. 0:20-0:30 dissonant swell. 0:30-0:33 exactly three sharp hits. 0:33-0:36 cut to silence.
Models: Stable Audio 3, ACE-Step (60 BPM so one beat is one second).
<!-- RUNS:B2 -->
Group key `dc3b421e7110ced1`, triggered 2026-10-23T13:54:08+00:00. In the Music Lab, look for the group whose description starts with `[B2]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 15 | stable-audio-3 | 1717 | succeeded | 36.0 |  |
| 16 | ace-step-1.5 | 1717 | succeeded | 36.0 |  |
<!-- /RUNS:B2 -->
- Is it really near silent for the first 8 s? Notes:
- Is there ONE heavy hit at 0:08, not several? Notes:
- Does the string stab land at 0:20? Notes:
- Count the hits near 0:30: exactly three? Notes:
- Is there silence at the end (0:33-0:36)? Notes:

## B3a. Odd length, 23.5 s soft rain (ambience models)
Models: LTX audio, Stable Audio Open, Stable Audio 3.
<!-- RUNS:B3a -->
Group key `eb1e53a03ed2294d`, triggered 2026-10-23T13:54:08+00:00. In the Music Lab, look for the group whose description starts with `[B3a]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 17 | ltx-audio | 1717 | succeeded | 23.3 |  |
| 18 | stable-audio-open | 1717 | succeeded | 23.5 |  |
| 19 | stable-audio-3 | 1717 | succeeded | 23.5 |  |
<!-- /RUNS:B3a -->
- Real file length against 23.5 s for each model (card shows it). Notes:
- Does the file end in padding or silence, or get cut mid-sound? Notes:
- Is the rain steady, or does it develop or loop audibly? Notes:

## B3b. Odd length, 23.5 s soft piano (score models)
Models: Stable Audio 3, ACE-Step.
<!-- RUNS:B3b -->
Group key `292cfc0f603f4933`, triggered 2026-10-23T13:54:08+00:00. In the Music Lab, look for the group whose description starts with `[B3b]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 20 | stable-audio-3 | 1717 | succeeded | 23.5 |  |
| 21 | ace-step-1.5 | 1717 | succeeded | 23.5 |  |
<!-- /RUNS:B3b -->
- Real file length against 23.5 s. Notes:
- Is there a clear ending or a cut? Notes:

## B4a. Maximum length: Stable Audio Open 47 s and LTX 60 s
Models: LTX audio (60 s), Stable Audio Open (47 s).
<!-- RUNS:B4a -->
Group key `5fd6a9f5508d1783`, triggered 2026-10-23T13:54:08+00:00. In the Music Lab, look for the group whose description starts with `[B4a]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 22 | ltx-audio | 1717 | succeeded | 60.0 |  |
| 23 | stable-audio-open | 1717 | succeeded | 47.0 |  |
<!-- /RUNS:B4a -->
- Real length against the maximum. Notes:
- Does the sound stay coherent to the end, or fall apart or repeat? Notes:
- Does the "gradually more tense" evolution happen? Notes:

## B4b. Maximum length: Stable Audio 3 at 285 s
<!-- RUNS:B4b -->
Group key `24150e76e52f5b2f`, triggered 2026-10-23T13:54:08+00:00. In the Music Lab, look for the group whose description starts with `[B4b]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 24 | stable-audio-3 | 1717 | succeeded | 285.0 |  |
<!-- /RUNS:B4b -->
- Real length against 285 s. Notes:
- Loops, drift, or silent stretches? Mark the time stamps. Notes:
- Does it change through calm, wonder, tension and resolution as asked? Notes:
- Ending: natural or cut? Notes:

---

# C. One audio with many emotions, or several audios

## C1. Arjun scenes 5 to 8 as ONE 129 s piece
Cues: 0:00-0:36 tense, cold dread, frozen fear. 0:36-1:04 methodical, then shaken. 1:04-1:51 dread, terror, childlike menace, blackout at 1:51. 1:51-2:09 shock, grief, quiet tragedy.
Models: Stable Audio 3, ACE-Step.
<!-- RUNS:C1 -->
Group key `53e47c9547e1edba`, triggered 2026-10-23T14:01:54+00:00. In the Music Lab, look for the group whose description starts with `[C1]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 25 | stable-audio-3 | 1717 | succeeded | 129.0 |  |
| 26 | ace-step-1.5 | 1717 | succeeded | 129.0 |  |
<!-- /RUNS:C1 -->
- Is each of the four emotional sections recognisable? Notes:
- Where do the changes actually happen against 0:36, 1:04 and 1:51? Notes:
- Is the music-box menace audible, and the silence at 1:51? Notes:
- Are the transitions smooth, or jumpy and unrelated? Notes:

## C2a to C2d. The same four scenes as SEPARATE audios (36 s, 28 s, 47 s, 18 s)
Same palette in each: low drone, sparse muted piano, bowed strings, sub bass, faint music box. Models: Stable Audio 3, ACE-Step.

### C2a. Scene 5 The Voice, 36 s
<!-- RUNS:C2a -->
Group key `c7ee17db135ac803`, triggered 2026-10-23T14:01:54+00:00. In the Music Lab, look for the group whose description starts with `[C2a]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 27 | stable-audio-3 | 1717 | succeeded | 36.0 |  |
| 28 | ace-step-1.5 | 1717 | succeeded | 36.0 |  |
<!-- /RUNS:C2a -->
### C2b. Scene 6 The Records, 28 s
<!-- RUNS:C2b -->
Group key `5c2e9bf2670141e5`, triggered 2026-10-23T14:01:54+00:00. In the Music Lab, look for the group whose description starts with `[C2b]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 29 | stable-audio-3 | 1717 | succeeded | 28.0 |  |
| 30 | ace-step-1.5 | 1717 | succeeded | 28.0 |  |
<!-- /RUNS:C2b -->
### C2c. Scene 7 The Staircase, 47 s
<!-- RUNS:C2c -->
Group key `b009df9591822547`, triggered 2026-10-23T14:01:54+00:00. In the Music Lab, look for the group whose description starts with `[C2c]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 31 | stable-audio-3 | 1717 | succeeded | 47.0 |  |
| 32 | ace-step-1.5 | 1717 | succeeded | 47.0 |  |
<!-- /RUNS:C2c -->
### C2d. Scene 8 The Final Truth, 18 s
<!-- RUNS:C2d -->
Group key `a3e9801974d43047`, triggered 2026-10-23T14:01:54+00:00. In the Music Lab, look for the group whose description starts with `[C2d]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 33 | stable-audio-3 | 1717 | succeeded | 18.0 |  |
| 34 | ace-step-1.5 | 1717 | succeeded | 18.0 |  |
<!-- /RUNS:C2d -->

- For each clip: is its emotion clearer than the same stretch of C1? Notes:
- Does the palette stay the same across the four clips (same world)? Notes:
- Would the four clips cut together back to back, or do they feel like four different pieces? Notes:
- Do the clips end where the scene ends (for example the cut at the end of C2c)? Notes:
- Overall: one long piece (C1) or separate pieces (C2), which is better and why? Notes:

## C3. English03, 40 s with three emotions
Cues: 0:00-0:14 cozy and silly. 0:14-0:30 mock-classroom tension. 0:30-0:40 comic deflation. Models: Stable Audio 3, ACE-Step.
<!-- RUNS:C3 -->
Group key `791353a7c7e39368`, triggered 2026-10-23T14:01:54+00:00. In the Music Lab, look for the group whose description starts with `[C3]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 35 | stable-audio-3 | 1717 | succeeded | 40.0 |  |
| 36 | ace-step-1.5 | 1717 | succeeded | 40.0 |  |
<!-- /RUNS:C3 -->
- Are the three parts distinct? Notes:
- Does the comic timing come through (the deflation especially)? Notes:
- Do the changes land near 0:14 and 0:30? Notes:

---

# D. Songs

## D1. English03 jingle, about 35 s, lyrics given
Models: ACE-Step (110 BPM, C major, 35 s fixed), YuE2.
<!-- RUNS:D1 -->
Group key `b24eeb43c734b9fa`, triggered 2026-10-23T14:03:07+00:00. In the Music Lab, look for the group whose description starts with `[D1]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 37 | ace-step-1.5 | 1717 | succeeded | 35.0 |  |
| 38 | yue2 | 1717 | succeeded | 21.3 |  |
<!-- /RUNS:D1 -->
- Are all the words sung correctly? Mark any wrong or missing line. Notes:
- Are "fewer" and "less" clear and not mixed up? Notes:
- Playful and cheeky, or flat? Notes:
- Length against 35 s (ACE fixed it, YuE2 follows the lyrics). Notes:

## D2. Arjun, the mother's lullaby in English
Models: ACE-Step (60 BPM, A minor, 3/4, length left to the model), YuE2.
<!-- RUNS:D2 -->
Group key `7ae8d2341f9901a3`, triggered 2026-10-23T14:03:07+00:00. In the Music Lab, look for the group whose description starts with `[D2]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 39 | ace-step-1.5 | 1717 | succeeded | 95.0 |  |
| 40 | yue2 | 1717 | succeeded | 115.8 |  |
<!-- /RUNS:D2 -->
- Is the voice female, soft and breathy? Notes:
- Tender but unsettling: creepy, or merely sad? Notes:
- Word accuracy against the lyrics. Notes:
- Does it feel like a lullaby (slow, waltz feel)? Notes:

## D3. The lullaby in Hindi (ACE only)
The Hindi lyrics were drafted by the assistant and not checked by a native speaker, so judge the wording as well as the singing.
<!-- RUNS:D3 -->
Group key `7a6ffe0c4b96ce20`, triggered 2026-10-23T14:03:07+00:00. In the Music Lab, look for the group whose description starts with `[D3]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 41 | ace-step-1.5 | 1717 | succeeded | 80.0 |  |
<!-- /RUNS:D3 -->
- Is it really sung in Hindi? Notes:
- Pronunciation: natural, or accented or garbled? Notes:
- Do the words make sense and fit a lullaby? Notes:
- Same emotion as the English version (D2)? Notes:

## D4a, D4b, D4c. First Light anthem, three ways
Same lyrics and style. D4a: ACE with 84 BPM, D major, 4/4 and 75 s fixed. D4b: ACE with nothing fixed, so it plans its own. D4c: YuE2 with "84 BPM" in the style line.

### D4a. ACE, everything fixed
<!-- RUNS:D4a -->
Group key `2870b2ce7b9d15aa`, triggered 2026-10-23T14:03:07+00:00. In the Music Lab, look for the group whose description starts with `[D4a]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 42 | ace-step-1.5 | 1717 | succeeded | 75.0 |  |
<!-- /RUNS:D4a -->
### D4b. ACE, planned by the model
<!-- RUNS:D4b -->
Group key `b1d2bee52958c69e`, triggered 2026-10-23T14:03:07+00:00. In the Music Lab, look for the group whose description starts with `[D4b]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 43 | ace-step-1.5 | 1717 | succeeded | 170.0 |  |
<!-- /RUNS:D4b -->
### D4c. YuE2, tempo in the style
<!-- RUNS:D4c -->
Group key `7fc9f6992c1fb5b0`, triggered 2026-10-23T14:03:07+00:00. In the Music Lab, look for the group whose description starts with `[D4c]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 44 | yue2 | 1717 | succeeded | 133.6 |  |
<!-- /RUNS:D4c -->

- Tempo of each, tapped. Does D4a hit 84 and does D4c follow "84 BPM"? Notes:
- Key of D4a (D major)? Notes:
- Length of each against 75 s. Do the lyrics fit D4a's 75 s, or is it squeezed or padded? Notes:
- Does the emotion shift from a quiet verse to a soaring chorus in each? Notes:
- Does fixing the values (D4a) beat letting the model plan (D4b)? Notes:

## D5. 6Fingers counting song, 30 s
Models: ACE-Step (120 BPM, G major, 30 s), YuE2.
<!-- RUNS:D5 -->
Group key `eaf72f97d78f9212`, triggered 2026-10-23T14:03:07+00:00. In the Music Lab, look for the group whose description starts with `[D5]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 45 | ace-step-1.5 | 1717 | succeeded | 30.0 |  |
| 46 | yue2 | 1717 | succeeded | 27.5 |  |
<!-- /RUNS:D5 -->
- Can you clearly hear "one, two, three, four, five" and then the "six" twist? Notes:
- Does the joke land? Notes:
- Length against 30 s. Notes:

---

# E. Sound effects (Stable Audio Open, Stable Audio 3, LTX audio, same description)

For each, also note: which model is best, and whether any model made music instead of an effect.

## E1. Ceiling footsteps, 8 s
Pattern: thump, pause, thump, pause, three quick thumps.
<!-- RUNS:E1 -->
Group key `633164bdae61790e`, triggered 2026-10-23T14:05:41+00:00. In the Music Lab, look for the group whose description starts with `[E1]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 47 | stable-audio-open | 1717 | succeeded | 8.0 |  |
| 48 | stable-audio-3 | 1717 | succeeded | 8.0 |  |
| 49 | ltx-audio | 1717 | succeeded | 8.0 |  |
<!-- /RUNS:E1 -->
- Does the rhythm follow the pattern exactly? Notes:
- Do they sound like footsteps on a ceiling (muffled, wood)? Notes:

## E2. Exactly three knocks, 4 s (smoke test)
<!-- RUNS:E2 -->
Group key `55adb9caf8d499af`, triggered 2026-10-23T13:43:56+00:00. In the Music Lab, look for the group whose description starts with `[E2]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 4 | stable-audio-open | 1717 | succeeded | 4.0 |  |
| 5 | stable-audio-3 | 1717 | succeeded | 4.0 |  |
| 6 | ltx-audio | 1717 | succeeded | 4.0 |  |
<!-- /RUNS:E2 -->
- Count the knocks for each model. Notes:
- Evenly spaced, with silence between? Notes:

## E3. Heavy object dragged across the ceiling, 6 s
<!-- RUNS:E3 -->
Group key `a177ce177becd583`, triggered 2026-10-23T14:05:41+00:00. In the Music Lab, look for the group whose description starts with `[E3]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 50 | stable-audio-open | 1717 | succeeded | 6.0 |  |
| 51 | stable-audio-3 | 1717 | succeeded | 6.0 |  |
| 52 | ltx-audio | 1717 | succeeded | 6.0 |  |
<!-- /RUNS:E3 -->
- Does it sound like dragging (a long scrape), or just a thud or noise? Notes:

## E4. Phone rings twice, then static, 8 s
<!-- RUNS:E4 -->
Group key `ccc1c7ba2c01ea74`, triggered 2026-10-23T14:05:41+00:00. In the Music Lab, look for the group whose description starts with `[E4]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 53 | stable-audio-open | 1717 | succeeded | 8.0 |  |
| 54 | stable-audio-3 | 1717 | succeeded | 8.0 |  |
| 55 | ltx-audio | 1717 | succeeded | 8.0 |  |
<!-- /RUNS:E4 -->
- Exactly two rings? Notes:
- Static after the rings, in that order? Notes:

## E5. Comic "dun dun" sting, 3 s
<!-- RUNS:E5 -->
Group key `432b107379dc9df0`, triggered 2026-10-23T14:05:41+00:00. In the Music Lab, look for the group whose description starts with `[E5]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 56 | stable-audio-open | 1717 | succeeded | 3.0 |  |
| 57 | stable-audio-3 | 1717 | succeeded | 3.0 |  |
| 58 | ltx-audio | 1717 | succeeded | 3.0 |  |
<!-- /RUNS:E5 -->
- Two hits? Is it funny and cartoonish, or a real dramatic hit? Notes:

## E6. Marker squeak, then chip crunch, 5 s
<!-- RUNS:E6 -->
Group key `a381d3315dff580a`, triggered 2026-10-23T14:05:41+00:00. In the Music Lab, look for the group whose description starts with `[E6]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 59 | stable-audio-open | 1717 | succeeded | 5.0 |  |
| 60 | stable-audio-3 | 1717 | succeeded | 5.0 |  |
| 61 | ltx-audio | 1717 | succeeded | 5.0 |  |
<!-- /RUNS:E6 -->
- Both sounds present and in the right order? Notes:
- Is the crunch recognisable as a chip? Notes:

---

# F. Ambience (LTX audio, Stable Audio Open, Stable Audio 3, same description)

## F1. Arjun's bedroom at 2:17 AM, 20 s, under narration
<!-- RUNS:F1 -->
Group key `66c5a742c22b2223`, triggered 2026-10-23T14:13:28+00:00. In the Music Lab, look for the group whose description starts with `[F1]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 62 | ltx-audio | 1717 | succeeded | 20.0 |  |
| 63 | stable-audio-open | 1717 | succeeded | 20.0 |  |
| 64 | stable-audio-3 | 1717 | succeeded | 20.0 |  |
<!-- /RUNS:F1 -->
- Uneasy and cold? Quiet enough to sit under a voice? Notes:
- Do the clock tick, creaks and city hum appear? Notes:

## F2. English03 sunny living room, 20 s
<!-- RUNS:F2 -->
Group key `586185139cb6f58e`, triggered 2026-10-23T14:13:28+00:00. In the Music Lab, look for the group whose description starts with `[F2]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 65 | ltx-audio | 1717 | succeeded | 20.0 |  |
| 66 | stable-audio-open | 1717 | succeeded | 20.0 |  |
| 67 | stable-audio-3 | 1717 | succeeded | 20.0 |  |
<!-- /RUNS:F2 -->
- Cheerful and calm, birds and clock present? Notes:

## F3. Burning building outside the window, 30 s
<!-- RUNS:F3 -->
Group key `2002611c86d2fc58`, triggered 2026-10-23T14:13:29+00:00. In the Music Lab, look for the group whose description starts with `[F3]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 68 | ltx-audio | 1717 | succeeded | 30.0 |  |
| 69 | stable-audio-open | 1717 | succeeded | 30.0 |  |
| 70 | stable-audio-3 | 1717 | succeeded | 30.0 |  |
<!-- /RUNS:F3 -->
- Does the sound GROW over the 30 s as asked (fire closer, sirens rising)? Notes:
- Are the sources recognisable (fire roar, crackle, glass, sirens)? Notes:

## F4. First Light, abstract deep-space hum, 30 s
<!-- RUNS:F4 -->
Group key `e3eed9584fe8dac0`, triggered 2026-10-23T14:13:29+00:00. In the Music Lab, look for the group whose description starts with `[F4]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 71 | ltx-audio | 1717 | succeeded | 30.0 |  |
| 72 | stable-audio-open | 1717 | succeeded | 30.0 |  |
| 73 | stable-audio-3 | 1717 | succeeded | 30.0 |  |
<!-- /RUNS:F4 -->
- Abstract and vast, with no earthly sound or musical melody? Notes:
- Does it evolve slowly, or is it static? Notes:

---

# G. Stems (Stable Audio 3, ACE-Step)

For all three: is it really ONE instrument with no backing, no drums, no pads?

## G1. Music-box lullaby motif, 20 s
<!-- RUNS:G1 -->
Group key `1e3dfa320b5ad4ea`, triggered 2026-10-23T14:20:54+00:00. In the Music Lab, look for the group whose description starts with `[G1]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 74 | stable-audio-3 | 1717 | succeeded | 20.0 |  |
| 75 | ace-step-1.5 | 1717 | succeeded | 20.0 |  |
<!-- /RUNS:G1 -->
- Music box only? Simple, haunting, slightly detuned? Notes:

## G2. Solo piano of wonder, 30 s
<!-- RUNS:G2 -->
Group key `55eb053ee99af8ab`, triggered 2026-10-23T14:20:54+00:00. In the Music Lab, look for the group whose description starts with `[G2]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 76 | stable-audio-3 | 1717 | succeeded | 30.0 |  |
| 77 | ace-step-1.5 | 1717 | succeeded | 30.0 |  |
<!-- /RUNS:G2 -->
- Piano only? Gentle and wondering, rising? Notes:

## G3. Pizzicato strings, sneaky, 15 s
<!-- RUNS:G3 -->
Group key `fabd4d8c604056aa`, triggered 2026-10-23T14:20:54+00:00. In the Music Lab, look for the group whose description starts with `[G3]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 78 | stable-audio-3 | 1717 | succeeded | 15.0 |  |
| 79 | ace-step-1.5 | 1717 | succeeded | 15.0 |  |
<!-- /RUNS:G3 -->
- Strings only? Does it sound sneaky and tiptoeing? Notes:

---

# H. Consistency and the AI prompt writer

## H1a. Same fields, three seeds (A2 fields, Stable Audio 3, seeds 1718 to 1720)
<!-- RUNS:H1a -->
Group key `9c9dd9c5f66cee4c`, triggered 2026-10-23T14:24:48+00:00. In the Music Lab, look for the group whose description starts with `[H1a]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 80 | stable-audio-3 | 1718 | succeeded | 60.0 |  |
| 81 | stable-audio-3 | 1719 | succeeded | 60.0 |  |
| 82 | stable-audio-3 | 1720 | succeeded | 60.0 |  |
<!-- /RUNS:H1a -->
- How different are the three takes (structure, instruments, mood)? Notes:
- Equally good, or is there one clear winner? Notes:
- Compare with the A2 run at seed 1717. Notes:

## H1b. Repeat of B1 on Stable Audio 3 with seed 1717
<!-- RUNS:H1b -->
Group key `97cdb7d0aaaedd54`, triggered 2026-10-23T14:24:48+00:00. In the Music Lab, look for the group whose description starts with `[H1b]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 83 | stable-audio-3 | 1717 | succeeded | 60.0 |  |
<!-- /RUNS:H1b -->
- Is it identical to the first B1 Stable Audio 3 run, or different? (Same seed and same prompt.) Notes:

## H2. AI prompt writer drafts the A2 brief
The app's writer wrote the fields for Stable Audio 3 and ACE-Step from the A2 brief. The warnings it raised are in the run table.
<!-- RUNS:H2 -->
Group key `9e0087a4b5418304`, triggered 2026-10-23T14:25:00+00:00. In the Music Lab, look for the group whose description starts with `[H2]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 84 | stable-audio-3 | 1717 | succeeded | 60.0 |  |
| 85 | ace-step-1.5 | 1717 | succeeded | 60.0 |  |

Prompt draft for stable-audio-3 (job 3147), warnings: none

Prompt draft for ace-step-1.5 (job 3148), warnings: none
<!-- /RUNS:H2 -->
- Better, worse or the same as the hand-written A2? Notes:
- Open "What was sent": is the prompt sensible, and is the length right? Notes:
- Are the writer's warnings fair? Notes:

## H3. Prompt writer writes the lullaby lyrics from a theme
The writer wrote the lyrics and style for ACE-Step and YuE2 from a theme only.
<!-- RUNS:H3 -->
Group key `01a501f3e88e079b`, triggered 2026-10-23T14:25:12+00:00. In the Music Lab, look for the group whose description starts with `[H3]`.

| Run | Model | Seed | Status | Length (s) | Error |
| --- | --- | --- | --- | --- | --- |
| 86 | ace-step-1.5 | 1717 | succeeded | 195.0 |  |
| 87 | yue2 | 1717 | succeeded | 185.0 |  |

Prompt draft for ace-step-1.5 (job 3151), warnings: none

Prompt draft for yue2 (job 3152), warnings: none
<!-- /RUNS:H3 -->
- Quality of the lyrics against the hand-written D2 lyrics. Notes:
- Do the lyrics keep the "tender but unsettling" feeling and hide the secret? Notes:
- Is it sung as written, and are the section tags used well? Notes:

---

# Conclusions (to fill in together after listening)

- Best model per kind (score, song, stem, sound effect, ambience):
- How strictly timestamps and durations are followed (B1, B2, B3, B4), and which model is most reliable:
- One long track against several per-scene tracks (C1 against C2):
- Songs: ACE-Step against YuE2, fixed settings against planned, Hindi quality:
- Sound effect counts and ordering (E1 to E6): which model can be trusted:
- Prompt writer against hand-written prompts (H2, H3):
- Seed consistency (H1):
- Changes to make to the pipeline or to the prompt profiles:
