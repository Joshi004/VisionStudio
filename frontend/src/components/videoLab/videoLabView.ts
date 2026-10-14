import type {
  H3ReferenceRunCreate,
  LabVideoRun,
  LabVideoRunCreate,
} from "../../api/videoLab";
import { H3_MODEL, type LabVideoModel } from "../../videoModels";
import type { ReferenceItem } from "../imageLab/labView";

export type LabMode = "quality" | "fast";
export type LabOrientation = "portrait" | "landscape";
/**
 * "generate": one run per chosen model, from the prompt and an optional first and last frame.
 * "h3_reference": one MiniMax H3 clip made from up to 9 pictures and an audio reference.
 */
export type LabKind = "generate" | "h3_reference";

export const DURATION_MIN_S = 1;
export const DURATION_MAX_S = 20;
/** MiniMax H3 makes 5.17 to 14.4 seconds (124 to 345 frames at a fixed 24 fps). */
export const H3_DURATION_MIN_S = 5;
export const H3_DURATION_MAX_S = 14.4;
export const H3_STEPS_MIN = 4;
export const H3_STEPS_MAX = 100;
/** `<Picture 1>` to `<Picture 9>`: what the reference endpoint takes. */
export const H3_MAX_REFERENCES = 9;
/** The audio reference lasts 2 to 15 seconds. */
export const H3_AUDIO_MIN_S = 2;
export const H3_AUDIO_MAX_S = 15;
const SEED_LIMIT = 2 ** 31;

/** The audio of a MiniMax H3 reference clip: a Voice lab speech, or a saved voice's recording. */
export type AudioChoice = {
  source: "voice_run" | "voice";
  id: number;
  /** What the picker shows: "voice: Mara" or "speech 12". */
  label: string;
  durationS: number;
};

export type VideoLabFormState = {
  kind: LabKind;
  prompt: string;
  models: LabVideoModel[];
  mode: LabMode;
  orientation: LabOrientation;
  durationS: number | string;
  /** Empty: a random seed, shared by the runs of one click. */
  seed: string;
  /** LTX-2.3 only. Empty: the pipeline's own default applies. */
  negativePrompt: string;
  /** The image the clip starts from, or null for text-to-video. */
  firstFrame: ReferenceItem | null;
  /** The image the clip ends on (needs a first frame), or null. */
  lastFrame: ReferenceItem | null;
  /** MiniMax H3 only. Empty: the pipeline's own default (50 steps). */
  steps: string;
  /** "h3_reference" only: the pictures, `<Picture 1>` first. */
  references: ReferenceItem[];
  /** "h3_reference" only: the audio reference (`<Audio 1>`). */
  audio: AudioChoice | null;
  /** "h3_reference" only: the clip is as long as the audio, instead of `durationS`. */
  matchAudio: boolean;
};

