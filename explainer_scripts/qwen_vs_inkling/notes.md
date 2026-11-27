# Qwen3.8-27B vs Inkling 2 Mini: notes

`script.txt` holds only spoken words. It's about 2,280 words, so roughly 14 minutes at the pace of the Kimi vs GLM script. Optional cuts that bring it to about 11 minutes are listed at the end.

The research behind it is the report [Qwen vs Inkling small model showdown](../../reports/stories/ai/Qwen%20vs%20Inkling%20small%20model%20showdown.md) and its notes folder. Research was done on 27 November 2026. **No evidence has been captured yet.** Every number below still has to pass an evidence round before it goes on screen.

## How the story is built

### The viewer's question, and the promise

The viewer clicks for "which is better?". The script keeps that question, but makes it personal and gives it stakes: "Do I switch?" Naresh has something to lose, so the viewer watches a decision being made, not a table being read.

Three promises are made in the first minute and kept at the end:
1. Which model to use for what (paid off in the verdict).
2. Whether Naresh switches (paid off in "Not yet", with a plan).
3. **The one setting to check before blaming any model.** This is the main open loop. It isn't named until the twist, about 80% of the way through, so it carries the viewer through the middle.

### Story shape

1. **Cold open (about 30 seconds):** the plane, airplane mode, and the flight simulator. A concrete, visual scene, not a claim.
2. **Stakes:** "that's a problem for me", because Naresh's own software is in the same size class.
3. **The curiosity gap:** "The biggest problem wasn't either model. It was a setting… you're probably using it right now."
4. **Who's talking:** 2 sentences. Credentials plus "my own server bill", so it's personal, not a lecture.
5. **The plan:** a roadmap, so the viewer knows the video is going somewhere.
6. **Meet them:** parameters, explained once in one plain line. Then the looped model, with the writer-redrafting analogy, and a planted line: "Thinking harder doesn't teach you new facts. Hold on to that."
7. **Expectation, then a subversion:** you'd expect a clear winner, but the score is 20 vs 20. "A dead heat." That's a short line on its own, as a pattern interrupt.
8. **"A tie isn't boring":** a reframe that sets up the rest of the video.
9. **The launch posts' small print:**
   - "fewer tokens" against the most talkative model;
   - the 4.8 times chart, which is theory, against a stopwatch;
   - the text contradicting the table ("my favourite");
   - then Alibaba's small print, so it stays fair.
