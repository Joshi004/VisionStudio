# LLM language strategy for Hindi stories in a multi-stage pipeline (native Hindi vs English pivot vs hybrid), as of 18 Nov 2026

Scope: Visio Studio's ~20 LLM calls (Story Bible, discovery, definitions, event extraction with verbatim narration/dialogue, shot planning, video/image prompts, music, on-screen callouts, thumbnails, YouTube copy). Default host Bitdeer (GLM-5.3); fallback Qwen3.8 on the owner's GPU. Architectures compared: (A) native Hindi everywhere, (B) English pivot (translate story to English, translate spoken/displayed text back), (C) hybrid (English instructions and internal/visual fields; model reads the original Hindi; spoken/displayed text copied or written in Hindi, never round-tripped).

Source-quality note: several 2026 numbers come from independent evaluation sites (sthanika.ai, NC Bench, synthorai, a personal tokenizer benchmark) rather than peer-reviewed papers. They are labelled where used. Model names such as "Claude Opus 4.8", "Qwen3.8-Max", "Gemini 3.6 Flash" are reported as those sources name them; I did not independently verify each model's existence or configuration.

---

## 1. How good are current models at Hindi understanding and creative writing (2025–2026), and what is the English–Hindi gap?

### Takeaway
Top 2026 models are strong at Hindi *understanding*: on knowledge/reasoning benchmarks the English-minus-Hindi gap is roughly 2–8 points for frontier and large open reasoning models, and wider (10–25 points) for small or non-reasoning models. Evidence on Hindi *creative writing* is thin; the only model-by-model Hindi writing test found (NC Bench) shows GLM and Qwen results that vary heavily by version and run, while some other frontier models score consistently.