export const DEFAULT_FORM: VideoLabFormState = {
  kind: "generate",
  prompt: "",
  // The lab is for comparing, so both LTX models are chosen to begin with. MiniMax H3 holds two
  // GPUs and takes longer, so it is chosen on purpose.
  models: ["ltx-2.3", "ltx-2.5"],
  mode: "quality",
  orientation: "portrait",
  durationS: 5,
  seed: "",
  negativePrompt: "",
  firstFrame: null,
  lastFrame: null,
  steps: "",
  references: [],
  audio: null,
  matchAudio: true,
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

/** Whether a MiniMax H3 clip is part of this form: chosen as a model, or the reference mode. */
export function usesH3(state: Pick<VideoLabFormState, "kind" | "models">): boolean {
  return state.kind === "h3_reference" || state.models.includes(H3_MODEL);
}

/** The steps as a number: null when the box is empty or holds something that is not a number. */
export function stepsOf(state: Pick<VideoLabFormState, "steps">): number | null {
  return wholeNumber(state.steps);
}

/** The shortest and longest clip the form's models can make: H3's range when H3 is in it. */
export function durationLimits(state: Pick<VideoLabFormState, "kind" | "models">): {
  min: number;
  max: number;
} {
  return usesH3(state)
    ? { min: H3_DURATION_MIN_S, max: H3_DURATION_MAX_S }
    : { min: DURATION_MIN_S, max: DURATION_MAX_S };
}

function stepsProblem(state: VideoLabFormState): string | null {
  if (state.steps.trim() === "") {
    return null;
  }
  const steps = stepsOf(state);
  if (steps === null || steps < H3_STEPS_MIN || steps > H3_STEPS_MAX) {
    return `MiniMax H3: the steps must be a whole number from ${H3_STEPS_MIN} to ${H3_STEPS_MAX}.`;
  }
  return null;
}

function seedProblem(state: VideoLabFormState): string | null {
  if (state.seed.trim() === "") {
    return null;
  }
  const seed = wholeNumber(state.seed);
  return seed === null || seed >= SEED_LIMIT
    ? `The seed must be a whole number from 0 to ${SEED_LIMIT - 1}.`
    : null;
}

/** Why a MiniMax H3 reference clip cannot be run, or null when it can. */
function referenceProblem(state: VideoLabFormState): string | null {
  if (state.references.length === 0) {
    return "Choose at least one reference picture.";
  }
  if (state.references.length > H3_MAX_REFERENCES) {
    return `At most ${H3_MAX_REFERENCES} reference pictures.`;
  }
  if (state.audio === null) {
    return "Choose an audio reference.";
  }
  if (state.audio.durationS < H3_AUDIO_MIN_S || state.audio.durationS > H3_AUDIO_MAX_S) {
    return `The audio reference lasts ${state.audio.durationS.toFixed(1)} seconds, and MiniMax H3 needs ${H3_AUDIO_MIN_S} to ${H3_AUDIO_MAX_S}.`;
  }
  if (!state.matchAudio) {
    const duration = durationOf(state);
    if (duration === null || duration < H3_DURATION_MIN_S || duration > H3_DURATION_MAX_S) {
      return `MiniMax H3: the length must be from ${H3_DURATION_MIN_S} to ${H3_DURATION_MAX_S} seconds.`;
    }
  }
  return null;
}

/** Why the form cannot be run, or null when it can. The server checks everything again. */
export function formProblem(state: VideoLabFormState): string | null {
  if (state.prompt.trim() === "") {
    return "Write a prompt first.";
  }
  if (state.kind === "h3_reference") {
    return referenceProblem(state) ?? stepsProblem(state) ?? seedProblem(state);
  }
  if (state.models.length === 0) {
    return "Choose one or more models.";
  }
  const duration = durationOf(state);
  if (duration === null || duration < DURATION_MIN_S || duration > DURATION_MAX_S) {
    return `The length must be from ${DURATION_MIN_S} to ${DURATION_MAX_S} seconds.`;
  }
  if (
    state.models.includes(H3_MODEL) &&
    (duration < H3_DURATION_MIN_S || duration > H3_DURATION_MAX_S)
  ) {
    return `MiniMax H3: the length must be from ${H3_DURATION_MIN_S} to ${H3_DURATION_MAX_S} seconds.`;
  }
  if (state.lastFrame !== null && state.firstFrame === null) {
    return "A last frame needs a first frame too.";
  }
  return (state.models.includes(H3_MODEL) ? stepsProblem(state) : null) ?? seedProblem(state);
}

/** The form as the request the server takes. */
export function toRequest(state: VideoLabFormState): LabVideoRunCreate {
  const negative = state.negativePrompt.trim();
  const h3 = state.models.includes(H3_MODEL);
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
    last_frame: state.lastFrame
      ? { source: state.lastFrame.source, id: state.lastFrame.id }
      : null,
    // Only MiniMax H3 has the field.
    num_inference_steps: h3 ? stepsOf(state) : null,
  };
}

