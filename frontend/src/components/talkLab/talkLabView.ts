import type { Character } from "../../api/characters";
import type { TalkStep, TalkTake, TalkTakeCreate } from "../../api/talkLab";
import type { ReferenceItem } from "../imageLab/labView";
import { needsVoice, type VoiceMode } from "../voiceLab/voiceLabView";

export type TalkOrientation = "portrait" | "landscape";
/** Whether the take makes a new speech, or reuses one an earlier run made. */
export type SpeechSource = "new" | "reuse";
/** What a click starts: the whole chain, only the speech, or only the clip. */
export type TalkRun = TalkTakeCreate["run"];

/** The server's limits (`services/talk_prompt_writer.py` and `video_lab.py`). */
export const DIALOGUE_MAX_CHARS = 1000;
export const CHARACTER_NOTE_MAX_CHARS = 2000;
export const DELIVERY_NOTE_MAX_CHARS = 500;
export const VOICE_INSTRUCTION_MAX_CHARS = 500;
export const VIDEO_PROMPT_MAX_CHARS = 8000;
export const NEGATIVE_PROMPT_MAX_CHARS = 2000;
/** The longest clip the video model makes. The clip is as long as the speech. */
export const CLIP_MAX_S = 20;
const SEED_LIMIT = 2 ** 31;

export type TalkFormState = {
  /** The line the character says. */
  dialogue: string;
  /** The picture the character is made from. */
  image: ReferenceItem | null;
  /** The cast character the picture and the voice came from, as the text of its id. */
  characterId: string | null;
  /** What you say about the character. Empty: the cast character's description is used. */
  characterNote: string;
  /** How the line is delivered ("gruff but quietly worried"). Optional. */
  deliveryNote: string;
  orientation: TalkOrientation;
  /** What steers the speech model. Empty: written by the language model. */
  voiceInstruction: string;
  /** What the video model shows. Empty: written by the language model. */
  videoPrompt: string;
  speech: SpeechSource;
  voiceMode: VoiceMode;
  /** The saved voice for clone and direction, as the text of its id. */
  voiceId: string | null;
  /** The Voice lab run whose speech is reused, as the text of its id. */
  reuseRunId: string | null;
  /** Empty: a random seed. */
  videoSeed: string;
  /** Empty: the pipeline's own default applies. */
  negativePrompt: string;
};

export const DEFAULT_FORM: TalkFormState = {
  dialogue: "",
  image: null,
  characterId: null,
  characterNote: "",
  deliveryNote: "",
  orientation: "portrait",
  voiceInstruction: "",
  videoPrompt: "",
  speech: "new",
  voiceMode: "design",
  voiceId: null,
  reuseRunId: null,
  videoSeed: "",
  negativePrompt: "",
};

function wholeNumber(text: string): number | null {
  const trimmed = text.trim();
  return /^\d{1,10}$/.test(trimmed) ? Number(trimmed) : null;
}

function orNull(text: string): string | null {
  const trimmed = text.trim();
  return trimmed === "" ? null : trimmed;
}

// --- How long the speech will be ---------------------------------------------------------------

// Spoken English is about 150 words a minute and spoken Chinese about 4 characters a second.
// This is only a guide: the clip is as long as the speech that is really made.
const WORDS_PER_SECOND = 2.5;
const CJK_CHARS_PER_SECOND = 4;
const CJK = /[\u3400-\u9fff]/g;

/** A guess at how long the dialogue takes to say, in seconds. 0 for no text. */
export function estimateSpeechSeconds(dialogue: string): number {
  const cjk = (dialogue.match(CJK) ?? []).length;
  const words = dialogue.replace(CJK, " ").split(/\s+/).filter((word) => word !== "").length;
  return words / WORDS_PER_SECOND + cjk / CJK_CHARS_PER_SECOND;
}

// --- The form ----------------------------------------------------------------------------------

