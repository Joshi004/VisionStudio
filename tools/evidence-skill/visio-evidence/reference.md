# Capture tool reference

`TOOL` is the command written at the top of `SKILL.md`. Run it from the round folder (the folder that holds `brief/`). Every command also has `--help`. In examples, `"..."` stands for text you write yourself.

Exit codes: `0` done, `1` refused or checks failed (the message says what to change), `2` wrong usage.

The tool writes the whole `result.json`. You never edit it.

## Ids

- Claim ids come from the brief (`c1`, `c2`, ...). Use only those.
- Evidence ids are `e1`, `e2`, `e3`: one per piece of evidence of a claim, at most `rules.max_evidence_per_claim`.
- Running `web`, `pdf` or `video` with an id that already exists **replaces** that piece of evidence. Use this to retry with better words.
- `TOOL remove --claim c1 --evidence e2` removes a piece of evidence and its files. The claim's status is then unset, so run `report` again.

## `web`: a quote on a web page

```
TOOL web --claim c1 --evidence e1 --url "https://example.com/report" \
  --quote "the exact words" \
  --relation supports --tier primary \
  --publisher "Example Corp" \
  --what-it-says "One plain sentence, including any difference from the claim." \
  --published 2026-10-03
```

- Required: `--claim`, `--evidence`, `--url`, `--quote`, `--relation`, `--tier`, `--publisher`, `--what-it-says`.
- Optional: `--title` (default: the page's own title), `--author`, `--published YYYY-MM-DD`, `--archive-url`, `--notes`.
- Only public `http` and `https` addresses work. Local and private addresses are refused.

## `pdf`: a quote in a PDF

```
TOOL pdf --claim c2 --evidence e1 --url "https://example.com/annual-report.pdf" \
  --quote "the exact words" --page 42 \
  --relation supports --tier primary \
  --publisher "Example Corp" --what-it-says "..."
```

- Same options as `web`, plus `--page N` (counted from 1) to search only that page.
- Use `--url`. Do not use `--file`: you have no way to download a file.
- A quote may run over several lines. A word cut by a hyphen at a line end is fine: write the word whole.
- A PDF with no text layer (a scan) is refused. Report that source as an attempt.
- A quote that crosses a page break is refused. Use the part on one page.

### Finding words in a PDF

1. Read the PDF text with the fetch tool to find the page and the sentence.
2. Run `pdf --page N` with the words you found.
3. If it is refused, the message lists the nearest text of that page. Run the command again with the exact words from the list.

## Sound bite claims: `video`, the moment a person says a quote

```
TOOL video --claim c4 --evidence e1 --url "https://www.youtube.com/watch?v=XXXXXXXXXXX" \
  --quote "the words said in the video" --near 20:25 \
  --relation supports --tier primary \
  --publisher "Example University" \
  --what-it-says "One plain sentence: who says it, where, and how the date and the context were checked." \
  --recorded 2026-03-20
```

The tool reads the video's English captions, finds the quote in them, and downloads only that part of the video (the quote plus about 15 seconds on each side, at most 90 seconds, at most 1080p). It writes `e1.mp4`, `e1-captions.json`, `e1.txt` (the captions of the window as plain text) and the result. A capture takes about half a minute.

- Required: `--claim`, `--evidence`, `--url`, `--quote`, `--relation`, `--tier`, `--publisher`, `--what-it-says`.
- Optional: `--near MM:SS` (or `H:MM:SS`, or plain seconds), `--recorded YYYY-MM-DD`, `--title`, `--author`, `--archive-url`, `--notes`, `--as-context`.
- `--url` is one YouTube video (`youtube.com/watch?v=...` or `youtu.be/...`). A playlist, a channel or any other site is refused. There is no cookie, login or account.
- `--quote`: at least 4 words, as the captions have them. A loose match is used (most of the words, in order), so a "you know" or a different spelling does not matter. Use the claim's `text` first.
- `--near`: where in the video the quote is, when you know it. The tool uses it to choose between several matches.
- `--recorded`: the recording date, not the upload date. It is stored as the evidence's `published` date. Say in `--what-it-says` how you know it.
- `--as-context`: only for a claim that is **not** a sound bite claim and needs a video as background. A sound bite claim never needs it.
- `--publisher` is the channel's owner (for example the university), `--title` defaults to the video's title.
- Check the clip's quote length: a sound bite is 3 to 15 seconds.

### What the tool's messages mean

| Message | What to do |
|---------|------------|
| `The quote is not in the captions` and a list of nearest caption text with times | Pick the words from the list that are the claim's words and run the command again. At most 3 tries per video; then it is an attempt and you move on. |
| `The quote is in the captions N times` | Run again with `--near` set to the time you want. |
| `The quote runs for about N s ... the review will not accept a longer one` | Choose a shorter quote that carries the point, or keep the clip and report `partial` with the reason. |
| `--recorded ... is later than the upload date` | The date is wrong or is the date of something else. Find the right date, or leave `--recorded` out and say so. |
| `No --recorded date was given` | Fine only when you could not find the date. Say so in `--what-it-says`. |
| `The captions are YouTube's automatic ones` | Names and numbers may be wrong in `e1.txt`. The app transcribes the clip itself later, so this is not a problem for the clip. |
| A message that ends with advice about `blocked` (bot check, age gate, private, members only, unavailable, no English captions) | The video cannot be captured. Report the claim `blocked` if this was the right video and you kept nothing else, and add an `--attempt`. |
| `yt-dlp could not get the video` with a note about `uv lock --upgrade-package yt-dlp` | It may be a fault of the downloader and not of the video. Tell the owner, and report the claim as `blocked` with that attempt. |
| `ffmpeg is not installed` | Tell the owner (`brew install ffmpeg`). Do not try to install it yourself. |
| `yt-dlp: ...` warnings (for example no JavaScript runtime) | Normal. Ignore them. |

### Finding a sound bite

1. **Find the event.** Use `hint`, `sentence` and `context` to name the event: who, where, when. Look for the event's own page (the organiser, the company, the university) with the web search tool and read it: it gives the recording date and often links the official video.
2. **Search for the video.** Search with the speaker's name, the event, the year and the channel (for example `site:youtube.com "<speaker>" "<event>" <year>`), and with a few words of the quote. The top results are often explainer channels telling the story; skip them and look for the official upload.
3. **Pick the video by its channel.** The channel must be the speaker's, the event's, the university's or the original broadcaster's. A reputable outlet's upload of the original footage (its own interview, for example) is acceptable and is `secondary`.
4. **Capture.** Run `video` as above. `--tier`, `--publisher` and `--what-it-says` are fixed by this command, but the tool tells you the real channel only afterwards (`capture.channel` in `result.json`). If the channel is not what you wrote, run `video` again with the same evidence id and the right `--tier`, `--publisher` and `--what-it-says`. Never leave a guess such as "channel not yet checked" in the stored text.
5. **Check the context.** Read `results/<claim>/e1.txt` with the file reading tool, and `capture.channel` in `result.json`. The captions do not mark who is speaking. Look for these before you report:
   - the interviewer or another person says the words, or the speaker is quoting someone else;
   - the words are a joke, a hypothetical ("imagine ...") or reported speech ("he said ...");
   - the next sentences turn the point ("but", "however", "I was wrong"), or an apology or an admission follows;
   - laughter or applause sits on the words.
   
   Put what you found in `--what-it-says`. If a problem is serious, run `video` again with the same evidence id for another moment, or `TOOL remove` the piece and try another video.
6. **Budget.** At most 3 videos captured per claim, and at most 3 tries per video. Every video you looked at and did not use is an `--attempt` of the claim (its address and why: retelling channel, re-upload, dubbed, host reading the quote, wrong speaker, quote not in the captions, blocked).
7. **Optional page.** After the clip search, you may add a `web` or `pdf` piece about the same moment (the event's page, a transcript), with the next evidence id and within `max_evidence_per_claim`. Never instead of looking for the clip.
8. **Report.** `TOOL report` with a summary that begins "Clip captured" or "No clip" (see "Status for a sound bite claim" in `SKILL.md`).

## `report`: the claim's status

```
TOOL report --claim c1 --status found --summary "What the sources say, set against the claim."
TOOL report --claim c3 --status not_found --summary "Nothing usable was found." \
  --attempt "search: the words I searched" "only blogs, no primary source" \
  --attempt "https://example.com/page" "the page does not give the number"
```

- Required: `--claim`, `--status`, `--summary`.
- `--status` is one of `found`, `partial`, `not_found`, `contradicted`, `blocked`.
- `--attempt WHAT OUTCOME` can be repeated. Both values are text. **Attempts are added each time you run `report`**, so do not repeat an attempt you already reported.
- Run it for every claim, also those with evidence.

## `validate`: check the whole round

```
TOOL validate
```

It prints a row per claim (status and sources), then `WARNING` and `PROBLEM` lines, and ends with `Checks passed` or the number of problems. Exit code `0` only when there are no problems. Fix each problem and run it again. Run it last, before you finish.

## `draw` (optional)

`TOOL draw --claim c1 --evidence e1` writes a picture of the highlight rectangles in the system temporary folder and prints the file names. You do not need it.

## Choosing `relation` and `--tier`

| `--relation` | When |
|--------------|------|
| `supports` | The words say what the claim says. |
| `partly_supports` | The words support part of the claim, or give a different number, date or name. Say the difference in `--what-it-says`. |
| `contradicts` | The words say the opposite, or a clearly different fact. |
| `context` | Useful background that neither proves nor disproves the claim. |

| `--tier` | When |
|----------|------|
| `primary` | The company, the person, the official body or the original publication. For a video: the speaker's or the event's own channel (the company, the university, the conference), or the original broadcaster. |
| `secondary` | A reputable outlet that reports it. For a video: a reputable outlet's upload of the original footage. |
| `other` | Anything else (a blog, a forum, an aggregator). Prefer not to use these. For a video: any other channel; do not use an explainer channel at all. |

The claim's `--status` should follow from the evidence: `found` from a `supports` source, `partial` from a `partly_supports` one, `contradicted` from a `contradicts` one. (`validate` only checks that these three statuses have some evidence, and that `not_found` and `blocked` have none.)

## Worked examples

**A figure in an annual report (PDF), found.** Claim `c1`: "revenue grew 12 percent".

```
TOOL pdf --claim c1 --evidence e1 --url "https://example.com/annual-report-2025.pdf" --page 18 \
  --quote "Revenue increased 12% to $4.2 billion compared with the prior year." \
  --relation supports --tier primary --publisher "Example Corp" \
  --what-it-says "The company's own report gives 12% revenue growth for 2025." --published 2026-02-14
TOOL report --claim c1 --status found --summary "Example Corp's annual report states 12% revenue growth, as claimed."
```

**A person's words in an article (web), found.** Claim `c2`: "she said the plan was a mistake".

```
TOOL web --claim c2 --evidence e1 --url "https://news.example.com/interview" \
  --quote "I think the plan was a mistake, and I said so at the time." \
  --relation supports --tier secondary --publisher "Example News" \
  --what-it-says "She is quoted saying the plan was a mistake." --published 2026-09-30
TOOL report --claim c2 --status found --summary "Example News quotes her saying it was a mistake."
```

**A wrong number, contradicted.** Claim `c5`: "the unemployment rate is 9 percent". The official page says 4.1.

```
TOOL web --claim c5 --evidence e1 --url "https://stats.example.gov/unemployment" \
  --quote "The unemployment rate was 4.1 percent in October." \
  --relation contradicts --tier primary --publisher "Example Statistics Office" \
  --what-it-says "The official figure is 4.1 percent, not 9 percent."
TOOL report --claim c5 --status contradicted \
  --summary "The official statistics office gives 4.1 percent for October, not 9 percent."
```

**Nothing found.** Claim `c6`.

```
TOOL report --claim c6 --status not_found --summary "No source for this claim was found within the search budget." \
  --attempt "search: the claim's key words" "results were opinion pieces and no figure" \
  --attempt "https://example.com/related" "covers the topic but never states this"
```

**Blocked.** Claim `c7`: the right article is behind a paywall.

```
TOOL report --claim c7 --status blocked --summary "The article that would settle this is behind a paywall." \
  --attempt "https://paper.example.com/article" "paywall: the tool could not read the text"
```

### Sound bite examples (invented names)

**A clip on the official channel, found.** Claim `c4` (`want` `soundbite`, `speaker` "Ana Reyes"): "Build the thing people ask for, not the thing you like."

```
TOOL video --claim c4 --evidence e1 --url "https://www.youtube.com/watch?v=AAAAAAAAAAA" \
  --quote "build the thing people ask for not the thing you like" --near 12:40 \
  --relation supports --tier primary --publisher "Example University" \
  --what-it-says "Ana Reyes says it at the university's 2025 founders' lecture; the date is on the event page; the next sentences keep the point." \
  --recorded 2025-05-14
TOOL report --claim c4 --status found \
  --summary "Clip captured from Example University's own channel; the captions show Reyes saying the words and the next sentences repeat the point." \
  --attempt "https://www.youtube.com/watch?v=BBBBBBBBBBB" "an explainer channel retelling the lecture, not the original"
```

**Only retellings found, not_found.** Claim `c5`.

```
TOOL report --claim c5 --status not_found \
  --summary "No clip: the only videos found were explainer channels retelling the interview, and the broadcaster's own upload was not found." \
  --attempt "search: site:youtube.com Ana Reyes interview 2025" "explainer channels and a compilation only" \
  --attempt "https://www.youtube.com/watch?v=CCCCCCCCCCC" "a re-upload with a different voice-over, not the original"
```

**The official video is blocked.** Claim `c6`.

```
TOOL report --claim c6 --status blocked \
  --summary "No clip: the broadcaster's official video exists but YouTube asked for a sign-in, so the tool could not fetch it." \
  --attempt "https://www.youtube.com/watch?v=DDDDDDDDDDD" "the tool was refused by YouTube (bot check)"
```

**No clip, but a page confirms the words, partial.** Claim `c7`: after the clip search, a web piece was kept.

```
TOOL web --claim c7 --evidence e1 --url "https://events.example.com/founders-lecture" \
  --quote "Reyes closed the lecture by telling the audience to ship before they were ready." \
  --relation supports --tier primary --publisher "Example University" \
  --what-it-says "The event page's summary says the same, in the organiser's words; it is not a transcript." --published 2025-05-15
TOOL report --claim c7 --status partial \
  --summary "No clip: the lecture video is not public. The organiser's page confirms what she said, in its own words." \
  --attempt "search: site:youtube.com Reyes founders lecture 2025" "no upload of the lecture by the university or anyone else"
```

**The context turns the point, partly_supports.** Claim `c8`: the clip is real, but the next sentence reverses it.

```
TOOL video --claim c8 --evidence e1 --url "https://www.youtube.com/watch?v=EEEEEEEEEEE" \
  --quote "we will never open the platform to outside developers" \
  --relation partly_supports --tier primary --publisher "Example Corp" \
  --what-it-says "The CEO says it at the 2024 keynote, but in the next sentence (see e1.txt) she says that this changed the following year." \
  --recorded 2024-09-10
TOOL report --claim c8 --status partial \
  --summary "Clip captured from the company's own channel, but the speaker turns the point in the next sentence, so the clip alone would mislead."
```
