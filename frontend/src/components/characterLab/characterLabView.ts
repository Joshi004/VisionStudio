import type {
  Angle,
  CharacterIn,
  CharacterReference,
  CharacterTake,
  LibraryCharacter,
  TakeCreate,
  TakeRerun,
  TakeStep,
} from "../../api/characterLab";
import type { JobSummary } from "../../api/jobs";
import { isJobActive } from "../../api/polling";

/*
 * Pure helpers of the Character lab tab: the forms, what they send, which fields apply, and the
 * words shown. No React here. The limits repeat the server's own (`character_library.py`,
 * `character_takes.py`), only to avoid a pointless request: the server stays the judge.
 */

export type EraKind = LibraryCharacter["era_kind"];
export type Output = TakeCreate["output"];
export type Framing = TakeCreate["framing"];
export type Orientation = TakeCreate["orientation"];
export type VideoModel = NonNullable<TakeCreate["video_model"]>;
export type PromptKey = "image_prompt" | "video_prompt" | "delivery_instruction";

export const LIMITS = {
  name: 80,
  gender: 40,
  species: 40,
  appearance: 2000,
  outfit: 500,
  personality: 1000,
  notes: 1000,
  eraSetting: 200,
  ageMax: 2000,
  eraYearsMax: 10_000,
  voiceDescription: 500,
  voiceName: 80,
  /** What a character says, and the line read in an audition. */
  speech: 1000,
  action: 1000,
  negativePrompt: 2000,
  durationMin: 1,
  durationMax: 20,
  seedLimit: 2 ** 31,
  imagePrompt: 4000,
  videoPrompt: 4000,
  deliveryInstruction: 500,
} as const;

// --- Words -------------------------------------------------------------------------------------

export const ANGLES: readonly Angle[] = ["front", "three_quarter", "profile", "back", "face"];

export const ANGLE_LABELS: Record<Angle, string> = {
  front: "Front",
  three_quarter: "Three-quarter",
  profile: "Profile",
  back: "Back",
  face: "Face",
};

export const STEP_LABELS: Record<TakeStep, string> = {
  prompts: "Writing the prompts",
  image: "Picture",
  voice: "Speech",
  video: "Video",
};

export const FRAMING_LABELS: Record<Framing, string> = {
  close_up: "Close-up",
  medium: "Medium",
  wide: "Wide",
};

export const ORIENTATION_LABELS: Record<Orientation, string> = {
  portrait: "Portrait",
  landscape: "Landscape",
};

export const OUTPUT_LABELS: Record<Output, string> = {
  image: "Image",
  video: "Video",
  audio: "Audio",
};

export const VIDEO_MODEL_LABELS: Record<VideoModel, string> = {
  "ltx-2.3": "LTX-2.3",
  "ltx-2.5": "LTX-2.5",
};

export const PROMPT_LABELS: Record<PromptKey, string> = {
  image_prompt: "Picture prompt",
  video_prompt: "Video prompt",
  delivery_instruction: "Delivery instruction",
};

export const PROMPT_HINTS: Record<PromptKey, string> = {
  image_prompt: "Edits the character's reference pictures into this scene.",
  video_prompt: "What happens over the next seconds: the motion, the camera and the expression.",
  delivery_instruction: "How the character's voice reads the line: tone, emotion and pace.",
};

export const PROMPT_LIMITS: Record<PromptKey, number> = {
  image_prompt: LIMITS.imagePrompt,
  video_prompt: LIMITS.videoPrompt,
  delivery_instruction: LIMITS.deliveryInstruction,
};

/** "human, 34, female": what to show under a character's name. */
export function characterSubtitle(character: LibraryCharacter): string {
  const parts = [character.species];
  if (character.age !== null) {
    parts.push(`${character.age} years old`);
  }
  if (character.gender !== "") {
    parts.push(character.gender);
  }
  return parts.join(", ");
}