/** The reference form as the request the server takes. Call it only when `formProblem` is null. */
export function toReferenceRequest(state: VideoLabFormState): H3ReferenceRunCreate {
  if (state.audio === null) {
    throw new Error("Choose an audio reference first.");
  }
  return {
    prompt: state.prompt,
    orientation: state.orientation,
    seed: state.seed.trim() === "" ? null : wholeNumber(state.seed),
    references: state.references.map((item) => ({ source: item.source, id: item.id })),
    audio: { source: state.audio.source, id: state.audio.id },
    match_audio_duration: state.matchAudio,
    duration_s: state.matchAudio ? null : durationOf(state),
    num_inference_steps: stepsOf(state),
  };
}

const H3_COST_TEXT =
  "MiniMax H3 is a GPU job that holds two GPUs (two slots) and can take more than 10 minutes.";

/**
 * What a click costs, for the line under the button: "5 to 10 minutes on one GPU" for an LTX
 * run, doubled for two, and MiniMax H3's two GPUs and longer wait said on their own.
 */
export function costText(models: LabVideoModel[]): string {
  const h3 = models.includes(H3_MODEL);
  const ltx = models.length - (h3 ? 1 : 0);
  if (!h3) {
    return ltxCostText(ltx, "run");
  }
  return ltx === 0 ? `One run: ${H3_COST_TEXT}` : `${ltxCostText(ltx, "LTX run")} ${H3_COST_TEXT}`;
}

function ltxCostText(count: number, noun: string): string {
  return count === 1
    ? `One ${noun}: a GPU job of 5 to 10 minutes.`
    : `${count} ${noun}s: ${count} GPU jobs of 5 to 10 minutes each, using the same GPU slots as scene clips.`;
}

/** What a MiniMax H3 reference clip costs. */
export function referenceCostText(): string {
  return `One run: ${H3_COST_TEXT}`;
}

/**
 * The six-part prompt of a MiniMax H3 reference clip with its blanks, for `pictureCount`
 * pictures. The parts and their order are the server's guide's; the words in brackets are for
 * the author to replace. `<Picture n>` and `<Audio 1>` are the labels of the files, in the order
 * they are sent, and `<Subject n>` names a person or thing defined from them.
 */
export function referenceSkeleton(pictureCount: number): string {
  const pictures = Array.from({ length: Math.max(pictureCount, 1) }, (_, index) => index + 1);
  return [
    "subject_definitions:",
    ...pictures.map(
      (number) => `<Subject ${number}> is [who or what], shown in <Picture ${number}>.`,
    ),
    "<Audio 1> is the voice-timbre reference for <Subject 1> (S1).",
    "",
    "summary:",
    "[reference generation + audio reference] <Subject 1> [what happens, and where].",
    "",
    "retention_analysis:",
    ...pictures.map(
      (number) =>
        `<Subject ${number}> (appears in [Shot 1]): fully_preserved - [what must stay the same].`,
    ),
    "<Audio 1>: reference - the voice timbre guides the delivery without copying the recording.",
    "",
    "detailed_description:",
    "The target video is [live-action, the light and the look].",
    "[Shot 1] [Shot size and angle], <Subject 1> (S1) [does something]. [Camera move.] They say, using the voice timbre referenced from <Audio 1>, <d>[English] [the words].</d>",
    "",
    "overall_soundscape:",
    "[1 to 4 sentences: ambience and physical sounds, no dialogue.]",
    "",
    "non_diegetic_music:",
    "N/A",
  ].join("\n");
}

