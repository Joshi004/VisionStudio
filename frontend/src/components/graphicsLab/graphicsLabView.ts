import type {
  GraphicBrief,
  GraphicOrientation,
  GraphicRender,
  GraphicResolved,
  GraphicRunCreate,
  GraphicRunState,
  GraphicVoiceStage,
} from "../../api/graphicsLab";
import { isJobActive } from "../../api/polling";

/** The longest line the lab takes. The server stays the judge; the form only says so early. */
export const LINE_MAX_CHARS = 300;

export type GraphicsLabFormState = {
  line: string;
  orientation: GraphicOrientation;
  /** The id of a saved voice as the select holds it (a string), or null for no voice. */
  voiceId: string | null;
};

export const DEFAULT_FORM: GraphicsLabFormState = {
  line: "",
  orientation: "landscape",
  voiceId: null,
};

export const ORIENTATION_LABELS: Record<GraphicOrientation, string> = {
  landscape: "Landscape",
  portrait: "Portrait",
};

const STATE_TEXT: Record<GraphicRunState, string> = {
  new: "No brief yet",
  making_voice: "Making the voice",
  voice_failed: "The voice failed",
  writing_brief: "Writing the brief",
  brief_ready: "Brief ready",
  brief_failed: "The brief failed",
};

/** What a run is doing, in words. */
export function stateText(state: GraphicRunState): string {
  return STATE_TEXT[state];
}

/** Why the form cannot be sent, or null when it can. */
export function formProblem(form: GraphicsLabFormState): string | null {
  const length = form.line.trim().length;
  if (length === 0) {
    return "Type the line to make a graphic for.";
  }
  if (length > LINE_MAX_CHARS) {
    return `The line must be at most ${LINE_MAX_CHARS} characters.`;
  }
  return null;
}

export function toRequest(form: GraphicsLabFormState): GraphicRunCreate {
  return {
    line_text: form.line.trim(),
    orientation: form.orientation,
    voice_id: form.voiceId === null ? null : Number(form.voiceId),
  };
}

const VOICE_STAGE_TEXT: Record<GraphicVoiceStage, string> = {
  speaking: "The line is being spoken",
  timing: "The words are being timed",
  ready: "Voice ready",
  failed: "The voice failed",
};

/** Where a run's voice stands, in words. */
export function voiceStageText(stage: GraphicVoiceStage): string {
  return VOICE_STAGE_TEXT[stage];
}

/** The line on one row of a list, cut at a whole word where it is long. */
export function snippet(text: string, max = 140): string {
  const oneLine = text.split(/\s+/).join(" ");
  if (oneLine.length <= max) {
    return oneLine;
  }
  const cut = oneLine.slice(0, max - 1);
  const space = cut.lastIndexOf(" ");
  return `${(space > max / 2 ? cut.slice(0, space) : cut).trimEnd()}…`;
}

export const KIND_LABELS: Record<GraphicBrief["kind"], string> = {
  kpi: "One big number",
  comparison: "Comparison",
  trend: "Trend",
  process: "Process",
  list: "List",
  statement: "Statement",
  concept: "Concept",
};

/** How a derived value is worked out, in words. */
export const OP_LABELS: Record<GraphicBrief["derived"][number]["op"], string> = {
  pct_change: "percent change",
  difference: "difference",
  ratio: "ratio",
  sum: "sum",
};

/** A frame as seconds into the graphic, to one decimal ("2.6 s"). */
export function secondsAt(frame: number, fps: number): string {
  return `${(frame / fps).toFixed(1)} s`;
}

export const TIMING_SOURCE_LABELS: Record<string, string> = {
  estimated: "estimated from a speaking pace",
  parakeet: "timed from the voice",
};

export const TEMPLATE_LABELS: Record<string, string> = {
  kpi_card: "KPI card",
  bar_comparison: "Bar comparison",
  line_trend: "Line trend",
  flow_diagram: "Flow diagram",
  bullet_build: "Bullet build",
};

/**
 * What the template engines hold as their input (GFX-006): a template with its variant, or the
 * reason that no template fits. Null for an input that is not one of the two (not written yet).
 */
export type TemplateInput =
  | { kind: "spec"; template: string; variant: string | null }
  | { kind: "no_fit"; reason: string };

export function readTemplateInput(input: unknown): TemplateInput | null {
  if (typeof input !== "object" || input === null) {
    return null;
  }
  const { template, variant, reason } = input as Record<string, unknown>;
  if (template === null) {
    return { kind: "no_fit", reason: typeof reason === "string" ? reason : "No reason was given." };
  }
  if (typeof template === "string") {
    return { kind: "spec", template, variant: typeof variant === "string" ? variant : null };
  }
  return null;
}