/** "Present", "About 200 years in the past, Victorian London". */
export function eraText(character: LibraryCharacter): string {
  const setting = character.era_setting ? `, ${character.era_setting}` : "";
  if (character.era_kind === "present") {
    return `Present${setting}`;
  }
  const direction = character.era_kind === "past" ? "in the past" : "in the future";
  return `About ${character.era_years ?? "?"} years ${direction}${setting}`;
}

/** The picture of one angle to show: the cut-out when there is one, else the white backdrop. */
export function referencePicture(reference: CharacterReference): string | null {
  return reference.cutout_url ?? reference.url;
}

/** The character's front picture, for a card. Null before it has a ready look. */
export function frontPicture(character: LibraryCharacter): string | null {
  const front = character.current_look?.references.find((reference) => reference.angle === "front");
  return front ? referencePicture(front) : null;
}

/** Can a take be made now? Only from a look that is ready: a look that is still being redone
 * may lack the angle a take needs.
 */
export function lookProblem(character: LibraryCharacter): string | null {
  const look = character.current_look;
  if (look === null) {
    return "This character has no look yet. Make one first: it is what every picture and clip is made from.";
  }
  if (look.status !== "ready") {
    return "A picture of the look is still being made. Wait until it is ready.";
  }
  return null;
}

// --- Numbers typed in a text box -------------------------------------------------------------

/** A whole number typed in a box, or null when it is not one. Empty is not a number. */
function wholeNumber(value: string): number | null {
  const text = value.trim();
  if (!/^-?\d{1,15}$/.test(text)) {
    return null;
  }
  return Number(text);
}

// --- The profile form -------------------------------------------------------------------------

export type ProfileFormState = {
  name: string;
  age: string;
  gender: string;
  species: string;
  eraKind: EraKind;
  eraYears: string;
  eraSetting: string;
  appearance: string;
  outfit: string;
  personality: string;
  notes: string;
  hasVisibleMouth: boolean;
};

export const DEFAULT_PROFILE: ProfileFormState = {
  name: "",
  age: "",
  gender: "",
  species: "",
  eraKind: "present",
  eraYears: "",
  eraSetting: "",
  appearance: "",
  outfit: "",
  personality: "",
  notes: "",
  hasVisibleMouth: true,
};

export function profileFromCharacter(character: LibraryCharacter): ProfileFormState {
  return {
    name: character.name,
    age: character.age === null ? "" : String(character.age),
    gender: character.gender,
    species: character.species,
    eraKind: character.era_kind,
    eraYears: character.era_years === null ? "" : String(character.era_years),
    eraSetting: character.era_setting ?? "",
    appearance: character.appearance,
    outfit: character.outfit ?? "",
    personality: character.personality ?? "",
    notes: character.notes ?? "",
    hasVisibleMouth: character.has_visible_mouth,
  };
}

function tooLong(value: string, limit: number, what: string): string | null {
  return value.length > limit ? `The ${what} must be at most ${limit.toLocaleString()} characters.` : null;
}

/** The first thing wrong with the profile, or null. Same rules as the server. */
export function profileProblem(form: ProfileFormState): string | null {
  if (form.name.trim() === "") {
    return "Give the character a name.";
  }
  if (form.species.trim() === "") {
    return "Give the character a species.";
  }
  if (form.appearance.trim() === "") {
    return "Describe the character's appearance.";
  }
  const lengths = [
    tooLong(form.name, LIMITS.name, "name"),
    tooLong(form.species, LIMITS.species, "species"),
    tooLong(form.gender, LIMITS.gender, "gender"),
    tooLong(form.appearance, LIMITS.appearance, "appearance"),
    tooLong(form.outfit, LIMITS.outfit, "outfit"),
    tooLong(form.personality, LIMITS.personality, "personality"),
    tooLong(form.notes, LIMITS.notes, "notes"),
    tooLong(form.eraSetting, LIMITS.eraSetting, "era setting"),
  ];
  const long = lengths.find((message) => message !== null);
  if (long) {
    return long;
  }
  if (form.age.trim() !== "") {
    const age = wholeNumber(form.age);
    if (age === null || age < 0 || age > LIMITS.ageMax) {
      return `Age must be a whole number from 0 to ${LIMITS.ageMax.toLocaleString()}.`;
    }
  }
  if (form.eraKind !== "present") {
    const years = wholeNumber(form.eraYears);
    if (years === null || years < 1 || years > LIMITS.eraYearsMax) {
      return `Give the number of years, from 1 to ${LIMITS.eraYearsMax.toLocaleString()}.`;
    }
  }
  return null;
}

