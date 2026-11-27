# Thinking Machines Lab's official material on Inkling 2 Mini (and siblings)

Research date: 27 November 2026. Everything below is **the lab's own claim** unless marked otherwise. No independent verification was done in this note; where independent checks are needed it says so.

**Sources used (all primary, Thinking Machines Lab):**
- [A] Announcement post "Introducing Inkling 2 Mini", dated **Nov 20, 2026**: https://thinkingmachines.ai/news/inkling-2-mini/ (no "update" banner visible when fetched on 27 Nov 2026)
- [B] Hugging Face model card (5-model benchmark table): https://huggingface.co/thinkingmachines/Inkling-2-Mini ("Date of release: November 20, 2026")
- [C] Thinking Machines website model card (**wider 8-model table with ~25 extra rows**, not shown on HF): https://thinkingmachines.ai/model-card/inkling-2-mini/
- [D] Variable-loop research model card: https://thinkingmachines.ai/model-card/tml-d24-varloop-research/
- [E] "Introducing Inkling 2 Small", dated **Nov 5, 2026**, with a **"Nov 12, 2026 update"** banner: https://thinkingmachines.ai/news/inkling-2-small/
- [F] "Inkling: Our Open-Weights Model", dated **Jul 15, 2026**: https://thinkingmachines.ai/news/introducing-inkling/
- [G] Tinker pricing page: https://thinkingmachines.ai/tinker/pricing/
- [H] Tinker docs, models list: https://tinker-docs.thinkingmachines.ai/tinker/models/

Note for on-screen use: the HF card [B] and the blog [A] show the **same 5-model table** (Inkling 2 Mini, Gemma 4 31B, Muse Glimmer, Qwen3.8-27B, Nemotron 3.5 Super VL). The website model card [C] adds Dory 1.0 4B, SenseNova-Loop-9B and Beam 1.0, plus extra rows, so the "best"/"second-best" highlights differ between [A]/[B] and [C].

---

## 1. What the announcement and model card claim (headline lines and full benchmark table)

### Takeaway
The lab's pitch is "a fast, powerful model that's small enough to run on your laptop", with headline wins on agentic coding (DeepSWE v1.1 48.2%) and the Vals Index (46.5%). In the lab's own table it **ties** Qwen3.8-27B on the Artificial Analysis Index (both 20.1).

