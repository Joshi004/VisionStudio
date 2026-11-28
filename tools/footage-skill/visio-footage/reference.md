# Capture tool reference (footage)

`TOOL` is the command written at the top of `SKILL.md`. Run it from the round folder (the folder that holds `brief/`). Every command also has `--help`. In examples, `"..."` stands for text you write yourself.

Exit codes: `0` done, `1` refused or checks failed (the message says what to change), `2` wrong usage.

The tool writes the whole `result.json`. You never edit it.

## Ids

- Mark ids come from the brief (`f1`, `f2`, ...). Use only those.
- Piece ids are `p1`, `p2`, `p3`, ... one per piece of a mark, at most `rules.max_pieces_per_mark`.
- Running `image`, `page`, `pdf` or `clip` with a piece id that already exists **replaces** that piece. Use this to retry with a better moment or picture.
- `TOOL remove --mark f1 --piece p2` removes a piece and its files. If no piece is left, the mark's status is unset, so run `report` again.
- Times are `MM:SS`, `H:MM:SS` or seconds, with up to three decimals: `2:21.5`, `1:02:03`, `141.5`.

## The words every capture needs (`--tier` and the rest)

Every piece (`image`, `page`, `pdf`, `clip`) is described with the same options.

Required:

| Option | Value |
|--------|-------|
| `--tier` | `official` (the subject's own channel or site), `press` (an official press kit or media library), `commons` (Wikimedia Commons or another free-licence library), `news` (a news outlet), `creator` (a creator's own video, only when the script talks about that video), `other` |
| `--publisher` | Who published it (for example `"The White House"`). For YouTube, the channel's owner. |
| `--what-it-shows` | One plain sentence on what the viewer sees (for example `"Both leaders shake hands in front of the fireplace."`). Say what is different from the note when it is. |
| `--same-event` | `yes`, `no` (file footage) or `unknown`. See "Same event or file footage" in `SKILL.md`. |
| `--on-screen-text` | `none`, `small` (a corner logo) or `large` (an anchor, a ticker, a big title). What you saw on the picture. |

Optional: `--title` (default: the page's or video's own title), `--published YYYY-MM-DD` (default for a video: the upload date), `--event-date YYYY-MM-DD` (the date of the event shown), `--licence` (for example `"CC BY 4.0"` or `"public domain (US government work)"`), `--licence-url`, `--notes`.

For a YouTube clip, `--publisher` that is not the channel gets a warning, because the review shows the channel. Use the channel's owner (for example the White House for the channel "The White House"). The tool reports the real channel; if you guessed, run `clip` again with the right `--publisher`.

## `image`: a photo

```
TOOL image --mark f2 --piece p1 --url "https://upload.wikimedia.org/.../Photo.jpg" \
  --page-url "https://commons.wikimedia.org/wiki/File:Photo.jpg" \
  --tier commons --publisher "Jane Doe / Wikimedia Commons" \
  --what-it-shows "The company's founder on stage at the 2025 launch event." \
  --same-event no --event-date 2025-06-10 --on-screen-text none \
  --licence "CC BY 4.0" --licence-url "https://creativecommons.org/licenses/by/4.0/"
```

- `--url` is the address of **the picture file itself** (JPEG, PNG or WebP), not of a page that shows it. A page address is refused with a message that says to use `page`. `--page-url` is the page you found it on (optional but give it).
- At most 20 MB and 40 million pixels. WebP is saved as PNG. A picture with a longer side under 1280 pixels gets a `WARNING` (it will look soft full screen): look for a larger one.
- Wikimedia refuses programs that do not say who runs them. If the tool says to set `VISIO_FOOTAGE_CONTACT`, **tell the owner** (it is an email address or a website of theirs, set before Cursor or Claude Code starts) and treat Wikimedia as blocked for now; use another source. You never set it yourself.

## `page`: a web page, scrolled to what the script talks about

```
TOOL page --mark f5 --piece p1 --url "https://example.com/blog/post" \
  --focus "drew a pelican riding a bicycle" \
  --tier other --publisher "Example Blog" \
  --what-it-shows "The blog post, with the paragraph about the pelican picture highlighted." \
  --same-event unknown --on-screen-text none --published 2026-05-02
```

