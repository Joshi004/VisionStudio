# Editing craft for inserting real-world sound bites into AI-narrated explainer videos

Scope: short (3–15 s) clips of a real person speaking (YouTube interviews, keynotes, news footage) placed inside a narrated explainer (AI narrator + on-screen AI presenter, B-roll, motion graphics, burned-in captions, ducked music). The goal is defaults an FFmpeg + Remotion pipeline can use.

How much to trust the sources:
- **Primary or authoritative:** Netflix Partner Help / Studio Partner specs, EBU R 128 and Tech 3343, W3C WAI, BBC Subtitle Guidelines, BBC Editorial Guidelines, NPR Ethics Handbook and NPR Training, DCMP Captioning Key, FCC, Walter Murch (*In the Blink of an Eye*), and iZotope (vendor docs, but the industry tool).
- **Low-authority practitioner, vendor or content-marketing blogs:** nolanlabs, valmera, videocue, kookenhoomen, tunaryinstruments, addaly, pristinepodcasts, tryuncle, crilly, make-vertical, trezalabs, lunarclip, fullsendagency, editingluke, yasserashour, jeffapierson, audiodrome, umbrellacreators, loudmeter. Several are dated 2026 and some say outright that their numbers are "our judgment". Numbers from these sources are labelled **[common practice, low-authority]** and should be treated as starting values, not standards.
- **Labels used below:** "[sourced]" means it comes from a primary or authoritative source. "[inference]" means it is my own reasoning.

---

## 1. Audio transitions: J-cuts, L-cuts, pauses, crossfades, room tone

### Takeaway
No broadcaster publishes a fixed split-edit length. Practitioner ranges agree on these starting points:
- About 6–14 frames at 24 fps (0.25–0.6 s) to soften a dialogue cut.
- About 0.5–1.5 s when going into or out of an interview over B-roll.

Splits should be used on only some cuts, never while a mouth is still moving on screen, and never so that two voices overlap. Room tone or matched ambience under and around a bite is what hides the seam.

