# Tools and Automation for Finding, Trimming and Inserting Real Sound Bites into Narrated Videos

Research date: 21 Nov 2026. Source labels used below: **[DOC]** vendor documentation, help centre, README, or official policy; **[PAPER]** benchmark or academic paper; **[MKT]** marketing page or vendor claim; **[ANEC]** forum post, portfolio case study, or other anecdotal or self-reported source; **[3P]** third-party guide or blog. Anything dated before 2025 is flagged as older.

---

## 1. Text-based / transcript-based editors (Descript, Premiere Pro, DaVinci Resolve, CapCut, Riverside)

### Takeaway
The mainstream transcript editors (Descript, Premiere, Resolve) all treat a word-level transcript as the edit surface and ripple-delete media under deleted words. The audio-quality safeguards they document are automatic micro-fades at every cut, AI room tone to fill gaps, an "avoid harsh cuts" check that **skips** edits that would clip neighbouring words, and AI "regenerate/smooth" healing. None of them publishes numeric defaults for crossfade length or word padding. Resolve's IntelliScript is the closest analogue to "find this scripted line in the footage": it matches script text against transcripts, puts the best match on the main track, and puts alternates on disabled tracks.

### Cited Findings
**Descript**
- [DOC] Filler-word removal (English only) offers per-instance choices: Delete (text and audio), "Delete and replace with gap" (keeps the timing), Ignore (strikes the text but removes the audio), and "Remove from transcript" (text only, audio untouched). — [Descript Help: Filler words](https://help.descript.com/script-editing/filler-words)
- [DOC] "Avoid harsh cuts": when enabled, Descript "analyzes the surrounding audio and automatically skips any filler words that can't be removed without clipping into nearby words or leaving behind an awkward cut." — [Descript Help: Filler words](https://help.descript.com/script-editing/filler-words)
- [DOC] The changelog says Avoid harsh cuts shipped in June 2025, and that it checks only for harsh *audio* cuts: "you may still see video cuts that you need to adjust manually." It also adds processing time. — [Descript changelog, 5 Jun 2025](https://descript.canny.io/changelog/release-roundupjune-5th-2025)
- [DOC] Room tone: AI builds a noise profile from **the first 30 seconds** of each file (it looks for non-speech audio) and adds that noise to adjacent gap clips. Descript recommends recording at least 15 s of silence first and avoiding music in the first 30 s. Room tone is on by default for new projects and is disabled for clips where Studio Sound is enabled. — [Descript Help: Room tone](https://help.descript.com/effects-animations-transitions/room-tone)
- [DOC] Edit boundaries are shown wherever two clips meet. "Smooth" runs Regenerate to heal a jumpy or awkward cut (audio and video, falling back to audio only), and "Restore removed media" brings back what was cut. — [Descript Help: Edit boundaries](https://help.descript.com/script-editing/edit-boundaries)
- [MKT/3P, Descript blog] Crossfades exist only at edit boundaries and are adjusted by dragging a handle. The post motivates crossfades by clicks or pops at abrupt cuts and room-tone discontinuities. Its only numeric guidance is about 5 s for *music* crossfades. It gives no default for speech. — [Descript blog: Crossfade audio](https://www.descript.com/blog/article/crossfade-audio-what-crossfade-is-and-how-to-edit-it)
- The claim that Descript "automatically applies short microfades at edit boundaries" appeared only in a search-engine synthesis. I did not find it in the fetched help text, so treat it as unverified.

**Adobe Premiere Pro (Text-Based Editing)**
- [DOC] Premiere transcribes source media, and you build a sequence by selecting transcript text. Deleting text in the sequence transcript applies a ripple edit. You can filter for Text, Filler words, Pauses or Speakers, then Delete one instance or Delete all. The minimum pause duration is set in Transcript View Options. — [Adobe Help: Detect and delete pauses (updated 7 Jan 2026)](https://helpx.adobe.com/premiere/desktop/edit-projects/edit-video-using-text-based-editing/detect-and-delete-pauses-in-transcripts.html); [Adobe Help: Text-Based Editing (Nov 2024)](https://helpx.adobe.com/africa/premiere-pro/using/text-based-editing.html)
- [DOC] Adobe recommends "dialogue recordings with clear audio and minimal background noise for best results." — [Adobe Help: Overview of Text-Based Editing](https://helpx.adobe.com/premiere/desktop/edit-projects/edit-video-using-text-based-editing/overview-of-text-based-editing.html)
- [3P] Deleting offers Extract (ripple, closes the gap) or Lift (leaves a gap, e.g. for B-roll later). Transcript View Options can mark low-confidence words. Covering filler cuts is left to the editor: B-roll, Morph Cut, or accept the jump cut. — [Zuhuri ACP exam guide](https://zuhuri.com/learn/stories/acp-premiere-text-based-editing/)
- [3P] RedShark found filler detection "not 100% effective" (tested in beta) and warned that "Delete all" removes intentional pauses. — [RedShark News](https://www.redsharknews.com/how-to-delete-pauses-and-filler-words-with-text-based-editing)

**DaVinci Resolve (Studio)**
- [DOC] AI Audio Transcription is attached to clips in the Media Pool and used to search, select and insert clips by text. Blackmagic warns that radically rewriting transcript text (e.g. replacing a paragraph with a summary) "will have unpredictable effects if used for editing." — [Resolve 21 manual, Ch. 47 Text Based Editing (mirror)](https://docs.imaster.org/davinci-resolve-21-manual/part-6-edit/ch.-47-text-based-editing)
- [DOC] IntelliScript takes a .txt script (Resolve 21 also accepts .fdx) and builds a timeline from transcribed clips. The best matches of each line go on Video 1, and alternative takes go on disabled tracks above for comparison. The manual says it "is smart enough to understand context," so a similar ad-libbed phrase "should still find it." — [Resolve 21 manual Ch. 47](https://docs.imaster.org/davinci-resolve-21-manual/part-6-edit/ch.-47-text-based-editing); [Editor's Guide to Resolve 20, L6 AI Workflows](https://docs.imaster.org/editor%E2%80%99s-guide-r20/l6-ai-workflows)
- [3P] Scripts should contain only spoken dialogue. Scene descriptions, parentheticals and character names cause matching problems. — [davinciresolveclub.com](https://davinciresolveclub.com/transcribe-audio-davinci-resolve/)

### Inferences
- Across these tools, the shared pattern is: transcript as index, ripple-edit on word boundaries, then cosmetic healing (fades, room tone, regeneration). Every vendor still expects a human to review cuts. Descript's "skip if it can't be cut cleanly" is a useful precedent for automatically **rejecting** a sound-bite candidate whose edges have no clean gap, rather than forcing the cut.
- Resolve's best match on the main track with alternates on disabled tracks is structurally close to our design of keeping the narrator's reading as a fallback underneath an approved clip.
- Room-tone matching by sampling non-speech audio is mainly relevant to filling gaps *within* one source. In our replace mode the clip's own background will differ from the narrator's clean TTS, so the transition is a source change, not a gap fill. That points toward short fades and loudness matching rather than room-tone synthesis.

### Gaps
- No published numeric defaults (micro-fade ms, crossfade ms, word padding) were found for Descript, Premiere or Resolve.
- CapCut and Riverside transcript-editing behaviour was not researched within the tool-call budget. No sourced findings.
- I found no documentation on how these editors snap a cut to the inter-word gap versus the ASR word timestamp.

---

## 2. Clip finders and quote search (Filmot, YouGlish, PlayPhrase, Opus Clip, etc.)

### Takeaway
Searching YouTube by spoken words relies on caption indexes. Filmot is the most capable public index. It has an API, exact-phrase and proximity operators, and timestamped exports, but it returns caption-line start times, not word-accurate boundaries, and its index can be a stale snapshot. "Find the moment" AI clippers such as Opus Clip work on a video you supply and pick moments for virality or semantic match, not verbatim quotes.

### Cited Findings
- [DOC] Filmot searches YouTube subtitles, captions and transcripts. It supports exact phrases, OR (`|`), grouping, proximity (`"a b"~5`), exclusion (`-word`) and sound tags like `#Applause#`. — [Filmot home](https://filmot.com/)
- [DOC] The Filmot API has `getsubtitlesearch` (with export formats), `getvideos` (metadata plus optional subtitles) and others. Subtitle search "can return matching text snippets with their start times." It requires an API key and has usage allowances. — [Filmot FAQ: API endpoints (updated 2026-10-11)](https://filmot.com/faq/1321/What%20endpoints%20does%20the%20Filmot%20API%20offer%2C%20and%20what%20does%20subtitle%20search%20return)
- [DOC] Filmot does **not** download video. It can export "embed urls" with start and end times around each match, with adjustable seconds before and after. Export limits are 60 subtitle-search rows without patron benefits and 10,000 with them. — [Filmot FAQ: downloads](https://filmot.com/faq/321/Can%20Filmot%20download%20YouTube%20videos%20or%20video%20clips%20directly); [Filmot FAQ: exports](https://filmot.com/faq/1441/How%20do%20I%20export%20search%20results%2C%20choose%20columns%20and%20create%20video%20or%20channel%20links)
- [DOC, third-party CLI README] Filmot's index segments "are derived: each line ends where the next begins, and the last ends within 10 seconds." Index text should be treated as "a Filmot snapshot that may predate the video's current captions." — [filmot-cli AGENTS_README](https://github.com/baba20o/filmot-cli/blob/main/AGENTS_README.md)
- [3P] YouGlish is for hearing a word or phrase in real speech (pronunciation); it is not a clip catalogue. PlayPhrase, Clip.Cafe and Subzin target film and TV dialogue. Search access is separate from download or export rights. Subtitle wording can differ from the audio, and results can be paraphrases or fan uploads, so verify the source. — [Techtippr, Jul 2026 (documentation-based, not a hands-on test)](https://techtippr.com/best-free-playphrase-alternatives/)
- [DOC/MKT] Opus Clip ClipAnything is "multimodal AI clipping" over visual, audio and sentiment cues. Each scene "is rated based on its virality potential," and you prompt in natural language ("Find all the touchdowns"). ClipBasic accepts only keywords that are "present in the speech or transcript." — [Opus Help: What is ClipAnything](https://help.opus.pro/docs/article/9947095-clip-anything); [Opus Help: prompts](https://help.opus.pro/docs/article/select-keywords); [Opus ClipAnything page (MKT)](https://www.opus.pro/clipanything)

### Inferences
- A practical design is two-stage: (1) use a caption index such as Filmot, or yt-dlp caption fetch, to find candidate videos and coarse timestamps; (2) download a padded window and re-transcribe it with our own ASR before trusting any boundary.
- Index text can be stale or paraphrased (manual captions are often condensed), so a match on the index is a lead, not a verified quote. The verbatim check must run on our own ASR of the downloaded audio.
- Virality-oriented clippers are not built for "find the exact sentence person X said," so they are a poor fit for verbatim sound bites.

### Gaps
- No published accuracy figures (precision, recall, or timestamp error) for Filmot, YouGlish, PlayPhrase or Opus Clip.
- Vizard, Munch, Eklipse, and YouTube's own AI "jump to moment"/Ask features were not researched within budget.

---

## 3. Archive and footage licensing (Getty, Reuters, AP, C-SPAN, Pond5/Storyblocks, corporate newsrooms)

### Takeaway
Legitimate news footage is quote-based, editorial-only by default, and expensive. Market estimates put it at about $80–100 per second with 30 s minimums. Monetised YouTube use is generally treated as commercial use. C-SPAN allows non-commercial posting of federal-event coverage with attribution, but monetised use needs a commercial license. Corporate newsrooms (e.g. NVIDIA) host downloadable keynote footage and B-roll, but I could not find published usage terms.

### Cited Findings
- [DOC] Reuters Connect: all licensed content is "for EDITORIAL USE ONLY" unless agreed in writing. "Commercial Use … shall not constitute an Editorial Use." Other uses need Reuters' written approval, may carry extra fees, and the licensee must obtain third-party clearances (publicity, privacy, trademark, etc.). — [Reuters Connect transactional license terms §2.3](https://www.reutersconnect.com/transactional-license-terms)
- [DOC] Reuters offers single-asset licensing by card or invoice for archive video (older than 30 days) without public prices on the page. — [Reuters Connect plans](https://www.reutersconnect.com/plans-and-pricing)
- [3P, verified 2026-07-16] Getty editorial video is "rights-ready," priced by use. Per-clip video prices are not published (UltraPack or enterprise quotes). Partner collections include BBC Motion Gallery, NBC News Archives, Bloomberg and ITN. AP Archive (over 2M stories since 1895) has no public rate card and negotiates licensing per use. — [Stockfilm comparison](https://stockfilm.com/compare)
- [3P, market estimate, not official] News archives typically quote **$80–$100 per second for B-roll with a 30-second minimum** (about $2,400–$3,000 per clip), and $100–150 per second when an on-camera reporter appears. Getty rights-ready clips start around $99. — [DFI Rentals](https://www.dfirentals.com/news/archival-footage-licensing-cost)
- [3P] Getty and Reuters editorial licenses "almost never permit commercial use," and ad-monetised YouTube is commercial "in YouTube's eyes." — [Vaatik 2026 guide](https://vaatik.com/blog/youtube-documentary-broll-licensing-guide). This is the author's opinion; I did not verify it against each license.
- [DOC] C-SPAN: no license is needed to post C-SPAN coverage of **federal government events** (hearings, White House events, commissions) for **non-commercial** purposes with attribution, and a visible C-SPAN logo counts as attribution. Commercial use needs a license, including documentaries and podcasts and "any use that relies substantially on C-SPAN content to generate revenue." Non-federal programs cost $100 per program per year, single URL, stream-only. — [C-SPAN Copyright and Licensing](https://www.c-span.org/about/copyrightsAndLicensing/)
- [DOC] C-SPAN Terms (effective 15 Dec 2025): commercial use includes "using the Content for the purpose of gaining advertising or subscription revenue." The terms prohibit altering the C-SPAN logo, using bots to copy content, and using content "in connection with any … AI … system, technology, tool" without an AI license. — [C-SPAN Terms and Conditions](https://www.c-span.org/about/termsAndConditions/)
- [DOC] Older (2007): the NYT reported C-SPAN's original policy shift clearing clips for web use with credit. — [NYT, 2007 — older](https://www.nytimes.com/2007/03/08/business/media/08cspan.html)
- [DOC] The NVIDIA Newsroom hosts "Videos and B-roll" and keynote assets (GTC 2026, CES 2026, Computex 2026, etc.). Press contact is press@nvidia.com. The fetched pages show no explicit usage license. — [NVIDIA Newsroom B-roll](https://nvidianews.nvidia.com/multimedia/corporate/corporate-b-roll); [Newsroom search](https://nvidianews.nvidia.com/multimedia/search?page=1); [Press contacts](https://nvidianews.nvidia.com/contacts)
- [ANEC] A creator who claims to run an automated newscast restricts media to Wikimedia Commons, Openverse, NASA and Pixabay through a "license gate" (public domain, CC0, CC BY, CC BY-SA, Pixabay). Every shot is labelled FILE PHOTO / FILE VIDEO / ILLUSTRATIVE with a credit box. — [Neon Bulletin case study, Oct 2026](https://expertcoders.net/portfolio/view/neon-bulletin)

### Inferences
- For a monetised explainer channel, "license every bite from an agency" is cost-prohibitive at per-second rates. Most creators instead rely on fair use or Content ID tolerance (see section 4). The pipeline should record a per-clip **rights class** (public domain or government, CC, press kit, fair-use-reliant YouTube rip, licensed) so the user makes an informed choice.
- C-SPAN's AI clause could arguably cover automated pipelines that process its content. That is a legal question to flag, not resolve.

### Gaps
- Pond5 and Storyblocks pricing and terms for editorial or news footage were not researched within budget.
- NVIDIA (and other corporate) newsroom media-use terms were not found. The pipeline should not assume press-kit footage is free for monetised use.
- AP's current licensing route for individual creators was not verifiable (aparchive.com now redirects into the login-gated AP Newsroom, per Stockfilm).

---

## 4. AI / "faceless" explainer pipelines and agentic editors: do they insert real sound bites, and what goes wrong?

### Takeaway
Mainstream AI video generators (InVideo, Pictory, Fliki, HeyGen, Synthesia) centre on stock B-roll, avatars and TTS. I found no evidence that they automatically locate and insert verbatim sound bites of real people. The precedents I found are open-source or hobbyist agent pipelines from 2026. VideoDB's agentic-streams pulls YouTube clips and self-checks narration against frames. "Neon Bulletin" (self-reported) cuts verbatim 5–20 s quotes using Whisper word timestamps, caps bites at four per show, and labels speaker, date and source on screen. The main risks are YouTube's channel-wide reused/inauthentic-content monetisation rules and Content ID claims on news clips.

### Cited Findings
**Pipelines that insert real clips**
- [DOC/blog] VideoDB "Agentic Streams" (open source, published Aug 2026, updated Oct 2026): agents browse the web, gather YouTube clips, tweets, screenshots and charts, write and voice the narration, and assemble a multi-track timeline. The "content creator" agent "indexes the output … and checks, scene by scene, that what the narration says matches what is on screen. Where the two disagree, it fixes the cut." A news-digest agent combines BBC, CNN and Al Jazeera coverage. — [VideoDB blog](https://videodb.io/blog/agentic-streams.md); [news-digest skill](https://www.skills.sh/video-db/agentic-streams/news-digest-video-agent)
- [ANEC, self-reported portfolio] Neon Bulletin (Oct 2026): "For stories where one moment is the news, the system searches this week's YouTube video, lays out time-stamped contact sheets, has a vision model find the moment, and cuts 20 seconds or less. Sound bites use Whisper word timestamps to cut a verbatim 5 to 20 second quote, capped at four per show with speaker, date, and source on screen." Voices are normalised to -16 LUFS. Uploads are private for human review before publishing. — [Neon Bulletin case study](https://expertcoders.net/portfolio/view/neon-bulletin)
- [MKT] Fliki's news generator turns a link into a script with an AI anchor and "cuts in b-roll." It does not mention source sound bites. — [Fliki AI news video generator](https://fliki.ai/features/ai-news-video-generator)
- [MKT] ViralMint's news-to-short skill grounds the script in saved article text and renders over "story-matched visuals." It does not mention sound bites. — [ViralMint](https://viralmint.net/skills/news-to-short/)

**Policy and monetisation risks**
- [DOC] On 15 Jul 2025 YouTube renamed "repetitious content" to "inauthentic content," covering mass-produced and repetitive content. Its examples include "AI-generated content made with generic or unoriginal templates giving the impression of mass production," and image slideshows or templated storylines with minimal narrative. — [YouTube channel monetization policies](https://support.google.com/youtube/answer/1311392?hl=en)
- [DOC] YouTube says reused-content rules for commentary, clips and compilations did not change. Such content can monetise "if you've added significant original commentary, modifications, or educational or entertainment value." Mass-produced examples include "narrated stories with only superficial differences" and "slideshows that all have the same narration." — [YouTube Community: creator questions on YPP (Jul 2025)](https://support.google.com/youtube/thread/356734251/response-to-creator-questions-about-ypp-policies-july-2025?hl=en-GB)
- [DOC] Reused content is judged at the **channel** level: "monetization may be removed from your entire channel." It is "not based on copyright, permission, or fair use," so even permitted clips can trigger it. — [YouTube monetization policies](https://support.google.com/youtube/answer/1311392?hl=en&ref_topic=9153642)
- [DOC] Content ID matches create *claims* (track, monetise, or block) but **no strike**. A valid DMCA takedown creates a strike, and three strikes in 90 days terminates the channel. — [How YouTube Works: Copyright](https://www.youtube.com/howyoutubeworks/policies/copyright/); [Strikes FAQ](https://support.google.com/youtube/answer/9235777)
- [DOC] Creators must disclose realistic altered or synthetic content. — [YouTube Community thread (Jul 2025)](https://support.google.com/youtube/thread/356734251/response-to-creator-questions-about-ypp-policies-july-2025?hl=en-GB)
- [News] YouTube suspended AI fake-trailer channels Screen Culture and KH Studio from YPP in March 2025. — [Deadline](https://deadline.com/2025/03/youtube-ad-revenue-fake-movie-trailer-screen-culture-1236354143/)
- [ANEC] r/documentaryfilmmaking (Jul 2026): faceless documentary channels commonly use 2–10 s CNBC, Bloomberg or CNN clips. Replies say most lean on fair use and accept Content ID claims, that outlets "do file Content ID claims fairly often," and that muting original audio and re-narrating "doesn't remove copyright liability for the visual content." — [Reddit thread](https://www.reddit.com/r/documentaryfilmmaking/comments/1vbuqqs/how_do_documentary_youtube_channels_legally_use/)
- [ANEC, older: Dec 2024] r/YT_Faceless: a creator using news footage with effects and commentary worries about reused-content classification. A reply warns that controversial news content risks termination. — [Reddit thread](https://www.reddit.com/r/YT_Faceless/comments/1hag4i4/reused_content_in_this_niche/)

### Inferences
- Automatic verbatim sound-bite insertion is still a frontier feature, built by agent hobbyists and open-source projects rather than commercial generators. Our design is ahead of mainstream products here, so there is little product prior art to copy and more need for our own safeguards.
- The recurring safeguards in the precedents are: caps on clip count and length, on-screen attribution (speaker, date, source), a self-check that narration matches the inserted media, and human approval before publishing. These map directly onto our "approved clip or narrator fallback" model.
- Because reused-content review is channel-wide and ignores permission, heavy reliance on clips (especially if every video follows the same template) is a monetisation risk even when each clip is short.

### Gaps
- I did not verify whether InVideo AI, Pictory, HeyGen or Synthesia have added real-person sound-bite search in 2025–2026. I found no evidence either way within budget.
- I found no documented case of an AI pipeline inserting a *wrong* or out-of-context quote clip. The failure modes here are inferred, not sourced.

---

## 5. Technical: yt-dlp sections, YouTube caption timing, forced alignment, diarization, word-timestamp error

### Takeaway
Section downloads are keyframe-inaccurate unless you re-encode. Cuts fall back to the previous keyframe, which can be 10 s or more early. YouTube auto-captions expose only word **start** times, in an undocumented format. On 2026 benchmarks, ASR-bundled word timestamps are much coarser than classical forced alignment: MFA has about 20 ms mean word-boundary error, while NeMo, WhisperX and Parakeet are roughly 40–110 ms depending on the benchmark. Parakeet-TDT reports on an **80 ms grid** with about 80 ms MAE. Many systems also carry a systematic early or late bias, and utterance-**end** boundaries are the hardest. Diarization (pyannote Community-1) still has about 20–30% DER on hard conversational audio, so use it as a warning flag, not ground truth.

### Cited Findings
**yt-dlp section download**
- [DOC] `--download-sections "*start-end"` downloads time ranges (needs ffmpeg). `--force-keyframes-at-cuts` forces keyframes at cuts; it "is slow due to needing a re-encode, but the resulting video may have fewer artifacts around the cuts." The default is not to force keyframes. — [yt-dlp README](https://github.com/yt-dlp/yt-dlp/blob/master/README.md)
- [DOC] yt-dlp FAQ: "Video files cannot be cut at exact timestamps without re-encoding. yt-dlp does not re-encode the video by default." — [yt-dlp FAQ](https://github.com/yt-dlp/yt-dlp/wiki/FAQ)
- [DOC, maintainer comment, older: 2023] Without forced keyframes, ffmpeg "will always fallback to the previous keyframe, even if the previous keyframe was 9 seconds behind." Keyframe spacing "can be 10 seconds or greater." — [yt-dlp issue #8011](https://github.com/yt-dlp/yt-dlp/issues/8011)
- [DOC, older: 2024] Example: a requested 30–58 s range produced a 38 s file starting at 20 s until `--force-keyframes-at-cuts` was added. This also affected audio-only extraction. — [yt-dlp issue #10970](https://github.com/yt-dlp/yt-dlp/issues/10970)

**YouTube auto-caption word timing**
- [3P] Auto-caption tracks in `json3`/`srv3` carry per-word offsets: word start = `tStartMs + tOffsetMs`. YouTube does not document these formats. They are "word start times only. Derive ends from the next word's start … and expect them to be approximate." Manual tracks are usually timed per line only, and manual captions "condense speech, drop disfluencies … and can be offset in time." — [Corpora blog: yt-dlp subtitles](https://globalcorpora.com/blog/yt-dlp-download-subtitles-auto-captions/)
- [DOC, open-source parser] The json3 reader produces no confidence values per word. Word ends follow a start-only rule (the next word's start, or the cue end). — [subtitle-toolbox-go issue #102](https://github.com/yama6a/subtitle-toolbox-go/issues/102)
- [3P] YouTube's ToS restricts automated access and downloading. At volume, subtitle requests hit the same anti-bot systems as video ("Sign in to confirm you're not a bot"). — [Corpora blog](https://globalcorpora.com/blog/yt-dlp-download-subtitles-auto-captions/)

**Forced alignment and ASR word-timestamp accuracy**
- [PAPER, Jun 2026] MFA 3.0 word alignment, mean boundary error: **TIMIT 19.93 ms** (66.5% of boundaries within 25 ms, 91.6% within 50 ms) and **Buckeye 21.75 ms**. ASR-based aligners: **NeMo 78.24 ms** TIMIT / 88.62 ms Buckeye (15.5% within 25 ms); **WhisperX 110.04 ms** / 110.90 ms (4.2% within 25 ms); MMS 43.06 / 49.54 ms. This paper scores word *beginning* timestamps. It notes that for neural aligners "the beginning of one word does not match the ending of the previous word." — [arXiv 2606.18466: MFA and the state of alignment in 2026](https://arxiv.org/abs/2606.18466)
- [PAPER, 2024, older] Using word *end* timestamps, WhisperX scored 34.3 ms mean (23.5 ms median) on TIMIT, versus MFA 21.9 ms mean (12.5 ms median). On Buckeye, WhisperX's mean blew up to 11,685 ms without a 500 ms outlier threshold. Its median stayed at 30.1 ms. — [arXiv 2406.19363](https://arxiv.org/abs/2406.19363). **Conflict:** WhisperX ranges from about 34–37 ms to 110 ms across papers. The likely cause is start versus end timestamps and outlier handling, so the scoring convention matters.
- [PAPER, Sep 2026] FA-Bench (21 open models plus 9 commercial APIs, clean and noisy audio): WhisperX MAE 37.2 ms on TIMIT and 41.7 ms on Buckeye. On the leaderboard, NeMo-FA (80 ms model) is at 79.2 / 91.4 ms MAE, and its 40 ms model scores better (F1 0.199 vs 0.155). Table 1 lists NeMo-FA at 47.4 ms on clean TIMIT. It is unclear which checkpoint that row uses, so this inconsistency is unresolved. — [FA-Bench paper](https://arxiv.org/html/2609.32396); [FA-Bench leaderboard](https://www.olewave.com/en/leaderboard/fa-bench)
- [PAPER] FA-Bench Track 2 (ASR output): **Parakeet-TDT** reports word boundaries on an **80 ms grid**. In the extracted table its MAE is about 79–81 ms with F1@20 ms around 0.18–0.19. I read the columns as MAE, F1@20 and WER; the parsed table lost its headers, so treat these numbers as approximate. FA-Bench notes that with an 80 ms grid "only half of the reference boundaries fall within 20 ms of such a step," which caps F1@20 near 0.5. — [FA-Bench](https://arxiv.org/html/2609.32396)
- [PAPER] FA-Bench findings: (a) "Word start and end times carry large systematic bias." Whisper is about **150 ms early**, while word durations are right to within 16 ms. Seven of eight commercial ASR APIs start words late, three by more than 50 ms. (b) "Utterance end timestamps are more difficult to estimate": end-boundary F1 is 0.17–0.18 lower than beginning or internal boundaries. (c) Re-aligning ASR output with a dedicated aligner improved F1@20 by 40% (Chirp 2 followed by Olign). (d) Recognition errors degrade adjacent boundaries. — [FA-Bench](https://arxiv.org/html/2609.32396)
- [PAPER] stable-ts (Whisper timestamp stabilisation) is included in FA-Bench. The extracted value near it was 96.8, but I couldn't confirm its column, so it is not reported as a firm figure. — [FA-Bench](https://arxiv.org/html/2609.32396)
- [PAPER] MFA's spontaneous-speech benchmark extracted utterances separated by 300 ms of silence and padded them with 200 ms of silence on each side. This is benchmark methodology, not an editing default. — [arXiv 2606.18466](https://arxiv.org/abs/2606.18466)

**Speaker diarization (clip-edge speaker detection)**
- [DOC] pyannote `speaker-diarization-community-1` DER (no collar, overlap scored): AMI-IHM 17.0%, DIHARD3 20.2%, VoxConverse 11.2%, REPERE (broadcast TV) 8.9%, CALLHOME 26.7%. The paid `precision-2` is lower (e.g. VoxConverse 8.5%, CALLHOME 16.6%). — [Hugging Face model card (benchmarks updated 2025-09)](https://huggingface.co/pyannote/speaker-diarization-community-1)
- [PAPER/benchmark, Oct 2026] Ocular Converse-Diarization (4 two-speaker conversations): Community-1 at 27.98% DER (15.01% missed, 11.01% false alarm, 1.96% confusion), effectively tied with DiariZen and Nemotron 3 Diarization. — [Ocular AI report](https://www.useocular.com/converse/diarization/report)
- [PAPER/benchmark, Sep 2026] Voice Arena (139 conversations): Community-1 at 30.6% DER at 0 ms collar, exact speaker count in 73% of sessions, undercount in 24%. — [Voice Arena Diarization-Bench](https://voicearena.com/research/diarization-bench/diarization-bench-v1-launch)
- [DOC] pyannoteAI describes overlapping speech as "the hardest problem in diarization." — [pyannoteAI blog](https://www.pyannote.ai/blog/overlapping-speech-and-speaker-separation-the-hardest-problem-in-diarization)

### Inferences
- With Parakeet's 80 ms grid and roughly 80 ms MAE, cutting exactly at reported word edges will sometimes clip the first or last phoneme, or include a breath or the interviewer's previous syllable. Pad the edges, then snap to the nearest low-energy gap. Optionally refine just the two edge boundaries with a dedicated aligner (MFA had about 20 ms error).
- End boundaries are the least reliable, so give the clip's tail more pad or a longer fade than the head.
- Systematic bias (whole-system early or late shifts) means we should measure Parakeet's mean signed offset on a few hand-labelled clips of our own and correct for it, rather than assume zero bias.
- Diarization at 10–30% DER is good enough to *flag* "another voice within N ms of the edge" for review or rejection, but not to make silent automated decisions. Broadcast-style audio (REPERE about 9%) is easier than conversational audio.
- Download a padded window (several seconds either side), then do the frame-accurate cut locally in our own FFmpeg step. This avoids relying on yt-dlp keyframe behaviour for exact edges and leaves material for later adjustment.

### Gaps
- I found no quantitative benchmark of **YouTube auto-caption word-start accuracy** against forced alignment. Sources only say "approximate."
- No direct benchmark of the NeMo Forced Aligner (NFA) tool with Parakeet-TDT checkpoints at 40 ms versus 80 ms for word *edges* in broadcast speech.
- Standalone WhisperX or stable-ts figures beyond those above were not extracted.

---

## 6. Replacing a narrator's spoken quote with original tape: precedents (radio, podcast, dubbing)

### Takeaway
Radio journalism treats "read the quote" and "play the tape" as distinct writing choices, not interchangeable audio. NPR guidance is to let tape carry core ideas, write *into* and *out of* the tape, and not repeat the tape's words in the narration. Its accuracy guideline requires an actuality to reflect what the speaker was responding to. That supports a replace design in which the narrator's surrounding lines are written as lead-ins. A verbatim narrator re-reading of the quote is a different editorial object, and should be explicitly framed as a quotation when used as the fallback.

### Cited Findings
- [DOC, NPR Training, May 2025] Radio stories use more quotes ("actualities," "clips," "tape") than print, roughly 50% copy and 50% tape. Sources should "articulate the core ideas of the story," and radio often introduces ideas *in the quote first*, then the reporter "write[s] through" the sound. Quotes that read well can "sound terrible" (boring, hard to hear, lacking passion). — [NPR Training: print to radio](https://www.npr.org/sections/npr-training/2025/05/30/g-s1-65814/the-journey-from-print-to-radio-storytelling-a-guide-for-navigating-a-new-landscape)
- [DOC, NPR Training, Feb 2026] "It's tempting to think of actualities as quotes. Especially nowadays with the availability of transcription software … This is a mistake. What the words say may be less important than how they are said." The author wrote "in and out of the act." — [NPR Training: radio reporting tips](https://www.npr.org/sections/npr-training/2026/02/05/g-s1-107659/radio-reporting-tips)
- [DOC, NPR Ethics: Accuracy] An actuality "should reflect accurately what that person was asked, was responding to or was addressing." When quoting or paraphrasing, "consider whether the source would agree with the interpretation." — [NPR Accuracy guideline](https://www.npr.org/about-npr/688139552/accuracy)
- [DOC, book excerpt, older] Jonathan Kern's *Sound Reporting* (NPR guide): a radio journalist must make sure that an actuality "is never edited in such a way that it distorts the speaker's meaning." Online text quotes from radio stories "have to be absolutely accurate" because listeners can compare them with the audio. — [U. Chicago Press excerpt](https://press.uchicago.edu/Misc/Chicago/431789.ht)
- [3P, teaching blog] Broadcast-writing rule: "Use direct quotes only when a paraphrase doesn't work better … (unless you have a sound bite)." Attribute at the start of the sentence. — [apjgibson broadcast writing](https://apjgibson.wordpress.com/broadcast-writing-2/)

### Inferences
- In our replace mode, the narrator's lines around the quote should be written as a lead-in ("Huang told the audience…") and a write-out, not as a sentence that also paraphrases the quote. Otherwise the clip duplicates the narration, which NPR guidance warns against.
- The fallback (narrator reads the quote) works best with attribution placed at the *start* ("As Huang put it, …"), because the same lead-in then works for both the tape and the read version. This is our inference from broadcast attribution practice, not a documented editorial standard.
- The accuracy guideline implies storing and showing the question or context preceding the clip during approval, not just the trimmed words.

### Gaps
- I found no documented precedent of a tool that *automatically* swaps a narrator's read of a quote for original tape at render time. Dubbing and ADR workflows were not researched within budget.
- BBC Academy and Transom guidance on tape versus read quotes was not fetched. The "quote … unquote" convention for read quotes on air is not sourced here.

---

## Lessons and design implications for our pipeline

These are synthesised from the findings above. Each one names the evidence it rests on.

1. **Two-stage find, then verify.** Use a caption index (Filmot API or yt-dlp caption fetch) only to shortlist videos and coarse times. Always re-transcribe the downloaded window with Parakeet and require a fuzzy-but-high verbatim match before a clip is eligible. Index text can be stale or derived, and manual captions are condensed or offset (Filmot README, Corpora blog).
2. **Download wide, cut locally.** Request a section padded by several seconds, or use `--force-keyframes-at-cuts`. Without re-encoding, cuts fall back to the previous keyframe, which can be 10 s or more early (yt-dlp FAQ and issues). Do the exact trim in our own FFmpeg step.
3. **Don't trust word edges raw.** Parakeet-TDT reports on an 80 ms grid with about 80 ms MAE, and ASR timestamps carry systematic bias (FA-Bench). Pad each edge, snap to the nearest low-energy gap, and give the **tail** more slack because end boundaries are hardest. Consider refining just the two edge boundaries with MFA (about 20 ms error) or NeMo Forced Aligner, and calibrate Parakeet's signed offset on a handful of hand-labelled clips.
4. **Reject rather than force.** Copy Descript's "Avoid harsh cuts" behaviour: if there is no clean gap near the quote's first or last word (or another speaker intrudes), mark the candidate unusable or widen to the sentence boundary. Then fall back to the narrator take instead of shipping a clipped bite.
5. **Use diarization as a flag.** Run pyannote over the padded window to detect a second speaker near the edges, but route positives to human review. Community-1 still shows about 20–30% DER on conversational audio, and overlap is the weakest case.
6. **Always fade at joins and match loudness.** Every editor reviewed applies fades or healing at cuts, but none publishes numbers, so pick short speech fades and tune by ear. Normalise clip loudness to the narrator's target. The self-reported Neon Bulletin pipeline uses -16 LUFS for voices. Clips bring their own room tone, so expect an audible source change and keep fades short rather than trying to synthesise matched room tone.
7. **Keep approval and fallback as first-class objects.** Resolve's alternates on disabled tracks, Descript's "Restore removed media," and Neon Bulletin's private-until-reviewed uploads all keep a human in the loop. Our "approved clip, else narrator" model matches this, so store both and allow a one-click swap.
8. **Write for tape.** The narrator's lines should lead into and out of the quote, with attribution at the start, and should not paraphrase the quoted content (NPR Training). This lets the same script work in replace mode and in fallback mode.
9. **Context is part of the clip.** Per NPR's accuracy guideline, show the reviewer the preceding question or sentence and the source video's date and title. Put speaker, date and source on screen, as the Neon Bulletin and VideoDB precedents do, and consider a narration-versus-media self-check like VideoDB's.
10. **Cap clip count and length.** Precedent: 5–20 s bites, at most 4 per show (Neon Bulletin, self-reported). YouTube's reused and inauthentic-content reviews are channel-wide and ignore permission or fair use, and outlets file Content ID claims on short news clips (anecdotal reports). Short, sparse, clearly commented clips reduce risk but do not remove it.
11. **Record rights per clip.** Tag each clip as government/C-SPAN, CC/public domain, corporate press kit, licensed, or YouTube rip relying on fair use. C-SPAN allows non-commercial use of federal-event footage with attribution, but monetised use needs a license and its terms restrict AI use. Reuters, Getty and AP are editorial-only, quote-based, and expensive (market estimates of about $80–100 per second). Press-kit terms (e.g. NVIDIA) were not found, so don't assume they are free.
12. **Respect platform access limits.** Automated caption and video fetching runs into YouTube's ToS restrictions and bot checks at volume (Corpora blog). Build in rate limiting and caching, and keep provenance (video ID, timestamps, transcript snapshot) for every bite.
