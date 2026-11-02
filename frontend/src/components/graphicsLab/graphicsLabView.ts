import type {
  GraphicBrief,
  GraphicOrientation,
  GraphicRunCreate,
  GraphicRunState,
  GraphicVoiceStage,
} from "../../api/graphicsLab";

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
