import type {
  Angle,
  AudioMarker,
  CharacterIn,
  CharacterReference,
  CharacterTake,
  CharacterVersion,
  LibraryCharacter,
  TakeCreate,
  TakeRerun,
  TakeStep,
} from "../../api/characterLab";
import type { JobSummary } from "../../api/jobs";
import { isJobActive } from "../../api/polling";
import type { ReferenceItem } from "../imageLab/labView";
import {
  H3_STEPS_MAX,
  H3_STEPS_MIN,
  type AudioChoice,
} from "../videoLab/videoLabView";

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
export type PromptKey = CharacterTake["prompt_keys"][number];

/** The id of the Create panel, so "New take from this" can scroll to it. */
export const CREATE_PANEL_ID = "character-create-panel";
export const H3_MODEL: VideoModel = "minimax-h3";

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
  lastFramePrompt: 4000,
  videoPrompt: 4000,
  /** A MiniMax H3 video prompt is several sections long. */
  h3VideoPrompt: 8000,
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
  last_frame: "Last frame",
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

export const VIDEO_MODELS: readonly VideoModel[] = ["ltx-2.3", "ltx-2.5", "minimax-h3"];

export const VIDEO_MODEL_LABELS: Record<VideoModel, string> = {
  "ltx-2.3": "LTX-2.3",
  "ltx-2.5": "LTX-2.5",
  "minimax-h3": "MiniMax H3",
};

/**
 * How a MiniMax H3 clip uses the speech, in MiniMax's own words for it (the guide for its
 * reference mode). They are listed from the one that follows the voice to the one that copies the
 * most, with `reference` first because it is the one to hear a new line in a character's voice.
 */
export const AUDIO_MARKERS: readonly AudioMarker[] = [
  "reference",
  "partially_copy",
  "fully_copy",
  "weak_reference",
];

export const AUDIO_MARKER_HINTS: Record<AudioMarker, string> = {
  reference:
    "The voice (its timbre and delivery) is followed, not copied: H3 speaks the dialogue in a voice like the speech's. A third-party guide (not MiniMax's) says this transfers better when the speech says a different sentence.",
  partially_copy:
    "The speech's words, timing and pauses are copied, and H3 adds other sound around it. The dialogue must be exactly what the speech says.",
  fully_copy:
    "The speech is the clip's whole soundtrack, copied as it is, so the clip is as long as the speech. The dialogue must be exactly what the speech says.",
  weak_reference: "Only a broad hint: the speech's gender, age and energy. The loosest option.",
};

export const PROMPT_LABELS: Record<PromptKey, string> = {
  image_prompt: "Picture prompt",
  last_frame_prompt: "Last frame prompt",
  video_prompt: "Video prompt",
  delivery_instruction: "Delivery instruction",
};

export const PROMPT_HINTS: Record<PromptKey, string> = {
  image_prompt: "Edits the character's reference pictures into this scene.",
  last_frame_prompt: "Edits the first frame into the last frame: the same shot when the action has ended.",
  video_prompt: "What happens over the next seconds: the motion, the camera and the expression.",
  delivery_instruction: "How the character's voice reads the line: tone, emotion and pace.",
};

export const PROMPT_LIMITS: Record<PromptKey, number> = {
  image_prompt: LIMITS.imagePrompt,
  last_frame_prompt: LIMITS.lastFramePrompt,
  video_prompt: LIMITS.videoPrompt,
  delivery_instruction: LIMITS.deliveryInstruction,
};

/** Does this take make its clip with MiniMax H3? */
export function isH3Take(take: CharacterTake): boolean {
  return take.output === "video" && take.video_model === H3_MODEL;
}

function hasDialogueText(take: CharacterTake): boolean {
  return take.dialogue !== null && take.dialogue.trim() !== "";
}

/** The limit of a take's text: a MiniMax H3 video prompt is several sections long. */
export function promptLimit(take: CharacterTake, key: PromptKey): number {
  return key === "video_prompt" && isH3Take(take) ? LIMITS.h3VideoPrompt : PROMPT_LIMITS[key];
}