function orNull(value: string): string | null {
  const text = value.trim();
  return text === "" ? null : text;
}

/**
 * What the profile sends. Every field is sent, so the same body creates a character and (as a
 * PATCH) saves an edit. An empty text is sent as null, and the present has no years.
 */
export function toCharacterIn(form: ProfileFormState): CharacterIn {
  return {
    name: form.name.trim(),
    age: form.age.trim() === "" ? null : wholeNumber(form.age),
    gender: form.gender.trim(),
    species: form.species.trim(),
    era_kind: form.eraKind,
    era_years: form.eraKind === "present" ? null : wholeNumber(form.eraYears),
    era_setting: orNull(form.eraSetting),
    appearance: form.appearance.trim(),
    outfit: orNull(form.outfit),
    personality: orNull(form.personality),
    notes: orNull(form.notes),
    has_visible_mouth: form.hasVisibleMouth,
  };
}

// --- The voice --------------------------------------------------------------------------------

/** The text with its whitespace collapsed, the way the server stores it. */
export function normalizedText(value: string): string {
  return value.split(/\s+/).filter((word) => word !== "").join(" ");
}

/** The first thing wrong with an audition (the voice description and the line), or null. */
export function auditionProblem(description: string, line: string): string | null {
  if (description.trim() === "") {
    return "Describe the voice first.";
  }
  if (line.trim() === "") {
    return "Write the sample line first.";
  }
  return (
    tooLong(description, LIMITS.voiceDescription, "voice description") ??
    tooLong(line, LIMITS.speech, "sample line")
  );
}

/** The first thing wrong with the name a chosen sample is saved under, or null. */
export function voiceNameProblem(name: string): string | null {
  if (name.trim() === "") {
    return "Give the voice a name.";
  }
  return tooLong(name, LIMITS.voiceName, "name");
}

// --- The Create panel -------------------------------------------------------------------------

export type TakeFormState = {
  output: Output;
  action: string;
  dialogue: string;
  videoModel: VideoModel;
  lipSync: boolean;
  durationS: string;
  framing: Framing;
  orientation: Orientation;
  seed: string;
  negativePrompt: string;
};

export const DEFAULT_TAKE_FORM: TakeFormState = {
  output: "image",
  action: "",
  dialogue: "",
  videoModel: "ltx-2.5",
  // On by default; it only applies to a video with dialogue and a visible mouth.
  lipSync: true,
  durationS: "5",
  framing: "medium",
  orientation: "portrait",
  seed: "",
  negativePrompt: "",
};

export function hasVoice(character: LibraryCharacter): boolean {
  return character.voice !== null;
}

/** Which fields of the Create panel apply, from what is made and who makes it. */
export type VisibleFields = {
  /** "Audio" is offered. */
  audio: boolean;
  action: boolean;
  dialogue: boolean;
  videoModel: boolean;
  lipSync: boolean;
  length: boolean;
  framing: boolean;
  orientation: boolean;
  seed: boolean;
  negativePrompt: boolean;
};

export function visibleFields(form: TakeFormState, character: LibraryCharacter): VisibleFields {
  const talks = hasVoice(character);
  const hasDialogue = form.dialogue.trim() !== "";
  const visual = form.output === "image" || form.output === "video";
  const video = form.output === "video";
  return {
    audio: talks,
    action: form.output !== "audio",
    // A mute character has no dialogue. A picture does not use it.
    dialogue: talks && form.output !== "image",
    videoModel: video,
    lipSync: video && talks && hasDialogue && character.has_visible_mouth,
    // With speech the clip follows the speech: only a silent clip has a length.
    length: video && !(talks && hasDialogue),
    framing: visual,
    orientation: visual,
    seed: visual,
    // LTX-2.5 ignores a negative prompt.
    negativePrompt: video && form.videoModel === "ltx-2.3",
  };
}

