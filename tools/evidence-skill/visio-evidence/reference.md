# Capture tool reference

`TOOL` is the command written at the top of `SKILL.md`. Run it from the round folder (the folder that holds `brief/`). Every command also has `--help`. In examples, `"..."` stands for text you write yourself.

Exit codes: `0` done, `1` refused or checks failed (the message says what to change), `2` wrong usage.

The tool writes the whole `result.json`. You never edit it.

## Ids

- Claim ids come from the brief (`c1`, `c2`, ...). Use only those.
- Evidence ids are `e1`, `e2`, `e3`: one per piece of evidence of a claim, at most `rules.max_evidence_per_claim`.
- Running `web` or `pdf` with an id that already exists **replaces** that piece of evidence. Use this to retry with better words.
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
| `primary` | The company, the person, the official body or the original publication. |
| `secondary` | A reputable outlet that reports it. |
| `other` | Anything else (a blog, a forum, an aggregator). Prefer not to use these. |

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
