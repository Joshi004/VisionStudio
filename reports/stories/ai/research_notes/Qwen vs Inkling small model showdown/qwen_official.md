# Qwen3.8-27B: Alibaba's official claims, the Qwen3.8 family, and whether Qwen4 makes it outdated (as of 27 Nov 2026)

All pages below were fetched on 27 Nov 2026. Labels used throughout:
- **[LAB]** = Alibaba / Qwen team's own claim (model card, README, blog, press release, cloud docs).
- **[INDEPENDENT]** = third party (press, Simon Willison, Artificial Analysis, Thinking Machines, etc.).
- Quotes in "double quotes" are verbatim and suitable for on-screen highlighting.

Primary source dates:
- Hugging Face model card `Qwen/Qwen3.8-27B`: no explicit publication date on the page. The GitHub README's News section dates the release "2026-08-14". The HF collection shows "Updated Aug 13". The HF API `createdAt` for the repo is 2026-08-05 (repo creation, before it went public, so it is not the release date).
- `Qwen/Qwen3.8-27B-FP8` card: same text as BF16 card plus the FP8 notes. HF API `createdAt` is 2026-08-13.
- GitHub README (https://github.com/QwenLM/Qwen3.8): undated page; News entries are dated.
- Qwen blog https://qwen.ai/blog?id=qwen3.8: titled "Qwen3.8-Max: A New Bar for Coding and Cowork", dated "2026/08/02". **It is a Qwen3.8-Max blog, not a 27B blog.** I found no separate qwen.ai blog post for Qwen3.8-27B (the README links only "the model card" for 27B, whereas Qwen3.6-27B had its own blog).
- Alibaba Cloud Community / Alizila: "Alibaba Unveils Qwen3.8-27B and Releases Weights of Qwen3.8 Flagship Model", 17 Aug 2026.
- QwenCloud changelog https://docs.qwencloud.com/changelog/models: running log, entries dated.

---

## 1. What Alibaba claims for Qwen3.8-27B (headline claims and every benchmark number)

### Takeaway
Alibaba's pitch is that a 27B dense model matches its own much larger closed Qwen3.7-Plus, and beats a frontier closed model (Claude "Opus4.6 Max") on several agentic and instruction-following rows. Every number is self-reported. The comparison set is narrow: Qwen's own models, one ~30B open rival (Muse Glimmer-30B), and an older Anthropic model. Inkling 2 Mini, Gemma 4 and Nemotron are not in the table.

### Cited Findings

**Headline wording [LAB]**
- Model card intro: "Qwen3.8-27B brings these advances to a compact, deployment-friendly dense model: a native vision-language model that understands images and videos, with flexible thinking control, designed to carry complex, multi-step tasks through to completion with greater reliability." — [HF model card](https://huggingface.co/Qwen/Qwen3.8-27B)
- Model card family framing: "we are pleased to introduce Qwen3.8, the most capable generation in the Qwen open-model family to date." — [HF model card](https://huggingface.co/Qwen/Qwen3.8-27B)
- Alibaba press article (17 Aug 2026): "Despite its compact footprint, Qwen3.8-27B delivers excellent capabilities in handling coding, professional work, research, and long-horizon agentic tasks, matching the performance of Qwen3.7-plus — an MoE model ten times its size." — [Alibaba Cloud Community, 17 Aug 2026](https://www.alibabacloud.com/blog/alibaba-unveils-qwen3-8-27b_603463)
- Same article: "It can run on consumer-grade hardware, and with quantization, it can even run on a laptop." — [Alibaba Cloud Community, 17 Aug 2026](https://www.alibabacloud.com/blog/alibaba-unveils-qwen3-8-27b_603463)
- Same article, a popularity claim: "Within just two days of release, Qwen3.8-27B has become one of the top 5 most-liked models on Hugging Face." — [Alibaba Cloud Community, 17 Aug 2026](https://www.alibabacloud.com/blog/alibaba-unveils-qwen3-8-27b_603463)
- QwenCloud changelog, 19 Aug 2026 entry: "The Qwen3.8 27B native vision-language dense model builds upon the 3.6-27B version, with key improvements in coding and office productivity capabilities across both text and visual modalities. It enables more reliable end-to-end completion of complex tasks, delivering consistently trustworthy results." — [QwenCloud changelog](https://docs.qwencloud.com/changelog/models)
- Model card highlights list: "Core Capabilities: Comprehensive improvements across coding, professional work, research, and long-horizon agentic tasks." / "Agent Execution: Stronger autonomous planning and better handling of environment feedback, leading to more reliable end-to-end task completion." / "Downstream Compatibility: Broader support for popular harnesses and development tools, making it easier to integrate into your existing stack." — [HF model card](https://huggingface.co/Qwen/Qwen3.8-27B)

**Text benchmark table on the 27B card [LAB]**: columns are Qwen3.8-27B | Qwen3.6-27B | Qwen3.7-Plus | Muse Glimmer-30B | Opus4.6 Max ("--" = not available). Source: [HF model card](https://huggingface.co/Qwen/Qwen3.8-27B)

| Benchmark (card's label) | Qwen3.8-27B | Qwen3.6-27B | Qwen3.7-Plus | Muse Glimmer-30B | Opus4.6 Max |
|---|---|---|---|---|---|
| Terminal Bench 2.1 (Terminus) | 73.0 | 63.4 | 64.0 | 51.7 | 78.2 |
| SWE-bench Pro | 61.7 | 53.5 | 57.6 | 51.2 | 53.4 |
| NL2Repo-Bench | 42.3 | 36.2 | 41.1 | -- | 47.6 |
| DeepSWE 1.1 | 42.2 | 13.3 | 14.2 | -- | -- |
| QwenSWEBench (in-house) | 79.0 | 49.3 | 59.2 | -- | 63.8 |
| CoWorkBench (in-house) | 70.7 | 61.0 | 65.1 | -- | 68.2 |
| JobBench | 33.4 | 21.8 | 27.6 | -- | -- |
| Agents' Last Exam | Pass@1 20.4 / Score 42.9 | 10.6 / 27.3 | 13.2 / 33.6 | -- | -- |
| IFBench | 79.5 | 69.1 | 79.1 | 77.0 | 62.5 |
| GPQA Diamond | 89.2 | 87.8 | 90.3 | 83.5 | 91.3 |
| HLE | 30.8 | 24.0 | 34.7 | 22.0 | 40.0 |
| LiveCodeBench v6 | 90.3 | 83.9 | 89.6 | -- | 88.8 |

**Vision-language table on the 27B card [LAB]**: same columns. Source: [HF model card](https://huggingface.co/Qwen/Qwen3.8-27B)

| Benchmark | Qwen3.8-27B | Qwen3.6-27B | Qwen3.7-Plus | Muse Glimmer-30B | Opus4.6 Max |
|---|---|---|---|---|---|
| OSWorld-Verified | 84.3 | 63.9 | 73.3 | 65.9 | 72.7 |
| WebArena-Verified | 64.8 | 48.8 | 55.3 | -- | -- |
| AndroidWorld | 81.9 | 70.3 | 81.0 | -- | 62.0 |
| RecreationBench (in-house) | 47.1 | 29.8 | 30.2 | -- | -- |
| ClawEval-MM | Pass@3 57.4 / Avg 56.9 | 42.6 / 50.4 | 57.4 / 60.1 | -- | 52.5 / 54.7 |
| SWE-MM | 38.6 | 25.7 | 30.0 | -- | 27.1 |
| Vision2Web | 62.9 | 45.0 | 42.1 | -- | -- |
| MathVision | w/o CI 90.0, with CI 94.6 | w/o CI 85.1 | w/o CI 90.3 | -- | w/o CI 65.5 |
| BabyVision | w/o CI 65.7, with CI 85.6 | w/o CI 28.9 | w/o CI 64.7, with CI 70.4 | -- | w/o CI 12.6 |
| CharXiv (RQ) | w/o CI 83.7, with CI 90.2 | w/o CI 78.4 | w/o CI 85.8, with CI 85.9 | 78.8 | w/o CI 66.0 |
| OmniDocBench 1.5 | 91.1 | 89.4 | 91.4 | 75.8 | 86.6 |
| RealWorldQA | 85.9 | 84.1 | 86.9 | -- | 73.9 |
| ERQA | 65.5 | 62.5 | 69.8 | -- | 40.8 |

**Extra Qwen3.8-27B numbers published elsewhere by Qwen [LAB]**: the later Qwen3.8-Flash-Next card (repo created 24 Aug 2026) lists Qwen3.8-27B as a comparison column and adds numbers that are not on the 27B card: "SWE-bench Multilingual" 73.8, "Toolathlon Verified (Pass@1)" 67.1, "OSWorld 2.0" "Binary 19.4 Partial 48.0", "LVBench" 72.4. It repeats DeepSWE 42.2, SWE-bench Pro 61.7, NL2Repo 42.3, CoWorkBench 70.7, JobBench 33.4, ALE 20.4/42.9, IFBench 79.5, GPQA 89.2, HLE 30.8, LCB v6 90.3. — [HF Qwen3.8-Flash-Next card](https://huggingface.co/Qwen/Qwen3.8-Flash-Next)

**Third-party evaluation widgets on the 27B HF page [INDEPENDENT, auto-aggregated]**
- Artificial Analysis Terminal-Bench 4.0 score shown: "5.6", with "Qwen3.8 27B (Xhigh); mini-swe-agent harness, pass@1 averaged over three repeats." and "Ranked #1 in the < 32B size range". — [HF model card evaluation results](https://huggingface.co/Qwen/Qwen3.8-27B)
- LlamaIndex ParseBench-2: Overall 73.39, Text 81.53, Formatting 79.33. Run notes: "served checkpoint: Qwen/Qwen3.8-27B-FP8; thinking enabled (chat template default effort)." — [HF model card evaluation results](https://huggingface.co/Qwen/Qwen3.8-27B). This is notable for the narrator: it was run on the **same FP8 checkpoint with thinking on** that he uses.

### Inferences
- Wins over "Opus4.6 Max" are against an older Anthropic model. Qwen's own Max blog (2 Aug 2026) already compares against "Opus4.8", "Fable5" and "GPT5.6 Sol (max)", so the 27B card picked a weaker frontier baseline.
- "An MoE model ten times its size" is loose. Qwen's own Flash-Next table gives Qwen3.7-Plus as "397B" total / "17B" activated. That is about 14.7× the total parameters of a 27B model, but fewer *active* parameters (17B vs 27B).
- "Matching the performance of Qwen3.7-plus" is only roughly true on the card's own table. The 27B is ahead on most coding and agent rows but behind on GPQA (89.2 vs 90.3), HLE (30.8 vs 34.7), RealWorldQA, ERQA, CharXiv w/o CI and OmniDocBench.
- On the 27B card, HLE (30.8) and Terminal Bench 2.1 (73.0 vs 78.2) are the rows where the frontier comparison clearly beats it.

### Gaps
- There is no dedicated qwen.ai blog or technical report for Qwen3.8-27B. The blog the brief cites (id=qwen3.8) covers Qwen3.8-Max only and has no 27B numbers.
- The "top 5 most-liked" claim was not independently verified. HF API at fetch time showed 21,882 likes and 6,047,011 downloads for the BF16 repo, and 7,028,433 downloads for the FP8 repo. These counts are live and will go stale.

---

## 2. Footnotes, evaluation settings, harnesses, thinking budgets, who ran competitor scores

### Takeaway
Coding and agent scores were mostly run by Qwen itself in Anthropic's Claude Code harness, at temperature 1.0 and with a 256K context window, on a benchmark Qwen says it "corrected". Several headline benchmarks are in-house. The card does not state the reasoning-effort level used for its own scores, and the Terminal Bench row has no footnote.

### Cited Findings
Text-table footnotes, verbatim [LAB] — [HF model card](https://huggingface.co/Qwen/Qwen3.8-27B):
- "SWE-bench Pro: Except for Opus4.6 Max, which uses the officially reported score, all models are evaluated with the Claude Code harness at temp=1.0, top_p=0.95, and a 256K context window. Problematic tasks were corrected, and all baseline models were re-evaluated on the refined benchmark."
- "NL2Repo-Bench: Evaluated with the Claude Code harness. To prevent reward hacking, we disable Bash commands that attempt to access the specific repository, such as pip download, pip install, and git clone."
- "DeepSWE 1.1: Evaluated with the Claude Code harness at temp=1.0, top_p=0.95, and a 256K context window."
- "QwenSWEBench: In-house coding benchmark for evaluating models' software engineering capabilities. Evaluated with the Claude Code harness. Reporting avg@3 with an 8-hour timeout, max_tokens=32,768, temperature=1.0, and a 256K context window."
- "CoWorkBench: In-house cowork benchmark for evaluating long-horizon tasks across computer science, finance, law, medical, and other productivity domains."
- "HLE: Judged by GPT-4o."
- "Empty cells (--) indicate that results are not yet available or not applicable."

VL-table footnotes, verbatim [LAB] — [HF model card](https://huggingface.co/Qwen/Qwen3.8-27B):
- "A small number of incorrect ground-truth annotations in MathVision and CharXiv (RQ) were corrected following manual verification, and all reported scores on those benchmarks were computed using the corrected annotations."
- "MathVision: Qwen3.8-27B is evaluated using the fixed prompt: "Please reason step by step, and put your final answer within `\boxed{}`." For the remaining models, we report the higher score from two prompt variants—one with and one without the `\boxed{}` formatting requirement."
- "WebArena-Verified: Scores are computed with the official WebArena-Verified grader under the OSWorld scaffold."
- "RecreationBench: An in-house, long-horizon application-recreation benchmark…"
- "ClawEval-MM: Scores are reported as "Pass@3 / average score." Pass@3 is the percentage of tasks passed in at least one of three trials…"
- "Vision2Web: … Evaluations use the Claude Code harness and are judged by `gpt-5.4-2026-03-05`."
- "SWE-MM: Scores are evaluated on the Claude Code harness using the public dev split of SWE-bench Multimodal, with the modifications described in Appendix 8.3 of the Claude Opus 4.7 system card."

Flash-Next card footnote (covers 27B numbers in that table) [LAB]: "DeepSWE 1.1: evaluated with the Claude Code and mini-SWE-agent harnesses, temp=1.0, top_p=0.95, 256K context window. We report the highest score across the two harnesses" and "SWE-bench Multilingual: evaluated with the mini-SWE-agent harness, temp=1.0, top_p=0.95, 256K context window." — [HF Qwen3.8-Flash-Next card](https://huggingface.co/Qwen/Qwen3.8-Flash-Next)

Max blog footnotes, which show the methodology family [LAB]: "Terminal Bench 2.1: Evaluated with Claude Code (avg@10), using a 5-hour timeout and max_tokens=131,072. For all other models, we report the best published score across harnesses…". Also, "SkillsBench: … the Qwen-series are evaluated on OpenCode. All results are from our own testing." — [Qwen3.8-Max blog, 2 Aug 2026](https://qwen.ai/blog?id=qwen3.8)

Default reasoning effort [LAB]: "`xhigh` (default): for complex tasks demanding thorough analysis". — [HF model card](https://huggingface.co/Qwen/Qwen3.8-27B)

### Inferences
- The card does not say which `reasoning_effort` was used for Qwen3.8-27B's own scores. Since `xhigh` is the default, the scores were most likely produced at xhigh. That is the most token-hungry setting and is not necessarily what a cost-conscious deployment runs. Flag as inference, not stated.
- Competitor scores: only SWE-bench Pro states who ran them (Qwen re-ran everyone except Opus4.6 Max). For other rows (Terminal Bench 2.1, IFBench, GPQA, HLE, LiveCodeBench, OSWorld and so on) the card does not say whether Muse Glimmer-30B and Opus4.6 Max numbers were run by Qwen or copied from vendors.
- The Terminal Bench 2.1 row is labelled "(Terminus)" but has no footnote, so the timeout, token cap and number of runs for the 27B are not stated on its card.
- "Problematic tasks were corrected" means Qwen's SWE-bench Pro is a Qwen-modified variant. Its numbers are not directly comparable to public SWE-bench Pro leaderboards or to Inkling's "SWEBench Pro v2 (Hard)".
- **Cross-check for the comparison video:** Thinking Machines' Inkling 2 Mini table lists Qwen3.8-27B at "73.0%" on "Terminal Bench v2.1 Inkling 2 Mini in pi v0.83.0" and "42.2%" on "DeepSWE v1.1 mini-swe-agent v2.4.6" ([Inkling 2 Mini HF card](https://huggingface.co/thinkingmachines/Inkling-2-Mini), 20 Nov 2026). These match Qwen's self-reported 73.0 (Terminus) and 42.2 (Claude Code / best-of-harness) exactly, even though the harness labels differ. Either Thinking Machines reused Qwen's numbers or the match is a coincidence; the Inkling researcher should verify. Inkling's SWE-bench Multilingual figure for Qwen3.8-27B (70.0%, "bash only") differs from Qwen's own 73.8 (mini-SWE-agent).

### Gaps
- There are no published token counts, average reasoning lengths or cost per task for Qwen3.8-27B in any Qwen document I found. Qwen gives such figures only for Qwen4-Max vs Qwen3.8-Max.
- Number of runs (avg@k) is stated only for QwenSWEBench (avg@3) on the 27B card.

---

## 3. Architecture, context window, modalities, thinking mode, sampling, FP8, serving, hardware

### Takeaway
Qwen3.8-27B is a dense 27B hybrid-attention model (linear-attention Gated DeltaNet plus periodic full gated attention) with a vision encoder. It is not text-only. It has a 262,144-token native context, extendable to about 1M with YaRN; thinking is on by default at `xhigh` effort; and the FP8 checkpoint is block-wise FP8 that Qwen says is "nearly identical" in quality. Qwen recommends SGLang, vLLM or TokenSpeed, and its README examples use 4-way tensor parallelism.

### Cited Findings
Architecture [LAB] — [HF model card](https://huggingface.co/Qwen/Qwen3.8-27B):
- "Type: Causal Language Model with Vision Encoder"
- "Number of Parameters: 27B", "Hidden Dimension: 5120", "Number of Layers: 64"
- "Hidden Layout: 16 × (3 × (Gated DeltaNet → FFN) → 1 × (Gated Attention → FFN))"
- Gated DeltaNet: "48 for V and 16 for QK" linear-attention heads, head dim 128. Gated Attention: "24 for Q and 4 for KV", head dim 256, RoPE dim 64.
- "Intermediate Dimension: 17,408"; "Token Embedding: 248,320 (Padded)"
- "MTP (Multi-Token Prediction): trained with multiple steps"
- "Context Length: 262,144 natively and extensible up to 1,000,000 tokens."
- HF page metadata: "Model size 28B params", "Tensor type BF16". The architecture tag in the HF API is `qwen3_5`.
- Lineage: "Built on the architectural foundation of Qwen3.5". The changelog adds that it "builds upon the 3.6-27B version" ([changelog](https://docs.qwencloud.com/changelog/models)).

Modalities [LAB]:
- "Vision-Language Understanding: Native support for image and video understanding, from STEM diagrams and documents to hour-scale videos." — [HF model card](https://huggingface.co/Qwen/Qwen3.8-27B)
- Output is text; inputs are text, image and video (card code examples use `image_url` and `video_url`).

Thinking mode [LAB] — [HF model card](https://huggingface.co/Qwen/Qwen3.8-27B):
- "Flexible Thinking Control: Thinking mode is on by default and can be disabled per request; reasoning depth can be tuned with `reasoning_effort`, and reasoning context from historical messages is retained via `preserve_thinking`."
- "Qwen3.8 models operate in thinking mode by default, generating thinking content … before producing the final response."
- Effort levels: "`xhigh` (default): for complex tasks demanding thorough analysis", "`medium`: balancing accuracy and speed", "`low`: efficient reasoning optimizing for speed and cost". Only these three levels are listed for the 27B (no "high").
- "`preserve_thinking` is enabled by default for all workloads for the best out-of-the-box experience."
- "By default, Qwen3.8 retains thinking blocks from all historical messages… It also improves KV cache utilization, optimizing inference efficiency in both thinking and non-thinking modes."
- To disable thinking when self-hosting: `"chat_template_kwargs": {"enable_thinking": False}`. On Qwen Cloud: `"enable_thinking": False` directly.

Recommended sampling [LAB] — [HF model card](https://huggingface.co/Qwen/Qwen3.8-27B):
- "Thinking Mode: `temperature=1.0`, `top_p=0.95`, `top_k=20`, `min_p=0.0`, `presence_penalty=0.0`, `repetition_penalty=1.0`"
- "Instruct (or non-thinking) mode: `temperature=0.7`, `top_p=0.80`, `top_k=20`, `min_p=0.0`, `presence_penalty=1.5`, `repetition_penalty=1.0`"
- "Please note that the support for sampling parameters varies according to inference frameworks."

Output-length (thinking budget) guidance [LAB] — [HF model card](https://huggingface.co/Qwen/Qwen3.8-27B):
- "Adequate Output Length: To optimize performance on agentic tasks, we recommend allocating sufficient output length… we suggest the following configuration within the 1M context length: Reasoning Content: Set the maximum output length to 262,144 tokens. Final Response: Set the maximum output length to 131,072 tokens."
- Hosted limits on Model Studio: "Max Output Length | 131072", "Max Chain-of-Thought Length | 262144", "Context Window | 1000000", "Max Input Length (Thinking Mode) | 983616". — [Model Studio qwen3.8-27b page](https://docs.modelstudio.console.alibabacloud.com/en/model-studio/qwen3-8-27b)

Long context / YaRN [LAB] — [HF model card](https://huggingface.co/Qwen/Qwen3.8-27B):
- "Qwen3.8-27B natively supports context lengths of up to 262,144 tokens. For long-horizon tasks where the total length (including both input and output) exceeds this limit, we recommend using RoPE scaling techniques to handle long texts effectively, e.g., YaRN."
- YaRN config uses `"factor": 4.0`, `"original_max_position_embeddings": 262144`, with vLLM `--max-model-len 1000000`.

FP8 checkpoint [LAB] — [HF Qwen3.8-27B-FP8 card](https://huggingface.co/Qwen/Qwen3.8-27B-FP8):
- "This repository contains FP8-quantized model weights and configuration files for the post-trained model in the Hugging Face Transformers format."
- "The quantization method is fine-grained fp8 quantization with block size of 128, and its performance metrics are nearly identical to those of the original model."
- Otherwise identical architecture, sampling and benchmark text to the BF16 card. Licence tag: `license:apache-2.0` (HF API).

Serving [LAB]:
- "These artifacts are compatible with Hugging Face Transformers, vLLM, SGLang, TokenSpeed, etc." — [HF model card](https://huggingface.co/Qwen/Qwen3.8-27B)
- "For production workloads or high-throughput scenarios, dedicated serving engines such as SGLang, vLLM, or TokenSpeed are recommended." — [HF model card](https://huggingface.co/Qwen/Qwen3.8-27B)
- README example commands for the BF16 model: `vllm serve Qwen/Qwen3.8-27B --port 8000 --tensor-parallel-size 4 --max-model-len 262144 --reasoning-parser qwen3 --enable-auto-tool-choice --tool-call-parser qwen3_coder`. SGLang uses `--tp-size 4 --context-length 262144 --reasoning-parser qwen3 --tool-call-parser qwen3_coder`. — [GitHub README](https://github.com/QwenLM/Qwen3.8/blob/main/README.md)
- The README also lists llama.cpp (GGUF), MLX, Unsloth and `transformers serve`. — [GitHub README](https://github.com/QwenLM/Qwen3.8/blob/main/README.md)

Hardware [LAB vs INDEPENDENT]:
- [LAB] "It can run on consumer-grade hardware, and with quantization, it can even run on a laptop." — [Alibaba Cloud Community, 17 Aug 2026](https://www.alibabacloud.com/blog/alibaba-unveils-qwen3-8-27b_603463)
- [INDEPENDENT] Simon Willison ran the "17GB Q4_K_M quantized build" on a "128GB M5 Max MacBook Pro" and an "NVIDIA DGX Spark", getting "around 15-30 tokens a second from LM Studio". With MTP speculative decoding in llama.cpp, the server "outperformed the LM Studio default GGUF by around 72%". — [Simon Willison, 16 Aug 2026](https://simonwillison.net/2026/aug/16/qwen-38-27b/)
- [INDEPENDENT] Willison: "That's the catch with these dense (non-Mixture-of-Experts) models—they require a whole lot of memory bandwidth to perform well". — [Simon Willison, 16 Aug 2026](https://simonwillison.net/2026/aug/16/qwen-38-27b/)

### Inferences
- The "28B params" in HF metadata vs "27B" in the text most likely reflects the vision encoder (and possibly MTP heads) being counted. Inference; Qwen does not explain it.
- Qwen's tensor-parallel-4 example is for full BF16 and the full 262K context. At FP8 a 27B model's weights are roughly 27–28 GB, so a single 48–80 GB GPU is plausible for the narrator's setup. Qwen gives no official minimum-GPU table, so this is an estimate.
- Because the model is dense, every token reads all ~27B weights. Inkling 2 Mini is 3.4B active (5.4B weight activations with looping), so speed and cost per token will likely favour Inkling on the same GPU. This needs an independent measurement.

### Gaps
- There is no official VRAM or GPU requirement table for BF16 or FP8.
- There are no published FP8-vs-BF16 benchmark deltas behind "nearly identical".
- No official throughput or latency numbers.

---

## 4. Writing quality, instruction following, structured output / JSON, long-context reliability, reasoning length

### Takeaway
Alibaba makes almost no specific claims about long-form writing quality or JSON reliability for the 27B. The closest evidence is IFBench (79.5) and general "dependable deliverables" language. Its own docs and independent testing both point to very long reasoning at the default `xhigh` setting. That matters directly for the narrator's long-form, JSON-returning jobs.

### Cited Findings
- [LAB] Instruction following: "Instruction following IFBench | 79.5" (vs Qwen3.6-27B 69.1, Qwen3.7-Plus 79.1, Muse Glimmer-30B 77.0, Opus4.6 Max 62.5). — [HF model card](https://huggingface.co/Qwen/Qwen3.8-27B)
- [LAB] Structured output on the hosted API: the changelog's qwen3.8-flash entries say "supporting text generation, deep thinking, visual understanding, function calling, structured output, and context caching". The **qwen3.8-27b** changelog entry (19 Aug 2026) does not list capabilities. For the previous 27B, the changelog says Qwen3.6-27B "Supports function calling and structured output but not built-in tools." — [QwenCloud changelog](https://docs.qwencloud.com/changelog/models)
- [LAB] The hosted 27B "will be available as a hosted version with more production features, e.g., 1M context length by default, official built-in tools." — [HF model card](https://huggingface.co/Qwen/Qwen3.8-27B)
- [LAB] Long context for the family flagship only: the Qwen3.8-Max blog reports "MRCR v2 256K (8-needle)" 92.9 and "LongBench v2" 66.3 for **Qwen3.8-Max**. No long-context benchmark is reported for the 27B on its card. — [Qwen3.8-Max blog, 2 Aug 2026](https://qwen.ai/blog?id=qwen3.8)
- [LAB] Static-YaRN caveat, which matters for long-context reliability: "All the notable open-source frameworks implement static YaRN, which means the scaling factor remains constant regardless of input length, potentially impacting performance on shorter texts. We advise modifying the `rope_parameters` configuration only when processing long contexts is required." — [HF model card](https://huggingface.co/Qwen/Qwen3.8-27B)
- [LAB] Reasoning effort vs. total cost: "In multi-turn agentic tasks, lower reasoning effort does not always reduce overall task completion time. Although it may produce faster per-turn responses, it can also lead to insufficient analysis, more failures, and repeated retries, which may increase total latency and token consumption." — [HF model card](https://huggingface.co/Qwen/Qwen3.8-27B)
- [INDEPENDENT] Simon Willison's headline: "Qwen 3.8 27B is excellent, but it defaults to wildly overthinking things". On the default: "This is a hilarious default. It's absolutely not a good way to run the model, especially on consumer hardware." A pelican SVG "took 21 minutes to generate, using 22,276 reasoning tokens to produce 3,223 tokens of output." The same prompt with reasoning off "produced 3,715 tokens and took 137s". — [Simon Willison, 16 Aug 2026](https://simonwillison.net/2026/aug/16/qwen-38-27b/)
- [INDEPENDENT] Willison on scope creep at xhigh: for "draw an svg of a circle" it produced "this absolutely beautiful animated circle, which was entirely not what I had asked for!" His advice: "My strong recommendation: ignore that default. Run Qwen 3.8 27B on low or even no reasoning levels at first." — [Simon Willison, 16 Aug 2026](https://simonwillison.net/2026/aug/16/qwen-38-27b/)
- [INDEPENDENT] Willison on JSON output: asked to "Return JSON bounding boxes…", the model produced valid JSON (`[{"bbox_2d": [195, 290, 370, 780], "label": "pelicans"}, …]`) that he called "such a good match." With reasoning off, a generated tool "nearly works but shows the boxes in the wrong place". — [Simon Willison, 16 Aug 2026](https://simonwillison.net/2026/aug/16/qwen-38-27b/)
- [INDEPENDENT, a competitor's claim] Thinking Machines concedes Qwen3.8-27B leads Inkling 2 Mini on multi-constraint instructions: "Inkling 2 Mini is not the strongest small model for multi-turn chat or for instructions with many constraints: it scores 50.0% on MultiChallenge and 33.4% on ComplexConstraints v1.1, behind Qwen3.8-27B on both." — [Thinking Machines, Introducing Inkling 2 Mini, 20 Nov 2026](https://thinkingmachines.ai/news/inkling-2-mini/)
- [INDEPENDENT, a competitor's claim] On chain-of-thought controllability, "Among CoTs of 750–1,250 tokens… follow the instruction at most 0.1% of the time… compared with… 1.3% for Qwen3.8-27B." — [Thinking Machines, 20 Nov 2026](https://thinkingmachines.ai/news/inkling-2-mini/)

### Inferences
- For a long-form writing and planning product running thinking on at the default `xhigh`, the main cost driver is probably reasoning tokens rather than answer tokens (Willison's example ran about 7:1 reasoning to output). Testing `medium` or `low` on his own jobs is the obvious first experiment before switching models. Qwen's own caveat warns lower effort can cause retries in *agentic* loops; it is less clear that applies to single-shot JSON generation.
- JSON reliability when self-hosting on vLLM/SGLang depends on the serving engine's guided or structured decoding, not on a Qwen claim. Qwen publishes no JSON-validity benchmark for the 27B.

### Gaps
- No Alibaba claim or benchmark specifically on creative or long-form writing quality (no creative-writing, EQ-Bench or Arena-writing numbers) for the 27B.
- No JSON-schema adherence or structured-output benchmark for the 27B.
- No long-context benchmark (MRCR, LongBench, RULER) for the 27B, and no data on quality degradation past 262K with YaRN.
- Whether the hosted `qwen3.8-27b` API supports `response_format` / JSON mode was not confirmed. The changelog entry doesn't say, and I did not fetch the full Model Studio capability table.

---

## 5. Known limitations Alibaba admits

### Takeaway
The 27B card has no "Limitations" section. The admissions are buried in usage notes: repetition and language mixing, static-YaRN hurting short texts, lower effort possibly costing more overall, conservative video defaults, and uneven sampling-parameter support across frameworks.

### Cited Findings
All [LAB] — [HF model card](https://huggingface.co/Qwen/Qwen3.8-27B):
- Repetition and language mixing: "For supported frameworks, you can adjust the `presence_penalty` parameter between 0 and 2 to reduce endless repetition. However, using a higher value may occasionally result in language mixing and a slight decrease in model performance."
- Static YaRN: "…potentially impacting performance on shorter texts."
- Reasoning effort trade-off: "lower reasoning effort does not always reduce overall task completion time… may increase total latency and token consumption."
- Framework variance: "Inference efficiency and throughput vary significantly across frameworks." and "the support for sampling parameters varies according to inference frameworks."
- Video defaults: "the `size` parameter in the released `video_preprocessor_config.json` is conservatively configured."
- Stale availability note on the card: "Qwen3.8-27B will be available as a hosted version… The service is coming soon. Stay tuned for updates." This is contradicted by the changelog, which lists `qwen3.8-27b` on 19 Aug 2026, and by live pricing pages ([changelog](https://docs.qwencloud.com/changelog/models); [QwenCloud model page](https://www.qwencloud.com/models/qwen3.8-27b?region=ap-southeast-1)).

### Inferences
- Alibaba does not disclose hallucination or factuality rates, safety evaluations, or a knowledge cutoff for the 27B in the materials I found.

### Gaps
- No knowledge-cutoff date, training-data summary or safety section for the 27B on the card. The Max blog ends with a "Training Data Summary" heading, but its content was not captured.

---

## 6. The Qwen3.8 family, how the 27B relates, and licences

### Takeaway
The Qwen3.8 family has two open-weight LLMs: Qwen3.8-2.4T-A95B (the Max-class model, licence tag "other") and Qwen3.8-27B (Apache 2.0). Hosted Qwen3.8-Max and Qwen3.8-Flash sit alongside them. An important twist: Qwen3.8-Flash is built on **Qwen3.8-Flash-Next**, a separately released 125B-total / 6B-active open-weight model that Qwen calls an "experimental preview of the architecture that will underpin Qwen4". It is gated and licensed "other". Alibaba never says the 27B was distilled from Max.

### Cited Findings
Qwen3.8-Max / 2.4T-A95B [LAB]:
- Blog (2 Aug 2026): "Today, we are officially releasing Qwen 3.8-Max, the most capable model in the Qwen family to date. This also marks the first time we will open-source the weights of a Qwen-Max-class model — the open weights will be released next week." and "2.4T parameters (95B active)". — [Qwen3.8-Max blog](https://qwen.ai/blog?id=qwen3.8)
- README News: "2026-08-12: Qwen3.8-2.4T-A95B is now available on Hugging Face Hub and ModelScope." and "2026-08-14: Qwen3.8-27B is now available on Hugging Face Hub and ModelScope." — [GitHub README](https://github.com/QwenLM/Qwen3.8/blob/main/README.md)
- Changelog, 13 Aug 2026: "Qwen3.8-2.4T-A95B is the open-source version of the Qwen flagship series, featuring a sparse MoE architecture with 2.4 trillion total parameters and approximately 95 billion activated per step… supports a 1 million token context window. Thinking mode is enabled by default." — [QwenCloud changelog](https://docs.qwencloud.com/changelog/models)
- Changelog, 3 Aug 2026 (hosted qwen3.8-max): "featuring 2.4 trillion parameters with a Mixture-of-Experts architecture… Supports hybrid thinking mode (enabled by default) and a 1M-token context window." Snapshot `qwen3.8-max-0902` was added on 2 Sep 2026. — [QwenCloud changelog](https://docs.qwencloud.com/changelog/models)
- Licence of 2.4T-A95B: the HF API tag is `license:other` (text-only model, `qwen3_5_moe_text`). — [HF API listing](https://huggingface.co/api/models?author=Qwen&sort=createdAt&direction=-1&limit=40)

Qwen3.8-27B licence [LAB, verified]:
- The LICENSE file in the repo is "Apache License | Version 2.0, January 2004" with "Copyright 2026 Alibaba Cloud". — [HF LICENSE file](https://huggingface.co/Qwen/Qwen3.8-27B/blob/main/LICENSE)
- "Released under the Apache 2.0 license". — [Alibaba Cloud Community, 17 Aug 2026](https://www.alibabacloud.com/blog/alibaba-unveils-qwen3-8-27b_603463)
- HF API tag `license:apache-2.0` on both `Qwen/Qwen3.8-27B` and `Qwen/Qwen3.8-27B-FP8`. — [HF API listing](https://huggingface.co/api/models?author=Qwen&sort=createdAt&direction=-1&limit=40)

How the 27B relates [LAB]:
- "Built on the architectural foundation of Qwen3.5, Qwen3.8 delivers substantial gains…" — [HF model card](https://huggingface.co/Qwen/Qwen3.8-27B)
- "builds upon the 3.6-27B version" — [QwenCloud changelog, 19 Aug 2026](https://docs.qwencloud.com/changelog/models)
- The Max blog describes the family-wide RL recipe: "By jointly scaling RL environments and compute, we lift general working competence uniformly across several popular harnesses (QwenWork / Claude Code / Codex / OpenClaw / Hermes)." This is stated for Qwen3.8-Max, not explicitly for the 27B. — [Qwen3.8-Max blog](https://qwen.ai/blog?id=qwen3.8)

Qwen3.8-Flash and Flash-Next [LAB]:
- Changelog, 26 Aug 2026: "Qwen3.8-Flash is a multimodal model from the Qwen family… It natively supports a million-token context window… Fully compatible with both OpenAI and Anthropic API protocols". — [QwenCloud changelog](https://docs.qwencloud.com/changelog/models)
- Flash-Next card: "Qwen3.8-Flash is the official version based on Qwen3.8-Flash-Next with more production features". — [HF Qwen3.8-Flash-Next card](https://huggingface.co/Qwen/Qwen3.8-Flash-Next)
- Flash-Next card: "This experimental preview of the architecture that will underpin Qwen4 is built around a fundamental rethinking of how the core components of modern large language models (LLMs) interact at scale." and "The first open-weight release under this architecture is Qwen3.8-Flash-Next". — [HF Qwen3.8-Flash-Next card](https://huggingface.co/Qwen/Qwen3.8-Flash-Next)
- Flash-Next size: "Number of Parameters: 125B with 6B activated, plus 51B n-gram embedding and 4B MTP". HF metadata shows "Model size 180B params"; architecture tag `qwen4_exp`; licence tag `license:other`; the page shows "You have been granted access to this model", i.e. it is gated. — [HF Qwen3.8-Flash-Next card](https://huggingface.co/Qwen/Qwen3.8-Flash-Next); [HF API listing](https://huggingface.co/api/models?author=Qwen&sort=createdAt&direction=-1&limit=40)
- In Qwen's own table, Flash-Next beats Qwen3.8-27B on every listed text row, e.g. DeepSWE 58.7 vs 42.2, JobBench 55.7 vs 33.4, IFBench 81.3 vs 79.5. — [HF Qwen3.8-Flash-Next card](https://huggingface.co/Qwen/Qwen3.8-Flash-Next)
- Also in the family: `qwen3.8-omni-flash` (18 Sep 2026), "Built on the Qwen3.8-Flash-Next architecture". — [QwenCloud changelog](https://docs.qwencloud.com/changelog/models)

### Inferences
- If the video frames the comparison by *active* parameters (Inkling 2 Mini has 3.4B active), Qwen's own closest analogue is Flash-Next (6B active), not the 27B. But Flash-Next needs memory for ~180B total parameters, has a non-Apache licence and is gated, so it is not a drop-in alternative for someone renting a single GPU.

### Gaps
- No Alibaba statement says whether Qwen3.8-27B was distilled from Qwen3.8-Max or trained with the same post-training recipe.
- The exact name and terms of the 2.4T-A95B licence ("custom Qwen3.8-Max licence" per the brief) were not verified. Only the HF tag "other" was confirmed. The same applies to Flash-Next's licence.

---

## 7. Does Qwen4 make Qwen3.8-27B outdated? (status as of 27 Nov 2026)

### Takeaway
No, not yet for open weights. Qwen4 exists only as a closed, API-only flagship (Qwen4-Max, 2.4T total / 71B active). Alibaba has promised "smaller-scale" open-weight Qwen4 models "soon", with no names, sizes, licence or date. Qwen's Hugging Face organisation has no Qwen4-named repos. Qwen3.8-27B (14 Aug 2026) remains the newest open-weight Qwen LLM in the ~20–35B class. **This is the claim most likely to go stale**: a small open Qwen4 could drop at any time.

### Cited Findings
Qwen4 timeline [LAB] — [QwenCloud changelog](https://docs.qwencloud.com/changelog/models):
- 11 Nov 2026, qwen4-max-preview: "Qwen4-Max-Preview is the next-generation flagship multimodal model in the Qwen family, combining text generation, image and video understanding, and deep reasoning."
- 16 Nov 2026, qwen4-max: "Qwen4-Max is a flagship multimodal model for text, image and video understanding, reasoning, coding, and agent tasks. It supports tool calling and structured outputs, plus explicit caching and CoT summaries."
- 20 Nov 2026: "qwen4-max is now available with the US deployment scope in US (Virginia)."
- 25 Nov 2026: "`qwen4-max-preview` was retired at 10:00 on November 25, 2026 (UTC+8). The original model ID remains callable and requests are automatically routed to `qwen4-max`."

Closed weights / open-weight promise [LAB]:
- Alibaba Group press release (16 Nov 2026): "Open-weight, smaller-scale models from the Qwen4 series will soon be released to developers worldwide." — [Alibaba Group press release](https://www.alibabagroup.com/en-US/document-2060139246777270272)
- Same release: "Built as an MoE model with 2.4 trillion total parameters, Qwen4-Max activates only 71 billion per token—25% fewer activated parameters compared to Qwen3.8-Max at the same 2.4T scale". — [Alibaba Group press release](https://www.alibabagroup.com/en-US/document-2060139246777270272)
- Alibaba Cloud blog FAQ (23 Nov 2026): "Is Qwen4-Max open source? No. Qwen4-Max is hosted only, through the Model Studio API and Token Plan. Smaller models in the Qwen4 family are coming to open source." — [Alibaba Cloud Community, 23 Nov 2026](https://www.alibabacloud.com/blog/qwen4-max-one-flagship-for-complex-work-at-a-price-that-scales_603806)
- Same blog's routing advice, which names Qwen3.8-Flash, not any small Qwen4, as the cheap tier: "pick Qwen4-Max for complex, long-horizon, multimodal workloads, and use Qwen3.8-Flash for high-frequency classification, extraction, and routing." — [Alibaba Cloud Community, 23 Nov 2026](https://www.alibabacloud.com/blog/qwen4-max-one-flagship-for-complex-work-at-a-price-that-scales_603806)
- Qwen4 architecture lineage: "These gains are driven by the new Qwen4 architecture, which upgrades the sparse Mixture-of-Experts (MoE) design across attention, residual connections, and embeddings." — [Alibaba Group press release](https://www.alibabagroup.com/en-US/document-2060139246777270272). Flash-Next (August) was the "experimental preview of the architecture that will underpin Qwen4" ([Flash-Next card](https://huggingface.co/Qwen/Qwen3.8-Flash-Next)).

Hugging Face evidence [LAB repository, checked 27 Nov 2026]:
- The HF API listing of Qwen's 40 most recently created public repos shows the newest as `Qwen/Qwen-Image-2.1-Turbo` (created 2026-10-09). No repo has "Qwen4" in its name. The only LLM repos created after Qwen3.8-27B are `Qwen3.8-Flash-Next` / `-FP8` (2026-08-24, 125B-A6B, licence "other"), plus non-LLM releases (Qwen-Drive-1.0-4B, Qwen-Image-2.1 variants). — [HF API listing](https://huggingface.co/api/models?author=Qwen&sort=createdAt&direction=-1&limit=40)

Independent confirmation [INDEPENDENT]:
- The Next Web (16 Nov 2026): "Unlike many earlier Qwen releases, Qwen4-Max cannot be downloaded and modified by users. Alibaba said smaller Qwen4 models will get open weights, with no date given." — [The Next Web](https://thenextweb.com/news/alibaba-launches-qwen4-max-flagship-ai-model-without-open-weights)
- VentureBeat (17 Nov 2026): "Alibaba promises smaller Qwen4 releases with downloadable weights, but the announcement supplies neither their licenses nor a release schedule." — [VentureBeat](https://venturebeat.com/technology/alibabas-qwen4-max-cuts-ai-task-costs-but-benchmarks-show-an-uneven-challenge-to-frontier-rivals)
- BetterClaw tracker (updated 24 Nov 2026; secondary, lower reliability): "Qwen 4 27B: not announced." and "Hugging Face "Qwen4-27B" repos are third-party placeholders". — [BetterClaw](https://www.betterclaw.io/blog/qwen-4-vs-qwen-3-8)

### Inferences
- As of 27 Nov 2026, Qwen3.8-27B is still the newest open-weight Qwen LLM with ~20–35B total parameters, and it is Qwen's only Apache-2.0 Qwen3.8 LLM. The older Qwen-AgentWorld-35B-A3B (June 2026) is a fine-tune of Qwen3.5. This is an inference from the HF listing plus Alibaba's statements; it rests on there being no Qwen4 open repos *today*.
- Qwen4-Max is a hosted flagship at $1.5 / $4.5 per 1M tokens, so it is not a substitute for a self-hosted 27B. It doesn't make the 27B outdated for self-hosters, but a small open Qwen4 is explicitly promised "soon". The narrator's video should say "as of 27 November 2026" on any "newest Qwen" claim.
- Alibaba claims the Qwen4 architecture cuts tokens (Qwen4-Max uses "35% fewer tokens at High effort reasoning mode" than Qwen3.8-Max on Work360, per the [press release](https://www.alibabagroup.com/en-US/document-2060139246777270272)). A future small Qwen4 could therefore address the 27B's verbosity problem, but that is speculation.

### Gaps
- No official name, size, licence or date for any small open Qwen4 model.
- HF listing shows public repos only; private or staged repos cannot be seen.
- I did not check ModelScope or Qwen team members' X posts directly (no accessible page was fetched), so a teaser posted there could be missed.

---

## 8. Alibaba / Qwen statements about Inkling 2 Mini

### Takeaway
I found no Alibaba or Qwen-team statement comparing with, or reacting to, Thinking Machines' Inkling 2 Mini (released 20 Nov 2026). All comparisons between the two come from Thinking Machines or third parties.

### Cited Findings
- [INDEPENDENT] The web search for a Qwen response returned only Thinking Machines' release, Hugging Face's blog and third-party tests, with no Qwen statement. — search results summarised from [Thinking Machines](https://thinkingmachines.ai/news/inkling-2-mini/), [HF blog](https://huggingface.co/blog/inkling2mini)
- [INDEPENDENT, Thinking Machines' claim] "Inkling 2 Mini scores ahead of every comparable model on agentic coding benchmarks such as DeepSWE v1.1 and SWE-bench Pro v2, and is behind only Qwen3.8-27B on others." — [Thinking Machines, 20 Nov 2026](https://thinkingmachines.ai/news/inkling-2-mini/)
- [INDEPENDENT, Thinking Machines' table] "AA Index (v5.0)": Inkling 2 Mini 20.1, Qwen3.8-27B 20.1. — [Inkling 2 Mini HF card](https://huggingface.co/thinkingmachines/Inkling-2-Mini)
- [INDEPENDENT, Thinking Machines] Thinking Machines used Qwen3.8-27B as a monitor in its safety evaluations: "both this model and TML-d24-varloop-research can be easily monitored by models like Qwen3.8-27B, which detected almost all side task attempts in our evaluation." — [Thinking Machines, 20 Nov 2026](https://thinkingmachines.ai/news/inkling-2-mini/)
- [INDEPENDENT, HF staff] "In our vibe tests, it's at least comparable with Qwen 3.8 27B. More validation is needed". — [Hugging Face blog](https://huggingface.co/blog/inkling2mini)

### Inferences
- Alibaba's newest material (the Qwen4-Max press and blog, 16 and 23 Nov) compares against Claude, Gemini and GPT models, not Thinking Machines.

### Gaps
- Qwen team members' X accounts were not directly accessible, so an informal reaction on X cannot be ruled out.

---

## 9. Pricing on QwenCloud / Alibaba Model Studio

### Takeaway
Hosted Qwen3.8-27B lists at $0.50 input / $3.00 output per 1M tokens (International / Singapore). Output is billed as "Chain-of-thought + response", so thinking tokens are paid for. Hosted Qwen3.8-Flash is much cheaper at $0.15 / $0.47.

### Cited Findings
All [LAB]; prices are list prices and may change:
- QwenCloud model page for `qwen3.8-27b` (titled "Qwen3.8-Open-Source"): "Input $0.5 Per 1M tokens", "Output $3 Per 1M tokens", "Input(Implicit Cache) $0.1 Per 1M tokens", "Explicit Cache Read $0.05 Per 1M tokens", "Max Output 128K", "Context 1M". — [QwenCloud model page](https://www.qwencloud.com/models/qwen3.8-27b?region=ap-southeast-1)
- QwenCloud pricing table: "qwen3.8-27b | International | Non-thinking and thinking modes | 0<Token≤1M | $0.5 | $3". The output column header is "Output unit price (per million tokens) Chain-of-thought + response". China (Beijing) price: "$0.424 | $1.696". — [QwenCloud model pricing](https://docs.qwencloud.com/developer-guides/getting-started/model-prices)
- Same table: "qwen3.8-2.4t-a95b | International | … | $2 | $6". — [QwenCloud model pricing](https://docs.qwencloud.com/developer-guides/getting-started/model-prices)
- Same table: "qwen3.8-flash | International | Non-thinking and thinking modes | 0<Token≤1M | $0.15 | $0.47". "Global" scope: $0.113 / $0.382. — [QwenCloud model pricing](https://docs.qwencloud.com/developer-guides/getting-started/model-prices)
- Same table: "qwen4-max | International | … | $1.5 | $4.5"; "qwen3.8-max | International | … | $2 | $6". — [QwenCloud model pricing](https://docs.qwencloud.com/developer-guides/getting-started/model-prices)
- Model Studio page for qwen3.8-27b: "This page only shows the original pricing for model API calls, excluding any limited-time promotions." — [Model Studio qwen3.8-27b](https://docs.modelstudio.console.alibabacloud.com/en/model-studio/qwen3-8-27b)
- Alibaba Cloud pricing page header: "Last Updated:Nov 27, 2026". — [Alibaba Cloud Model Studio pricing](https://www.alibabacloud.com/help/en/model-studio/model-pricing)

### Inferences
- For the narrator, the hosted $3/1M output price applies to reasoning tokens too. A run like Willison's 22K-reasoning-token example would be dominated by thinking cost. That makes the cost of `xhigh` vs `medium`/`low` a concrete on-screen point if he ever moves off his rented GPU.
- Hosted Qwen3.8-Flash ($0.15/$0.47) is cheaper than hosted 27B and, per Qwen's own Flash-Next table, its base model scores higher. That is a third option besides "stay on self-hosted 27B" and "switch to Inkling 2 Mini", if he is willing to use an API instead of self-hosting.

### Gaps
- No Qwen-provided cost-per-task figures for the 27B.
- Promotional discounts are shown only in the console, which I could not access.