/** Whether the voice step will need a voice instruction written (by hand or by the AI). */
export function wantsVoiceInstruction(state: TalkFormState): boolean {
  return state.speech === "new" && state.voiceMode !== "clone";
}

/**
 * Why a click cannot start `run`, or null when it can. The server checks everything again, and
 * knows things this does not (that a reused speech is finished, that an image still exists).
 */
export function formProblem(state: TalkFormState, run: TalkRun): string | null {
  const dialogue = state.dialogue.trim();
  if (dialogue === "") {
    return "Write the line the character says first.";
  }
  if (dialogue.length > DIALOGUE_MAX_CHARS) {
    return `The dialogue must be at most ${DIALOGUE_MAX_CHARS.toLocaleString()} characters.`;
  }
  if (state.image === null) {
    return "Choose the character's picture first.";
  }
  if (state.characterNote.trim().length > CHARACTER_NOTE_MAX_CHARS) {
    return `The character description must be at most ${CHARACTER_NOTE_MAX_CHARS.toLocaleString()} characters.`;
  }
  if (state.deliveryNote.trim().length > DELIVERY_NOTE_MAX_CHARS) {
    return `The delivery note must be at most ${DELIVERY_NOTE_MAX_CHARS} characters.`;
  }
  if (state.voiceInstruction.trim().length > VOICE_INSTRUCTION_MAX_CHARS) {
    return `The voice instruction must be at most ${VOICE_INSTRUCTION_MAX_CHARS} characters.`;
  }
  if (state.videoPrompt.trim().length > VIDEO_PROMPT_MAX_CHARS) {
    return `The video prompt must be at most ${VIDEO_PROMPT_MAX_CHARS.toLocaleString()} characters.`;
  }
  if (state.negativePrompt.trim().length > NEGATIVE_PROMPT_MAX_CHARS) {
    return `The negative prompt must be at most ${NEGATIVE_PROMPT_MAX_CHARS.toLocaleString()} characters.`;
  }
  if (state.videoSeed.trim() !== "") {
    const seed = wholeNumber(state.videoSeed);
    if (seed === null || seed >= SEED_LIMIT) {
      return `The seed must be a whole number from 0 to ${SEED_LIMIT - 1}.`;
    }
  }

  if (state.speech === "reuse") {
    if (run === "voice") {
      return "The speech step makes a new speech. Choose New speech, or run the video.";
    }
    if (state.reuseRunId === null) {
      return "Choose the speech to reuse.";
    }
  } else {
    if (run === "video") {
      return "The video step needs a finished speech. Make one first, or reuse an earlier one.";
    }
    if (needsVoice(state.voiceMode) && state.voiceId === null) {
      return "Choose the saved voice that reads the line.";
    }
    if (run === "voice" && state.voiceMode === "direction" && state.voiceInstruction.trim() === "") {
      return "Direction needs an instruction: tone, emotion or pace. Write it, or write the prompts with AI first.";
    }
  }
  if (run === "video" && state.videoPrompt.trim() === "") {
    return "Write the video prompt first, or write the prompts with AI.";
  }
  return null;
}

/** The form as the request the server takes. */
export function toRequest(state: TalkFormState, run: TalkRun): TalkTakeCreate {
  const reuse = state.speech === "reuse";
  const image = state.image;
  return {
    run,
    dialogue: state.dialogue,
    image: { source: image?.source ?? "lab", id: image?.id ?? 0 },
    character_id: state.characterId === null ? null : Number(state.characterId),
    character_note: orNull(state.characterNote),
    delivery_note: orNull(state.deliveryNote),
    voice_mode: reuse ? null : state.voiceMode,
    voice_id: !reuse && needsVoice(state.voiceMode) && state.voiceId !== null ? Number(state.voiceId) : null,
    reuse_voice_run_id: reuse && state.reuseRunId !== null ? Number(state.reuseRunId) : null,
    voice_instruction: orNull(state.voiceInstruction),
    video_prompt: orNull(state.videoPrompt),
    orientation: state.orientation,
    video_seed: state.videoSeed.trim() === "" ? null : wholeNumber(state.videoSeed),
    negative_prompt: orNull(state.negativePrompt),
  };
}

