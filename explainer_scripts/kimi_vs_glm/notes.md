# Kimi K3.1 Pro vs GLM-5.3: notes

`script.txt` holds only spoken words. About 1,830 words, so roughly 11 to 12 minutes at the Nvidia script's pace. Two optional cuts to get under 10 minutes are listed at the end.

Research was done on 25 November 2026 from search results and the pages listed below. **No evidence has been captured yet.** Every number below still has to pass an evidence round before it goes on screen.

## Story shape

1. **Cold open:** two independent tests, the same model, opposite answers, and "neither test is wrong".
2. **Who's talking, and the plan (about 25 seconds):** Naresh's credentials (several AI research projects; CEO of Techsergy, AI consulting plus building and fine-tuning models for companies). "Not a hobby for me. It is the job." Then the plan and the promise: which model to use for what, plus five questions.
3. **Who they are:** open weights in one line, Kimi's size, GLM's price. Question: "They can't both be the best. Or can they?"
4. **What the labs say, and the small print:** Z.ai's "50%" is 11 points on its own private test. Kimi's footnotes say "Claude-Code harness". **Open loop:** "Hold on to that word. Harness."
5. **The referee:** Artificial Analysis. Kimi wins, and its Terminal-Bench claim holds up. **Twist:** the June "51" vs today's "32" come from a different version of the test. **Lesson one.**
6. **The flip:** Bito's long sessions. Kimi costs $150 and takes 5+ hours, while GLM wins. Explained with the "re-read the whole book" analogy. **Lesson two.**
7. **Payoff of the open loop:** the harness, with the driver-and-car analogy. 35 points in one study, about 2 in another.
8. **Hidden layer:** the hosts, with the recipe-and-kitchen analogy. Broken tool calls range from 0.04% to 9%.
9. **Users:** good and bad for both. Plumbing (41% of failures were cut connections). "Slow compared to what?"
10. **YouTube:** a hype title against the data, and why single-prompt tests favour Kimi.
11. **What is consistent:** Kimi is slow, and Kimi makes fewer false claims.
12. **Verdict by use case,** dated "as of late November 2026".
13. **Payoff of the promise:** the five questions.
14. **Close:** GLM-5.4 released on 22 November. "The leaderboard will change next month. These five questions won't."

Re-hooks come every 60 to 90 seconds: "Or can they?", "Hold on to that word", "So, case closed? Not quite", "How can the same model be a genius on one test and a money pit on another?", "The experts don't agree", "There is one more hidden layer".

## Claims to mark for evidence

Text evidence unless noted. "Highlight" is the wording to look for on the page.

