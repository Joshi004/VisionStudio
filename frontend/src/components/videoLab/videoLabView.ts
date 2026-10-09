import type { LabVideoRun, LabVideoRunCreate } from "../../api/videoLab";
import type { VideoModel } from "../../videoModels";
import type { ReferenceItem } from "../imageLab/labView";

export type LabMode = "quality" | "fast";
export type LabOrientation = "portrait" | "landscape";

export const DURATION_MIN_S = 1;
export const DURATION_MAX_S = 20;
const SEED_LIMIT = 2 ** 31;

export type VideoLabFormState = {
  prompt: string;
  models: VideoModel[];
  mode: LabMode;
  orientation: LabOrientation;
  durationS: number | string;
  /** Empty: a random seed, shared by the runs of one click. */
  seed: string;
  /** LTX-2.3 only. Empty: the pipeline's own default applies. */
  negativePrompt: string;
  /** The image the clip starts from, or null for text-to-video. */
  firstFrame: ReferenceItem | null;
};

export const DEFAULT_FORM: VideoLabFormState = {
  prompt: "",
  // The lab is for comparing, so both models are chosen to begin with.
  models: ["ltx-2.3", "ltx-2.5"],
  mode: "quality",
  orientation: "portrait",
  durationS: 5,
  seed: "",
  negativePrompt: "",
  firstFrame: null,
};

/** A whole number from the text of a box, or null when it is not one. */
function wholeNumber(text: string): number | null {
  const trimmed = text.trim();
  return /^\d{1,10}$/.test(trimmed) ? Number(trimmed) : null;
}

/** The length as a number, or null while the box holds something that is not one. */
export function durationOf(state: Pick<VideoLabFormState, "durationS">): number | null {
  const value = typeof state.durationS === "number" ? state.durationS : Number(state.durationS);
  return state.durationS === "" || !Number.isFinite(value) ? null : value;
}

/** Why the form cannot be run, or null when it can. The server checks everything again. */
export function formProblem(state: VideoLabFormState): string | null {
  if (state.prompt.trim() === "") {
    return "Write a prompt first.";
  }
  if (state.models.length === 0) {
    return "Choose LTX-2.3, LTX-2.5, or both.";
  }
  const duration = durationOf(state);
  if (duration === null || duration < DURATION_MIN_S || duration > DURATION_MAX_S) {
    return `The length must be from ${DURATION_MIN_S} to ${DURATION_MAX_S} seconds.`;
  }
  if (state.seed.trim() !== "") {
    const seed = wholeNumber(state.seed);
    if (seed === null || seed >= SEED_LIMIT) {
      return `The seed must be a whole number from 0 to ${SEED_LIMIT - 1}.`;
    }
  }
  return null;
}

/** The form as the request the server takes. */
export function toRequest(state: VideoLabFormState): LabVideoRunCreate {
  const negative = state.negativePrompt.trim();
  return {
    prompt: state.prompt,
    models: state.models,
    mode: state.mode,
    orientation: state.orientation,
    duration_s: durationOf(state) ?? 0,
    seed: state.seed.trim() === "" ? null : wholeNumber(state.seed),
    // Only LTX-2.3 has the field: the server sends it to no other model.
    negative_prompt: state.models.includes("ltx-2.3") && negative !== "" ? negative : null,
    first_frame: state.firstFrame
      ? { source: state.firstFrame.source, id: state.firstFrame.id }
      : null,
  };
}

/** "5 to 10 minutes on one GPU", doubled for two runs. */
export function costText(modelCount: number): string {
  return modelCount === 1
    ? "One run: a GPU job of 5 to 10 minutes."
    : `${modelCount} runs: ${modelCount} GPU jobs of 5 to 10 minutes each, using the same GPU slots as scene clips.`;
}

function numberParam(run: LabVideoRun, key: string): number | null {
  const value = run.params[key];
  return typeof value === "number" ? value : null;
}

function textParam(run: LabVideoRun, key: string): string | null {
  const value = run.params[key];
  return typeof value === "string" ? value : null;
}

/** What a run's job and clip say about it, for a caption: "1088 x 1920 · 121 frames · 5.04 s". */
export function runStats(run: LabVideoRun): string {
  const parts: string[] = [];
  if (run.width !== null && run.height !== null) {
    parts.push(`${run.width} x ${run.height}`);
  }
  if (run.frame_count !== null) {
    parts.push(`${run.frame_count} frames`);
  }
  if (run.duration_s !== null) {
    parts.push(`${run.duration_s.toFixed(2)} s`);
  }
  if (run.url !== null) {
    parts.push(run.audio_codec !== null ? `sound: ${run.audio_codec}` : "no sound");
  }
  return parts.join(" · ");
}

/** The settings a group of runs was made with, as a short line. */
export function paramsLine(run: LabVideoRun): string {
  const parts: string[] = [];
  const mode = textParam(run, "mode");
  if (mode !== null) {
    parts.push(mode);
  }
  const orientation = textParam(run, "orientation");
  if (orientation !== null) {
    parts.push(orientation);
  }
  const duration = numberParam(run, "duration_s");
  if (duration !== null) {
    parts.push(`${duration} s`);
  }
  const frames = numberParam(run, "num_frames");
  if (frames !== null) {
    parts.push(`${frames} frames requested`);
  }
  const seed = numberParam(run, "seed");
  if (seed !== null) {
    parts.push(`seed ${seed}`);
  }
  return parts.join(" · ");
}

/** The negative prompt a run sent (LTX-2.3 only), or null. */
export function negativePromptOf(run: LabVideoRun): string | null {
  return textParam(run, "negative_prompt");
}

/**
 * The form that would make these runs again: the prompt and settings of the first run, with
 * every model the group used. The first frame is loaded only while its image still exists.
 */
export function stateFromRuns(runs: LabVideoRun[]): VideoLabFormState {
  const first = runs[0];
  const mode = textParam(first, "mode");
  const orientation = textParam(first, "orientation");
  const duration = numberParam(first, "duration_s");
  const seed = numberParam(first, "seed");
  const frame = first.first_frame;
  return {
    prompt: first.prompt,
    models: runs.map((run) => run.video_model),
    mode: mode === "fast" ? "fast" : "quality",
    orientation: orientation === "landscape" ? "landscape" : "portrait",
    durationS: duration ?? DEFAULT_FORM.durationS,
    seed: seed === null ? "" : String(seed),
    negativePrompt: runs.map(negativePromptOf).find((text) => text !== null) ?? "",
    firstFrame:
      frame !== null && frame.url !== null
        ? {
            source: frame.source,
            id: frame.id,
            url: frame.url,
            width: null,
            height: null,
            label: frame.source === "lab" ? `lab image ${frame.id}` : `project frame ${frame.id}`,
          }
        : null,
  };
}