/** What a take's text is for: MiniMax H3's video prompt has a structure of its own. */
export function promptHint(take: CharacterTake, key: PromptKey): string {
  if (key !== "video_prompt" || !isH3Take(take)) {
    return PROMPT_HINTS[key];
  }
  return hasDialogueText(take)
    ? "MiniMax H3's six sections: the labels (<Picture 1>, <Audio 1>) must match what the clip is sent with, and the words inside <d> are what is spoken."
    : "MiniMax H3's three fields. The line that places the frames on the timeline is added when the clip runs.";
}

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

/**
 * "Present", "About 200 years in the past, Victorian London". Takes the era fields only, so a
 * character and a version's profile both fit.
 */
export function eraText(
  character: Pick<LibraryCharacter, "era_kind" | "era_years" | "era_setting">,
): string {
  const setting = character.era_setting ? `, ${character.era_setting}` : "";
  if (character.era_kind === "present") {
    return `Present${setting}`;
  }
  const direction = character.era_kind === "past" ? "in the past" : "in the future";
  return `About ${character.era_years ?? "?"} years ${direction}${setting}`;
}

/** What a version changed compared with the one before it, in words. */
export const VERSION_CHANGE_LABELS: Record<CharacterVersion["changes"][number], string> = {
  created: "Created",
  profile: "Profile",
  look: "Look",
  voice: "Voice",
};

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

/** A first frame or a speech is made by the take, or picked from what the labs hold. */
export type SourceMode = "make" | "pick";
/** A last frame is also optional: made from the first frame, picked, or left out. */
export type LastFrameMode = "none" | "make" | "pick";

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
  // --- MiniMax H3 only ---
  firstFrameMode: SourceMode;
  firstFrame: ReferenceItem | null;
  lastFrameMode: LastFrameMode;
  lastFrame: ReferenceItem | null;
  audioMode: SourceMode;
  audio: AudioChoice | null;
  audioMarker: AudioMarker;
  /** The clip is as long as the speech. Always on for fully_copy. */
  matchAudio: boolean;
  /** Empty: the pipeline's own number of steps. */
  steps: string;
  /** Also send the character's own pictures as references after the frames. */
  identityRefs: boolean;
};

export const DEFAULT_TAKE_FORM: TakeFormState = {
  output: "image",
  action: "",
  dialogue: "",
  videoModel: H3_MODEL,
  // On by default; it only applies to a video with dialogue and a visible mouth.
  lipSync: true,
  durationS: "5",
  framing: "medium",
  orientation: "portrait",
  seed: "",
  negativePrompt: "",
  firstFrameMode: "make",
  firstFrame: null,
  lastFrameMode: "none",
  lastFrame: null,
  audioMode: "make",
  audio: null,
  audioMarker: "reference",
  matchAudio: true,
  steps: "",
  identityRefs: false,
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
  /** MiniMax H3's own settings: its frames and its steps. */
  h3: boolean;
  /** H3 with dialogue: the speech, how it is used, and the character's own pictures. */
  h3Speech: boolean;
};

/** Is the clip as long as the speech? fully_copy needs it, so that choice cannot be undone. */
export function matchesAudio(form: TakeFormState): boolean {
  return form.audioMarker === "fully_copy" || form.matchAudio;
}

export function visibleFields(form: TakeFormState, character: LibraryCharacter): VisibleFields {
  const talks = hasVoice(character);
  const hasDialogue = form.dialogue.trim() !== "";
  const visual = form.output === "image" || form.output === "video";
  const video = form.output === "video";
  const h3 = video && form.videoModel === H3_MODEL;
  const speaks = video && talks && hasDialogue;
  return {
    audio: talks,
    action: form.output !== "audio",
    // A mute character has no dialogue. A picture does not use it.
    dialogue: talks && form.output !== "image",
    videoModel: video,
    // MiniMax H3 makes the talking itself.
    lipSync: speaks && character.has_visible_mouth && !h3,
    // With LTX and speech the clip follows the speech: only a silent clip has a length. An H3
    // clip with speech has one only when it is not made to match the speech.
    length: video && (!speaks || (h3 && !matchesAudio(form))),
    framing: visual,
    orientation: visual,
    seed: visual,
    // LTX-2.5 ignores a negative prompt, and so does MiniMax H3.
    negativePrompt: video && form.videoModel === "ltx-2.3",
    h3,
    h3Speech: h3 && speaks,
  };
}