/** The dialogue that counts: what is typed, but only where the field is shown. */
function effectiveDialogue(form: TakeFormState, fields: VisibleFields): string | null {
  return fields.dialogue ? orNull(form.dialogue) : null;
}

/** The first thing wrong with the Create form, or null. Same rules as the server. */
export function takeFormProblem(form: TakeFormState, character: LibraryCharacter): string | null {
  const fields = visibleFields(form, character);
  if (form.output === "audio" && !fields.audio) {
    return "This character has no voice. Give it one first, or choose Image or Video.";
  }
  const lookIssue = lookProblem(character);
  if (lookIssue !== null) {
    return lookIssue;
  }
  const dialogue = effectiveDialogue(form, fields);
  if (form.output === "audio" && dialogue === null) {
    return "Write what the character says.";
  }
  const long =
    tooLong(form.action, LIMITS.action, "action") ??
    tooLong(form.dialogue, LIMITS.speech, "dialogue") ??
    (fields.negativePrompt ? tooLong(form.negativePrompt, LIMITS.negativePrompt, "negative prompt") : null);
  if (long !== null) {
    return long;
  }
  if (fields.seed && form.seed.trim() !== "") {
    const seed = wholeNumber(form.seed);
    if (seed === null || seed < 0 || seed >= LIMITS.seedLimit) {
      return `The seed must be a whole number from 0 to ${(LIMITS.seedLimit - 1).toLocaleString()}.`;
    }
  }
  if (fields.length) {
    const seconds = Number(form.durationS);
    if (
      form.durationS.trim() === "" ||
      !Number.isFinite(seconds) ||
      seconds < LIMITS.durationMin ||
      seconds > LIMITS.durationMax
    ) {
      return `The length must be from ${LIMITS.durationMin} to ${LIMITS.durationMax} seconds.`;
    }
  }
  return null;
}

/** What one click on "Create" will start, in plain words: every step is a paid call. */
export function takeCostNote(form: TakeFormState, character: LibraryCharacter): string {
  const fields = visibleFields(form, character);
  const speaks = effectiveDialogue(form, fields) !== null;
  if (form.output === "image") {
    return "One call to the language model and one picture (a GPU job of a few minutes).";
  }
  if (form.output === "audio") {
    return "One call to the language model and one speech (a GPU job of one to three minutes).";
  }
  if (!speaks) {
    return "One call to the language model, one picture and one clip (5 to 10 minutes).";
  }
  return fields.lipSync && form.lipSync
    ? "One call to the language model, one picture, one speech and one lip-synced clip (5 to 10 minutes, plus several for the lip sync)."
    : "One call to the language model, one picture, one speech and one clip (5 to 10 minutes).";
}

/** What "Create" sends. It always runs the whole chain (`run: "all"`). */
export function toTakeIn(form: TakeFormState, character: LibraryCharacter): TakeCreate {
  const fields = visibleFields(form, character);
  return {
    run: "all",
    output: form.output,
    action: fields.action ? orNull(form.action) : null,
    dialogue: effectiveDialogue(form, fields),
    framing: form.framing,
    orientation: form.orientation,
    video_model: fields.videoModel ? form.videoModel : null,
    lip_sync: fields.lipSync && form.lipSync,
    duration_s: fields.length ? Number(form.durationS) : null,
    seed: fields.seed && form.seed.trim() !== "" ? wholeNumber(form.seed) : null,
    negative_prompt: fields.negativePrompt ? orNull(form.negativePrompt) : null,
  };
}

// --- A take's steps and prompts ---------------------------------------------------------------

export type StepState = "done" | "running" | "failed" | "todo";

export type StepRow = {
  step: TakeStep;
  state: StepState;
  job: JobSummary | null;
};