- The tool opens the page in a headless browser, dismisses cookie banners, hides fixed elements, and screenshots it **from its top**, at most 4 screens tall. It also keeps the page's text.
- `--focus` is the words on the page that the script talks about. The tool finds them like a quote and highlights them in the video. Copy them **character for character from the page text you read**, not from a summary a fetch tool gave you. 3 to 600 characters is best; a short phrase of one or two lines is ideal.
- If the words are not found, the message lists the nearest text of the page: use the exact words from the list and run the command again.
- **A focus lower on the page than the 4 captured screens is refused**, with the screen it is on. Use another page, a part of the page that is higher up (a different heading or an anchor link), or capture without `--focus`.
- No `--focus` is fine when the whole page is the point: it then scrolls slowly.
- A page with a login wall, a paywall or a bot check: report that source as an attempt (or `blocked` if it was the only right source).

## `pdf`: one page of a PDF

```
TOOL pdf --mark f4 --piece p1 --url "https://example.com/reports/annual-2025.pdf" --page 18 \
  --focus "Revenue increased 12% to $4.2 billion" \
  --tier official --publisher "Example Corp" \
  --what-it-shows "The annual report's page with the revenue table." \
  --same-event unknown --on-screen-text none --published 2026-02-14
```

- `--url` and `--page N` (counted from 1) are required. `--focus` is optional. Do not use `--file`: you have no way to download a file.
- The picture is the **whole page**. Words you give in `--focus` are highlighted. A scanned PDF with no text layer is accepted with no `--focus`.
- Find the page and the words by reading the PDF text with the fetch tool first. If a focus is refused, the message lists the nearest text of that page.

## YouTube: `scan`, `scan --fine`, `clip`

A video is never downloaded whole. Three steps, each more precise. Each step only downloads what it needs. The time stamped on a frame is the time of that frame in the video.

### 0. Find the video

Search with the web search tool. Check each result's **channel** (see "Where footage comes from" in `SKILL.md`). Find the event's date from the event's own page or from the video's description, so you can set `--event-date` and `--same-event`. Keep the video's address in the form `https://www.youtube.com/watch?v=XXXXXXXXXXX` (or `youtu.be/...`). A playlist, a channel or any other site is refused.

### 1. `scan`: the area, no download of the video

```
TOOL scan --mark f3 --url "https://www.youtube.com/watch?v=XXXXXXXXXXX"
TOOL scan --mark f3 --url "https://www.youtube.com/watch?v=XXXXXXXXXXX" --from 20:00 --to 35:00
```

It writes into `results/f3/scans/<video_id>/`:

- `info.json`: the title, channel, upload date, length, YouTube licence, chapters and the start of the description.
- `captions.txt`: the English captions as plain text, one line each with its time first (`2:21  Thank you, Mr. President`), when there are any. A silent moment (a handshake) often comes right before a spoken line.
- `sheet-01.jpg`, ...: YouTube's own preview pictures as contact sheets, 36 frames each, with the time of each frame stamped in its corner. **Read the sheets with the file reading tool** (they are pictures). The spacing is whole seconds (2, 5 or 10 s are common; the tool tells you), so a shot shorter than the spacing can fall between two frames and never be seen.

A video is scanned whole only up to **20 minutes**. For a longer video the tool writes `info.json` and `captions.txt` only and says to pass `--from` and `--to` (at most 20 minutes apart). Narrow the area down first with the chapters, the captions and the description, or from what the event page says (for example "the joint press meet starts at 38:00"). Some videos have no preview pictures; then use a fine scan on a range you narrowed down from the captions.

A scan downloads a few hundred KB.

### 2. `scan --fine`: the shot, to half a second

```
TOOL scan --fine --mark f3 --url "https://www.youtube.com/watch?v=XXXXXXXXXXX" --from 37:58 --to 38:40
```

It downloads **only that range** (1 to 90 seconds) at low resolution without sound, and writes into `results/f3/scans/<video_id>/fine-<from>-<to>/`:

- `sheet-01.jpg`, ...: frames **0.5 s apart**, each with its time stamped to 0.1 s.
- `cuts.json`: the exact cut times of the range, in seconds of the source video.

Read the sheets. Find the shot that fits the note, the instant that matters (for example the handshake) and where the shot starts and ends. Check each frame of that shot for a logo, a ticker, an anchor and large text. A fine scan of 30 s takes about 7 seconds and downloads about 1 MB.

### 3. `clip`: the exact seconds