export const BLOCK_LABELS: Record<string, string> = {
  text: "Text",
  counter: "Counter",
  bar_series: "Bars",
  line_series: "Line",
  node: "Node",
  arrow: "Arrow",
  table: "Table",
  badge: "Badge",
  highlight: "Highlight",
  progress_ring: "Ring",
};

/**
 * What the building-blocks engine holds as its input (GFX-009): the blocks of the scene in order,
 * and what the layout check found. `problems` is empty when the layout is clean or was not
 * checked; `checked` tells the two apart.
 */
export type BlockInput = {
  blocks: string[];
  checked: boolean;
  /** Why the layout was not checked, when it was not. */
  reason: string | null;
  problems: string[];
  askedAgain: boolean;
};

export function readBlockInput(input: unknown): BlockInput | null {
  if (typeof input !== "object" || input === null) {
    return null;
  }
  const { elements, layout } = input as Record<string, unknown>;
  if (!Array.isArray(elements)) {
    return null;
  }
  const blocks = elements.flatMap((element) => {
    const block = (element as { block?: unknown } | null)?.block;
    return typeof block === "string" ? [block] : [];
  });
  const { checked, reason, problems, asked_again } = (
    typeof layout === "object" && layout !== null ? layout : {}
  ) as Record<string, unknown>;
  return {
    blocks,
    checked: checked !== false,
    reason: typeof reason === "string" ? reason : null,
    problems: Array.isArray(problems)
      ? problems.filter((problem): problem is string => typeof problem === "string")
      : [],
    askedAgain: asked_again === true,
  };
}

/**
 * What the generated-component engine holds as its input (GFX-010): the code the model wrote, what
 * the browser check found, and the warnings about numbers that are not traced to a fact.
 * `checked` is false when the motion service could not be reached; `passed` is null then.
 */
export type ComponentInput = {
  code: string;
  checked: boolean;
  passed: boolean | null;
  /** Why the check was not made, when it was not. */
  reason: string | null;
  errors: string[];
  warnings: string[];
  askedAgain: boolean;
};