10. **The referees:** Inkling wins price and speed; Qwen wins office work, facts, writing votes and tool calls. **Payoff of the planted line** (thinking harder doesn't teach facts). Then The Dark Factory's sound bite as a verdict.
11. **YouTube:** the INSANE title, and Bijan Bowen admitting he "cheated a little". The flight simulator reality check, and "runs on your laptop depends on your laptop" (Naresh's own 24GB). Then the fair turn: first-week plumbing. AI Coding Daily's sound bite closes the section.
12. **"Should I switch?":** job by job, in short one-word section heads (Planning. Facts. Complicated instructions. Writing. Speed.). The contradictory-rules story is the emotional core: "the kind of mistake you don't notice".
13. **The twist:** the setting. Both models ship at maximum thinking. Willison's pelican, the 3-hour run, Unbiased Bob's sound bite, why companies do it, and then Naresh's own code.
14. **The fix and its catch:** medium effort costs 2 points and saves about 30% of tokens, but the fact score drops, so test first. Honest that this puts Qwen just below Inkling.
15. **Verdict, as of late November 2026:** Naresh's plan, then advice by situation.
16. **The clock:** Qwen4 is coming "soon".
17. **Series callback:** last video's 5 questions, plus a 6th: "What setting was it running at?"
18. **Comment prompt:** a real question viewers can answer from their own setup, not "smash that like button".

### Viewer psychology choices

- **Talking to one person:** "you", contractions, short sentences, asides ("And my favourite.", "OK. So now, my question."), admitted uncertainty ("As far as I can tell"), and a little self-deprecation (his own laptop, his own code).
- **Stakes and vulnerability:** the narrator checks his own code on camera. That makes the twist land, and it builds trust because he's not exempt from the mistake.
- **Re-hooks every 45 to 90 seconds:**
  - "Hold on to that."
  - "A dead heat."
  - "It isn't [boring]."
  - "And my favourite."
  - "So nobody's hands are completely clean."
  - "Remember the writer…?"
  - "Which brings us to YouTube."
  - "So now, my question."
  - "But that's not the twist."
  - "Remember that setting I promised you?"
- **Plant and payoff:** "thinking harder doesn't teach you new facts" is planted in the looping explanation and paid off with the hallucination numbers. "Remember that last one" (the thinking setting Alibaba doesn't state) is planted in the small-print section and paid off in the twist.
- **Fairness beats:** every time one side looks bad, the other side's weakness follows soon after (Alibaba's small print, Inkling's first-week plumbing, medium putting Qwen below Inkling). Viewers trust a narrator who isn't a fan.
- **Value the viewer keeps:** a choice by situation, one action ("turn the thinking level down, and test it on your own work"), and the 6th question.

## Things Naresh must confirm before recording

- **"Part of the software I build runs on… Qwen3.8-27B."** In Visio Studio, Qwen3.8-27B is an option per language-model role (the `llm_provider`, `description_llm_provider` and `image_prompt_llm_provider` settings). The code default is GLM-5.3 on Bitdeer (`backend/app/core/settings.py`). If no role is set to Qwen in practice, change the line to "part of the software I build can run on…".
- **The confession beat.** `backend/app/providers/qwen38.py` sends `"thinking": True` and drops `reasoning_effort` (its `to_request` keeps only the messages), so the code never picks a level. The script says only what the code shows: "unless the server picks one, Qwen runs at its highest setting." Ask the GPU server team which level `/v1/qwen38/generate` uses.
  - If it's `xhigh`, a stronger line could replace the last sentence: "And the server was running it at the highest setting. On every job."
  - If the server already uses a lower level, change the line, and the twist still works for viewers.
- **"The laptop I'm using right now has 24."** This is true of the M4 Pro this research ran on (24GB). Keep it only if that's the laptop on camera.
- **"In my last comparison video, I gave you 5 questions."** This only works if the Kimi vs GLM video is published first.
- **"My software uses these models for long writing and planning jobs. Story outlines, scene plans."** Adjust if Naresh describes it differently.

## Claims to mark for evidence

These are text evidence unless marked as a sound bite. The full quotes and URLs are in the report and its notes. "Highlight" is the wording to look for on the page.

| Script claim | Source | Highlight |
|---|---|---|
| Plane, airplane mode, flight simulator in a few minutes | [Thinking Machines, Inkling 2 Mini](https://thinkingmachines.ai/news/inkling-2-mini/) | "took Inkling 2 Mini on a flight, where it ran offline on a MacBook Pro and built a playable flight simulator in a few minutes" |
| Leads every open model of its size at coding | Same | "leads every open-weights model with less than 100B total parameters on benchmarks such as DeepSWE v1.1 (48.2%)" |
| Most downloaded open model family on Hugging Face | See `backstory_context.md` (about 54% of tracked downloads, summer 2026) | The download-share line in the cited article |
| Mira Murati, former OpenAI CTO, founded Thinking Machines | Reuters, Axios or WIRED (see `backstory_context.md`) | The founding line |
| 26.4B total, 3.4B active, about 20GB | [HF Inkling 2 Mini card](https://huggingface.co/thinkingmachines/Inkling-2-Mini) | The parameters line and "about 20GB" |
| Middle of its brain runs 3 times | [Thinking Machines](https://thinkingmachines.ai/news/inkling-2-mini/) | "running the middle layers of the model three times for every token" |
| Thinking harder doesn't add facts (the company admits it) | Same | "it doesn't enable its weights to store more facts" |
| 20 vs 20 | [Artificial Analysis comparison](https://artificialanalysis.ai/models/comparisons/inkling-2-mini-vs-qwen3-8-27b) | Intelligence Index row. Show "20 vs 20", not 20.1 or 20.11 |
| "reach the right answer with fewer tokens" | [Thinking Machines](https://thinkingmachines.ai/news/inkling-2-mini/) | That phrase |
| Most talkative in its class, 161M vs 128M | [AA Inkling page](https://artificialanalysis.ai/models/inkling-2-mini) and the comparison page | The verbosity / output tokens rows |
| 4.8 times chart is a calculation | [Thinking Machines](https://thinkingmachines.ai/news/inkling-2-mini/) | "at 614 GB/s with BF16 weights and batch size one" (the narration paraphrases this) |
| RTX 3090: 38.7 vs 34.5 | [Bench Lab](https://benchlab.ironyaditya.xyz/posts/2026-11-22-inkling-2-mini-vs-qwen-27b-pagoda/) | The decode speed table |
| Mac Studio: Qwen faster | [The Dark Factory, quick test](https://www.youtube.com/watch?v=IcjndezG9vE) | About 48 vs 37 tok/s |
| Text says behind, table says 33.4% vs 30.1% | [Thinking Machines](https://thinkingmachines.ai/news/inkling-2-mini/) | The limitations sentence and the ComplexConstraints row (2 captures) |
| Qwen compared against Opus 4.6 | [HF Qwen3.8-27B card](https://huggingface.co/Qwen/Qwen3.8-27B) | The "Opus4.6 Max" column |
| SWE-bench Pro "corrected" | Same | "problematic tasks were corrected, and all baseline models were re-evaluated on the refined benchmark" |
| $0.59 vs $3.53 per task; 175 vs 59 tok/s | [AA comparison](https://artificialanalysis.ai/models/comparisons/inkling-2-mini-vs-qwen3-8-27b) | Cost per task and output speed rows |
| About 8 times cheaper on OpenRouter | [OpenRouter Inkling](https://openrouter.ai/thinkingmachines/inkling-2-mini) and [OpenRouter Qwen](https://openrouter.ai/qwen/qwen3.8-27b) | Weighted average output price ($0.2953 vs $2.409 per million tokens) |
| Office-style tests | AA comparison | AA-Briefcase 1391 vs 1263, AutomationBench, Strategy & Ops |
| 71.4% vs 63.4% | OpenRouter pages (AA data) | The non-hallucination rate rows |
| Inkling knows slightly more | AA comparison | AA-Omniscience accuracy 20.5% vs 17.3% |
| LMArena creative writing 1379 vs 1207, 423 votes | [LLMBenchmark.ai](https://llmbenchmark.ai/benchmarks/lmarena-creative-writing) / [ModelChoice](https://modelchoice.dev/lmarena/models/inkling-2-mini) | The two rows and the vote count |
| Tool calls broke 4.2% vs 0.14% | [dottxt tool-call index](https://providers.dottxt.ai/) | Inkling 2 Mini row and Qwen's best provider row |
| 136 jobs, 123 vs 116 | [The Dark Factory](https://www.youtube.com/watch?v=cAZnPv8UgjY) | The score screen |
| About 168,000 views, INSANE | [Bijan Bowen](https://www.youtube.com/watch?v=OdMpNiByntM) | Title and view count (both change) |
| Demo on 48GB MacBook, mostly at 15 times speed | [Thinking Machines](https://thinkingmachines.ai/news/inkling-2-mini/) | "MacBook Pro (M5 Pro, 48GB) Airplane mode" and the speed label in the video |
| JeredBlu, 36GB Mac, 11 minutes; over an hour with no code | [JeredBlu](https://www.youtube.com/watch?v=DCcPlV2iHzw) | 4:14–4:21 and about 5:08–5:18 |
| 32GB or more | [HF Inkling 2 Mini card](https://huggingface.co/thinkingmachines/Inkling-2-Mini) | "Apple silicon devices with 32GB or more memory" |
| Samuel Gregory, "looks like the safer bet" | [Samuel Gregory](https://www.youtube.com/watch?v=H_sjmoqmzO8) | 9:48–10:02 |
| Gibberish until a fix; tool-calling crash | [Zero to MVP](https://www.youtube.com/watch?v=SAc7Eq64L1I); [llama.cpp #32818](https://github.com/ggml-org/llama.cpp/issues/32818) | "the model outputs gibberish"; the LM Studio grammar crash |
| 26 to 80–100 tok/s in 4 days | [Hacker News](https://news.ycombinator.com/item?id=50581260) | jakswa: "Update 4 days later: I'm up to 80-100 tok/s… chalk all the slowness talk above up to model newness." |
| "less reliable than larger models at following detailed instructions" | [HF Inkling 2 Mini card](https://huggingface.co/thinkingmachines/Inkling-2-Mini) | That phrase |
| Contradictory rules: 4,000 vs 32,000 tokens | [The Dark Factory](https://www.youtube.com/watch?v=cAZnPv8UgjY) | 8:29–8:41 (manual captions). The narrator tells it, because it is full of numbers |
| 16GB card: 38.2 vs 6.1 | [CyberQ](https://cyberq.tw/2026/11/21/inkling-2-mini-debuts-5b-enables-a-loop/) | The RTX 5060 Ti figures |
| Full speed only on NVIDIA's newest chips | See the report (NVFP4 is accelerated on Blackwell-class GPUs) | Needs a clean source line; soften to "newest NVIDIA chips" if only implied |
| Qwen default is xhigh | [HF Qwen3.8-27B card](https://huggingface.co/Qwen/Qwen3.8-27B) | The default reasoning-effort line |
| Willison: 21 minutes, 22,276 and 3,223 tokens; "absolutely not a good way" | [Simon Willison](https://simonwillison.net/2026/aug/16/qwen-38-27b/) | "took 21 minutes to generate, using 22,276 reasoning tokens to produce 3,223 tokens of output" and "It's absolutely not a good way to run the model" |
| Over 3 hours, more than 180 tool calls | [Hacker News](https://news.ycombinator.com/item?id=50581260) | chriddyp: "it worked for over 3 hours on my Mac Mini, taking over 180 tool calls" |
| "essentially broken" | Same thread | solarkraft: "the default configuration is essentially broken" |
| Medium: 20 to 18, about 30% fewer tokens, 31.2 to 25.6 minutes, fact score drops | [AA comparison](https://artificialanalysis.ai/models/comparisons/inkling-2-mini-vs-qwen3-8-27b) and [AA Qwen page](https://artificialanalysis.ai/models/qwen3-8-27b) | The xhigh and medium rows (128M to 89.3M tokens; AA-Omniscience −6 to −36) |
| Smaller open Qwen4 models "soon" | [Alibaba Group, 16 Nov 2026](https://www.alibabagroup.com/en-US/document-2060139246777270272) | "Open-weight, smaller-scale models from the Qwen4 series will soon be released" |

## Sound bites

Each lead-in names the speaker and ends with a colon, as `backend/app/services/soundbite_rules.py` asks. Each quote is a whole sentence inside one pair of quotation marks. If a clip can't be cut, the narrator reads the quote and the sentence still works.

| Quote in the script | Video | Time | Captions | Note |
|---|---|---|---|---|
| "The new American model is as good as people say, but only by a little." | [The Dark Factory](https://www.youtube.com/watch?v=cAZnPv8UgjY) | from about 12:57 | Manual | Best of the four. Check the speaker is on camera |
| "I have to be honest and say I cheated a little because I'm just using it from their API." | [Bijan Bowen](https://www.youtube.com/watch?v=OdMpNiByntM) | about 7:37–8:07 | Auto | The spoken sentence goes on (", though I do have it running on the system behind me"). Cut after "API", or quote the full sentence |
| "It's a little bit overhyped on Twitter, but it's a really strong contestant for local AI model." | [AI Coding Daily](https://www.youtube.com/watch?v=XKISwJQJwws) | 13:25–13:35 | Auto | The host isn't named, so the lead-in names the channel |
| "It also just seems like a bunch of word salad that has no real point." | [Bijan Bowen](https://www.youtube.com/watch?v=OdMpNiByntM) | about 26:13 | Auto | About Inkling's long creative writing |
| "Inkling 2 Mini is an incredible coding model that launched yesterday with some really unfortunate defaults and support from llama.cpp in particular." | [Unbiased Bob](https://www.youtube.com/watch?v=tBtmWBwcgP4) | 0:00–0:07 | Manual | The clip starts with "Okay, guys," so cut after it |

All timestamps can be off by about 2 seconds, and none of the speakers has been confirmed on camera. Check each line against the audio, because the auto-captions garble "Qwen".

Left out on purpose:
- **Kai's "the chart said five times faster… the stopwatch said a third of Qwen's speed".** It's a great line, but it describes launch-night local runs, and his accuracy data relays a test whose original post wasn't found.
- **Morgans Code's "Not yet, but… my answer isn't just keep Qwen".** It would steal the verdict.

## Left out on purpose

- **Nick Greece's 2,031-job test, Plotly's "a 14th of the tokens", and DHH's overnight eval.** All 3 are second-hand and fit the story too neatly. Kai's two retellings of Greece's test also disagree on which model was more accurate.
- **The Vals Index drop (46.5% to 44.03%, 38th of 43).** It's a good beat, but the speed chart and the text-vs-table contradiction already make the point. Add it back if a third example is wanted.
- **Funding ($5B round at $40B) and co-founder departures.** They're unconfirmed or off-topic, and the departures involve an allegation.
- **Looping and monitoring (reasoning that is never written down).** It's interesting but would need a minute of its own, and the lab says it found no real loss of monitorability.
- **The datacenter speed test (Qwen FP8 at 189 tok/s on an H200).** It's from a tester with a disclosed interest, so the script says only that the gap mostly disappears on bigger cards.

## Facts that will go stale

Re-check these right before recording:
- The Artificial Analysis scores, speeds, cost per task and token counts. They are rolling averages, and Inkling's speed fell from 280 to 175 tok/s in 5 days.
- The OpenRouter prices, the dottxt tool-call rates and the LMArena scores and vote counts.
- The YouTube view counts and titles.
- Whether small open Qwen4 models have been released. If they have, the ending needs rewriting.

## Pronunciation checks for the voice

- Qwen ("chwen", as Alibaba says it; confirm)
- Qwen3.8-27B ("Qwen three point eight, twenty-seven B")
- Inkling 2 Mini
- Mira Murati ("MEER-uh moo-RAH-tee")
- Techsergy ("TEK-ser-jee"; confirm)
- xhigh ("extra high")
- LMArena ("L-M Arena")
- llama.cpp ("llama C-P-P")
- JeredBlu ("Jered Blue")
- OpenRouter

## Optional cuts to get to about 11 minutes

Together these save about 450 words:
- **"To be fair, Alibaba's small print isn't clean either" paragraph (about 75 words).** Keep the sentence about the missing thinking setting, because the twist pays it off.
- **The Mac Studio sentence in the speed chart paragraph (about 15 words).**
- **The LMArena and tool-call paragraph (about 75 words).** It is the weakest of the referee points for viewers.
- **The first-week plumbing paragraph, apart from its last line (about 70 words).** Keep "you're often judging the plumbing".
- **The 16GB card sentence and the NVIDIA format sentence (about 50 words).**
- **The Hacker News "essentially broken" line and the 3-hour run (about 50 words).** Unbiased Bob's sound bite carries the point.
- **The Qwen4 paragraph (about 30 words).** Only cut this if no Qwen4 news lands before publishing.
- **"Because a model at its highest setting…" (about 35 words).**