| Script claim | Source | Highlight |
|---|---|---|
| Kimi 65.7% on Terminal-Bench 4.0, behind Opus 5.5, ahead of GPT-6 Astra | [Kimi K3.1 Pro blog](https://www.kimi.ai/blog/kimi-k3-1-pro) | "K3.1 Pro scores 65.7%, ahead of GPT-6 Astra (58.2%) and narrowly behind Claude Opus 5.5 (66.4%)" |
| "Kimi K3.1 Pro is evaluated with the Claude-Code harness." | Same blog, footnotes | That exact line (Coding benchmarks, note 1) |
| Kimi in Kimi Code, rivals in Claude Code, on a few tests | Same blog, footnotes | Agentic note 1 (BioMysteryBench) or Cybersecurity note 3 (xdev-Bench-hard) |
| Rivals given their highest reported score | Same blog, footnotes | "taken as the maximum value reported in either their blog posts or the official Terminal-Bench 4.0 leaderboard" |
| GLM-5.3 "50%" better, on Z.ai's private test | [Z.ai GLM-5.3 docs](https://docs.z.ai/guides/llm/glm-5.3) or [blog](https://z.ai/blog/glm-5.3) | "a 50% performance gain over GLM-5.2 on Z.ai Code Bench" and "As a private benchmark" |
| 23.4% to 34.5% at max effort | Same docs page | "At Max effort, GLM-5.3 reaches 34.5% ... compared with 23.4% at 96K for GLM-5.2" |
| GLM-5.3 "most capable open model for coding" | Same | "the most capable open-weights model for coding" |
| Kimi "matches or approaches" closed models | Kimi blog | "K3.1 Pro matches or approaches the strongest proprietary models" |
| Kimi 47, GLM-5.3 (max) 32 | [Artificial Analysis comparison](https://artificialanalysis.ai/models/comparisons/kimi-k3-1-pro-vs-glm-5-3) | Intelligence Index row |
| Kimi 67% on Terminal-Bench, top of any model | [Artificial Analysis Index v5 article](https://artificialanalysis.ai/articles/artificial-analysis-intelligence-index-v5) | "Kimi K3.1 Pro: Terminal-Bench 4.0 (67%)" |
| GLM-5.2 scored 51 in June | [Zhipu GLM-5.2 post (Chinese)](https://www.zhipuai.cn/zh/research/161) | "在Artificial Analysis综合榜单上，GLM-5.2取得51分" |
| New, harder index on 27 October | Index v5 article | Date line and "v5 is our biggest upgrade since v4" |
| Kimi 12 points behind Opus; best open model 12 behind the best closed one | Index v5 article | "Kimi K3.1 Pro ... scores 46, 12 points behind the leader" |
| Bito: Kimi fourth of four, $149.86, 320 minutes; GLM 74.0% and $34.82; Kimi 60.3% vs GLM 51.2% on hard short tasks | [Bito](https://bito.ai/blog/best-open-weight-model-for-coding-kimi-k3-1-pro-glm-5-3-deepseek/) | The results table and "A 20-turn session on Kimi K3.1 Pro cost $149.86 and took 320 minutes" |
| More than three times Opus; more than twice as long | Bito | "more than three times Claude Opus 5.5" and "2.2x as long" |
| Up to a million tokens re-sent; 800+ requests | Bito | "Kimi keeps the whole session, half a million to a million tokens, and sends it again on every request: its two 20-turn sessions made 823 and 982 requests" |
| Kimi cheaper per task than GLM at max; about half an hour per task | Artificial Analysis comparison | Cost per Task ($3.68 vs $5.01) and Time per Task (34.0 min) |
| GLM-5.3 Flash: 24% vs 59% across harnesses | [8090](https://www.8090.ai/blog/same-model-different-harness) | "it passed 24% of its runs in Codex and 59% in the DeepSeek harness" |
| Seven of ten harnesses tied | [GetVibe harness leaderboard write-up](https://getvibeapi.com/blog/harness-leaderboard-coding-agents) | "GLM-5.3 Flash: seven harnesses share first place" |
| About 2 points for GLM-5.3 and Kimi K3; "The lab's own harness is not automatically best." | [Axis Spatial](https://www.axisspatial.com/blog/same-model-different-harness) | The table rows and that sentence |
| More than twenty hosts | [dottxt tool-call index](https://providers.dottxt.ai/) | Kimi K3.1 Pro row, 21 providers |
| Big hosts land close together on accuracy | [Kimi Vendor Verifier](http://github.com/MoonshotAI/Kimi-Vendor-Verifier) | The K3.1 Pro results table |
| Broken tool calls: 0.04% best host, 9% worst, for GLM-5.3 | dottxt tool-call index | GLM 5.3 row |
| "often gets into long reasoning loops" | [r/ZaiGLM thread](https://www.reddit.com/r/ZaiGLM/comments/1wdby6i/glm_53_is_mediocre_after_a_week_of_coding_im/) | Original post |
| "very rarely requires steering" | Same thread | Comment by u/ironj |
| Two five-hour quotas in under six hours | [Littlewolf Labs round-up of X posts](https://news.littlewolflabs.com/posts/2026-10-26-kimi-k3-1-pro-what-people-say) | The @bwnyng quote |
| "These were our issues, and we should have fixed them sooner." | Same Littlewolf page (quotes Kimi's X post) | The October 25 apology |
| 41% of almost 3,000 failures were cut connections | [Jed Arden, four months of GLM-5.3](https://jedarden.com/guides/glm-coding-plan/) | "2,879 failures of 8,302 attempts" and "Stream cut by the gateway (HTTP 499) — 41%" |
| Kimi about half GLM's speed; 2.5+ minutes before the first answer word | Artificial Analysis comparison | Output Speed (35 vs 71 tok/s) and Time to First Answer Token (155.6 s) |
| YouTube title | [The video](https://www.youtube.com/watch?v=5Z_Y7SRd_oo) | The title as shown on the page |
| Kimi false-claim rate 23.4% to 8.3%, on its own stress test | Kimi blog | "its claim-level hallucination rate fell from 23.4% for K3 to 8.3%" |
| Knowledge test: Kimi 30, GLM-5.3 6, below zero at low effort | Artificial Analysis comparison | AA-Omniscience v1.1 row (30, 6, −11) |
| Kimi reads images; GLM-5.3 text only | Artificial Analysis comparison, or [Z.ai docs](https://docs.z.ai/guides/llm/glm-5.3) | Input Modality row, or "GLM-5.3 currently supports text-only inputs" |
| GLM-5.3 less than a third of Kimi's size | [VentureBeat on GLM-5.2](https://venturebeat.com/technology/z-ais-open-weights-glm-5-2-beats-gpt-5-5-on-multiple-long-horizon-coding-benchmarks-for-1-6th-the-cost) (753B) and the [Kimi K3.1 Pro model card](https://huggingface.co/moonshotai/Kimi-K3.1-Pro) (2.8T). GLM-5.3 uses GLM-5.2's base model, per the Z.ai docs. | "753-billion parameter" and "Total Parameters 2.8T" |
| GLM-5.4 released on 22 November | [Zhipu research list](https://www.zhipuai.cn/zh/research) | "2026/11/22 GLM-5.4" |

## Sound bites

**None are marked yet, on purpose.** Every quote in the script comes from a written source, so the narrator reads them. Lab leaders' launch talks are likely in Mandarin, and the capture tool needs English captions, so those clips would come back as `blocked`.

One good candidate is a YouTuber saying in their own words that Kimi beats Opus. It would fit the YouTube section in place of the title. I only saw a garbled auto-transcript of one such video ([qjjLmW2coo4](https://www.youtube.com/watch?v=qjjLmW2coo4): "it's beating Claude Opus and it's beating GLM 5.3"), so the exact words, the speaker's name and the channel still need checking. If one is found, rewrite the lead-in to name the speaker and end with a colon, as `soundbite_rules.py` asks.

## Needs checking before recording

- **"A typical YouTube test gives the model one question, or one app to build."** I saw only parts of two or three reviews. Watch a few before keeping this line, and soften it if it doesn't hold.
- **The Jed Arden logs** cover Claude Code on the GLM Coding Plan. His article title says GLM-5.3, but part of August ran on GLM-4.7. Check that the 41% figure covers only the GLM-5.3 period, or soften it to "running GLM's coding plan".
- **"Kimi had a rougher launch":** the quota quotes are X posts collected second-hand by Littlewolf Labs. The capture tool can't log in to X, so the Littlewolf page is the evidence source.
- **Terminal-Bench 67%:** the Index v5 article reports Terminal-Bench 4.0 at 67%. The comparison page now shows Terminal-Bench 4.1 at 68.2%. Use the article, which matches the 4.0 version Moonshot quoted.

## Facts that will go stale

These were true on 25 November 2026. Re-check them before publishing:
- the Artificial Analysis scores (47 and 32), speeds and cost per task;
- the 7-day tool-call error rates (0.04% and 9%), which update daily;
- the number of hosts (more than twenty);
- whether Artificial Analysis has scored GLM-5.4 yet. If it has, the closing section needs a line about it.

## Pronunciation checks for the voice

Naresh Joshi, Techsergy ("TEK-ser-jee"; confirm), Kimi ("KEE-mee"), K3.1 ("K three point one"), GLM-5.3 ("G-L-M five point three"), Z.ai ("zee dot A-I"), Moonshot, Terminal-Bench, OpenRouter, 8090 ("eighty ninety"), Bito ("BEE-toe"), Codex.

## Hedged or left out on purpose

- **Not used: "Kimi scored 55" from [machine.net](https://machine.net/news/kimi-k31-pro-price-cut-verbosity-cost/).** It looks like a score on the old scale, but the article's date isn't clear. Its "nearly double the tokens" claim is also left out, because the current Artificial Analysis page calls Kimi only "somewhat verbose" (113M tokens against a 105M median).
- **Not used: a YouTuber seemingly quoting GLM-5.3 at "$1.40 per million output tokens".** Artificial Analysis lists $1.40 for input and $4.40 for output, but I only saw a garbled transcript.
- **No host is named for the 9% tool-call error rate.** It is a 7-day figure that changes daily.
- **Cut: the cyber-security contrast.** Z.ai celebrates GLM-5.3's hacking ability, while Moonshot removed cyber data and took Kimi's exploit score from 90.5% to 81%. It's interesting but off the main question, and it would need careful wording.
- **Cut: licences.** GLM-5.2 is MIT-licensed. Kimi uses a custom licence with conditions once a business passes $20M in revenue. I haven't checked GLM-5.3's licence.
- **Bito sells code review tools,** and its results are its own runs. The script says so.

## Optional cuts to get under 10 minutes

- The "Even slow depends on who is talking" paragraph (about 55 words). The consistency section still says Kimi is slow, but without the numbers.
- The third harness study (Axis Spatial, about 45 words). Keep the 35-point and seven-tied studies; they already show the disagreement.