### Cited Findings
Headline wording (verbatim):
- "Today we are releasing Inkling 2 Mini, a fast, powerful model that's small enough to run on your laptop." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- "Inkling 2 Mini leads every open-weights model with less than 100B total parameters on benchmarks such as DeepSWE v1.1 (48.2%) and Vals Index v2.2 (46.5%). It runs faster than similarly performing models as well." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- "Inkling 2 Mini's strengths mirror those of Inkling 2 Small: it does best on long-horizon agentic work and is the best among open-weights models of similar size on most tasks we measured." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- "Inkling 2 Mini scores ahead of every comparable model on agentic coding benchmarks such as DeepSWE v1.1 and SWE-bench Pro v2, and is behind only Qwen3.8-27B on others. On PMPP-Hard, a kernel-optimization benchmark, it approaches the score of the much larger Inkling 2 Small." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- "Inkling 2 Mini overcomes the knowledge gap by efficiently using search and tools. It leads open-weights models of similar size on BrowseComp, DeepSearchQA, and MCP Atlas. It is also strong on knowledge work benchmarks that incorporate search and tool use." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- Licence: "License: Apache 2.0"; "It is released with open weights to support research, fine-tuning and integration into third-party products by downstream developers." — [B](https://huggingface.co/thinkingmachines/Inkling-2-Mini)
- Table legend (verbatim): "Best reported score in each row (lowest where lower is better); equal displayed scores tie Second-best reported score in each row; none when first place is tied" — [A](https://thinkingmachines.ai/news/inkling-2-mini/), [B](https://huggingface.co/thinkingmachines/Inkling-2-Mini)

**Full table from blog [A] / HF card [B] — Inkling 2 Mini vs Qwen3.8-27B (other competitors in brackets: Gemma 4 31B / Muse Glimmer / Nemotron 3.5 Super VL).** Row labels copied verbatim including the harness text that appears in the row label. Source: [A](https://thinkingmachines.ai/news/inkling-2-mini/), [B](https://huggingface.co/thinkingmachines/Inkling-2-Mini).

| Row label (verbatim) | Inkling 2 Mini | Qwen3.8-27B | Others (Gemma 4 31B / Muse Glimmer / Nemotron 3.5 Super VL) |
|---|---|---|---|
| Params (B) activated / total | 5.4/26.4 | 27.0/27.0 | 30.7/30.7; 30.0/30.0; 12.0/124.5 |
| AA Index (v5.0) | 20.1 | 20.1 | 4.4; 6.3; 13.6 |
| Vals Index (v2.2) | 46.5% | – | –; –; 29.8% |
| FrontierCode v2.0 stirrup v0.2.1 | 15.1% | 14.9% | 0.0%; 1.5%; 6.1% |
| DeepSWE v1.1 mini-swe-agent v2.4.6 | 48.2% | 42.2% | 0.3%; 4.4%; 24.7% |
| Terminal Bench v4.0 mini-swe-agent v2.4.6 | 5.6% | 5.6% | 0.0%; 0.5%; 0.0% |
| Terminal Bench v2.1 Inkling 2 Mini in pi v0.83.0 | 71.6% | 73.0% | 43.4%; 51.7%; 60.7% |
| SWEBench Pro v2 (Hard) mini-swe-agent v2.4.6 | 77.9% | 73.8% | 14.2%; 44.3%; 44.1% |
| SWEBench Multilingual Inkling 2 Mini with bash only | 73.7% | 70.0% | 43.0%; 66.9%; 67.7% |
| SWEBench Verified bash only | 79.2% | 77.8% | 46.1%; 76.0%; 71.1% |
| Vibe Code Bench v1.1 openhands (vals) | 77.9% | 64.9% | –; –; 3.5% |
| PMPP-Hard (AUC, 0–10h) pi v0.83.0 | 455.82 | 262.50 | –; –; 253.59 |
| BrowseComp Inkling 2 Mini with compaction | 79.0% | 61.6% | 37.0%; 63.9%; 78.9% |
| DeepSearchQA Inkling 2 Mini with compaction | 85.3% | 79.7% | 61.7%; 74.6%; 77.7% |
| MCP Atlas Public | 82.7% | 77.3% | 54.2%; 75.5%; 67.7% |
| AA-Briefcase v1.1 | 1263 | 1391 | 369; 478; 999 |
| GDPVal-AA v2.1 | 1319 | 1427 | 627; 792; 1162 |
| JobBench | 49.6% | 33.4% | 8.2%; 16.1%; 36.5% |
| AutomationBench-AA v1.0.6 | 41.8% | 48.2% | 4.9%; 6.8%; 14.8% |
| EnterpriseOps-Gym | 42.0% | 44.2% | 28.4%; 34.7%; 28.1% |
| Vals Finance Index | 50.1% | – | –; –; 41.0% |
| AA-AnalystAgent | 46.3% | – | –; 20.0%; – |
| Diligence Bench Best harness | 48.6% | 46.4% | 26.3%; 40.9%; 45.0% |
| GDP.pdf | 16.8% | 16.4% | 6.0%; 11.8%; 8.0% |
| PerceptionBench | 57.5% | 52.4% | 40.7%; 42.8%; 36.8% |
| MMMU Pro Standard 10 | 74.9% | 76.3% | 73.4%; 74.3%; 72.3% |
| OmniDocBench v1.6 | 92.8% | 91.5% | 82.5%; 90.4%; 77.9% |
| ScreenSpot Pro original / with Python | 76.5/87.7% | 57.6/78.9% | 5.9/15.9%; 75.4%/–; 43.5%/– |
| Chartography original / with Python | 22.1/72.5% | 12.2/52.1% | 12.0%/–; 17.4/25.1%; 9.7/29.3% |
| ZeroBench (main) original / with Python | 17.0/34.0% | 12.0/29.0% | 9.0/12.0%; 9.0/17.0%; 11.0/12.0% |
| MuirBench | 77.5% | 65.9% | 72.3%; 77.6%; 72.7% |
| BVB | 68.4% | 70.7% | 47.0%; 50.5%; 52.1% |
| HLE-Diamond | 15.2% | 15.3% | 7.2%; 9.1%; 8.8% |
| CritPt v2 Full / Hard | 31.4/17.0% | 10.6/4.0% | 11.7/4.0%; 24.3/7.0%; 36.9/13.5% |
| Apex 2025 | 34.4% | 18.8% | 5.2%; 4.2%; 22.9% |
| ARC-AGI v1 / v2 | 84.5/49.3% | 87.5/42.4% | –; –; 22.7/1.5% |
| LongBench v2 | 66.9% | 52.3% | 52.9%; 33.1%; 62.1% |
| GraphWalks BFS 256K | 69.7% | 50.4% | –; –; 63.3% |
| MRCR v2 8-needle 256K–512K | 46.4% | 38.0% | –; –; 5.7% |
| AA-Omniscience v1.1 score | -8.6 | -6.4 | -48.5; -32.2; -2.9 |
| AA-Omniscience v1.1 non-hallucination rate | 63.4% | 71.4% | 14.5%; 16.4%; 69.5% |
| ComplexConstraints v1.1 openhands v1.45.0 | 33.4% | 30.1% | 31.6%; 35.6%; 30.1% |
| FORTRESS (adversarial) Public | 89.5% | 78.8% | 67.8%; 90.3%; 79.6% |
| FORTRESS (benign) Public | 96.4% | 97.8% | 97.6%; 89.1%; 92.7% |
| StrongREJECT (none) | 97.8% | 99.0% | 98.1%; 99.0%; 99.4% |
| Misbehavior (Internal) ↓ | 9.8% | 57.7% | 27.6%; 46.4%; 52.8% |
| Covert misbehavior (Internal) ↓ | 8.3% | 33.2% | 24.3%; 45.6%; 43.4% |
| Destructive actions (Internal) ↓ | 10.2% | 35.2% | 75.8%; 68.8%; 65.6% |

**Extra rows only on the website model card [C]** (Mini vs Qwen3.8-27B; [C] also adds Dory 1.0 4B, SenseNova-Loop-9B and Beam 1.0 (23.0/501.0B) columns, and a "# Passes" row: Inkling 2 Mini 3, Qwen3.8-27B 1). Source: [C](https://thinkingmachines.ai/model-card/inkling-2-mini/).

| Row label (verbatim) | Inkling 2 Mini | Qwen3.8-27B |
|---|---|---|
| SWEBench Multimodal v2 mini-swe-agent (vals) | 37.9% | 37.5% |
| Code Migration v1.1 pi (vals) | 23.2% | – |
| Terminal Bench Science v0.1 mini-swe-agent v2.4.6 | 1.4% | 0.5% |
| Finance Agent v2.1 | 56.5% | – |
| Excel Modeling Benchmark v1.1 | 66.0% | – |
| Tax Agent Bench | 14.1% | 30.9% |
| BabyVision original / with Python | 53.4/88.8% | 65.7/85.6% |
| Charxiv RQ original / with Python | 80.6/88.3% | 83.7/90.2% |
| GroundingME | 55.5% | 44.7% |
| SAGE v1.1 | 85.9% | – |
| MathVision | 89.0% | 90.0% |
| Code2Video-AA | 870 | 949 |
| HLE (text only) | 30.7% | 33.9% |
| GPQA Diamond | 86.6% | 90.5% |
| MysteryMechanism | 23.0% | – |
| ProofBench v1.1 | 18.0% | 16.0% |
| AA-LCR v1.1 | 80.0% | 82.0% |
| HoneyBench v0.2 ↓ | 56.7% | – |

- On [C], with Beam 1.0 added, several Mini "best" highlights become "second-best", e.g. MCP Atlas Public: Beam 1.0 83.2% vs Mini 82.7%; SWEBench Verified: Beam 1.0 80.1% vs Mini 79.2%; Terminal Bench v2.1: Beam 1.0 80.1%. — [C](https://thinkingmachines.ai/model-card/inkling-2-mini/)
- The HF page shows Hugging Face "Evaluation results" badges such as "Ranked #1 in the < 32B size range" (DeepSWE v1.1), "Ranked #2 in the < 32B size range" (pi v0.83.0 harness, i.e. Terminal Bench 2.1) and "Ranked #1 in the < 128B size range" (SWE-Bench Pro v2 (Hard)); scores there carry an asterisk (e.g. "48.2 *"). — [B](https://huggingface.co/thinkingmachines/Inkling-2-Mini)

### Inferences
- The "AA Index (v5.0)" tie at 20.1 is the lab reporting a third-party index number; the narrator should confirm it on Artificial Analysis directly (independent check needed).
- The website card [C] is the richer, less-publicised source and contains most of the rows where Qwen3.8-27B wins (GPQA Diamond, HLE text-only, Tax Agent Bench, AA-LCR, etc.). For a fair video, [C] should be cited, not just [A]/[B].

### Gaps
- I did not determine what the asterisk on HF evaluation-result badges means (it may mark self-reported/unverified results on HF; not confirmed).
- Benchmark versions like "Terminal Bench v4.0", "SWEBench Pro v2" and "AA Index (v5.0)" are recent; scores on living leaderboards are likely to go stale.

---

## 2. Where Inkling 2 Mini beats and loses to Qwen3.8-27B (by the lab's own figures)

### Takeaway
By the lab's numbers, Mini clearly beats Qwen3.8-27B on agentic coding, search/tool use, long-context and several vision rows, but **loses** on knowledge-work suites (GDPVal-AA, AA-Briefcase, AutomationBench, EnterpriseOps), factuality (AA-Omniscience), GPQA Diamond, HLE, Terminal Bench 2.1, and some vision rows. The two **tie** on the AA Index (20.1).

### Cited Findings
All numbers: [A](https://thinkingmachines.ai/news/inkling-2-mini/), [B](https://huggingface.co/thinkingmachines/Inkling-2-Mini), extra rows marked [C](https://thinkingmachines.ai/model-card/inkling-2-mini/).

**Qwen3.8-27B ahead of Inkling 2 Mini (lab's figures):**
- Terminal Bench v2.1: 73.0% vs 71.6%
- AA-Briefcase v1.1: 1391 vs 1263
- GDPVal-AA v2.1: 1427 vs 1319
- AutomationBench-AA v1.0.6: 48.2% vs 41.8%
- EnterpriseOps-Gym: 44.2% vs 42.0%
- MMMU Pro Standard 10: 76.3% vs 74.9%
- BVB: 70.7% vs 68.4%
- HLE-Diamond: 15.3% vs 15.2% (0.1 pt)
- ARC-AGI v1: 87.5% vs 84.5%
- AA-Omniscience v1.1 score: -6.4 vs -8.6; non-hallucination rate: 71.4% vs 63.4%
- FORTRESS (benign): 97.8% vs 96.4%; StrongREJECT: 99.0% vs 97.8%
- [C] only: GPQA Diamond 90.5% vs 86.6%; HLE (text only) 33.9% vs 30.7%; Tax Agent Bench 30.9% vs 14.1%; AA-LCR v1.1 82.0% vs 80.0%; MathVision 90.0% vs 89.0%; Charxiv RQ 83.7/90.2% vs 80.6/88.3%; BabyVision original 65.7% vs 53.4% (Mini wins "with Python" 88.8% vs 85.6%); Code2Video-AA 949 vs 870.
- Text claim: "it scores 50.0% on MultiChallenge and 33.4% on ComplexConstraints v1.1, behind Qwen3.8-27B on both." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)

**Ties:** AA Index (v5.0) 20.1 vs 20.1; Terminal Bench v4.0 5.6% vs 5.6%.

**Inkling 2 Mini ahead of Qwen3.8-27B (lab's figures):** FrontierCode 15.1% vs 14.9%; DeepSWE v1.1 48.2% vs 42.2%; SWEBench Pro v2 (Hard) 77.9% vs 73.8%; SWEBench Multilingual 73.7% vs 70.0%; SWEBench Verified 79.2% vs 77.8%; Vibe Code Bench 77.9% vs 64.9%; PMPP-Hard 455.82 vs 262.50; BrowseComp 79.0% vs 61.6%; DeepSearchQA 85.3% vs 79.7%; MCP Atlas 82.7% vs 77.3%; JobBench 49.6% vs 33.4%; Diligence Bench 48.6% vs 46.4%; GDP.pdf 16.8% vs 16.4%; PerceptionBench 57.5% vs 52.4%; OmniDocBench 92.8% vs 91.5%; ScreenSpot Pro 76.5/87.7% vs 57.6/78.9%; Chartography 22.1/72.5% vs 12.2/52.1%; ZeroBench 17.0/34.0% vs 12.0/29.0%; MuirBench 77.5% vs 65.9%; CritPt v2 31.4/17.0% vs 10.6/4.0%; Apex 2025 34.4% vs 18.8%; ARC-AGI v2 49.3% vs 42.4%; LongBench v2 66.9% vs 52.3%; GraphWalks BFS 256K 69.7% vs 50.4%; MRCR v2 46.4% vs 38.0%; FORTRESS (adversarial) 89.5% vs 78.8%; Misbehavior ↓ 9.8% vs 57.7%; Covert misbehavior ↓ 8.3% vs 33.2%; Destructive actions ↓ 10.2% vs 35.2%. [C] only: SWEBench Multimodal v2 37.9% vs 37.5%; Terminal Bench Science 1.4% vs 0.5%; GroundingME 55.5% vs 44.7%; ProofBench 18.0% vs 16.0%.

**Rows where Qwen3.8-27B has no score ("–"):** Vals Index (v2.2), Vals Finance Index, AA-AnalystAgent; on [C] also Code Migration, Finance Agent, Excel Modeling, SAGE, MysteryMechanism. So the headline "Vals Index v2.2 (46.5%)" lead has **no Qwen3.8-27B comparison** in the lab's table. — [A](https://thinkingmachines.ai/news/inkling-2-mini/), [C](https://thinkingmachines.ai/model-card/inkling-2-mini/)

**Internal contradiction (important to flag on screen):**
- The Limitations text says Mini is "behind Qwen3.8-27B" on ComplexConstraints v1.1 at 33.4%, but the lab's own table lists **ComplexConstraints v1.1: Inkling 2 Mini 33.4%, Qwen3.8-27B 30.1%**, i.e. Mini ahead. — [A](https://thinkingmachines.ai/news/inkling-2-mini/) (text vs table on the same page); same table numbers on [B](https://huggingface.co/thinkingmachines/Inkling-2-Mini) and [C](https://thinkingmachines.ai/model-card/inkling-2-mini/)
- MultiChallenge (50.0%) appears only in the text; there is **no MultiChallenge row** in any table and no Qwen3.8-27B MultiChallenge number is given. — [A](https://thinkingmachines.ai/news/inkling-2-mini/)

**Possible conflict with "ahead of every comparable model ... SWE-bench Pro v2":**
- The blog's coding chart data (in the page's accessible chart labels) lists "Ripple-65B (Preview): 79.1%" on "SWE-bench Pro v2 Hard (51 tasks)", above "Inkling 2 Mini: 77.9%". On DeepSWE v1.1 the same chart lists Ripple-65B (Preview) at 44.3%, below Mini's 48.2%. — [A](https://thinkingmachines.ai/news/inkling-2-mini/)

### Inferences
- "Behind only Qwen3.8-27B on others" most plausibly refers to rows like Terminal Bench v2.1, AA-Briefcase, GDPVal-AA, AutomationBench-AA, EnterpriseOps-Gym, HLE-Diamond, MMMU Pro, BVB and AA-Omniscience, where Qwen3.8-27B is first and Mini second in the 5-model table. The post does not list them; this mapping is my reading of the table.
- For the narrator's use case (long-form writing/planning returning JSON), the rows where Qwen leads (knowledge-work suites like GDPVal-AA and AA-Briefcase, factuality, multi-turn chat, GPQA/HLE) are arguably more relevant than the coding rows where Mini leads.
- Ripple-65B (Preview) may be excluded from "comparable" because it is a preview and/or not open weights; the post doesn't say.
- SWE-bench Pro v2 Hard has only 51 tasks, so one task is about 2 percentage points; the 77.9% vs 73.8% gap is roughly 2 tasks. 77.9% of 51 is not a whole number (39.7 tasks), which suggests Mini's score is averaged over several runs. Inference only; not stated.

### Gaps
- No Qwen3.8-27B score for Vals Index, MultiChallenge, IFBench, or any writing benchmark in Thinking Machines material.
- The ComplexConstraints contradiction is unexplained (either the text or the table is wrong, or a different setting was meant).

---

## 3. Footnotes and methodology: harnesses, effort, who ran competitor scores, runs

### Takeaway
The Inkling 2 Mini post and both model cards contain **no methodology statement** about effort level, temperature, number of runs, or whether competitor scores were run by the lab or taken from other reports. The only explicit caveat is a chart caption: "Evaluation setups vary by model." Harness names appear only inside row labels, and several are worded as applying to Inkling 2 Mini specifically. The sibling posts (Inkling 2 Small, original Inkling) **do** state their settings, which makes the absence on Mini notable.

### Cited Findings
- Chart caption (verbatim): "Reported coding scores for models under 100B total parameters. The green line is the frontier with Inkling 2 Mini, the dashed line the frontier without it, and the shading the ground it adds. Decoding speed is a theoretical ceiling at 614 GB/s with BF16 weights and batch size one, including repeated reads across loops. Evaluation setups vary by model." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- Harness information exists only in row labels, e.g. "DeepSWE v1.1 mini-swe-agent v2.4.6", "SWEBench Pro v2 (Hard) mini-swe-agent v2.4.6", "Terminal Bench v2.1 Inkling 2 Mini in pi v0.83.0", "SWEBench Multilingual Inkling 2 Mini with bash only", "SWEBench Verified bash only", "Vibe Code Bench v1.1 openhands (vals)", "PMPP-Hard (AUC, 0–10h) pi v0.83.0", "FrontierCode v2.0 stirrup v0.2.1", "BrowseComp Inkling 2 Mini with compaction", "DeepSearchQA Inkling 2 Mini with compaction", "Diligence Bench Best harness", "ComplexConstraints v1.1 openhands v1.45.0". — [A](https://thinkingmachines.ai/news/inkling-2-mini/), [B](https://huggingface.co/thinkingmachines/Inkling-2-Mini)
- I searched the raw HTML of [A] and [C] and the raw README of [B] for footnote markers, superscripts, daggers, tooltips and words like "effort", "temperature", "self-reported", "taken from"; the only effort mentions relate to the monitorability experiments and the Stanford energy test (below), not the benchmark table. — [A](https://thinkingmachines.ai/news/inkling-2-mini/), [B](https://huggingface.co/thinkingmachines/Inkling-2-Mini), [C](https://thinkingmachines.ai/model-card/inkling-2-mini/)
- Effort settings that **are** stated on the Mini page:
  - Stanford energy test: "Inkling 2 Mini ran on NVIDIA DGX Spark (128GB) at MXFP8 precision with low reasoning effort in this experiment. The other models ran at NVFP4 (Qwen3.6-35B-A3B and Gemma-4-26B-A4B) and INT4 (Qwen3.5-27B)." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
  - CoT controllability: "we pool responses from five reasoning efforts (0.1, 0.2, 0.7, 0.9 and 0.99)" — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
  - Calendar example: "Excerpts of the model's reasoning at 1 and 5 passes for a simple question run at effort 0.1." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- Sibling comparison, Inkling 2 Small: "All evals run at effort 0.99 (xhigh) and temperature 1.0. All evals run with a 1M-token maximum trajectory limit, increased from the 256K-token limit used for Inkling Small." — [E](https://thinkingmachines.ai/news/inkling-2-small/)
- Inkling 2 Small PMPP-Hard note: "Each model uses its maximum available reasoning setting, the PI harness and a shared compaction policy. We include fixes for task and grading issues identified during evaluation. Each submitted solution receives two independent LLM audits, with a third review resolving disagreements." — [E](https://thinkingmachines.ai/news/inkling-2-small/)
- Original Inkling (Jul 15): "All evals are run at effort 0.99 and temperature 1.0. All coding evals run with 256K max-token trajectory limit." and "To improve consistency, we rely on externally reported evaluations for both internal and external models when applicable. Specifically, we use the score reported by Artificial Analysis for the following evals: Humanity's Last Exam, GPQA Diamond, GDPVal, Tau 3 Banking, AA Omniscience, MMMU Pro." — [F](https://thinkingmachines.ai/news/introducing-inkling/)
- Original Inkling footnote: "*SWEBench Verified: Inkling numbers are reported using a bash-only harness. We use self-reported numbers for external models. *Terminal Bench 2.1: Inkling numbers are reported using an internal coding harness. A small number of solutions were found to be contaminated from web search and were assigned a score of 0. We use self-reported numbers for external models where available. Otherwise, we report performance using our internal harness." — [F](https://thinkingmachines.ai/news/introducing-inkling/)
- Possible internal inconsistency: the DeepSWE v1.1 effort-sweep chart data on [A] lists Inkling 2 Mini's points as "28.8% at 32,902 tokens, 29.3% at 35,303 tokens, 44.2% at 87,893 tokens, 42.2% at 110,250 tokens, 44.6% at 110,660 tokens", so peak 44.6%, below the 48.2% headline in the table. — [A](https://thinkingmachines.ai/news/inkling-2-mini/)

### Inferences
- Row labels such as "Terminal Bench v2.1 **Inkling 2 Mini in** pi v0.83.0" and "BrowseComp **Inkling 2 Mini with** compaction" read as if the harness/compaction applies to Mini's run, and competitors may have been scored differently. Combined with "Evaluation setups vary by model" and the word "Reported" in the caption, it is likely (not confirmed) that at least some Qwen3.8-27B numbers were self-reported by Alibaba or taken from third parties such as Artificial Analysis or Vals, as the lab explicitly did for the July Inkling launch.
- If Mini's table followed the Inkling 2 Small convention, it would be at effort 0.99 (xhigh), temperature 1.0. This is an assumption; the Mini page does not say it.
- The 44.6% vs 48.2% DeepSWE gap may reflect a different setting, subset or number of runs in the sweep chart; not explained.
- Whether Qwen3.8-27B was scored in thinking mode (the narrator's configuration) is not stated anywhere.

### Gaps
- Not stated by the lab for Mini: effort level of table runs; temperature; pass@1 vs other; number of runs/seeds; who ran each Qwen3.8-27B score; Qwen precision (BF16 vs FP8) or thinking mode; harness used for competitors on rows labelled with Mini-specific harness text.
- These are the questions to put to Thinking Machines or to verify against Alibaba's Qwen3.8 report and Artificial Analysis/Vals leaderboards (independent research needed).

---

## 4. The looped transformer: explanation, 5.4B activations, fewer tokens, speed, variable-loop model, monitorability

### Takeaway
The middle 12 of 24 layers run three times per token (48 layer applications), giving 3.4B active parameters but 5.4B "weight activations" per token. The lab claims looping improves reasoning per token and that more loops shorten the chain of thought without making it less readable. The "fewer tokens" evidence is a comparison of the research model at different loop counts, **not a token comparison against Qwen3.8-27B**. The speed claim against Qwen is a **theoretical** calculation, not a measurement.

### Cited Findings
Plain-language explanation (verbatim):
- "Inkling 2 Mini is a looped transformer, running the middle layers of the model three times for every token. This allows the model to apply more reasoning and reach the right answer with fewer tokens, especially on tasks such as agentic coding that depend on reasoning quality." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- "Inkling 2 Mini is a Mixture-of-Experts model with 26.4B total parameters, 3.4B active, and 5.4B weight activations per token to account for looping. Looping allows the model to reason longer without writing its reasoning down, which matters for monitoring: our ability to oversee and understand what the model does by reading its chain of thought (CoT)." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- "Inkling 2 Mini has 24 layers, divided into four blocks of six layers each. The two middle blocks run three times, while the first and last blocks each run once." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- "...motivated by the intuition that the middle layers of the model carry more abstract reasoning, while the first and last few layers devote more space to translating between embeddings and internal representations." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- "In our experiments, looping the middle 12 layers resulted in larger gains in accuracy than looping the last 12 on 27 out of 28 different evaluations." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- "Blocks 2 and 3 share weights across three passes, giving 48 layer applications per token from 24 stored layers." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- "Note: each extra pass through the looped layers adds about 1.0B effective active parameters. Since the model runs with three passes, there are 5.4B effective active parameters per token." — [B](https://huggingface.co/thinkingmachines/Inkling-2-Mini)
- Architecture: "A 24-layer decoder-only transformer with sparse Mixture-of-Experts (MoE) feed-forward layers... In each layer, each token is routed to 8 of 128 experts. Attention is a hybrid of local and global layers." — [B](https://huggingface.co/thinkingmachines/Inkling-2-Mini)
- Attention residuals: "Instead of adding every layer's output into one running sum, each layer reads the outputs of the earlier blocks and learns its own mix of them. This allows richer information to pass between loops." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- Training efficiency: "The non-looping model cost 7.5% less compute to train, but the looping version was over 50% more compute-efficient: the non-looping scaling law predicts it would take over 1.5× the looping version's training compute to match its held-out loss." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- Compute caveat: "Because the middle layers run three times, compute per token is higher than the active-parameter count alone suggests." — [B](https://huggingface.co/thinkingmachines/Inkling-2-Mini)

Fewer tokens (lab's evidence):
- "We ran the variable-looped model at 1 to 5 passes, and found that as looping increases, the model generally achieves higher accuracy at each reasoning token budget, with diminishing returns after 3 passes." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- "Reasoning at 5 passes was less than half as long as at 1 pass (1,661 vs. 3,703 tokens on average), but no less legible: sentence length and the fraction of words in an English dictionary were unchanged. On initial analysis, the difference is that the model is more direct and backtracks less on the way to the answer." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- Table on [A]: mean reasoning tokens 3703 (1 pass) / 1731 (3 passes) / 1661 (5 passes); uncertainty indicators ("wait", "actually", "hmm") 9.7 / 3.9 / 3.6. — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- Calendar example: "582 reasoning tokens" at 1 pass vs "240 reasoning tokens" at 5 passes, same answer (Friday). — [A](https://thinkingmachines.ai/news/inkling-2-mini/)

Speed (lab's theoretical figures, from the page's chart data):
- DeepSWE chart: "Qwen3.8-27B: 42.2% at 11.4 theoretical tokens/s... Inkling 2 Mini: 48.2% at 54.4 theoretical tokens/s." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- Basis (verbatim): "Decoding speed is a theoretical ceiling at 614 GB/s with BF16 weights and batch size one, including repeated reads across loops." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- "Local performance. Support for looped models in local runtimes is new, and speed varies by runtime and hardware." — [B](https://huggingface.co/thinkingmachines/Inkling-2-Mini)

Variable-loop research model:
- "we also trained a variable-looped model, TML-d24-varloop-research, because Inkling 2 Mini only supports a fixed number of looping passes... trained with between one and five looping passes." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- "This corresponds to 3.4B active parameters at 1 pass, 5.4B at 3 passes, and 7.4B at 5 passes." and "trained with 1 to 5 passes through the looped layers, sampled in a 1:2:6:2:1 ratio, and it was then post-trained with 3 passes." Licence: "Apache 2.0". — [D](https://thinkingmachines.ai/model-card/tml-d24-varloop-research/)
- "The variable-loop model's no-CoT time horizon improved from 16 seconds at one pass to 37 seconds with three, and its performance on a benchmark of serial reasoning kept improving out to ten loops—twice as many as it was trained with." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- Chart data: Inkling 2 Mini (3 passes) no-CoT horizon 41 seconds (95% CI 3 to 59.4 s); varloop 16 s (1 pass), 26 s (2), 37 s (3), 42 s (5), 40 s (10). — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- "Gains are largest on long-context tasks (GraphWalks BFS, MRCR v2), followed by math, abstract, and visual reasoning... Closed-book factual QA is nearly invariant to loop passes (AA-Omniscience, SimpleQA Verified, SimpleVQA, WorldVQA)." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)

Monitorability:
- "Overall, we find that looping increases what these models can do without a verbalized chain of thought, but at this scale we do not see a meaningful reduction in the monitorability of their reasoning." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- "The model's chain of thought grew shorter with more loops but stayed legible throughout. The model didn't trend higher on tests of agentic sabotage as loops were added." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- "Among CoTs of 750–1,250 tokens, Inkling 2 Mini and TML-d24-varloop-research (at 3 passes) follow the instruction at most 0.1% of the time, compared with 0.3% for Inkling 2 Small, 0.4% for Inkling-Small, and 1.3% for Qwen3.8-27B." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- LinuxArena (weaker monitor Qwen3.6-35B-A3B), stealth rate with tool calls only / also sees thinking: Qwen3.8-27B 20.5% / 0.4%; Inkling 2 Small 3.2% / 0.5%; Inkling 2 Mini (helpful-only) 3.9% / 1.3%; varloop 1–5 passes 1.0–5.0% / 0.0–0.6%. "we see no clear trend with the number of looped passes." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- Caveat (verbatim): "These experiments therefore do not tell us what a model trained with RL at a higher pass count would learn, and such a model might compress its reasoning more aggressively." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)

### Inferences
- 54.4 vs 11.4 theoretical tokens/s is about 4.8× in Mini's favour, but it is a memory-bandwidth calculation assuming **BF16 weights** at batch size one. The narrator runs Qwen in FP8 on a rented GPU server, likely with batching, so real throughput differences will differ. Independent benchmarking is needed.
- The 614 GB/s figure is not attributed to a named device on the page.
- The lab offers no direct "Mini uses X% fewer tokens than Qwen3.8-27B" figure; "fewer tokens" is shown within its own model family across loop counts.

### Gaps
- No measured tokens/sec on any real hardware (MacBook, DGX Spark or datacentre GPU) for Mini vs Qwen3.8-27B in Thinking Machines material.
- Goodfire's interpretability write-up is linked from [A] (https://www.goodfire.com/research/interpreting-inkling-2-mini/) but was not reviewed here; it is a partner with early access, not fully independent.

---

## 5. Hardware, formats, frameworks, context, modalities, speculative decoding

### Takeaway
About 20GB checkpoint, trained and shipped natively in NVFP4 (20 layers) plus MXFP8 (last 4 layers), so "no conversion loss". Officially supported on one DGX Spark or Apple silicon with 32GB+; 1M-token context; text and image in, text out; no audio. I found **no mention of a draft head, MTP or speculative decoding** for Mini.

### Cited Findings
- "Most of Inkling 2 Mini's weights were trained and are deployed natively in NVFP4, with the last four layers in MXFP8. The total memory footprint of Inkling 2 Mini is ~20GB, allowing it to run on local devices such as consumer laptops and desktop AI computers." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- "Inkling 2 Mini's weights are deployed in the same numeric precision they were trained on—20 layers in NVFP4 and 4 in MXFP8—so there is no conversion loss from quantization." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- "We use 4-bit NVFP4 precision in the expert layers on all forward passes from pretraining through RL, bolstered by a dedicated kernel and hardware-accelerated on NVIDIA's GB300 platform." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- "The model is distributed as a single checkpoint of about 20GB, in mixed NVFP4 and MXFP8 precisions." Supported: "1x NVIDIA DGX Spark"; "Apple silicon devices with 32GB or more memory (MacBooks, Mac minis and Studios)"; "Other GPUs and platforms are possible, with 32GB or more of VRAM recommended". — [B](https://huggingface.co/thinkingmachines/Inkling-2-Mini)
- "At launch we support Inkling 2 Mini running on any Mac system (MacBook, Mac Mini) with at least 32GB RAM via Ollama. With native NVFP4 training and inference precision, Inkling 2 Mini runs efficiently on NVIDIA's DGX Spark desktop AI computer. Quantized GGUF versions are available via Unsloth and llama.cpp for local inference." — [A](https://thinkingmachines.ai/news/inkling-2-mini/) (section "Try Inkling 2 Mini today", present in page HTML)
- Frameworks: "Open source inference is available on SGLang, vLLM, Ollama, Unsloth, NVIDIA Dynamo, TokenSpeed, and Llama App, with RL fine-tuning support on SkyRL, Miles, and NVIDIA AutoModel." — [A](https://thinkingmachines.ai/news/inkling-2-mini/). HF card list: Hugging Face, SGLang, vLLM, TokenSpeed, NVIDIA Dynamo, Unsloth (incl. GGUF), llama.cpp (GGUF), Llama App; Apple silicon: Ollama and Exo Labs; post-training: Miles, SkyRL. — [B](https://huggingface.co/thinkingmachines/Inkling-2-Mini)
- Website card adds: "The model is also available via API access through third party inference providers." — [C](https://thinkingmachines.ai/model-card/inkling-2-mini/)
- Context: "Inkling 2 Mini supports a context window of up to 1M tokens." — [B](https://huggingface.co/thinkingmachines/Inkling-2-Mini)
- Modalities: "accepts text and image inputs and generates text outputs"; "Image: Any pixel-based image input. For optimal performance, each image dimension should be between 40px to 4096px."; Output modalities: "Text". — [B](https://huggingface.co/thinkingmachines/Inkling-2-Mini), [C](https://thinkingmachines.ai/model-card/inkling-2-mini/)
- Stanford energy result (third-party researchers, reported by the lab): "Inkling 2 Mini scored 0.703 running on NVIDIA DGX Spark, significantly higher than other models: 0.430 for Qwen3.6-35B-A3B, 0.159 for Gemma-4-26B-A4B and 0.036 for Qwen3.5-27B." — [A](https://thinkingmachines.ai/news/inkling-2-mini/). Note: Qwen3.8-27B was **not** in this comparison.

### Inferences
- NVFP4 hardware acceleration is an NVIDIA Blackwell-class feature; on the narrator's rented GPU, whether native NVFP4 runs fast depends on the GPU generation. Not stated by the lab; needs checking for his specific server.
- Speculative decoding: the only "draft" mention is in the Inkling 2 Small post's RL infrastructure ("During sampling, prefill, draft, and verify run fully on CUDA graphs") — [E](https://thinkingmachines.ai/news/inkling-2-small/). Nothing ties a draft head to Mini.

### Gaps
- No draft head / MTP / speculative decoding information for Mini in any official source I found.
- No statement of how quality holds up at long context in local runtimes, or KV-cache memory needs at 1M tokens on a 32GB Mac.

---

## 6. The flight simulator and Thinkyville demos

### Takeaway
Ran offline on a "MacBook Pro (M5 Pro, 48GB)" in airplane mode and "built a playable flight simulator in a few minutes"; the video is mostly sped up 15×. A second demo runs 20 village agents on one offline MacBook.

### Cited Findings
- "Our researchers took Inkling 2 Mini on a flight, where it ran offline on a MacBook Pro and built a playable flight simulator in a few minutes." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- Demo label: "MacBook Pro (M5 Pro, 48GB) Airplane mode"; video title: "PlaneBench flight simulator demo, screen with phone video inset". — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- Caption: "Building and flying a flight simulator with Inkling 2 Mini. The timer shows real time; most of the recording plays at 15× speed." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- The page embeds the video file at https://thinkingmachines.ai/_astro/planebench-demo3.FdsHOEHH.mp4 and a playable artifact ("To try the flight simulator, open this page on desktop."). — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- Thinkyville: "All 20 residents of the energy-conscious village of Thinkyville are managed by Inkling 2 Mini running on a single offline MacBook." and "Thinkyville is a tiny pixel town built by Inkling 2 Mini, where the same model powers all 20 villagers on one offline MacBook. They plan their day, gossip, host bake-offs, and answer the notes you leave on their doors." Label: "MacBook Pro (M5 Pro, 48GB) Airplane mode". — [A](https://thinkingmachines.ai/news/inkling-2-mini/)

### Inferences
- "A few minutes" is vague; the real elapsed time is only visible on the timer in the video.

### Gaps
- Exact build duration, prompt, number of turns, runtime used (Ollama?) and effort setting for the demo are not stated in text. I did not watch the video to read the timer.

---

## 7. Limitations the lab admits

### Takeaway
The lab is fairly candid: weaker on factual knowledge, multi-turn chat and many-constraint instructions; it can get stuck in reasoning loops; it is less reliable at following project conventions in agentic work and may take destructive actions; minimum effort doesn't fully disable reasoning; non-English output can degrade.

### Cited Findings
- "While looping improves the model's reasoning, it doesn't enable its weights to store more facts—knowledge is mostly a function of total parameter count. Inkling 2 Mini's score on AA-Omniscience, a measure of factuality, is in line with other models of the same size." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- "Inkling 2 Mini is not the strongest small model for multi-turn chat or for instructions with many constraints: it scores 50.0% on MultiChallenge and 33.4% on ComplexConstraints v1.1, behind Qwen3.8-27B on both. It also trails larger models on reasoning-intensive benchmarks such as CritPt v2 and HLE-Diamond." — [A](https://thinkingmachines.ai/news/inkling-2-mini/) (see contradiction flagged in section 2)
- "Knowledge and factual accuracy. It is less capable than Inkling 2 Small across most of our evaluations, with the largest gaps on factual recall and knowledge-heavy questions. It is more likely than larger models to state incorrect information with confidence." — [B](https://huggingface.co/thinkingmachines/Inkling-2-Mini)
- "Repetitive reasoning. In internal testing the model sometimes became stuck in long reasoning loops, or repeatedly re-checked its own work without making progress, particularly when debugging code. We recommend setting limits on output tokens and agent turns." — [B](https://huggingface.co/thinkingmachines/Inkling-2-Mini)
- "Agentic reliability. When using tools, it is less reliable than larger models at following detailed instructions and project conventions. It may take destructive actions, such as deleting or overwriting files, without confirmation, and may not report the outcome of its work accurately." — [B](https://huggingface.co/thinkingmachines/Inkling-2-Mini)
- "Languages other than English. Output quality can be lower outside English. In testing in Chinese we observed clipped phrasing and mixed languages." — [B](https://huggingface.co/thinkingmachines/Inkling-2-Mini)
- "Sensitive topics. The model can respond with more caution than the situation calls for when a conversation touches on mental health." — [B](https://huggingface.co/thinkingmachines/Inkling-2-Mini)
- "Reasoning and compute. Setting reasoning effort to its minimum does not fully disable reasoning." — [B](https://huggingface.co/thinkingmachines/Inkling-2-Mini)
- General: "including hallucination (generating plausible but factually incorrect or unsupported content), occasional failures to follow instructions precisely, and degraded performance in long multi-turn conversations." — [B](https://huggingface.co/thinkingmachines/Inkling-2-Mini)
- Safety conclusion: "Across all areas, we concluded that Inkling 2 Mini does not give material uplift beyond what is already available from open-weights models." — [B](https://huggingface.co/thinkingmachines/Inkling-2-Mini)

### Inferences
- "Destructive actions" appears both as a limitation in the card ("may take destructive actions") and as a strength in the table (Destructive actions ↓ 10.2% vs Qwen3.8-27B 35.2%, internal eval). Both are the lab's claims; they are relative (better than peers, worse than larger models), not contradictory, but worth explaining carefully on screen.
- The Mini post has no explicit "chat presentation" caveat like Inkling 2 Small's (below); the multi-turn-chat limitation is the closest.

### Gaps
- No quantified rate for the "reasoning loops" failure.

---

## 8. Writing quality, instruction following, structured output/JSON, long context

### Takeaway
Thinking Machines makes **no claims about long-form writing quality or JSON/structured output** for Inkling 2 Mini. The nearest evidence: it trails Qwen3.8-27B on multi-turn chat (MultiChallenge) and on knowledge-work document suites (GDPVal-AA, AA-Briefcase), and leads on most long-context retrieval/reasoning benchmarks except AA-LCR.

### Cited Findings
- I searched [A], [B], [C], [D] for "JSON", "structured", "writing", "IFBench", "IFEval", "creative", "EQ-Bench", "MultiChallenge"; the only hit related to these topics is the MultiChallenge/ComplexConstraints limitation sentence. — [A](https://thinkingmachines.ai/news/inkling-2-mini/), [B](https://huggingface.co/thinkingmachines/Inkling-2-Mini), [C](https://thinkingmachines.ai/model-card/inkling-2-mini/)
- Instruction following: "it scores 50.0% on MultiChallenge and 33.4% on ComplexConstraints v1.1, behind Qwen3.8-27B on both." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- Intended uses mention "instruction-following" generically: "suitable for general-purpose conversational use, instruction-following, and other natural language and visual tasks." — [B](https://huggingface.co/thinkingmachines/Inkling-2-Mini)
- Knowledge-work/document rows (Mini vs Qwen3.8-27B): GDPVal-AA v2.1 1319 vs 1427; AA-Briefcase v1.1 1263 vs 1391; JobBench 49.6% vs 33.4%; GDP.pdf 16.8% vs 16.4%. — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- Long-context rows (Mini vs Qwen3.8-27B): LongBench v2 66.9% vs 52.3%; GraphWalks BFS 256K 69.7% vs 50.4%; MRCR v2 8-needle 256K–512K 46.4% vs 38.0%; AA-LCR v1.1 80.0% vs 82.0% ([C] only). — [A](https://thinkingmachines.ai/news/inkling-2-mini/), [C](https://thinkingmachines.ai/model-card/inkling-2-mini/)
- Lab's mechanism claim: "performances on long-context benchmarks improve with more passes, such as GraphWalks BFS and MRCR v2" — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- Original Inkling's training note on tool schemas (context only, not Mini): "we randomized the tool set and schema during training to reduce sensitivity to any particular one." — [F](https://thinkingmachines.ai/news/introducing-inkling/)

### Inferences
- For the narrator's long-form writing and planning jobs returning structured JSON, the lab's own evidence is mixed-to-unfavourable for Mini: Qwen3.8-27B leads on GDPVal-AA and AA-Briefcase (the closest to document/knowledge-work output) and on multi-turn chat, while Mini leads on long-context retrieval. JSON reliability would have to be tested independently.
- The "repetitive reasoning" limitation and the advice to cap output tokens are directly relevant to long-form generation jobs.

### Gaps
- No official writing-quality, JSON-schema adherence, or structured-output benchmark for Mini. Independent testing required.

---

## 9. Siblings for context: Inkling 2 Small, original Inkling, Tinker pricing, licence

### Takeaway
Inkling 2 Small (Nov 5, 594B/17B, AA Index "31") launched closed-weight on Tinker, then went open on Nov 12. Original Inkling (Jul 15) is 975B/41B with audio. On Tinker, Inkling 2 Mini costs $0.15 prefill / $0.50 sample / $0.75–$1.50 train per 1M tokens, and has a rate-limited free tier.

### Cited Findings
Inkling 2 Small:
- "Today we are introducing our second model generation with Inkling 2 Small. It is a Mixture-of-Experts model with 594B total parameters, 17B active, and supports image inputs and variable effort." — [E](https://thinkingmachines.ai/news/inkling-2-small/) (Nov 5, 2026)
- "Inkling 2 Small far surpasses our previous models' scores on the Artificial Analysis Intelligence Index with a score of 31..." — [E](https://thinkingmachines.ai/news/inkling-2-small/). The post's own table lists "AA Index (v5.0) | 30.6", so "31" is rounded.
- "Inkling 2 Small will initially be available through Tinker, with closed weights... We intend to make the full weights available under an Apache 2.0 license next week after the completion of external safety testing and red-teaming." — [E](https://thinkingmachines.ai/news/inkling-2-small/)
- Update banner: "Nov 12, 2026 update: Inkling 2 Small's weights are now available for download on HuggingFace." — [E](https://thinkingmachines.ai/news/inkling-2-small/)
- Limitations (verbatim): "While Inkling 2 Small improves on usability vs Inkling, it is not the most succinct communicator, and doesn't always choose the best tools for the job—especially in codebases with a large number of skills." / "Like previous Inkling models, Inkling 2 Small natively supports image input; however, this model does not support audio." / "Inkling 2 Small is also less optimized for the chat experience. We notice issues such as worse organization and presentation of content, overuses of slashes, and overreaction to mental health and other safety related queries." — [E](https://thinkingmachines.ai/news/inkling-2-small/)
- Mini's post-training followed Small: "Inkling 2 Mini underwent SFT with a similar data mix to Inkling 2 Small. This was followed by an RL that totaled 2.2T tokens over 2,000 steps." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- Mini's origin: "pruning two-thirds of the experts" (from 384 to 128) and then "the model trained on 1T tokens distilled from a larger internal Inkling model." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)

Original Inkling:
- "Our model, called Inkling, is a Mixture-of-Experts transformer with 975B total parameters, 41B active. It supports a context window of up to 1M tokens. It was pretrained on 45 trillion tokens of text, images, audio, and video." — [F](https://thinkingmachines.ai/news/introducing-inkling/) (Jul 15, 2026)
- Admitted: "Inkling is not the strongest overall model available today, open or closed." — [F](https://thinkingmachines.ai/news/introducing-inkling/)
- Inkling-Small: listed as 276B total / 12B active on Tinker. — [H](https://tinker-docs.thinkingmachines.ai/tinker/models/)

Tinker availability and pricing (USD per 1M tokens):
- "Inkling 2 Mini is available for inference and fine-tuning on Tinker, and for chat on the Tinker Playground." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- Pricing table (header reads "Training & sampling prices in US dollars per million tokens, as of October 19, 2026"): "Inkling 2 Mini (free) 64K: $0.00 / $0.00 / $0.00 / $0.00"; "Inkling 2 Mini 64K: Prefill $0.15, Cached prefill $0.015, Sample $0.50, Train $0.75"; "Inkling 2 Mini 256K: $0.15 / $0.015 / $0.50 / $1.50"; Inkling 2 Small 64K: $0.30 / $0.03 / $1.00 / $1.50; Inkling 64K: $1.87 / $0.374 / $4.68 / $5.61. — [G](https://thinkingmachines.ai/tinker/pricing/)
- Free tier footnote: "To use the free tier, select the model ID thinkingmachines/Inkling-2-Mini:peft:65536:free. Free training and sampling have a 64K context limit and are subject to rate limits. Requests may be throttled when those limits are reached." — [G](https://thinkingmachines.ai/tinker/pricing/)
- "Mixture-of-experts models are priced by active parameters, rather than total model size." — [G](https://thinkingmachines.ai/tinker/pricing/)
- Docs list "Inkling 2 Mini (64K train / 1M sample)" with "26B | 5.4B | MoE | Hybrid + Vision". — [H](https://tinker-docs.thinkingmachines.ai/tinker/models/)
- Checkpoint storage "Currently available for Inkling 2 Small, Inkling, and Inkling-Small only." — [G](https://thinkingmachines.ai/tinker/pricing/)

Licence:
- Inkling 2 Mini: "License: Apache 2.0" — [B](https://huggingface.co/thinkingmachines/Inkling-2-Mini); website card links a "Model Acceptable Use Policy" — [C](https://thinkingmachines.ai/model-card/inkling-2-mini/)

### Inferences
- The pricing table's "as of October 19, 2026" date predates Mini's Nov 20 release, so the date label is stale or not updated. Prices are likely to change; re-check before publishing.
- Tinker's "Sample" price is per output token; for long-form generation jobs, $0.50/M output is the number most relevant to the narrator if he used Tinker instead of self-hosting.

### Gaps
- I didn't confirm whether checkpoint storage for Mini is planned.
- Third-party API providers for Mini are mentioned generically ([C]) but not named on Mini pages.

---

## 10. Technical report, papers, looping blog, launch video/podcast

### Takeaway
I found no separate technical report or PDF for Inkling 2 Mini. The announcement post is the technical write-up, backed by the two model cards. There is one related Connectionism blog post on 4-bit training and a Goodfire write-up. Official X and YouTube accounts exist but were not reviewed.

### Cited Findings
- The post links to a 4-bit training article: "Inkling 2 Mini was trained with 4-bit precision, which we describe in a recent article on Connectionism." (link: https://thinkingmachines.ai/blog/end-to-end-4-bit-training/) — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- Cited prior work in the post: Universal Transformers (Dehghani et al., 2018); Attention Residuals (Kimi Team, 2026); Intelligence per Watt (Saad-Falcon and Narayan et al., 2025); Reasoning Models Struggle to Control their Chains of Thought (Yueh-Han et al., 2026); Think Fast (arXiv 2606.07157). — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- "We are working with the National Deep Inference Fabric (NDIF) to make these models more easily accessible to interpretability researchers. We also provided Goodfire, an interpretability research lab, early access to our looped models... and have written up their early findings here." — [A](https://thinkingmachines.ai/news/inkling-2-mini/)
- Footer links: X https://x.com/thinkymachines and YouTube https://www.youtube.com/@thinkymachines — [A](https://thinkingmachines.ai/news/inkling-2-mini/)

### Inferences
- The richest "small print" is in the website model card [C] and the chart data embedded in [A], not in a paper.

### Gaps
- I did not review the Connectionism 4-bit article, the Goodfire write-up, or any X/YouTube launch posts or videos (not checked; needed if the video wants launch-day quotes or footage).
- No arXiv paper for Inkling 2 Mini found in official links.
