import type { LibraryCharacter } from "../../api/characterLab";
import type {
  H3ReferenceRunCreate,
  LabVideoRun,
  LabVideoRunCreate,
} from "../../api/videoLab";
import type { Voice } from "../../api/voiceLab";
import { H3_MODEL, type LabVideoModel } from "../../videoModels";
import type { ReferenceItem } from "../imageLab/labView";

export type LabMode = "quality" | "fast";
export type LabOrientation = "portrait" | "landscape";
/**
 * "generate": one run per chosen model, from the prompt and an optional first and last frame.
 * "h3_reference": one MiniMax H3 clip made from up to 9 pictures (one or two characters, a
 * scene, other pictures) and 0 to 2 voices.
 */
export type LabKind = "generate" | "h3_reference";

export const DURATION_MIN_S = 1;
export const DURATION_MAX_S = 20;
// MiniMax H3 has no length limit here: the GPU server documents 5.17 to 14.4 seconds of video
// and 2 to 15 seconds of audio, but the app sends what was asked and shows the server's answer.
export const H3_STEPS_MIN = 4;
export const H3_STEPS_MAX = 100;
/** `<Picture 1>` to `<Picture 9>`: what the reference endpoint takes. */
export const H3_MAX_REFERENCES = 9;
/** One voice for each of the two characters. */
export const H3_MAX_VOICES = 2;
export const AMBIENCE_MAX_CHARS = 1000;
const SEED_LIMIT = 2 ** 31;

/** What a reference picture is for, as the server records it. */
export type ReferenceRole = NonNullable<H3ReferenceRunCreate["reference_roles"]>[number];
/** Which character a voice belongs to. */
export type VoiceOwner = NonNullable<H3ReferenceRunCreate["audio_owners"]>[number];

/** A voice of a MiniMax H3 reference clip: a Voice lab speech, or a saved voice's recording. */
export type AudioChoice = {
  source: "voice_run" | "voice";
  id: number;
  /** What the picker shows: "voice: Mara" or "speech 12". */
  label: string;
  durationS: number;
};

/** One character of a reference clip: a picture of them, what to call them, and their voice. */
export type CharacterSlot = {
  picture: ReferenceItem | null;
  /** What the prompt calls them: "Mara". */
  name: string;
  /** What they look like and wear, for the prompt's subject_definitions. */
  description: string;
  /** Optional: how they sound. Without one, H3 makes up a voice. */
  voice: AudioChoice | null;
};

/** The place the clip happens in: a picture of it and a few words. */
export type SceneSlot = {
  picture: ReferenceItem | null;
  description: string;
};

export const EMPTY_CHARACTER: CharacterSlot = {
  picture: null,
  name: "",
  description: "",
  voice: null,
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
  /** "h3_reference" only: Character 1 and Character 2 (always two slots, the second optional). */
  characters: CharacterSlot[];
  /** "h3_reference" only: the place. */
  scene: SceneSlot;
  /** "h3_reference" only: the sounds of the place, for overall_soundscape. */
  ambience: string;
  /** "h3_reference" only: any other pictures (an object, a pet), after the ones above. */
  references: ReferenceItem[];
  /**
   * "h3_reference" only: the skeleton the form last put in the prompt. While the prompt is
   * still exactly this, the skeleton may be made again; once edited, it is never replaced.
   */
  skeletonText: string;
  /** "h3_reference" only: the clip is as long as the first voice (needs a voice). */
  matchAudio: boolean;
};