```
TOOL clip --mark f3 --piece p1 --url "https://www.youtube.com/watch?v=XXXXXXXXXXX" \
  --from 38:11.0 --to 38:24.0 --moment 38:16.5 \
  --tier official --publisher "The White House" \
  --what-it-shows "Both leaders shake hands in front of the fireplace, then turn to the cameras." \
  --same-event yes --event-date 2025-02-13 --on-screen-text none
```

- `--from` and `--to` are the **part to use**: 2 to 15 seconds. Choose it **inside one shot** where you can, using `cuts.json`. The app cuts the part to the length the words need and never shows a cut in the first or last half second, so a part that crosses a cut is allowed but should hold the picture you want.
- `--moment` is the instant that matters, inside the part. The app centres on it where it can. Give it when there is one.
- The tool downloads the part plus 2 seconds on each side at up to 1080p, **video only** (the footage never has sound), re-encoded to H.264. It writes `pN.mp4`, `pN-strip.jpg` (a frame every 0.5 s) and the result. A clip of 10 s takes about 15 seconds and is a few MB (at most 60 MB).
- **Read `pN-strip.jpg`** with the file reading tool. Check it shows what the note asks, that there is no anchor, ticker, logo or large text (or set `--on-screen-text` right), and that the first and last half second hold the shot you want.
- A clip below 720 pixels on the shorter side gets a `WARNING`.

### What the tool's messages mean

| Message | What to do |
|---------|------------|
| `The video is longer than 20 minutes, so no preview pictures were made` | Use `info.json` chapters, `captions.txt` and the description to find the area, then run `scan` again with `--from` and `--to`. |
| `YouTube gave no preview pictures for this video` | Run `scan --fine` on a range of at most 90 s that you found from the captions. |
| `A scan covers at most 20 minutes` / `A fine scan covers at most 90 s` | Choose a shorter range. |
| `--from is past the end of the video` | The time is wrong. Check `info.json` for the length. |
| `The part to use lasts N s. It must last at least 2 s` or `may last at most 15 s` | Choose a part of 2 to 15 seconds: the shot that shows what the note asks. |
| `--moment ... is outside the part to use` | Give a moment inside `--from` and `--to`. |
| `The part is larger than 60 MB` | Use a shorter part. |
| `The video is a live stream or a premiere that is not finished` | Use another video, or report `blocked`. |
| `WARNING: the publisher ... is not the YouTube channel ...` | Say who really published it: run `clip` again with the right `--publisher` (and `--tier`). Never leave a guess. |
| `No --moment was given, so the clip will start at the start of the part to use` | Fine when there is no single instant. |
| `Cuts inside the part to use: ...` | Information. Check the strip near each cut. |
| A message that ends with advice about `blocked` (bot check, age gate, private, members only, unavailable) | The video cannot be captured. Report the mark `blocked` if this was the right video and you kept nothing else, and add an `--attempt`. |
| `yt-dlp could not get the video` with a note about `uv lock --upgrade-package yt-dlp` | It may be a fault of the downloader and not of the video. Tell the owner, and report `blocked` with that attempt. |
| `ffmpeg is not installed` (or `ffprobe`) | Tell the owner (`brew install ffmpeg`). Do not try to install it yourself. |
| `yt-dlp: ...` warnings (for example no JavaScript runtime) | Normal. Ignore them. |
| `Set VISIO_FOOTAGE_CONTACT ...` | Tell the owner (see `image`). Use another source meanwhile. |
| `That address did not give a JPEG, PNG or WebP picture` | The address is a page, not the picture. Use `page`, or find the picture's own address. |
| A refusal that lists nearby text of the page (the focus words were not found) | Use the exact words from the list and run the command again. |
| `The focus words are on screen N of the page, below the first 4 screens` | Use a page where the words are higher up, or capture the page with no focus. |
| `The server answered 4xx. If the page is behind a paywall or a login, report the mark as blocked` | Count it as an attempt, or report `blocked` if it was the only right source. |
| `That address is a PDF. Use the pdf command` | Run `pdf` with `--page` instead. |
| `... leads to a local or private address` | Not allowed. Use a public address. |
| `The page moved while it was captured` | Run the command again (once). |

## `report`: the mark's status

```
TOOL report --mark f3 --status found --summary "What was found and how it fits the note."
TOOL report --mark f6 --status not_found --summary "Nothing usable was found." \
  --attempt "search: the words I searched" "only commentary channels, no original footage" \
  --attempt "https://example.com/gallery" "no photo of the event"
```