/** The lengths a clip can have: the same for every model (the GPU server has the last word). */
export function lengthLimits(): { min: number; max: number } {
  return { min: LIMITS.durationMin, max: LIMITS.durationMax };
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
  if (fields.h3) {
    const h3Issue = h3Problem(form, fields);
    if (h3Issue !== null) {
      return h3Issue;
    }
  }
  if (fields.length) {
    const seconds = Number(form.durationS);
    const { min, max } = lengthLimits();
    if (form.durationS.trim() === "" || !Number.isFinite(seconds) || seconds < min || seconds > max) {
      return `The length must be from ${min} to ${max} seconds.`;
    }
  }
  return null;
}

/** What is wrong with the MiniMax H3 settings, or null. The server checks the rest. */
function h3Problem(form: TakeFormState, fields: VisibleFields): string | null {
  if (form.firstFrameMode === "pick" && form.firstFrame === null) {
    return "Choose the first frame, or let it be made.";
  }
  if (form.lastFrameMode === "pick" && form.lastFrame === null) {
    return "Choose the last frame, or let it be made or left out.";
  }
  if (fields.h3Speech && form.audioMode === "pick") {
    if (form.audio === null) {
      return "Choose the speech, or let it be made.";
    }
    if (!(form.audio.durationS > 0)) {
      return "The speech has no length.";
    }
  }
  if (form.steps.trim() !== "") {
    const steps = wholeNumber(form.steps);
    if (steps === null || steps < H3_STEPS_MIN || steps > H3_STEPS_MAX) {
      return `The steps must be a whole number from ${H3_STEPS_MIN} to ${H3_STEPS_MAX}.`;
    }
  }
  return null;
}

