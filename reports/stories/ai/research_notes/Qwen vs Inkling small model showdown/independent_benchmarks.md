# Independent benchmarks: Qwen3.8-27B vs Inkling 2 Mini (as of 27 November 2026)

All pages below were read on **27 November 2026** unless stated otherwise. "Lab" means Thinking Machines Lab (TML) or Alibaba. Many figures are rolling or versioned; each section flags what is likely to go stale.

**Parameter-count note (affects on-screen captions):** the brief says Inkling 2 Mini has "3.4B active". TML's model card says both: "26.4B, 3.4B active" and "each extra pass through the looped layers adds about 1.0B effective active parameters. Since the model runs with three passes, there are 5.4B effective active parameters per token." Artificial Analysis (AA) and TML's benchmark table both list **5.4B active**, and OpenRouter's model description says "3.4B active parameters out of 26.4B total". Captions should say "3.4B active (5.4B effective with three loops)". — [TML model card](https://thinkingmachines.ai/model-card/inkling-2-mini/); [AA model page](https://artificialanalysis.ai/models/inkling-2-mini); [OpenRouter](https://openrouter.ai/thinkingmachines/inkling-2-mini)

---

## 1. Artificial Analysis (AA): Intelligence Index v5.0.2, sub-scores, speed, verbosity, cost