/** What a shape choice is called: the size depends on the models in the form. */
export function shapeLabel(
  orientation: LabOrientation,
  state: Pick<VideoLabFormState, "kind" | "models">,
): string {
  const portrait = orientation === "portrait";
  const ltxSize = portrait ? "1088 x 1920" : "1920 x 1088";
  const h3Size = portrait ? "768 x 1344" : "1344 x 768";
  const name = portrait ? "Portrait" : "Landscape";
  if (state.kind === "h3_reference") {
    return `${name} ${h3Size}`;
  }
  if (!state.models.includes(H3_MODEL)) {
    return `${name} ${ltxSize}`;
  }
  // MiniMax H3 is trained at its own sizes whatever the LTX ones are.
  return state.models.length === 1 ? `${name} ${h3Size}` : `${name} (LTX ${ltxSize}, H3 ${h3Size})`;
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
    parts.push(run.params.match_audio_duration === true ? `${duration} s (the audio's)` : `${duration} s`);
  }
  const frames = numberParam(run, "num_frames");
  if (frames !== null) {
    parts.push(`${frames} frames requested`);
  }
  const steps = numberParam(run, "num_inference_steps");
  if (steps !== null) {
    parts.push(`${steps} steps`);
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

/** Whether a run is a MiniMax H3 reference clip: pictures and an audio reference, no frames. */
export function isReferenceRun(run: LabVideoRun): boolean {
  return run.video_model === H3_MODEL && run.references.length > 0;
}

/** Whether a run is an LTX clip made to match a recorded speech (made in the Characters tab). */
export function isLipSyncRun(run: LabVideoRun): boolean {
  return run.audio_input !== null && !isReferenceRun(run);
}

/**
 * The form that would make these runs again: the prompt and settings of the first run, with
 * every model the group used. The first frame is loaded only while its image still exists.
 * A MiniMax H3 reference clip comes back as the reference form.
 */
export function stateFromRuns(runs: LabVideoRun[]): VideoLabFormState {
  const first = runs[0];
  // MiniMax H3 records no recipe, so the first run that has one tells it.
  const mode = runs.map((run) => textParam(run, "mode")).find((text) => text !== null) ?? null;
  const orientation = textParam(first, "orientation");
  const duration = numberParam(first, "duration_s");
  const seed = numberParam(first, "seed");
  const steps = runs.map((run) => numberParam(run, "num_inference_steps")).find((n) => n !== null);
  const base: VideoLabFormState = {
    ...DEFAULT_FORM,
    prompt: first.prompt,
    models: runs.map((run) => run.video_model),
    mode: mode === "fast" ? "fast" : "quality",
    orientation: orientation === "landscape" ? "landscape" : "portrait",
    durationS: duration ?? DEFAULT_FORM.durationS,
    seed: seed === null ? "" : String(seed),
    negativePrompt: runs.map(negativePromptOf).find((text) => text !== null) ?? "",
    firstFrame: referenceOf(first.first_frame),
    lastFrame: referenceOf(first.last_frame),
    steps: steps === undefined || steps === null ? "" : String(steps),
  };
  if (!isReferenceRun(first)) {
    return base;
  }
  const audio = first.audio_input;
  const audioSeconds = numberParam(first, "audio_duration_s");
  return {
    ...base,
    kind: "h3_reference",
    models: [H3_MODEL],
    references: first.references
      .map((picture) => referenceOf(picture))
      .filter((item): item is ReferenceItem => item !== null),
    audio:
      audio === null || audioSeconds === null
        ? null
        : {
            source: audio.source,
            id: audio.id,
            label: audio.source === "voice" ? `voice ${audio.id}` : `speech ${audio.id}`,
            durationS: audioSeconds,
          },
    matchAudio: first.params.match_audio_duration === true,
  };
}

/** A frame a run used as a form item, only while its image still exists. */
function referenceOf(frame: LabVideoRun["first_frame"]): ReferenceItem | null {
  if (frame === null || frame.url === null) {
    return null;
  }
  return {
    source: frame.source,
    id: frame.id,
    url: frame.url,
    width: null,
    height: null,
    label: frame.source === "lab" ? `lab image ${frame.id}` : `project frame ${frame.id}`,
  };
}
