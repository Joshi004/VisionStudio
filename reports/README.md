# Reports

Reports are sorted into two folders by what they are for.

| Folder | What goes here |
|---|---|
| `technical/` | Research that informs how the app is built: features, providers, models, pipelines, architecture choices. |
| `stories/` | Research behind the videos we make: story research, topic ranking, source material for scripts. |

## Layout inside each folder

```
<category>/
  <Title>.md                  the report
  PDFs/<Title>.pdf            the PDF of the report
  research_notes/<Title>/     the raw notes the report was written from
```

Keep a report's notes and PDF in the same category folder as the report.

## If a report fits both

Put it where its main decision is made, and link to it from the other category.

## Links

Links to code or root-level docs use relative paths. From `technical/` or `stories/` the repo root is `../../`. From `<category>/research_notes/<Title>/` it is `../../../../`.