### Takeaway
AA has scored Inkling 2 Mini and has a direct comparison page. On Intelligence Index **v5.0.2** the two models **tie at 20** (Qwen at its default "xhigh" effort). Inkling 2 Mini wins clearly on AA's cost per task ($0.59 vs $3.53) and on speed through first-party APIs (175 vs 59 tok/s, 14.5 vs 31.2 minutes per task). Qwen wins on AA's knowledge-work tests (AA-Briefcase, AutomationBench) and has the lower hallucination rate. Inkling 2 Mini is the **most verbose** model in its class (161M output tokens vs Qwen's 128M).

### Cited Findings

**Version and comparability**
- The current AA index version shown on both model pages is: "Artificial Analysis Intelligence Index v5.0.2 incorporates 9 evaluations: AA-Briefcase v1.1, AutomationBench-AA, Terminal-Bench 4.1, FrontierCode-AA 2.0, AA-Omniscience v1.1, GDP.pdf, HLE-Diamond, CritPt v2 (Hard Subset), and Terminal-Bench-Science 0.1". Category weights: Knowledge Work 25%, Coding 25%, Science 25%, General 25%. — [AA methodology](https://artificialanalysis.ai/methodology/intelligence-benchmarking)
- An example of why versions can't be compared: a third-party tracker lists Qwen3.8 27B (Xhigh) at "20.11 index … Intelligence Index v5.0" and "33.68 index · … Intelligence Index v4.3.2". The same model scores about 13 points lower on the newer, harder version. — [RLTasks](https://www.rltasks.com/models/qwen3-8-27b)
- TML's launch table cites "AA Index (v5.0) | 20.1 | … | 20.1" for Inkling 2 Mini and Qwen3.8-27B. This matches AA, which shows both as 20 (20.1 unrounded, per AA data mirrored on OpenRouter: "Inkling 2 Mini Intelligence Index | 20.1" and "Qwen3.8 27B (Xhigh) Intelligence Index | 20.1"). — [TML launch post](https://thinkingmachines.ai/news/inkling-2-mini/); [OpenRouter Inkling](https://openrouter.ai/thinkingmachines/inkling-2-mini); [OpenRouter Qwen](https://openrouter.ai/qwen/qwen3.8-27b)
- I did not verify the 27 Oct 2026 launch date of v5 on an AA page. The fetched pages only show the current version, v5.0.2.

**Direct comparison page (best on-screen asset).** The page's own headline bullets read:
  - "For intelligence, Inkling 2 Mini and Qwen3.8 27B tie at 20 (Inkling 2 Mini and Qwen3.8 27B (Xhigh))."
  - "For time per task, Qwen3.8 27B is fastest: Qwen3.8 27B (Non-reasoning) at 13.9 min, against Inkling 2 Mini at 14.5 min."
  - "For cost per task, Inkling 2 Mini is cheapest at $0.59, against Qwen3.8 27B (Low) at $1.91 for Qwen3.8 27B."
  - Source: [AA comparison: Inkling 2 Mini vs Qwen3.8 27B](https://artificialanalysis.ai/models/comparisons/inkling-2-mini-vs-qwen3-8-27b)

Table rows from the same page (Inkling 2 Mini | Qwen xhigh | Qwen medium | Qwen low | Qwen non-reasoning):
| Row (verbatim label) | Inkling 2 Mini | Qwen xhigh | Qwen medium | Qwen low | Qwen non-reasoning |
|---|---|---|---|---|---|
| Intelligence Index | 20 | 20 | 18 | 16 | 10 |
| Finance & Accounting | 35 | 36 | 29 | 28 | 22 |
| Strategy & Ops | 35 | 39 | 34 | 29 | 16 |
| Legal | 31 | 33 | 26 | 27 | 22 |
| Healthcare & Medical | -- | 35 | 24 | 23 | 19 |
| Engineering | 28 | 28 | 22 | 21 | 17 |
| Economics | 33 | 34 | 27 | 27 | 22 |
| AA-Briefcase v1.1 (Elo) | 1263 | 1391 | 1369 | 1267 | 901 |
| AutomationBench-AA | 41.8% | 48.2% | 40.3% | 30.1% | 12.4% |
| Terminal-Bench 4.1 | 5.6% | 5.6% | 5.6% | 2.5% | 0.0% |
| FrontierCode-AA 2.0 | 15.1% | 14.9% | 11.3% | 12.4% | 3.7% |
| AA-Omniscience v1.1 | −9 | −6 | −36 | −21 | −7 |
| GDP.pdf | 16.8% | 16.4% | 12.8% | 10.4% | 5.2% |
| HLE-Diamond | 15.2% | 15.3% | 6.7% | 6.8% | 4.2% |
| CritPt v2 (Hard Subset) | 17.0% | 4.0% | 16.5% | 5.5% | 2.0% |
| Terminal-Bench-Science 0.1 | 1.4% | 0.5% | 1.0% | 0.5% | 0.0% |
| Cost per Task USD | $0.59 | $3.53 | $2.51 | $1.91 | $4.63 |
| Input Price USD/1M Tokens | $0.15 | $0.50 | $0.50 | $0.50 | $0.50 |
| Output Price USD/1M Tokens | $0.50 | $3.00 | $3.00 | $3.00 | $3.00 |
| Cache Hit Price USD/1M Tokens | $0.015 | $0.10 | $0.10 | $0.10 | $0.10 |
| Time per Task Minutes | 14.5 | 31.2 | 25.6 | 22.6 | 13.9 |
| Output Speed tok/s | 175 | 59 | 58 | 59 | 54 |
| Time to First Answer Token s | 24.59 | 101.85 | 29.23 | 21.23 | 4.79 |
| Time to First Token s | 2.06 | 5.37 | 14.98 | 7.77 | 4.79 |
| End-to-End Time Mean of Single-Request Workloads (s) | 71.41 | 224.57 | 155.66 | 160.77 | 55.31 |
| Context Window | 1M | 256k | 256k | 256k | 256k |
— [AA comparison page](https://artificialanalysis.ai/models/comparisons/inkling-2-mini-vs-qwen3-8-27b)

**AA model pages (verbatim summary wording)**
- Inkling 2 Mini: "#2 / 15 … 20 Artificial Analysis Intelligence Index"; "Time to first answer token 24.59s Output speed 175 tok/s"; "14.5 Time per Intelligence Index task (minutes)"; "In $0.15 Out $0.50 Cache discount 90% … $0.59 Cost per Intelligence Index task"; "Verbosity #14 / 14 … Input tokens 18.1B … 161M Output tokens from Intelligence Index". Summary sentence: "Inkling 2 Mini is amongst the leading models in intelligence and reasonably priced when comparing to other open weight models of similar size. It's also quicker than average per task, however very verbose." Speeds are "based on Thinking Machines's API". — [AA Inkling 2 Mini](https://artificialanalysis.ai/models/inkling-2-mini)
- Qwen3.8 27B: "#3 / 15 … 20"; "Time to first answer token 101.85s Output speed 59 tok/s"; "31.2 Time per Intelligence Index task"; "In $0.50 Out $3.00 Cache discount 80% … $3.53 Cost per Intelligence Index task"; "Verbosity #12 / 14 … Input tokens 9.87B … 128M Output tokens". Summary sentence: "Qwen3.8 27B (Xhigh) is amongst the leading models in intelligence, but particularly expensive when comparing to other open weight models of similar size. It's also notably slow per task and very verbose." Speeds are "based on Alibaba's API". Output tokens by effort: "128M (xhigh), 89.3M (medium), 77.3M (low), and 37.5M (non-reasoning)"; class median 93.4M. — [AA Qwen3.8 27B](https://artificialanalysis.ai/models/qwen3-8-27b)
- AA's blended price: Inkling "$0.0905 per 1M tokens" vs Qwen "$0.47" (7:2:1 cache-hit/input/output blend). — same two pages

**Factuality (AA-Omniscience v1.1), from AA data mirrored on OpenRouter**
- Inkling 2 Mini: "AA-Omniscience Accuracy | 20.5%", "AA-Omniscience Non-Hallucination Rate | 63.4%". — [OpenRouter Inkling (AA data table)](https://openrouter.ai/thinkingmachines/inkling-2-mini)
- Qwen3.8 27B (Xhigh): "AA-Omniscience Accuracy | 17.3%", "AA-Omniscience Non-Hallucination Rate | 71.4%". — [OpenRouter Qwen (AA data table)](https://openrouter.ai/qwen/qwen3.8-27b)
- In plain terms, Inkling 2 Mini knows slightly more facts, but Qwen is less likely to make things up. TML's own table agrees: "AA-Omniscience v1.1 non-hallucination rate | 63.4% | … | 71.4%". — [TML model card](https://thinkingmachines.ai/model-card/inkling-2-mini/)

**Extra AA evals outside the index (from the AA table mirrored on OpenRouter)**
- Qwen3.8 27B (Xhigh): "AA-LCR | 82.0%", "MLCR-AA | 22.8%", "τ³-Banking | 48.0%", "GDPval-AA | 46.3%", "Terminal-Bench 2.1 | 79.8%", "GPQA Diamond | 90.5%", "MMMU-Pro | 76.3%". — [OpenRouter Qwen](https://openrouter.ai/qwen/qwen3.8-27b)
- Inkling 2 Mini: "GDPval-AA | 40.9%", "AA-AnalystAgent | 46.3%", "EnterpriseOps-Gym-AA | 42.0%", "CritPt v2 | 31.4%". **No AA-LCR, MLCR-AA, τ³-Banking or Terminal-Bench 2.1 rows appear for Inkling 2 Mini** in that mirror. — [OpenRouter Inkling](https://openrouter.ai/thinkingmachines/inkling-2-mini)
- AA's "Coding Index" and "Agentic Index" for Qwen3.8 27B appear only via a third-party aggregator: "Coding 11.2 AA Index · Agentic 32.3 AA Index … Benchmark data from Artificial Analysis · updated 2026-11-23". I found no equivalent figures for Inkling 2 Mini. — [Every Local AI](https://everylocalai.com/model/qwen3-8-27b)

**Staleness evidence (AA performance numbers move)**
- AA notes: "Speed and latency metrics average each endpoint's runs over the past 5 days … We run the benchmark every 6 hours." — [AA Inkling page](https://artificialanalysis.ai/models/inkling-2-mini)
- On 22 Nov, AIToolsReview quoted AA as "Output speed | 280 tokens/s | 63 tokens/s" and "Time to first answer token | 9.72 s | 117.08 s (xhigh)". It also quoted "9.0 minutes against 29.2" per task. On 27 Nov, AA shows **175 tok/s / 24.59 s / 14.5 min** for Inkling 2 Mini and **59 tok/s / 101.85 s / 31.2 min** for Qwen. — [AIToolsReview, 22 Nov 2026](https://aitoolsreview.co.uk/insights/thinking-machines-inkling-2-mini); [AA comparison](https://artificialanalysis.ai/models/comparisons/inkling-2-mini-vs-qwen3-8-27b)
- AA pages disagree with each other on the same day. The GLM-5.3 vs Qwen comparison page shows Qwen xhigh at "Time per Task 30.6", "Output Speed 60", "Time to First Answer Token 106.61", and non-reasoning "Cost per Task $3.77". The Inkling vs Qwen comparison page shows 31.2 / 59 / 101.85 and $4.63. — [AA GLM-5.3 vs Qwen](https://artificialanalysis.ai/models/comparisons/glm-5-3-vs-qwen3-8-27b); [AA Inkling vs Qwen](https://artificialanalysis.ai/models/comparisons/inkling-2-mini-vs-qwen3-8-27b)
- Provider count: AA's FAQ says Inkling 2 Mini "is available via API through 2 providers", while the page's chart panels say "No publicly available API". On 22 Nov, AIToolsReview had "1 (Thinking Machines)". For Qwen, AA says "10 API providers". — [AA Inkling](https://artificialanalysis.ai/models/inkling-2-mini); [AA Qwen](https://artificialanalysis.ai/models/qwen3-8-27b)
- AA-PersonalityBench (including "Expressiveness … Rich, varied, well-crafted language" and a "Slop Score") lists both models, but the fetched text did not contain their scores. — [AA comparison](https://artificialanalysis.ai/models/comparisons/inkling-2-mini-vs-qwen3-8-27b)

### Inferences
- The speed and cost comparisons are **endpoint comparisons**, not model comparisons. AA measured Inkling 2 Mini on TML's own API and Qwen on Alibaba's API. Alibaba's API is slow (about 54–59 tok/s) and expensive ($0.50/$3.00). Faster third-party hosts serve Qwen at 200+ tok/s (see section 4). For the narrator, who self-hosts Qwen in FP8, AA's $3.53 vs $0.59 cost figure doesn't directly apply.
- For the narrator's writing and planning jobs, the most relevant AA rows are AA-Briefcase (knowledge-work deliverables, where Qwen leads 1391 vs 1263), Strategy & Ops (39 vs 35), and the hallucination rate (Qwen better). These favour Qwen. The Inkling 2 Mini wins are concentrated in science (CritPt) and very small edges in coding.
- Default Qwen (xhigh) takes 101.85 s to the first answer token on Alibaba's API. Inkling 2 Mini's 24.59 s is still long. Both models "think" a lot before answering.

### Gaps
- No AA long-context (AA-LCR, MLCR-AA) or instruction-following score was found for Inkling 2 Mini. AA v5.0.2 has no instruction-following eval in the index.
- AA-PersonalityBench numbers were not captured.
- The v5 launch date (27 Oct 2026) was not confirmed on an AA page.

---

## 2. Vals AI: what Vals itself shows for both models

### Takeaway
Vals' live model page now shows Inkling 2 Mini at **44.03%** on the Vals Index, not the 46.5% the lab cites. Vals' own launch-day note said 46.46%. Qwen3.8-27B appears only on the older **Vals Index v2** board (48.48%, dated 27 Sep 2026), not on v2.2, so the two index scores cannot be compared directly. On individual Vals benchmarks both models ran, results split: Inkling 2 Mini leads on cyber and code migration, while Qwen leads on legal research, tax, and competitive programming.

### Cited Findings
- **Inkling 2 Mini model page (live):** "It ranks #38 of 43 models on the Vals Index with 44.03%. Its best result is #10 of 49 on CyberBench v1.1." Header: "Accuracy 44.03 % ± 1.15 · Cost / Test (Vals Index) $ 3.197 · Latency 47 min 15 s". — [Vals: Inkling 2 Mini](https://www.vals.ai/models/thinkingmachines_inkling-2-mini)
- **Vals' own launch note on the same page (dated Nov 20, 2026):** "On the Vals Index, Mini scores 46.46%, up 17.5 points from the original Inkling." and "On Vibe Code Bench, it scores 77.92%, up from the original Inkling's 19.21%." — [Vals: Inkling 2 Mini](https://www.vals.ai/models/thinkingmachines_inkling-2-mini)
- **The same page's live component scores now read:** "Vibe Code Bench v1.1.1 58.00% ±4.48 41/ 51", "Terminal-Bench 4.0 6.57% ±0.51 57/ 70", "CyberBench v1.1 74.58% ±5.35 10/ 49", "Code Migration v1.1 23.16%", "EMB v1.1 66.02%", "Finance Agent v2.1 56.54%", "Legal Research Bench 17.79%", "HLAB-Vals-1.1 5.00%", "SkillsBench 43.24%", "SWE-bench Multimodal 37.92%", "ProgramBench 0.50%", "IOI 11.61%", "Tax Agent Bench 14.12%", "MedScribe 86.37%", "MedCode 25.71%", "ProofBench v1.1 18.00%", "SRE Bench 38/ 38" (rank only, last place). — [Vals: Inkling 2 Mini](https://www.vals.ai/models/thinkingmachines_inkling-2-mini)
- **TML's claim:** "Inkling 2 Mini leads every open-weights model with less than 100B total parameters on benchmarks such as DeepSWE v1.1 (48.2%) and Vals Index v2.2 (46.5%)." In TML's table, the Qwen3.8-27B cell in the "Vals Index (v2.2)" row is "–". — [TML launch post](https://thinkingmachines.ai/news/inkling-2-mini/)
- **Vals Index v2 leaderboard ("Updated 9/27/2026"):** "| 38 | Qwen 3.8 27B | 48.48% | $8.48 | 7.99b / 149.10m | 1h01m |". Inkling 2 Mini is not on this board. The original Inkling is listed as "| 50 | Inkling | 34.10% |". — [Vals Index v2](https://www.vals.ai/benchmarks/vals_index_v2)
- **Evidence that v2 and v2.2 differ:** "EMB v1.0 has been superseded by EMB v1.1, which updates the rubric judge to GPT-6 Luna and replaces it in the Finance sector of Vals Index v2.2." — [Vals EMB](https://www.vals.ai/benchmarks/emb)
- **Qwen 3.8 27B model page (live):** "Code Migration 14.16%", "CyberBench v1.1 67.80%", "EMB 59.66%", "Finance Agent (v2) 48.55%", "Legal Research Bench 36.06%", "Tax Agent Bench 30.89%", "Vibe Code Bench v1.1 64.85%", "Terminal-Bench 2.1 58.43%", "SWE-bench 86.00% … 15/ 88", "SkillsBench 38.11%", "IOI 39.06%", "MedScribe 83.85%", "MedCode 28.70%", "ProofBench v1.1 16.00%", "GPQA Diamond 88.89%", "Terminal-Bench-Science 49/ 49". Token costs: "$0.50/3.00". Max output tokens: "66k". — [Vals: Qwen 3.8 27B](https://www.vals.ai/models/alibaba_qwen3.8-27b)
- **Vals SWE-bench Verified (Qwen):** "| 15 | Qwen 3.8 27B | Mini-SWE-agent | 86.00% | $1.08 | 1.99m | 10m00s |". Vals notes it "no longer run[s] this benchmark on new model releases", so Inkling 2 Mini has no entry. — [Vals SWE-bench](https://www.vals.ai/benchmarks/swebench)

Like-for-like rows on Vals (same benchmark name; Inkling 2 Mini vs Qwen 3.8 27B):
| Vals benchmark | Inkling 2 Mini | Qwen 3.8 27B |
|---|---|---|
| CyberBench v1.1 | 74.58% | 67.80% |
| Code Migration (v1.1 for Inkling; version unlabeled for Qwen) | 23.16% | 14.16% |
| SkillsBench | 43.24% | 38.11% |
| ProofBench v1.1 | 18.00% | 16.00% |
| MedScribe | 86.37% | 83.85% |
| Legal Research Bench | 17.79% | 36.06% |
| Tax Agent Bench | 14.12% | 30.89% |
| IOI | 11.61% | 39.06% |
| MedCode | 25.71% | 28.70% |
| Vibe Code Bench | 58.00% (v1.1.1) | 64.85% (v1.1), so versions differ |
— [Vals Inkling 2 Mini](https://www.vals.ai/models/thinkingmachines_inkling-2-mini); [Vals Qwen 3.8 27B](https://www.vals.ai/models/alibaba_qwen3.8-27b)

### Inferences
- The most likely explanation for the drop from 46.46% to 44.03% is that Vals re-ran Vibe Code Bench on version v1.1.1, where Inkling 2 Mini scored 58.00% against 77.92% on v1.1. Vals does not say this explicitly on the page; it is an inference from the changed component.
- The lab's "leads every open-weights model under 100B on Vals Index v2.2" claim holds partly because Qwen3.8-27B has no v2.2 score. On the older v2 board Qwen scored 48.48%, which is higher than either Inkling 2 Mini figure, though the versions differ.
- Vals' cost per index test ($3.197) and latency (47 min 15 s) for Inkling 2 Mini were measured at TML's prices. They suggest heavy token use on long agentic tasks, consistent with AA's verbosity finding. Qwen's v2 figure was $8.48 and 1h01m, on a different index version.

### Gaps
- Vals' v2.2 leaderboard page was not found, so I couldn't confirm "38 of 43" against a dated board.
- No Vals Index v2.2 score exists for Qwen3.8-27B.

---

## 3. Public leaderboards: coding, LMArena, writing, long context, structured output and tool calling

### Takeaway
Most of TML's agentic-coding wins over Qwen (DeepSWE, SWE-bench Pro v2 Hard, MRCR v2) have **no independent replication**; Hugging Face labels them "self-reported". Where crowds and third parties have measured, **Qwen leads** on LMArena (text, WebDev, creative writing), EQ-Bench long-form writing (Inkling 2 Mini not yet listed), a hobbyist BFCL run, and tool-call reliability through OpenRouter. Inkling 2 Mini leads in one hobbyist IFEval run.

### Cited Findings

**SWE-bench Pro, DeepSWE, SWE-bench Verified**
- TML's figures: "SWEBench Pro v2 (Hard) mini-swe-agent v2.4.6 | 77.9% | … | 73.8%" (Inkling | Qwen); the chart caption says "SWE-bench Pro v2 Hard (51 tasks)". "DeepSWE v1.1 mini-swe-agent v2.4.6 | 48.2% | … | 42.2%". "SWEBench Verified bash only | 79.2% | … | 77.8%". — [TML launch post](https://thinkingmachines.ai/news/inkling-2-mini/); [HF model card](https://huggingface.co/thinkingmachines/Inkling-2-Mini)
- A Hugging Face staff PR that adds these scores says: "Scores are copied from the published model card … They are self-reported, not verified runs." — [HF discussion #49](https://huggingface.co/thinkingmachines/Inkling-2-Mini/discussions/49)
- Scale's public SWE-Bench Pro leaderboard, as fetched, does not list either model. The fetched snapshot looked outdated (top entry "Muse Spark 1.1"), so treat its absence with caution. — [Scale SWE-Bench Pro](https://labs.scale.com/leaderboard/swe_bench_pro)
- Independent SWE-bench Verified figure for Qwen: Vals measured **86.00%** with mini-SWE-agent, a bash-only harness. TML's table lists Qwen at **77.8%** "bash only". — [Vals SWE-bench](https://www.vals.ai/benchmarks/swebench); [TML](https://thinkingmachines.ai/news/inkling-2-mini/)

**Terminal-Bench**
- AA, Terminal-Bench 4.1: both models score 5.6%. — [AA comparison](https://artificialanalysis.ai/models/comparisons/inkling-2-mini-vs-qwen3-8-27b)
- Vals, Terminal-Bench 4.0: Inkling 2 Mini 6.57% (57/70). — [Vals](https://www.vals.ai/models/thinkingmachines_inkling-2-mini)
- Terminal-Bench 2.1 results for Qwen depend heavily on the harness: TML "Terminal Bench v2.1 Inkling 2 Mini in pi v0.83.0 | 71.6% | … | 73.0%"; Vals "Terminal-Bench 2.1 58.43%"; AA "Qwen3.8 27B (Xhigh) Terminal-Bench 2.1 | 79.8%". — [TML](https://thinkingmachines.ai/news/inkling-2-mini/); [Vals Qwen](https://www.vals.ai/models/alibaba_qwen3.8-27b); [OpenRouter Qwen (AA data)](https://openrouter.ai/qwen/qwen3.8-27b)
- tbench.ai was not checked (see Gaps).

**LMArena.** All figures come via aggregators that republish LMArena data (CC BY 4.0); I did not read lmarena.ai directly.
- Inkling 2 Mini: "Chat · Text … #210 of 427 | 1,367 | 1,352–1,381 | 1,793 votes | 2026-11-22"; "Code · WebDev … #54 of 160 | 1,560 | 1,543–1,577 | 1,312 votes | 2026-11-23"; "Agent · Overall Index … #57 of 69 | 996"; "Agent · Tool Use Which agent uses tools without making things up? | #24 of 69". — [ModelChoice: Inkling 2 Mini on LMArena](https://modelchoice.dev/lmarena/models/inkling-2-mini)
- Qwen3.8 27B: Text "| 40 | Qwen3.8 27B … | 1438 ±4· 37.4K votes | Nov 22, 2026 |"; WebDev "| 10 | Qwen3.8 27B … | 1590 ±6· 22.4K votes | Nov 23, 2026 |". — [llm.ing LMArena Text](https://llm.ing/benchmarks/lmarena-text); [llm.ing LMArena WebDev](https://llm.ing/benchmarks/lmarena-webdev)
- Creative writing (read 27 Nov): "| 86 | Qwen3.8 27B Qwen | 1379 | 7,741 | ±7.9 |" vs "| 167 | Inkling 2 Mini Thinking Machines | 1207 | 423 | ±32.6 |". — [LLMBenchmark.ai LMArena creative writing](https://llmbenchmark.ai/benchmarks/lmarena-creative-writing)
- BenchClub's category table (Qwen | Inkling): "Arena score | 1438 | 1344", "Creative writing | 1379 | 1207", "Instructions | 1434 | 1361", "Hard prompts | 1458 | 1371", "Multi-turn | 1439 | 1334", "Coding | 1481 | 1431". Note the conflict: BenchClub gives Inkling 2 Mini 1344 overall, while ModelChoice gives 1,367 (probably a different date or board variant). — [BenchClub](https://www.benchclub.ai/compare?m=qwen-qwen3.8-27b&m=thinkingmachines-inkling-2-mini)

**EQ-Bench (long-form creative writing, v1.11, judged by Claude Sonnet 4.6)**
- "| 86 | Qwen 3.8 27B | 53.3 | | Aug 2026 | eqbench.com | Official leaderboard |". The original **Inkling** (not Inkling 2 Mini) scores "72.5 … Jul 2026". **Inkling 2 Mini is not listed** as of the 27 Nov read. — [Benchmark Almanac (EQ-Bench longform)](https://www.benchmarkalmanac.com/benchmarks/eqbench-longform-writing/); [EQ-Bench longform](https://eqbench.com/creative_writing_longform.html)
- Method: "Models plan, revise and then write a short story or novella over eight 1,000-word turns from a minimal prompt." It also tracks "Degradation", i.e. how much chapter quality drops by the end. — [EQ-Bench](https://eqbench.com/creative_writing_longform.html)

**Long context**
- TML's figures: "MRCR v2 8-needle 256K–512K | 46.4% | … | 38.0%", "LongBench v2 | 66.9% | … | 52.3%", "GraphWalks BFS 256K | 69.7% | … | 50.4%", "AA-LCR v1.1 | 80.0% | … | 82.0%". — [TML model card](https://thinkingmachines.ai/model-card/inkling-2-mini/)
- AA's independent figures for Qwen: "AA-LCR | 82.0%" (matches TML's Qwen figure) and "MLCR-AA | 22.8%". I found no AA long-context figures for Inkling 2 Mini. — [OpenRouter Qwen (AA data)](https://openrouter.ai/qwen/qwen3.8-27b)
- Context limits: AA lists Qwen at "256k", Vals at "262k" with "Max Output Tokens 66k". Inkling 2 Mini is listed at "1M" (OpenRouter: "1,048,576 token context window … up to 65,536 completion tokens"). A hobbyist reviewer lists "Native context | 262,144 (extendable to 1M)". — [AA](https://artificialanalysis.ai/models/qwen3-8-27b); [Vals Qwen](https://www.vals.ai/models/alibaba_qwen3.8-27b); [OpenRouter Inkling](https://openrouter.ai/thinkingmachines/inkling-2-mini); [Demietrich](https://www.demietrich.com/blog/inkling-2-mini-review/)
- No independent RULER or Fiction.LiveBench entries were found for either model.

**Structured output and tool calling**
- dottxt Tool-call Index, home page ("data as of 2026-11-27"):
  - Tool calls: "| Qwen3.8 27B | Qwen | 17 | ModelRun [by Modular] (fp4) 0.14% | AkashML (fp8) 32.10% |" and "| Inkling 2 Mini | Thinking Machines | 1 | io.net (nvfp4) 4.18% | io.net (nvfp4) 4.18% | none (single provider) |".
  - Structured outputs: "| Qwen3.8 27B | Qwen | 14 | AkashML (fp8) 0.00% | CoreWeave (fp8) 0.10% |" and "| Inkling 2 Mini | Thinking Machines | 2 | io.net (nvfp4) 0.00% | DeepInfra (fp4) 0.01% |".
  - Source: [dottxt Tool-call Index](https://providers.dottxt.ai/)
- dottxt Qwen page ("Window: 2026-11-17 to 2026-11-24"): "Wafer (fp8) … 0.10%", "Alibaba Cloud Int. (Lab's API) … 3.13%", "Cerebras (fp16) … 6.28%". Recommendation: "Use `wafer/fp8`, `modelrun/fp4`, `parasail/fp8`. Avoid `alibaba`, `cloudflare`, `coreweave/fp8`, `cerebras/fp16`, `siliconflow/fp8`, `akashml/fp8` (≥3% broken tool calls)." — [dottxt: Qwen3.8 27B](https://providers.dottxt.ai/m/qwen/qwen3.8-27b/)
- dottxt Inkling 2 Mini page: "io.net nvfp4 … 4.56% | 13k" tool calls a day; "No recommended settings for Inkling 2 Mini — Fewer than two providers at 1,000 tool calls a day or more." — [dottxt: Inkling 2 Mini](https://providers.dottxt.ai/m/thinkingmachines/inkling-2-mini-20261120/)
- dottxt's method caveats: rates are "OpenRouter's published tool-call error rate per provider endpoint … over the last 7 days"; "This underestimates the real error rate: parsing errors … aren't counted"; for structured outputs, OpenRouter "doesn't document what fails one". — [dottxt](https://providers.dottxt.ai/)
- Hobbyist BFCL v4 run (300 samples, vLLM NVFP4): "BFCL v4 | 300 | 76.00 | 85.00 | 82.67" (Inkling | Qwen | Gemma4-26B), with subsets "live_multiple | 68 | 82" and "multi_turn_base | 54 | 70". IFEval prompt-strict: "88.80 | 79.60". The Qwen columns are "the results already published on the /benchmarks page", i.e. from earlier runs rather than the same session. — [Demietrich, 22 Nov 2026](https://www.demietrich.com/blog/inkling-2-mini-review/)

### Inferences
- For a product that returns structured JSON, the independent picture favours Qwen on tool-call reliability. This is mostly a provider-maturity effect: there is only one measured Inkling provider, at about 4.2–4.6% broken tool calls, against about 0.1% for the best Qwen hosts. Structured-output (`response_format`) failure rates are near zero for both.
- On long-form writing, the only independent writing signals (LMArena creative writing; EQ-Bench, where Inkling 2 Mini is absent) favour Qwen or are missing for Inkling. Inkling 2 Mini's 1207 rests on only 423 votes (±32.6).
- TML's Qwen SWE-bench Verified figure (77.8%) is about 8 points below Vals' independent 86.00%. The lab may be understating its rival, or the setups differ.

### Gaps
- tbench.ai, swebench.com bash-only rows, and DeepSWE's official board were not checked or showed no entries.
- No independent BFCL leaderboard, RULER or Fiction.LiveBench scores were found.
- LMArena figures were read through aggregators, not lmarena.ai directly.

---

## 4. OpenRouter: providers, pricing, throughput, latency, tool-call errors

### Takeaway
Qwen3.8-27B has a far larger provider market (about 22 endpoints). Inkling 2 Mini has 4 providers plus tiers. Inkling 2 Mini is roughly 8× cheaper on the output prices customers actually pay. At the top end, throughput is similar: Inkling 2 Mini reaches up to 289 tok/s, and Qwen reaches 240 tok/s on Wafer or 912 tok/s on Cerebras.

### Cited Findings
- **Inkling 2 Mini listed endpoints** (Provider | In/M | Out/M | Latency | Throughput | Uptime): "Prime Intellect | $0.06 | $0.24 | 0.59 s | 116 tok/s | 100.00%"; "DeepInfra | $0.075 | $0.30 | 0.26 s | 191 tok/s | 99.69%"; "Prime Intellect Fast | $0.15 | $0.60 | 0.43 s | 289 tok/s | 99.85%"; "Darkbloom | $0.02625 | $0.105 | 1.39 s | 48 tok/s | 99.89%"; "io.net | $0.08 | $0.35 | 4.33 s | 76 tok/s | 98.24%"; "Prime Intellect Flex | $0.0375 | $0.15 | 0.53 s | 90 tok/s". Weighted average actually paid: "$0.02093/M tokens" input, "$0.2953/M tokens" output. Prime Intellect carries "63.1%" of the token share. "Availability (3d) … 99.92%". FAQ: "accepts `tools` and `tool_choice` … on 3 of the 4 providers"; "supports structured outputs via a JSON schema in `response_format`". OpenRouter lists the release date as "Nov 21, 2026". — [OpenRouter: Inkling 2 Mini](https://openrouter.ai/thinkingmachines/inkling-2-mini)
- **Inkling 2 Mini AutoExacto (7-day rolling):** "| Provider | GPQA Diamond (Unsaturated) | Tool Call Schema Fuzz |" with rows "Darkbloom | 74.2% | 98.9%", "auto-routing | 76.9% | 88.8%", "io.net | 74.9% | 88.1%", "Relace | 71.8% | 90.4%", "Prime Intellect | 73.2% | 88.2%". — [OpenRouter: Inkling 2 Mini](https://openrouter.ai/thinkingmachines/inkling-2-mini)
- **Qwen3.8 27B listed endpoints (selection):** "Wafer | $0.06 | $1.96 | 0.43 s | 240 tok/s | 100.00%"; "ModelRun [by Modular] | $0.20 | $2.50 | 0.13 s | 239 tok/s | 97.44%"; "Nebius Token Factory | $0.45 | $3.00 | 0.65 s | 202 tok/s"; "Cerebras | $0.99 | $1.49 | 0.15 s | 912 tok/s | 100.00%"; "Alibaba Cloud Int. | $0.425 | $2.55 | 0.56 s | 54 tok/s"; "Chutes | $0.039 | $1.25 | 3.41 s | 54 tok/s"; "SiliconFlow | $0.425 | $2.55 | 0.67 s | 14 tok/s | 96.15%". The headline lowest price is "$0.035 / $1.50 per 1M". Weighted average actually paid: "$0.1475/M tokens" input, "$2.409/M tokens" output. AutoExacto: "Wafer -- 97.1%", "Prime Intellect 81.0% 99.9%", "auto-routing 76.2% 95.4%", "Cloudflare 83.1% 88.2%", "ModelRun 75.5% 95.0%" (GPQA Unsat, Tool Call Schema Fuzz). — [OpenRouter: Qwen3.8 27B](https://openrouter.ai/qwen/qwen3.8-27b)
- Usage: BenchClub, citing OpenRouter "as of 2026-11-25", lists "API tokens, 7 days | 743.7B | 308.1B" (Qwen | Inkling) and Hugging Face "Downloads, last 30 days | 6M | 96.5K". — [BenchClub](https://www.benchclub.ai/compare?m=qwen-qwen3.8-27b&m=thinkingmachines-inkling-2-mini)
- Tool-call error rates per provider are covered in section 3 (dottxt, built on OpenRouter data).

### Inferences
- Output price matters most for long-form writing jobs. On weighted-average output price actually paid, Inkling 2 Mini ($0.2953/M) is about 8× cheaper than Qwen ($2.409/M). AA found Inkling 2 Mini writes about 26% more output tokens on the index (161M vs 128M), which narrows but does not erase that gap.
- Throughput differences between providers are larger than differences between the two models.

### Gaps
- OpenRouter's per-model tool-call error rates for Inkling's other providers (DeepInfra, Prime Intellect, Darkbloom) were not in the dottxt index.
- P90/P99 latency figures were not captured.

---

## 5. Local inference: speed, memory, quantisation quality, and whether looping slows Inkling 2 Mini down

### Takeaway
At 4-bit, both models need about 17–18 GB for weights. Inkling 2 Mini ships natively in NVFP4/MXFP8, so its "full precision" is about 20–23 GB, against 56 GB for Qwen at BF16. On machines where Qwen doesn't fit fully on the GPU, Inkling 2 Mini is several times faster. **On a GPU that holds both models whole, the decode gap is small**: on an RTX 3090 with the same llama.cpp build, 38.7 vs 34.5 tok/s, and Qwen read prompts faster. The loop does cost speed: running one pass instead of three made decoding about 2× faster but wrecked quality.

### Cited Findings

**Memory and quantisation (Unsloth's own figures, plus one independent check)**
- Unsloth, Inkling 2 Mini: "| 1-bit | 2-bit | 3-bit | 4-bit | 8-bit (Lossless) | → | 9 GB | 10-11 GB | 13-15 GB | 17-18 GB | 24 GB |"; "The 4-bit `UD-Q4_K_XL` gets 0.0107 mean KLD and 98.0% top-token agreement at 17.63 GB. The 2-bit `UD-IQ2_XXS` brings the download down to 8.49 GB with 90.6% agreement." The reference is UD-Q8_K_XL (22.87 GB), not BF16. — [Unsloth: Inkling 2 Mini](https://unsloth.ai/docs/models/inkling-2-mini)
- Independent re-measurement against F32 (Xylolabs, which also publishes competing quants): "Unsloth UD-Q4_K_XL | 17.63 GB | 0.0029 | 97.6%" (WikiText-2 KL, top-1) and "llama.cpp baseline Q4_K_M | 17.48 GB | 0.0167 | 94.4%". — [Xylolabs GGUF](https://huggingface.co/Xylolabs/Inkling-2-Mini-GGUF)
- Unsloth, Qwen3.8-27B: "Qwen3.8- 27B 4-bit quants work on 16-19GB VRAM like RTX 5080, 4090 or a Mac with 24GB RAM." Table: "| 1-bit | 2-bit | 3-bit | 4-bit | 6-bit | 8-bit | BF16 | → | 7-8 GB | 9-11 GB | 12-14 GB | 16-19 GB | 23-26 GB | 31 GB | 56 GB |". "Dynamic V3.1 Update (November 11th 2026)". — [Unsloth: Qwen3.8](https://unsloth.ai/docs/models/qwen3.8)
- Qwen quant quality, measured on a Mac mini M6 32GB on 2026-10-11 against UD-Q6_K rather than BF16: "UD-Q4_K_XL 17.6GB | 0.0068 | 96.4% | 0.0236 | 95.0%" (Korean KL, match, English KL, match). — [gitseonjeap](https://gitseonjeap.com/en/blog/qwen27b-4bit-fast-macmini)
- Qwen KV-cache quantisation: "A 4-bit cache has a measurable impact"; "the added KL is about 15-30% higher at 16-32k tokens than in the first 4k". — [Erlidev](https://erli.xyz/posts/qwen38-27b-quant-kv-comparison/)
- Hardware guidance for Inkling 2 Mini, quoted from the model card by a reviewer: "1× DGX Spark · Apple silicon ≥32 GB · ≥32 GB VRAM recommended". — [Demietrich](https://www.demietrich.com/blog/inkling-2-mini-review/)

**Apple silicon, Inkling 2 Mini**
- M4 Max 128 GiB (GitHub PR comment, 21 Nov, read via a mirror site): "mlx-lm, original checkpoint | 33.7 tok/s | 85.2 tok/s | 18.7 GiB"; "llama.cpp, IQ4_NL | 36.1 tok/s | 84.6 tok/s | 18.6 GiB"; "llama.cpp, Q8_0 | 33.9 tok/s | 75.6 tok/s | 28.2 GiB" (1-stream decode | 4-stream total | peak memory). Caveat from the tester: "Every generation hit the 256-token cap while the model was still reasoning." — [PR #4274 mirror](https://coolrandomwebsite.com/p/bookmark-0279/ashhart/TensorFold/pull/4274)
- M4 Max Mac Studio 64 GB, writing speed in tok/s, MLX-Serve → optimised server: "4k … 76.3 → 80.4", "32k … 72.6 → 75.7", "131k … 51.7 → 56.6", "262k … 32.1 → 38.0", "524k … 16.1 → 17.3". Draft heads were on, and "The weights are about 18 GiB." — [tomascupr/inkling-mini-mac-longctx](https://github.com/tomascupr/inkling-mini-mac-longctx)
- M5 Pro 64 GB Mac mini (24 Nov): "oMLX + DSpark … 49.09 tok/s at 512 … 48.04 tok/s at 4k"; with MTP off, "40.23 and 35.44 tok/s" at 16k and 32k. "MLX 4-bit was 33.53 / 16.76 / 12.20 / 12.57" and "llama.cpp official IQ4_NL was 10.56 / 9.44 / 15.57 / 17.64" (a background app was running). TTFT on GGUF was "3.40 / 29.07 / 114.16 / 218.82 s versus 0.55 / 3.54 / 15.05 / 32.85 s" on oMLX. — [pratikgx field notes](https://github.com/pratikgx/local-ai-field-notes/blob/main/notes/2026-11-24-thinking-machines-inkling-2-mini-mlx-vllm.md)
- M3 Max (RAM size not stated in the excerpt): "the 4-bit build decodes at 45.60 ± 0.15 tok/s at 4096 tokens of context … Native precision decodes at 36.36 ± 0.62 … Peak memory at 4096 is 20.18 GB for 4-bit and 24.34 GB for native"; llama.cpp IQ4_NL "29.30 ± 0.18 decode". — [Destroy / Rebuild](https://www.destroyrebuild.xyz/blog/inkling-on-mac/)

**Apple silicon, Qwen3.8-27B (dense)**
- Mac mini M6 32GB (2026-10-11), UD-Q4_K_XL, tok/s by prompt type (Korean / English / Code / JSON): "speculation off (baseline) | 8.5 | 8.2 | 8.1 | 7.9"; "+ MTP | 11.2 | 12.4 | 20.1 | 21.8"; "+ DFlash2 | 8.3 | 14.2 | 38.9 | 44.4". — [gitseonjeap](https://gitseonjeap.com/en/blog/qwen27b-4bit-fast-macmini)
- MacBook Pro M5 Pro, 48 GB (Nov 2026), UD-Q4_K_XL 17.7 GB, 128K context: "llama.cpp with MTP | 20.3 | 331"; "Kapitsa | 41 | 443"; "Splash | 61 | 666" (generation | prompt processing). Also "on battery with Low Power Mode: 28 tokens per second; plugged in with High Power mode: 63". — [Emanuel's Blog](https://emasblog.dev/posts/2026/11/qwen3.8-27b-on-m5-pro-macbook-pro/)

**NVIDIA**
- Inkling 2 Mini on an RTX PRO 6000 Blackwell (96 GB), vLLM NVFP4, no speculative decoding (22 Nov), decode tok/s: "1k … 167.4", "8k … 163.9", "32k … 152.9", "131k … 121.3", "262k … 95.2"; TTFT "23.79 s" at 262k. With 8 concurrent clients, aggregate decode was "168.7 → 740.7 (x4.39)". "Size in VRAM | 42,986 MiB (42.0 GiB)" for one 262k stream with BF16 KV cache. — [Demietrich](https://www.demietrich.com/blog/inkling-2-mini-review/)
- DGX Spark (GB10): "vLLM, original checkpoint | 38.7 tok/s"; "…DSpark | 48.6 tok/s"; "llama.cpp, IQ4_NL | 38.8 tok/s". — [PR #4274 mirror](https://coolrandomwebsite.com/p/bookmark-0279/ashhart/TensorFold/pull/4274)
- **Same-GPU head-to-head, RTX 3090 (24 GB), same llama.cpp build (22 Nov):** "Average tok/s | 38.7 | 34.5"; "Prefill | 779 tok/s … | 1,004 tok/s"; "Context | 131,072 | 98,304"; "Peak VRAM | 24.0 GB … | 24.1 GB" (Inkling | Qwen; both UD-Q4_K_XL, Qwen without its MTP draft head). — [Bench Lab](https://benchlab.ironyaditya.xyz/posts/2026-11-22-inkling-2-mini-vs-qwen-27b-pagoda/)
- **RTX 5060 Ti 16 GB, where Qwen spills to the CPU (21 Nov):** "512 token 解碼速度 | 38.2 tok/s | 6.1 tok/s" (512-token decode speed); "顯示記憶體峰值 | 15.4 GB | 14.1 GB" (peak VRAM). Qwen had only "65 層中 48 層上 GPU" (48 of 65 layers on the GPU). The author notes that on a 24 GB-plus card "差距會大幅縮小" (the gap would shrink greatly). — [CyberQ](https://cyberq.tw/2026/11/21/inkling-2-mini-debuts-5b-enables-a-loop/)

**Does the loop make Inkling 2 Mini slower than "3.4B active" suggests?**
- TML's model card: "Because the middle layers run three times, compute per token is higher than the active-parameter count alone suggests." Also: "Support for looped models in local runtimes is new, and speed varies by runtime and hardware." — [TML model card](https://thinkingmachines.ai/model-card/inkling-2-mini/)
- TML's speed chart caption: "Decoding speed is a theoretical ceiling at 614 GB/s with BF16 weights and batch size one, including repeated reads across loops." — [TML launch post](https://thinkingmachines.ai/news/inkling-2-mini/)
- Measured effect of fewer passes: "Two passes give 1.39× the decode speed and one pass gives 2.06×, but perplexity goes from 6.89 to 12.12 (×1.76) at two passes and to 16.10 (×2.34) at one. The model was trained at 3 passes only." — [Destroy / Rebuild](https://www.destroyrebuild.xyz/blog/inkling-on-mac/)
- The M5 Pro tester's best result was "about 66% of the estimated 307 GB/s ceiling, from model geometry". — [pratikgx](https://github.com/pratikgx/local-ai-field-notes/blob/main/notes/2026-11-24-thinking-machines-inkling-2-mini-mlx-vllm.md)

### Inferences
- Yes, the loop roughly halves decode speed compared with a single pass of the same weights. Inkling 2 Mini still decodes faster than dense Qwen on the same hardware. The margin is large when Qwen doesn't fit in VRAM (6.3× on a 16 GB card) and small when it does (about 12% on a 24 GB RTX 3090). Speculative decoding (MTP or DFlash drafts) can lift Qwen to 40–60+ tok/s on Macs, so engine choice matters as much as model choice.
- For the narrator's rented GPU running Qwen in FP8, which is about 31 GB of weights by Unsloth's 8-bit figure, switching to Inkling 2 Mini's native NVFP4/MXFP8 (about 20 GB) would free VRAM for KV cache and batching. The independent Blackwell vLLM numbers show strong concurrency scaling (740 tok/s aggregate at 8 clients). I found no same-GPU FP8 Qwen vs NVFP4 Inkling server test to quantify the throughput difference.
- 24 GB Macs: Unsloth says 4-bit Qwen fits "a Mac with 24GB RAM". Inkling 2 Mini at 4-bit needs 17–18 GB and measured 18.6–20.2 GB peak at 4k context, and the model card recommends 32 GB or more. 24 GB is likely tight, but I found no measurement on a 24 GB Mac for either model.

### Gaps
- No measured runs on a 24 GB or 32 GB Mac for Inkling 2 Mini, and none on a 24 GB Mac for Qwen.
- No measured Qwen FP8 throughput on a datacenter GPU.
- No Unsloth KL figures against BF16 for Qwen Dynamic V3.1 were captured (that table was not in the fetched text).
- llama.cpp support for Inkling 2 Mini is still on unmerged PRs (Bench Lab "merged the open pull requests"), so local GGUF speeds are likely to change soon.

---

## 6. Independent head-to-heads: who tested, how, and possible conflicts

### Takeaway
There are three hands-on comparisons by independent hobbyists or media, each small-sample and none sponsored as far as disclosed. They point in different directions:
- **Long agentic coding session:** Inkling 2 Mini won (half the time, half the tokens).
- **Short JSON classification:** Qwen won, because Inkling 2 Mini cannot fully switch off thinking and got truncated before answering.
- **Mixed benchmark suite:** Inkling 2 Mini won IFEval and coding; Qwen won BFCL tool calling.

### Cited Findings
- **CyberQ (Taiwanese tech blog), 21 Nov 2026.** RTX 5060 Ti 16 GB, both models UD-Q4_K_XL, Unsloth llama.cpp b12588, temperature 0. The task was 20 synthetic insider-threat log entries requiring JSON output (表 = table rows):
  - "Inkling，思考關（none） | 13/20 | 11/20 | … | 9.5 | 332 | 7 題" (thinking "off": 13/20 correct, 7 items with no answer written)
  - "Inkling，思考開（high） | 19/20 | 16/20 | … | 31.1 | 1,135 | 1 題"
  - "Qwen，思考關 | 20/20 | 17/20 | … | 5.3 | 24 | 0 題"
  - "Qwen，思考開 | 20/20 | 17/20 | … | 100.9 | 597 | 0 題"
  - Key line: "設成 reasoning_effort=none 後，每題仍先寫約 1,000 字的思考，20 題中有 7 題在 400 token 內還沒想完就被截斷" (with reasoning_effort=none, each item still began with about 1,000 characters of thinking, and 7 of 20 were cut off at 400 tokens before finishing).
  - Self-caveat: "這個測試只有 20 題 … 屬於小樣本的情境測試" (only 20 items; a small-sample scenario test).
  - No conflict of interest disclosed. — [CyberQ](https://cyberq.tw/2026/11/21/inkling-2-mini-debuts-5b-enables-a-loop/)
- **Bench Lab (individual blogger), 22 Nov 2026.** One RTX 3090, same llama.cpp build, omp agent, thinking high; one run building a three.js voxel pagoda.
  - "Time | 1 h 23 min 45 s | 2 h 49 min 6 s"; "Tokens out | 144K | 289K"; "Model calls | 198 | 194".
  - Verdict: "Inkling 2 Mini — The winner. A clean, complete island in half the time…"; Qwen "planted its forest in the wrong place".
  - Caveats stated by the author: Qwen ran at 98K vs 131K context, without MTP, and with different sampling (temperature 1.0 vs 0.6, each maker's recommended setting). — [Bench Lab](https://benchlab.ironyaditya.xyz/posts/2026-11-22-inkling-2-mini-vs-qwen-27b-pagoda/)
- **Demietrich (individual reviewer and self-described Qwen3.8-27B daily user), 22 Nov 2026.** RTX PRO 6000, vLLM.
  - Six-suite means: "mean of the six | | 89.21 | 87.96 | 89.70" (Inkling | Qwen | Gemma4-26B).
  - On the Word500 reasoning puzzle, Inkling scored "50/60" vs Qwen "(37/60)", with "Eight loop aborts" for Inkling.
  - Conclusion: "It thinks a LOT and uses a LOT of tool calls … Experienced some looping reasoning." He also wrote he was "consistently impressed with both its prose and tool calling capabilities" while using it for planning and brainstorming in OpenWebUI. That last point is anecdotal.
  - Caveats: Qwen scores came from earlier runs; the Arena-Hard judge was DeepSeek V4-Flash; "not comparable to leaderboards". — [Demietrich](https://www.demietrich.com/blog/inkling-2-mini-review/)
- **AIToolsReview, 22 Nov 2026.** Compiles others' numbers only: "AI Tools Review has not yet run its own tests on the model." Its verdict: "'beats Qwen' is fair for coding agents and tool use. For general chat, it is not." — [AIToolsReview](https://aitoolsreview.co.uk/insights/thinking-machines-inkling-2-mini)
- **VitoMind (ruocco.it).** Ran an RTX 3060 test with mismatched quants (Inkling "2-bit community file (bartowski IQ2_XXS) on reasoning effort medium" vs Qwen "3-bit … with thinking switched off"). Results were not captured, and the setup is not a fair comparison. — [VitoMind](https://ruocco.it/ai-demos/inkling-2-mini-vs-qwen-3-8-27b-rtx-3060/)
- **Other sources with possible interests:**
  - Unsloth publishes quants for both models and its KL figures describe its own quants.
  - Xylolabs publishes competing GGUFs.
  - dottxt sells a structured-generation API (its index links to "dottxt-api").
  - Vals supplied several of the scores TML cites ("Vibe Code Bench v1.1 openhands (vals)", "Code Migration v1.1 pi (vals)") and posted "Congrats to the Thinking Machines team on the release!"
  - Sources: [Unsloth](https://unsloth.ai/docs/models/inkling-2-mini); [Xylolabs](https://huggingface.co/Xylolabs/Inkling-2-Mini-GGUF); [dottxt](https://providers.dottxt.ai/); [TML model card](https://thinkingmachines.ai/model-card/inkling-2-mini/); [Vals](https://www.vals.ai/models/thinkingmachines_inkling-2-mini)

### Inferences
- The CyberQ result maps most directly onto the narrator's workload (thinking on, structured JSON). With thinking on, both models got the classifications right; Inkling 2 Mini was faster (31 s vs 101 s per item) but wrote about 1.9× more tokens and once ran to its 4,000-token cap without answering. Any switch would need generous `max_tokens` and limits on output tokens and turns, which TML itself recommends ("We recommend setting limits on output tokens and agent turns").
- No independent test covered long-form prose quality across long sessions, which is the narrator's core use case.

### Gaps
- No independent head-to-head on long-form writing quality or multi-hour planning sessions with JSON output.
- The WorldofAI YouTube test (22 Nov, cited by AIToolsReview) was not reviewed.

---

## 7. Where independent results agree or disagree with the labs' claims

### Takeaway
Independent referees **agree** with TML that the two models tie on AA's index and that Inkling 2 Mini is much cheaper and faster on hosted APIs. They **disagree or complicate** TML's claims on: token efficiency (AA says Inkling 2 Mini is the most verbose model in its class), the Vals Index figure (now 44.03%, not 46.5%), Vibe Code Bench (now 58.00% on v1.1.1, not 77.9%), tool-calling and chat or writing preference (Qwen leads), and Qwen's own SWE-bench Verified score (Vals measured higher than TML reported).

### Cited Findings

| Topic | Lab says (verbatim) | Independent says (verbatim) |
|---|---|---|
| Token efficiency | TML: "This allows the model to apply more reasoning and reach the right answer with fewer tokens, especially on tasks such as agentic coding" ([TML](https://thinkingmachines.ai/news/inkling-2-mini/)) | AA: "When evaluating the Intelligence Index, it generated 161M tokens, which is very verbose in comparison to the median of 93.4M"; Verbosity "#14 / 14"; Qwen xhigh used 128M ([AA](https://artificialanalysis.ai/models/inkling-2-mini)). Bench Lab's agent run: "Tokens out | 144K | 289K", favouring Inkling ([Bench Lab](https://benchlab.ironyaditya.xyz/posts/2026-11-22-inkling-2-mini-vs-qwen-27b-pagoda/)) |
| Vals Index | TML: "Vals Index v2.2 (46.5%)" ([TML](https://thinkingmachines.ai/news/inkling-2-mini/)) | Vals (live): "It ranks #38 of 43 models on the Vals Index with 44.03%"; Vals' 20 Nov note: "Mini scores 46.46%" ([Vals](https://www.vals.ai/models/thinkingmachines_inkling-2-mini)) |
| Vibe Code Bench | TML: "Vibe Code Bench v1.1 openhands (vals) | 77.9% | … | 64.9%" ([TML card](https://thinkingmachines.ai/model-card/inkling-2-mini/)) | Vals (live): "Vibe Code Bench v1.1.1 58.00% ±4.48 41/ 51" ([Vals](https://www.vals.ai/models/thinkingmachines_inkling-2-mini)) |
| AA Index | TML: "AA Index (v5.0) | 20.1 | … | 20.1" | AA: "Inkling 2 Mini and Qwen3.8 27B tie at 20" ([AA](https://artificialanalysis.ai/models/comparisons/inkling-2-mini-vs-qwen3-8-27b)), so they **agree** |
| Speed | TML: "It runs faster than similarly performing models as well." | AA: 175 vs 59 tok/s; 14.5 vs 31.2 min per task (first-party APIs), so they **agree**. But on the same RTX 3090: "Average tok/s | 38.7 | 34.5" ([Bench Lab](https://benchlab.ironyaditya.xyz/posts/2026-11-22-inkling-2-mini-vs-qwen-27b-pagoda/)), and on OpenRouter Qwen reaches "240 tok/s" (Wafer) and "912 tok/s" (Cerebras) ([OpenRouter](https://openrouter.ai/qwen/qwen3.8-27b)) |
| Qwen SWE-bench Verified | TML lists Qwen at "SWEBench Verified bash only | … | 77.8%" | Vals: "Qwen 3.8 27B | Mini-SWE-agent | 86.00%" ([Vals](https://www.vals.ai/benchmarks/swebench)) |
| Agentic coding wins (DeepSWE 48.2 vs 42.2; SWE-bench Pro v2 Hard 77.9 vs 73.8) | TML table | HF: "They are self-reported, not verified runs" ([HF #49](https://huggingface.co/thinkingmachines/Inkling-2-Mini/discussions/49)). No independent replication found |
| Terminal-Bench 4.x | TML: "Terminal Bench v4.0 … 5.6% | … | 5.6%" | AA TB 4.1: 5.6% / 5.6%; Vals TB 4.0: Inkling 6.57%, so they **agree** (both models are weak here) |
| Reasoning off | TML: "Setting reasoning effort to its minimum does not fully disable reasoning." | CyberQ **confirms**: with "reasoning_effort=none", 7/20 items were truncated before answering ([CyberQ](https://cyberq.tw/2026/11/21/inkling-2-mini-debuts-5b-enables-a-loop/)) |
| Looping and repetition | TML: "the model sometimes became stuck in long reasoning loops" | Demietrich **confirms**: "Eight loop aborts" in 60 Word500 runs ([Demietrich](https://www.demietrich.com/blog/inkling-2-mini-review/)) |
| Multi-turn chat | AIToolsReview's summary of TML: Inkling "scores 50.0% on MultiChallenge, a multi-turn conversation test, behind Qwen3.8-27B" | LMArena (via BenchClub): "Multi-turn | 1439 | 1334" (Qwen | Inkling), which **agrees** that Qwen leads ([BenchClub](https://www.benchclub.ai/compare?m=qwen-qwen3.8-27b&m=thinkingmachines-inkling-2-mini)) |
| Tool use | TML: "MCP Atlas Public | 82.7% | … | 77.3%", an Inkling win | Hobbyist BFCL v4: "76.00 | 85.00" (Inkling | Qwen) ([Demietrich](https://www.demietrich.com/blog/inkling-2-mini-review/)); dottxt: Inkling's only measured provider breaks 4.18% of tool calls vs 0.14% for Qwen's best ([dottxt](https://providers.dottxt.ai/)). This **contradicts** the lab's framing |
| Instruction following | TML: "ComplexConstraints v1.1 … | 33.4% | … | 30.1%" | Hobbyist IFEval prompt-strict: "88.80 | 79.60" (Inkling leads), which **agrees** ([Demietrich](https://www.demietrich.com/blog/inkling-2-mini-review/)); LMArena "Instructions | 1434 | 1361" (Qwen leads on human preference) |
| Factual recall | TML: "While looping improves the model's reasoning, it doesn't enable its weights to store more facts." (as quoted by [AIToolsReview](https://aitoolsreview.co.uk/insights/thinking-machines-inkling-2-mini)) | AA: Non-hallucination rate 63.4% (Inkling) vs 71.4% (Qwen). Qwen hallucinates less |

### Inferences
- For the narrator's question, the independent evidence that favours switching is: cost (about 6× cheaper per AA task on first-party APIs, about 8× on OpenRouter output price actually paid), speed when VRAM is limited, a 1M-token context, and smaller weights.
- The independent evidence against switching for long-form writing plus JSON is: Qwen's lead on human-preference writing votes (LMArena creative writing 1379 vs 1207); Qwen's lower hallucination rate; Qwen's better tool-call reliability on hosted providers; Inkling 2 Mini's higher verbosity and documented reasoning loops; and Inkling 2 Mini's inability to fully switch off thinking (less relevant, since the narrator runs with thinking on).
- No independent source directly tests the narrator's workload: long-form writing and planning with structured JSON over long sessions.

### Gaps
- No independent replication of DeepSWE, SWE-bench Pro v2 Hard (51 tasks), MRCR v2, LongBench v2 or GraphWalks for either model.
- No EQ-Bench entry for Inkling 2 Mini yet.

---

### Likely to go stale (check again before publishing)
- **AA speed, latency and cost per task.** These are 5-day rolling averages: Inkling 2 Mini's speed dropped from 280 to 175 tok/s between 22 and 27 Nov. Provider counts on AA are also changing.
- **Vals Index for Inkling 2 Mini.** It moved from 46.46% to 44.03% within a week, and the component versions are changing (Vibe Code Bench v1.1 → v1.1.1).
- **OpenRouter prices and providers, and dottxt.** dottxt uses a 7-day window; its Qwen page says "Valid until: 2026-11-26". Inkling 2 Mini has 1 provider measured for tool calls today.
- **LMArena.** Inkling 2 Mini has small vote counts (1,793 text, 423 creative writing), so expect movement.
- **EQ-Bench.** Inkling 2 Mini is not listed yet.
- **Local speeds.** llama.cpp Inkling support is on unmerged PRs; MLX servers are being tuned weekly; Unsloth re-uploaded Qwen quants on 11 Nov.