- Required: `--mark`, `--status`, `--summary` (one or two plain sentences, at most 1500 characters).
- `--status` is one of `found`, `not_found`, `blocked`.
- `--attempt WHAT OUTCOME` can be repeated, at most 40 per mark. Both values are text (at most 500 characters). **Attempts are added each time you run `report`**, so do not repeat an attempt you already reported.
- Run it for every mark, also those with pieces. `found` needs a piece; `not_found` and `blocked` need none (and refuse to be set when the mark has pieces).

## `validate`: check the whole round

```
TOOL validate
```

It prints a row per mark (status and pieces), then `WARNING` and `PROBLEM` lines, and ends with `Checks passed` or the number of problems. Exit code `0` only when there are no problems. Fix each problem and run it again. Run it last, before you finish. It checks the shape of every result, that every file is one the tool wrote and has not been changed, the types and sizes of the pictures and videos (a video with sound, or a `use` outside its `window`, is a problem), and that every focus box lies inside its picture.

## Worked examples (invented names)

**An official clip, found.** Mark `f3`: "the two leaders met at the Example Hall"; note "the handshake, both leaders, flags behind".

```
TOOL scan --mark f3 --url "https://www.youtube.com/watch?v=AAAAAAAAAAA" --from 35:00 --to 55:00
TOOL scan --fine --mark f3 --url "https://www.youtube.com/watch?v=AAAAAAAAAAA" --from 41:20 --to 42:20
TOOL clip --mark f3 --piece p1 --url "https://www.youtube.com/watch?v=AAAAAAAAAAA" \
  --from 41:31.0 --to 41:41.0 --moment 41:35.5 \
  --tier official --publisher "Example Office of the President" \
  --what-it-shows "The two leaders shake hands in front of the flags, then sit down." \
  --same-event yes --event-date 2025-02-13 --on-screen-text none
TOOL report --mark f3 --status found \
  --summary "Ten seconds from the official channel's upload of the meeting; the date is on the event page. The strip shows no logo or ticker." \
  --attempt "https://www.youtube.com/watch?v=BBBBBBBBBBB" "a news channel's panel discussion over the same footage, with a ticker"
```

**A free-licence photo of another occasion, file footage.** Mark `f4`: "the company started by Jane Doe"; note "Jane Doe on stage".

```
TOOL image --mark f4 --piece p1 --url "https://upload.wikimedia.org/.../JaneDoe2024.jpg" \
  --page-url "https://commons.wikimedia.org/wiki/File:JaneDoe2024.jpg" \
  --tier commons --publisher "A. Photographer / Wikimedia Commons" \
  --what-it-shows "Jane Doe speaks at a 2024 conference, not at the event of the sentence." \
  --same-event no --event-date 2024-05-02 --on-screen-text none \
  --licence "CC BY-SA 4.0" --licence-url "https://creativecommons.org/licenses/by-sa/4.0/"
TOOL report --mark f4 --status found \
  --summary "A Commons photo of Jane Doe on stage at a 2024 conference. It is file footage: the sentence is about the company's founding, not about this talk."
```

**A page with a focus.** Mark `f5`: "a developer asked the model to draw a pelican".

```
TOOL page --mark f5 --piece p1 --url "https://example.com/blog/pelican" \
  --focus "asked it to draw a pelican riding a bicycle" \
  --tier creator --publisher "Example Blog" \
  --what-it-shows "The developer's own blog post, with the paragraph about the pelican highlighted." \
  --same-event yes --event-date 2026-05-02 --on-screen-text none
TOOL report --mark f5 --status found --summary "The developer's own post, which the script talks about."
```

**Nothing found, not_found.** Mark `f6`.

```
TOOL report --mark f6 --status not_found \
  --summary "No usable footage: the only videos were commentary channels retelling the event, and no official upload exists." \
  --attempt "search: site:youtube.com example summit 2026 keynote" "commentary and compilation channels only" \
  --attempt "https://example.com/press" "the press kit has logos and no photos of the event"
```

**Blocked.** Mark `f7`.

```
TOOL report --mark f7 --status blocked \
  --summary "The official video exists but YouTube asked for a sign-in, so the tool could not fetch it." \
  --attempt "https://www.youtube.com/watch?v=CCCCCCCCCCC" "the tool was refused by YouTube (bot check)"
```
