# Hindi (Devanagari) rendering, lip-sync, music and publishing for Visio Studio (as of 18 Nov 2026)

Scope: what the output side of Visio Studio (FFmpeg + libass captions, Pillow graphics/thumbnails, Remotion motion graphics, SRT/YTT captions, MiniMax H3 video, image models, ACE-Step 1.5 music, YouTube Data API uploads) needs in order to produce Hindi videos in Devanagari, including mixed Hindi + English (Latin) text.

Local repo facts used below (read directly from the repo on 18 Nov 2026, not web sources):
- `backend/Dockerfile` is `FROM python:3.13-slim` and installs Debian's packaged `ffmpeg` with `apt-get install --no-install-recommends -y ffmpeg`. No FriBiDi or font packages are installed explicitly.
- `backend/app/services/render_commands.py` (line ~809) builds the caption burn filter as `subtitles=filename='…':fontsdir='…'`.
- Pillow text is drawn via `ImageFont.truetype(...)` with no `layout_engine` argument in `graphics_python/canvas.py`, `graphics_templates.py`, `font_metrics.py`, `thumbnail_compose.py`, `placeholder_frame.py`.
- `motion/Dockerfile` is `FROM node:24-bookworm-slim`, runs with no internet at runtime, installs no font packages, and bundles only `Montserrat-ExtraBold.ttf` and `Inter-Medium.ttf` into `public/fonts/`.

---

## 1. Complex script shaping: libass/FFmpeg, drawtext, Pillow, Chrome/Remotion

### Takeaway
All four renderers can shape Devanagari correctly, but each has a configuration trap. The most important one for Visio Studio: FFmpeg's `subtitles` filter (the one the backend uses) silently forced libass's *simple* shaper (no HarfBuzz) until a fix committed on 28 May 2026. Any FFmpeg build older than that, which includes Debian's packaged FFmpeg, will draw broken Devanagari unless you switch to the `ass` filter or pass `shaping=complex` on a fixed build. Pillow needs Raqm, which in pip wheels only turns on if FriBiDi is installed in the image. Chrome/Remotion shapes correctly but needs a bundled Devanagari font.

