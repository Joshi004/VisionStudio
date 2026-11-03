import type {
  GraphicTrialCost,
  GraphicTrialEngine,
  GraphicTrialOrientation,
  GraphicTrialOutcome,
  GraphicTrialSummary,
} from "../../api/graphicsLab";
import { ORIENTATION_LABELS } from "./graphicsLabView";

export const ORIENTATION_MODE_LABELS: Record<GraphicTrialOrientation, string> = {
  own: "Each excerpt's own",
  landscape: "All landscape",
  portrait: "All portrait",
};

export const OUTCOME_LABELS: Record<GraphicTrialOutcome["kind"], string> = {
  video: "Video",
  no_fit: "No template fits",
  failed: "Failed",
  working: "Working",
  not_started: "Not started",
};

export const OUTCOME_COLORS: Record<GraphicTrialOutcome["kind"], string> = {
  video: "green",
  no_fit: "yellow",
  failed: "red",
  working: "blue",
  not_started: "gray",
};

/** What a trial will do, in words, for the confirmation: the paid calls and any speeches. */
export function costText(cost: GraphicTrialCost): string {
  const calls =
    `${cost.runs} runs, ${cost.paid_calls} paid model calls ` +
    `(up to ${cost.most_paid_calls} when answers are retried)`;
  return cost.speeches > 0
    ? `${calls}, and ${cost.speeches} speeches on the remote server, each timed by Parakeet`
    : calls;
}

/** The engines that draw from a template spec: only they can say "no template fits". */
const TEMPLATE_ENGINES: ReadonlyArray<string> = ["remotion_templates", "python_templates"];

const NONE = "-";

function secondsText(seconds: number | null): string {
  return seconds === null ? NONE : `${seconds.toFixed(1)} s`;
}

function verdictsText(engine: GraphicTrialEngine): string {
  return (
    `good ${engine.verdict_good}, usable ${engine.verdict_usable}, ` +
    `bad ${engine.verdict_bad}, not judged ${engine.verdict_none}`
  );
}

function repeatsText(engine: GraphicTrialEngine): string {
  const total = engine.repeats_identical + engine.repeats_differing + engine.repeats_not_compared;
  if (total === 0) {
    return NONE;
  }
  return (
    `${engine.repeats_identical} identical, ${engine.repeats_differing} differ, ` +
    `${engine.repeats_not_compared} not compared`
  );
}

/** The measures of §4.9 as rows of a table: a name, and the text of each engine (in order). */
export type MeasureRow = { name: string; values: string[] };

export const NUMBERS_NOTE =
  "Every number traced: only the generated component can show a number nothing traced. The " +
  "other engines refuse one before they draw (G-7), so each of their videos counts.";

export function measureRows(engines: GraphicTrialEngine[]): MeasureRow[] {
  const row = (name: string, text: (engine: GraphicTrialEngine) => string): MeasureRow => ({
    name,
    values: engines.map(text),
  });
  const ofVideos = (count: number, engine: GraphicTrialEngine) => `${count} of ${engine.videos}`;
  return [
    row("Made a video", (e) => `${e.videos} of ${e.runs}`),
    row("No template fits", (e) => (TEMPLATE_ENGINES.includes(e.key) ? String(e.no_fit) : NONE)),
    row("Failed", (e) => String(e.failed)),
    row("Not finished", (e) => String(e.working + e.not_started)),
    row("Frames, size and frame rate right", (e) => ofVideos(e.checks_passed, e)),
    row("No layout warning", (e) => ofVideos(e.no_layout_warning, e)),
    row("Every number traced", (e) => ofVideos(e.numbers_traced, e)),
    row("Median render time", (e) => secondsText(e.median_render_s)),
    row("Median tokens (in and out)", (e) =>
      e.median_tokens === null ? NONE : e.median_tokens.toLocaleString("en-US"),
    ),
    row("Render again", repeatsText),
    row("Verdicts", verdictsText),
  ];
}

/** One run's result on one engine: "Video (good)", "No template fits", "Failed", ... */
export function outcomeText(outcome: GraphicTrialOutcome | undefined): string {
  if (outcome === undefined) {
    return NONE;
  }
  if (outcome.kind === "video") {
    return `Video (${outcome.verdict ?? "not judged"})`;
  }
  return OUTCOME_LABELS[outcome.kind];
}

/** A cell of a Markdown table: no line breaks, and the bar that would end the cell escaped. */
function cell(text: string): string {
  return text.replace(/\s+/g, " ").replaceAll("|", "\\|");
}

function table(header: string[], rows: string[][]): string {
  const line = (cells: string[]) => `| ${cells.map(cell).join(" | ")} |`;
  return [line(header), line(header.map(() => "---")), ...rows.map(line)].join("\n");
}

/**
 * The summary as Markdown for Appendix B: a heading, the table of measures (one column for each
 * engine), the table of runs, and the note about traced numbers.
 */
export function trialMarkdown(summary: GraphicTrialSummary): string {
  const when = new Date(summary.created_at).toLocaleString();
  const heading =
    `### Trial set ${summary.set_no} (${when}, ` +
    `${summary.with_voice ? "with a voice" : "no voice"})`;
  const engines = summary.engines;
  const measures = table(
    ["Measure", ...engines.map((engine) => engine.label)],
    measureRows(engines).map((row) => [row.name, ...row.values]),
  );
  const runs = table(
    ["Run", "Excerpt", "Orientation", ...engines.map((engine) => engine.label)],
    summary.runs.map((run) => [
      String(run.run_id),
      run.case,
      ORIENTATION_LABELS[run.orientation],
      ...engines.map((engine) => outcomeText(run.outcomes[engine.key])),
    ]),
  );
  return [heading, "", measures, "", runs, "", NUMBERS_NOTE, ""].join("\n");
}
