# Hindi speech recognition, word timestamps and forced alignment for Visio Studio (as of 18 Nov 2026)

Scope: what to use for Hindi (hi-IN, Devanagari) in the three transcription uses of Visio Studio: (1) word timings of the app's own TTS audio, where the exact text is known; (2) word timings of a user's own recorded voice in explainer projects, which are split and spliced at word boundaries, where the script is known but the speaker may deviate; (3) the dialogue check of MiniMax H3 clips, which compares heard words with the intended line. Hinglish (code-mixed Hindi-English) is covered separately in its own section.

Context from the codebase (read on 18 Nov 2026): the transcriber sends only `{audio_asset_id}` (plus optional partition/priority) to `/v1/parakeet/transcribe`, with no language field, and expects `word_timestamps: [{word, start, end}]` — [backend/app/providers/transcriber.py](backend/app/providers/transcriber.py). The dialogue check normalises with NFKC + casefold, keeps letters, digits and combining marks, turns everything else into a space, then compares word lists with `difflib.SequenceMatcher`, and its later matching steps (numbers, UK/US spelling, homophones, fillers) are English-only — [backend/app/services/dialogue_check.py](backend/app/services/dialogue_check.py), [backend/app/services/dialogue_matching.py](backend/app/services/dialogue_matching.py).

---

## 1. Which NVIDIA (Parakeet / Canary / NeMo / Nemotron / Riva) models support Hindi, and what happens if the current Parakeet gets Hindi audio?

### Takeaway
The only NVIDIA-published model with confirmed Hindi support is **Parakeet-RNNT-1.1B Multilingual**, distributed as an NVIDIA NIM / Riva container (not as a Hugging Face checkpoint); `parakeet-tdt-0.6b-v3` covers 25 European languages and **does not include Hindi**, and it has no language input or output, so Hindi audio sent to it will not be rejected — it will be transcribed into whatever its vocabulary allows. The Hindi Parakeet fine-tunes found on Hugging Face (`parakeet-hi-v3`, `parakeet-indic-v1`) are private community models, not NVIDIA releases.