/** "one call to the language model, one picture and one clip", for a list of parts. */
function joinParts(parts: string[]): string {
  if (parts.length <= 1) {
    return parts.join("");
  }
  return `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
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
  if (fields.h3) {
    // Only what the take makes is paid for: a picture or a speech that is picked is free.
    const parts = ["one call to the language model"];
    if (form.firstFrameMode === "make") {
      parts.push("one picture");
    }
    if (form.lastFrameMode === "make") {
      parts.push("one last frame");
    }
    if (fields.h3Speech && form.audioMode === "make") {
      parts.push("one speech");
    }
    parts.push("one MiniMax H3 clip (5 to 10 minutes or more, on the 4 or 8 GPUs the server picks)");
    const text = joinParts(parts);
    return `${text.charAt(0).toUpperCase()}${text.slice(1)}.`;
  }
  if (!speaks) {
    return "One call to the language model, one picture and one clip (5 to 10 minutes).";
  }
  return fields.lipSync && form.lipSync
    ? "One call to the language model, one picture, one speech and one lip-synced clip (5 to 10 minutes, plus several for the lip sync)."
    : "One call to the language model, one picture, one speech and one clip (5 to 10 minutes).";
}

function pickedRef(item: ReferenceItem | null): { source: "lab" | "asset"; id: number } | null {
  return item === null ? null : { source: item.source, id: item.id };
}

/** What "Create" sends. It always runs the whole chain (`run: "all"`). */
export function toTakeIn(form: TakeFormState, character: LibraryCharacter): TakeCreate {
  const fields = visibleFields(form, character);
  const h3 = fields.h3;
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
    first_frame: h3 && form.firstFrameMode === "pick" ? pickedRef(form.firstFrame) : null,
    make_last_frame: h3 && form.lastFrameMode === "make",
    last_frame: h3 && form.lastFrameMode === "pick" ? pickedRef(form.lastFrame) : null,
    audio:
      fields.h3Speech && form.audioMode === "pick" && form.audio !== null
        ? { source: form.audio.source, id: form.audio.id }
        : null,
    audio_marker: form.audioMarker,
    match_audio_duration: matchesAudio(form),
    num_inference_steps: h3 && form.steps.trim() !== "" ? wholeNumber(form.steps) : null,
    identity_refs: fields.h3Speech && form.identityRefs,
  };
}

// --- A new take from an old one --------------------------------------------------------------

/** A picture of a take as the Create panel's picker holds it, or null while it is not there. */
function pictureOf(
  picture: CharacterTake["first_frame_ref"],
  label: string,
): ReferenceItem | null {
  if (picture === null || picture.url === null) {
    return null;
  }
  return { source: picture.source, id: picture.id, url: picture.url, width: null, height: null, label };
}

/**
 * The Create panel filled from a take: its settings, and the pictures and the speech it was made
 * from, picked, so a new take can try another marker, another model or another seed without
 * making them again. A picture or a speech that is not ready yet is left to be made.
 */
export function takeToForm(take: CharacterTake): TakeFormState {
  const firstFrame = pictureOf(take.first_frame_ref, `first frame of take ${take.id}`);
  const lastFrame = pictureOf(take.last_frame_ref, `last frame of take ${take.id}`);
  const audioRef = take.audio_ref;
  const audio: AudioChoice | null =
    audioRef !== null && audioRef.duration_s !== null
      ? {
          source: audioRef.audio.source,
          id: audioRef.audio.id,
          label: `${audioRef.audio.source === "voice" ? "voice" : "speech"} ${audioRef.audio.id}`,
          durationS: audioRef.duration_s,
        }
      : null;
  return {
    ...DEFAULT_TAKE_FORM,
    output: take.output,
    action: take.action ?? "",
    dialogue: take.dialogue ?? "",
    videoModel: take.video_model ?? DEFAULT_TAKE_FORM.videoModel,
    lipSync: take.lip_sync,
    durationS: take.duration_s === null ? DEFAULT_TAKE_FORM.durationS : String(take.duration_s),
    framing: take.framing,
    orientation: take.orientation,
    seed: take.seed === null ? "" : String(take.seed),
    negativePrompt: take.negative_prompt ?? "",
    firstFrameMode: firstFrame === null ? "make" : "pick",
    firstFrame,
    lastFrameMode: lastFrame !== null ? "pick" : take.make_last_frame ? "make" : "none",
    lastFrame,
    audioMode: audio === null ? "make" : "pick",
    audio,
    audioMarker: take.audio_marker ?? DEFAULT_TAKE_FORM.audioMarker,
    matchAudio: take.audio_marker === null ? true : take.match_audio_duration,
    steps: take.num_inference_steps === null ? "" : String(take.num_inference_steps),
    identityRefs: take.identity_refs,
  };
}

// --- A take's steps and prompts ---------------------------------------------------------------

export type StepState = "done" | "running" | "failed" | "todo";

export type StepRow = {
  step: TakeStep;
  state: StepState;
  job: JobSummary | null;
};

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

/** Each step of a take with how far it got. The server says which steps the take has. */
export function takeSteps(take: CharacterTake): StepRow[] {
  return take.steps.map((step) => {
    switch (step) {
      case "prompts":
        return { step, job: take.prompt_job, state: stepState(take.prompt_job, take.prompt_job?.status === "succeeded") };
      case "image":
        return { step, job: take.image?.job ?? null, state: stepState(take.image?.job ?? null, !!take.image?.url) };
      case "last_frame":
        return {
          step,
          job: take.last_frame?.job ?? null,
          state: stepState(take.last_frame?.job ?? null, !!take.last_frame?.url),
        };
      case "voice":
        return { step, job: take.voice?.job ?? null, state: stepState(take.voice?.job ?? null, !!take.voice?.url) };
      case "video":
        return { step, job: take.video?.job ?? null, state: stepState(take.video?.job ?? null, !!take.video?.url) };
    }
  });
}

/** The prompts a take uses, in the order they are shown. The server says which. */
export function promptKeys(take: CharacterTake): PromptKey[] {
  return take.prompt_keys;
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
    const limit = promptLimit(take, key);
    if (text.length > limit) {
      return `The ${name} must be at most ${limit.toLocaleString()} characters.`;
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
    if (take.audio_marker !== null) {
      parts.push(take.audio_marker);
    }
    if (take.make_last_frame || take.last_frame_ref !== null) {
      parts.push("last frame");
    }
  }
  if (take.output !== "audio") {
    parts.push(FRAMING_LABELS[take.framing], ORIENTATION_LABELS[take.orientation]);
  }
  return parts.join(" · ");
}