### Cited Findings
**MILU (original, NAACL 2025, 5-shot, older models):**
- GPT-4o: English 81.75 vs Hindi 78.62 (gap ≈3.1); GPT-4o-mini 70.52 vs 63.14 (≈7.4); Gemini-1.5-Pro 76.91 vs 70.63 (≈6.3); Gemini-1.5-Flash 69.42 vs 64.81 (≈4.6); Krutrim-spectre-v2 46.59 vs 45.39 — [MILU, arXiv 2411.02538](https://arxiv.org/html/2411.02538v3)
- Indic-specific models (Krutrim-spectre-v2, sarvam-2b-v0.5) "perform slightly below their English counterparts of comparable scale"; performance is "notably higher" in en/hi/bn than in low-resource languages — [MILU, ACL Anthology](https://aclanthology.org/2025.naacl-long.507.pdf)

**MILU re-run on 2026 models (independent evaluator sthanika.ai; mixed scoring protocols, so treat cross-protocol ranks as descriptive):**
- Hindi accuracy: Qwen3.8-Max 91.67; Qwen3.6-27B (thinking on) 84.77; Sarvam-M 24B 83.70; Gemma 3 27B 65.73; Llama 4 Scout 64.67; Qwen2.5 7B 42.30 — [sthanika MILU 2026](https://sthanika.ai/research/milu-2026)
- English vs 10-language Indic average gap: Qwen3.8-Max 2.94; Qwen3.6-27B thinking-on 3.17 but thinking-off 12.18 (same checkpoint); Sarvam-M 3.21; DeepSeek V4-Flash 5.86; Gemma 3 27B 11.17; Qwen2.5 7B 23.19. Average gap from English for Hindi across their models: 7.14 points (smallest of the Indic languages) — [sthanika MILU 2026](https://sthanika.ai/research/milu-2026)
- Frontier MILU figures quoted from Anthropic system cards (equal-weighted average over English + 10 Indic languages, vendor-run, not Hindi-only): Gemini 3.1 Pro 93.6%, Gemini 3 Pro 93.2%, Claude Opus 4.8 91.1%, GPT-5.4 90.6%, Claude Sonnet 4.5 87.6% — [sthanika MILU 2026](https://sthanika.ai/research/milu-2026)

**MMLU-ProX (EMNLP 2025, 5-shot CoT; English vs Hindi):**
- Qwen3-235B-Think 80.7 vs 78.7 (gap 2.0); DeepSeek-R1 79.5 vs 77.5 (2.0); o4-mini 73.7 vs 71.8 (1.9); GPT-4.1 79.8 vs 74.5 (5.3); Qwen3-235B non-thinking 73.5 vs 67.6 (5.9); Qwen3-32B-Think 74.9 vs 70.4 (4.5); DeepSeek-V3 79.6 vs 71.6 (8.0) — [MMLU-ProX site](https://mmluprox.github.io/)
- "Hindi consistently leads [the South Asian] group with scores ranging from 58.4% to 78.7%" across models — [MMLU-ProX paper](https://aclanthology.org/2025.emnlp-main.79.pdf)

**BhashaBench V1 (Oct 2025, India-centric domain exams, EN/HI):**
- "Models consistently perform better on English content compared to Hindi across all domains"; best average Qwen3-235B-A22B-Instruct 67.25%, GPT-4o 66.18%, gpt-oss-120b 65.41% — [BhashaBench V1, arXiv 2510.25409](https://arxiv.org/pdf/2510.25409)
- Finance track gaps (EN − HI): gpt-oss-120b 9.95, Qwen3-235B 7.45, GPT-4o 7.45, DeepSeek-V3 6.42 — [BharatGen blog](https://bharatgen.com/blogs/bhashabench-finance-ai-india/)

**Sarvam's published evaluations (Sarvam-M 24B, built on Mistral Small):**
- Sarvam-M MILU-EN 0.83 vs MILU-IN 0.75; MMLU 0.87 vs MMLU-IN 0.79 vs romanized MMLU-IN-R 0.66; IndicGenBench 0.49 (Gemma 3 27B 0.48, Llama 3.3 70B 0.47, Mistral Small 0.43). "-IN" sets are Sarvam's own translations into Indic languages (multi-language aggregates, not Hindi-only) — [Sarvam-M blog](https://www.sarvam.ai/blogs/sarvam-m)
- Conflict: a third-party aggregator lists Sarvam-M IndicGenBench as 37.2 from the "official leaderboard" vs Sarvam's 0.49 — likely a different metric/split — [Benchmark Almanac](https://www.benchmarkalmanac.com/models/sarvam-m/)

**GLM (the owner's default family):**
- The GLM-5 model card's headline benchmark table covers reasoning, coding and agentic tasks (HLE, AIME, SWE-bench, BrowseComp, τ²-Bench…) and includes no Hindi/Indic evaluation — [zai-org/GLM-5 on Hugging Face](https://huggingface.co/zai-org/GLM-5)

**Hindi creative writing:**
- NC Bench "Character dialogue (Hindi) in a story" (5 runs per model; scoring method not visible on the pages fetched): GLM 5 58% (runs 100/50/50/47/44); GLM 5.3 (Reasoning, Max) 69% with 25% stability; GLM 5.3 Flash (Reasoning, Low) 100%; GLM 5.2 (Reasoning, High) 100%; GLM 5.1 97%; GLM 4.7 55%; Qwen 3.8 Max (Reasoning, XHigh) 84%; Qwen 3.8 27B (XHigh) 92%; Qwen 3.8 Flash 99%; Claude Opus 4.7 100%; DeepSeek V4.1 Flash (High) 100% — [NC Bench Hindi dialogue scenario](https://www.nc-bench.com/tests/language-writing/scenarios/hindi-character-dialogue); [NC Bench GLM 5 page](https://www.nc-bench.com/models/or-z-ai-glm-5)
- On the same bench, GLM 5 scored 92–100% on French/German/Italian/Spanish dialogue vs 58% on Hindi — [NC Bench GLM 5](https://www.nc-bench.com/models/or-z-ai-glm-5)
- TALES (Nov 2025): 88% of LLM-generated stories about Indian cultural identities contained at least one cultural inaccuracy; errors were more common in mid- and low-resource languages; models often had the cultural knowledge but did not apply it while writing — [TALES, arXiv 2511.21322](https://arxiv.org/html/2511.21322v1)
- Pocket FM's co-founder claims "up to 95% human-like quality" for script generation and voice synthesis in English, Hindi and German (company claim on a podcast, not a measurement) — [Analytics Insight podcast](https://www.analyticsinsight.net/podcast/ai-powered-audio-breaking-language-barriers-in-entertainment-with-prateek-dixit)
- A Dec 2025 Hindi suite (IFEval-Hi, MT-Bench-Hi, GSM8K-Hi, ChatRAG-Hi, BFCL-Hi) exists but has no creative-story task — [BHASHA 2025](https://aclanthology.org/2025.bhasha-1.5/)

### Inferences
- For *reading and analysing* a Hindi story (Story Bible, discovery, event extraction), the strongest models lose only a few points versus English, and turning reasoning on closes much of the gap (Qwen3.6-27B: gap 12.18 → 3.17). Hindi comprehension alone is not a strong reason to translate the story.
- The GLM line is the weakest-documented family for Hindi: no vendor Hindi benchmarks, and an unstable Hindi-dialogue result for GLM 5.3 at max reasoning (69%, 25% stability). The owner should test GLM-5.3 on real Hindi stories before treating it as the Hindi default, and keep Qwen3.8 or another model as a candidate for Hindi-writing stages.

### Gaps
- No Hindi results found for Kimi K2, MiniMax M2, or GLM-4.5/4.6/5.x on MILU, IndicGenBench, IndicMMLU-Pro or Global-MMLU.
- No published human evaluation of Hindi *literary/creative* writing comparing GPT-5.x, Gemini 3, Claude 4.x/5, GLM-5.x and Qwen3.x was found. NC Bench's Hindi test methodology (what is scored — script, language, naturalness?) was not visible.
- Krutrim and Llama-based Indic fine-tunes: only old MILU numbers found (Krutrim-spectre-v2 ≈45%; Hindi Llama fine-tunes such as OpenHathi/Airavata ≈28–32%, near chance), so they are not competitive with 2026 frontier/open models — [MILU](https://arxiv.org/html/2411.02538v3).

---

## 2. English pivot vs native prompting: what does the research say, and does it differ for reasoning/extraction vs creative tasks?

### Takeaway
For a high/mid-resource language like Hindi and a strong model, full translate-test gives only ~1–2 points on multiple-choice reasoning; English *instructions* with *native Hindi input* get most of that gain without translating the content. Forcing reasoning in Hindi hurts reasoning tasks, but reasoning in the input language helps cultural tasks. Models do appear to make lexical/semantic decisions in an English-like latent space, which explains why English instructions/CoT help.

### Cited Findings
- "No One Fits All" (Apr 2026): on Global-MMLU with Llama-3.3-70B, Hindi NATIVE 84.6, TRANSLATE 86.2, SEL-TRANS (English instruction with native input) 85.7; "Translation strongly benefits low-resource languages… high-resource languages gain little"; the paper groups Hindi as high-resource; "language resource level, rather than translation quality alone, determines when translation is beneficial" — [arXiv 2604.16937](https://export.arxiv.org/pdf/2604.16937)
- Sthanika (2026, independent): on IndicMMLU-Pro maths averaged over Hindi/Marathi/Telugu/Kannada, Qwen3-8B native CoT 78.65, native question + English CoT 79.17, Google-translated 80.21 (+1.6); Gemma 3 4B native 39.06 vs translated 51.04 (+12.0). Tokenizer fertility did not predict which model needed rescuing — [sthanika tokenizer study](https://sthanika.ai/research/tokenizer-fertility-2026)
- "Language Matters" (May 2025): reasoning models default to English/Chinese "reasoning hubs"; forcing input-language reasoning degrades reasoning tasks (English vs native gains: DeepSeek-R1-Distill-Llama-8B +26.8%, Qwen3-30B-A3B +11.5%, QwQ-32B +5.4%) "but benefits cultural tasks" — [arXiv 2505.17407](https://arxiv.org/abs/2505.17407)
- Hindi Analogy Test Set (Jul 2025): "models perform best with English prompts, irrespective of the prompting strategy"; "Some models struggled to follow instructions in Hindi" — [arXiv 2507.13238](https://arxiv.org/pdf/2507.13238)
- BHRAM-IL (Dec 2025): native-language prompts gave "slight accuracy improvements for Hindi" and reduced language hallucinations (answering in the wrong language), especially for small models — [arXiv 2512.01852](https://arxiv.org/pdf/2512.01852)
- Indic-QA (NAACL Findings 2025): translate-test (translate in, process, translate back) "outperformed multilingual LLMs, particularly in low-resource settings" for context-grounded QA — [ACL Anthology](https://aclanthology.org/2025.findings-naacl.141/)
- Self-translate (2023, older models such as XGLM/BLOOM/LLaMA-1): having the model translate its own input to English beat direct inference, and the effect was "more prominent for large models and high-resource languages" — [arXiv 2308.01223](https://arxiv.org/html/2308.01223v1) (older; label as pre-2025)
- Interpretability: "current LLMs make key decisions in a representation space closest to English, regardless of their input and output languages"; lexical words are chosen in English-like space first, grammatical words are not; steering works better with English vectors (tested on French, German, Dutch, Mandarin, not Hindi) — [arXiv 2502.15603](https://arxiv.org/html/2502.15603)
- Transfer-neurons work (Sep 2025): early layers map inputs into an English-centric shared space, middle layers reason there, final layers map back to the output language — [alphaXiv 2509.17030](https://www.alphaxiv.org/abs/2509.17030)
- Counterpoint (May 2025): larger models' hidden states "are more likely to dissociate from the shared representation", relying more on language-specific subspaces, while still retrieving knowledge across languages — [arXiv 2505.13141](https://arxiv.org/html/2505.13141v2)

### Inferences
- Visio Studio's analysis stages (Story Bible, discovery, definitions, shot planning) look like reasoning/extraction tasks, where English instructions and English reasoning are the best-supported choice. That is what option C does without translating the story.
- Option B's extra gain over C on comprehension is probably small (≈0.5–1.5 points in the MCQ studies) for strong models, while B adds a translation step that can lose story nuance (section 3) and breaks verbatim copying (section 6).
- Stages that are cultural or stylistic (tone, register, Hindi titles, callouts) are where native-language processing helps, per "Language Matters". Those stages should see the Hindi text and write in Hindi.
- None of these studies tested *creative writing* or long-narrative extraction directly. The evidence comes from MCQ, QA, maths and analogies.

### Gaps
- No study found comparing native vs pivot for long-form narrative *extraction* (scene segmentation, speaker attribution) in Hindi.
- No study found measuring hi→en→hi round-trip degradation on literary text specifically.

---

## 3. What is lost when literary Hindi is round-tripped through translation (honorifics, register, vocabulary layer, idioms, voice, Hinglish)?

### Takeaway
There is direct evidence that LLM translation into Hindi loses honorific marking. Literary MT studies show LLM translations are more literal and less diverse than human ones, and that automatic metrics barely detect this. Hindi register (Sanskritized vs Urdu-origin vs English-loan vocabulary) carries character voice and is easily flattened. All of these point against round-tripping dialogue and narration.

### Cited Findings
- Hindi Wikipedia uses third-person honorifics 86.6% of the time; when GPT-4o generated English and then translated into Hindi (Tr_w setting), honorific usage fell to 56.1% — "indicating potential loss of socio-pragmatic cues"; the translation-without-name setting was erratic across models; Qwen-2.5 matched Wikipedia most closely in Hindi — [EMNLP 2025, honorifics study](https://doi.org/10.18653/v1/2025.emnlp-main.966)
- Literary MT (LitEval-Corpus, 4 language pairs, none Hindi): "published human translations consistently outperform LLM translations… even the most recent LLMs tend to produce considerably more literal and less diverse translations"; automatic metrics identified human translations at most 20% of the time — [arXiv 2410.18697](https://arxiv.org/abs/2410.18697)
- Hindi→English of literary texts (Tamas, Bhagavad Gita): challenges remain "in preserving sentiment and semantic integrity, especially in metaphorical and philosophical contexts"; GPT models beat Google Translate — [arXiv 2503.21393](https://arxiv.org/abs/2503.21393)
- Idiomatic en→hi (May 2025, via an aggregator): IndicTrans2 had the highest COMET (0.74) but the lowest LLM-judged idiomatic score (1.247), while GPT-4o direct had COMET 0.73 and LLM-eval 2.14 — so COMET did not capture idiom quality — [SOTA2 leaderboard](https://www.sota2.com/research/sota/idiomatic-translation-on-mixed-dataset-en-hi) (secondary source; original paper not retrieved)
- Register layers: Hindi has overlapping Sanskritic (सहायता, अनुमति, प्रश्न), Urdu-associated (मदद, इजाज़त, सवाल) and everyday options, chosen by "domain, collocations, audience, and speaker stance" — [Elon.io Hindi grammar](https://elon.io/grammar/hindi/choosing/sanskritic-versus-urdu-versus-everyday-vocabulary); Urdu-influenced vocabulary is typical of "conversation, poetry, film dialogue", Sanskritic of official/news/ceremonial prose — [Settemila Lingue](https://www.settemilalingue.com/en/languages/hi/grammar/urdu-hindi-register)
- A company research blog (TruLM) reports that standard MT benchmarks reward formal Sanskritized "editorial" Hindi: their conversational-register translator dropped from 54.6 to 45.5 chrF++ on FLORES-200; a plain instruction to "write शुद्ध हिंदी" shifted register far less than a targeted intervention — [TruLM blog, benchmarks](https://blog.trulm.com/posts/hindi-benchmarks-cant-hear/); [TruLM blog, register neurons](https://blog.trulm.com/posts/register-neurons/) (vendor blog, moderate reliability)
- Pocket FM's research on long-form story adaptation found English→Hindi the "high-divergence" pair, where a rigid global entity registry was brittle (identity error 0.147 vs 0.111 for a rolling-summary baseline) — [Pocket FM, "Adaptation, Not Translation"](https://pocketfm.com/about-us/research/adaptation-not-translation.pdf)

### Inferences
- In option B, Hindi aap/tum/tu distinctions disappear in English ("you") and must be guessed again on the way back. The honorific study suggests that guess will often be wrong (≈30-point drop for GPT-4o). This directly damages character voice in dialogue.
- Register choices (दिल vs हृदय, सवाल vs प्रश्न, English loans like मीटिंग) carry character and genre. An English pivot erases them and the back-translation will pick its own register. MT systems tuned on FLORES-style data lean toward formal Hindi.
- Because automatic metrics (COMET/chrF) barely detect literary loss, a pipeline can't reliably check its own round-trip quality automatically.

### Gaps
- No quantitative study found on Hinglish or code-mixed dialogue surviving hi→en→hi translation.
- No study found on wordplay/puns in Hindi MT.

---

## 4. Translation engines for Hindi↔English (if a translation step is used)

### Takeaway
For self-hosting, IndicTrans2 is the only clearly permissive (MIT) dedicated Hindi MT model. NLLB-200 is non-commercial and research-only. Sarvam-Translate is open-weights but is evaluated on technical and structured content, not fiction. DeepL added Hindi only in Nov 2025, as an enterprise beta with a limited feature set. A strong LLM is likely the best translator for literary and idiomatic text, but with the register and honorific risks above.

### Cited Findings
- IndicTrans2: model checkpoints MIT-licensed; covers all 22 scheduled Indian languages; RoPE long-context variants handle up to 2048 tokens (Jan 2025); 1B en-indic/indic-en and ~200M distilled variants — [AI4Bharat/IndicTrans2 GitHub](https://github.com/AI4Bharat/IndicTrans2/); [HF collection](https://huggingface.co/collections/ai4bharat/indictrans2)
- IndicTrans2 paper uses chrF++ as the primary metric (COMET-22 reported for 13 languages including Hindi); reports En→Indic gains of 1.7 (commercial) and 4.1 (open) chrF++ over the best baselines on IN22-Gen, and Indic→En comparable to them (+0.7/+1.1) — [arXiv 2305.16307](https://arxiv.org/pdf/2305.16307v3.pdf) (2023, older)
- NLLB-200: licence "CC-BY-NC"; "research model and is not released for production deployment"; "not intended to be used for document translation"; trained on inputs ≤512 tokens — [facebook/nllb-200-distilled-600M](https://huggingface.co/facebook/nllb-200-distilled-600M)
- Sarvam-Translate: fine-tuned from Gemma3-4B-IT; 8k-token context; paragraph and structured-document translation for Hindi; professional human evaluators preferred it over Gemma3-27B-IT, Llama-3.1-405B and Llama 4 Scout. The test documents were technical, conversational, structured and news content — [Sarvam blog](https://www.sarvam.ai/blogs/sarvam-translate); [HF README](https://huggingface.co/sarvamai/sarvam-translate/blob/main/README.md)
- An independent reviewer found a clear lexical error in Sarvam's own showcase example, judged Google Translate "a bit better" in personal tests, and would use it for stories "only as a reference" — [Thejesh GN, Jun 2025](https://thejeshgn.com/2025/06/10/first-impressions-of-sarvam-indic-translate-model/)
- DeepL announced ~70 new languages including Hindi on 5 Nov 2025, "in beta for enterprise customers" — [DeepL press release](https://www.deepl.com/en/press-release/deepl_unveils_next-gen_language_ai_tools_and_game-changing_agentic_productivity_solution); a later review says the DeepL API lists Hindi with only Translation and Tag Handling (no glossaries/style rules listed) — [LikaCloud review](https://www.likacloud.com/blog/multilingual-website/deepl-2025-language-expansion-review/) (secondary)
- The "No One Fits All" study used Google Translate to translate prompts — [arXiv 2604.16937](https://export.arxiv.org/pdf/2604.16937); Sthanika found Google Translate and Sarvam-1 translation gave near-identical downstream accuracy (Qwen3-8B 80.21 both) — [sthanika](https://sthanika.ai/research/tokenizer-fertility-2026)

### Inferences
- If any translation is needed (e.g., an English working summary for the owner, or English visual prompts), use an LLM or IndicTrans2 for *internal* text only, never for text that is spoken or shown.
- NLLB's licence and sentence-level design rule it out for a product pipeline.

### Gaps
- Sarvam-Translate's licence terms were not confirmed (it is Gemma-derived, so Gemma terms may apply; unverified).
- No 2025–2026 chrF/COMET comparison was found of IndicTrans2 vs GPT-5/Gemini 3/Claude on *literary or conversational* hi↔en text. Mayura (Sarvam's API translator) quality data was not found.

---

## 5. Tokenization cost of Devanagari Hindi

### Takeaway
The same Hindi content costs about 1.3× to 4.8× the tokens of English, depending on tokenizer. GLM-5.x and the Qwen2/Qwen3 tokenizer are among the *worst* for Devanagari, which matters because those are the owner's two model families. Hindi stages on GLM may cost roughly 3× English for input and output, run slower, and fit about a third as much story text into context.

### Cited Findings
- "Indic Token Tax in 2026" (Nov 2026, FLORES-200, tokens relative to aligned English): Hindi needs 1.57× on GPT-4o/o200k (lowest of all Indian languages on that tokenizer), 1.79× on Mistral-Nemo/Sarvam-M, 2.81× on DeepSeek-V3, 4.43× on Qwen2.5, 4.78× on cl100k, 1.31× on Sarvam-30B/105B, 1.14× on Sarvam-1. DeepSeek V4/V4.1 tokenizers are identical to V3 for plain text. On cl100k and Qwen2.5, Devanagari averages about one character per token — [arXiv 2611.13058](https://arxiv.org/abs/2611.13058)
- Same paper, worked example (illustrative list prices, 5 Nov 2026): a bot costing INR 56,640/month in English on GPT-4o costs INR 89,145 in Hindi; on deepseek-flash, Hindi ≈19.1k vs English ≈6.8k INR (≈2.8×) — [arXiv 2611.13058](https://arxiv.org/abs/2611.13058)
- GLM 5.2 uses 0.91 tokens per Devanagari character ("almost no multi-character Devanagari merges") vs GPT-5.5 0.35, DeepSeek 0.61, Kimi K2.5 0.63, Claude 0.71; on a parallel passage GLM 5.2 needed 192 tokens for Hindi vs 63 for English (~3×), "2.59x the leanest" model — [synthorai blog](https://synthorai.io/blog/cheapest-llm-by-language/) (independent blog; small sample)
- Devanagari (Nepali) token tax across tokenizers: GLM-5 4.8× (only 138 Devanagari vocabulary entries), GLM-4 5.3×, Qwen3 base 4.9× (71 entries), Qwen 3.5 tokenizer 3.7× (959 entries), DeepSeek V4 3.3×, Kimi K2 3.3×, Llama 3 3.0×, o200k 2.2×, Gemma 4 2.0× — [Siddhant Karki benchmark](https://siddhantskarki.com/case-studies/nepali-tokenizer) (personal benchmark; Nepali shares Devanagari, used here as a proxy for Hindi)
- Tokens per Hindi word (FLORES+): Sarvam-1 1.27, Sarvam-30B 1.31, Gemma 3 4B 1.68, GPT-4o 2.42, Claude Sonnet 4.5 2.75, Qwen3-8B 2.85, Llama 3.1 8B 2.88, Gemini 3.6 Flash 3.10 (API models estimated via output tokens); English ≈1.3 for all — [sthanika tokenizer study](https://sthanika.ai/research/tokenizer-fertility-2026). Caution: the same page's prose gives Qwen3-8B "8.68 tokens/word" and its glossary gives Gemini 3.6 Flash an Indic average of 2.31 vs 3.69 in the table, so its figures are internally inconsistent — [sthanika glossary](https://sthanika.ai/glossary/tokenizer-fertility)
- Romanized vs native script: on o200k the two cost about the same (0.90–1.10×); on Qwen2.5 romanized text needs only 0.28–0.75 of the native-script tokens; on Sarvam tokenizers romanized is *more* expensive. Hinglish (PHINC) costs 1.28× English on o200k, 1.36× on Qwen2.5 — [arXiv 2611.13058](https://arxiv.org/abs/2611.13058)

### Inferences
- In Visio Studio, the Hindi story text is re-sent to many of the ~20 calls. Under option A, *every* output field (definitions, shot specs, prompts) would also pay the ~3× GLM tax. Under option C, only the story text and the Hindi spoken/displayed fields pay it, and English internal fields cost the same as today. That is a concrete cost and latency argument for C over A.
- Output-token budgets (max_tokens) for stages that emit Hindi narration or dialogue (event extraction, speech units, callouts) should be raised about 3× on GLM/Qwen3 to avoid truncated JSON.
- Long Hindi stories will hit context limits about 3× sooner on GLM than the same story in English. Scene-level chunking matters more for Hindi.

### Gaps
- Qwen3.8's tokenizer was not measured anywhere found. GLM-5.3's tokenizer was not measured directly (GLM-5 and 5.2 were).
- Bitdeer's per-token prices for GLM-5.3 were not retrieved.

---

## 6. Exact-copy reliability for Hindi spans (scene slices, verbatim dialogue) and Devanagari normalization

### Takeaway
LLMs do not copy long spans verbatim reliably even in English: they substitute tokens mid-span and overrun boundaries. No benchmark covers multilingual copying, but Devanagari adds Unicode pitfalls (nukta composition exclusions, meaningful ZWJ/ZWNJ). The pipeline should avoid having the model regenerate the story text: get boundaries from the model, then slice the original text in code.

### Cited Findings
- CopyGen (Oct 2026): "even when the target string is present in context, models often still drift within the span or fail to stop correctly". Base Qwen3-8B exact match was 16.31% on contracts, 77.24% on literature and 80.35% on code; the average across three frozen backbones was 51.9%, raised to 70.3% by a copy-constrained decoder. The benchmark "does not consider… multilingual copying" — [arXiv 2610.28393](https://arxiv.org/abs/2610.28393)
- In machine-translated web text, structured spans into Hindi were preserved 93.4% of the time; failures were mostly deletions (46.8%) rather than transliteration (5.0% of failures for Hindi) — [WAC 2026](https://aclanthology.org/2026.wac-1.9.pdf)
- U+0958 DEVANAGARI LETTER QA (क़) is a script-specific *composition exclusion*: NFC normalization does not keep the precomposed form, so "the same" letter can appear as one or two code points — [Unicode UAX #15](https://www.unicode.org/reports/tr15/)
- ZWJ after virama forces a half-form and ZWNJ forces a visible virama, so these invisible characters change rendering — [Unicode Indic FAQ](https://unicode.org/faq/indic.html); [Microsoft Devanagari font spec](https://learn.microsoft.com/en-us/typography/script-development/devanagari)
- Keyboards sometimes pad text with unnecessary joiners, but "joiners cannot be blindly deleted"; visually identical alternative sequences exist (e.g., ऑं vs आँ in many fonts); Google's Nisaba "visual normalization" handles these and includes NFC — [google-research/nisaba](https://github.com/google-research/nisaba/blob/main/nisaba/scripts/brahmic/README.md)
- Common text pipelines that apply NFKD + ASCII-only encoding delete non-Latin text entirely — [disarm docs](https://docs.disarm.dev/user-guide/llm-pipelines)

### Inferences
- Visio Studio requires scene slices that concatenate exactly to the story and dialogue copied word-for-word. Given about 77% exact match on English literature for an 8B model, asking the model to *reproduce* Hindi spans will produce mismatches. Safer design:
  1. Normalize the story once at input (NFC, or Nisaba visual normalization) and store it as canonical.
  2. Pre-split it in code into numbered sentences or paragraphs.
  3. Have the model return unit IDs or ranges for scenes and for each narration/dialogue line.
  4. Build the Hindi text in code from the canonical story.
  5. If models must quote, validate with exact match after NFC on both sides and reject or repair on mismatch.
- This design works the same under A, B or C. But it is impossible under B for the *Hindi* text, because B's model only ever sees English, so its spans can't map back to Hindi offsets without alignment.
- Normalizing NFC on both sides before comparing avoids false mismatches for nukta letters (क़ ख़ ग़ ज़ ड़ ढ़ फ़).

### Gaps
- No study found measuring how often LLMs silently "correct" Hindi spelling (e.g., chandrabindu vs anusvara, nukta dropping) when copying. This is plausible but unverified.
- No multilingual exact-copy benchmark exists yet (CopyGen authors list it as future work).

---

## 7. Input forms: Romanized Hindi / Hinglish and transliteration

### Takeaway
Models handle Devanagari Hindi better than Romanized Hindi. Transliterating Romanized input back to Devanagari recovers most of the lost accuracy. LLM-based transliteration beats IndicXlit on informal Romanized sentences.

### Cited Findings
- EMNLP 2026 industry paper (medical triage; GPT-4o, Claude Sonnet 4.5, Qwen3-80B, DeepSeek-V3, Llama-4, Sarvam-M): romanized input was weakest for every model, 1–8 points below native script for the top tier; "Hindi and Punjabi are comparatively robust, though the native-vs-romanized script gap persists even there"; Sarvam-M showed a substantial script gap — [Script Gap, ACL Anthology](https://aclanthology.org/2026.emnlp-industry.144.pdf)
- Per press coverage of that study, transliterating romanized messages back to native script raised GPT-4o from 75.3% to 80.1%, nearly matching native; translating to English also helped "but not as reliably" — [Hindu BusinessLine](https://www.thehindubusinessline.com/business-tech/scripting-ideal-ai-output/article70396751.ece)
- Sarvam-M: MMLU-IN 0.79 vs romanized MMLU-IN-R 0.66; GSM-8K-IN 0.92 vs -IN-R 0.82 — [Sarvam-M blog](https://www.sarvam.ai/blogs/sarvam-m)
- IndicXlit: ~11M-parameter transformer, Roman↔native for 21 Indic languages — [AI4Bharat/IndicXlit](https://github.com/ai4bharat/indicxlit). On romanized Hindi sentences, IndicXlit had 45.5% WER vs 21.5% for Llama 3.1 and 18.9% for a fine-tuned Llama — [IndoNLP 2025](https://aclanthology.org/2025.indonlp-1.15.pdf)

### Inferences
- Accept Romanized Hindi but convert it to Devanagari once at intake, using an LLM transliteration pass rather than IndicXlit. Show the result to the user to confirm, then treat the confirmed Devanagari text as the canonical story for slicing and verbatim copying. TTS and on-screen Hindi text will also typically want Devanagari.
- English words inside Hindi (Hinglish loans like मीटिंग) are natural spoken register and should be kept, not "purified".

### Gaps
- No data found on how well Hindi TTS voices (used downstream) handle Romanized vs Devanagari input. That is outside this note's scope but affects the canonical-script choice.
- Google Input Tools' transliteration accuracy was not found in 2025–2026 sources.

---

## 8. How existing AI video, dubbing and story products handle Hindi

### Takeaway
Dubbing and video-translation tools (HeyGen, ElevenLabs) are translation pipelines by nature, but all of them put a human-editable target-language script between translation and speech. HeyGen guarantees exact speech only for a script the user supplies in proofread mode. The closest analogue to Visio Studio, Pocket FM, lets Hindi writers produce audio from their Hindi text directly. For cross-language work it uses a staged LLM "adaptation" pipeline rather than plain translation.

### Cited Findings
- HeyGen: an *input* SRT is used as reference "but re-translates the content — the output will not match your file word-for-word"; an *output* SRT uploaded in Proofread mode is "spoken exactly as written"; Brand Glossary keeps terms consistent; text baked into the video image is not translated — [HeyGen help](https://help.heygen.com/en/articles/10029081-how-to-get-started-with-video-translation); the Proofread step lets users edit the translated script word-by-word before generation — [HeyGen Academy](https://www.heygen.com/academy/proofread)
- ElevenLabs Dubbing: source transcript → per-segment machine translation that users can override → regenerate; "Correct the source transcript before adding languages" — [ElevenLabs docs](https://elevenlabs.io/docs/eleven-api/guides/how-to/dubbing/refine-and-regenerate). ElevenLabs Productions adds native-speaker review of translations — [ElevenLabs Productions](https://elevenlabs.io/docs/eleven-creative/services/productions/dubbing)
- Pocket FM extended its one-click AI audio series (built with ElevenLabs) to Hindi writers. Hindi is its largest writer and listener base; tonality per genre was a key focus — [Moneycontrol](https://www.moneycontrol.com/artificial-intelligence/pocket-fm-now-lets-hindi-writers-in-india-create-ai-audio-series-in-a-single-click-article-13553178.html)
- Pocket FM Atlas runs five phases: Extract, Strategize, Localize, Complete, Adapt. It keeps an entity registry and a cultural strategy, and does separate rephrasing and language-specific polish passes. Its LLM entity extraction reads source languages directly ("language-agnostic") — [Pocket FM Atlas](https://xtra.pocketfm.com/out-of-pocket/introducing-atlas-powerful-story-adaptation-engine); [Pocket FM paper](https://pocketfm.com/about-us/research/adaptation-not-translation.pdf)
- Pocket FM (Jan 2026): off-the-shelf models "do not work for us out of the box"; leading TTS providers "perform poorly" on Hindi for dramatic dialogue delivery — [YourStory](https://yourstory.com/2026/01/pocket-fm-hires-former-meta-ai-scientist-to-build-its-own-ai-models-for-storytelling)

### Inferences
- Where the source is already Hindi, products keep the author's Hindi text as the spoken script (Pocket FM). Translation is used only when the source language differs, and then always with a human-editable script layer. Visio Studio's case (Hindi in, Hindi out) matches the "no translation of spoken text" pattern, i.e., option C.
- Pocket FM's design (LLM reads the source directly, builds a registry, then does stage-specific passes) is close to option C's structure.

### Gaps
- No public documentation found on Synthesia's or Rask AI's internal Hindi pipeline. Sarvam's consumer products (e.g., Samvaad/Bulbul-based) were not reviewed for pipeline design.

---

## 9. Should identifiers and visual descriptions stay in English for Hindi stories?

### Takeaway
No direct study answers this. The indirect evidence (English-centric reasoning, the Hindi token tax, exact-copy fragility, and English-heavy video and image prompts) supports keeping IDs ASCII/English and keeping visual definitions and prompts in English, while storing each character's Hindi name and Hindi spoken text alongside.

### Cited Findings
- Models reason in an English-like latent space and follow English instructions best — [arXiv 2502.15603](https://arxiv.org/html/2502.15603); [arXiv 2507.13238](https://arxiv.org/pdf/2507.13238)
- English text costs ~1.3–4.8× fewer tokens than Hindi for the same content, depending on tokenizer — [arXiv 2611.13058](https://arxiv.org/abs/2611.13058); [Karki](https://siddhantskarki.com/case-studies/nepali-tokenizer)
- Long-form adaptation keeps a canonical-name registry per entity to stop identity drift across chapters — [Pocket FM paper](https://pocketfm.com/about-us/research/adaptation-not-translation.pdf)

### Inferences
- Use ASCII slugs (e.g., `char_ramesh`, `scene_04`) as IDs, plus fields like `display_name_hi: "रमेश"` and `display_name_en_translit: "Ramesh"`. IDs are joined in code; Devanagari IDs would bring NFC/ZWJ comparison hazards and higher token cost.
- Appearance, wardrobe, environment and shot specs are internal and feed English-prompted image/video models, so keep them English. Add culturally specific terms in transliterated form where needed (e.g., "kurta", "dupatta", "chawl") so visual meaning isn't lost.
- Voice descriptions (for TTS selection) in English are fine. Each speaking character should also carry a Hindi register note (e.g., "uses tu with brother, aap with father; Urdu-leaning vocabulary").

### Gaps
- Whether MiniMax H3 (video) and the image models used accept or benefit from Hindi prompts, and how they render Devanagari on-screen text, was not researched here.

---

## 10. Overall: A vs B vs C (or another design)

### Takeaway
The evidence favours option C (hybrid), refined. Use English instructions and English internal and visual fields. The model reads the original Devanagari story directly. Spoken text comes from the source story by reference (unit IDs sliced in code), not regenerated. New audience-facing Hindi text (titles, callouts, YouTube copy, thumbnail text) is written natively in Hindi following a Story-Bible register guide. Option B (the owner's "translate in/out" idea) offers ~1–2 points of comprehension gain at best for strong models, but loses honorifics, register and verbatim fidelity. Option A pays the Hindi token tax on every internal field for no clear quality benefit.

### Cited Findings
- English instruction with native input (SEL-TRANS) scored within ~0.5 points of full translation for Hindi (85.7 vs 86.2; native 84.6) — [arXiv 2604.16937](https://export.arxiv.org/pdf/2604.16937)
- English reasoning helps reasoning tasks; input-language reasoning helps cultural tasks — [arXiv 2505.17407](https://arxiv.org/abs/2505.17407)
- Translation into Hindi drops honorific usage (GPT-4o 56.1% vs 86.6% reference) — [EMNLP 2025](https://doi.org/10.18653/v1/2025.emnlp-main.966)
- LLM literary translations are more literal and less diverse; automatic metrics rarely detect this — [arXiv 2410.18697](https://arxiv.org/abs/2410.18697)
- GLM-5.x Devanagari tokenization ≈0.91 tokens per character, ~3× English for the same passage — [synthorai](https://synthorai.io/blog/cheapest-llm-by-language/)
- Reasoning mode closes much of the Hindi gap (Qwen3.6-27B gap 12.18 → 3.17 with thinking on) — [sthanika MILU 2026](https://sthanika.ai/research/milu-2026)
- Exact copying is unreliable without decoding control (≈52% average exact match for frozen 4–8B models across domains) — [arXiv 2610.28393](https://arxiv.org/abs/2610.28393)

### Inferences
- Stage mapping under C:
  - **Story Bible:** English fields, plus a new `language_profile` block: script, register (Hindustani, shuddh or Hinglish), honorific conventions, and how much English loan vocabulary to allow.
  - **Discovery and event extraction:** Hindi story in, English instructions, output is unit IDs plus English summaries. Hindi narration and dialogue are filled in from the source by code.
  - **Definitions and shots:** English, with Hindi names carried as fields.
  - **Speech units:** split Hindi lines at unit boundaries.
  - **Callouts, thumbnails, YouTube copy:** generated directly in Hindi (optionally with English or Hinglish variants), with the register guide in the prompt.
  - **Image and video prompts:** English.
- Allow reasoning/thinking in English: instruct "think in English, output JSON with Hindi only in designated fields".
- For model routing, run a short in-house evaluation on 5–10 real Hindi stories before committing. Compare GLM-5.3 and Qwen3.8 on scene-boundary accuracy, speaker attribution, honorific/register preservation in generated Hindi, and the token cost per story. GLM's tokenizer cost and unstable Hindi-dialogue results justify that check.
- A small optional variant: if one stage struggles with Hindi comprehension, add an *internal-only* English gloss of the story (self-translation) as extra context next to the Hindi original, never as a replacement. This captures B's comprehension benefit without B's output losses.

### Gaps
- No end-to-end study of a multi-stage story-to-video pipeline in Hindi exists. The recommendation is assembled from component evidence (MCQ/QA pivoting studies, honorific translation, tokenizer measurements, copy benchmarks) and should be validated on the owner's own stories.