### Cited Findings
- `parakeet-tdt-0.6b-v3` (released on HF 14 Aug 2025) supports exactly 25 European languages: bg, hr, cs, da, nl, en, et, fi, fr, de, el, hu, it, lv, lt, mt, pl, pt, ro, sk, sl, es, sv, ru, uk. **Hindi is not in the list.** It "automatically detects the language of the audio and transcribes it without requiring additional prompting", provides word- and segment-level timestamps, and is licensed CC-BY-4.0 ("ready for commercial/non-commercial use") — [HF model card](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3)
- The model card's listed risk: "If a word is not trained in the language model and not presented in vocabulary, the word is not likely to be recognized." — [HF model card](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3)
- An NVIDIA NeMo maintainer (nithinraok, 9 Dec 2025) confirmed "parakeet-v3 model doesn't receive or output language id"; users report language misclassification (e.g. mixing Slavic languages, Cyrillic vs Latin), and the thread is referenced by an issue titled "Parakeet-TDT v3: Russian output is transliterated garbage" — [NeMo issue #14799](https://github.com/NVIDIA-NeMo/NeMo/issues/14799)
- A third-party app's docs describe Parakeet V3 as "Locked to Auto-detect" for its 25 European languages, and list a separate "Nemotron Multilingual" model with 31 languages (which languages were not listed in the excerpt) — [Vowen docs](https://docs.vowen.ai/transcription/languages)
- `nvidia/parakeet-rnnt-1.1b` on Hugging Face is English-only ("transcribes speech in lower case English alphabet") — [HF model card](https://huggingface.co/nvidia/parakeet-rnnt-1.1b)
- **Parakeet-RNNT-1.1B Multilingual** (NIM id `parakeet-1-1b-rnnt-multilingual-asr`): 1.1B params, FastConformer-RNNT, trained on >90K hours, "universal tokenizer", supports 25 languages/variants **including Hindi (hi-IN)**, outputs case and punctuation, "ready for commercial use"; Linux only, NVIDIA Blackwell/Ampere/Hopper/Jetson/Turing GPUs — [NVIDIA NIM model card](https://build.nvidia.com/nvidia/parakeet-1_1b-rnnt-multilingual-asr/modelcard)
- An NVIDIA FAQ page (updated 9 Jun 2026) states "NVIDIA Nemotron Speech provides confirmed Hindi ASR support through Parakeet RNNT 1.1B Multilingual" and that it can run on a single L40, A100 (80GB) or H100 together with Magpie TTS Multilingual (which also supports Hindi). The same page says both "20-language matrix" and "25-language matrix", so it is internally inconsistent on the count — [NVIDIA Perspectives FAQ](https://perspectives.nvidia.com/nemotron-speech/task/faq/speech-recognition-models-hindi-transcription/)
- Per a secondary aggregator summarising NVIDIA docs: the NIM has a default profile (auto language detection), a "prompt" profile (client supplies a language code, "may provide better accuracy") and an **"Indic" profile optimised for Bengali, Hindi and Tamil**; it needs roughly **50 GB of GPU memory**; Riva release notes say this model does not support word boosting or inverse text normalisation; served through Riva gRPC APIs — [llms.ninja (aggregator, not primary)](https://llms.ninja/nvidia/models/parakeet-1-1b-rnnt-multilingual-asr)
- Parakeet CTC NIM models cover only en-US, es-US, vi-VN, zh-CN, zh-TW — [NVIDIA Perspectives FAQ](https://perspectives.nvidia.com/nemotron-speech/task/faq/speech-recognition-models-hindi-transcription/)
- Community Hindi Parakeet: `amn-raw/parakeet-indic-v1` (0.6B FastConformer-TDT, base `nvidia/parakeet-tdt-0.6b-v3`) is "Built from parakeet-hi-v3 (Hindi)", reports Hindi WER 16.1 / CER 6.4 averaged over 5 sets; `parakeet-hi-v3` scores FLEURS-hi 12.37 WER / 4.24 CER, IndicVoices-valid 18.12 / 7.37, noisy phone 23.45 / 11.40. **But the repo is private ("the repo is private", "Status: ... Internal use only")**. Word timings available through NeMo `timestamps=True` — [HF model card](https://huggingface.co/amn-raw/parakeet-indic-v1)
- The NeMo-format Hindi model `ai4bharat/indicconformer_stt_hi_hybrid_ctc_rnnt_large` (an AI4Bharat model, not NVIDIA) was usable with the NeMo Forced Aligner in an Oct 2026 study — [arXiv 2610.08847](https://arxiv.org/abs/2610.08847)

### Inferences
- The current pipeline has a silent-failure risk for Hindi: because `parakeet-tdt-0.6b-v3` cannot be told the language and has no Hindi in its training set, Hindi audio will most likely come back as non-empty Latin/Cyrillic-like text with plausible timestamps, not as an error. For use 3 this would make every Hindi take fail the dialogue check as `dialogue_mismatch` (and trigger paid retries); for uses 1 and 2 it would produce wrong caption words. The app should route by project language rather than rely on "Parakeet detects it". (Strongly expected from the cited facts, but no direct Hindi test of v3 was found — see Gaps.)
- Parakeet-RNNT-1.1B Multilingual is the "stay on NVIDIA" option, but it is a heavyweight NIM (about 50 GB of GPU memory per the aggregator) with Riva gRPC, which is a different serving model from the current NeMo-style `/v1/parakeet/transcribe` endpoint.
- If the owner wants a Parakeet-family Hindi model served exactly like the current one, the practical route is fine-tuning `parakeet-tdt-0.6b-v3` on Hindi data (as amn-raw did), since the public Hindi fine-tunes found are private. That is a training project, not a drop-in.

### Gaps
- No published Hindi WER for Parakeet-RNNT-1.1B Multilingual was found, and it was not confirmed whether its Riva/NIM API returns word time offsets for Hindi.
- No first-hand test showing what `parakeet-tdt-0.6b-v3` outputs for Hindi audio was found; "garbage rather than error" is an inference. A 5-minute test on the owner's server would settle it.
- NIM licensing for self-hosted production (whether an NVIDIA AI Enterprise licence is needed) was not verified.
- `canary-1b-v2` language coverage was not checked in this session (from training knowledge, it covers the same 25 European languages as Parakeet v3, so no Hindi — unverified). The language list of "Nemotron Multilingual (31 languages)" was not found.
- No NVIDIA-published Hindi-specific NeMo Conformer/Parakeet checkpoint on Hugging Face was found in this session.

---

## 2. Open-source alternatives for Hindi ASR: accuracy, timestamps, licences

### Takeaway
Untuned Whisper is weak on Hindi (around 29–32% WER on FLEURS-hi for large-v3 and turbo); Hindi-fine-tuned Whisper models (IndicWhisper, ARTPARK `whisper-large-v3-vaani-hindi`) and AI4Bharat's IndicConformer (MIT) are in the 9–15% WER range on read-speech benchmarks. For timestamps, the strongest Hindi evidence (Oct 2026, hand-labelled boundaries) favours a Hindi wav2vec2 CTC model for alignment (WhisperX-style) over the NeMo Forced Aligner with IndicConformer. Meta Omnilingual ASR is Apache-2.0 with a very low Hindi CER, but word timestamps are only in an unmerged pull request.

### Cited Findings
**Whisper (OpenAI, MIT licence)**
- FLEURS Hindi test WER (leaderboard dated 2026.04): Whisper large-v3 **29.1**, turbo **32.1**, large-v2 33.7, medium 39.9, small 59; for comparison SeamlessM4T-v2 15.3, MMS-1B 19.8 — [SOTA2 leaderboard (aggregator; normalisation not stated)](https://www.sota2.com/research/sota/automatic-speech-recognition-on-fleurs-hindi-test)
- On the IndicVoices test set, Whisper scored 34.0 WER for Hindi vs 15.0 for AI4Bharat's IndicASR, 20.5 for Google USM, 27.2 Azure, 38.9 MMS — [IndicVoices paper, arXiv 2403.01926 (2024)](https://arxiv.org/html/2403.01926)
- In a Feb 2026 agricultural-domain benchmark, Whisper via the OpenAI API scored 46.8% Hindi WER (rank 7 of 10) — [arXiv 2602.03868](https://arxiv.org/html/2602.03868v2)
- Hallucination evidence on Hindi (Oct 2026): with a Hindi-fine-tuned Whisper, the ~30% of DISPLACE-M conversational segments shorter than 1 s had WER 121.4%, "largely due to the insertions" (sentence completions, repeated generations); **beam search increased WER** on every configuration because it favours longer, complete sentences; capping output length using a CTC head cut insertions (e.g. M3: 7.28% → 3.66%) — [arXiv 2610.08847](https://arxiv.org/abs/2610.08847)
- Whisper's own word timestamps come from cross-attention DTW, which is coarser than CTC alignment; WhisperX and CrisperWhisper "were developed for English and to the best of our knowledge, models capable of timestamped transcription are not available for Hindi" — [arXiv 2610.08847](https://arxiv.org/abs/2610.08847)
- Whisper's `BasicTextNormalizer` replaces every Unicode "Mark" character with a space, which deletes Devanagari matras and virama ("चाहिए" → "च ह ए"); an open PR (Sept 2026) says WER on that output is effectively character-level — [Sonex Labs blog](https://www.sonexlabs.com/blog/hindi-hinglish-speech-to-text-8khz-wer); same problem demonstrated in [Kavya Manohar's post](https://kavyamanohar.com/post/indic-normalizer/)

**Hindi-fine-tuned Whisper**
- IndicWhisper (Vistaar, AI4Bharat, Interspeech 2023 — older): Hindi WER Kathbath **10.3**, Kathbath-Hard 12.0, IndicTTS 7.6, MUCS 12.0, GramVaani 26.8, average 13.6. In the README's per-language table Hindi is CommonVoice 11.4 / FLEURS 15.0, but the model-comparison table shows FLEURS 11.4 / CommonVoice 15.0 — the two tables swap these columns, so one of them is mislabelled. Baselines on the same Hindi sets: Google STT avg 23.9, Azure STT 20.0, IndicWav2vec 21.0, NVIDIA medium 19.4, NVIDIA large 18.6 — [Vistaar README](https://github.com/AI4Bharat/vistaar/blob/master/README.md); [Vistaar paper](https://www.isca-archive.org/interspeech_2023/bhogale23_interspeech.pdf)
- `ARTPARK-IISc/whisper-large-v3-vaani-hindi` (fine-tuned on ~718 h): Kathbath **8.85**, Kathbath noisy 11.80, FLEURS **11.20**, CommonVoice 13.84, MUCS 14.60, GramVaani 25.11, Vaani 24.66 (self-reported) — [HF model card](https://huggingface.co/ARTPARK-IISc/whisper-large-v3-vaani-hindi)
- Fine-tuning Hindi-Whisper (vasista22 whisper-hindi-large-v2) on IndicVoices-R cut IndicVoices-R WER from 22.89 to ~14.4–14.9 and DISPLACE-M conversational WER from 67.34 to ~35.6–39.1 — [arXiv 2610.08847](https://arxiv.org/abs/2610.08847)
- Trelis "Tara" (Hindi model) measured itself and two commercial systems under one protocol (NFC + punctuation removal; nukta and vowel/nasal marks kept; clips ≤30 s): Vistaar Hindi mean WER Tara 12.06, Sarvam Saaras-v3 12.32, ElevenLabs Scribe-v2 13.79; IndicVoices-500 (spontaneous) 16.51 / 15.29 / 27.46 — [HF model card (self-published)](https://huggingface.co/Trelis/tara)

**WhisperX + Hindi wav2vec2 alignment (Oct 2026 Hindi study, 125 IndicVoices-R utterances, 3,784 hand-marked boundaries)**
- Forced alignment with a Hindi wav2vec2 CTC model (`theainerd/Wav2Vec2-large-xlsr-hindi`, XLSR-53 fine-tuned for Hindi) of the **ground-truth** text: mean boundary error **70.9 ms**, median 54.5 ms; systematic bias: starts **+36.4 ms late**, ends **−92.8 ms early**; after removing the constant offsets, mean 43.4 / median 30.3 ms. Inter-annotator agreement: 27.0 / 18.0 ms — [arXiv 2610.08847](https://arxiv.org/abs/2610.08847)
- NeMo Forced Aligner with the IndicConformer Hindi CTC model, same ground truth: mean **79.5 ms**, median 62.0; calibrated 52.1 / 39.6 — worse than wav2vec2 — [arXiv 2610.08847](https://arxiv.org/abs/2610.08847)
- WhisperX (Hindi-Whisper transcript + wav2vec2 alignment) against manual boundaries: **71.0 ms** mean error; a Hindi adaptation of CrisperWhisper (attention DTW) deviated far more (107.2 ms mean, only 40.4% of boundaries within 50 ms vs ~93% for CTC methods) — [arXiv 2610.08847](https://arxiv.org/abs/2610.08847)
- The paper's own approach (a 93.5K-parameter character-level CTC head with 71 Devanagari characters + space + blank on the Whisper encoder) matches WhisperX timing within 10 ms without a second model; code, models and annotations are linked from a demo page; the paper is CC BY-NC-ND (model licences not stated in the text) — [arXiv 2610.08847](https://arxiv.org/abs/2610.08847)
- Devanagari BPE tokens in Whisper average only 0.77 characters on the test transcripts, so token boundaries are irregular for timing — [arXiv 2610.08847](https://arxiv.org/abs/2610.08847)

**AI4Bharat IndicConformer (MIT)**
- `ai4bharat/indic-conformer-600m-multilingual`: 600M, hybrid CTC + RNNT, 22 Indian languages, **MIT licence**, loaded via `transformers` with `trust_remote_code=True` and ONNX runtime; called as `model(wav, "hi", "ctc")` or `"rnnt"` (language is passed explicitly); Vaani-Benchmark-V1.0 Hindi WER **13.2**. The card now says: "Indic-Transcribe is now available. It supports 25 Indian languages and has better transcription quality compared to IndicConformer. We recommend using Indic-Transcribe." — [HF model card](https://huggingface.co/ai4bharat/indic-conformer-600m-multilingual)
- A community GGUF port self-reports Kathbath-hi 13.5 WER / 5.2 CER and FLEURS-hi 15.2 WER / 5.9 CER — [Singla0009/IndicConformer-GGUF](https://huggingface.co/Singla0009/IndicConformer-GGUF); a 100-sample Kathbath-valid test gave 7.65% Hindi WER (author warns it is a lightweight benchmark) — [GitHub benchmark](https://github.com/Mohanaspiringcoder/indicconformer-asr-benchmark)
- IndicASR (the IndicVoices model family) Hindi WER on IndicVoices: 15.0 — [arXiv 2403.01926](https://arxiv.org/html/2403.01926)
- In the agricultural benchmark (domain-specific, Feb 2026), the "AI4Bharat" entry scored 59.8% Hindi WER (last of 10) — which model/version was not specified in the excerpt — [arXiv 2602.03868](https://arxiv.org/html/2602.03868v2)

**Meta MMS and Omnilingual ASR**
- Omnilingual ASR: code and models **Apache 2.0**; 7B LLM-ASR Hindi (`hin_Deva`) CER **3.6** with 236.7 training hours; LLM models accept an optional language code — [GitHub repo](https://github.com/facebookresearch/omnilingual-asr); [per-language CSV](https://github.com/facebookresearch/omnilingual-asr/blob/main/per_language_results_table_7B_llm_asr.csv)
- Word/character timestamps for Omnilingual (CTC emission frames; cross-attention DTW for LLM models) exist only in an **open, unmerged community PR** (#22, last updated 3 Jun 2026) — [PR #22](https://github.com/facebookresearch/omnilingual-asr/pull/22/files)
- MMS (Meta) Hindi: 38.9 WER on IndicVoices — [arXiv 2403.01926](https://arxiv.org/html/2403.01926); 51.4% on the agricultural set — [arXiv 2602.03868](https://arxiv.org/html/2602.03868v2); MMS-1B 19.8 on FLEURS-hi — [SOTA2](https://www.sota2.com/research/sota/automatic-speech-recognition-on-fleurs-hindi-test)

### Inferences
- For a self-hosted Hindi ASR with permissive licensing, IndicConformer (MIT) or a Hindi-fine-tuned Whisper are the most defensible choices; untuned Whisper large-v3/turbo should not be used for Hindi checks given ~30% WER and insertion-type hallucinations on short clips (H3 dialogue clips are short).
- Because the dialogue check runs on short clips, a CTC or transducer model (IndicConformer, Parakeet-family) is structurally safer than Whisper, which tends to "complete" short segments; if Whisper is used, use greedy decoding (beam search made things worse in the Hindi study).
- WhisperX's architecture (ASR words → Hindi wav2vec2 CTC alignment) is the best-evidenced self-hosted way to get Hindi word timestamps when the text is not known exactly.

### Gaps
- No Hindi WER numbers or licence for AI4Bharat's newer "Indic-Transcribe" were gathered.
- Licences of `ARTPARK-IISc/whisper-large-v3-vaani-hindi`, IndicWhisper checkpoints, `theainerd/Wav2Vec2-large-xlsr-hindi` and the Trelis models were not verified.
- Whether WhisperX's built-in default alignment model for `hi` is `theainerd/Wav2Vec2-large-xlsr-hindi` was not verified in this session (believed so from older knowledge).
- No Common Voice-hi or Kathbath numbers for untuned Whisper large-v3-turbo were found; FLEURS numbers come from an aggregator with unstated normalisation.
- No Hindi WER for faster-whisper specifically (it is a reimplementation of the same Whisper weights, so accuracy should match Whisper — inference).

---

## 3. Forced alignment when the text is already known (uses 1 and largely 2)

### Takeaway
For Hindi there is exactly one study with human-marked word boundaries (Oct 2026): CTC forced alignment with a Hindi wav2vec2 model gave ~71 ms mean error (43 ms after a constant-offset correction), better than the NeMo Forced Aligner with IndicConformer (~80 ms); no Hindi boundary benchmark exists for MMS_FA, ctc-forced-aligner, MFA or aeneas. All CTC aligners place word **starts late and ends early**, which matters for splicing. MMS_FA (torchaudio / ctc-forced-aligner) needs uroman romanisation and its weights are **CC-BY-NC 4.0 (non-commercial)**.

### Cited Findings
**Hindi-specific evidence**
- Hindi raw/calibrated mean boundary error vs human labels: wav2vec2 Hindi CTC 70.9 / 43.4 ms; NFA + IndicConformer 79.5 / 52.1 ms; inter-annotator 27.0 ms. Bias of wav2vec2: onset +36.4 ms, offset −92.8 ms (NFA: +41.2 / −102.2). The authors note CTC's "sharp frame level posteriors" predict characters before the true end, introducing a systematic bias — [arXiv 2610.08847](https://arxiv.org/abs/2610.08847)
- The test set itself was filtered to utterances the wav2vec2 aligner could align with per-word confidence ≥0.30 (median 0.45), which may favour that aligner — [arXiv 2610.08847](https://arxiv.org/abs/2610.08847)

**General (English) aligner evidence, 2026**
- Survey of 72 systems: "no system we found, open or commercial, publishes the timing accuracy of its word boundaries in Malay, Indonesian or Tamil"; MMS alignments "were judged only through downstream error rates, never against boundaries"; ctc-forced-aligner wraps the same MMS checkpoint as torchaudio and "inserts the star before every word by default" — [arXiv 2610.17782](https://arxiv.org/html/2610.17782)
- Why CTC aligners are biased: with MMS-300M on TIMIT, a median 67% of frames inside a word are blank; first character frame falls a median **33 ms after** the human start and the last ends a median **26 ms before** the human end — [arXiv 2610.17782](https://arxiv.org/html/2610.17782)
- Decoder choice matters as much as the model: four decoders on the same MMS emissions ranged 29.2–46.8 ms MAE on clean TIMIT; ctc-forced-aligner's default (star before every word) was the worst and padded the **last word to end a median 135 ms late**; "star only at the edges" was the best MMS decoder (29.2 ms). MFA (english_us_arpa) was most precise at 19.1 ms with 68.2% of boundaries within 20 ms; Qwen3-ForcedAligner 30.1 ms (covers 11 languages; Malay/Indonesian/Tamil not among them); stable-ts on Whisper large-v3-turbo least precise at 77.5 ms — [arXiv 2610.17782](https://arxiv.org/html/2610.17782)
- MFA "run per language over FLEURS ... fails on about a fifth of the utterances" (citing Akavarapu et al., 2026); MFA needs a dictionary and acoustic model per language — [arXiv 2610.17782](https://arxiv.org/html/2610.17782)
- Nyra speech timing benchmark (English only: Buckeye, FluencyBank, TIMIT; created Jun 2026), Buckeye MAE: MFA wide beam 35.7 ms, Qwen FA 39.4, ElevenLabs "Cue" forced aligner 50.8, `mms_fa` 52.7 (only 15.2% within 25 ms), ctc_segmentation 81.0, NeMo FA 72.6, WhisperX 89.8, Deepgram Nova-3 87.6, NVIDIA Canary 107.2 — [nyra benchmark](https://github.com/nyrahealth/nyra_speech_timing_benchmark)

**torchaudio MMS_FA**
- MMS_FA: trained on 31K hours in 1,130 languages; published "under [CC-BY-NC 4.0 License]"; has no word-boundary token, so post-processing differs — [torchaudio 2.10 docs](https://docs.pytorch.org/audio/2.10.0/generated/torchaudio.pipelines.MMS_FA.html)
- Status: `forced_align` was deprecated in torchaudio 2.8 and slated for removal in 2.9, but TorchAudio **2.10 (Jan 2026) preserved** `forced_align` (with `lfilter`, `RNNTLoss`, `CUCT`, `overdrive`); torchaudio is in maintenance mode with "No new features" — [TorchAudio 2.10 release](https://github.com/pytorch/audio/releases/tag/v2.10.0); [issue #3902](https://github.com/pytorch/audio/issues/3902). The 2.10 multilingual tutorial page still carries the old "will be removed in 2.9" warning (stale) — [tutorial source](https://docs.pytorch.org/audio/2.10.0/_sources/tutorials/forced_alignment_for_multilingual_data_tutorial.rst.txt)
- Input handling: the transcript must be romanised with uroman, lower-cased and reduced to `[a-z' ]`; digits not romanised by uroman are **deleted** ("To avoid this, one needs to romanize numbers, but this is known to be a non-trivial task") — [torchaudio tutorial](https://docs.pytorch.org/audio/2.10.0/_sources/tutorials/forced_alignment_for_multilingual_data_tutorial.rst.txt)
- Hugging Face MMS docs: for non-Roman scripts "such as Arabic, Mandarin or Hindi, the `uroman` perl package is required" — [HF MMS docs](https://huggingface.co/docs/transformers/model_doc/mms)
- A third-party port of uroman's romanisation data notes accuracy "tracks uroman's own accuracy for that language" — [arham-sayyed/mms-forced-align](https://github.com/arham-sayyed/mms-forced-align)

**NeMo Forced Aligner (NFA)**
- NFA runs Viterbi on the CTC log-probabilities of NeMo models — [arXiv 2610.17782](https://arxiv.org/html/2610.17782); it worked with `ai4bharat/indicconformer_stt_hi_hybrid_ctc_rnnt_large` on Hindi (Devanagari text input, no romanisation) at 79.5 ms mean error — [arXiv 2610.08847](https://arxiv.org/abs/2610.08847)

**Montreal Forced Aligner (MFA)**
- MFA ships a Hindi pronunciation dictionary `hindi_cv` v2.0.0 (Vox Communis; Epitran phone set; 11,113 words; "intended for forced alignment of Hindi transcripts"; it "was used in training the Hindi Epitran acoustic model"). Licence is shown as CC-0 on the dictionary page but CC BY 4.0 in the dictionary list (conflict) — [MFA Hindi dictionary page](https://mfa-models.readthedocs.io/en/latest/dictionary/Hindi/Hindi%20CV%20dictionary%20v2_0_0.html); [MFA dictionary list](https://mfa-models.readthedocs.io/en/latest/dictionary/)
- Out-of-dictionary words need pronunciations; each phone has a 10 ms minimum duration, so heavily reduced pronunciations cause errors on neighbouring words — [MFA Hindi dictionary page](https://mfa-models.readthedocs.io/en/latest/dictionary/Hindi/Hindi%20CV%20dictionary%20v2_0_0.html)
- A search of the MFA acoustic-model catalogue did not show a Hindi acoustic model (the fetched listing was truncated, so this is not fully verified) — [MFA acoustic models](https://mfa-models.readthedocs.io/en/latest/acoustic/)

**Hosted aligner**
- ElevenLabs Forced Alignment API takes audio + text and returns word timings; its multilingual v2 models support 29 languages **including Hindi** — [ElevenLabs docs](https://elevenlabs.io/docs/overview/capabilities/forced-alignment.mdx). Its English accuracy in the nyra benchmark ("Cue"): 50.8 ms MAE, 7.5% within 25 ms — [nyra benchmark](https://github.com/nyrahealth/nyra_speech_timing_benchmark)

### Inferences
- **Best self-hosted aligner for Hindi today, on the evidence:** a Hindi Devanagari-character wav2vec2 CTC model plus `torchaudio.functional.forced_align` (or WhisperX's alignment step), with no romanisation step. It is also the only option with measured Hindi boundaries. NFA + IndicConformer (MIT) is a close second and fits a NeMo-based GPU server.
- MMS_FA / ctc-forced-aligner is convenient (one model, all languages), but adds a uroman step that loses Devanagari distinctions, drops digits, has no Hindi boundary evidence, and is CC-BY-NC — a problem if Visio Studio is ever used commercially.
- MFA could be the most precise (it is in English) but for Hindi it needs a dictionary entry for every word (11k words is small; TTS/story vocabulary will include names and English loanwords) and a Hindi acoustic model that may have to be trained; not a quick option.
- aeneas was not researched in this session; from older knowledge it uses TTS + DTW and is designed for sentence/fragment-level sync, so it is unlikely to beat CTC aligners at word level (unverified).
- **Practical correction for splicing (use 2):** since CTC aligners end words ~93–102 ms early on Hindi and start ~36–41 ms late, cutting exactly at an aligner's `end` will clip word tails. Cut in the middle of the gap between one word's end and the next word's start, or apply a measured offset (e.g. extend ends ~90 ms and move starts ~35 ms earlier, capped by the neighbour), and re-check on the owner's own recordings.
- **Text preparation for alignment:** numerals in the script (`25`, `२५`, `2026`) must be expanded into the Hindi words the speaker or TTS actually said before alignment, while keeping a mapping from aligned tokens back to the displayed words for captions. Danda and other punctuation should be stripped from the alignment text but kept in the caption text.
- For use 2 (speaker may deviate), plain forced alignment of the script will force deviating audio onto script words. A wildcard/"star" token at the edges (not before every word) absorbs extra audio at the edges only; for real deviations an ASR-first approach is safer (see section 7).

### Gaps
- No Hindi boundary-accuracy numbers for MMS_FA, ctc-forced-aligner, MFA, Qwen3-ForcedAligner, the Scicom Whisper aligners (87 languages; whether Hindi is included was not checked) or ElevenLabs forced alignment.
- How uroman romanises Hindi nukta letters, chandrabindu/anusvara and conjuncts was not documented in the sources found.
- Whether an official MFA Hindi acoustic model exists could not be fully confirmed.
- Licence of `theainerd/Wav2Vec2-large-xlsr-hindi` was not verified.

---

## 4. Commercial APIs with Hindi word timestamps: support, accuracy, price

### Takeaway
ElevenLabs Scribe, Deepgram Nova-3, AWS Transcribe and Azure all list Hindi; ElevenLabs and Deepgram document per-word start/end times. **Sarvam (Saaras v4), the Indic specialist with the best spontaneous-Hindi accuracy in the one same-protocol comparison, does not return word-level timestamps per its API docs** (its marketing page says it does — conflicting). Google's Chirp 3 page contradicts itself on word timestamps. Independent accuracy evidence is thin and mostly vendor-run.

### Cited Findings
**Sarvam (Saaras v4 / Saarika)**
- REST `POST https://api.sarvam.ai/speech-to-text`, `model=saaras:v4` (default; 22 Indic languages + English), modes `transcribe`, `translate`, `verbatim`, `translit`, `codemix`; `language_code=hi-IN` or `unknown` (auto-detect); `keyterms` up to 50 biasing terms; REST is for audio under 30 s — [Sarvam API reference](https://docs.sarvam.ai/api-reference/speech-to-text/transcribe)
- `with_timestamps=true` gives chunk-level timestamps: "each entry covers a sentence or phrase, not an individual word. Note: Word-level timestamps are not supported." — [Sarvam API reference](https://docs.sarvam.ai/api-reference/speech-to-text/transcribe); the Batch API (up to 2 h per file) also returns "Chunk-level timestamps only (not word-level)" — [Sarvam Batch docs](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/batch-api)
- **Conflict:** Sarvam's marketing page says "All modes include word-level timestamps" and that `response.words` holds word-level timestamps — [sarvam.ai/speech-to-text](https://www.sarvam.ai/speech-to-text). The API docs are more specific and should be trusted until tested.
- Saarika v2.5 is being deprecated in favour of Saaras v4 `mode="transcribe"` — [Saarika docs](https://docs.sarvam.ai/api/getting-started/models/saarika)
- Price: ₹0.49/min pay-as-you-go (₹0.45 Pro, ₹0.41 Growth, ₹0.38 Business); batch with diarisation ₹0.59/min; ₹100 free credit — [Sarvam pricing](https://www.sarvam.ai/api-pricing); [sarvam.ai/speech-to-text](https://www.sarvam.ai/speech-to-text)
- Accuracy: same-protocol test by Trelis: Saaras-v3 Vistaar-Hindi mean 12.32 WER, IndicVoices-500 15.29 (best of the three systems tested on spontaneous speech) — [Trelis/tara](https://huggingface.co/Trelis/tara). A vendor test (Oct 2026): Saaras v4 Kathbath 5.8% WER, Hindi phone calls 21.6% — [miraiminds comparison (competitor)](https://voice.miraiminds.co/guides/hindi-speech-to-text-api-comparison). In the 60dB benchmark (vendor columns taken from dataset authors' precomputed results, not re-run) Sarvam scored 22.16% overall — [60dB benchmark](https://60db.ai/benchmarks/hindi-asr). Agricultural domain: 28.7% — [arXiv 2602.03868](https://arxiv.org/html/2602.03868v2)

**Google Cloud Speech-to-Text (Chirp 2 / Chirp 3)**
- Chirp 3 lists Hindi (hi-IN) as GA in Speech-to-Text V2 — [Chirp 3 docs](https://docs.cloud.google.com/speech-to-text/docs/models/chirp-3)
- **Internal contradiction:** the same page puts "Word-level timestamps" under "Chirp 3 doesn't support the following features", but describes it as "can be optionally enabled, which some transcription degradation is expected. Available only in Speech.Recognize and Speech.BatchRecognize"; its method table says BatchRecognize is "up to 20 minutes with word-level timestamp enabled", and it includes a code sample `transcribe_sync_chirp3_with_timestamps` "which provides word-level timestamps" — [Chirp 3 docs](https://docs.cloud.google.com/speech-to-text/docs/models/chirp-3). A third-party comparison says Chirp 2 offers word timestamps and Chirp 3 lists them as unsupported — [synthorai](https://synthorai.io/compare/models/chirp-2-vs-chirp-3/)
- Google describes word time offsets as "an experimental feature and the accuracy of the time offset can vary" (v1 API reference) — [Google WordInfo](https://docs.cloud.google.com/speech-to-text/docs/reference/rest/v1/speech/recognize)
- Price (aggregator, Oct 2026): V2 standard $0.016/min for the first 500,000 min/month; dynamic batch $0.003/min; hi-IN on chirp_3 (us, eu regions), chirp_2 and telephony models — [miraiminds comparison](https://voice.miraiminds.co/guides/hindi-speech-to-text-api-comparison)
- Accuracy: agricultural Hindi: Google STT 16.2% (rank 1), Chirp 3 30.0% — [arXiv 2602.03868](https://arxiv.org/html/2602.03868v2); Vistaar (2023, older): Google STT Hindi avg 23.9 — [Vistaar](https://github.com/AI4Bharat/vistaar/blob/master/README.md); Deepgram's own 20-language aggregate (Hindi not separated) ranks Chirp 3 at 18.50 WER — [Deepgram benchmarks (vendor)](https://deepgram.com/benchmarks)

**Azure Speech**
- hi-IN listed including fast transcription; real-time $1/h, fast $0.36/h, batch $0.18/h (aggregator) — [miraiminds comparison](https://voice.miraiminds.co/guides/hindi-speech-to-text-api-comparison)
- Accuracy: Azure Hindi 27.2 WER on IndicVoices — [arXiv 2403.01926](https://arxiv.org/html/2403.01926); Vistaar (2023): Azure Hindi avg 20.0 (Kathbath 13.6, FLEURS 24.3) — [Vistaar](https://github.com/AI4Bharat/vistaar/blob/master/README.md); agricultural: 25.6% — [arXiv 2602.03868](https://arxiv.org/html/2602.03868v2)

**AWS Transcribe**
- Hindi (hi-IN) batch and streaming; "US East examples: streaming $0.01 a minute, batch $0.006; tiered and varies by region" (aggregator; verify against AWS pricing) — [miraiminds comparison](https://voice.miraiminds.co/guides/hindi-speech-to-text-api-comparison)

**Deepgram Nova-3**
- Nova-3 supports Hindi (`hi`) both in the multilingual (code-switching) model and as a monolingual language — [Deepgram models & languages](https://developers.deepgram.com/docs/models-languages-overview/)
- Response `words[]` include `word`, `start`, `end` (seconds), `confidence`, `punctuated_word` — [SLNG-hosted Deepgram Nova-3 Hindi schema](https://docs.slng.ai/api-reference/speech-to-text/slng/deepgram-nova-3/nova-3-hindi-websocket)
- Price (aggregator): pre-recorded $0.0043/min (multilingual $0.0052) — [miraiminds comparison](https://voice.miraiminds.co/guides/hindi-speech-to-text-api-comparison)
- Accuracy: 60dB benchmark Deepgram 20.69% Hindi overall — [60dB](https://60db.ai/benchmarks/hindi-asr); Deepgram's own (vendor) 20-language aggregate 13.78 WER vs ElevenLabs Scribe 16.33 — [Deepgram benchmarks](https://deepgram.com/benchmarks). English timing accuracy: 87.6 ms MAE in nyra — [nyra](https://github.com/nyrahealth/nyra_speech_timing_benchmark)

**ElevenLabs Scribe**
- Current docs: "Use Scribe v3 for recorded audio and Scribe v3 Live for real-time"; "Precise word-level timestamps"; Scribe v3 claims "27% fewer word errors than Scribe v2 on FLEURS"; Hindi is in Scribe v2's "High Accuracy (>5% to ≤10% WER)" band (vendor-published) — [ElevenLabs STT docs](https://elevenlabs.io/docs/overview/capabilities/speech-to-text)
- Independent-ish: Trelis same-protocol Scribe-v2 Vistaar-Hindi mean 13.79, but IndicVoices-500 spontaneous **27.46** — [Trelis/tara](https://huggingface.co/Trelis/tara); 60dB (dataset vendor columns) 15.74% overall — [60dB](https://60db.ai/benchmarks/hindi-asr)
- Price (aggregator): Scribe v2 $0.22/h, Scribe v2 Realtime $0.39/h — [miraiminds comparison](https://voice.miraiminds.co/guides/hindi-speech-to-text-api-comparison)
- ElevenLabs also offers a Forced Alignment API that supports Hindi (see section 3) — [ElevenLabs FA docs](https://elevenlabs.io/docs/overview/capabilities/forced-alignment.mdx)

**AssemblyAI**
- Sync STT word timestamps: `timestamps: true` gives per-word start/end in ms; "Timings are exact or absent, never approximate"; "Timestamp accuracy is best for English audio" — [AssemblyAI word timestamps](https://www.assemblyai.com/docs/sync-stt/word-timestamps)
- Deepgram's (vendor) aggregate ranks AssemblyAI Universal at 22.97 WER across 20 languages — [Deepgram benchmarks](https://deepgram.com/benchmarks)

**Gemini**
- Gemini 2.5 Pro (best-speaker variant) scored 18.5% Hindi WER on agricultural audio (rank 3) — [arXiv 2602.03868](https://arxiv.org/html/2602.03868v2)

**OpenAI hosted**
- gpt-transcribe $0.0045/min, gpt-4o-transcribe $0.006, gpt-4o-mini-transcribe $0.003 (aggregator, "estimated") — [miraiminds comparison](https://voice.miraiminds.co/guides/hindi-speech-to-text-api-comparison)

### Inferences
- For use 3 (dialogue check needs words, and the SCN-009 line windows need per-word times), Sarvam's chunk-level timestamps are not enough unless the windows logic falls back to whole-clip comparison; ElevenLabs Scribe or Deepgram Nova-3 are the hosted options that return word times with Hindi.
- Given that every independent Hindi comparison found is either vendor-run or domain-specific, a small in-house test set (20–50 H3 Hindi clips and recordings with known text) is the only reliable way to choose between hosted options.
- Hosted APIs conflict with the "self-hosted" character of the app and send user voice recordings to third parties; this is a product decision, not a technical one.

### Gaps
- Azure and AWS Hindi word-timestamp support was not confirmed from their own docs in this session (both generally return word-level offsets — older knowledge, unverified for hi-IN).
- AssemblyAI's Hindi support and model name were not confirmed from primary docs.
- Gemini's word-timestamp capability and accuracy for Hindi were not researched (LLM-produced timestamps are generally unreliable — older knowledge, unverified).
- Official price pages of Google, Azure, AWS, Deepgram and ElevenLabs were not fetched; prices above come from one aggregator (Oct 2026) and Deepgram's streaming price was marked "limited-time".
- No Hindi word-boundary accuracy numbers exist for any commercial API.

---

## 5. Matching Hindi transcripts against intended text (dialogue check): normalisation, scripts, libraries, CER vs WER

### Takeaway
The current `normalize_words` is mostly Hindi-safe (it keeps matras/virama, NFKC unifies the two nukta encodings, the danda becomes a space), but a local test shows three gaps: zero-width joiners split words, Devanagari digits never equal ASCII digits, and chandrabindu/anusvara (and nukta/no-nukta) spelling variants count as different words. English-only matching steps (numbers, spelling, homophones, fillers) need Hindi counterparts, and English words may come back in Latin or Devanagari script, which can swing WER by large amounts. Use a Hindi-safe normaliser (indic-nlp-library or similar) and add a character-level similarity for Hindi.

### Cited Findings
**What the current code does with Hindi (local test, 18 Nov 2026, `normalize_words` in [dialogue_check.py](backend/app/services/dialogue_check.py))**
- `मैं घर जा रहा हूँ। ठीक है॥` → `['मैं','घर','जा','रहा','हूँ','ठीक','है']` (danda and double danda handled; matras and chandrabindu kept).
- Precomposed nukta `ज़` (U+095B) and decomposed `ज`+`़` give the same word (NFKC decomposes U+095B).
- `क्\u200dष` and `क्\u200cष` (ZWJ / ZWNJ inside a word) → `['क्','ष']` — **the word is split in two**.
- `५` stays `५` after NFKC and does not match `5`.
- `हाँ` (chandrabindu) ≠ `हां` (anusvara).
- `मेरा Phone नंबर` → `['मेरा','phone','नंबर']` (Latin is casefolded; Devanagari unaffected).
- The later matching steps are English-only: `FILLERS` is `ah, eh, er, hm, ... um, oh`; `fold_numbers` handles English number words; UK→US spelling; English homophones — [dialogue_matching.py](backend/app/services/dialogue_matching.py)

**Normalisation guidance and libraries**
- indic-nlp-library `DevanagariNormalizer(lang='hi', remove_nuktas=False, nasals_mode='do_nothing', do_normalize_chandras=False, do_normalize_vowel_ending=False)`: replaces nukta composites with decomposed form, `|` → poorna virama (danda), colon → visarga after a Devanagari letter; the base class removes BOM/word joiner and **ZWJ/ZWNJ**, and turns ZWSP/NBSP into spaces — [indic-nlp-library docs](https://indic-nlp-library.readthedocs.io/en/latest/indicnlp.normalize.html); also handles "multiple representations of two part dependent vowel signs" — [Indic NLP Library](https://anoopkunchukuttan.github.io/indic_nlp_library/)
- `hindi-normalize` (community, stdlib-only): lossless defaults strip invisibles, NFC, Devanagari digits → ASCII, danda fixes; opt-in lossy folds `remove_nukta` (`क़`→`क`), nasals to anusvara (`हिन्दी`→`हिंदी`), `chandrabindu` (`ँ`→`ं`), visarga; converts Hindi number words to digits tolerant of ASR spelling variants (`पाँच/पांच/पाच`) without summing adjacent numbers (`दो तीन दिन` → `2 3 दिन`) — [GitHub hindi-normalize](https://github.com/Tushar-9802/hindi-normalize)
- A Hindi-safe WER normaliser should remove punctuation only, keep vowel signs, and may fold nukta and chandrabindu→anusvara because they are "not recognition errors"; numbers can be correctly written `500`, `५००` or `पांच सौ`, so pick one form and convert before scoring — [Sonex Labs](https://www.sonexlabs.com/blog/hindi-hinglish-speech-to-text-8khz-wer)
- Script of English words changes the score: the same hypothesis scored **17% WER** against an all-Devanagari reference (`अपॉइंटमेंट`) and **0%** against a mixed-script reference (`appointment`) — [Sonex Labs](https://www.sonexlabs.com/blog/hindi-hinglish-speech-to-text-8khz-wer)
- Output conventions vary by system: Sarvam `transcribe` mode gives `मेरा फोन नंबर है 9840950950`, `codemix` gives `मेरा phone number है 9840950950`, `verbatim` spells digits as words — [Sarvam API reference](https://docs.sarvam.ai/api-reference/speech-to-text/transcribe); parakeet-indic writes English words "usually in lowercase Latin (`payment`, `account`), sometimes in the native script", and numbers as digits for Hindi — [amn-raw/parakeet-indic-v1](https://huggingface.co/amn-raw/parakeet-indic-v1)
- Evaluation practice in 2026 Hindi work: NFC, zero-width removed, punctuation removed, Latin lowercased, all-script digits → 0-9, number words → digits, vowel signs kept — [amn-raw/parakeet-indic-v1](https://huggingface.co/amn-raw/parakeet-indic-v1); CER computed over Devanagari **grapheme clusters** (base + combining marks + conjuncts) — [arXiv 2610.08847](https://arxiv.org/abs/2610.08847)
- CER is consistently much lower than WER for Hindi (e.g. IndicConformer GGUF Kathbath 13.5 WER vs 5.2 CER; parakeet-hi-v3 FLEURS 12.37 vs 4.24) — [IndicConformer-GGUF](https://huggingface.co/Singla0009/IndicConformer-GGUF); [parakeet-indic-v1](https://huggingface.co/amn-raw/parakeet-indic-v1)

### Inferences
- Minimal Hindi additions to the dialogue check: (a) strip ZWJ/ZWNJ/ZWSP before splitting; (b) map Devanagari digits to ASCII; (c) a Hindi "spelling" step that folds nukta, chandrabindu→anusvara and nasal-consonant+virama clusters→anusvara on both sides; (d) a Hindi number-word step (`पच्चीस` ↔ `25`); (e) Hindi fillers (e.g. `अं`, `हम्म`) — the exact list needs native review; (f) a Latin↔Devanagari fold for English loanwords, e.g. by transliterating Latin-script words in the transcript to Devanagari (or both sides to a romanisation) before comparing.
- Because one wrong matra makes a whole Hindi word "wrong", a word-level `SequenceMatcher` ratio is harsh; adding a character-level (grapheme-cluster) similarity as a fallback step, with its own threshold, would reduce false failures. The existing step-by-step "pass at the first step that reaches the threshold" design fits this.
- Use 3 should store the language with each check so that a stored English-normalised result is not reused for a Hindi take.

### Gaps
- IndicXlit (AI4Bharat neural transliteration) and `indic-transliteration` (rule-based scheme conversion) were not researched in this session; from older knowledge, IndicXlit can transliterate English words in Latin script into Devanagari (needed for the loanword fold), while `indic-transliteration` converts between romanisation schemes and Indic scripts but does not handle English spelling — unverified, and licences not checked.
- No published study on the right similarity threshold for Hindi dialogue verification was found.
- A validated list of Hindi filler sounds for ASR output was not found.

---

## 6. Hinglish (code-mixed Hindi-English) audio

### Takeaway
Hinglish is common and hurts monolingual models (≈30–50% relative WER increase reported); systems with an explicit code-mix output mode are Sarvam (`codemix`), Deepgram Nova-3 multilingual and the open Trelis `whisper-hinglish-preview`; ElevenLabs Scribe v2 is reported to be strong on code-switch sets. The main practical issue for Visio Studio is script: whether English words come back in Latin or Devanagari, which the comparison step must fold.

### Cited Findings
- "Recent evaluations have shown that ASR models experience a relative increase in WER of 30–50% when exposed to code-switched speech"; models trained on monolingual data underperform by ~42% WER on the HiACC test set (5.24 h, 3,318 adult + 1,858 child segments; Devanagari for Hindi, Latin for English) — [HiACC paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC12329218/)
- Sarvam `codemix` mode: "English words in English and Indic words in native script" — [Sarvam API reference](https://docs.sarvam.ai/api-reference/speech-to-text/transcribe)
- Deepgram Nova-3 multilingual mode covers Hindi with English (code-switching) — [Deepgram models](https://developers.deepgram.com/docs/models-languages-overview/); [miraiminds comparison](https://voice.miraiminds.co/guides/hindi-speech-to-text-api-comparison)
- Trelis `whisper-hinglish-preview` (open weights, built on ARTPARK's Vaani Whisper) uses a `<|mixedcode|>` token to output Devanagari Hindi + Roman English; reported to approach Sarvam and Scribe V2 on the Koshi benchmark, beat Sarvam's code-mix mode but trail Scribe V2 on "Code Switch FLIR", and beat both on HiACC adult and child sets (self-reported) — [Trelis Substack](https://trelis.substack.com/p/whisper-hinglish)
- Benchmarks: CoSHE-Eval (Soket AI; 1,985 samples, ~30 h; Devanagari for Hindi, Latin for English; guideline converts English-origin words written in Devanagari, e.g. `कंप्यूटर`, to `computer`) — [Soket AI blog](https://soket.ai/blogs/coshe_eval); Gnani Hinglish telephony benchmark (1,536 utterances, 2.5 h, fully romanised transcripts) — [HF dataset](https://huggingface.co/datasets/gnani/asr-verbatim-benchmark); Sarvam + AI4Bharat Indic DiarBench (~108 h, 22 languages; English words in Roman script, Arabic numerals) — [Moneycontrol](https://www.moneycontrol.com/technology/sarvam-ai-introduces-indic-diarbench-to-evaluate-speech-recognition-and-speaker-attribution-across-22-indian-languages-article-14001942.html)
- Vendor claim: mirai minds' Mira STT is "built for Hindi and Hinglish phone calls" (18.3% vs Saaras v4 21.6% on Hindi phone calls; Saaras better on clean read speech) — [miraiminds comparison (vendor)](https://voice.miraiminds.co/guides/hindi-speech-to-text-api-comparison)
- parakeet-indic (community) handles mixed-language recordings piece by piece with predicted language tags and writes English words mostly in Latin — [amn-raw/parakeet-indic-v1](https://huggingface.co/amn-raw/parakeet-indic-v1)

### Inferences
- For Visio Studio, Hinglish matters mainly for use 2 (users' own voice) and use 3 (H3 dialogue written in Hinglish). The intended text's script convention (e.g. script writers typing `phone` vs `फ़ोन`) will rarely match the ASR's choice, so a script fold in the comparison is more important than the choice of ASR.
- For alignment (uses 1–2), a Devanagari-only Hindi CTC model cannot spell Latin-script English words; those words must be transliterated to Devanagari in the alignment text (or a romanising aligner like MMS_FA used). This is a reason MMS_FA's uroman route can be convenient for Hinglish despite its other drawbacks.

### Gaps
- No independent, same-protocol Hinglish WER comparison across IndicConformer, Whisper, Sarvam, ElevenLabs and Deepgram was found; the Trelis results are self-reported and the Koshi / Code Switch FLIR benchmarks were not inspected.
- No Hinglish forced-alignment accuracy study was found.

---

## 7. Recommended approach for each of the three uses (ASR vs forced alignment vs both)

### Takeaway
Use **forced alignment** where the text is known and trusted (use 1), **ASR followed by alignment** where the speaker may deviate (use 2), and **ASR only** for verification (use 3) — forced alignment cannot be used for the dialogue check, because it always "finds" the expected words. A self-hosted stack that covers all three is: a Hindi ASR (IndicConformer, MIT, or a Hindi-fine-tuned Whisper) + a Hindi Devanagari CTC aligner (wav2vec2 Hindi, or NFA with IndicConformer CTC), routed by project language instead of sending Hindi to the current Parakeet v3.

### Cited Findings
- Hindi alignment accuracy with known text: wav2vec2 Hindi CTC 70.9 ms mean (43.4 calibrated), NFA + IndicConformer 79.5 ms (52.1 calibrated); systematic late starts / early ends — [arXiv 2610.08847](https://arxiv.org/abs/2610.08847)
- WhisperX-style ASR + CTC alignment on Hindi: 71.0 ms mean boundary error with system-generated transcripts — [arXiv 2610.08847](https://arxiv.org/abs/2610.08847)
- Hindi ASR candidates and evidence: IndicConformer MIT, Vaani-hi 13.2 WER — [HF](https://huggingface.co/ai4bharat/indic-conformer-600m-multilingual); whisper-large-v3-vaani-hindi Kathbath 8.85 / FLEURS 11.20 — [HF](https://huggingface.co/ARTPARK-IISc/whisper-large-v3-vaani-hindi); untuned Whisper large-v3 29.1 / turbo 32.1 on FLEURS-hi — [SOTA2](https://www.sota2.com/research/sota/automatic-speech-recognition-on-fleurs-hindi-test); Parakeet-RNNT-1.1B Multilingual (NIM, commercial use, Hindi listed) — [NVIDIA NIM](https://build.nvidia.com/nvidia/parakeet-1_1b-rnnt-multilingual-asr/modelcard)
- Parakeet v3 has no Hindi and no language control — [HF](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3); [NeMo #14799](https://github.com/NVIDIA-NeMo/NeMo/issues/14799)
- MMS_FA weights are CC-BY-NC 4.0 — [torchaudio docs](https://docs.pytorch.org/audio/2.10.0/generated/torchaudio.pipelines.MMS_FA.html)
- Sarvam returns no word-level timestamps (per API docs) — [Sarvam API reference](https://docs.sarvam.ai/api-reference/speech-to-text/transcribe)

### Inferences
**Use 1 — TTS word timings (exact text known): forced alignment only.**
- Align the TTS input text (numbers and abbreviations expanded the way the TTS speaks them; punctuation stripped; NFC + zero-width removal) with a Hindi Devanagari CTC model (wav2vec2 Hindi via `torchaudio.functional.forced_align`, preserved in torchaudio 2.10) or NFA with the IndicConformer Hindi model. ASR is unnecessary and would add errors on clean TTS audio. If the TTS provider itself can return word or character timings, that may be simpler still (not researched here).
- Keep a mapping from each aligned token run back to the original display word so captions show Devanagari with punctuation.
- Hosting: one ~300M–1B CTC model on the existing GPU server, much lighter than ASR.

**Use 2 — user's recorded voice (script known, speaker may deviate): ASR first, then alignment, then reconcile with the script.**
- Run Hindi ASR (IndicConformer RNNT/CTC or Hindi-fine-tuned Whisper, greedy decoding), force-align the ASR's own words with the Hindi CTC aligner (the WhisperX pattern; 71 ms on Hindi), then match ASR words to script words with the existing `SequenceMatcher` approach to find where the speaker followed or left the script. Where a stretch matches the script exactly, re-aligning that stretch with the script text is an option.
- Pad cut points: CTC ends are ~90–100 ms early on Hindi, so cut mid-gap or apply a calibrated offset, or words will be clipped at splice points.

**Use 3 — dialogue check of H3 audio: ASR only, with Hindi-aware matching.**
- Needs real recognition with per-word times (for the SCN-009 windows). Self-hosted: IndicConformer (MIT) or a Hindi-fine-tuned Whisper; hosted: ElevenLabs Scribe or Deepgram Nova-3 (word timestamps documented), or Sarvam Saaras v4 if the windows step can live with chunk-level times.
- Add the Hindi normalisation and matching steps from section 5, and consider a grapheme-level similarity step, because Hindi WER on read speech is still ~9–15% for good models and the current threshold was tuned for English.
- Avoid untuned Whisper for this use (high WER and insertion hallucinations on short clips).

**Routing and licences**
- Add a language field to the transcription request (or a second endpoint) so Hindi never reaches Parakeet v3; route English to Parakeet as today.
- Prefer MIT/Apache/CC-BY components (IndicConformer MIT, Omnilingual Apache-2.0, Parakeet CC-BY-4.0, Whisper MIT) over MMS_FA (CC-BY-NC) unless use is strictly non-commercial.

### Gaps
- No head-to-head test of these candidates on the owner's actual audio (H3 Hindi clips, Hindi TTS output from the app's provider, user recordings) exists; a small labelled set (even 20–50 clips with hand-checked word boundaries for a few) is needed to pick the aligner offset, the ASR and the dialogue threshold.
- GPU memory and throughput of IndicConformer, Hindi Whisper and wav2vec2 Hindi on the owner's server were not measured.
- Which Hindi TTS the app will use (and whether it returns its own timings) is outside this research.