/** The steps a take has, in the order they run, from what it makes and whether it speaks. */
export function takeStepOrder(take: CharacterTake): TakeStep[] {
  const speaks = take.dialogue !== null && take.dialogue.trim() !== "";
  if (take.output === "image") {
    return ["prompts", "image"];
  }
  if (take.output === "audio") {
    return ["prompts", "voice"];
  }
  return speaks ? ["prompts", "image", "voice", "video"] : ["prompts", "image", "video"];
}

function stepState(job: JobSummary | null, finished: boolean): StepState {
  if (finished) {
    return "done";
  }
  if (isJobActive(job)) {
    return "running";
  }
  if (job !== null && (job.status === "failed" || job.status === "cancelled")) {
    return "failed";
  }
  return "todo";
}

/** Each step of a take with how far it got. */
export function takeSteps(take: CharacterTake): StepRow[] {
  return takeStepOrder(take).map((step) => {
    switch (step) {
      case "prompts":
        return { step, job: take.prompt_job, state: stepState(take.prompt_job, take.prompt_job?.status === "succeeded") };
      case "image":
        return { step, job: take.image?.job ?? null, state: stepState(take.image?.job ?? null, !!take.image?.url) };
      case "voice":
        return { step, job: take.voice?.job ?? null, state: stepState(take.voice?.job ?? null, !!take.voice?.url) };
      case "video":
        return { step, job: take.video?.job ?? null, state: stepState(take.video?.job ?? null, !!take.video?.url) };
    }
  });
}

/** The prompts a take uses (the server's `needed_keys`), in the order they are shown. */
export function promptKeys(take: CharacterTake): PromptKey[] {
  const speaks = take.dialogue !== null && take.dialogue.trim() !== "";
  if (take.output === "image") {
    return ["image_prompt"];
  }
  if (take.output === "audio") {
    return ["delivery_instruction"];
  }
  return speaks ? ["image_prompt", "video_prompt", "delivery_instruction"] : ["image_prompt", "video_prompt"];
}

export type PromptDrafts = Partial<Record<PromptKey, string>>;

function storedPrompt(take: CharacterTake, key: PromptKey): string {
  const value = take.prompts[key];
  return typeof value === "string" ? value : "";
}

/** The take's stored prompts, as the text boxes start. */
export function promptDraftsFrom(take: CharacterTake): PromptDrafts {
  const drafts: PromptDrafts = {};
  for (const key of promptKeys(take)) {
    drafts[key] = storedPrompt(take, key);
  }
  return drafts;
}

/** Only the prompts the author changed: the server clears and remakes exactly those. */
export function changedPrompts(take: CharacterTake, drafts: PromptDrafts): TakeRerun {
  const changed: TakeRerun = {};
  for (const key of promptKeys(take)) {
    const draft = drafts[key];
    if (draft !== undefined && draft.trim() !== storedPrompt(take, key).trim()) {
      changed[key] = draft.trim();
    }
  }
  return changed;
}

/** The first thing wrong with the changed prompts, or null. Same rules as the server. */
export function rerunProblem(take: CharacterTake, drafts: PromptDrafts): string | null {
  const changed = changedPrompts(take, drafts);
  const keys = Object.keys(changed) as PromptKey[];
  if (keys.length === 0) {
    return "Change a prompt first.";
  }
  for (const key of keys) {
    const text = changed[key] ?? "";
    const name = PROMPT_LABELS[key].toLowerCase();
    if (text === "") {
      return `The ${name} cannot be blank.`;
    }
    if (text.length > PROMPT_LIMITS[key]) {
      return `The ${name} must be at most ${PROMPT_LIMITS[key].toLocaleString()} characters.`;
    }
  }
  return null;
}

/** "Video · LTX-2.5 · Medium · Portrait": a take in one line. */
export function takeSummary(take: CharacterTake): string {
  const parts: string[] = [OUTPUT_LABELS[take.output]];
  if (take.output === "video" && take.video_model !== null) {
    parts.push(VIDEO_MODEL_LABELS[take.video_model]);
    if (take.lip_sync) {
      parts.push("lip sync");
    }
  }
  if (take.output !== "audio") {
    parts.push(FRAMING_LABELS[take.framing], ORIENTATION_LABELS[take.orientation]);
  }
  return parts.join(" · ");
}