### Cited Findings
**libass and FFmpeg `subtitles` / `ass` filters**
- FFmpeg docs (9.0.1 filter docs mirror): the `shaping` option has values `auto` (default, "the best available"), `simple` ("fast, font-agnostic shaper that can do only substitutions") and `complex` ("slower shaper using OpenType for substitutions and positioning. **Required for correct rendering of complex scripts such as Arabic, Hebrew, Devanagari and Thai.** Requires libass to be built with HarfBuzz") — [FFmpeg 9.0.1 subtitles filter docs (mirror)](https://ayosec.github.io/ffmpeg-filters-docs/9.0/Filters/Video/subtitles.html)
- FFmpeg commit b08c9c5 "lavfi/vf_subtitles: expose shaping option" (dated 2026-05-28): "The subtitles filter uses the same renderer path but did not expose the option. This left the zero-initialized shaping field to select ASS_SHAPING_SIMPLE implicitly." The fix exposes `shaping` on `subtitles`, defaulting to `auto` — [FFmpeg commit b08c9c5](https://github.com/FFmpeg/FFmpeg/commit/b08c9c5f533e7dced089d12d4526301cc200c16e); companion docs commit says complex shaping "is required for Arabic, Hebrew, Devanagari and Thai and depends on a HarfBuzz-enabled libass build" — [FFmpeg commit 7c176c0](https://github.com/FFmpeg/FFmpeg/commit/7c176c068d0992e277c59bba0e0beea0be47dd46)
- Verified in FFmpeg 7.1 source: `ass_options[]` has `shaping` (default -1 = auto), `subtitles_options[]` has no `shaping` entry, and `config_input` runs `if (ass->shaping != -1) ass_set_shaper(ass->renderer, ass->shaping);` — so the zero value is passed to libass — [FFmpeg release/7.1 vf_subtitles.c](https://raw.githubusercontent.com/FFmpeg/FFmpeg/release/7.1/libavfilter/vf_subtitles.c). In libass, `ASS_SHAPING_SIMPLE = 0` — [libass ass.h](https://raw.githubusercontent.com/libass/libass/master/libass/ass.h)
- libass simple shaping uses only FriBidi; complex shaping uses FriBidi + HarfBuzz and is "required for proper rendering of languages like Arabic, Hindi, Thai"; text is split into "shape runs" sharing the same font, style and script, and each run is shaped independently (secondary source, AI-generated code wiki) — [DeepWiki: libass text shaping](https://deepwiki.com/libass/libass/3.2-text-shaping-and-layout)
- `wrap_unicode` (Unicode line breaking) needs libass ≥ 0.17.0 built with libunibreak; it is on by default except for native ASS input — [FFmpeg 9.0.1 subtitles filter docs (mirror)](https://ayosec.github.io/ffmpeg-filters-docs/9.0/Filters/Video/subtitles.html)
- A 2026 practitioner guide states the `subtitles` filter "uses libass, which uses HarfBuzz and shapes correctly", and gives test strings: `क्षत्रिय` (two conjuncts; a visible halant means shaping failed) and `कि` (the ि sign must appear left of क) — [Addaly: subtitles in Indian languages](https://addaly.com/learn/video-editing/subtitles-in-indian-languages). **This conflicts** with the FFmpeg commit and source above for builds before May 2026; the source code is the stronger evidence.

**FFmpeg `drawtext`**
- Commit 1eeb59a (May 2023, landed in FFmpeg 7.0): "text is now shaped using libharfbuzz", glyph positions accurate to 1/4 pixel, default line height now the font's own; `drawtext_filter_deps="libfreetype libharfbuzz"`, so drawtext needs `--enable-libfreetype --enable-libharfbuzz`; `--enable-libfontconfig` for font fallback/`font=`; `--enable-libfribidi` for `text_shaping` — [FFmpeg commit 1eeb59a (mirror)](https://github.com/aybe/FFmpeg/commit/1eeb59a2099479eeead8cdc0d4586443fb301a8a); FFmpeg 7.0 drawtext has `shape_text_hb()` — [FFmpeg 7.0 doxygen](https://www.ffmpeg.org/doxygen/7.0/vf__drawtext_8c.html)
- Without libharfbuzz, drawtext is "silently disabled" when building FFmpeg ≥ 7 — [Spack PR #47249](https://github.com/spack/spack/pull/47249)
- The patch author's notes: new `font_a`/`font_d`/`top_a`/`bottom_d` variables, `boxw`/`boxh`, `text_align`, `y_align`; line height now from font metrics — [yethie drawtext CHANGES.md](https://github.com/yethie/FFmpeg/blob/master/drawtext/CHANGES.md)

**Pillow**
- libraqm provides "bidirectional text support (using FriBiDi), shaping (using HarfBuzz), and proper script itemization"; "Pillow wheels since version 8.2.0 include a modified version of libraqm that loads libfribidi at runtime if it is installed" — [Pillow: building from source](https://github.com/python-pillow/Pillow/blob/main/docs/installation/building-from-source.rst)
- Pillow maintainer: "To enable Raqm for binary wheels, it is sufficient to install FriBiDi on Linux (Raqm is linked statically but runtime loading is used for its dependency FriBiDi in wheels)" — [Pillow issue #4859](https://github.com/python-pillow/Pillow/issues/4859)
- `PIL.features.check("raqm")` reports whether `ImageFont.Layout.RAQM` is usable; `features.pilinfo()` prints the loaded raqm, fribidi and harfbuzz versions — [Pillow features docs (12.2.0)](https://github.com/python-pillow/Pillow/blob/12.2.0/docs/reference/features.rst); [Pillow features.py](https://github.com/python-pillow/Pillow/blob/master/src/PIL/features.py)
- Raqm support is a runtime property of the environment, not of the Pillow version; without it text is drawn "in typed order" with no error. Advice: log `features.check("raqm")` from the rendering process and pin the base image — [Syamjith NK blog](https://syamjith-nk.github.io/raqm-is-a-runtime-property/)
- `ImageFont.truetype(..., layout_engine=...)`: Raqm is used by default if available, otherwise basic layout (from Pillow API reference; not re-fetched this session) — [Pillow ImageFont reference](https://pillow.readthedocs.io/en/stable/reference/ImageFont.html)

**Chrome / Remotion**
- HarfBuzz is the shaping engine used by Chrome/Chromium (and Firefox, Android, LibreOffice etc.) per its README (not re-fetched this session) — [HarfBuzz GitHub](https://github.com/harfbuzz/harfbuzz)
- "HTML and CSS shape correctly, and a headless browser screenshot gives you a PNG per cue" — [Addaly](https://addaly.com/learn/video-editing/subtitles-in-indian-languages)
- `@remotion/google-fonts` `loadFont()` blocks the render until the font is ready; from Remotion v5 `weights` and `subsets` arrays are required (e.g. `subsets: ['devanagari']`); large fonts on slow networks can cause render timeouts — [Remotion loadFont()](https://www.remotion.dev/docs/google-fonts/load-font); [Remotion font loading errors](https://www.remotion.dev/docs/troubleshooting/font-loading-errors); local font files can be loaded instead — [Remotion: using fonts](https://www.remotion.dev/docs/fonts)

### Inferences
- **Visio Studio captions are probably broken for Hindi today.** The backend burns ASS through `subtitles=filename=…`, on Debian's packaged FFmpeg. Debian's FFmpeg (likely 7.1.x on the trixie-based `python:3.13-slim`; check with `ffmpeg -version`) predates the May 2026 fix, so libass gets `ASS_SHAPING_SIMPLE`. Two fixes, simplest first: (a) switch to the `ass` filter, `ass=filename='…':fontsdir='…'`. It reads `.ass` files, accepts `fontsdir`, and defaults to `shaping=auto`, which is complex when libass has HarfBuzz. (b) On a build containing commit b08c9c5, use `subtitles=…:shaping=complex`. Either way, render `क्षत्रिय`, `कि`, `र्क` (reph) and `श्र` once and compare them with a browser rendering.
- Debian's libass package is built with HarfBuzz and fontconfig (libass has required HarfBuzz since about v0.15; from memory, not verified this session). Check by rendering, not by reading build flags.
- **Pillow in the backend image:** `python:3.13-slim` does not ship FriBiDi, so Raqm is probably unavailable and every `ImageFont.truetype` call falls back to basic layout, which draws Devanagari wrongly with no error. Fix: add the FriBiDi runtime library to the `apt-get install` line (the Debian package is `libfribidi0`; name from memory). Then assert `features.check("raqm")` at startup and pass `layout_engine=ImageFont.Layout.RAQM` explicitly for Hindi text, so a missing Raqm fails loudly instead of degrading. Text measurement (`font_metrics.py`) must use the same engine, because basic and Raqm layouts give different widths.
- Pillow loads one font file per `truetype` call and does not fall back to another font. Mixed Hindi + English strings must use one font that has both Devanagari and Latin (most Devanagari Google Fonts do, see section 2), or the code must split the string into runs by script. Inter and Montserrat have no Devanagari glyphs.
- **drawtext** (not currently used for captions) shapes Devanagari on FFmpeg ≥ 7.0 built with HarfBuzz. It is still a poor fit for word highlighting and mixed-font lines; libass or Remotion are better.
- **Remotion motion container:** Chrome will shape correctly, but the container is offline and has no system fonts. `@remotion/google-fonts`, which fetches at render time, will not work. Copy the Devanagari font files into `public/fonts/` at build time (as already done for Inter/Montserrat) and load them with `@font-face`/`@remotion/fonts`. Without a bundled font, Devanagari will render as tofu (empty boxes), since there is no fallback font in `node:24-bookworm-slim`.

### Gaps
- I did not confirm the exact FFmpeg version in the current `python:3.13-slim` (Debian) image, or whether a released FFmpeg version number (8.x/9.x) contains commit b08c9c5. The 9.0.1 docs mirror lists the option, which suggests 9.0 has it.
- No empirical render test was run in this session. A one-off container render of the test strings would settle the libass/Pillow questions definitively.
- Whether Chrome shapes across differently coloured `<span>`s, which matters for sub-word highlighting in Remotion, was not researched.

---

## 2. Fonts for Hindi captions, headlines and motion graphics; vertical metrics

### Takeaway
Use OFL fonts from Google Fonts that cover both Devanagari and Latin, so mixed Hindi + English lines can be set in one font. Noto Sans Devanagari (9 weights, 100–900) is the safest caption and body font. Mukta (7 weights), Hind (5), Poppins (9 + italics, geometric like Montserrat) and Anek Devanagari (variable 100–800) suit UI, headlines and motion graphics. Baloo 2, Rozha One, Yatra One, Kalam and Tiro Devanagari Hindi are display or serif accents. Allow roughly 20–30% more line height than for Latin text.

### Cited Findings
- 65 Google Fonts families list the Devanagari subset. Weights include: Anek Devanagari 100–800 (2022), Baloo 2 400–800, Hind 300–700 (5), IBM Plex Sans Devanagari 100–700 (7), Kalam 300–700 (3), Martel 200–900 (7), Martel Sans 200–900 (7), Mukta 200–800 (7), Noto Sans Devanagari 100–900, Noto Serif Devanagari 100–900, Poppins 100–900 (9) + italic, Rozha One 400, Tiro Devanagari Hindi 400 + italic (2022), Yantramanav 100–900 (6), Yatra One 400, Khand/Rajdhani/Teko (condensed, 300–700) — [typefacefiles: Devanagari in Google Fonts](https://typefacefiles.online/script/devanagari/) (third-party index built from Google Fonts metadata)
- Noto Sans Devanagari: unmodulated sans, 954 glyphs, Thin 100 to Black 900 — [Google Fonts: Noto Sans Devanagari](https://fonts.google.com/noto/specimen/Noto+Sans+Devanagari)
- Mukta: 200–800, no italic, subsets devanagari + latin + latin-ext, designer Ek Type, licence OFL; Inter has 9 weights and no Devanagari — [FontFYI Inter vs Mukta](https://fontfyi.com/compare/inter-vs-mukta/); [Google Fonts: Mukta](https://fonts.google.com/specimen/Mukta)
- Hind (Indian Type Foundry) 300–700 — [Google Fonts: Hind](https://fonts.google.com/specimen/Hind); Poppins (Indian Type Foundry, Jonny Pinhorn, Ninad Kale), 18 styles with Devanagari — [Google Fonts: Poppins](https://fonts.google.com/specimen/Poppins); Tiro Devanagari Hindi (Tiro Typeworks, John Hudson, Fiona Ross) Regular + Italic — [Google Fonts: Tiro Devanagari Hindi](https://fonts.google.com/specimen/Tiro+Devanagari+Hindi)
- Baloo 2: display face by Ek Type, five weights Regular–ExtraBold, each family is one Indic script + Latin + Latin Extended + Vietnamese, SIL OFL 1.1 — [EkType/Baloo2](https://github.com/EkType/Baloo2)
- Noto is SIL OFL and "its shaping tables are complete and well tested". Alternatives: Mukta, Hind, Rozha One, Baloo, Yantramanav. "Indic scripts need more vertical space… a line height that is comfortable for English clips the matras. Increase line spacing by 20 to 30%." Mixed-script captions need an intentional pairing or a family covering both scripts — [Addaly](https://addaly.com/learn/video-editing/subtitles-in-indian-languages)
- Pairings recommended for screens: Inter + Noto Sans Devanagari ("clean modern tech"), Poppins + Mukta ("friendly commercial"), Playfair Display + Rozha One (editorial). Devanagari body text needs at least `line-height: 1.8`, against 1.5–1.6 for Latin. Match optical size and stroke weight rather than point size — [Susania: multilingual typography](https://susania.com/blog/multilingual-typography-font-pairing-india)
- Anek Devanagari (Anek superfamily, variable weight axes) is suggested for Devanagari headlines with Inter body text — [Font Fusion: Anek Devanagari + Inter](https://font.csskey.com/pair/anek-devanagari-inter)
- The Netflix Hindi guide uses "Mangal as a generic placeholder for proportional SansSerif", white, sized to fit 42 characters across the screen — [Netflix Hindi Timed Text Style Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/115003196707-Hindi-Timed-Text-Style-Guide)

### Inferences
- **Pairing with the existing brand fonts.** Inter (captions, UI) pairs with Noto Sans Devanagari or Mukta. Montserrat ExtraBold (headlines) is geometric, so Poppins Bold/ExtraBold (also geometric, with Devanagari) or Anek Devanagari Bold are the closest Devanagari headline matches. Because Poppins and Mukta contain Latin, mixed lines can be set entirely in the Devanagari font. This avoids per-run font switching in Pillow and libass, at the cost of the English words not being in Inter/Montserrat.
- **Weights.** For burned captions with outlines, Noto Sans Devanagari or Mukta at 500–700 survive video compression better than 400 (general video-caption practice; not specifically sourced). Rozha One, Yatra One and Tiro Devanagari Hindi each have only one weight (Tiro adds an italic), so they suit occasional accents, not systems that need bold/regular hierarchies.
- **Vertical metrics in each renderer.** In ASS, increase `MarginV` and keep the box (`BorderStyle=3`) padding large enough for above-base matras/anusvara (ि ी े ै ं ँ) and below-base marks (ु ू ृ ्). In Pillow, compute line advance from the font's ascent + descent (`font.getmetrics()`) rather than from the glyph bbox of the sample text. In Remotion/CSS use `line-height` about 1.3–1.5 for one- or two-line callouts (the ≥1.8 figure is for paragraph body text). These numbers are inferred and should be checked visually.
- Licence: all fonts named above are distributed by Google Fonts. Baloo 2, Mukta and Noto are confirmed OFL above; OFL allows bundling in a Docker image and burning into video. Keep each family's `OFL.txt` next to the font files.

### Gaps
- I did not confirm each remaining family's licence file (Hind, Poppins, Martel, Kalam, Rozha One, Yatra One, Anek, Tiro) individually; Google Fonts lists them, and to my knowledge all are OFL.
- No source compared Devanagari fonts specifically for legibility in burned-in, compressed video.

---

## 3. Hindi caption conventions, segmentation and word-by-word highlighting

### Takeaway
Netflix's Hindi guide allows 42 characters per line, at most 2 lines (prefer one, bottom-heavy pyramid), and 22 characters per second for adults (up to 25 in SDH). It has no italics, no space before the danda ।, and specific number rules. Break lines only at spaces or after punctuation, never inside a word. Segment text into extended grapheme clusters using Unicode 15.1+ rules (ICU ≥ 76), which keep Devanagari conjuncts together. Word-level karaoke in libass is safe because Hindi words are space-separated. Highlighting part of a word (syllable or akshara) is risky, because override tags inside a word can split shaping runs and break conjuncts or matra placement.

### Cited Findings
**Netflix Hindi Timed Text Style Guide** — [Netflix Partner Help Center](https://partnerhelp.netflixstudios.com/hc/en-us/articles/115003196707-Hindi-Timed-Text-Style-Guide) (also mirrored at [Netflix Studio Knowledge Hub](https://studiopartner.netflix.net/studio/hindi-timed-text-style-guide))
- 42 characters per line; maximum two lines; keep to one line unless it exceeds the limit; prefer a bottom-heavy pyramid but avoid only one or two words on the top line.
- Reading speed: adult up to 22 cps, children up to 18 cps. In the SDH section it can be raised to 25 / 20 cps.
- "Do not use italics"; titles go in double quotes. English titles and words are transliterated into Devanagari, e.g. आज मैं थिएटर में "हैमिल्टन" देखने गया था। SDH rule: "English words used in a mostly Hindi line of dialogue do not require identifiers, but should be transliterated (with correct spelling)."
- "There should be no spaces after text and before punctuation marks". The examples end sentences with the danda and no preceding space: `हमें बस दो और कक्षाएँ पास करनी हैं।`, `-आओ भी! -नहीं।`
- Ellipsis must be the single character U+2026. Do not use an ellipsis when a sentence simply continues into the next subtitle. Dual speakers use a hyphen *without* a space, one speaker per line.
- Numbers: 1–10 spelled out, 11+ as numerals; spell out a number that starts a sentence. Ordinals 1st–9th spelled out (पहला, दूसरा, नौवाँ), from 10th numeral + वीं (10वीं). Decades as "20 का दशक". Decimal point "16.8", thousands comma "50,000", time "8:30". Currency is not written with symbols but transliterated ("10 डॉलर", "20 मिलियन डॉलर").
- Abbreviation suggestions (e.g. Dr. → डॉ., % → प्रतिशत). Lyrics are enclosed in ♪ with only ? or ! at line end.
- Netflix counts spaces and punctuation toward character count and reading speed — [Netflix: how reading speed is measured](https://partnerhelp.netflixstudios.com/hc/en-us/articles/115001352212-How-is-reading-speed-measured-Do-punctuation-and-spaces-count)
- Conflicting secondary source: an India OTT spec roundup cites 17 cps adult / 13 children as the Netflix limit. That is the *general* figure; the Hindi-specific guide says 22/18 — [Buttercut: OTT subtitle specs India 2026](https://www.buttercut.ai/blog/ott-subtitle-specs-india)

**Segmentation (UAX #29, ICU)**
- Unicode 15.1 (Sept 2023) added grapheme-cluster rule GB9c, which uses the new `Indic_Conjunct_Break` property so that consonant + virama + consonant sequences stay in one cluster. It initially covered Bengali, Devanagari, Gujarati, Oriya, Telugu and Malayalam — [W3C iip issue #87](https://github.com/w3c/iip/issues/87); [Unicode 15.1.0](https://unicode.org/versions/Unicode15.1.0/)
- ICU 74 "does not yet support Indic_Conjunct_Break" — [ICU 74](https://icu.unicode.org/download/74); the property arrived in ICU 76 (ICU-22503) — [ICU commit 06c077b](https://github.com/unicode-org/icu/commit/06c077bd35b3b5950c17ac610ef94803fbf756ab); [ICU 76 notes](https://unicode-org.github.io/icu/download/76.html)
- In Devanagari, shaping reorders characters: the pre-base matra ि is typed after the consonant but drawn before it, and reph (र्) is moved to the end of the syllable. Shaping operates per syllable cluster — [Microsoft: Developing OpenType fonts for Devanagari](https://learn.microsoft.com/en-us/typography/script-development/devanagari); [OpenType shaping documents: Devanagari](https://fontspec.org/opentype-shaping/opentype-shaping-devanagari.html)

**Karaoke / word highlighting in libass**
- `\k` = instant switch, `\K`/`\kf` = left-to-right sweep, `\ko` = outline variant. Durations are in centiseconds and accumulate within the event. The sweep moves across the *rendered* unit, not per code point — [Emby: subtitle karaoke timing](https://emby.media/learn/articles/subtitles/rendering/fonts-typesetting/Subtitle-Karaoke.html)
- libass (matching VSFilter) treats "any following run split as a karaoke delimiter rather than only the next karaoke tag". Changing font or style partway through a word makes part of the word highlight with the next word; maintainers say this is required for compatibility — [libass issue #638](https://github.com/libass/libass/issues/638)
- libass splits text into shape runs by font, style and script, and karaoke word boundaries are where a new run starts (secondary, AI-generated wiki) — [DeepWiki: libass tag processing](https://deepwiki.com/libass/libass/3.1-text-parsing-and-tag-processing)
- Sidecar `.srt`/`.vtt` files uploaded to a platform are rendered by the platform's own text engine, which shapes complex scripts correctly — [Addaly](https://addaly.com/learn/video-editing/subtitles-in-indian-languages)

### Inferences
- **Word-level highlighting is the safe default.** Put one `{\k}`/`{\kf}` tag before each space-separated Hindi word, matching the current English word-by-word design. Each word is then a whole shaping run, so conjuncts, reph and the reordered ि stay correct, and a `\kf` sweep moves visually left-to-right across the shaped word.
- **Avoid sub-word highlighting.** A tag between ि and its consonant, or between the parts of a conjunct (e.g. inside क्ष), would likely split a shaping run (DeepWiki, libass #638). The result could be a dotted-circle glyph, a visible halant, or a matra on the wrong side. If syllable timing is ever needed, highlight at UAX #29 extended-grapheme-cluster boundaries computed with ICU ≥ 76 and test visually; even then a cluster boundary is not always a safe shaping boundary.
- **Line breaking for burned captions:** break only at spaces, never before ।, ?, ! or the closing quote, and never inside a word. libass's `wrap_unicode` (UAX #14 via libunibreak) can do this automatically, but it is off for native ASS input, so Visio Studio's own line-splitting code must apply the rule when it writes `\N`.
- **Character counting:** to apply the 42-character / 22-cps limits, count something consistent. Code points overcount Hindi (matras and virama are separate code points), while grapheme clusters are closer to what readers see. Netflix's guide does not say which it uses (see Gaps).
- **Mixed Hindi + English captions:** two conventions are in use. Netflix transliterates English words into Devanagari; many YouTube Hindi channels keep English terms in Latin, or write the whole caption in Roman Hinglish (see section 7). Pick one per channel.
- **YTT (srv3) and SRT sidecars:** YouTube renders these with its own text engine, so shaping is handled. Per-word segments in YTT break at word boundaries, which is safe. Splitting a word into several timed segments might break shaping in the YouTube player; this is untested.

### Gaps
- Netflix's guide does not say whether Devanagari combining marks count toward the 42-character / cps limits.
- I found no documentation or test of libass karaoke specifically on Devanagari sub-word tags. The run-splitting risk is inferred from general libass behaviour.
- Whether Python's `regex` module (`\X`) or other non-ICU segmenters implement Unicode 15.1 GB9c was not verified.
- Word-level timing alignment for Hindi speech (forced aligner or ASR with Hindi support) was outside this research and needs separate verification.

---

## 4. Video lip-sync: MiniMax H3 (Ref2VA) with Hindi dialogue

### Takeaway
MiniMax H3 is not "audio-driven" in the classic lip-sync sense. It generates its own voice and the mouth movement together, with the dialogue text written in the prompt under a language tag. Reference audio is officially a voice-timbre reference. Hindi is **not** among H3's 11 "stable" dialogue languages ("additional languages… to varying degrees"), and one tester reported that Hindi didn't work. Expect H3's own Hindi speech to be unreliable, and plan to discard H3's audio track, overlay the Hindi TTS, and QA the sync. Practitioners report that passing the exact dialogue audio (length-matched, with ≥ 0.9 s lead silence) makes the mouth follow its timing. Keep a dedicated lip-sync model as a fallback.

### Cited Findings
- H3 model card: output 4–15 s, 24 fps, 32 kHz stereo audio. "Supported dialogue languages: Stable support for 11 languages: Arabic, Chinese, English, French, German, Italian, Japanese, Korean, Portuguese, Russian, and Spanish. Additional languages are also supported to varying degrees." Ref2VA accepts up to 9 images, 3 videos and 3 audio clips, each audio 2–15 s with total ≤ 15 s; audio cannot be the sole input; 12 files max — [MiniMax-H3 Hugging Face model card](https://huggingface.co/MiniMaxAI/MiniMax-H3); [MiniMax news: H3 open source](https://www.minimax.io/news/minimax-h3-open-source)
- In the official Ref2VA example (H3-Context-IR output), one audio input is "the voice timbre reference" and the model "animates [the character's] face to speak the user-provided dialogue". Dialogue is written inline in English in the prompt with a language tag, e.g. "(S1) speaks softly, [English] Follow the wind, live free." Video and audio latents are predicted jointly by one transformer — [MiniMax-H3 model card](https://huggingface.co/MiniMaxAI/MiniMax-H3)
- H3-Context-IR, the prompt-rewriting stage that MiniMax "strongly recommend[s]", is not open source; it is available as an API, or you follow MiniMax's Prompting Guidance — [MiniMax-H3 model card](https://huggingface.co/MiniMaxAI/MiniMax-H3)
- Licence: "MiniMax H3 Community License Agreement", with an application form "only for USA/EU/UK/South Korea"; inputs and enhanced prompts are moderated on the hosted service — [MiniMax-H3 model card](https://huggingface.co/MiniMaxAI/MiniMax-H3)
- Atlas Cloud test (2026): "the mouth follows whatever voice the model produced, because the mouth and the voice were produced together". "The reference audio must say a different sentence than the one you want in the video. It is a timbre anchor… The lines come from the prompt." Changing the language tag (e.g. `[English]` to `[Japanese]`) changes the mouth. For "a finished clip whose mouth needs to speak a new language", use a patch lip-sync model (`sync/lipsync-v3`, $0.22/s), because H3 "does not modify your existing render". Lip sync breaks with long scripts crammed into short durations, missing performance direction, and multi-speaker scenes. The prompt should request "no text anywhere in the frame" so captions don't fight baked-in lettering — [Atlas Cloud: MiniMax H3 lip sync and audio](https://www.atlascloud.ai/blog/tips/minimax-h3-lip-sync-and-audio)
- ALTOLTA practitioner record (ComfyUI `MiniMaxH3ReferenceToVideo` node): passing pre-made Japanese TTS dialogue to `ref_audios` made "the character's mouth move in sync with that speech timing". They still remove H3's audio and overlay the original TTS because H3's own Japanese speech "is not yet of practical quality". Recipe: match the reference length exactly to the clip; ≥ 0.9 s lead silence (< 0.5 s "will always fail"); make pauses with silence, not prompts; for 2+ speakers pass overall + per-speaker audio (fixed 12/12 cross-talk errors); use dot notation `ref_audios.ref_audio_0` or the inputs are silently ignored — [ALTOLTA on note.com](https://note.com/altolta_428/n/n51b674a65091?hl=en)
- Conflict: Atlas Cloud says reference audio is only a timbre anchor and should differ from the spoken line. ALTOLTA found that passing the *same* line's audio drives mouth timing. Both agree that H3's output audio is generated by H3.
- Spoken-Hindi comparison of five video models (LinkedIn post, weak source): for H3, "the video looks a bit too smooth, and Hindi wasn't there" — [LinkedIn: da sachin sharma](https://www.linkedin.com/posts/dasachin_aivideo-generativeai-aifilmmaking-activity-7490735823517118464-hfxq). Another LinkedIn post claims a text-to-video test of H3 with Indian regional languages and accents, but its content could not be read — [LinkedIn: Kandrapa Bhuyan](https://www.linkedin.com/posts/kandrapa-bhuyan-b062b4169_aivideo-activity-7490834091836375041-7q9r)
- Sponsored English review: dialogue "about 90%", "slight delay in the lip sync of the first character" — [YouTube: Minimax H3 filmmaking test (sponsored)](https://www.youtube.com/watch?v=JsttNJib1z8)

### Inferences
- **Prompt language:** keep the scene, camera and character description in English, since MiniMax's examples and IR format are English. Put the Hindi dialogue inside the dialogue markup with a Hindi language tag (e.g. `[Hindi] …`) so the generated mouth shapes target Hindi phonemes. Whether to write the line in Devanagari or romanized Hindi is untested (see Gaps). An English line paired with Hindi audio would invite mismatched mouth shapes.
- **Will H3 add or alter speech? Yes, it can.** H3 writes its own audio track from the prompt, so its Hindi may mispronounce words, change wording, add filler or drift in timing. Since Hindi is outside the stable 11, the pipeline should always: (1) pass the Hindi TTS clip with ≥ 0.9 s lead silence, length-matched to the shot; (2) strip H3's audio and mux the original TTS; (3) QA sync, e.g. by comparing H3's own audio envelope with the TTS envelope (ALTOLTA's "waveform correlation") and rejecting clips that diverge; (4) fall back to a dedicated audio-driven lip-sync pass on a no-dialogue H3 shot when QA fails.
- Classic audio-driven lip-sync models (mouth-region patching from audio) are generally language-agnostic because they map phoneme-like acoustics to visemes. I found no 2025–2026 Hindi-specific benchmark (see Gaps).

### Gaps
- No MiniMax documentation lists which "additional languages" work, or how well Hindi does.
- No source tested Devanagari vs romanized Hindi in H3 prompts.
- No independent 2025–2026 benchmark of Hindi lip-sync quality for H3, Hailuo, or dedicated lip-sync models (sync/lipsync-v3, LatentSync, MuseTalk etc.) was found.

---

## 5. Text inside generated images (frames, thumbnails, signage)

### Takeaway
No image model renders Devanagari reliably enough to publish without review as of late 2026. Tests show broken shirorekha (the headline bar), misplaced matras and malformed conjuncts even in the best models. Generate images with **no text**, and overlay Hindi programmatically (Pillow with Raqm, or Remotion/Chrome) for thumbnails, signage and cards.

### Cited Findings
- Nano Banana 2 (gemini-3.1-flash-image-preview) six-script test: Devanagari is a "Partial pass… human review mandatory". Base characters are mostly right; some vowel signs are misaligned or clipped; the conjunct ब्र has shape inconsistencies; the shirorekha is "mostly continuous but with breaks". Latin, Chinese, Japanese and Korean pass — [JuheAPI: Nano Banana 2 text test](https://www.juheapi.com/blog/nano-banana-2-text-in-image-quality-testing-ai-text-in-image-generation-across-6-languages)
- Indian-creator test (May 2026), Hindi text stars: Ideogram v3 ★5, Nano Banana 2 ★4, Imagen 4 ★4, GPT Image 2 ★3, Seedream v5 Lite ★3, Flux 2 Pro ★2. "No model currently renders complex Hindi text with 100% accuracy — always review the output" — [AIClips: best AI image generator India 2026](https://blog.aiclips.net/2026/05/22/ai-image-generator-india-2026/)
- OpenAI *claims* about 99% character-level accuracy for GPT Image 2 "across Latin, CJK, Hindi, and Bengali scripts" (vendor claim reported by press). This conflicts with AIClips' ★3 rating — [Decrypt: GPT Image 2 vs Nano Banana 2](https://decrypt.co/366408/openai-gpt-image-2-vs-google-nano-banana-2-review)
- Large October 2026 text benchmark (GPT Image 2.5, Nano Banana 2.1, Grok Imagine 2.0, Seedream 5.0 Pro, Qwen-Image 3.0 Pro) covered Latin, Chinese, Japanese and Arabic but **not Devanagari**. On Arabic, the closest complex-script proxy: Nano Banana 55/57, GPT Image 53/57, Grok 42/57, Seedream 34/54, Qwen-Image 8/59 — [AIFont: best image model for text (2026)](https://aifont.ai/blog/best-image-generation-model-for-text)
- Seedream 5 Pro text accuracy 89.5% vs GPT Image 2 98.5% vs Nano Banana 2 91.2% (Atlas Cloud benchmark, mostly Latin); small or background text "drifts" into near-words — [CreateVision: Seedream 5 vs Nano Banana 2 vs GPT Image 2](https://createvision.ai/guides/seedream-5-vs-nano-banana-2-vs-gpt-image-2)
- Rendering text elsewhere and importing it as an image is "the most reliable route" for Indic titles — [Addaly](https://addaly.com/learn/video-editing/subtitles-in-indian-languages)

### Inferences
- For thumbnails and evidence cards, prompt image models for "no text, no lettering, blank signs" and overlay Hindi in Pillow (with Raqm on) or Remotion. This also keeps the overlay text editable and searchable. Qwen-Image's very weak Arabic score suggests weak non-Latin, non-CJK text in general, so do not rely on it for Devanagari.
- If in-image Hindi is ever wanted (e.g. a shop sign inside a scene), use the strongest models (Ideogram v3, Nano Banana 2.x, GPT Image 2.x), keep it to 1–3 short words, and have a Hindi reader review it.
- Video frames from H3 should likewise avoid baked-in text (Atlas Cloud, section 4).

### Gaps
- No rigorous 2026 benchmark covering Devanagari across Seedream 4.x/5, Qwen-Image, FLUX, Ideogram, GPT-Image and Nano Banana with native-reader judging was found; the available Hindi tests are small or blog-level.

---

## 6. Music: ACE-Step 1.5 with Hindi lyrics

### Takeaway
ACE-Step 1.5 officially accepts Hindi: `vocal_language="hi"` is in its valid-language list, and lyrics are free text up to 4096 characters. Quality for Hindi is undocumented. One LoRA author says the base model was trained mostly on Western music and gives generic results for Indian genres. No official guidance says whether lyrics should be in Devanagari or romanized, so A/B test both.

### Cited Findings
- `VALID_LANGUAGES` in ACE-Step 1.5 includes `'hi'`, and also `'ur'`, `'pa'`, `'bn'`, `'ta'`, `'te'`, `'ne'`, `'sa'` among about 50 codes plus `'unknown'` — [ACE-Step-1.5 constants.py](https://github.com/ace-step/ACE-Step-1.5/blob/6d467e4b/acestep/constants.py); the same list is exposed by a hosted API's `language` parameter — [Vultr: ACE-Step 1.5](https://api.vultrinference.com/docs/models/ace-step-1.5)
- Inference API: `lyrics` "Supports multiple languages. Max 4096 characters"; `vocal_language` is an ISO 639-1 code, with `"unknown"` for auto-detect; `caption` max 512 characters; `create_sample(..., vocal_language=...)` can constrain LM-written lyrics to a language (example uses Bengali `"bn"`) — [ACE-Step 1.5 inference docs](https://ace-step.github.io/ACE-Step-1.5/en/INFERENCE)
- The ACE-Step Transcriber, used to label ACE-Step 1.5's training data, lists Hindi (hi) among its 50+ languages for speech and singing transcription — [ACE-Step/acestep-transcriber](https://huggingface.co/ACE-Step/acestep-transcriber)
- RagaLoRA (community LoRA): "The base ACE-Step 1.5 model was trained mostly on Western music and produces generic output for Indian genres". The adapter targets Bollywood ballad, ghazal, bhajan, indie Hindi, Hinglish pop etc. Its example passes romanized lyrics with `vocal_language="hi"` — [RagaLoRA on Hugging Face](https://huggingface.co/veeceey/RagaLoRA-indian-music-ace-step)

### Inferences
- Supply lyrics in Devanagari first. It is the native script, and the transcriber that labelled the training data presumably output Devanagari for Hindi, though that is unverified. Set `vocal_language="hi"` explicitly rather than `unknown`. A/B test romanized lyrics, which some users use, and listen for pronunciation of conjuncts and nasalisation.
- Keep `caption` (style prompt) in English; it is a style description, separate from the lyric language.
- For karaoke lyric captions from ACE-Step output, word timings will need alignment (the hosted API mentions `timestamps`); check that its timestamps work for Devanagari.
- Consider the RagaLoRA adapter (or similar) for Indian styles; check its licence before use.

### Gaps
- No official ACE-Step 1.5 quality notes or samples for Hindi vocals were found.
- No guidance was found on Devanagari vs romanized lyric input.
- ACE-Step 1.5's licence was not verified in this session (check the repo's LICENSE file).

---

## 7. YouTube publishing: API language fields, multi-language audio, Hindi channel practice

### Takeaway
Set `snippet.defaultLanguage="hi"` and `snippet.defaultAudioLanguage="hi"` for Hindi videos. Add translated titles and descriptions through `localizations`, and upload a Hindi caption track (`hi`). Multi-language audio (one video with English and Hindi tracks) works only through YouTube Studio for eligible channels. An `audiotracks` upload method briefly appeared in the API discovery document in April 2026 but was removed days later, and is absent from the official revision history (updated 17 Nov 2026). For titles, Hindi viewers mostly *type* Roman Hinglish, while ranking titles often mix scripts, so bilingual titles are common.

### Cited Findings
**Data API fields**
- `snippet.defaultLanguage`: "The language of the text in the video resource's snippet.title and snippet.description properties"; `snippet.defaultAudioLanguage`: "the language spoken in the video's default audio track"; `localizations.(key)` key is a BCP-47 code with `.title` and `.description`; `snippet.localized` is read-only (returned when `hl` is passed) — [YouTube Data API: videos resource](https://developers.google.com/youtube/v3/docs/videos)
- The `captions` resource takes a `snippet.language` (BCP-47, e.g. `hi`) and `snippet.name` on `captions.insert` (from the API reference; not re-fetched this session) — [YouTube Data API: captions](https://developers.google.com/youtube/v3/docs/captions)
- Revision history, last updated 2026-11-17: 2026 entries cover co-view counts, posts (pilot), thumbnails for Shorts, granular quota for `videos.insert` and `search.list` (June 2026), upload cost about 100 units (Dec 2025), and that unverified-project uploads are no longer forced private. **No audio-track method is listed** — [YouTube Data API revision history](https://developers.google.com/youtube/v3/revision_history)

**Multi-language audio**
- YouTube Help: multi-language audio lets creators upload dubbed tracks for new or existing videos (and Shorts), plus per-language thumbnails for long-form. It is available to creators with access to Advanced features. Tracks are added in **YouTube Studio on desktop** (Languages → Add language → Dub → Add); files must be audio-only and "roughly the same length as your video". An existing auto-dub for that language must be deleted first. A secondary track whose copyrighted content differs from the original "may be removed". The player defaults to the viewer's preferred language, and translated titles and descriptions are used in search — [YouTube Help: multi-language features](https://support.google.com/youtube/answer/13338784?hl=en)
- The API discovery document gained `youtube.media.upload` "Inserts a new AudioTrack for a video" (`POST /upload/youtube/v3/audiotracks?videoId=…&language=<BCP-47>`, scopes include `youtube.upload`) on about 28 Apr 2026 — [gcpapichanges: addition](https://gcpapichanges.com/changes/1777377600-youtube:v3.html) — and the same method was listed under **Deletions** about 1 May 2026 — [gcpapichanges: deletion](https://gcpapichanges.com/changes/1777636800-youtube:v3.html)
- As of 12 Aug 2026, "the public YouTube Data API documentation does not document a standard method for uploading Multi-Language Audio tracks"; options are manual Studio handoff, partner workflows, or uploading a separate localized video — [DubLab: YouTube dubbing API workflow](https://dublab.app/blog/youtube-dubbing-api)
- Open-source tool ytmla: "Multi-language audio has no Data API endpoint". Localized titles and descriptions via API are "proven"; attaching audio requires driving Studio with Playwright (selectors "unverified"). Studio rejects tracks that don't match video length ("Audio tracks must match video length") — [cryptotech407/ytmla](https://github.com/cryptotech407/ytmla)

**Hindi channel practice (titles, tags, search)**
- Hindi searches come in English, Roman Hindi and Devanagari forms; check YouTube autocomplete in all three. Devanagari works well for devotional content, older or rural audiences and regional news; Roman Hindi or English for tech, gaming, finance and education. Bilingual titles (main searchable phrase first, other script second) are "often the safest"; state the language ("Hindi", "हिंदी में"); put tags and description lines in both scripts; choose one caption script per video — [Shinel Studios: Hindi & Hinglish YouTube SEO](https://shinelstudios.in/blog/hindi-hinglish-youtube-seo)
- October 2026 autocomplete study, 10,781 phrases across 30 digital-marketing/AI topics: **0** contained Devanagari, and "kaise" beat "how to" 965 to 380. Yet among 214 ranking titles, 14% used Devanagari and 68% used a pipe to combine both languages. Caveats: autocomplete is a proxy, not volume; one niche; causation not tested; nothing measured about click-through — [Pretutorials: How India searches YouTube](https://pretutorials.com/blog/how-india-searches-youtube-hinglish-data)
- Keep brand, product, exam and app names in Roman script (iPhone, UPSC); read your comments to see which script viewers use; keep the choice consistent across the channel — [Videxa: Hindi title guide](https://videxa.in/tools/hindi-youtube-title-generator); use your channel's Search terms report — [InditubeDB: YouTube SEO India 2026](https://www.inditubedb.com/guides/youtube-seo-india)

### Inferences
- Simplest publishing model for Visio Studio: render a separate Hindi video, upload it with `videos.insert` (`defaultLanguage`/`defaultAudioLanguage = "hi"`), add a Hindi caption track, and optionally add an English `localizations.en` entry. Fully automatable today.
- Multi-language audio on a single video (an English original plus a Hindi dub) is possible, but in 2026 only through Studio or browser automation. It also needs the Hindi track's length to match the English video's, and the shots and lip-sync are the English ones, so it suits narration-only videos better than lip-synced dialogue.
- Visio Studio's title generation should support a bilingual pattern, e.g. Roman Hinglish or English keywords first, then `|`, then Devanagari. Generate tags and description lines in both scripts.

### Gaps
- Why the April 2026 `audiotracks` method was removed, and whether it is in a private pilot, is unknown.
- No YouTube-official guidance on Devanagari vs Roman titles for search ranking was found; the evidence is from agencies and blogs.

---

## 8. Indian number formatting in on-screen graphics

### Takeaway
Hindi media use Western digits (0–9) with lakh/crore wording and Indian digit grouping (1,00,000; 1,00,00,000). Devanagari digits (०–९) are valid but uncommon in mainstream news and YouTube graphics. For graphics, use forms like "₹2.5 लाख करोड़" or "1.2 करोड़", and never mix digit sets inside one number.

### Cited Findings
- Indian numbering: lakh = 10^5 (1,00,000), crore = 10^7 (1,00,00,000). Grouping is three digits then pairs; "lakh crore" = 10^12. Formal Indian English publications use lakh/crore for Indian currency and international numbering for foreign currencies — [Wikipedia: Indian numbering system](https://en.wikipedia.org/wiki/Indian_numbering_system)
- Union Budget 2026-27 documents use crore, lakh and "lakh crore" throughout, and arab/kharab/neel "zero times" (an analysis of the English budget documents) — [RecaTools: South Asian number ladder](https://recatools.com/guides/south-asian-number-ladder/); "₹1.5 lakh crore" is the RBI, Budget and newspaper form — [ToolDabba number-to-words](https://tooldabba.com/number-to-words/)
- Western and Devanagari digits read the same ("3,45,678 and ३,४५,६७८"). International grouping appears in technical or imported material; "Mixed digit sets inside one numeral are poor typography; choose one set consistently" — [Elon.io: Indian digit grouping](https://elon.io/grammar/hindi/numbers-measurement/indian-digit-grouping-and-commas)
- Amar Ujala, a major Hindi news site, presents numbers in Western digits with Indian grouping (e.g. "1,00,00,000" for करोड़) and shows Devanagari digits only as a reference column — [Amar Ujala: Indian number system](https://www.amarujala.com/photo-gallery/education/what-is-indian-numbering-system-know-about-arab-trillion-neel-padma-shankh-etc)
- Netflix Hindi subtitles use Western digits ("11, 12", "50,000", "16.8", "8:30", "10वीं") and transliterated currency words instead of symbols ("10 डॉलर") — [Netflix Hindi Timed Text Style Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/115003196707-Hindi-Timed-Text-Style-Guide)

### Inferences
- Visio Studio needs a small Indian-number formatter for Hindi graphics: Indian grouping, plus scale words लाख/करोड़ (and "लाख करोड़" for 10^12), with an option to output international grouping for foreign figures (e.g. "$20 मिलियन" or "20 मिलियन डॉलर"). Netflix's no-symbol currency rule is for subtitles; on-screen news graphics commonly use ₹ (not sourced; verify against channel examples).
- The Constitution of India (Art. 343) specifies the "international form of Indian numerals" for official Union purposes. This is well known but was not re-verified this session; it explains why Western digits dominate.
- Make sure the chosen Devanagari font has the ₹ (U+20B9) glyph; Noto Sans Devanagari, Mukta and Poppins very likely do, but check.

### Gaps
- No systematic survey of Hindi TV news (Aaj Tak, ABP, Zee) or Hindi YouTube on-screen graphics was found. The claim that they use Western digits with लाख/करोड़ rests on Hindi news websites and general practice, not a measured study.