export const DEFAULT_FORM: VideoLabFormState = {
  kind: "generate",
  prompt: "",
  // MiniMax H3 is the app's default video model, so it is the one chosen to begin with. It holds
  // several GPUs and takes longer than LTX: add an LTX model to compare the two.
  models: [H3_MODEL],
  mode: "quality",
  orientation: "portrait",
  durationS: 5,
  seed: "",
  negativePrompt: "",
  firstFrame: null,
  lastFrame: null,
  steps: "",
  characters: [EMPTY_CHARACTER, EMPTY_CHARACTER],
  scene: { picture: null, description: "" },
  ambience: "",
  references: [],
  skeletonText: "",
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

/** The shortest and longest clip the form can ask for (the same for every model). */
export function durationLimits(): { min: number; max: number } {
  return { min: DURATION_MIN_S, max: DURATION_MAX_S };
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

/** The form with some fields of one character slot (0 or 1) changed. */
export function withCharacter(
  state: VideoLabFormState,
  index: number,
  changes: Partial<CharacterSlot>,
): VideoLabFormState {
  return {
    ...state,
    characters: state.characters.map((slot, position) =>
      position === index ? { ...slot, ...changes } : slot,
    ),
  };
}

/** The front picture of a library character's current look, as a form item, or null. */
export function lookPicture(character: LibraryCharacter): ReferenceItem | null {
  const front = character.current_look?.references.find((reference) => reference.angle === "front");
  if (
    front === undefined ||
    !front.ready ||
    front.url === null ||
    front.lab_image_id === null ||
    front.lab_image_id === undefined
  ) {
    return null;
  }
  return {
    source: "lab",
    id: front.lab_image_id,
    url: front.url,
    width: null,
    height: null,
    label: `${character.name}'s look`,
  };
}

/** Text without the full stops and spaces at its end, so it can be joined with commas. */
function withoutTrailingStops(text: string): string {
  return text.replace(/[.\s]+$/, "");
}

/**
 * A character slot filled from the library: the look's front picture, the name, a description
 * from the character's appearance and outfit, and the saved voice when there is one (found in
 * `voices`, which have the lengths). Null while the character has no ready look.
 */
export function slotFromCharacter(character: LibraryCharacter, voices: Voice[]): CharacterSlot | null {
  const picture = lookPicture(character);
  if (picture === null) {
    return null;
  }
  const outfit = character.outfit?.trim() ?? "";
  const description = [
    withoutTrailingStops(character.appearance),
    outfit === "" ? "" : `wearing ${withoutTrailingStops(outfit)}`,
  ]
    .filter((part) => part !== "")
    .join(", ");
  const saved = voices.find((voice) => voice.id === character.voice?.id);
  return {
    picture,
    name: character.name,
    description,
    voice:
      saved === undefined
        ? null
        : {
            source: "voice",
            id: saved.id,
            label: `voice: ${saved.name}`,
            durationS: saved.duration_s,
          },
  };
}

/** A reference picture with what it is for. */
export type RolePicture = { item: ReferenceItem; role: ReferenceRole };
/** A voice with the character it belongs to. */
export type OwnedVoice = { audio: AudioChoice; owner: VoiceOwner };

type CastState = Pick<VideoLabFormState, "characters" | "scene" | "references">;

const CHARACTER_ROLES: VoiceOwner[] = ["character_1", "character_2"];

/**
 * The pictures in the order they are sent: Character 1, Character 2, the scene, then the others.
 * The position here is the picture's number in the prompt (`<Picture 1>` is the first).
 */
export function referencePictures(state: CastState): RolePicture[] {
  const pictures: RolePicture[] = [];
  state.characters.forEach((slot, index) => {
    if (slot.picture !== null) {
      pictures.push({ item: slot.picture, role: CHARACTER_ROLES[index] });
    }
  });
  if (state.scene.picture !== null) {
    pictures.push({ item: state.scene.picture, role: "scene" });
  }
  for (const item of state.references) {
    pictures.push({ item, role: "other" });
  }
  return pictures;
}

/** The voices in the order they are sent (`<Audio 1>` is the first): Character 1's, then 2's. */
export function referenceVoices(state: Pick<VideoLabFormState, "characters">): OwnedVoice[] {
  const voices: OwnedVoice[] = [];
  state.characters.forEach((slot, index) => {
    if (slot.voice !== null) {
      voices.push({ audio: slot.voice, owner: CHARACTER_ROLES[index] });
    }
  });
  return voices;
}

/**
 * Whether the clip is as long as the first voice: the box is ticked and there is a voice to
 * measure. Without a voice the length is the one chosen.
 */
export function matchesAudio(state: VideoLabFormState): boolean {
  return state.matchAudio && referenceVoices(state).length > 0;
}

/** Why a MiniMax H3 reference clip cannot be run, or null when it can. */
function referenceProblem(state: VideoLabFormState): string | null {
  const pictureCount = referencePictures(state).length;
  if (pictureCount === 0) {
    return "Choose at least one picture: a character, the scene or another picture.";
  }
  if (pictureCount > H3_MAX_REFERENCES) {
    return `At most ${H3_MAX_REFERENCES} pictures in all.`;
  }
  const voiceless = state.characters.findIndex((slot) => slot.voice !== null && slot.picture === null);
  if (voiceless !== -1) {
    return `Character ${voiceless + 1} has a voice but no picture. Choose a picture or remove the voice.`;
  }
  if (referenceVoices(state).some((voice) => !(voice.audio.durationS > 0))) {
    return "A voice has no length.";
  }
  if (state.ambience.length > AMBIENCE_MAX_CHARS) {
    return `The ambience is at most ${AMBIENCE_MAX_CHARS} characters.`;
  }
  if (!matchesAudio(state)) {
    const duration = durationOf(state);
    if (duration === null || duration < DURATION_MIN_S || duration > DURATION_MAX_S) {
      return `The length must be from ${DURATION_MIN_S} to ${DURATION_MAX_S} seconds.`;
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
  const pictures = referencePictures(state);
  const voices = referenceVoices(state);
  const ambience = state.ambience.trim();
  return {
    prompt: state.prompt,
    orientation: state.orientation,
    seed: state.seed.trim() === "" ? null : wholeNumber(state.seed),
    references: pictures.map(({ item }) => ({ source: item.source, id: item.id })),
    reference_roles: pictures.map(({ role }) => role),
    audios: voices.map(({ audio }) => ({ source: audio.source, id: audio.id })),
    audio_owners: voices.map(({ owner }) => owner),
    ambience: ambience === "" ? null : ambience,
    match_audio_duration: matchesAudio(state),
    duration_s: matchesAudio(state) ? null : durationOf(state),
    num_inference_steps: stepsOf(state),
  };
}

// The GPU server decides how many GPUs and how long: the number is shown on the run once the
// server has answered, so this line says only what is certain beforehand.
const H3_COST_TEXT =
  "MiniMax H3 is a GPU job that holds 4 or 8 GPUs (the server says which once it accepts the run) and can take more than 10 minutes.";

/**
 * What a click costs, for the line under the button: "5 to 10 minutes on one GPU" for an LTX
 * run, doubled for two, and MiniMax H3's GPUs (the server's choice) and longer wait said on
 * their own.
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

/** A picture's place in the prompt: `<Subject n>` and `<Picture n>` share the number. */
type NumberedPicture = { role: ReferenceRole; number: number };

/** "Mara, a tall woman in a red coat", or the blank for whoever it is. */
function whoText(name: string, description: string): string {
  const parts = [name.trim(), description.trim()].filter((part) => part !== "");
  return parts.length === 0 ? "[who they are, and what they look like and wear]" : parts.join(", ");
}

/** The label the guide gives a speaker: Character 1 is S1, Character 2 is S2. */
function speakerOf(role: ReferenceRole): string {
  return role === "character_2" ? "S2" : "S1";
}

/**
 * The six-part prompt of a MiniMax H3 reference clip, filled from the cast: the characters'
 * names and descriptions, the scene, the ambience and the voices. The parts and their order are
 * the server's guide's; the words in brackets are for the author to replace.
 *
 * `<Picture n>` and `<Subject n>` are numbered alike, in the order the pictures are sent
 * (Character 1, Character 2, the scene, the others). `<Audio n>` is a voice, in the order the
 * voices are sent. With pictures alone, each character, place or thing is a subject and no
 * `<Audio n>` line is written.
 */
export function referenceSkeleton(
  state: Pick<VideoLabFormState, "characters" | "scene" | "ambience" | "references">,
): string {
  const numbered: NumberedPicture[] = referencePictures(state).map(({ role }, index) => ({
    role,
    number: index + 1,
  }));
  // A form with no picture yet still gets one line to fill in.
  const pictures: NumberedPicture[] = numbered.length > 0 ? numbered : [{ role: "other", number: 1 }];
  const characters = pictures.filter(
    (picture) => picture.role === "character_1" || picture.role === "character_2",
  );
  const scene = pictures.find((picture) => picture.role === "scene");
  // The people the story is about; with no character, the first picture stands in.
  const actors = characters.length > 0 ? characters : pictures.slice(0, 1);
  // Each voice with the picture of the character it belongs to.
  const voiced = referenceVoices(state).flatMap((voice, index) => {
    const owner = pictures.find((picture) => picture.role === voice.owner);
    return owner === undefined ? [] : [{ audioNumber: index + 1, owner }];
  });

  function subjectLine({ role, number }: NumberedPicture): string {
    const link = `shown in <Picture ${number}>.`;
    if (role === "character_1" || role === "character_2") {
      const slot = state.characters[role === "character_1" ? 0 : 1];
      return `<Subject ${number}> is ${whoText(slot.name, slot.description)}, ${link}`;
    }
    if (role === "scene") {
      const place = state.scene.description.trim() || "[what the place looks like]";
      return `<Subject ${number}> is the place where it happens: ${place}, ${link}`;
    }
    return `<Subject ${number}> is [who or what], ${link}`;
  }
  function retentionLine({ role, number }: NumberedPicture): string {
    const kept =
      role === "scene"
        ? "partially_preserved - the place, its layout, light and mood"
        : "fully_preserved - [what must stay the same]";
    return `<Subject ${number}> (appears in [Shot 1]): ${kept}.`;
  }

  const summaryTag = voiced.length > 0 ? "[reference generation + audio reference]" : "[reference generation]";
  const names = actors.map((actor) => `<Subject ${actor.number}>`).join(" and ");
  const setting = scene === undefined ? "" : `, in <Subject ${scene.number}>`;
  const look =
    scene === undefined
      ? "[live-action, the light and the look]"
      : `[live-action, the light and the look], set in <Subject ${scene.number}>`;
  const actions = actors.map((actor) => `<Subject ${actor.number}> (${speakerOf(actor.role)}) [does something].`);
  const speech = voiced.map(
    ({ audioNumber, owner }) =>
      `<Subject ${owner.number}> (${speakerOf(owner.role)}) says, using the voice timbre referenced from <Audio ${audioNumber}>, <d>[English] [the words].</d>`,
  );

  return [
    "subject_definitions:",
    ...pictures.map(subjectLine),
    ...voiced.map(
      ({ audioNumber, owner }) =>
        `<Audio ${audioNumber}> is the voice-timbre reference for <Subject ${owner.number}> (${speakerOf(owner.role)}).`,
    ),
    "",
    "summary:",
    `${summaryTag} ${names} [what happens]${setting}.`,
    "",
    "retention_analysis:",
    ...pictures.map(retentionLine),
    ...voiced.map(
      ({ audioNumber, owner }) =>
        `<Audio ${audioNumber}>: reference - the voice timbre guides <Subject ${owner.number}>'s delivery without copying the recording.`,
    ),
    "",
    "detailed_description:",
    `The target video is ${look}.`,
    `[Shot 1] [Shot size and angle], ${actions.join(" ")} [Camera move.] ${speech.join(" ")}`.trimEnd(),
    "",
    "overall_soundscape:",
    state.ambience.trim() || "[1 to 4 sentences: ambience and physical sounds, no dialogue.]",
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
  // MiniMax H3 only: the GPUs the server said it used.
  if (run.gpus !== null) {
    parts.push(`${run.gpus} GPUs`);
  }
  if (run.url !== null) {
    parts.push(run.audio_codec !== null ? `sound: ${run.audio_codec}` : "no sound");
  }
  return parts.join(" · ");
}

/** The length of each audio a run sent: a reference clip's list, or a lip-sync take's one. */
function audioSecondsOf(run: LabVideoRun): number[] {
  const list = listParam(run, "audio_durations_s");
  if (list !== null) {
    return list.filter((value): value is number => typeof value === "number");
  }
  const single = numberParam(run, "audio_duration_s");
  return single === null ? [] : [single];
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
    parts.push(
      run.params.match_audio_duration === true
        ? `${duration.toFixed(2)} s (the audio's)`
        : `${duration.toFixed(2)} s requested`,
    );
  }
  const audioSeconds = audioSecondsOf(run);
  if (audioSeconds.length > 0) {
    parts.push(`audio ${audioSeconds.map((seconds) => `${seconds.toFixed(2)} s`).join(" + ")}`);
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

/** "3 pictures, 2 voices" or "1 picture, no voice": what a reference run was made from. */
export function referenceSummary(run: LabVideoRun): string {
  const pictures = run.references.length;
  const voices = run.audio_references.length;
  const pictureText = `${pictures} ${pictures === 1 ? "picture" : "pictures"}`;
  const voiceText = voices === 0 ? "no voice" : `${voices} ${voices === 1 ? "voice" : "voices"}`;
  return `${pictureText}, ${voiceText}`;
}

/** Whether a run is a MiniMax H3 reference clip: pictures and optional voices, no frames. */
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
  return {
    ...base,
    kind: "h3_reference",
    models: [H3_MODEL],
    ...castFromRun(first),
    ambience: textParam(first, "ambience") ?? "",
    matchAudio: first.params.match_audio_duration === true,
  };
}

/** The list a run's params hold under `key`, or null when it has none. */
function listParam(run: LabVideoRun, key: string): unknown[] | null {
  const value = run.params[key];
  return Array.isArray(value) ? value : null;
}

/**
 * The characters, scene and other pictures of a reference run, put back where they were. A run
 * made before the roles were recorded has none: its first picture is Character 1, its first
 * voice is that character's, and the rest are other pictures.
 */
function castFromRun(
  run: LabVideoRun,
): Pick<VideoLabFormState, "characters" | "scene" | "references"> {
  const roles = listParam(run, "reference_roles");
  const owners = listParam(run, "audio_owners");
  const durations = listParam(run, "audio_durations_s") ?? [numberParam(run, "audio_duration_s")];

  const characters = [EMPTY_CHARACTER, EMPTY_CHARACTER];
  let scene: SceneSlot = DEFAULT_FORM.scene;
  const references: ReferenceItem[] = [];
  run.references.forEach((picture, index) => {
    const item = referenceOf(picture);
    if (item === null) {
      return;
    }
    const role = roles === null ? (index === 0 ? "character_1" : "other") : roles[index];
    if (role === "character_1" || role === "character_2") {
      const slot = role === "character_1" ? 0 : 1;
      characters[slot] = { ...characters[slot], picture: item };
    } else if (role === "scene") {
      scene = { ...scene, picture: item };
    } else {
      references.push(item);
    }
  });

  run.audio_references.forEach((audio, index) => {
    const seconds = durations[index];
    if (typeof seconds !== "number") {
      return;
    }
    const owner = owners === null ? CHARACTER_ROLES[index] : owners[index];
    if (owner !== "character_1" && owner !== "character_2") {
      return;
    }
    const slot = owner === "character_1" ? 0 : 1;
    characters[slot] = {
      ...characters[slot],
      voice: {
        source: audio.source,
        id: audio.id,
        label: audio.source === "voice" ? `voice ${audio.id}` : `speech ${audio.id}`,
        durationS: seconds,
      },
    };
  });
  return { characters, scene, references };
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