function texts(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

export function readComponentInput(input: unknown): ComponentInput | null {
  if (typeof input !== "object" || input === null) {
    return null;
  }
  const { code, checks, warnings } = input as Record<string, unknown>;
  if (typeof code !== "string") {
    return null;
  }
  const { checked, passed, reason, errors, asked_again } = (
    typeof checks === "object" && checks !== null ? checks : {}
  ) as Record<string, unknown>;
  return {
    code,
    checked: checked !== false,
    passed: typeof passed === "boolean" ? passed : null,
    reason: typeof reason === "string" ? reason : null,
    errors: texts(errors),
    warnings: texts(warnings),
    askedAgain: asked_again === true,
  };
}

// --- The comparison view (GFX-011) -----------------------------------------------------------

/** The frames where a beat arrives, once each and in order (the marks of the playback bar). */
export function beatFrames(resolved: GraphicResolved | null): number[] {
  if (resolved === null) {
    return [];
  }
  const frames = Object.values(resolved.beats).map((beat) => beat.frame);
  return [...new Set(frames)].sort((a, b) => a - b);
}

/** A size in bytes as "86 KB" or "1.2 MB". */
export function formatBytes(bytes: number): string {
  return bytes < 1024 * 1024
    ? `${(bytes / 1024).toFixed(0)} KB`
    : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** The five checks the backend makes on every video (`metrics.checks`), in this order. */
export const CHECK_LABELS: Record<string, string> = {
  frames: "Frames",
  size: "Size",
  fps: "Frame rate",
  codec: "Codec",
  pix_fmt: "Pixel format",
};

/** What Render again found when it compared the frames with the render it repeated (§4.7). */
export type RepeatResult =
  | { kind: "compared"; ofAttempt: number | null; frames: number; differing: number }
  | { kind: "not_compared"; ofAttempt: number | null; reason: string };

/** `metrics` of a render, read safely: any part that is missing is null or empty. */
export type RenderMetrics = {
  /** Each check that was made, with whether the video came out as asked. */
  checks: [key: string, ok: boolean][];
  renderSeconds: number | null;
  sizeBytes: number | null;
  frames: number | null;
  timingSource: string | null;
  voice: boolean | null;
  layoutProblems: number | null;
  /** Only the generated component counts them. */
  untracedNumbers: number | null;
  repeat: RepeatResult | null;
};

function numberOf(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function readMetrics(metrics: unknown): RenderMetrics | null {
  if (typeof metrics !== "object" || metrics === null) {
    return null;
  }
  const record = metrics as Record<string, unknown>;
  const checks = (typeof record["checks"] === "object" && record["checks"] !== null
    ? record["checks"]
    : {}) as Record<string, unknown>;
  let repeat: RepeatResult | null = null;
  const raw = record["repeat"];
  if (typeof raw === "object" && raw !== null) {
    const found = raw as Record<string, unknown>;
    const ofAttempt = numberOf(found["of_attempt"]);
    const frames = numberOf(found["frames"]);
    const differing = numberOf(found["differing"]);
    if (frames !== null && differing !== null) {
      repeat = { kind: "compared", ofAttempt, frames, differing };
    } else {
      const reason = found["reason"];
      repeat = {
        kind: "not_compared",
        ofAttempt,
        reason: typeof reason === "string" ? reason : "no reason was given",
      };
    }
  }
  return {
    checks: Object.keys(CHECK_LABELS).flatMap((key) =>
      typeof checks[key] === "boolean" ? [[key, checks[key] as boolean] as [string, boolean]] : [],
    ),
    renderSeconds: numberOf(record["render_s"]),
    sizeBytes: numberOf(record["size_bytes"]),
    frames: numberOf(record["frames"]),
    timingSource: typeof record["timing_source"] === "string" ? record["timing_source"] : null,
    voice: typeof record["voice"] === "boolean" ? record["voice"] : null,
    layoutProblems: numberOf(record["layout_problems"]),
    untracedNumbers: numberOf(record["untraced_numbers"]),
    repeat,
  };
}

/** "Identical to attempt 1" or "2 of 255 frames differ from attempt 1", in words. */
export function repeatText(repeat: RepeatResult): string {
  const of = repeat.ofAttempt !== null ? `attempt ${repeat.ofAttempt}` : "the earlier render";
  if (repeat.kind === "not_compared") {
    return `Not compared with ${of}: ${repeat.reason}.`;
  }
  return repeat.differing === 0
    ? `Identical to ${of} (all ${repeat.frames} frames)`
    : `${repeat.differing} of ${repeat.frames} frames differ from ${of}`;
}

/** Where one render stands: a short label, a colour for it, and whether something is running. */
export type RenderState = {
  label: string;
  color: "gray" | "blue" | "green" | "red" | "yellow";
  busy: boolean;
};

export function renderState(render: GraphicRender): RenderState {
  if (isJobActive(render.input_job)) {
    const phase = render.input_job?.phase;
    return { label: `Writing the input${phase ? `: ${phase}` : ""}`, color: "blue", busy: true };
  }
  if (isJobActive(render.render_job)) {
    const phase = render.render_job?.phase;
    return { label: `Rendering${phase ? `: ${phase}` : ""}`, color: "blue", busy: true };
  }
  if (render.url !== null) {
    return { label: "Done", color: "green", busy: false };
  }
  if (render.last_error !== null) {
    return { label: "Failed", color: "red", busy: false };
  }
  if (readTemplateInput(render.input)?.kind === "no_fit") {
    return { label: "No template fits", color: "yellow", busy: false };
  }
  if (render.input_job?.status === "failed" || render.render_job?.status === "failed") {
    return { label: "Failed", color: "red", busy: false };
  }
  return { label: "No video yet", color: "gray", busy: false };
}

/**
 * The model call that wrote a render's input, in words ("41.2 s, 2 attempts, tokens: 9,120 in,
 * 6,500 out, 3,000 reasoning"). A count the model did not report is left out.
 */
export function callText(call: NonNullable<GraphicRender["input_call"]>): string {
  const parts = [
    `${call.seconds.toFixed(1)} s`,
    `${call.attempts} ${call.attempts === 1 ? "attempt" : "attempts"}`,
  ];
  const counts: string[] = [];
  if (call.prompt_tokens !== null) {
    counts.push(`${call.prompt_tokens.toLocaleString("en-US")} in`);
  }
  if (call.completion_tokens !== null) {
    counts.push(`${call.completion_tokens.toLocaleString("en-US")} out`);
  }
  if (call.reasoning_tokens !== null) {
    counts.push(`${call.reasoning_tokens.toLocaleString("en-US")} reasoning`);
  }
  if (counts.length > 0) {
    parts.push(`tokens: ${counts.join(", ")}`);
  }
  return parts.join(", ");
}
