import type { VoiceLabRun, VoiceLabRunCreate } from "../../api/voiceLab";

export type VoiceMode = "design" | "clone" | "direction";

/** The server's limits for one request (the OpenAPI document of its Breeze TTS endpoint). */
export const TEXT_MAX_CHARS = 1000;
export const INSTRUCTION_MAX_CHARS = 500;
export const TRANSCRIPT_MAX_CHARS = 1000;
export const NAME_MAX_CHARS = 80;
export const CFG_SCALE_MAX = 10;
const SEED_MAX = 2147483647;

export const MODES: { value: VoiceMode; label: string; help: string }[] = [
  {
    value: "design",
    label: "Design",
    help: "A new voice made from a description. Write the description in the same language as the text.",
  },
  {
    value: "clone",
    label: "Clone",
    help: "A saved voice reads the text, with its tone, rhythm and style.",
  },
  {
    value: "direction",
    label: "Direction",
    help: "A saved voice reads the text, steered by an instruction: tone, emotion, pace.",
  },
];

export type VoiceLabFormState = {
  mode: VoiceMode;
  text: string;
  /** Design: describes the voice (optional). Direction: how to say it. Clone: not used. */
  instruction: string;
  /** The saved voice for clone and direction, as the text of its id. */
  voiceId: string | null;
  /** Empty: a random seed. */
  seed: string;
  /** Empty: 4 with an instruction, 1 without (what the server recommends). */
  cfgScale: string;
};

export const DEFAULT_FORM: VoiceLabFormState = {
  mode: "design",
  text: "",
  instruction: "",
  voiceId: null,
  seed: "",
  cfgScale: "",
};

/** The modes that speak in a saved voice. */
export function needsVoice(mode: VoiceMode): boolean {
  return mode !== "design";
}

/** The modes that take an instruction. */
export function takesInstruction(mode: VoiceMode): boolean {
  return mode !== "clone";
}

function wholeNumber(text: string): number | null {
  const trimmed = text.trim();
  return /^\d{1,10}$/.test(trimmed) ? Number(trimmed) : null;
}

function cfgScaleOf(text: string): number | null {
  const trimmed = text.trim();
  if (trimmed === "") {
    return null;
  }
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : Number.NaN;
}

/** Why the form cannot be run, or null when it can. The server checks everything again. */
export function formProblem(state: VoiceLabFormState): string | null {
  if (state.text.trim() === "") {
    return "Write the text to speak first.";
  }
  if (state.text.trim().length > TEXT_MAX_CHARS) {
    return `The text must be at most ${TEXT_MAX_CHARS} characters.`;
  }
  if (needsVoice(state.mode) && state.voiceId === null) {
    return "Choose the saved voice that reads the text.";
  }
  if (state.mode === "direction" && state.instruction.trim() === "") {
    return "Direction needs an instruction: tone, emotion or pace.";
  }
  if (state.instruction.trim().length > INSTRUCTION_MAX_CHARS) {
    return `The instruction must be at most ${INSTRUCTION_MAX_CHARS} characters.`;
  }
  if (state.seed.trim() !== "") {
    const seed = wholeNumber(state.seed);
    if (seed === null || seed > SEED_MAX) {
      return `The seed must be a whole number from 0 to ${SEED_MAX}.`;
    }
  }
  const cfgScale = cfgScaleOf(state.cfgScale);
  if (cfgScale !== null && !(cfgScale > 0 && cfgScale <= CFG_SCALE_MAX)) {
    return `The guidance must be above 0 and at most ${CFG_SCALE_MAX}.`;
  }
  return null;
}

/** The form as the request the server takes. */
export function toRequest(state: VoiceLabFormState): VoiceLabRunCreate {
  const instruction = state.instruction.trim();
  return {
    mode: state.mode,
    text: state.text,
    instruction: takesInstruction(state.mode) && instruction !== "" ? instruction : null,
    voice_id: needsVoice(state.mode) && state.voiceId !== null ? Number(state.voiceId) : null,
    seed: state.seed.trim() === "" ? null : wholeNumber(state.seed),
    cfg_scale: cfgScaleOf(state.cfgScale),
  };
}

function numberParam(run: VoiceLabRun, key: string): number | null {
  const value = run.params[key];
  return typeof value === "number" ? value : null;
}

/** The settings a run was made with, as a short line: "clone · Anna · seed 12 · guidance 1". */
export function paramsLine(run: VoiceLabRun): string {
  const parts: string[] = [run.mode];
  if (run.voice !== null) {
    parts.push(run.voice.name);
  }
  const seed = numberParam(run, "seed");
  if (seed !== null) {
    parts.push(`seed ${seed}`);
  }
  const cfgScale = numberParam(run, "cfg_scale");
  if (cfgScale !== null) {
    parts.push(`guidance ${cfgScale}`);
  }
  if (run.duration_s !== null) {
    parts.push(`${run.duration_s.toFixed(1)} s`);
  }
  return parts.join(" · ");
}

/**
 * The form that would make this run again, with the seed kept so the same inputs give the same
 * speech. A voice that is gone cannot be chosen again.
 */
export function stateFromRun(run: VoiceLabRun): VoiceLabFormState {
  const seed = numberParam(run, "seed");
  const cfgScale = numberParam(run, "cfg_scale");
  return {
    mode: run.mode,
    text: run.text,
    instruction: run.instruction ?? "",
    voiceId: run.voice !== null ? String(run.voice.id) : null,
    seed: seed === null ? "" : String(seed),
    cfgScale: cfgScale === null ? "" : String(cfgScale),
  };
}
