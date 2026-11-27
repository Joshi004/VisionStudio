# Community reports: Inkling 2 Mini vs Qwen3.8-27B (as of 27 November 2026)

Scope note for the writer: Inkling 2 Mini came out on 20 November 2026, one week before these notes. Almost all Inkling evidence is first-week, single-run, hobbyist testing on quantized community builds (mostly Unsloth/bartowski GGUFs in llama.cpp), often on runtimes that were still being patched. Qwen3.8-27B has about 3.5 months of reports. Treat the two bodies of evidence as unequal in depth. "First-hand" below means the person says they ran the model themselves; "second-hand" means a round-up, mirror or someone relaying another person's report. Reddit itself blocked direct fetching (HTTP 403), so Reddit material comes from reddit.com pages surfaced by search, from Hacker News quoting Reddit, from a Korean mirror (aiwitness.kr), or from round-up sites, and is flagged as such.

Provenance warning: two round-up/test sites used below — `inkling2mini.novcog.us.com` (an Inkling-branded site) and `kingy.ai` — publish their methods but their ownership/independence is unknown. The Blixild (dev.to) test is by a company that sells hosting for all three models it tested (disclosed in the post). The Atomic Agent Qwen report is by the agent's builders (disclosed).

## 1. What do Reddit and Hacker News praise and complain about?

### Takeaway
Inkling 2 Mini: praised as a fast, laptop-sized coder and tool-user that "might replace Qwen 27B"; criticised for overlong reasoning and runaway loops at the default effort, weak factual knowledge (invents things, then argues), stubbornness, and a very rough first few days of runtime support. Qwen3.8-27B: widely praised as the best model for ≤32 GB of VRAM and a strong coder/agent; the near-universal complaint is massive over-thinking at its default `xhigh` effort plus slowness (it is dense), and some say it is a "terrible collaborator" that over-engineers small edits.

### Cited Findings

