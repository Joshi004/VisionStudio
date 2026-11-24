# Hindi text-to-speech options for Visio Studio (as of 18 Nov 2026)

Scope: Hindi (hi-IN, Devanagari) narration and character dialogue for YouTube videos, with three pipeline modes (voice design from a description, voice cloning from reference audio + transcript, and "direction" = cloning + tone/emotion/pace instruction). Dialogue audio feeds MiniMax H3 lip sync, so naturalness and stable voice identity matter. Research done 18 Nov 2026; most sources are 2025–2026 model cards, vendor docs and pricing pages. Third-party blogs/aggregators are labelled as secondary.

---

## 1. Does Breeze TTS 2 support Hindi? What is it?

### Takeaway
Breeze TTS 2 is from **BreezeBlue** (breezeblue.ai, Hugging Face org `BreezeBlue`), not MediaTek Research as far as these sources show. The **open-weight model the owner self-hosts is English + Chinese only; it does not support Hindi.** Only BreezeBlue's *hosted* `breeze-tts-2-multilingual` API lists Hindi (`hi`) among 51 languages. Commercial rights come only through a paid hosted subscription, never for self-hosted outputs.

### Cited Findings
- The open-weight model card describes "Bilingual Support — Generates natural English and Chinese speech with a single model"; vocal-event tags are documented only for English `(laugh)` and Chinese `[笑]`. — [BreezeBlue/Breeze-TTS-2 model card](https://huggingface.co/BreezeBlue/Breeze-TTS-2); [demo Space README](https://huggingface.co/spaces/BreezeBlue/breeze-tts-2-demo/blob/main/README.md) ("Open-weight bilingual (English/Chinese)")
- Weights released 25 Aug 2026; 3B parameters; ~7.7 GiB GPU memory for eager inference (12 GB GPU minimum), 14.4 GiB with `--fast-all` (24 GB GPU); streaming output is mono 24 kHz 16-bit PCM; the audio tokenizer is based on Qwen3-TTS (Apache-2.0). — [Breeze-TTS-2 model card](https://huggingface.co/BreezeBlue/Breeze-TTS-2)
- Licence: code is Apache-2.0, but "Model weights, checkpoints, adapters, derivative models, and self-hosted outputs are governed separately by the BreezeBlue Research and Non-Commercial License." Outputs from the hosted platform/API "can be used commercially" with an active paid subscription; "A paid subscription does not grant commercial rights to the open-weight model or self-hosted outputs." — [Breeze-TTS-2 model card](https://huggingface.co/BreezeBlue/Breeze-TTS-2)
- The hosted model `breeze-tts-2-multilingual` (alias `breeze-tts-2-preview`) supports 51 language codes including `hi` (Hindi), `ur`, `mr`, `bn`, `ta`, `te`, `kn`, `ne`. Accent codes exist only for English (incl. `indian`) and Chinese; "All other languages require `accent: null`." — [BreezeBlue docs: Multilingual audio](https://docs.breezeblue.ai/concepts/multilingual)
- BreezeBlue's launch page markets "natural, expressive text to speech AI voices across 51 languages". — [Introducing Breeze TTS 2](https://breezeblue.ai/breeze-tts-2)
- The GitHub repo claims "#1 among open-weight models on the Artificial Analysis TTS leaderboard" (vendor claim; this leaderboard is not Hindi-specific). — [breezeblue-ai/breeze-tts](https://github.com/breezeblue-ai/breeze-tts)

### Inferences
- The current self-hosted Breeze setup cannot produce Hindi. Adding Hindi means either (a) switching to BreezeBlue's paid hosted multilingual API, which keeps the same three-mode contract but is untested for Hindi quality, or (b) adding a second TTS engine for Hindi.
- **Licence flag that also affects English:** if the YouTube videos are monetized, self-hosted Breeze outputs are probably not allowed under the non-commercial licence. A paid hosted BreezeBlue subscription (or another engine) would be needed for commercial output. This is a reading of the licence text, not legal advice.
- The hosted API's request header (`xi-api-key`) and voice-metadata model look ElevenLabs-style, so a hosted Breeze integration could be small. This is a guess from the doc snippet.

### Gaps
- No independent or vendor Hindi quality numbers (MOS, CER, WER) were found for `breeze-tts-2-multilingual`. Whether voice design and direction work in Hindi on the hosted model is not documented in the pages read.
- No link between BreezeBlue and MediaTek Research appeared in any source. I did not separately search MediaTek's Breeze/BreezyVoice line, so "not MediaTek" rests on the BreezeBlue branding and org names.

---

## 2. Open, self-hostable models with Hindi

### Takeaway
No open model matches Breeze TTS 2's full set (design + clone + direction) for Hindi under a clean commercial licence. Each realistic open candidate covers part of it:
- **Chatterbox Multilingual V3 / Hindi finetune** (MIT): cloning plus an exaggeration control. It has been unmaintained since Aug 2026.
- **Indic Parler-TTS** (Apache-2.0): the only open option found with voice design from a text description for Hindi. It has no cloning.
- **IndicF5** (MIT per AI4Bharat, but the licence is disputed): cloning with reference audio + transcript, the same contract as Breeze. It ranked last in a 120K-vote human study.
- **Indic-Speak** (Bodhan AI, conditional commercial licence): 95 library voices, no cloning.
- **Veena** (Apache-2.0): 4 fixed voices, Hindi/English code-mixed.

Many popular general models do not support Hindi at all: Qwen3-TTS, CosyVoice 3, IndexTTS 2, Fish Audio S1, Spark-TTS and Higgs Audio v2.

### Cited Findings

**Independent Hindi and Indic evidence (2026)**
- AI4Bharat "Preferences of a Voice-First Nation" (Interspeech 2026): 5,357 sentences in 10 Indian languages including Hindi, more than 120K pairwise votes from more than 1,900 native raters. Overall Bradley–Terry ranking: Gemini 2.5 Pro TTS 1128.5 > ElevenLabs v3 1056.3 ≈ Sonic 3 1050.8 > Bulbul v3 Beta 1021.9 > MiniMax Speech 2.8 HD 993.9 (only 2 languages) > GPT-4o-mini TTS 942.8 > **IndicF5 805.8 (last; 19% win rate)**. "Indic F5 consistently ranks at or near the bottom." Gemini ranks first in 9 of 10 languages. — [arXiv 2604.21481](https://arxiv.org/html/2604.21481v1); [SpeechArenaBench dataset (MIT)](https://huggingface.co/datasets/ai4bharat/SpeechArenaBench)
- The same study has Normalized, Symbolic (raw numerals/formulas) and Code-mixed subsets. IndicF5 scored 812.5 on code-mixed, 849.8 on normalized and 785.4 on symbolic, so it does worst on raw numbers. — [arXiv 2604.21481](https://arxiv.org/html/2604.21481v1)
- PSP accent benchmark (pilot, 10 utterances per language, so preliminary): on Hindi, retroflex and aspiration collapse are about 0% for ElevenLabs v3, Cartesia Sonic-3 and Sarvam Bulbul; Indic Parler-TTS had a single retroflex outlier. "Modern Hindi TTS — both commercial and open-source — has largely solved core phonological articulation." Hindi FAD (closeness to native speech; lower is better): Sarvam 211.8, ElevenLabs 227.5, **Indic Parler 248.4**, Cartesia 267.4. — [arXiv 2604.25476 (PSP)](https://arxiv.org/html/2604.25476v1)
- Praxy Voice (pilot, 10 utterances): vanilla Chatterbox plus a 6–11 s *native Hindi* voice prompt and tuned sampling (exaggeration 0.7, temperature 0.6, min_p 0.1) reached Hindi LLM-WER 0.025, "tied with Cartesia", with 0% retroflex/aspiration collapse. Raw IndicF5 on code-mixed input scored LLM-WER 0.80–0.85; adding a native-script transliteration preprocessor brought this to 0.14–0.27, "remaining clearly behind commercial systems on Hi". — [arXiv 2604.25441 (Praxy)](https://arxiv.org/html/2604.25441)
- Superteams.ai blog (rubric scoring on a T4 Colab; small and low-reliability) gave Chatterbox 4.0 overall and AI4Bharat/Kokoro 4.33. — [Superteams.ai](https://www.superteams.ai/blog/benchmarking-tts-hindi-english-telugu/)
- Sonex Labs (24 Oct 2026; secondary, and the publisher sells its own Hindi TTS) declines to rank open Hindi models because published figures are not comparable. It lists user-reported failures: IndicF5 skipping words in long paragraphs; IndicF5 turning OTPs, amounts and dates into garbled noise until they are spelled out; Kokoro crashing on long Hindi; XTTS-v2 adding unintelligible sounds to short Hindi phrases. — [Sonex Labs](https://www.sonexlabs.com/blog/best-open-source-hindi-tts)

**Per-model facts**

| Model | Hindi? | Clone | Design from text | Emotion/direction | Size / memory | Licence (commercial?) |
|---|---|---|---|---|---|---|
| AI4Bharat **IndicF5** | Yes (11 Indic) | Yes: ref audio + exact transcript | No | Via reference prosody only | 0.4B, 24 kHz | MIT; AI4Bharat says "completely open for commercial usage". **Disputed**, see below |
| AI4Bharat **Indic Parler-TTS** | Yes (21 langs; Hindi speakers Rohit, Divya, Aman, Rani) | No | **Yes**: English caption describes pitch, pace, expressivity, recording quality | 12 emotion labels; Hindi emotion "not extensively tested" | 0.9B | Apache-2.0 (open question about dataset terms on outputs) |
| Resemble **Chatterbox Multilingual V3** + `Chatterbox-Multilingual-hi` | Yes (23 langs + Hindi finetune) | Yes: zero-shot from audio prompt | No | `exaggeration` intensity control | 0.5B | MIT; outputs watermarked; **retired, unmaintained since Aug 2026** |
| Bodhan AI **Indic-Speak** | Yes (13 production langs incl. Hindi, Urdu; 22 Indic total) | **No** | No (95 library voices) | `style` field is "preview-quality" | 3B (Llama-3.2-3B + SNAC + Vocos) | Indic Open Model License v1.0: commercial self-hosting OK; third-party hosting needs written approval |
| Maya Research **Veena** | Hindi + English, code-mixed | No | No (4 voices) | Not documented as controllable | 3B (3.8B weights, ~7.6 GB BF16; 4-bit supported) | Apache-2.0 |
| Kenpath **svara-tts-v1** / **voiceclone-beta** | Yes (19 langs; Hindi male/female) | Beta: ~10 s reference | No | End-of-utterance emotion tags | 3B (Llama-3.2-3B / Orpheus Hindi base) | Apache-2.0 stated |
| SPRINGLab **Indic-Mio** (2026) | Yes (22 Indic + English) | Zero-shot via codec speaker embeddings | No | Not documented | 0.6B, 44 kHz, <0.1 RTF | **Not stated in the card excerpt read** |
| somyalab **Spark-Somya-TTS** | Yes (Hindi + others) | Zero-shot | No | No | 0.5B | Apache-2.0 |
| DheeYantra **Dhee-Indic-F5** (2026) | Yes | Yes | No | No | 0.4B | **CC-BY-NC-4.0 (non-commercial)** |
| hexgrad **Kokoro-82M** | 4 Hindi voices, graded C, 1–10 h of data | No | No | No | 82M | Apache-2.0 |
| Coqui **XTTS-v2** | Yes | Yes (~6 s) | No | No | n/a | **Coqui Public Model License: non-commercial; Coqui shut down** |

Sources for the table rows:
- IndicF5: [model card](https://huggingface.co/ai4bharat/IndicF5) (trained on 1,417 h from Rasa, IndicTTS, LIMMITS, IndicVoices-R; "Indic-Speak is now available… We recommend using Indic-Speak"); [discussion 34, licence](https://huggingface.co/ai4bharat/IndicF5/discussions/34)
- Indic Parler-TTS: [model card](https://huggingface.co/ai4bharat/indic-parler-tts)
- Chatterbox: [GitHub README](https://github.com/resemble-ai/chatterbox) ("As of August 2026, Chatterbox is retired research and is no longer maintained"); [HF card](https://huggingface.co/ResembleAI/chatterbox) ("Watermarked outputs", "0.5B Llama backbone", "Unique exaggeration/intensity control"); [Hindi finetune card](https://huggingface.co/ResembleAI/Chatterbox-Multilingual-hi/blob/main/README.md) (MIT)
- Indic-Speak: [model card](https://huggingface.co/bodhan-ai/indic-speak); [licence text](https://huggingface.co/Muesli-HQ/indic-transcribe-core-coreml/blob/c4a41308acbd68a8c6256ad8a54acd1565872c88/Bodhan_AI_Open_Model_License.md); [EightBots](https://www.eightbots.com/AIproviders/bodhan-ai/indic-speak) (95 voices; secondary)
- Veena: [model card](https://huggingface.co/maya-research/Veena); [AxForge](https://axforge.ai/models/veena/) (7.6 GB BF16, RTX 3060 12 GB minimum; secondary); [News9](https://www.news9live.com/technology/artificial-intelligence/maya-research-veena-tts-hindi-english-ai-launch-2873017) (emotional tones and streaming are on the roadmap)
- Svara: [svara-tts-v1](https://huggingface.co/kenpath/svara-tts-v1); [voiceclone-beta](https://huggingface.co/kenpath/svara-tts-voiceclone-beta) ("Speaker similarity may degrade over long utterances"); [MLX port](https://huggingface.co/mlx-community/svara-tts-v1) (base `canopylabs/3b-hi-ft-research_release`)
- [Indic-Mio](https://huggingface.co/SPRINGLab/Indic-Mio); [Spark-Somya-TTS](https://huggingface.co/somyalab/Spark_somya_TTS); [Dhee-Indic-F5](https://huggingface.co/dheeyantra/dhee-indic-f5)
- Kokoro and XTTS-v2: [Sonex Labs](https://www.sonexlabs.com/blog/best-open-source-hindi-tts) (secondary, citing the Kokoro VOICES.md and the XTTS-v2 licence)

**Licence conflict on IndicF5**
- AI4Bharat staff say IndicF5 is MIT and "completely open for commercial usage". — [IndicF5 discussion 34](https://huggingface.co/ai4bharat/IndicF5/discussions/34)
- The Dhee-Indic-F5 card contradicts this: IndicF5 "builds on F5-TTS (trained on the Emilia dataset, CC-BY-NC-4.0) and IIT-Madras Indic TTS data (non-commercial)", so it says non-commercial terms "carry through". — [Dhee-Indic-F5](https://huggingface.co/dheeyantra/dhee-indic-f5)
- Indic Parler-TTS has a similar unanswered question about whether training-data terms (GLOBE, IndicTTS, LIMMITS, Rasa) carry over to commercial use of its outputs (discussion 31). — [Sonex Labs](https://www.sonexlabs.com/blog/best-open-source-hindi-tts)

**Models that do not support Hindi (or are unusable for a commercial channel)**
- **Qwen3-TTS** (VoiceDesign, CustomVoice and Base 0.6B/1.7B): 10 languages (zh, en, ja, ko, de, fr, ru, pt, es, it); no Hindi. — [QwenLM/Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS/)
  - A community LoRA, `DRG-X/qwen3_TTS_FineTuned-Hindi`, provides one female voice with no formal evaluation and was trained on clips of 15 s or less. — [model card](https://huggingface.co/DRG-X/qwen3_TTS_FineTuned-Hindi)
- **Fun-CosyVoice3-0.5B-2512**: Apache-2.0; 9 languages, no Hindi. It does have instruct control (emotion, speed) and built-in text normalization. — [model card](https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512/blob/main/README.md)
- **Fish Audio S1**: 13 languages, no Hindi. — [Fish docs](https://docs.fish.audio/developer-guide/models-pricing/models-overview)
  - **Fish Audio S2 Pro** is under the "Fish Audio Research License… Commercial use requires a separate license." — [fish.audio/s2](https://fish.audio/s2/)
  - S2 Pro's Hindi support is conflicting: a search summary claimed yes, but a community language matrix marks it ❌. — [TTS-Audio-Suite LANGUAGE_SUPPORT.md](https://github.com/diodiogod/TTS-Audio-Suite/blob/main/docs/LANGUAGE_SUPPORT.md)
- **IndexTTS 2**: marked as no Hindi in the community matrix. — [TTS-Audio-Suite matrix](https://github.com/diodiogod/TTS-Audio-Suite/blob/main/docs/LANGUAGE_SUPPORT.md)
- **Microsoft VibeVoice**: Microsoft does "not recommend using VibeVoice in commercial or real-world applications"; it is research only. — [microsoft/VibeVoice](https://github.com/microsoft/VibeVoice/)
  - Cartesia reports that Microsoft removed the TTS code after misuse. — [Cartesia open-source TTS guide](https://www.cartesia.ai/learn/open-source-tts) (secondary, and Cartesia is a competitor)
- **Higgs Audio v2**: en, zh, es, fr, de, ja, ko only. — [OpenSpeech](https://www.openspeech.dev/models/higgs-audio-v2)
  - It uses the Boson community licence derived from Llama 3, with attribution and naming requirements. — [licence](https://huggingface.co/bosonai/higgs-tts-2-3b-base/blob/main/LICENSE)
- **Spark-TTS**: Chinese and English only. — [SparkAudio/Spark-TTS](https://github.com/SparkAudio/Spark-TTS/)
- **Orpheus**: a Hindi research-release finetune exists, and the community Orpheus-FastAPI ships a Hindi model and voice. — [Orpheus-FastAPI](https://github.com/lex-au/orpheus-fastapi); [Spokio overview](https://spokio.pro/orpheus-tts) (secondary)
- **Meta MMS-TTS Hindi**: CC BY-NC 4.0, non-commercial. — [Sonex Labs](https://www.sonexlabs.com/blog/best-open-source-hindi-tts)
- **Sarvam**: no open TTS weights found. Bulbul is API-only; Sarvam's open-weight release was the Sarvam-2B LLM, which is non-commercial. — [Sarvam Bulbul docs](https://docs.sarvam.ai/api/api-guides-tutorials/models/bulbul); [Maginative](https://www.maginative.com/article/sarvam-ai-launches-open-weights-sarvam-2b-model-and-suite-of-ai-products-for-indian-languages/)
- **Newer 2026 models with a Hindi checkmark** in the community matrix: Higgs Audio v3, Dots TTS, OmniVoice, MOSS-TTS v1.5. I did not verify these against primary sources. — [TTS-Audio-Suite matrix](https://github.com/diodiogod/TTS-Audio-Suite/blob/main/docs/LANGUAGE_SUPPORT.md)

### Inferences
- For a self-hosted Hindi stack that mirrors the three Breeze modes, the most plausible combination is:
  - **Design:** Indic Parler-TTS caption → save a 6–11 s clip and its transcript.
  - **Clone and direction:** Chatterbox-Multilingual-hi with a native Hindi reference and the exaggeration knob, or IndicF5 for the identical ref-audio + ref-text contract.
  - Expect lower naturalness than commercial APIs. The only large human study puts IndicF5 last, and Chatterbox's Hindi parity evidence is a 10-utterance pilot.
- Chatterbox being unmaintained is a real operational risk: no fixes for Hindi bugs. Its MIT licence is the cleanest among the capable open cloners.
- Veena and Indic-Speak suit narration (fixed, consistent voices) better than many distinct characters. Veena has only 4 voices, and Indic-Speak has no cloning.
- GPU budget: all shortlisted open models (0.4B–3B) should fit alongside or instead of Breeze on a 12–24 GB card. This is inferred from parameter counts; peak memory was not measured.

### Gaps
- No Hindi-specific MOS or CER on IndicVoices-R or Rasa was found for Veena, Indic-Speak, Svara, Indic-Mio or Chatterbox-hi from independent sources. A "Veena 4.2 MOS" figure appeared only in a search summary without a traceable source, so it is excluded.
- I could not find Indic-Mio's licence or the MioTTS base licence. Indic-Mio was trained on IndicTTS, Rasa and Syspin, whose terms may matter.
- Svara is labelled Apache-2.0 but built on Llama-3.2-3B. Whether Llama community licence terms also apply was not checked.
- MegaTTS3 language and licence details were not verified from a primary source.
- Long-form stability of open models on 1,000-character chunks was not benchmarked by anyone found.

---

## 3. Commercial APIs for Hindi

### Takeaway
On human preference for Indian languages, **Gemini 2.5 Pro TTS leads**. ElevenLabs v3 and Cartesia Sonic 3 are statistically tied for second, then Sarvam Bulbul v3, MiniMax Speech 2.8 HD (thin evidence) and GPT-4o-mini TTS.

For this pipeline's needs (custom voices per character, cloning, emotion direction, timestamps):
- **ElevenLabs v3/v4** covers everything at $80 per million characters.
- **MiniMax Speech 2.8** has voice design, cloning, Hindi, word subtitles and the same vendor as H3, at $60–100 per million.
- **Sarvam Bulbul** is the cheapest and most Indic-native, but has weak emotion control.
- **Gemini TTS** has the best preference scores and is cheap, but I found no custom-voice cloning in the Gemini TTS API.
- OpenAI gpt-4o-mini-tts leaves the API on 6 Jan 2027.

### Cited Findings

**Quality evidence**
- Overall ranking across 10 Indian languages: Gemini 2.5 Pro TTS > ElevenLabs v3 ≈ Sonic 3 > Bulbul v3 Beta > Speech 2.8 HD (2 languages only) > GPT-4o-mini TTS. Raters found ElevenLabs v3, Sonic 3 and Bulbul v3 "maintain strong intelligibility and robustness but exhibit comparatively lower expressiveness and liveliness". Bulbul v3 "performs relatively better under symbolic inputs" (raw numbers). — [arXiv 2604.21481](https://arxiv.org/html/2604.21481v1)
- PSP Hindi pilot:
  - ElevenLabs v3 has the lowest Hindi WER (0.006) but second-place FAD.
  - Sarvam is closest to native speech (FAD 211.8); Cartesia is furthest (267.4).
  - "Indic-first systems outperform Western-built systems on Indic dimensions."

  — [arXiv 2604.25476](https://arxiv.org/html/2604.25476v1)
- **Chariot-1-TTS-Multilingual** (launched 12 Nov 2026, IndiaAI Mission-backed): 11 Indic languages + English, 50+ voices, instant cloning, code-mixing, 1,000 characters per request, "context-aware pronunciation… without custom normalisation rules". Self-reported Hindi CER is 7.60%, and the figures "have not yet been independently reproduced". — [Elets CIO](https://cio.eletsonline.com/artificial-intelligence/chariot-indic-text-to-speech-model/76872/)

**Pricing and features (list prices; read Oct–Nov 2026)**

| Provider / model | Price | Hindi voices / cloning / design | Expressive control | Notes |
|---|---|---|---|---|
| **ElevenLabs** v3, v4, Multilingual v2 | $0.08 per 1K chars ($80/M); Flash/Turbo/v4 Turbo/v3 Conversational $0.04 per 1K ($40/M) | Hindi supported; Instant Voice Clone from 30 s; Pro clone from 10+ min; cross-lingual clone | v3 audio tags `[whispers]`, `[sighs]`, `[excited]`; multi-speaker dialogue | v3: 70+ langs, 5,000-char limit; Multilingual v2: 29 langs, 10,000 chars, "Stable on long-form"; v4: 90+ langs (secondary) |
| **Sarvam** Bulbul v3 | ₹3.00 per 1K chars PAYG (₹2.60–2.85 on plans); Instant Voice Cloning ₹2.00 per 1K | 30+ speakers (Hindi recommended: shubh, ashutosh, priya, suhani); clone beta (≤15 s ref, cross-lingual) | Only `pace` (0.5–2.0) and `temperature` (0.01–1.0); no pitch or loudness on v3 | 11 languages; 2,500 chars per REST request (clone API: 1,000); up to 48 kHz; handles Hinglish and numbers "out of the box" |
| **Sarvam** Bulbul v4 Flash | **Conflict:** ₹1.00 per 1K (docs) vs ₹2.00 per 1K (marketing page) | 200+ persona voices | `temperature`, `pitch`, `loudness` | Newer model; not in the benchmarks |
| **Google** Chirp 3 HD | $30/M chars (first 1M per month free); Instant custom voice $60/M | Hindi voice list not verified here | n/a | |
| **Google** Gemini TTS | 2.5 Pro TTS: $1/M text tokens + $20/M audio tokens; 3.8 Flash TTS: $0.50 + $9/M through 31 Dec 2026, then $1 + $18/M; 25 audio tokens per second | n/a | "granular control… using text-based prompts" | 3.8 Flash TTS marketed for "long-form stability" |
| **Azure** | Neural $15/M; Neural HD $22/M (East US list) | hi-IN: Swara, Ananya, Kavya, Aarav, Kunal, Rehaan; Dragon HD Omni covers "all released voices", multilingual, with natural-language style control; Personal Voice $24/M (limited access) | Omni `mstts:express-as` descriptions | |
| **Amazon Polly** | Neural $16/M (speech marks available); Generative $30/M (no speech marks) | hi-IN: Aditi (standard); Kajal (neural + generative); Arjun, Kiara (generative) | Limited (SSML) | |
| **OpenAI** gpt-4o-mini-tts | $0.60/M text tokens + $12/M audio tokens (~$0.015/min) | 13 preset voices; no cloning | Instructions steer accent, emotion, tone | **Deprecated; removed 6 Jan 2027.** Replacement `gpt-realtime-2.1-mini` does not use the Speech endpoint |
| **MiniMax** Speech 2.8 | hd $100/M, turbo $60/M; Voice Design $3 per voice; Rapid Voice Cloning $1.50 per voice | `language_boost: "Hindi"`; 300+ system voices; design and clone produce reusable `voice_id`s; clone needs 10 s–5 min audio | Interjection tags `(laughs)`, `(sighs)`, `(breath)` etc. on 2.8 models; pause tags | Sync <10,000 chars; async up to 1M chars per request; `text_normalization_mode` basic/quality |
| **Cartesia** Sonic-3.x | 1 credit per char. Pro $5 = 100K credits; Startup $49 = 1.25M; Scale $299 = 8M (≈$37–50/M); overage $38–65/M | Hindi supported (language-specific Hindi voices used in PSP); instant cloning; Pro clones from Startup plan | `emotion` parameter; speed 0.6–1.5× | Commercial use licence from the $5 plan; `normalization` param; Sonic 3.5 and 3.6 now listed |

Sources for the table rows:
- ElevenLabs: [API pricing](https://elevenlabs.io/pricing/api); [micdrop.dev](https://micdrop.dev/blog/elevenlabs-api-pricing-voice-agent) (secondary); [paywithlocus](https://paywithlocus.com/guides/elevenlabs-api-pricing) (secondary); [Eleven v3 blog](https://elevenlabs.io/blog/eleven-v3); [IIT Delhi cloning blog](https://elevenlabs.io/blog/voice-cloning-in-12-indian-languages-demonstrated-live-at-iit-delhi)
- Sarvam: [Sarvam pricing](https://www.sarvam.ai/api-pricing); [Sarvam docs pricing](https://docs.sarvam.ai/api/getting-started/pricing); [Bulbul docs](https://docs.sarvam.ai/api/api-guides-tutorials/models/bulbul); [v3 best practices](https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/bulbul-v3-best-practices); [REST guide](https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/rest-api); [clone API](https://docs.sarvam.ai/api-reference/voice-cloning/clone); [convert API](https://docs.sarvam.ai/api-reference/text-to-speech/convert)
- Google: [Cloud TTS pricing](https://cloud.google.com/text-to-speech/pricing); [Gemini API pricing](https://aistudio.google.com/docs/pricing)
- Azure: [new Indian voices GA](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/announcing-ga-of-new-indian-voices/4247044); [HD voices](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/high-definition-voices); [OndaLabs](https://ondalabs.app/blog/azure-ai-speech-tts) (prices, secondary)
- Amazon Polly: [available voices](https://docs.aws.amazon.com/polly/latest/dg/available-voices.html); [Polly pricing](https://aws.amazon.com/polly/pricing/); [generative engine blog](https://aws.amazon.com/blogs/machine-learning/amazon-polly-delivers-a-major-upgrade-to-its-generative-engine/)
- OpenAI: [model page](https://developers.openai.com/api/docs/models/gpt-4o-mini-tts) (status: Deprecated); [pricing](https://developers.openai.com/api/docs/pricing); [Omcircle](https://omcircle.ai/radar/ai-models/gpt-4o-mini-tts) (removal date, secondary)
- MiniMax: [pricing](https://platform.minimax.io/docs/pricing/overview); [T2A API](https://platform.minimax.io/docs/api-reference/speech-t2a-http); [AI Stack Current](https://aistackcurrent.com/models/minimax-speech-2-8-family/) (clone constraints, secondary)
- Cartesia: [pricing](https://www.cartesia.ai/pricing); [docs pricing](https://docs.cartesia.ai/pricing); [SSE API](https://docs.cartesia.ai/api-reference/tts/sse); [advanced capabilities](https://docs.cartesia.ai/build-with-cartesia/capability-guides/advanced-capabilities)

- Sarvam output rights: "Production rights apply to output generated while account credits are consumed… subject to EULA terms." — [LunaPrompts](https://lunaprompts.com/models/sarvam/bulbul-v3) (secondary)
- Maya Research's hosted API terms allow commercial use and assign output ownership to the user. Access is by request only. — [Maya terms](https://www.mayaresearch.ai/terms/)

### Inferences
- **Cost per finished minute** (rough; assumes about 1,000 characters per minute, which is ElevenLabs' English approximation and unverified for Hindi):

  | Option | Approx. cost per minute |
  |---|---|
  | ElevenLabs v3 | ~$0.08 |
  | MiniMax 2.8 hd | ~$0.10 |
  | MiniMax 2.8 turbo | ~$0.06 |
  | Cartesia | ~$0.04–0.05 |
  | Sarvam v3 (₹3 per 1K) | ~₹3 |
  | Chirp 3 HD | ~$0.03 |
  | Gemini 2.5 Pro TTS | ~$0.03 (1,500 audio tokens per minute × $20/M) |
  | Gemini 3.8 Flash TTS | ~$0.0135 until 31 Dec 2026, then ~$0.027 |

  For a story-video channel, all of these are small next to video-generation costs.
- **MiniMax** is attractive for operational reasons: one vendor and account with H3, plus voice design + cloning + word subtitles + Hindi. However, its Hindi preference evidence is thin (Speech 2.8 HD was evaluated in only 2 languages, and which ones was not identified).
- **Gemini TTS** probably suits narration best (top preference scores, prompt-steerable delivery). Character voices would be limited to its preset voice catalogue unless Google's Instant custom voice is available to the account.
- **Sarvam Bulbul v3** is a strong low-cost baseline for narration and plain dialogue. It is weak on the pipeline's "direction" mode (pace and temperature only) and has no voice design.
- **Avoid OpenAI gpt-4o-mini-tts** for new work: it is deprecated with a set removal date.

### Gaps
- Gemini TTS: Hindi voice list, custom-voice/cloning availability and commercial output terms were not verified in the pages read.
- ElevenLabs: whether Voice Design (text-to-voice) produces native-sounding Hindi voices, and its commercial-use terms by plan, were not verified.
- MiniMax commercial output terms were not verified. No Hindi-specific MiniMax benchmark was found.
- Cartesia's dedicated Hindi voice catalogue size and Hinglish handling were not verified beyond a search summary.
- Google Chirp 3 HD hi-IN voice availability was not confirmed from a primary page in this pass.
- No source gave Hindi characters per minute of speech, which affects per-character cost comparisons.

---

## 4. Cross-lingual voice identity: can an English-designed character voice speak Hindi?

### Takeaway
Most systems technically allow it (ElevenLabs, Sarvam's clone API, Chatterbox, MiniMax via voice IDs), but every vendor that documents the behaviour says **accent and pronunciation come from the reference or voice, not the text.** An English-designed voice speaking Hindi will tend to carry its English accent or drift. The evidence-backed approach is **separately designed or cloned Hindi voices** per character, using native Hindi reference audio. Use cross-lingual cloning only where the same character must sound identical across the English and Hindi versions, and test it.

### Cited Findings
- ElevenLabs: "The language is determined by the text, the accent and pronunciation is determined by the voice itself… you should use a cloned voice that was cloned speaking the language with the correct accent." — [ElevenLabs help: same voice across languages](https://elevenlabs.io/docs/help-center/product/core-capabilities/text-to-speech/can-i-use-the-same-cloned-designed-voice-across-languages.md)
- ElevenLabs: a voice not native to the language "might retain its native accent, or drift between different accents". — [ElevenLabs help: accent changes](https://elevenlabs.io/docs/help-center/troubleshooting/why-does-my-voice-change-accent-or-language)
- ElevenLabs markets cross-lingual clones ("English to Hindi? Yes"). It also says a cloned voice "retains its unique characteristics and accent" in other languages, which means accent carry-over is expected. — [ElevenLabs IIT Delhi blog](https://elevenlabs.io/blog/voice-cloning-in-12-indian-languages-demonstrated-live-at-iit-delhi); [ElevenLabs Hindi TTS page](https://elevenlabs.io/text-to-speech/hindi)
- Chatterbox: "Ensure that the reference clip matches the specified language tag. Otherwise, language transfer outputs may inherit the accent of the reference clip's language. To mitigate this, set `cfg_weight` to `0`." — [resemble-ai/chatterbox README](https://github.com/resemble-ai/chatterbox)
  - A community explainer says `cfg_weight=0` lowers reference influence, which trades accent leakage against voice similarity. — [DeepWiki: multilingual considerations](https://deepwiki.com/rsxdalv/chatterbox/8.3-multilingual-considerations) (secondary)
- Sarvam clone API: "The cloned voice can speak any supported language, regardless of the reference clip's language (cross-lingual cloning)." — [Sarvam clone API](https://docs.sarvam.ai/api-reference/voice-cloning/clone)
- Dhee-Indic-F5: "match the reference speaker's language/accent to your target text". — [Dhee-Indic-F5](https://huggingface.co/dheeyantra/dhee-indic-f5)
- Praxy: commercial-class Hindi from Chatterbox was recovered only when a *native Hindi* voice prompt was supplied. Conditioning on a native speaker moved accent metrics "sharply and in the right direction". — [arXiv 2604.25441](https://arxiv.org/html/2604.25441); [arXiv 2604.25476](https://arxiv.org/html/2604.25476v1)
- BreezeBlue hosted API: a saved voice's `language_code` and `accent` describe the reference or preview audio. Accent codes exist only for en/zh, and `indian` is an English accent option. — [BreezeBlue multilingual docs](https://docs.breezeblue.ai/concepts/multilingual)

### Inferences
- The current voices are designed as "neutral Indian English accent". An Indian-English voice may leak less non-native accent into Hindi than an American one would, but none of the sources quantify this.
- Recommended approach:
  - Keep each character's *description* (age, pitch, warmth) as the source of truth.
  - Generate a separate Hindi voice from the same description with a Hindi-capable designer: ElevenLabs/MiniMax Voice Design, or Indic Parler caption for self-hosting.
  - Store that Hindi reference clip + transcript as the character's `hi` voice and reuse it for every Hindi line. This keeps lip-sync input consistent within a Hindi video.
- For lip sync, accent drift *within* a video probably matters more than identity match *across* language versions, so per-language voices are lower-risk.

### Gaps
- No source measured accent leakage (for example PSP or FAD scores) for English-reference → Hindi-output cloning on any system.
- MiniMax's cross-lingual behaviour for cloned or designed voices was not documented in the pages read.

---

## 5. Hindi-specific text issues and normalizers

### Takeaway
Numbers, dates, currency and OTPs are the most common Hindi TTS failure for open models. IndicF5, Svara and Praxy/Telugu all document garbled digits, and IndicF5 does worst on raw-symbol input in AI4Bharat's study. Hinglish written in Latin script is read badly by Indic-native open models (Indic Parler; the Sarvam clone API rejects it).

Several commercial APIs normalize internally: Sarvam Bulbul v3, MiniMax `text_normalization_mode`, Cartesia `normalization`, ElevenLabs `normalized_alignment`, and Chariot's claim. **NVIDIA NeMo-text-processing** has an open Hindi WFST normalizer, including a Hindi-English code-switched mode in release r1.2.0. Nukta and schwa-deletion handling were not documented by any source found.

### Cited Findings
- IndicF5 "turning OTPs, amounts and dates into garbled noise until they were spelt out as words" (GitHub issue 31, open). The recommended fix is a normaliser that writes ₹1,499 or 4582 out in Hindi words. — [Sonex Labs](https://www.sonexlabs.com/blog/best-open-source-hindi-tts)
- Svara: "Numbers & currency: normalize large values… e.g., ₹1,23,456 → 'one lakh twenty-three thousand…'"; "Proper nouns & rare entities can trip pronunciation." — [Svara blog](https://huggingface.co/blog/kenpath/svara-tts-open-multilingual-speech-for-india)
- Praxy: numeric date tokens produced "garbage tokens"; expanding digits to words fixed it, which is "a number-normaliser in preprocessing, not a model-capacity limitation" (Telugu example). — [arXiv 2604.25476](https://arxiv.org/html/2604.25476v1)
- AI4Bharat's benchmark: the Symbolic subset keeps raw numerals, formulas and operators; the Code-mixed subset covers intra-sentential English, transliteration and mixed script. IndicF5 scored lowest on Symbolic (785.4), and Bulbul v3 did relatively better on Symbolic. — [arXiv 2604.21481](https://arxiv.org/html/2604.21481v1)
- Code-mixing in open models: raw IndicF5 LLM-WER on code-mixed Hindi was 0.80–0.85. A native-script transliteration preprocessor brought it to 0.14–0.27, still "clearly behind commercial systems on Hi". — [arXiv 2604.25441](https://arxiv.org/html/2604.25441)
- Indic Parler-TTS: "Text typed in English letters (Hinglish or Tanglish) is read badly, because the model learned each language from its native script." — [LiveWeights](https://liveweights.com/blog/indic-parler-tts-online) (secondary)
- Sarvam: Bulbul v3 "handles code-mixed text (e.g., Hinglish), number normalization, and natural prosody out of the box". The clone API says "Romanized Indic and Urdu return 400". — [Sarvam REST guide](https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/rest-api); [Sarvam clone API](https://docs.sarvam.ai/api-reference/voice-cloning/clone)
- Veena and Indic-Speak advertise code-mixed Hindi/English. Indic-Speak focuses on STEM and code-mixed reading, but "unusual words may be mispronounced". — [Veena card](https://huggingface.co/maya-research/Veena); [Indic-Speak card](https://huggingface.co/bodhan-ai/indic-speak)
- MiniMax `text_normalization_mode`: "`basic` uses fast, rule-based normalization. `quality` uses a hybrid LLM + rule-based approach." — [MiniMax T2A API](https://platform.minimax.io/docs/api-reference/speech-t2a-http)
- Cartesia `normalization` "sets how dates, times, and numbers are read. Use `auto` (default), `off`, or a language or locale code." — [Cartesia advanced capabilities](https://docs.cartesia.ai/build-with-cartesia/capability-guides/advanced-capabilities)
- Chariot-1 claims correct reading of amounts, dates and abbreviations "without custom normalisation rules" (vendor claim, unreproduced). — [Elets CIO](https://cio.eletsonline.com/artificial-intelligence/chariot-indic-text-to-speech-model/76872/)
- **NeMo-text-processing (open)**:
  - Hindi TN covers Cardinal, Decimal, Fraction, Ordinal, Date, Time, Money, Measure, Telephone and Electronic classes.
  - Release r1.2.0 also adds "Hi-En (Hindi-English) Code-Switched TN (#415)".
  - Usage: `normalize.py --language=hi`.

  — [NeMo-text-processing r1.2.0](https://github.com/NVIDIA/NeMo-text-processing/releases/tag/r1.2.0); [PR #241](https://github.com/NVIDIA/NeMo-text-processing/pull/241); [NeMo TN docs](https://docs.nvidia.com/nemo-framework/user-guide/25.02/nemotoolkit/nlp/text_normalization/wfst/wfst_text_normalization.html)
- NeMo Hindi TN 2.0 per-class accuracy (from the PR):

  | Class | Accuracy |
  |---|---|
  | Cardinal | 89.86% |
  | Money | 99.04% |
  | Time | 92.61% |
  | Date | 87.18% |
  | **Ordinal** | **38.46%** |
  | Decimal | 100% |
  | Fraction | 99.66% |
  | Measure | 96.26% |
  | Telephone | 99.13% |
  | **Address** | **18.99%** |

  It also adds Hindi quantity words सवा, साढ़े, पौने, डेढ़, ढाई. — [NeMo PR #294](https://github.com/NVIDIA/NeMo-text-processing/pull/294)

### Inferences
- **Open models need a normalizer first.** IndicF5, Indic Parler, Chatterbox-hi, Svara, Veena and Kokoro should all get a pre-pass: NeMo Hindi TN, then Latin→Devanagari transliteration of English loanwords where the model is native-script-only. Ordinals and addresses in NeMo are weak, so story text with "पहला/दूसरा" written as digits may need custom rules or an LLM rewrite.
- For story narration, an **LLM rewrite step** that outputs fully verbalized Devanagari is a practical alternative. The story already passes through an LLM in Visio Studio. It would handle numbers, abbreviations (e.g., "डॉ." → "डॉक्टर") and Hinglish script choice in one step. This needs testing; no source evaluates it for Hindi TTS.
- Commercial APIs with built-in normalization (Sarvam, MiniMax quality mode, Cartesia, ElevenLabs) can take raw text. Deterministic pre-normalization still makes output reproducible and keeps captions matching the audio.

### Gaps
- No source specifically tested **nukta** (क़ ख़ ग़ ज़ फ़) handling or **schwa deletion** errors in Hindi TTS models. This should be checked in listening tests. Unicode nukta normalization (precomposed vs combining forms) should also be checked; it was not researched here.
- AI4Bharat-specific normalization and transliteration tools (e.g., IndicXlit, Indic NLP library) were not verified in this pass.
- Whether Gemini TTS and ElevenLabs v3 correctly verbalize Hindi numerals and Indian number grouping (lakh/crore) was not documented in the sources read. The AI4Bharat Symbolic subset suggests the commercial systems cope, but per-model Hindi numbers were not extracted.

---

## 6. Word-level timestamps for captions

### Takeaway
Direct timestamps are available from:
- **MiniMax** (word-level subtitles)
- **Cartesia** (word- and phoneme-level)
- **ElevenLabs** (character-level alignment, grouped into words)
- **Azure** (WordBoundary events)
- **Amazon Polly** neural voices (speech marks; not generative voices)

**Google** offers only SSML `<mark>` timepoints. **OpenAI** offers none. None of the open Hindi models document timestamps, so self-hosted output needs forced alignment; Hindi CTC aligners exist.

### Cited Findings
- MiniMax T2A: `subtitle_enable` with `subtitle_type` `sentence`, `word` or `word_streaming`. Non-streaming returns a `subtitle_file`; streaming returns `timestamped_words`. — [MiniMax T2A API](https://platform.minimax.io/docs/api-reference/speech-t2a-http)
- Cartesia: `add_timestamps` returns "word-level timing information"; `add_phoneme_timestamps` returns phoneme timing; `use_normalized_timestamps` is also available. — [Cartesia SSE API](https://docs.cartesia.ai/api-reference/tts/sse)
- ElevenLabs: `POST /v1/text-to-speech/{voice_id}/with-timestamps` returns `alignment` and `normalized_alignment` with per-character start and end times. — [ElevenLabs API: Create speech with timing](https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps)
- Azure: the `WordBoundary` event "reports the current word's time offset, in ticks". — [Azure how-to speech synthesis](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-speech-synthesis)
- Google Cloud TTS: timepoints only for `<mark>` tags with `SSML_MARK`. — [Google SSML docs](https://docs.cloud.google.com/text-to-speech/docs/ssml)
- Amazon Polly: neural voices support "All speech marks"; "Speech marks are not available on generative voices." — [Polly neural voices](https://docs.aws.amazon.com/polly/latest/dg/neural-voices.html); [Polly generative blog](https://aws.amazon.com/blogs/machine-learning/amazon-polly-delivers-a-major-upgrade-to-its-generative-engine/)
- OpenAI TTS: "no timestamps; run the audio through a word-level STT". — [OpenCode Skills](https://opencodeskills.dev/skills/ai-ml/text-to-speech/) (secondary)
- Indic-Speak lists word timestamps as planned, not shipped. — [The Signal](https://signalbriefing.app/summaries/ai4bharat-indic-speak-code-mixed-tts) (secondary)
- A Hindi CTC aligner exists: the PSP benchmark used `ai4bharat/indicwav2vec-hindi` for forced alignment of Hindi audio. — [arXiv 2604.25476](https://arxiv.org/html/2604.25476v1)

### Inferences
- If captions matter, MiniMax word subtitles and Cartesia word timestamps are the most direct. ElevenLabs needs character→word grouping (simple for Devanagari if split on spaces).
- For Gemini TTS, Sarvam or open models, plan a forced-alignment step (Hindi wav2vec2 CTC or a Hindi ASR with word timestamps) after synthesis.

### Gaps
- Sarvam Bulbul timestamp support was not found in the docs read.
- Gemini TTS timestamp support was not documented in the pages read.
- Whether ElevenLabs/Cartesia Hindi alignments are accurate for Devanagari combining marks was not tested by any source found.

---

## 7. Recommended shortlist and trade-offs

### Takeaway
For a monetized YouTube channel, the realistic shortlist is:

1. **ElevenLabs v3 (or v4)**: the best match to all three Breeze modes in Hindi.
2. **MiniMax Speech 2.8 HD/turbo**: same vendor as H3, with design, clone and word subtitles.
3. **Gemini 2.5 Pro / 3.8 Flash TTS**: top human preference and cheapest; best for narration.
4. **Sarvam Bulbul v3/v4 Flash**: Indic-native, cheapest per character, weak direction control.
5. **BreezeBlue hosted multilingual API**: least integration work, but Hindi quality unverified.

For self-hosting, **Chatterbox-Multilingual-hi (MIT) + Indic Parler-TTS (Apache-2.0) + a NeMo Hindi normalizer** is the most viable open stack. Expect a quality gap to commercial systems and no maintenance for Chatterbox.

### Cited Findings
- Human-preference ranking for Indian languages: Gemini 2.5 Pro TTS > ElevenLabs v3 ≈ Sonic 3 > Bulbul v3 > Speech 2.8 HD > GPT-4o-mini TTS > IndicF5. — [arXiv 2604.21481](https://arxiv.org/html/2604.21481v1)
- In the PSP Hindi pilot, Sarvam is the most native-like on accent distribution, ElevenLabs is lowest on WER, and Cartesia is least native-like. — [arXiv 2604.25476](https://arxiv.org/html/2604.25476v1)
- ElevenLabs has audio-tag direction and cross-lingual cloning at $80/M. — [ElevenLabs v3 blog](https://elevenlabs.io/blog/eleven-v3); [ElevenLabs API pricing](https://elevenlabs.io/pricing/api)
- MiniMax has Voice Design ($3), Rapid Clone ($1.50), Hindi `language_boost` and word subtitles. — [MiniMax pricing](https://platform.minimax.io/docs/pricing/overview); [MiniMax T2A API](https://platform.minimax.io/docs/api-reference/speech-t2a-http)
- BreezeBlue hosted outputs are commercially usable with a paid subscription; self-hosted outputs are not. — [Breeze-TTS-2 model card](https://huggingface.co/BreezeBlue/Breeze-TTS-2)
- Chatterbox has been retired since Aug 2026; Indic Parler-TTS is the open option with description-based design. — [Chatterbox README](https://github.com/resemble-ai/chatterbox); [Indic Parler-TTS card](https://huggingface.co/ai4bharat/indic-parler-tts)

### Inferences

**How each candidate maps to the three pipeline modes**

| Option | Voice design | Voice cloning | Direction | Main risk |
|---|---|---|---|---|
| ElevenLabs v3/v4 | Voice Design (Hindi quality untested) | Instant Voice Clone (Hindi) | Audio tags | Cost; accent drift if voices aren't Hindi-native |
| MiniMax 2.8 | Voice Design | Rapid Clone | Interjection tags (limited emotion) | Thin Hindi evidence |
| Gemini TTS | Prompt style only, preset voices | Not verified | Prompt-steerable | Few custom character voices |
| Sarvam Bulbul | No (library voices) | Clone beta | Pace/temperature only | Weak emotion for drama |
| BreezeBlue hosted | Same as today | Same as today | Same as today | Hindi quality unknown |
| Self-hosted (Chatterbox-hi + Indic Parler + IndicF5) | Indic Parler caption | Chatterbox-hi or IndicF5 | Exaggeration only | Quality, maintenance, IndicF5 licence dispute |

**Suggested evaluation**
- Pick 2–3 candidates and synthesize the same Hindi story excerpt. Include dialogue with emotion, numbers/dates, Hinglish, nukta words and 1,000-character chunks.
- Have native listeners judge it, then pass a dialogue clip through MiniMax H3 to check lip-sync behaviour. No source evaluates TTS→H3 lip-sync for Hindi.
- Per-language voices (Hindi voices designed from the same character description) are the safer default than reusing English voices cross-lingually.

### Gaps
- No source compares how these TTS outputs perform as input to MiniMax H3 lip sync.
- No Hindi-specific scores were extracted per model from the AI4Bharat study (only aggregate and qualitative per-language statements).
- Hosted BreezeBlue Hindi quality, ElevenLabs Voice Design Hindi quality and Gemini custom-voice availability all need hands-on testing.