### Cited Findings
- **Definition [common practice, low-authority]:** A J-cut starts the next shot's sound before its picture; an L-cut carries the last shot's sound over the next picture. Starting ranges at 24 fps (multiply by 1.25 for 30 fps):
  - Softening a cut between two speakers: J-cut, 6–14 frames (0.25–0.58 s).
  - Going to the listener before the line ends: L-cut, 8–24 frames (0.33–1 s).
  - Interview into or out of B-roll: 12–36 frames (0.5–1.5 s).
  - Fast social cuts: 2–4 frames, "often none at all".
  - The source says explicitly that these "aren't a standard or a measurement". — [nolanlabs](https://nolanlabs.io/blog/j-cut-and-l-cut)
- **When not to split [common practice, low-authority]:** keep cuts straight on "punchlines and sync hits", and never "when a mouth is still moving" (lips moving under someone else's voice). "When the rooms don't match… add a fade or fill, or don't [split]." — [nolanlabs](https://nolanlabs.io/blog/j-cut-and-l-cut)
- **Secondhand references, cited via nolanlabs:**
  - Blackmagic's *Editor's Guide to DaVinci Resolve 20* rolls a landscape-to-interview picture cut by about 15 frames.
  - Murch told Steve Hullfish that the cut point is generally "a frame or two before an actor… blinks". — [nolanlabs](https://nolanlabs.io/blog/j-cut-and-l-cut)
- **More ranges [common practice, low-authority]:** 6–12 frames (0.2–0.4 s) for a quick hand-off; 0.5–2 s for a normal dialogue split. "Under about four frames the offset does not register as a split edit." The overlap must end "before the viewer starts searching the frame for whoever is talking." — [Valmera](https://valmera.io/glossary/j-cut-and-l-cut)
- **Ranges by type and frequency [common practice, low-authority]:**
  - Dialogue J-cuts: 6–18 frames (0.25–0.75 s). Dialogue L-cuts: 12–36 frames (0.5–1.5 s).
  - Music bridges: 1–3 s. Ambience bridges: 1.5–4 s.
  - Use split edits on "roughly 30–50% of dialogue cuts, not all of them"; applying them everywhere flattens the rhythm.
  - Don't split when the reveal of a face should land on the visual.
  - — [VideoCue](https://videocue.io/guides/the-j-cut-and-the-l-cut)
- **Cut points [common practice, low-authority]:**
  - A transient is "the first 5 to 20 milliseconds of a sound"; a breath is "200 to 600 milliseconds of air before a phrase". Both are better cut points than the frame where a mouth opens.
  - Same speaker, continuing thought: cut 2 frames before the transient of the incoming word.
  - Speaker change: cut on the outgoing speaker's breath, 1–2 frames after the last consonant.
  - Reaction shots: 4–6 frames after the line ends.
  - "More than 8 frames of audio tail and the two speakers start talking over each [other]."
  - — [kookenhoomen](https://kookenhoomen.com/motion/cut-the-sequence-on-the-sound/)
- **Room tone [sourced, iZotope]:**
  - "When room tone suddenly goes missing, the brain notices. It becomes clear that the performance was artificially edited."
  - Laying room tone under audio recorded in a different session helps disguise the edit. Recommended capture is 30–60 s of room tone.
  - If none was recorded, RX Ambience Match can synthesise matching ambience, which can be rendered onto silence and laid behind lines.
  - — [iZotope: Basics of Room Tone](https://www.izotope.com/community/blog/basics-of-room-tone-audio-editing)
- **Ambience Match limits [sourced, iZotope]:** Static mode suits steady room tone; Complex mode suits moving ambience. Ambience Match "cannot reduce the amount of ambience that already exists… it can only increase it". To reduce ambience, use Spectral De-noise. — [iZotope RX 10 Help: Ambience Match](https://docs.izotope.com/rx10/en/ambience-match/index.html)
- **Reality-TV mixer Koch on Frankenbites [sourced, trade press]:** "Then, to further help the transition between the edits, Koch layers ambience from the vérité segments underneath the interview bites." — [postPerspective / iZotope](https://postperspective.com/emails/iZotope/ppnews-iZotope-161004.html)
- **Handles [sourced, school broadcast guide]:** "Leave a little extra picture and sound before and after the chosen words when editing." No number is given. — [Bellville AV: Write the Video Package Script](https://bellvilleav.com/wp-content/uploads/2026/09/Section-4-Write-the-Video-Package-Script.pdf)

### Inferences
- **No voice overlap [inference]:** In a narrated explainer, narrator and bite must never overlap as voices. Split edits should overlap picture with silence, room tone or breath, not narrator speech with clip speech. Treat the "mouth still moving" rule as a hard constraint: the clip's picture must not appear while the narrator is still talking *and* the clip speaker's lips are visibly moving.
- **Picture-first entry, an L-cut of the narration [inference]:** Cut to the clip picture 6–12 frames (about 0.2–0.4 s) *before* the clip speaker's first word. The narrator's last syllable or breath can finish over the clip picture while the speaker is not yet talking. This lets the viewer see the face before the voice arrives, which helps identification.
- **Sound-first entry, a J-cut of the clip [inference]:** The clip's own room tone or breath can start 4–8 frames before its picture, for continuity, provided the narrator has finished.
- **Exit [inference]:** Let clip room tone tail 6–12 frames after the last word, then cut back to the presenter or B-roll. Optionally hold the clip picture 0.3–0.5 s after the last word as a "beat" (consistent with Editing Luke's "held cut", Section 3) before the narrator resumes.
- **Edge fades [inference, not sourced]:** Apply short fades to clip audio edges (about 10–30 ms afade in/out) to avoid clicks. Use a longer fade (about 100–250 ms) only on the room-tone portion, never across a word. Hard cuts at word boundaries are normal in dialogue editing; crossfades are mainly for ambience.
- **Room tone bed [inference]:** Generate or extract room tone from the clip's own pauses and extend it 0.25–0.5 s on both sides under the transition. This avoids the noise floor "switching on and off" at the clip boundaries.
- **Frame equivalents [inference]:** At 30 fps, 6–14 frames ≈ 200–470 ms; at 25 fps ≈ 240–560 ms.

### Gaps
- I found no broadcaster standard (BBC, NPR, PBS, CBC) specifying milliseconds of pause before or after a sound bite. All ms values above are practitioner ranges.
- I did not find the Blackmagic Resolve 20 guide or the Murch/Hullfish interview directly; both are cited secondhand via nolanlabs.

---

## 2. Loudness and tone matching of clip audio vs narration

### Takeaway
Normalise both narration and bite to the same dialogue loudness, and match EQ and ambience to the narration as the reference.
- **YouTube:** −14 LUFS integrated is an observed, unofficial reference, with true peak ≤ −1 dBTP. YouTube turns loud audio down but does not turn quiet audio up.
- **Netflix:** dialogue-gated −27 LKFS ±2 LU, true peak ≤ −2 dBTP.
- **EBU R128:** −23 LUFS, true peak ≤ −1 dBTP.

Clean bad clip audio first (de-noise, de-reverb), then match. Don't over-clean; some degradation is acceptable and even signals authenticity.

### Cited Findings
- **Netflix sound mix spec [sourced]:** "Set average loudness at -27 LKFS with a tolerance of ±2 LU, dialog-gated. Peaks must not exceed -2dB True Peak," measured over the full programme per ITU-R BS.1770-1. — [Netflix Sound Mix Specifications](https://studiopartner.netflix.net/studio/branded-sound-mix-spec-and-best-practices)
- **Netflix QC thresholds [sourced]:**
  - Dialogue-gated: −27 LKFS ±3. Full-programme BS.1770-4: −24 LKFS ±3.
  - Short-term window 3 s; true-peak threshold −2 dBFS.
  - — [Netflix: Loudness and True Peaks](https://studiopartner.netflix.net/studio/loudness-and-true-peaks-how-to-measure-and-when-to-flag)
- **Why Netflix gates on dialogue [sourced, trade press]:** "Dialogue is the anchor element of a Netflix mix… The meter will judge what is dialogue and it will not measure sound effects and music." — [Production Expert](https://www.production-expert.com/production-expert-1/how-to-optimise-an-audio-mix-for-delivery-to-netflix)
- **EBU R 128 [sourced]:**
  - Programme loudness −23.0 LUFS. Tolerance ±1.0 LU where exact targeting isn't practical (live); ±0.2 LU in QC workflows.
  - True peak must not exceed −1 dBTP. Measured "without emphasis on specific foreground elements such as speech".
  - — [EBU R 128 v5 (2023)](https://tech.ebu.ch/docs/r/r128v5_0.pdf)
- **EBU Tech 3343 [sourced]:**
  - Meter time scales: Momentary 400 ms, Short-term 3 s, Integrated.
  - For short-form content under 60 s, Max Short-term Loudness of −18 LUFS (+5 LU) is recommended.
  - — [EBU Tech 3343 v4.1](https://tech.ebu.ch/docs/tech/tech3343v4_1.pdf)
- **YouTube does not publish a target [sourced via third parties; conflict noted]:**
  - The −14 LUFS figure is an observation from the "Stats for nerds" content-loudness readout (MeterPlugs, 2019).
  - YouTube turns loud videos down and does not turn quiet ones up.
  - "Stable volume" is on by default for many viewers and changes dynamics within a video.
  - — [lufsready](https://lufsready.com/blog/loudness-normalization-explained); [Production Advice (2017)](https://productionadvice.co.uk/stats-for-nerds/); [loudmeter](https://www.loudmeter.net/youtube-loudness)
- **Spot check of big channels [low-authority]:**
  - Wendover Productions measured −24.3 LUFS and Veritasium −13.2. The median of 50 big-channel videos was −16.3 LUFS.
  - The DaVinci Resolve manual is quoted as stating "the YouTube target LUFS specification is -14 LUFS".
  - — [umbrellacreators](https://umbrellacreators.com/blog/how-to-normalize-audio-for-youtube)
- **Podcast and other delivery norms [common practice, low-authority]:**
  - Podcast: −16 LUFS stereo / −19 LUFS mono. US broadcast: −24 LKFS (ATSC A/85).
  - A mix made at −23 and uploaded to YouTube effectively plays about 9 dB quieter than −14 content.
  - — [tunaryinstruments](https://tunaryinstruments.com/guides/mixing-music-under-dialogue/)
- **Matching workflow from a professional reality/doc mixer [sourced, trade press]:**
  - "I strive to match all dialogue to the quality of the studio interviews. I use that as my baseline."
  - Order of steps: Dialog De-noise each vérité clip, then De-reverb, then De-crackle (wind/rustle), then EQ Match, then levels.
  - Retain "as much robustness and low-end as possible while cleaning up the vérité clips"; "sometimes… you may have to degrade the interview dialogue to make it sound like it was recorded in the vérité environment."
  - EQ Match can also compensate for compression or mic-distance differences.
  - — [postPerspective / iZotope](https://postperspective.com/emails/iZotope/ppnews-iZotope-161004.html)
- **Clean before matching [sourced, iZotope]:** "noises in, noises out". Clean noisy audio before running Dialogue Match, which learns EQ, reverb and ambience profiles. — [iZotope: Dialogue Editing Workflow](https://www.izotope.com/community/blog/the-dialogue-editing-workflow)
- **Spectral De-noise [sourced, iZotope]:** learns from a section of pure background noise; use smaller selections when the noise changes. — [iZotope: Repair a Compressed or Noisy Interview](https://www.izotope.com/community/blog/tips-to-repair-a-compressed-or-noisy-interview)

### Inferences
- **Loudness target [inference]:** Normalise each bite so its speech-gated loudness matches the narrator's speech loudness within ±1 LU. Use EBU R128's ±1 LU tolerance as the analogue; the "no jarring jump" threshold is a judgement. In FFmpeg, measure with `ebur128`/`loudnorm` (two-pass) on the bite's speech-only region, then apply static gain. Don't run dynamic loudnorm on a 5 s clip; gain jumps would be audible.
- **Final mix target for YouTube [inference]:** Master the final mix to about −14 LUFS integrated, true peak −1 dBTP, for both landscape and Shorts. The alternative is −16 LUFS for more headroom, accepting slightly quieter playback. Pick one house value; consistency matters more than the exact number.
- **Bad audio chain [inference]:**
  1. High-pass at about 80–100 Hz to remove rumble.
  2. Gentle FFT de-noise (FFmpeg `afftdn`, or an offline ML denoiser) with conservative reduction.
  3. Optional low-pass at about 8–12 kHz for very hissy old footage.
  4. Light compression so peaks don't exceed narration peaks.
- **Don't over-clean [inference]:** Phone or old footage can stay audibly "archival", which is honest and expected. Over-denoising produces watery artefacts that are worse than hiss. Koch's "retain robustness and low-end" supports this.
- **Where the line falls [inference]:** Match level and roughly match tonal balance, but do *not* try to make the clip sound like the studio narrator. Viewers accept a timbre change between narrator and real-world clip; they don't accept a loudness jump.
- **Burned-in clip audio [inference]:** If the clip has music or crowd noise baked in, treat it as the bite's "ambience" and fade it in and out over about 100–250 ms at the edges.

### Gaps
- I found no published dB figure for how much tonal mismatch audiences tolerate between narrator and archival clip.
- YouTube's internal measurement (gated or not, dialogue-weighted or not) is undocumented.
- I didn't verify FFmpeg `loudnorm` default parameter values, so check them against current FFmpeg docs before relying on defaults.

---

## 3. Music behaviour under a sound bite

### Takeaway
Typical duck under speech is about 12–18 dB, and about 15–20 dB below the voice for dense narration. W3C recommends background at least 20 dB below foreground speech. Duck attack and release are reported as about 10–30 ms / 300–600 ms, or a manual move beginning about 200 ms before speech.

For key bites, a recognised technique is to drop the music entirely: cut a beat before the line, add a reverb tail on the cut, sometimes a riser, let the bite play clean, then bring the music back on the line's end. Silence, or room tone only, marks importance.

### Cited Findings
- **W3C WAI [sourced]:** "Make the background sounds at least 20 decibels lower than the foreground speech content (with the exception of occasional sounds that last for only one or two seconds)." — [W3C WAI: Audio and Video Content](https://www.w3.org/WAI/media/av/av-content/)
- **WCAG G56 [secondhand]:** "Making sure that the foreground speech is 20 db louder than the backgound sound makes the speech 4 times louder." — quoted in [tryuncle](https://tryuncle.com/learn/davinci-resolve/how-to-duck-background-music-under-dialogue-in-davinci-resolve)
- **Duck amounts by use case [common practice, low-authority]:**

  | Use case | Duck | Rise | Recovery |
  | --- | --- | --- | --- |
  | General YouTube | 12–18 dB | 100–300 ms | 300–600 ms |
  | Explainer, dense narration | 15–20 dB | 100–200 ms | 200–400 ms |
  | Cinematic | 6–12 dB with manual keyframes | — | — |

  — [tryuncle](https://tryuncle.com/learn/davinci-resolve/how-to-duck-background-music-under-dialogue-in-davinci-resolve)
- **Sidechain settings and level targets [common practice, low-authority]:**
  - Sidechain duck: ratio 2:1–4:1, attack 10–30 ms, release 300–800 ms, depth limited to 6–9 dB, sidechain high-passed at about 200 Hz.
  - Bed target: music 15–20 dB below dialogue. For a −16 LUFS programme, the bed under speech is about −30 to −34 LUFS short-term, rising to about −18 in gaps.
  - Manual automation "begins the move 200ms early, over half a second", which avoids pumping.
  - Speech intelligibility lives at about 1–4 kHz; choose music with sparse midrange.
  - — [addaly](https://addaly.com/learn/motion-and-audio/ducking-and-beds)
- **Duck depth versus music density [common practice, low-authority]:** typical duck 10–18 dB. Sparse music: 10–12 dB. Busy drums: 15–18 dB. Music with singing: avoid, or duck 20 dB or more. Put the duck's ramp-in so it ends *before* the first word. — [jeffapierson journalism training](https://jeffapierson.com/journal_tools/training/08-audio-production/05-music-beds-and-ducking.html)
- **Keyframed duck [common practice, low-authority]:** about −10 dB. The dip starts 6 frames before speech and recovers over 12 frames after; gaps under 12 frames are treated as continuous speech. — [yasserashour](https://www.yasserashour.com/directors-notes/master-guide/sound-design/the-mix-with-speech-as-the-anchor)
- **Lighter duck view [common practice, low-authority]:** "3 to 6 dB of reduction is plenty. If it needs 12, the music is simply too loud or too busy"; music typically sits 12–18 dB below dialogue "when the words matter". This conflicts with the 12–18 dB *duck* figures above. The difference is whether the bed is pre-set low (small duck) or loud (big duck). — [tunaryinstruments](https://tunaryinstruments.com/guides/mixing-music-under-dialogue/)
- **"Impact moment" [common practice, low-authority, brand-video agency]:** "Right before the powerful soundbite lands, the music cuts out. A polished reverb tail is added on the cut… A riser builds tension into the drop. The soundbite plays clean… Then the music slams back in hard the instant the line concludes." The source recommends two or three of these per video. — [Full Send](https://fullsendagency.co/blog/how-music-editing-in-a-brand-video-actually-works)
- **Silence for emphasis [common practice, low-authority]:** "pulling the music out entirely under a critical line of dialogue so the words land without competition"; "dropping to pure room tone signals to the viewer that something different is happening"; hold the speaker "an extra beat after they've stopped talking". — [Editing Luke](https://www.editingluke.net/breathing-room-editors-embrace-silence/)
- **Pull music back on the key line [common practice, low-authority]:** "Pull the music back when the speaker gives the key line"; avoid "dramatic rises under important answers". — [audiodrome](https://audiodrome.net/use-cases/music-for-interview-documentaries/)

### Inferences
- **Two modes per bite [inference]:**
  - **(a) Standard bite:** keep the bed but duck deeper than under narration, by about an extra 3–6 dB. The target is music ≥ 20 dB below the bite's speech loudness, because clip audio is usually lower fidelity and noisier than the narrator, so masking hurts it more.
  - **(b) Key/"money" bite:** fade music out over about 300–500 ms ending about 200–400 ms before the first word, leaving clip room tone only. Restart the music 0–300 ms after the last word, on the next narrator phrase or a musical downbeat.
  - Cap mode (b) at about 2–3 uses per 10 minutes (Full Send's "two or three moments"), so it keeps its weight.
- **Music can help mismatched bites [inference]:** A steady bed partly masks the clip's noise-floor switch-on (Koch layers ambience for the same reason). That argues for mode (a) when clip audio is noisy, and mode (b) only when the clip audio is clean enough to stand alone.
- **Duck the music with keyframes, not a live sidechain [inference]:** In Remotion/FFmpeg, apply the duck with deterministic keyframes from the known bite in/out timestamps rather than a live sidechain. Ramp down starting 200 ms before the bite audio and ramp up over 300–500 ms after it. This is the "anticipating" manual move that sidechains can't do.
- **Stings [inference]:** A riser or short "whoosh"/hit 0.5–1 s before a bite is a stylistic option for high-energy channels. It isn't a norm for documentary-style explainers and should be off by default.

### Gaps
- I found no published broadcaster rule (BBC/PBS/NPR) on music under archival sound bites specifically.
- I found no measured analysis of how Vox, Johnny Harris or ColdFusion handle music under bites; observations of those channels were not gathered in this research.
- Note on WCAG SC 1.4.7 (Low or No Background Audio, AAA): per my knowledge of the criterion text (not re-fetched here), it is formally scoped to *prerecorded audio-only* content. For video, the 20 dB figure is best-practice guidance from the WAI media page rather than a binding requirement.

---

## 4. Visual treatment: full-screen vs framed, punch-ins, 9:16 reframing, styling, watermarks

### Takeaway
I found no authoritative standard for framing treatments (PiP, TV/phone frame, rounded card). These are stylistic. For vertical 9:16 from 16:9 the geometry is fixed:
- A full-height crop keeps a 608 px-wide strip, about 31.6% of a 1080p frame.
- Fitting the full frame on a blurred background fills only about 31.6% of the screen height.

Practitioner consensus: face-tracked crop for single talking heads; blurred-fill or square-on-blur when width matters or two people share the frame; avoid plain black letterboxing.

### Cited Findings
- **Crop geometry [sourced arithmetic, low-authority site]:** The largest 9:16 crop in a 1920×1080 frame keeps 656,100 of 2,073,600 px (31.6%). With a blurred background, "your video fills 31.6% of the screen height". — [make-vertical](https://make-vertical.com/en/16-9-to-9-16-converter)
- **Four methods [common practice, low-authority]:**
  - Full-frame centre crop, for a centred subject.
  - Automatic speaker tracking, for interviews.
  - Whole picture on blur, for wide shots, slides and groups; the freed space top and bottom "is the ideal place for a hook and for captions".
  - Stacked areas.
  - Tracking that jumps between faces "every two seconds is tiring".
  - — [Crilly](https://crilly.io/blog/en/vertical-9-16-framing)
- **Square on blur [common practice, low-authority]:** A square window keeps 56% of a 16:9 frame's width vs 32% for a 9:16 crop, and lets a two-shot stay a two-shot. Plain black letterboxing "looks like a repost". A 9:16 crop from 720p is only 404 px wide, so burned captions at that size look soft. — [trezalabs](https://www.trezalabs.com/blog/how-to-convert-horizontal-video-to-vertical)
- **Tracking behaviour [common practice, low-authority]:** a fixed centre crop is right for locked-off shots ("tracking adds drift with nothing to gain"). Tracking should hold steady rather than jitter; when it loses the subject it should stay put. — [lunarclip](https://lunarclip.com/guides/face-tracking-vs-fixed-crop)
- **YouTube and padding [unverified]:** A snippet states "YouTube says not to add padding or black bars to the…", but it was truncated and I couldn't confirm YouTube's exact wording. — [ClipSDK](https://clipsdk.com/guides/horizontal-to-vertical)
- **Covering edits [sourced, broadcast production guide]:** script example "Jordan on camera for first 4 seconds of SOT; add lower third… Cover remaining jump cut with matching shop B-roll." This shows the speaker's face at the start of the bite, then uses cutaways to hide internal edits. — [Bellville AV](https://bellvilleav.com/wp-content/uploads/2026/09/Section-4-Write-the-Video-Package-Script.pdf)
- **Archive must not mislead [sourced]:** "Archive material should not be used in a way that materially misleads the audience about a situation, events or the subject being depicted… where appropriate it should be made clear to audiences that the material is archive." — [BBC Editorial Guidelines, Section 3 Accuracy 3.4.32](https://www.bbc.co.uk/editorialguidelines/documents/section-3-accuracy.pdf)

### Inferences
- **Default landscape treatment [inference]:** Show the clip full-frame (16:9) for at least the first 1–2 s of the bite, so the viewer reads the face and identity. Hidden internal edits may then be covered with B-roll (see Section 7). Framed treatments are a house-style choice:
  - Rounded card about 70–85% of frame width, corner radius about 2–3% of width, soft drop shadow, over a blurred or darkened copy of the presenter scene.
  - TV/monitor frame, which signals "archival/media" and suits old news footage.
  - Phone frame, for vertical-native sources such as TikTok clips.
- **When to use a framed treatment [inference]:** use it when source resolution is low (≤ 480p), when watermarks or tickers must be hidden, or when the clip's aspect ratio differs from the canvas. Use full-frame when the source is ≥ 1080p and clean.
- **Punch-in [inference]:** A slow push (about 100% to 105–110% scale over the bite) or a single punch-in of about 115–130% on the speaker's face adds energy and hides compression artefacts at the edges. Don't punch in beyond the source's resolution headroom (for example, ≤ 1.3× on 1080p delivered at 1080p).
- **9:16 defaults [inference, from the low-authority consensus above]:**
  - Single centred speaker: face-tracked 9:16 crop, smoothed (no jumps; hold when tracking confidence is low).
  - Two people or slides: square-on-blur.
  - Fallback: full-frame-on-blur.
  - Captions go in the blurred band, not over the face.
- **Archival styling [inference]:** Add light grain or a slight desaturation *only* if the clip is genuinely old, and add a visible year label. Don't apply "archival" styling to recent footage: it would mislead about date, which runs against BBC 3.4.32 and 13.4.4.
- **Watermarks, logos, tickers and burned-in captions [inference]:** Prefer keeping source logos visible, since they serve as attribution, and frame them rather than cropping. Crop or scale only to remove tickers or burned-in captions that would collide with our own captions. Never blur out a broadcaster's logo to pass footage off as one's own. Rights and fair-use questions are out of scope here.

### Gaps
- I found no authoritative sizes for PiP or card treatments, and no measured observations of how Vox, Johnny Harris, ColdFusion, Bloomberg Originals or CNBC frame clips.
- I found no source on grain or "archival" styling parameters.
- I found no source on watermark/logo handling conventions; YouTube's own guidance wasn't confirmed.

---

## 5. Identification: lower thirds, source credits, year labels

### Takeaway
A name/title lower third conventionally appears near the start of the person's first bite and stays about 4–6 s (range 3–7 s; "read every word twice"), with two lines at most: name, then role. Archive or non-contemporaneous material should be labelled with a date or source (BBC, NPR). Don't name a speaker in captions before they've been introduced in the audio or on screen (DCMP).

### Cited Findings
- **Duration [common practice]:** "at least four seconds for a name font to register… any longer than seven seconds is too much… five or six seconds is ample." — [Hencar Productions](https://hencar.com/2015/12/what-the-font-when-to-use-onscreen-text/)
- **Read twice [common practice, Frame.io blog]:** "A good rule of thumb is to have it up long enough for the viewer to read every word twice." World-famous people may need only the name. — [Frame.io](https://blog.frame.io/2017/12/04/create-lower-thirds-titles-that-dont-suck/)
- **Typical range [common practice, low-authority]:** 3–6 s typical; up to 10 s for fact-type lower thirds. — [CutPro Media](https://cutpromedia.com/what-is-a-lower-third-and-how-to-use-it-correctly/)
- **Layout [common practice, low-authority]:** 4–6 s, "inside the bottom fifth of the frame", two lines at most: name, then role. — [Scenes](https://scenes.design/guides/lower-third-name-graphic)
- **Placement and checks [sourced, broadcast production guide]:** the lower third "should appear long enough to read, usually near the beginning of the person's first sound bite". It must not cover a face, captions or important action, and must be "short enough to read on a phone". Every spelling and title should be confirmed. — [Bellville AV](https://bellvilleav.com/wp-content/uploads/2026/09/Section-4-Write-the-Video-Package-Script.pdf)
- **Broadcast convention on introductions [common practice, low-authority]:** "There is no need to introduce anyone before the bite because you are going to have their name and title supered on the screen during the SOT." — [Quizlet SOT flashcards](https://quizlet.com/134632520/soundbites-sot-vosots-flash-cards/)
- **BBC 13.4.4 [sourced]:** "Where appropriate it should be made clear to audiences when content is not contemporaneous. Labels, first transmission dates, contextual information or other signalling may be required." — [BBC Editorial Guidelines, Section 13](https://www.bbc.com/editorialguidelines/guidelines/use-of-bbc-content-after-publication-or-broadcast/guidelines)
- **NPR [sourced]:** "When our stories include tape or material from an earlier story, we identify it as such. The listener should not be left to think that any archival or previously obtained audio was gathered in the context of the current story." — [NPR Ethics Handbook (2012)](https://current.org/wp-content/uploads/2013/01/NPR-Ethics-Handbook-5.2.2012-Final-Edition.pdf)
- **DCMP [sourced]:** "Do not identify the speaker by name until the speaker is introduced in the audio or by an onscreen text/graphic." — [DCMP Captioning Key: Speaker Identification](https://dcmp.org/learn/603-captioning-key---speaker-identification)

### Inferences
- **Lower-third timing [inference]:** Lower third in at bite start + 0.3–0.5 s (after the face has registered), visible for 4–6 s, animated in and out over about 200–300 ms each. Show it only on the person's first bite in the video; repeat bites rely on the face, plus a short name tag if more than about 2–3 minutes have passed (no source for this interval).
- **Bites shorter than about 4 s [inference]:** The lower-third minimum doesn't fit. Either (a) keep the lower third for the full bite and accept less reading time, or (b) identify the speaker in the narrator's lead-in ("As Nvidia CEO Jensen Huang put it at GTC 2024…") and show a compact name tag only.
- **Source credit [inference]:** Show a small persistent credit, for example "Source: Stanford GSB, 2024" or "via CNBC, Mar 2023", for the whole bite. Place it top-right or bottom-right at about 2–3% of frame height and 60–80% opacity, clear of the caption zone. The year satisfies BBC 13.4.4 / NPR's "identify archival material" intent. Make the date mandatory when the clip is more than about 12 months old or predates a key event in the story.
- **Combined lower third [inference]:** A practical two-line form is line 1 "Name", line 2 "Role · Venue, Year" (for example, "CEO, Nvidia · GTC keynote, 2024"). This merges identification and dating into one element and avoids clutter.

### Gaps
- I found no broadcaster style-guide numbers (BBC/CBC/PBS) for lower-third duration; the duration figures are practitioner conventions.
- I found no source on lower-third behaviour in 9:16 Shorts (safe zones for UI overlays were not researched).

---

## 6. Captions for the bite: style, speaker identification, accessibility

### Takeaway
Accessibility standards require captions to identify who is speaking (WCAG 1.2.2) and to be accurate, synchronous, complete and properly placed (FCC).
- **Netflix:** speaker IDs in brackets only when the speaker can't be visually identified; italics for off-screen narrators and for speech heard through media when the speaker isn't in the scene; never italicise an on-screen speaker.
- **BBC:** colour identifies speakers (white, yellow, cyan, green); the narrator is conventionally yellow; double quotes can mark mechanically reproduced speech or quotation.

So the bite should be visually distinguished from narration (colour or label) and transcribed verbatim.

### Cited Findings
- **WCAG [sourced]:** "Captions not only include dialogue, but identify who is speaking and include non-speech information." — [W3C Understanding SC 1.2.2](https://www.w3.org/WAI/WCAG22/Understanding/captions-prerecorded)
- **FCC [sourced]:** captions must be Accurate, Synchronous, Complete and Properly placed ("should not block other important visual content"). — [FCC: Closed Captioning on Television](https://www.fcc.gov/consumers/guides/closed-captioning-television)
- **DCMP [sourced]:**
  - Identify the speaker by placement under them when possible.
  - Otherwise, if the name is known, put "(Jack)" in parentheses on its own line; if unknown, use what a hearing viewer knows, such as "(narrator)".
  - Captions are left-aligned, at most two lines, inside the safe area.
  - — [DCMP Speaker ID](https://dcmp.org/learn/603-captioning-key---speaker-identification); [DCMP Tip Sheet](https://dcmp.org/learn/225-captioning-tip-sheet/)
- **Netflix US English Timed Text Style Guide [sourced]:**
  - 42 characters per line.
  - Speaker IDs in brackets after a hyphen, for example "-[Kimmy] Are you coming?", used only when the speaker can't be visually identified.
  - Italics for "dialogue heard through electronic media (e.g., phone, device, television, computer…) if the speaker isn't physically present in the scene", and for off-screen narrators. Don't italicise someone "merely off screen".
  - Documentary/unscripted: "For TV/movie clips, all audible lines should be transcribed if possible"; "If the speaker is on-camera for at least part of the scene, don't italicize. Leave italics for off-screen narrators."
  - Use an ellipsis for pauses of 2 s or more.
  - — [Netflix English (US) Timed Text Style Guide](https://studiopartner.netflix.net/studio/us-english-timed-text-style-guide)
- **BBC Subtitle Guidelines [sourced]:**
  - Colour is "the preferred method" for identifying speakers. Order of priority: White #FFFFFF, Yellow #FFFF00, Cyan #00FFFF, Green #00FF00, all on a black background.
  - "By convention, the narrator is indicated by a yellow colour."
  - "Once a speaker has a colour, they should keep that colour."
  - Single quotes indicate an out-of-vision speaker; "Double quotes… can suggest mechanically reproduced speech, e.g. radio, loudspeakers etc., or a quotation from a person or book."
  - Labels in white caps only when other techniques can't resolve who is speaking.
  - — [BBC Subtitle Guidelines](https://www.bbc.co.uk/accessibility/forproducts/guides/subtitles/)
- **BBC caption timing [sourced]:**
  - Reading speed 160–180 wpm; minimum about 0.3 s per word (for example, 1.2 s for 4 words).
  - Subtitles should ideally start and end on shot changes and avoid straddling them.
  - When a subtitle would end within a few frames of a shot change, extend it to the change. If it is 12 or more frames away, end it before the change (this is stated in the song-lyrics section).
  - — [BBC Subtitle Guidelines](https://www.bbc.co.uk/accessibility/forproducts/guides/subtitles/)

### Inferences
- **Narrator captions [inference]:** Narration keeps the house caption style. In BBC convention the narrator would be yellow; if the house style is white, keep it consistently.
- **Bite captions [inference]:**
  - Use a different, consistent colour per real speaker (for example white narrator → yellow or cyan for bite speakers), held for the whole video (BBC 8.4).
  - Add a speaker label on the *first* caption of each bite when there's no lower third yet, using the house label style (for example "JENSEN HUANG:" in small caps, or DCMP-style "(Jensen Huang)").
  - Wait until the person is introduced by lower third or narration before naming them (DCMP).
- **Quotation marks [inference]:** Opening and closing quotes around bite captions are a legitimate BBC-style signal ("quotation from a person"). They're optional, but help when the bite plays inside a framed or TV treatment.
- **Italics [inference]:** Netflix's rule implies roman (non-italic) for the bite when the speaker is visible. If the clip is shown inside a TV/monitor frame, Netflix's "heard through electronic media" rule could justify italics. Choose one rule and apply it consistently, which is Netflix's own instruction.
- **Verbatim and no word paraphrasing [inference]:** Bite captions must match the clip exactly, including retained "um"s if they're audible and kept (NPR "true to meaning"; Netflix "all audible lines transcribed").
- **Timing at boundaries [inference]:** Narration captions must end at or before the cut to the bite; don't let a narrator caption hang over the speaker's face (BBC's avoid-straddling rule). Bite captions start on the first word, not on the picture cut.
- **Burned-in source captions [inference]:** If the source has burned-in captions, crop or frame them out or place ours elsewhere. Two caption layers is a legibility failure under the FCC "properly placed" principle.
- **Character and line limits [inference]:** For 9:16, use about 32–42 characters per line and at most 2 lines. 42 is Netflix's landscape limit; the shorter vertical figure is my inference.

### Gaps
- I found no published survey of how YouTube explainer channels style bite captions differently from narration. Many explainers don't burn in captions at all.
- I couldn't find a caption standard that directly addresses an AI narrator who is also an on-screen presenter (in vision vs out of vision).

---

## 7. Clip length, trimming, in/out points, jump-cut vs cutaway, ethics of splicing

### Takeaway
- **Length:** broadcast bites are typically 5–15 s (8–15 s in TV news teaching), and longer bites must justify their length.
- **Trimming:** cut on word boundaries or breaths with small handles, keep the speaker's meaning intact, and never splice separate fragments so they appear continuous unless the break is visible (a cutaway, flash or jump cut is shown honestly).
- **Ethics:** BBC requires fair representation and forbids juxtaposition that materially misleads. NPR permits "clean-ups" for time and clarity but forbids internal edits on the US president, vice president and major-party candidates.

### Cited Findings
- **Bite length [sourced, journalism textbook]:** "Sound bites are typically 5-15 seconds long, though the closer you get to 15, the more you must justify the added length." Choose "a bite that is representative of your interview." — [Writing for Electronic Media (UEN Pressbooks)](https://uen.pressbooks.pub/writingforelectronicmedia/chapter/vosots/)
- **Bite length in TV news [low-authority]:** "Most soundbites are eight to fifteen seconds long." The script must note the out-cue (last 3–4 words). — [YouTube: How to Write a News Report Script](https://www.youtube.com/watch?v=2xGvoem04Do)
- **Splicing rule [sourced, broadcast production guide]:**
  - "Never join separate pieces of an answer so they appear to be one continuous statement unless the break is clear and the meaning remains accurate."
  - Record source filename, exact in/out timecodes and measured length for each bite.
  - "Does the bite make sense without hearing the interview question?"
  - — [Bellville AV](https://bellvilleav.com/wp-content/uploads/2026/09/Section-4-Write-the-Video-Package-Script.pdf)
- **BBC Fairness 6.4.30 [sourced]:** "The final content should be a fair representation of what a contributor says and does and their contribution should not be misrepresented." — [BBC Editorial Guidelines, Section 6](https://www.bbc.com/editorialguidelines/guidelines/fairness/guidelines/)
- **BBC Accuracy 3.4.25 [sourced]:** cutaways improving "clarity and flow" are acceptable. Content makers should not "inter-cut shots and sequences if the resulting juxtaposition of material leads to a materially misleading impression"; "Commentary and editing must never be used to give the audience a materially misleading impression of events or a contribution." — [BBC Section 3 Accuracy](https://www.bbc.co.uk/editorialguidelines/documents/section-3-accuracy.pdf)
- **NPR on editing tape [sourced]:**
  - Editing must be "true to the meaning of their words".
  - Kern (*Sound Reporting*): "you can… cross onto shaky editorial ground if you keep all the sentences… intact, but change their order", because inflection changes meaning.
  - "No one we interview should be surprised by what they hear… themselves saying."
  - — [NPR Ethics Handbook](https://current.org/wp-content/uploads/2013/01/NPR-Ethics-Handbook-5.2.2012-Final-Edition.pdf)
- **NPR Training on clean-ups [sourced]:** removing ums, ahs, stumbles and pauses is "most of the time… fine, as long as you are not removing something that suggested the interviewee was reluctant or unable to respond". There is no audio equivalent of an ellipsis. Cleaning up too much "could yield unnatural-sounding" tape. — [NPR Training: How to decide what to cut](https://www.npr.org/sections/npr-training/2025/05/29/g-s1-65686/how-to-decide-what-to-cut-or-not-in-an-interview)
- **NPR on the president [sourced]:** "With the president… vice president and major party candidates… we don't do internal edits. We won't click out an um or a ah or take out something from the middle of a sentence… if you make someone sound too coherent when they're not that coherent, you… may be changing the tone." — [NPR: How NPR edits remarks by the president (2025)](https://www.npr.org/2025/11/14/nx-s1-5609180/how-npr-edits-remarks-by-the-president)
- **Frankenbites are industry practice in reality TV [sourced, trade press]:** "Koch is asked to create 'Frankenbites'… to help move the story forward." This shows the practice exists, and why news/explainer contexts restrict it. — [postPerspective](https://postperspective.com/emails/iZotope/ppnews-iZotope-161004.html)
- **Cut points [common practice, low-authority]:** breath 200–600 ms; transient 5–20 ms; cut 2 frames before the transient of the incoming word. — [kookenhoomen](https://kookenhoomen.com/motion/cut-the-sequence-on-the-sound/)

### Inferences
- **In/out rules for the pipeline [inference]:**
  - Choose in/out on word-timestamp boundaries from forced alignment or ASR on the clip.
  - In-point = first word onset − 80 to 150 ms, but never earlier than the end of the previous speaker's or interviewer's last word.
  - Out-point = last word offset + 150 to 300 ms, cut inside the following breath or silence. Extend to the silence midpoint if the gap is < 400 ms.
  - Reject the bite if another voice (interviewer, crowd, translator) is audible inside the window, or if the in/out lands mid-word (energy above a threshold within ±30 ms of the cut).
- **Full sentences [inference]:** Prefer bites that start and end on full sentences, which follows from the "makes sense without the question" test. Don't end on a rising or continuing intonation. A heuristic is to require the last word to be followed by ≥ 250 ms of silence in the source.
- **Default editing policy [inference]:** Single continuous excerpt, no internal edits. If an internal edit is necessary:
  - Show it visibly, either as a cutaway to B-roll or graphic over the edit point (BBC-acceptable "clarity and flow" when meaning is preserved), or as an honest jump cut.
  - Never reorder sentences (NPR/Kern).
  - Never make internal edits for heads of state or candidates (NPR's rule, a good conservative default for public figures).
  - Log the source URL and timecodes for every bite (Bellville).
- **Length [inference]:** 3–4 s bites work as "punctuation"; 6–12 s is the sweet spot; above 15 s, cover part with B-roll or split into two bites with narration between.

### Gaps
- I found no authoritative ms handle values; the values above are inference.
- No PBS or CBC specific guidance was retrieved; their standards pages were not fetched.
- The specific BBC rule on "flash frames"/"white flash" to signal edits was not found.

---

## 8. Presenter-led videos: throwing to a clip and returning

### Takeaway
Broadcast writing gives clear verbal rules:
- **Lead-in:** set up the bite with context or a question the bite answers; don't parrot its words; never say "had this to say".
- **Outro:** add new information rather than restating the bite.

I found no sourced guidance on presenter body language (looks, gestures, screen-in-screen) for throwing to clips; that part is inference.

### Cited Findings
- **Setting up the bite [sourced, journalism textbook]:** "You want the SOT to fit right after the anchor's last words. You also don't want the bite to repeat what the anchor just said." "If you set up a bite with HAD THIS TO SAY, you are doing it wrong." Setups must be factual. — [UEN Pressbooks: VOSOTs](https://uen.pressbooks.pub/writingforelectronicmedia/chapter/vosots/)
- **Into and out of the bite [sourced, broadcast production guide]:**
  - "The sentence before a bite is called a setup… The sentence after a bite moves the story forward. Neither sentence should repeat the bite word for word."
  - A setup can "create a logical question in the viewer's mind that the bite then answers".
  - Do not write "She had this to say" or "He tells us more."
  - — [Bellville AV](https://bellvilleav.com/wp-content/uploads/2026/09/Section-4-Write-the-Video-Package-Script.pdf)
- **Lead-in and outro [sourced, broadcast writing training]:** "Give a brief lead-in that previews the sound bite"; "After the bite plays, give a quick outro with any details that weren't featured in the audio"; "Don't use the same phrasing in your intro that's used in the bite." — [CBI: Writing for the Ear](https://www.askcbi.org/wp-content/uploads/2019/11/Writing-for-the-Ear-NSEMC-2019-FINAL-1.pdf)
- **Out-cue [low-authority]:** the script records the clip duration and the out-cue (last 3–4 words) so the director knows when to switch back to the anchor. — [YouTube: news script tutorial](https://www.youtube.com/watch?v=2xGvoem04Do)
- **Held beat after the speaker [common practice, low-authority]:** let the person on screen "exist in the frame for an extra beat after they've stopped talking". — [Editing Luke](https://www.editingluke.net/breathing-room-editors-embrace-silence/)
- **Emotion first [sourced, Murch]:** Rule of Six priorities: Emotion 51%, Story 23%, Rhythm 10%, Eye-trace 7%, 2D plane 5%, 3D space 4%. "Sacrifice your way up… from the bottom." This is relevant to where the return cut lands (on emotion or rhythm, not mechanical continuity). — [Murch, In the Blink of an Eye](https://stavry.github.io/docs/in-the-blink-of-an-eye.pdf)

### Inferences
- **Script rules the LLM generator can enforce [inference]:**
  - (1) The narrator line before the bite must not share a content n-gram of 3 or more words with the bite transcript (the "no parroting" check).
  - (2) Ban "had this to say", "tells us more", "says the following" and similar phrases.
  - (3) The lead-in either names the speaker plus context ("At the 2024 shareholder meeting, Buffett was asked about…") or poses the question the bite answers.
  - (4) The line after the bite must add new information or move the story forward, not restate the bite. A short acknowledgement ("Exactly." / "And that's the key point.") is acceptable only if followed immediately by new content.
- **Throwing visually [inference]:**
  - The presenter turns their head or eyes toward the side where the clip will appear, or gestures toward an inset or monitor, during the last 0.5–1 s of the lead-in.
  - Optionally, the clip first appears as a screen-in-screen card behind or beside the presenter (about 40–50% of frame), then scales to full-frame over about 300–500 ms as the speaker begins.
  - The return reverses this: the clip shrinks back to the card, or cuts to the presenter mid-reaction (a nod).
  - Landscape: put the clip card on the side the presenter is looking toward. 9:16: card in the upper half, presenter in the lower half (or full-screen clip).
- **Return timing [inference]:** Resume narration 250–500 ms after the clip's last word (allowing the held beat), and land the cut back on the presenter on a nod, blink or start of a gesture (Murch's emotion/rhythm over continuity). Keep the room-tone tail of the clip under the first frames of the presenter shot.
- **Frequency [inference]:** Space bites at least about 20–30 s of narration apart so each throw feels deliberate. This isn't sourced.

### Gaps
- I found no published guidance (broadcaster, editor channel or book) on presenter gestures and eyelines when throwing to inserted clips in YouTube explainers.
- Observational study of Johnny Harris, Vox, ColdFusion etc. was not performed; the requested editor channels (Premiere Gal, Film Riot, Cinecom) were not retrieved.
- Karen Pearlman's *Cutting Rhythms* was not retrieved, so her rhythm and "timing, pacing, trajectory phrasing" concepts are not represented here.

---

## 9. Published guidelines and canon: what exists and what it covers

### Takeaway
Hard numeric standards exist only for loudness (Netflix, EBU R128, ATSC; YouTube's −14 LUFS is observed rather than published) and for captions (Netflix, BBC, DCMP, WCAG, FCC). Editorial ethics rules exist (BBC Sections 3, 6 and 13; NPR Ethics Handbook and Training). Split-edit lengths, duck depths, lower-third timing and framing are craft conventions published mainly by practitioners, with no single authoritative standard.

### Cited Findings
- **Loudness standards [sourced]:**
  - Netflix: −27 LKFS dialogue-gated ±2 LU, −2 dBTP — [Netflix](https://studiopartner.netflix.net/studio/branded-sound-mix-spec-and-best-practices)
  - EBU R128: −23 LUFS, −1 dBTP; short-form Max Short-term Loudness −18 LUFS — [EBU R128](https://tech.ebu.ch/docs/r/r128v5_0.pdf), [EBU Tech 3343](https://tech.ebu.ch/docs/tech/tech3343v4_1.pdf)
  - YouTube: about −14 LUFS observed, turn-down only — [lufsready](https://lufsready.com/blog/loudness-normalization-explained)
- **Captions and accessibility [sourced]:** [Netflix Timed Text Style Guide](https://studiopartner.netflix.net/studio/us-english-timed-text-style-guide), [BBC Subtitle Guidelines](https://www.bbc.co.uk/accessibility/forproducts/guides/subtitles/), [DCMP](https://dcmp.org/learn/603-captioning-key---speaker-identification), [WCAG 1.2.2](https://www.w3.org/WAI/WCAG22/Understanding/captions-prerecorded), [W3C background audio ≥ 20 dB](https://www.w3.org/WAI/media/av/av-content/), [FCC](https://www.fcc.gov/consumers/guides/closed-captioning-television)
- **Editing ethics [sourced]:** [BBC Fairness 6.4.30](https://www.bbc.com/editorialguidelines/guidelines/fairness/guidelines/), [BBC Accuracy 3.4.25/3.4.32](https://www.bbc.co.uk/editorialguidelines/documents/section-3-accuracy.pdf), [BBC Section 13](https://www.bbc.com/editorialguidelines/guidelines/use-of-bbc-content-after-publication-or-broadcast/guidelines), [NPR Ethics Handbook](https://current.org/wp-content/uploads/2013/01/NPR-Ethics-Handbook-5.2.2012-Final-Edition.pdf), [NPR president-editing rule](https://www.npr.org/2025/11/14/nx-s1-5609180/how-npr-edits-remarks-by-the-president)
- **Editing canon [sourced]:** Murch's Rule of Six and the blink-based cut point. — [In the Blink of an Eye](https://stavry.github.io/docs/in-the-blink-of-an-eye.pdf); [nolanlabs citing Hullfish interview](https://nolanlabs.io/blog/j-cut-and-l-cut)

### Inferences

#### Candidate default parameters for the pipeline
All values are starting points, labelled by origin.

**Bite selection**

| Parameter | Default | Basis |
| --- | --- | --- |
| Bite length | 3–15 s, preferred 6–12 s | Textbook 5–15 s [sourced]; user scope |

**Audio levels**

| Parameter | Default | Basis |
| --- | --- | --- |
| Final mix | −14 LUFS integrated, −1 dBTP (house alternative −16 LUFS) | YouTube observed; EBU true peak [sourced] |
| Bite vs narrator loudness | Match speech loudness within ±1 LU | Inference, by analogy with EBU ±1 LU |
| Clip clean-up chain | HPF 80–100 Hz → gentle de-noise → optional LPF 8–12 kHz → light compression | Inference, from Koch/iZotope workflow [sourced] |
| Music under narration | Bed 15–20 dB below speech (duck 12–18 dB from full) | Common practice [low-authority] |
| Music under standard bite | ≥ 20 dB below bite speech (about 3–6 dB deeper than under narration) | W3C ≥ 20 dB [sourced] + inference |
| Music for key bite | Fade out 300–500 ms, ending 200–400 ms before first word; return 0–300 ms after last word; ≤ 2–3 per 10 min | Full Send / Editing Luke [low-authority] + inference |
| Duck ramps | Start 200 ms before speech; release 300–600 ms | addaly / tryuncle [low-authority] |
| Clip audio edge fades | 10–30 ms on words; 100–250 ms on ambience | Inference |
| Room tone | Extend clip ambience 0.25–0.5 s beyond both edges | iZotope room-tone rationale [sourced] + inference |

**Trimming and transitions**

| Parameter | Default | Basis |
| --- | --- | --- |
| In-point | First word onset − 80 to 150 ms | Inference |
| Out-point | Last word offset + 150 to 300 ms, inside breath or silence | Inference; breath 200–600 ms [low-authority] |
| Picture lead (narration L-cut onto clip face) | 6–12 frames (0.2–0.4 s) before first word; no voice overlap | Practitioner ranges [low-authority] + inference |
| Return to narration | 250–500 ms after last word; hold the speaker's face for a beat | Editing Luke [low-authority] + inference |
| Internal edits | Off by default; if used, cover with B-roll; never for heads of state or candidates; never reorder | BBC / NPR [sourced] |

**On-screen text and captions**

| Parameter | Default | Basis |
| --- | --- | --- |
| Lower third | In at bite start + 0.3–0.5 s; on screen 4–6 s; first appearance only; 2 lines (name / role · venue, year) | Hencar / Frame.io / Bellville [common practice] |
| Source/year credit | Persistent small corner credit for whole bite; mandatory date if clip is old | BBC 13.4.4 / NPR [sourced] + inference |
| Bite captions | Verbatim; distinct consistent colour per real speaker; speaker label when not yet identified; roman (no italics) when speaker is visible; narration captions end at the cut | Netflix / BBC / DCMP / WCAG [sourced] + inference |

**Framing**

| Parameter | Default | Basis |
| --- | --- | --- |
| 9:16 framing | Smoothed face-tracked crop for a single speaker; square-on-blur for two people or slides; never plain black bars; captions in the blur band | Practitioner consensus [low-authority] |

### Gaps
- I didn't retrieve guidance from PBS, CBC or editor YouTube channels (Premiere Gal, Film Riot, Cinecom, Johnny Harris's editors). Treat this as a known coverage hole.
- Observations of high-quality explainer channels (Vox, Wendover, ColdFusion, Bloomberg Originals, CNBC) were not collected. The only data point is one third-party measurement of Wendover's loudness (−24.3 LUFS), which suggests even top explainer channels don't all master to −14 ([umbrellacreators](https://umbrellacreators.com/blog/how-to-normalize-audio-for-youtube), low-authority).
- Many craft numbers come from 2026-dated vendor or tool blogs whose authorship and expertise couldn't be verified. They agree with each other, but some may derive from one another rather than from independent practice.