**Inkling 2 Mini — scale of attention**
- HN launch thread "Inkling 2 Mini (thinkingmachines.ai)": 1,488 points, 297 comments when fetched; posted by jasondavies at 2026-11-20T20:12:19Z — [HN](https://news.ycombinator.com/item?id=50581260). A 21 Nov snapshot by a round-up site recorded 1,396 points / 283 comments on HN and "1,567 upvotes · 455 comments" on the r/LocalLLaMA launch thread (archive snapshot, second-hand), plus 238,152 downloads of the Unsloth GGUF vs 7,944 of the original weights, and "34 [uncensored/abliterated copies] in 24 hours" — [novcog reactions](https://inkling2mini.novcog.us.com/reactions)
- Reddit sentiment aggregator: index 54/100 (95% interval 50–57, "above neutral") from 605 opinions in 161 threads over 7 days; ranked 11th of 19 models. Share praising by topic: coding 67% of 124 opinions; speed 49% of 250; intelligence 46% of 106; "follow-through" 39% of 102; writing & tone 41% of 41; refusals 12% of 17. r/LocalLLaMA index 52 (449 opinions), r/LocalLLM 58 (148) — [modelsentiment](https://modelsentiment.com/m/inkling-2-mini). (LLM-tagged sentiment; lists release as 21 Nov, likely time-zone difference.)

**Inkling 2 Mini — praise (quotes)**
- Thinking Machines staff note on r/LocalLLaMA, relayed on HN by montroser (2026-11-20T20:40:46Z): "Hope that folks find this model more amenable to local usage - the sizing was largely informed by what folks on this subreddit ask for the most haha!" and "folks like Unsloth have noticed that our models seem to respond very well to being quantized, maintaining 90% top-1 even at at 1-bit quantization." (second-hand relay of a vendor comment) — [HN](https://news.ycombinator.com/item?id=50581260)
- montroser: "This is bonkers good if these benchmarks hold up in real-world scenarios. To be at the level of Qwen3.8-27B with a looped transformer model is quite the flex." — [HN](https://news.ycombinator.com/item?id=50581260)
- reissbaker (2026-11-21T04:17:35Z): "It beats Qwen on effectively every coding benchmark… Still super impressive, and probably replaces Qwen 27B in pretty much any workload!" (benchmark-based opinion, not hands-on) — [HN](https://news.ycombinator.com/item?id=50581260)
- dgacmu (2026-11-21T02:40:12Z), M1 Pro 32 GB: "write a python program to sort a csv… Result: Nailed it. Nice python program. Nice explanation of output, if a little chatty" and "One of the first models that seems OK running side-by-side with a browser on my older MBP." — [HN](https://news.ycombinator.com/item?id=50581260)
- An HN commenter using oMLX + pi: "I found its coding style to be concise and lean" (vs a 2-bit DeepSeek 4.1 Flash on a 64 GB Mac) — [HN](https://news.ycombinator.com/item?id=50581260)
- chr15m (2026-11-21T02:46:20Z): "Might replace Muse Glimmer for me for local tool calling workloads. As good as Qwen 27b for many tasks and no state mandated censorship - yes please!" — [HN](https://news.ycombinator.com/item?id=50581260)
- chriddyp (2026-11-21T09:11:48Z), 43-question data-analytics exam: "It scored a 'B' on the exam… It's the most accurate U.S. open weight model that fits on a Mac mini that I've tested… Against other models its size, the only model that got a better score was Qwen 3.8 27B(it got a B+)." — [HN](https://news.ycombinator.com/item?id=50581260); tabular results on the parent benchmark page: [Plotly DataAnalyticsBench](https://plotly.com/blog/introducing-dataanalyticsbench/) (the Inkling-specific Plotly post URL was truncated in the HN comment and could not be recovered)
- capv (2026-11-21T03:57:44Z): "In my tests inkling-2-mini shows results similar to GPT 5.6 with light reasoning. Impressive ..." — [HN](https://news.ycombinator.com/item?id=50581260)
- Korean-mirrored r/LocalLLaMA thread comment (translated by mirror): the community mood is good, people are "experimenting with settings and sharing results instead of just arguing about benchmarks"; another: "if it works properly it looks pretty promising" — [aiwitness.kr mirror](https://aiwitness.kr/community/1y1vv9p)

**Inkling 2 Mini — complaints (quotes)**
- dofm (2026-11-20T22:53:22Z), Unsloth Q4, default "extra high": "The model burned through 19200 thinking tokens on this task (which was the hard limit I had set) and didn't finish." Later: "it went down a significant rabbit hole to try to make some code work off the basis of a 'core' wordpress hook it had actually invented, and nothing I could do would get it to use the correct hook." And: "it would repeatedly EOT rather than actually run the tools it was saying it would call. Whether this is the model failing or Unsloth's harness and the model disagreeing, I don't know." — [HN](https://news.ycombinator.com/item?id=50581260)
- dofm, after retesting on Low: "it appears to accept correction much more quickly… I pointed it out, it doubled down, I asked it to check online, it checked and was done; fixed its mistake and moved on fine." Also: "It's such an interesting model — perky, overconfident, makes suggestions" — [HN](https://news.ycombinator.com/item?id=50581260)
- akazantsev (2026-11-21T15:56:19Z): "Yeah, many mention that this model is very suspicious of users' input." — [HN](https://news.ycombinator.com/item?id=50581260)
- drdaeman (2026-11-21T22:18:10Z): "It's a pretty stubborn model, for some reason… it pushed back still, zero chill. Also, this model takes everything literally. Can't understand or even detect humor at all… Somehow, Qwen3.6/3.8 was more... humane in this regard." — [HN](https://news.ycombinator.com/item?id=50581260)
- dgacmu: coin-identification test "Failed miserably, I gave up after 12,000 tokens of it babbling incessantly… slightly annoying it seemed to get in a loop." — [HN](https://news.ycombinator.com/item?id=50581260)
- chriddyp: "The main limitation that I saw was a 'runaway loop' when asked to find a issues in a dataset: it worked for over 3 hours on my Mac Mini, taking over 180 tool calls to answer the question before I cut it off." — [HN](https://news.ycombinator.com/item?id=50581260)
- RandyOrion (2026-11-21T06:32:32Z): "The problem I observed is that in SWE workflows the output length of inkling is longer than qwen 3.8 27b xhigh, which is already notorious. Multilingual support except English is another pain point." — [HN](https://news.ycombinator.com/item?id=50581260)
- sourcecodeplz (2026-11-20T22:30:16Z): "Even more talkative than Qwen" — [HN](https://news.ycombinator.com/item?id=50581260)
- stymaar (2026-11-21T05:17:36Z), reacting to Artificial Analysis token chart: "So much for people who see looping transformers as a way of cutting token output down." — [HN](https://news.ycombinator.com/item?id=50581260)
- causal (2026-11-20T22:03:06Z): "those Terminal Bench numbers are pretty abysmal, and I find that tends to track 'agent usefulness' more than most SWE benchmarks." — [HN](https://news.ycombinator.com/item?id=50581260)
- relistan (2026-11-21T19:22:21Z), 36 GB MacBook Pro: "still not really worth using for much… the context has to be kept too small to fit in memory. But it's progress." — [HN](https://news.ycombinator.com/item?id=50581260)
- r/LocalLLaMA thread "At the risk of going against the popular grain…" reported the model "over-writing" bash commands; HF discussion by pathosethoslogos: "The context is 262k, where 65536 tokens are for output. It went over 65k tokens multiple times. It's been the same for me." john1248: a system-prompt instruction to write short bash calls "doesn't always work" — [HF discussion #16](https://huggingface.co/thinkingmachines/Inkling-2-Mini/discussions/16) (original Reddit thread: [r/LocalLLaMA 1y1u4ac](https://old.reddit.com/r/LocalLLaMA/comments/1y1u4ac/at_the_risk_of_going_against_the_popular_grain), not fetchable)
- Reddit quotes relayed by round-up (second-hand): Melodic-Clue9555: "looping is supposed to reduce the amount of output tokens, not increase it."; Nepertia: "A MoE that devours VRAM like a dense."; MerePotato: "Support was merged for the model (in my opinion) before it was ready" — [novcog reactions](https://inkling2mini.novcog.us.com/reactions)

**Vendor's own admissions (useful context for which complaints are "expected")**
- Model card: "In internal testing the model sometimes became stuck in long reasoning loops, or repeatedly re-checked its own work without making progress, particularly when debugging code." Also "It is more likely than larger models to state incorrect information with confidence." and "Output quality can be lower outside English. In testing in Chinese we observed clipped phrasing and mixed languages." — [HF model card](https://huggingface.co/thinkingmachines/Inkling-2-Mini)
- Launch post: "Inkling 2 Mini is not the strongest small model for multi-turn chat or for instructions with many constraints: it scores 50.0% on MultiChallenge and 33.4% on ComplexConstraints v1.1, behind Qwen3.8-27B on both." — [Thinking Machines](https://thinkingmachines.ai/news/inkling-2-mini/)

**Qwen3.8-27B — praise (quotes)**
- u/Material-Database-24 (r/Qwen_AI, 2 Oct 2026, 25 pts): "It's the best model for machines with 32gb or less VRAM. Just turn thinking to medium and don't expect Opus5.5 or 1M context." — [r/Qwen_AI](https://www.reddit.com/r/Qwen_AI/comments/1wvw8hv/tell_me_about_what_your_experiences_with_qwen_38/)
- u/LocalAI_Amateur (same thread): "It's really quite a step up from Qwen 3.6 27b even at low or off thinking. I find high thinking to get in the way sometimes when debugging… xhigh is not meant for daily driver, only for when you need some oomph." — [r/Qwen_AI](https://www.reddit.com/r/Qwen_AI/comments/1wvw8hv/tell_me_about_what_your_experiences_with_qwen_38/)
- u/OleCuvee (same thread), Dell GB10 128 GB, vLLM + DFlash2: "about 50-60tok/s, good reasoning, super reliable to stay on track with a given task… I still use frontier models for reasoning, ideating, creating concepts, but then hand over to qwen locally to do the job - it always delivers (so far)." — [r/Qwen_AI](https://www.reddit.com/r/Qwen_AI/comments/1wvw8hv/tell_me_about_what_your_experiences_with_qwen_38/)
- u/MakionGarvinus: "it's super smart and very capable… can fine errors like nothing else. I do have to set the thinking/reasoning to minimum though, it does overthink a lot." — [r/Qwen_AI](https://www.reddit.com/r/Qwen_AI/comments/1wvw8hv/tell_me_about_what_your_experiences_with_qwen_38/)
- Simon Willison (16 Aug 2026), headline: "Qwen 3.8 27B is excellent, but it defaults to wildly overthinking things"; "It's a great model, but wow that default setting is a bad place to start." — [simonwillison.net](https://simonwillison.net/2026/Aug/16/qwen-38-27b/)
- HN commenter in the Inkling thread: "I run qwen 27b fine on 24gb VRAM, with room for 200k context. It's a little tight but it works well enough… 32gb is very comfortable." — [HN](https://news.ycombinator.com/item?id=50581260)

**Qwen3.8-27B — complaints (quotes)**
- u/Chuyito (r/LocalLLaMA, 2 Sep 2026, 184 pts, 142 comments), title "Everyone is t/s maxing.. 3.8.. but after a week of using it for work I'm tempted to switch back to 3.6": "'Qwen 3.8 is a damn good coder, but a terrible collaborator'… It modifies SO many things in my scripts for what should be a 2 line PR, I get a 100 line linter style mess… It can't maintain a common style" — [r/LocalLLaMA](https://www.reddit.com/r/LocalLLaMA/comments/1w4wjxd/everyone_is_ts_maxing_38_but_after_a_week_of/)
- Simon Willison: default `xhigh` reasoning "is a hilarious default. It's absolutely not a good way to run the model"; one prompt "took 21 minutes to generate, using 22,276 reasoning tokens to produce 3,223 tokens of output"; with reasoning off the same prompt "produced 3,715 tokens and took 137s"; "I've been getting around 15-30 tokens a second from LM Studio… The only thing holding this back from being a daily driver is performance." — [simonwillison.net](https://simonwillison.net/2026/Aug/16/qwen-38-27b/)
- u/No_Oil_6152 (r/Qwen_AI OP): "it overthinks a lot and token generation is slow on my rig so I can't really 'iterate' with it interactively, but I have found the code it generates (greenfield) is pretty good." — [r/Qwen_AI](https://www.reddit.com/r/Qwen_AI/comments/1wvw8hv/tell_me_about_what_your_experiences_with_qwen_38/)
- u/breake (r/vibecoding, 21 Aug 2026), M2 Ultra: "Ships confident-but-wrong code on implicit/underspecified requirements"; "One prior attempt hung ~6.5 min and produced zero files before retry" — [r/vibecoding](https://www.reddit.com/r/vibecoding/comments/1vuvlp4/qwen38_27b_tried_a_real_life_test/)
- solarkraft (HN, 2026-11-21T13:29:45Z): "Qwen, even on low reasoning, takes forever (I have a 400GB/s Mac, for context)." — [HN](https://news.ycombinator.com/item?id=50581260)

### Inferences
- The two models share the same headline complaint — too much reasoning at the shipped default — and both communities converge on the same fix: turn effort down. For Inkling the default is "high"/0.9 per the shipped chat template (several HN users perceived it as "extra high" via Unsloth), for Qwen it is `xhigh`.
- Inkling's distinctive complaints (invents facts then defends them, stubborn, literal) line up with the vendor's own statement that looping does not add knowledge. Qwen's distinctive complaint is over-engineering/style drift in small edits.

### Gaps
- Could not read the r/LocalLLaMA Inkling launch thread (1y1diuk) or the "popular grain" thread directly (Reddit returned 403). Comment wording from those threads is only available via relays.
- No r/singularity or r/MachineLearning threads on either model surfaced in searches.

## 2. Has anyone switched from Qwen3.8-27B to Inkling 2 Mini, or compared them on the same work?

### Takeaway
Yes, a handful, all within the first week — and results split. Reported switchers cite speed and more room for context on 24 GB cards; at least two head-to-heads found Qwen better or Inkling worse on their own work. Structured tasks at low reasoning were a tie or slight Inkling edge in two small published tests. Nobody found to date reports switching a long-form writing + JSON pipeline like the narrator's.

### Cited Findings

**Switched / leaning to Inkling (first-hand)**
- rsolva (HN, 2026-11-22T12:14:35Z), AMD 7900 XTX 24 GB: "I get better speed on decode and prefill than Qwen 3.8 27B, and much more kv cache! So far this seems to be a nice upgrade an will replace Qwen 3.8 27B as a workhorse on my local machine. I still have to use it more extensively to evaluate its coding behaviour." Also: "It speaks Norwegian fluently, which even the Qwen 3.8 Flash Next failed miserably at!" Numbers: "63 tok/s decode (70–110 code, n-gram), 1.5–2.2K tok/s prefill, 384K ctx × 4 slots in 23 GiB" (patched llama.cpp/ROCm) — [HN](https://news.ycombinator.com/item?id=50581260)
- DHH (@dhh, 26 Nov 2026, via a nitter mirror — second-hand; the mirror text is garbled where a handle was stripped): "American open-weight models can too 's Inkling2 Mini just beat Qwen3.8 27B in my overnight eval shoot-out for best model for a 48-64GB RTX Spark on Omarchy malleability." — [nitter mirror](https://nitter.gq/dhh/status/2125845831051858053)
- Sebastian Christiansen (@CerebralCoding_, reply to DHH, via mirror): "I've been slowly moving off Qwen3.8 27B to Inkling 2 Mini on my Mac too, and public Mac Studio runs have it at 110 tok/s vs 48 for 27B." — [nitter mirror](https://nitter.gq/dhh/status/2125845831051858053)
- Kresimir Kos (@kkos, reply, via mirror): "Switched from Qwen 3.8 Flash Next to Inkling2 mini for testing - so far much faster and shorter reasoning with little slower tok output." (note: Flash Next, not 27B) — [nitter mirror](https://nitter.gq/dhh/status/2125845831051858053)

**Head-to-heads where Qwen won or Inkling disappointed (first-hand)**
- nittanymount (HN, 2026-11-23T02:03:09Z): "using omlx with Qwen3.8-27B-UD-Q4_K_M vs. Inkling-2-Mini-oQ4e-mtp, tried to create a loan payoff calculator/schedule web app. qwen works better and faster." — [HN](https://news.ycombinator.com/item?id=50581260)
- chriddyp: Qwen3.8-27B B+ vs Inkling B on a 43-question data-analytics exam — [HN](https://news.ycombinator.com/item?id=50581260)
- Anonymous reply under the Thinking Machines launch post (via xitter mirror; username not shown in mirror): "Just ran it through 200 mixed test and it lost. Only got 73% vs 27b 86% sooo maybe it passed on a controlled test and it's slower despite being a MOE" — [xitter mirror](https://xitter.gq/superalesha/status/2123874928600469918)
- Round-up relays a 7900 XTX user "rusl1" reporting 20 tok/s for Inkling "against 90 for Qwen 27B" (second-hand, early build) — [novcog reactions](https://inkling2mini.novcog.us.com/reactions)

**Small published side-by-side tests**
- Blixild AI (Jacek Garbuliński, dev.to, 22 Nov), 5 agent tasks × 54 runs per model on an RTX 5090: guided prompt — Inkling 27/27 vs Qwen3.8-27B 21/27 (Qwen stalled by inventing an argument like `{"void": "true"}` for a no-argument tool and retrying); short prompt — Inkling 20/27 vs Qwen 26/27, mostly because Inkling asked before accepting a price rise: "Do you want me to confirm and place the order with the updated B-210 price (129.00), or do you want something else?" Speeds: Inkling 161 tok/s vs Qwen 4-bit 68 tok/s (136 with built-in draft). Inkling had 1–4 s time-to-first-token on 121 of 357 requests, "its cause is not yet known." (Author's company sells hosting of all three models.) — [dev.to](https://dev.to/jacek_garbuliski/inkling-2-mini-vs-qwen38-27b-and-arete-27b-on-agent-tasks-54ii)
- Kingy Lab (20 Nov), 12 short fixtures × 3 attempts, low reasoning, temperature 0.7: strict totals Inkling (Runpod/vLLM) 36/36; Qwen3.8-27B (via Wafer on Vercel) 30/36. Two Qwen misses were the grader rejecting valid `LIKE` queries (32/36 after correction); three were one screenshot error — Qwen "read the letter O in the product code as a zero" (`M-06OB` → `M-060B`). "JSON answers passed only if the keys, value types and values all matched." — [kingy.ai](https://kingy.ai/blog/inkling-2-mini/)
- novcog test, MacBook Pro M4 Pro 48 GB, llama.cpp mainline, 12 jobs, 1 run each: both 12/12 correct; Inkling wrote 29% more tokens (mean 1,446 vs 1,120) but finished 1.6× faster in total (678 s vs 1,078 s), generating at 25.7 vs 12.7 tok/s median. One job (Roman numerals) took Inkling 6,053 tokens vs Qwen's 1,852, "re-checking its own work." — [novcog test](https://inkling2mini.novcog.us.com/our-test)

### Inferences
- Pattern: Inkling tends to win on *wall-clock time* (faster tokens) even when it writes *more* tokens; Qwen tends to win or tie on *accuracy per task* in open-ended work. For a batch writing pipeline on a rented GPU, that trade is the core question.
- The Blixild result suggests Inkling is more cautious (asks before acting) and better with explicit procedures; a pipeline with a fixed, detailed prompt plays to that.

### Gaps
- No first-hand report found of anyone comparing the two on long-form prose generation with structured JSON output, or with Qwen at FP8 on a datacenter GPU vs Inkling at native NVFP4.
- No longitudinal "used it for a week of real work" Inkling reports exist yet (the model is one week old).

## 3. Quality dimensions: writing, instruction following, JSON, long context, reasoning length, verbosity, hallucinations

### Takeaway
Writing: Qwen3.8 has a substantial record — better prose than 3.6, strong summariser, but "mechanical"/literal for fiction; Inkling has almost no writing-specific reports (one sibling-model compliment). JSON/structured output: no widespread JSON complaints for either model itself; two small tests show both reliable at low effort. Reasoning length: both over-think at default; Inkling is reported as at least as verbose as Qwen in tokens. Hallucination: Inkling's weak factual recall is the most consistent complaint.

### Cited Findings

**Writing quality**
- Qwen3.8 (r/SillyTavernAI, 14 Aug): "Very very smart, followed instructions closely, waaay better prose than 3.6." — [r/SillyTavernAI](https://www.reddit.com/r/SillyTavernAI/comments/1voatfl/thoughts_on_qwen_38_27b/)
- u/No-Veterinarian8627 (same thread): for creative writing "it's not much better than 3.6… It's really nice in summarizing clearly and objectively things. Honestly, writing documentation, papers with strict rules like APA… Here it shines." — [r/SillyTavernAI](https://www.reddit.com/r/SillyTavernAI/comments/1voatfl/thoughts_on_qwen_38_27b/)
- u/Tylopodas (same thread): "It really sticks to the preset and character card without much drift, even at 20K+ context. Sometimes it can feel like its trying to hard to be in character with thinking on, so I turned it off and it was more natural… Still a bit clinical compared to Gemma… Best thing about it was its summarization ability." — [r/SillyTavernAI](https://www.reddit.com/r/SillyTavernAI/comments/1voatfl/thoughts_on_qwen_38_27b/)
- u/Plastic-Stress-6468 (r/SillyTavernAI, 25 Sep), Qwen3.8 27B Q8, 50–100k lore: "after a while it will feel very 'mechanical.' It's prose tends to be rigid/stiff. It's more of a co-writer than a DM. Tell it clearly what you want to see happen and it does quite well." Also: "Also thinks a whole lot. A whole whole lot." — [r/SillyTavernAI](https://www.reddit.com/r/SillyTavernAI/comments/1wpwwxg/my_impressions_on_current_highend_local_models/)
- A commenter in that thread: "Qwen3.8 for me was a huge improvement, especially in terms of prose. However, it takes the scenes very literal, and shows either very little in creativity, or just takes very common tropes to use." — [r/SillyTavernAI](https://www.reddit.com/r/SillyTavernAI/comments/1wpwwxg/my_impressions_on_current_highend_local_models/)
- A Hugging Face dataset diagnosing Qwen3.8-27B "word salad" in story writing: "about 5-10% word salad at temperature 1.2 whatever the server setup; 0/130 at … thinking-off settings" (sampling settings, not a model defect per se) — [HF dataset](https://huggingface.co/datasets/latkes/story-writing-feedback-diag-qwen-degeneration)
- Inkling 2 Mini writing: Hunterloftis on HN: "I haven't tried inkling so I have no idea how it speaks, writes, and tells stories." Other commenters recommended Gemma 4 for prose instead — [HN](https://news.ycombinator.com/item?id=50581260)
- jakswa (HN) on the *original* Inkling (not Mini): "When inkling first released I tested it out and thought it was the best prose from an LLM in my quick sampling -- easy-reading and easy to understand." summarity: "Inkling for prose (and vision), Deepseek 10XX for code" — refers to the Inkling family, not specifically Mini — [HN](https://news.ycombinator.com/item?id=50581260)
- liuliu (HN) on the sibling Inkling 2 Small: "its responses sometimes can be odd (they are honest about it in the blog post!), can have wrong use of markdown syntax, sometimes overly brief" — [HN](https://news.ycombinator.com/item?id=50581260)
- Reddit sentiment for Inkling 2 Mini "writing & tone": 41% praising, from only 41 opinions — [modelsentiment](https://modelsentiment.com/m/inkling-2-mini)

**Instruction following**
- Vendor: Inkling behind Qwen3.8-27B on MultiChallenge (50.0%) and ComplexConstraints v1.1 (33.4%) — [Thinking Machines](https://thinkingmachines.ai/news/inkling-2-mini/)
- Model card: "When using tools, it is less reliable than larger models at following detailed instructions…" — [HF model card](https://huggingface.co/thinkingmachines/Inkling-2-Mini)
- Contrasting field result: with a detailed, numbered procedure, Inkling passed 27/27 agent runs vs Qwen's 21/27 — [dev.to](https://dev.to/jacek_garbuliski/inkling-2-mini-vs-qwen38-27b-and-arete-27b-on-agent-tasks-54ii)
- Qwen over-reaches on scope ("2 line PR → 100 line linter style mess") — [r/LocalLLaMA](https://www.reddit.com/r/LocalLLaMA/comments/1w4wjxd/everyone_is_ts_maxing_38_but_after_a_week_of/)

**Structured output / JSON**
- Kingy test: Inkling 12/12, Qwen3.8-27B 11/12 on strict structured-data JSON fixtures (keys, types, values all matching), low reasoning — [kingy.ai](https://kingy.ai/blog/inkling-2-mini/)
- vLLM issue on Qwen3.8-27B: "`response_format: {"type": "json_schema", ...}` also works, so structured output itself is functional on this setup" (bug was in `tool_choice` enforcement, fixed in v0.29.0+) — [vLLM #54808](https://github.com/vllm-project/vllm/issues/54808)
- Groq lists Qwen3.8-27B with "JSON Object Mode, JSON Schema Mode" (context 131,072, max output 16,384 on Groq) — [Groq docs](https://console.groq.com/docs/model/qwen%2Fqwen3.8-27b)
- Inkling emits tool calls as a JSON object `{"name":…,"args":…}` inside special tokens, which runtimes must parse — [vLLM parser source](https://github.com/vllm-project/vllm/blob/a9dcfae9/vllm/parser/inkling.py)

**Long context**
- Vendor: on the variable-loop model, "performances on long-context benchmarks improve with more passes, such as GraphWalks BFS and MRCR v2"; 1M-token context window claimed — [Thinking Machines](https://thinkingmachines.ai/news/inkling-2-mini/); [HF model card](https://huggingface.co/thinkingmachines/Inkling-2-Mini)
- "8/8 on needle-in-a-haystack tests" reported in an independent M5 Pro Mac mini benchmark (snippet only) — [HF dataset pratikgx](https://huggingface.co/datasets/pratikgx/inkling-2-mini-m5-pro-mac-mini-bench/blob/main/README.md)
- Aayush Garg on a 4090: one 244K prompt survived, "then crashed early in the multi-turn session" with the newer drafter; cold prompts "take ~132 s at 256K and ~240 s at 374K" — [aayushgarg.dev](https://aayushgarg.dev/posts/2026-11-23-inkling2-mini-llamacpp/)
- Qwen3.8 held character "without much drift, even at 20K+ context" (u/Tylopodas) — [r/SillyTavernAI](https://www.reddit.com/r/SillyTavernAI/comments/1voatfl/thoughts_on_qwen_38_27b/)

**Reasoning length / overthinking / loops**
- Qwen: 22,276 reasoning tokens for 3,223 output tokens at default `xhigh` (Simon Willison); Atomic Agent team: "By default it reasons at max effort, and our first uncapped attempts wrote zero files in half an hour. With a thinking budget it gets to the code fast." — [simonwillison.net](https://simonwillison.net/2026/Aug/16/qwen-38-27b/); [r/Qwen_AI](https://www.reddit.com/r/Qwen_AI/comments/1wsx013/qwen_38_27b_as_the_coder_in_a_cloudlocal_agent_on/)
- Inkling: 19,200-token cap hit (dofm), 12,000-token loop (dgacmu), 3-hour/180-tool-call runaway (chriddyp), 65K-token output overruns (HF #16); Artificial Analysis counted ~38% more tokens for Inkling but ~4× faster per task (relayed) — [HN](https://news.ycombinator.com/item?id=50581260); [HF #16](https://huggingface.co/thinkingmachines/Inkling-2-Mini/discussions/16); [novcog test](https://inkling2mini.novcog.us.com/our-test)
- Contrary data point: Reddit user RegretNo6554 (relayed): "it completed tasks for the AA index in 9 min compared to 35 min for qwen" — [novcog reactions](https://inkling2mini.novcog.us.com/reactions)
- Inkling's chat template default effort is 0.9 ("high"), with levels none/minimal/low/medium/high/xhigh/max — [chat_template.jinja](https://huggingface.co/thinkingmachines/Inkling-2-Mini/blob/main/chat_template.jinja)

**Hallucinations / knowledge**
- Inkling invented a WordPress hook and defended it (dofm); identified a 1967 half-dollar as "1979 dime" (dgacmu) — [HN](https://news.ycombinator.com/item?id=50581260)
- Round-up of the AA-Omniscience number: "-8.6 vs Qwen's -6.4" (X post by @superalesha, via mirror) — [xitter mirror](https://xitter.gq/superalesha/status/2123874928600469918)
- Qwen: "Ships confident-but-wrong code on implicit/underspecified requirements" (u/breake) — [r/vibecoding](https://www.reddit.com/r/vibecoding/comments/1vuvlp4/qwen38_27b_tried_a_real_life_test/)

**Non-English**
- Mixed: rsolva says Inkling speaks Norwegian fluently; RandyOrion calls non-English a "pain point"; Blixild saw Polish slips from all models ("faktuarach" from Inkling, "Uprzejmий" from Qwen) — [HN](https://news.ycombinator.com/item?id=50581260); [dev.to](https://dev.to/jacek_garbuliski/inkling-2-mini-vs-qwen38-27b-and-arete-27b-on-agent-tasks-54ii)

### Inferences
- For the narrator's use case (long-form writing + planning → JSON), the evidence base is lopsided: Qwen3.8 has months of "good structured summariser, stiff fiction writer" reports; Inkling 2 Mini has essentially no long-form writing reports yet. Vendor-reported weaker multi-constraint instruction following is the most relevant red flag for complex JSON schemas.
- Neither model shows a community pattern of broken JSON *from the model itself*; JSON problems reported are in runtime parsers/grammars (see section 5).

### Gaps
- No first-hand report on Inkling 2 Mini prose quality for essays/articles/scripts.
- No report on either model's JSON validity rate for long outputs (thousands of tokens) with thinking on.
- No independent long-context *quality* test (beyond needle-in-haystack) for Inkling 2 Mini.

## 4. Speed and memory in practice

### Takeaway
Inkling generates roughly 2× faster than Qwen3.8-27B on the same hardware once runtimes are tuned (e.g. 161 vs 68 tok/s on an RTX 5090 without drafting), but day-one numbers were all over the place because of broken builds. It does run on 32 GB Macs (~10–20 tok/s on M1-generation machines) and 24 GB GPUs, but llama.cpp's implementation needed tricks (`-ub` batch reduction, KV settings) to fit long contexts. Qwen3.8-27B fits 24 GB at Q4 at ~31–34 tok/s on a 3090, and gets much faster with speculative decoding (MTP/DFlash).

### Cited Findings

**Inkling 2 Mini — GPUs**
- RTX 4090, llama.cpp Unsloth build b12676: recommended "8-bit KV + DSpark" — 196K context, 119 / 98 / 82 / 72 tok/s at 0 / 64K / 120K / 160K context, 21.9 GB peak VRAM; "Long context" 8-bit KV — 262K context, 89→62 tok/s — [aayushgarg.dev](https://aayushgarg.dev/posts/2026-11-23-inkling2-mini-llamacpp/)
- RTX 3090: llama.cpp default batch made 9 of 12 setups fail to load; cause: an attention-bias table "2 x 24 x 131,072 x 512 x 4 bytes, 12.9 GB at 128K, on top of the weights and the cache. Flash attention does not avoid it"; fix: `-ub 128`/`-ub 64` (lets Q4_K_M run at 128K on 24 GB, at the cost of prompt-reading speed) — [vramcalculator.com](https://vramcalculator.com/inkling-2-mini-vram/)
- RTX 5070 Ti user (r/LocalLLaMA via Korean mirror): q8_0 KV used 12.3 GB vs 8.8 GB for f16 — "quantizing the KV cache actually uses more VRAM"; f16 gave up to 50% faster generation; commenters: "Probably a bug. llama.cpp's Inkling 2 Mini implementation seems pretty buggy." — [aiwitness.kr mirror](https://aiwitness.kr/community/1y1vv9p)
- RTX 3090: DeathArrow "Got between 130 and 152 tokens per second for Q4 using ninfer"; early llama.cpp reports of ~10 tok/s were "compilation issues that were causing CPU fallback" (baoooooooooooo) — [HN](https://news.ycombinator.com/item?id=50581260)
- RTX 5090: enlyth "700 tok/s prefill and 52tok/s generation" day one; later "folks are already hitting >280tok/s on 5090 configs" (relayed) — [HN](https://news.ycombinator.com/item?id=50581260)
- AMD 7900 XTX: jakswa ~26 tok/s day one → "Update 4 days later: I'm up to 80-100 tok/s on this setup with maya engine. So chalk all the slowness talk above up to model newness." — [HN](https://news.ycombinator.com/item?id=50581260)
- RX 9060 XT 16 GB: 17 tok/s (vikmals); RTX 4060 Ti 8 GB with 10 layers offloaded: ~12 tok/s — [HN](https://news.ycombinator.com/item?id=50581260); [Ollama #19826](https://github.com/ollama/ollama/issues/19826)
- RTX 5090 (Blixild): 161 tok/s single request, 740 tok/s aggregate with 8 concurrent, vs Qwen3.8-27B 4-bit 68 tok/s (136 with MTP draft) — [dev.to](https://dev.to/jacek_garbuliski/inkling-2-mini-vs-qwen38-27b-and-arete-27b-on-agent-tasks-54ii)

**Inkling 2 Mini — Macs / laptops**
- M1 Pro 32 GB: "About 10t/s using q4 xl while running browsers/etc." (dgacmu); same machine runs Qwen3.8-27B at "2–4 tok/s" (quinncom) — [HN](https://news.ycombinator.com/item?id=50581260)
- M1 Max 64 GB: "20 tokens/s running the 4-bit version" (gregsadetsky); "about 18" on Unsloth llama.cpp build (meatmanek), who adds: "18tps is close to what you'd expect for a dense model this size" — [HN](https://news.ycombinator.com/item?id=50581260)
- 24 GB M2 MacBook Air with a custom engine: "about 110 t/s prefill / 19 t/s decode" (ltrg) — [HN](https://news.ycombinator.com/item?id=50581260)
- M4 Pro 64 GB Mac mini: "each question takes between 4min-30min… On OpenRouter, the median was ~70s… Llama was taking about 29GB" (chriddyp) — [HN](https://news.ycombinator.com/item?id=50581260)
- M4 Pro 48 GB MacBook Pro: Inkling 25.7 tok/s vs Qwen3.8 27B 12.7 tok/s (median) — [novcog test](https://inkling2mini.novcog.us.com/our-test)
- M5 Pro 64 GB Mac mini: IQ4 GGUF ~30 tok/s short context, 17.4 tok/s at 128K (search-result summary of benchmark README) — [HF dataset pratikgx](https://huggingface.co/datasets/pratikgx/inkling-2-mini-m5-pro-mac-mini-bench/blob/main/README.md)
- 36 GB MacBook Pro: "context has to be kept too small to fit in memory" (relistan) — [HN](https://news.ycombinator.com/item?id=50581260)
- frou_dh: "Macs with 32GB unified memory have a default soft-cap of ⅔ for how much memory the graphics subsystem can use, so when they say it's targeted at 32GB Macs that effectively means targeting 21.3 GB VRAM?" — [HN](https://news.ycombinator.com/item?id=50581260)
- Vendor support statement: "Apple silicon devices with 32GB or more memory… Other GPUs and platforms are possible, with 32GB or more of VRAM recommended" — [HF model card](https://huggingface.co/thinkingmachines/Inkling-2-Mini)

**Qwen3.8-27B**
- RTX 3090 24 GB, UD-Q4_K_XL, llama.cpp: "31–34 tok/s generation and ~1,080 tok/s prompt processing. On a 3060 12 GB it spilled ~7 GB into RAM and dropped to 4–6 tok/s" (u/GapNew4766, Atomic Agent builders) — [r/Qwen_AI](https://www.reddit.com/r/Qwen_AI/comments/1wsx013/qwen_38_27b_as_the_coder_in_a_cloudlocal_agent_on/)
- M2 Ultra 128 GB: MLX 4-bit 51.5 tok/s; Q4_K_M 33.4; Q8_0 21.3 (u/breake) — [r/vibecoding](https://www.reddit.com/r/vibecoding/comments/1vuvlp4/qwen38_27b_tried_a_real_life_test/)
- M5 Max 128 GB / DGX Spark, LM Studio Q4_K_M: "around 15-30 tokens a second" (Simon Willison) — [simonwillison.net](https://simonwillison.net/2026/Aug/16/qwen-38-27b/)
- 7900 XTX: Qwen3.8-27B/DaisyRose-27B Q4 "~66 t/s and ~800 t/s prefill with 3 slots and about 190k kv cache" (rsolva) — [HN](https://news.ycombinator.com/item?id=50581260)
- H200 NVL, Qwen FP8 with built-in MTP draft: 189 tok/s single, 1,070 tok/s aggregate with 8 concurrent; agent task median 6.9 s — fastest config in that test — [dev.to](https://dev.to/jacek_garbuliski/inkling-2-mini-vs-qwen38-27b-and-arete-27b-on-agent-tasks-54ii)

### Inferences
- On a rented datacenter GPU (the narrator's setup), the speed gap narrows a lot: Qwen FP8 + MTP on an H200 beat Inkling-on-5090 on agent-task time in the one test that measured both. Inkling's speed advantage is most dramatic on memory-bandwidth-limited consumer hardware.
- "Runs on a laptop" is true for 32 GB+ Macs at ~10–25 tok/s; 24 GB GPUs work but long context needs care; 16 GB devices need heavier quantization or offload.

### Gaps
- No report of Inkling on an H100/H200 via vLLM with throughput numbers (see hardware conflict in section 5).
- Tokens-per-second figures come from many different builds/quantizations; no controlled apples-to-apples test across many machines.

## 5. Setup problems — which complaints are plumbing, not the model?

### Takeaway
Most first-week Inkling "it's broken / it's slow" reports trace to runtimes: llama.cpp support was merged in pieces, early Unsloth GGUFs gave ~130 perplexity until a loop-slot fix, a tool-call grammar bug crashed LM Studio with tools on, MLX had no tool parser, Ollama needed a version bump, and CPU-fallback builds gave ~10 tok/s. Qwen3.8-27B's plumbing issues are older and mostly fixed: reasoning-parser mismatches with prefilled `<think>`, `tool_choice` not enforced in vLLM, and tool calling degrading with thinking off.

### Cited Findings

**Inkling 2 Mini — plumbing**
- llama.cpp: support arrived via PRs registering `inkling2`/`inkling2_loop` (#32217, refined by #32704 merged Nov 21); "Unsloth's files require the #32704 loop-slot fix, otherwise they load but report ~130 perplexity" — [Ollama #19826](https://github.com/ollama/ollama/issues/19826). Early PRs linked on launch day: [llama.cpp PR #32695](https://github.com/ggml-org/llama.cpp/pull/32695) ("adds looped support") and [#32694](https://github.com/ggml-org/llama.cpp/pull/32694)
- Ollama: was pinned to llama.cpp b12257 (pre-support); MLX-only at first; Ollama 0.40.18 (llama.cpp b12651) added PC support; Nov 25 rebuilt downloads; error `unknown model architecture: 'inkling2_loop'` means old Ollama or old download — [Ollama #19826](https://github.com/ollama/ollama/issues/19826); [Logeshwaran.org](https://www.logeshwaran.org/2026/11/run-inkling-2-mini-locally.html)
- Tool-call grammar bug (llama.cpp, affects LM Studio): "inkling model + tools attached + thinking off = every plain reply dies with a mid-stream 500" — error `Unexpected empty grammar stack after accepting piece`. Reporter nikosleft; first bad commit "chat : implement inkling parser (#32381)", merged 2026-11-16. A second commenter (parda21) showed some cases were actually all-`?` garbage output from a CPU-offload bug (#32778/#32710), workaround `--no-op-offload`. Fixed by [PR #32833](https://github.com/ggml-org/llama.cpp/pull/32833) (merged 2026-11-23), which "will not address generation issues" — [llama.cpp #32818](https://github.com/ggml-org/llama.cpp/issues/32818)
- LM Studio guide: "If you've switched on tools or plugins… every message fails with: Unexpected empty grammar stack… It isn't your setup… Until it does, turn tools off for this model"; some saw replies "hang at 'Processing Prompt' with a long system prompt" — [Logeshwaran.org](https://www.logeshwaran.org/2026/11/run-inkling-2-mini-locally.html) (LM Studio bug tracker #2632 referenced in [llama.cpp #32818](https://github.com/ggml-org/llama.cpp/issues/32818))
- Thinking-off template quirk: "this model opens a thinking block at effort 0 unless pinned" (nikosleft) — [llama.cpp #32818](https://github.com/ggml-org/llama.cpp/issues/32818)
- MLX: mlx-lm support is an open draft PR; chrispatil: "Tool calling through the OpenAI-compatible API doesn't work yet… the raw template tokens come back in `content` instead"; another user confirms on "MacBook Pro M1, 32 Gb RAM. No tool calls."; FezVrasta built a proxy parser as a workaround — [mlx-lm PR #2086](https://github.com/ml-explore/mlx-lm/pull/2086). LM Studio's MLX engine can't load it until an engine update — [PortOS #17205](https://github.com/atomantic/PortOS/issues/17205)
- vLLM: day-0 Docker image `vllm/vllm-openai:inkling-2-mini` with `--reasoning-parser inkling --tool-call-parser inkling` — [vLLM blog](https://vllm.ai/blog/2026-11-20-inkling2-mini). PR #69028 (merged 2026-11-21) claims hardware "Blackwell (SM100/SM103), Hopper (SM90) and DGX Spark (SM120/SM121)" — [vLLM PR #69028](https://github.com/vllm-project/vllm/pull/69028); **contradicted for the published image** by Blixild (22 Nov): "its published image for vLLM… lacks the code for H100 and H200 cards… an open issue at vLLM"; also DSpark draft "did not start" on their 5090 — [dev.to](https://dev.to/jacek_garbuliski/inkling-2-mini-vs-qwen38-27b-and-arete-27b-on-agent-tasks-54ii). A how-to guide says "NVFP4 builds are MLX-only and will not run on an H100" — but this refers to Ollama's NVFP4 tag, not vLLM — [Logeshwaran.org](https://www.logeshwaran.org/2026/11/run-inkling-2-mini-locally.html)
- ROCm: "Flash Attention (FA) is not supported on the current llama.cpp (at least not for ROCm) for this model so KV cache is forced to f16 for the value" (rsolva, day one); Vulkan bug fix patch took a card from ~27 to ~41 tok/s — [HN](https://news.ycombinator.com/item?id=50581260)
- Quantization debate: woadwarrior01: "What's the point in quantizing a QAT model?"; reply: "It was natively trained in NVFP4, through and through." — [HN sub-thread](https://news.ycombinator.com/item?id=50592509). Simon Willison found a community MLX build (`oQ4e-mtp`) gave "way better" pelicans than the IQ4_NL GGUF he used — [Bluesky](https://bsky.app/profile/simonwillison.net/post/3n2u5xcciwk2u)
- dofm on tool calls that never fired: "Whether this is the model failing or Unsloth's harness and the model disagreeing, I don't know." — [HN](https://news.ycombinator.com/item?id=50581260)
- Round-up summary quote (OrcaRouter blog, relayed): "a looped architecture has roughly one day of serving maturity" — [novcog reactions](https://inkling2mini.novcog.us.com/reactions)

**Qwen3.8-27B — plumbing**
- SGLang gateway (Rust) didn't populate `reasoning_content` for Qwen3.8-27B-FP8 because "Qwen3.8's chat template injects the opening `<think>` token into the prefill"; reasoning text leaked into `content`. Fix PRs #35249/#35346; closed — [SGLang #35148](https://github.com/sgl-project/sglang/issues/35148)
- vLLM 0.28.0: `qwen3_coder` parser "silently ignores tool_choice 'required' and named function"; "Fixed on main by #52830 (in v0.29.0+)"; JSON-schema `response_format` worked — [vLLM #54808](https://github.com/vllm-project/vllm/issues/54808)
- Qwen repo: "Tool calling becomes unreliable with long prompts when enable_thinking=false (Qwen3.8-27B/Qwen3.8-27B-FP8)… when `enable_thinking: true` (default), tool calling is stable regardless of prompt length." Reproduced on BF16 and FP8; closed 2026-11-14 — [QwenLM/Qwen3.8 #236](https://github.com/QwenLM/Qwen3.8/issues/236). (Arguably a model behaviour, surfaced via thinking-off.)
- SGLang tool-call 400 error on a tool schema with `required: None` (client schema issue) — [SGLang #35242](https://github.com/sgl-project/sglang/issues/35242)
- LM Studio's default 8,192 context was used up by Qwen's thinking; fixed by loading 262,144 context (Simon Willison) — [simonwillison.net](https://simonwillison.net/2026/Aug/16/qwen-38-27b/)
- Atomic Agent team: "Tool calling in Q4 was solid, no broken calls in the final runs." — [r/Qwen_AI](https://www.reddit.com/r/Qwen_AI/comments/1wsx013/qwen_38_27b_as_the_coder_in_a_cloudlocal_agent_on/)

### Inferences
- Plumbing, not model: Inkling's ~10 tok/s reports, ~130 perplexity garbage, "empty grammar stack" 500s, MLX tool calls in `content`, Ollama "unknown architecture", q8_0 KV using more VRAM, and llama.cpp OOMs at long context. Model, not plumbing: over-long reasoning at default effort, invented facts, stubbornness, runaway loops (all echoed by the vendor's own model card). Gray zone: tool calls announced but never emitted (dofm), 1–4 s TTFT on vLLM (cause unknown).
- For the narrator specifically (vLLM/SGLang on a rented GPU, FP8 Qwen with thinking on): Qwen's known parser bugs are already fixed in current releases. Inkling's vLLM path is new; the Hopper-support conflict means he should verify H100/H200 support on the exact image before renting.

### Gaps
- Could not confirm whether the vLLM H100/H200 gap Blixild reported has since been fixed in a released image (the vLLM issue number was not given).
- No SGLang-specific Inkling 2 Mini issues surfaced in searches.

## 6. X/Twitter reactions from notable developers

### Takeaway
All second-hand (via nitter/xitter mirrors and round-ups). Notable: DHH said Inkling beat Qwen3.8 27B in his overnight eval; Simon Willison ran it locally (pelican test, mixed results by quant); launch excitement emphasised "beats Qwen3.8-27B with 5× fewer active params", with sceptics posting their own losing comparisons.

### Cited Findings
- DHH (26 Nov, mirror): "…Inkling2 Mini just beat Qwen3.8 27B in my overnight eval shoot-out for best model for a 48-64GB RTX Spark on Omarchy malleability." Replies asked for the test sheet: Yetunde Olowe: "beat am on which task though?…"; Junaid Rehman: "the whole 0.5 gap is the App column, and Qwen only finished 7 of 8. if the missing run was an App one, that 6.0 is a DNF, not a weaker model" — [nitter mirror](https://nitter.gq/dhh/status/2125845831051858053)
- JRB (@JRB_AI, mirror): "It's possibly the greatest local model we've ever seen. I don't mean that on raw intelligence… but the capability as a function of parameter count is mindblowing." — [nitter mirror](https://nitter.gq/dhh/status/2125845831051858053)
- Alexey Fateev (@superalesha, 20 Nov, mirror): "HOLY SHIT, Thinking Machines just dropped a 26.4B Apache 2.0 looped transformer and it beats Qwen3.8-27B with 5x fewer active params." (repeats vendor benchmark numbers) — [xitter mirror](https://xitter.gq/superalesha/status/2123874928600469918)
- Thinking Machines (@thinkymachines, 20 Nov, mirror): "Some of you thought that Inkling 2 Small was too big at 594B parameters. We heard you…" — [xitter mirror](https://xitter.gq/superalesha/status/2123874928600469918)
- Round-up: Thinking Machines' launch post 3.2M views; Mira Murati's post 754.1K views (21 Nov snapshot) — [novcog reactions](https://inkling2mini.novcog.us.com/reactions)
- Simon Willison (HN, 2026-11-21T05:55:46Z): "Pelicans aren't terrible (for the model size)… Generated with Inkling-2-Mini-IQ4_NL.gguf and llama.cpp on a M5 MacBook Pro." On Bluesky (21 Nov) to a user with an MLX `oQ4e-mtp` build: "That's way better than the pelicans I got from that model with Inkling-2-Mini-IQ4_NL.gguf - what exact file did you use?" — [HN](https://news.ycombinator.com/item?id=50581260); [Bluesky](https://bsky.app/profile/simonwillison.net/post/3n2u5xcciwk2u)
- VentureBeat headline: "Thinking Machines wows with Inkling 2 Mini looped transformer model that runs locally on laptops", noting traction "driven by rapid day-one integrations from local-inference tooling providers" — [VentureBeat](https://venturebeat.com/technology/thinking-machines-wows-with-inkling-2-mini-looped-transformer-model-that-runs-locally-on-laptops)

### Inferences
- Notable-developer endorsements are about local-hardware fit and parameter efficiency, not about writing quality.

### Gaps
- No direct statements from Karpathy, Latent Space or Interconnects on Inkling 2 Mini were found (one X user invoked Karpathy's "cognitive core" idea; Karpathy himself not quoted). X could not be read directly; mirrors may drop handles/formatting (DHH quote visibly garbled).
- No notable-developer X reactions specific to Qwen3.8-27B were gathered in this pass.

## 7. Fine-tuning experiences (Tinker, Unsloth)

### Takeaway
Tooling exists for Inkling 2 Mini on day one-ish (Tinker LoRA; Unsloth LoRA/QLoRA on ~22 GB VRAM), but almost no user reports of actual fine-tune outcomes yet. Qwen3.8-27B has an ecosystem of community fine-tunes (e.g., Nous Research's Arete-27B, writing-focused "Hemmingway-1").

### Cited Findings
- Tinker: Inkling 2 Mini available "on Tinker today for inference and customization" — [Thinking Machines](https://thinkingmachines.ai/news/inkling-2-mini/). Cookbook: "LoRA trains one adapter per layer, shared by all three passes" — [tinker-cookbook SKILL.md](https://github.com/thinking-machines-lab/tinker-cookbook/blob/main/skills/inkling/SKILL.md)
- Unsloth: "Local training with Unsloth works on 22GB VRAM"; 1.81× faster / ~50% less VRAM than TRL on A100; "with plain transformers 4-bit, the looped layers' message gates are quantized too and the first losses are 3.4-3.9 instead of 0.4-1.2. Keeping `message_gate.down_proj` out of 4-bit fixes the loss" — [Unsloth docs](https://unsloth.ai/docs/models/inkling-2-mini/fine-tuning). Release notes: fits Kaggle 2×T4 "at about 26 s per step"; GGUF export "needs about 150 GB of free disk"; `merged_4bit` not supported — [Unsloth release](https://github.com/unslothai/unsloth/releases/tag/v0.1.925-beta) (vendor claims)
- Tom Ballard (@tcballard) asked DHH whether he'd done "post training / tuning using the @tinkerapi yet" — question, not a report — [nitter mirror](https://nitter.gq/dhh/status/2125845831051858053)
- Qwen3.8-27B derivatives: Arete-27B is "Nous Research's fine-tune of Qwen3.8-27B" — [dev.to](https://dev.to/jacek_garbuliski/inkling-2-mini-vs-qwen38-27b-and-arete-27b-on-agent-tasks-54ii); Hemmingway-1 (27B), a Qwen3.8-27B fine-tune for "Natural writing, conversation", rated 9/10 prose by a writer comparing local models — [r/WritingWithAI](https://www.reddit.com/r/WritingWithAI/comments/1x81y2e/choosing_a_local_ai_to_write_with_comparison_of/). HF downloads (30 days): Qwen3.8-27B 6.3 million vs Inkling 2 Mini 23,500 (original weights only) — [dev.to](https://dev.to/jacek_garbuliski/inkling-2-mini-vs-qwen38-27b-and-arete-27b-on-agent-tasks-54ii)

### Inferences
- The "plumbing" warning extends to fine-tuning: naïve 4-bit fine-tuning of Inkling silently breaks the loop gates per Unsloth, so DIY fine-tunes may underperform for reasons unrelated to the base model.

### Gaps
- No first-hand user report of a completed Inkling 2 Mini fine-tune and its results (Tinker or Unsloth).
- Did not search specifically for Qwen3.8-27B Unsloth fine-tuning experience reports.

## 8. Consistent themes — what almost everyone agrees on

### Takeaway
Inkling 2 Mini: fast for its quality, genuinely runs on 24–32 GB hardware, good coder/tool-user, but weak on facts, over-verbose at default effort, stubborn, and too new for stable runtimes. Qwen3.8-27B: the strongest ≤32 GB model, very capable, reliable tool calling, good structured summariser, but overthinks wildly at default and is slow because it is dense.

### Cited Findings
- Both: lower the reasoning effort. Qwen — "Run Qwen 3.8 27B on low or even no reasoning levels at first" (Simon Willison) — [simonwillison.net](https://simonwillison.net/2026/Aug/16/qwen-38-27b/); Inkling — "Running it on low was better" (dgacmu) and lower effort made it "accept correction much more quickly" (dofm) — [HN](https://news.ycombinator.com/item?id=50581260)
- solarkraft (HN): "For this reason it's crazy to me that labs would release their models at xhigh. That means, to me, that the default configuration is essentially broken (all in the name of benchmaxxing)." — [HN](https://news.ycombinator.com/item?id=50581260)
- Inkling: knowledge gap acknowledged by the vendor ("knowledge is mostly a function of total parameter count") and confirmed by users (invented hook, coin test) — [Thinking Machines](https://thinkingmachines.ai/news/inkling-2-mini/); [HN](https://news.ycombinator.com/item?id=50581260)
- Inkling: speed improved rapidly as runtimes matured ("chalk all the slowness talk above up to model newness" — jakswa) — [HN](https://news.ycombinator.com/item?id=50581260)
- Inkling vs Qwen tokens: more tokens but faster wall-clock (novcog; AA relayed) — [novcog test](https://inkling2mini.novcog.us.com/our-test)
- Qwen: best for ≤32 GB VRAM (u/Material-Database-24); "damn good coder, but a terrible collaborator" (u/Chuyito) — [r/Qwen_AI](https://www.reddit.com/r/Qwen_AI/comments/1wvw8hv/tell_me_about_what_your_experiences_with_qwen_38/); [r/LocalLLaMA](https://www.reddit.com/r/LocalLLaMA/comments/1w4wjxd/everyone_is_ts_maxing_38_but_after_a_week_of/)
- Benchmark trust split: 2001zhaozhao: "TML is not known to benchmaxx nearly as hard as Qwen."; stavros (replying to "if these benchmarks hold up"): "To me, this means they probably won't." — [HN](https://news.ycombinator.com/item?id=50581260); [novcog reactions](https://inkling2mini.novcog.us.com/reactions)

### Inferences
- For a narrator running Qwen3.8-27B FP8 with thinking on, on a rented datacenter GPU, for long-form writing/planning with JSON output: the community evidence does not yet support a clear switch. Inkling's clearest wins (consumer-hardware speed, agentic coding, explicit-procedure tool use) are not the narrator's core job; its documented weaknesses (multi-constraint instruction following per vendor, factual recall, verbosity at default, immature serving stack, Hopper-image uncertainty) touch it directly. Qwen's main weakness (overthinking) is already something he can cap. A same-prompt A/B on his own jobs is what the community itself recommends.
- Evidence on Inkling is one week deep; expect opinions to shift as runtimes stabilise.

### Gaps
- No consensus yet on Inkling writing quality or long-output JSON reliability — the two dimensions most relevant to the narrator.
- No data on Inkling with thinking on vs off for structured long-form output.
