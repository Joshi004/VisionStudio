# Reports

Reports are sorted into two folders by what they are for.

| Folder | What goes here |
|---|---|
| `technical/` | Research that informs how the app is built: features, providers, models, pipelines, architecture choices. |
| `stories/` | Research behind the videos we make: story research, topic ranking, source material for scripts. Sorted by channel. |

## Story channels

`stories/` has one folder per channel.

| Folder | Channel |
|---|---|
| `stories/finance_business_india/` | Finance and business stories for an Indian audience. |
| `stories/finance_business_usa/` | Finance and business stories for a US audience. |
| `stories/history/` | Historical stories. |
| `stories/ai/` | AI education and stories: AI news, explainers, model comparisons and any other AI topic. |
| `stories/fiction/` | Any other fictional story. |

## Layout

```
technical/
  <Title>.md                  the report
  PDFs/<Title>.pdf            the PDF of the report
  research_notes/<Title>/     the raw notes the report was written from

stories/<channel>/
  <Title>.md
  PDFs/<Title>.pdf
  research_notes/<Title>/
```

Keep a report's notes and PDF in the same folder as the report. Create `PDFs/` and `research_notes/` when the first report needs them.

## If a report fits more than one place

Put it where its main decision is made, or in the channel the video is made for. Link to it from the other place.

## Links

Links to code or root-level docs use relative paths. The repo root is `../../` from a report in `technical/`, and `../../../` from a report in a story channel. From a notes folder, add two more levels: `../../../../` under `technical/` and `../../../../../` under a story channel.