// --- Loading things into the form --------------------------------------------------------------

type Picture = { source: "lab" | "asset"; id: number; url: string | null } | null;

/** A picture as a form item, only while its image still exists. */
export function referenceFromPicture(picture: Picture): ReferenceItem | null {
  if (picture === null || picture.url === null) {
    return null;
  }
  return {
    source: picture.source,
    id: picture.id,
    url: picture.url,
    width: null,
    height: null,
    label: picture.source === "lab" ? `lab image ${picture.id}` : `project frame ${picture.id}`,
  };
}

/**
 * The form with a cast character chosen: its picture, and its default voice. A saved voice that
 * has a voice description too is directed by it; a saved voice alone is cloned as it is; a
 * description alone makes a voice. A character with no voice leaves the voice settings alone.
 * What you wrote about the character is kept: the description of the cast is used when it is empty.
 */
export function withCharacter(state: TalkFormState, character: Character): TalkFormState {
  const next: TalkFormState = {
    ...state,
    characterId: String(character.id),
    image: referenceFromPicture(character.image) ?? state.image,
  };
  if (state.speech === "reuse") {
    return next;
  }
  if (character.voice !== null) {
    const instruction = character.voice_instruction ?? "";
    return {
      ...next,
      voiceMode: instruction === "" ? "clone" : "direction",
      voiceId: String(character.voice.id),
      voiceInstruction: instruction === "" ? state.voiceInstruction : instruction,
    };
  }
  if (character.voice_instruction) {
    return {
      ...next,
      voiceMode: "design",
      voiceId: null,
      voiceInstruction: character.voice_instruction,
    };
  }
  return next;
}

/**
 * The form that would make this take again. With `reuseSpeech` the take's own speech is reused,
 * so only the clip is made again; without it a take that made its own speech makes a new one
 * with the same settings, and a take that reused a speech reuses it again.
 */
export function stateFromTake(take: TalkTake, reuseSpeech: boolean): TalkFormState {
  const speechRunId = take.voice_run?.id ?? null;
  const reuse = (reuseSpeech || take.voice_mode === null) && speechRunId !== null;
  return {
    dialogue: take.dialogue,
    image: referenceFromPicture(take.image),
    characterId: take.character === null ? null : String(take.character.id),
    characterNote: take.character_note ?? "",
    deliveryNote: take.delivery_note ?? "",
    orientation: take.orientation,
    voiceInstruction: take.voice_instruction ?? "",
    videoPrompt: take.video_prompt ?? "",
    speech: reuse ? "reuse" : "new",
    voiceMode: take.voice_mode ?? DEFAULT_FORM.voiceMode,
    voiceId: take.voice_id === null ? null : String(take.voice_id),
    reuseRunId: reuse && speechRunId !== null ? String(speechRunId) : null,
    videoSeed: "",
    negativePrompt: take.negative_prompt ?? "",
  };
}

// --- Reading a take ----------------------------------------------------------------------------

export const STEP_LABELS: Record<TalkStep, string> = {
  prompts: "Write prompts",
  voice: "Make speech",
  video: "Make video",
};

export type StepState = "not started" | "waiting" | "running" | "done" | "failed";

/** Where one step of a take is, from its job (and, for the speech and clip, its file). */
export function stepState(
  job: { status: string } | null | undefined,
  hasResult: boolean,
): StepState {
  if (hasResult) {
    return "done";
  }
  if (job === null || job === undefined) {
    return "not started";
  }
  if (job.status === "queued") {
    return "waiting";
  }
  if (job.status === "running") {
    return "running";
  }
  return job.status === "succeeded" ? "done" : "failed";
}

export const STEP_STATE_COLORS: Record<StepState, string> = {
  "not started": "gray",
  waiting: "gray",
  running: "blue",
  done: "green",
  failed: "red",
};
