import type {
  LabMusicRun,
  LabMusicRunCreate,
  MusicBrief,
  MusicCatalog,
  MusicFieldSpec,
  MusicKind,
  MusicModel,
  MusicModelInfo,
} from "../../api/musicLab";

export const MAX_VARIANTS = 4;
const SEED_MAX = 2147483647;

/** What a field holds in the form: text for text and numbers, true or false for a flag. */
export type FieldValue = string | boolean;
export type ModelValues = Record<string, FieldValue>;

/** The brief as the form holds it: every box is text, and an empty box means "not given". */
export type MusicBriefState = {
  description: string;
  /** Comma-separated. */
  genre: string;
  /** Comma-separated. */
  tone: string;
  era: string;
  moodStart: string;
  moodMiddle: string;
  moodEnd: string;
  dramaticGoal: string;
  place: string;
  durationS: string;
  underNarration: boolean;
  soundEvent: string;
  lyrics: string;
  lyricsTheme: string;
  language: string;
  voiceNote: string;
};

export type MusicLabFormState = {
  kind: MusicKind;
  brief: MusicBriefState;
  /** The models to run, or null for every model of the kind (the choice until one is changed). */
  selected: MusicModel[] | null;
  /** What each model will be sent, as the person last edited it or the language model wrote it. */
  values: Partial<Record<MusicModel, ModelValues>>;
  /** The prompt-writing job started for each model, to follow its progress. */
  promptJobIds: Partial<Record<MusicModel, number>>;
  /** The prompt-writing job whose fields are in `values`, kept on the run for the record. */
  usedPromptJobIds: Partial<Record<MusicModel, number>>;
  variants: string;
  /** Empty: random seeds. */
  seed: string;
};

export const EMPTY_BRIEF: MusicBriefState = {
  description: "",
  genre: "",
  tone: "",
  era: "",
  moodStart: "",
  moodMiddle: "",
  moodEnd: "",
  dramaticGoal: "",
  place: "",
  durationS: "",
  underNarration: false,
  soundEvent: "",
  lyrics: "",
  lyricsTheme: "",
  language: "",
  voiceNote: "",
};

export const DEFAULT_FORM: MusicLabFormState = {
  kind: "score",
  brief: EMPTY_BRIEF,
  selected: null,
  values: {},
  promptJobIds: {},
  usedPromptJobIds: {},
  variants: "1",
  seed: "",
};

/** What each kind of sound is for in the story pipeline, so a person knows what to try. */
export const KIND_HELP: Record<MusicKind, string> = {
  score: "Music under a scene: it follows the mood of the scene and stays behind the voices.",
  song: "A song with sung words, such as a title song or a song a character sings.",
  stem: "A short loop or a single instrument layer that can be mixed under other sounds.",
  sfx: "One sound event: a door, a footstep, a crash.",
  ambience: "A bed of room tone or weather that plays under a whole scene.",
};

/** The brief's boxes: which kinds use them, and the pipeline stage that will fill them. */
export type BriefBox = {
  key: keyof MusicBriefState;
  label: string;
  /** The pipeline stage whose output this box stands in for. */
  source: string;
  kinds: MusicKind[];
  multiline?: boolean;
};

const ALL_KINDS: MusicKind[] = ["score", "song", "stem", "sfx", "ambience"];

export const BRIEF_BOXES: BriefBox[] = [
  { key: "genre", label: "Genre", source: "story bible", kinds: ["score", "song", "stem"] },
  { key: "tone", label: "Tone", source: "story bible", kinds: ALL_KINDS },
  { key: "era", label: "Era", source: "story bible", kinds: ALL_KINDS },
  { key: "place", label: "Place", source: "scene setting", kinds: ["score", "sfx", "ambience"] },
  { key: "moodStart", label: "Mood at the start", source: "scene beats", kinds: ["score", "song", "stem"] },
  { key: "moodMiddle", label: "Mood in the middle", source: "scene beats", kinds: ["score", "song", "stem"] },
  { key: "moodEnd", label: "Mood at the end", source: "scene beats", kinds: ["score", "song", "stem"] },
  { key: "dramaticGoal", label: "Dramatic goal", source: "scene definition", kinds: ["score", "song"] },
  { key: "soundEvent", label: "The sound event", source: "shot plan", kinds: ["sfx"] },
  { key: "lyricsTheme", label: "What the song is about", source: "story bible", kinds: ["song"] },
  {
    key: "lyrics",
    label: "Lyrics (if you already have them)",
    source: "scene definition",
    kinds: ["song"],
    multiline: true,
  },
  { key: "language", label: "Language of the singing", source: "story bible", kinds: ["song"] },
  { key: "voiceNote", label: "Voice of the singer", source: "character definition", kinds: ["song"] },
];

export function boxesFor(kind: MusicKind): BriefBox[] {
  return BRIEF_BOXES.filter((box) => box.kinds.includes(kind));
}

/** The kinds for which "keep it behind the voices" applies. */
export function takesUnderNarration(kind: MusicKind): boolean {
  return kind === "score" || kind === "stem" || kind === "ambience";
}

/** Hints under a field, per model, so a person writes the field the way the model reads it. */
const FIELD_HINTS: Record<string, string> = {
  "ace-step-1.5.caption":
    "Genre, instruments, mood and texture. Do not put the tempo or the key here: they have their own fields.",
  "ace-step-1.5.lyrics": "Sections in brackets: [Verse], [Chorus]. For no singing, tick Instrumental.",
  "ace-step-1.5.bpm": "Empty: the model chooses. With the key and the duration set, it skips its own planning.",
  "ace-step-1.5.keyscale": "For example A minor.",
  "yue2.style": "Genre, mood, instruments and the singer's voice, as comma-separated tags.",
  "yue2.lyrics": "Sections in brackets: [verse], [chorus]. Sung in the language of the lyrics.",
  "stable-audio-3.prompt": "What the sound is, how it sounds and the mood, in plain words.",
  "stable-audio-open.prompt": "What the sound is, how it sounds and the mood, in plain words.",
  "stable-audio-open.negative_prompt": "What the audio must not have, such as low quality or distortion.",
  "ltx-audio.prompt": "Describe the sound as you would describe it to a sound designer.",
  "ltx-audio.negative_prompt": "What the audio must not have.",
};

export function hintFor(model: MusicModel, spec: MusicFieldSpec): string {
  return FIELD_HINTS[`${model}.${spec.name}`] ?? "";
}

/** Whether a text field is a short single line (a key, a language code) or a long text. */
export function isShortText(spec: MusicFieldSpec): boolean {
  return spec.choices !== null || (spec.max_chars !== null && spec.max_chars <= 40) || spec.max_chars === null;
}

/** The text of a field's range, such as "from 30 to 300". */
export function rangeText(spec: MusicFieldSpec): string {
  if (spec.minimum !== null && spec.maximum !== null) {
    return `from ${spec.minimum} to ${spec.maximum}`;
  }
  return "";
}

/** The models the form will run, in the order of the catalog: only models that suit the kind. */
export function selectedModels(state: MusicLabFormState, catalog: MusicCatalog): MusicModelInfo[] {
  const suitable = catalog.kinds.find((entry) => entry.id === state.kind)?.models ?? [];
  return catalog.models.filter(
    (info) => suitable.includes(info.id) && (state.selected === null || state.selected.includes(info.id)),
  );
}

/** The values a model starts with: every field empty, flags off. */
export function emptyValues(info: MusicModelInfo): ModelValues {
  const values: ModelValues = {};
  for (const spec of info.fields) {
    values[spec.name] = spec.type === "flag" ? false : "";
  }
  return values;
}

/** The values of a model in the form, or empty ones when it has none yet. */
export function valuesOf(state: MusicLabFormState, info: MusicModelInfo): ModelValues {
  return { ...emptyValues(info), ...state.values[info.id] };
}

function textOf(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  return "";
}

/** Fields that came from the server (written by the language model, or a past run) as form values. */
export function valuesFromFields(info: MusicModelInfo, fields: Record<string, unknown>): ModelValues {
  const values = emptyValues(info);
  for (const spec of info.fields) {
    const value = fields[spec.name];
    values[spec.name] = spec.type === "flag" ? value === true : textOf(value);
  }
  return values;
}

/** Whole numbers only (a seed or the number of variants). */
function wholeNumber(text: string): number | null {
  const trimmed = text.trim();
  return /^\d{1,10}$/.test(trimmed) ? Number(trimmed) : null;
}

/** A decimal number, or null for an empty box and NaN for text that is not a number. */
function decimalOf(text: string): number | null {
  const trimmed = text.trim();
  if (trimmed === "") {
    return null;
  }
  return /^\d+(\.\d+)?$/.test(trimmed) ? Number(trimmed) : Number.NaN;
}

function listOf(text: string): string[] | null {
  const items = text
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item !== "");
  return items.length === 0 ? null : items;
}

function textOrNull(text: string): string | null {
  const trimmed = text.trim();
  return trimmed === "" ? null : trimmed;
}

/** The brief as the request the server takes. */
export function briefRequest(kind: MusicKind, brief: MusicBriefState): MusicBrief {
  const used = new Set<string>(boxesFor(kind).map((box) => box.key));
  const text = (key: keyof MusicBriefState): string | null =>
    used.has(key) ? textOrNull(brief[key] as string) : null;
  const duration = decimalOf(brief.durationS);
  return {
    description: brief.description.trim(),
    genre: used.has("genre") ? listOf(brief.genre) : null,
    tone: used.has("tone") ? listOf(brief.tone) : null,
    era: text("era"),
    mood_start: text("moodStart"),
    mood_middle: text("moodMiddle"),
    mood_end: text("moodEnd"),
    dramatic_goal: text("dramaticGoal"),
    place: text("place"),
    duration_s: duration !== null && Number.isFinite(duration) ? duration : null,
    under_narration: takesUnderNarration(kind) ? brief.underNarration : null,
    sound_event: text("soundEvent"),
    lyrics: text("lyrics"),
    lyrics_theme: text("lyricsTheme"),
    language: text("language"),
    voice_note: text("voiceNote"),
  };
}

/** One model's values as the fields the server takes: trimmed text, numbers, flags. */
export function fieldsRequest(info: MusicModelInfo, values: ModelValues): Record<string, unknown> {
  const fields: Record<string, unknown> = {};
  for (const spec of info.fields) {
    const value = values[spec.name];
    if (spec.type === "flag") {
      fields[spec.name] = value === true;
    } else if (spec.type === "text") {
      fields[spec.name] = typeof value === "string" ? value.trim() : "";
    } else {
      fields[spec.name] = typeof value === "string" ? decimalOf(value) : null;
    }
  }
  return fields;
}

/** What is wrong with one model's fields, or null. The server checks everything again. */
function fieldsProblem(info: MusicModelInfo, values: ModelValues): string | null {
  for (const spec of info.fields) {
    const value = values[spec.name];
    if (spec.type === "text" && spec.required && (typeof value !== "string" || value.trim() === "")) {
      return `${info.label}: ${spec.label} is empty. Write it, or write the prompts with the language model.`;
    }
    if (spec.type === "int" || spec.type === "number") {
      const number = typeof value === "string" ? decimalOf(value) : null;
      if (number !== null && Number.isNaN(number)) {
        return `${info.label}: ${spec.label} must be a number.`;
      }
    }
  }
  return null;
}

/** Why the form cannot be run, or null when it can. */
export function formProblem(state: MusicLabFormState, catalog: MusicCatalog): string | null {
  if (state.brief.description.trim() === "") {
    return "Describe what you want first.";
  }
  const chosen = selectedModels(state, catalog);
  if (chosen.length === 0) {
    return "Choose at least one model.";
  }
  if (decimalOf(state.brief.durationS) !== null && Number.isNaN(decimalOf(state.brief.durationS))) {
    return "The duration must be a number of seconds.";
  }
  for (const info of chosen) {
    const problem = fieldsProblem(info, valuesOf(state, info));
    if (problem !== null) {
      return problem;
    }
  }
  const variants = wholeNumber(state.variants);
  if (variants === null || variants < 1 || variants > MAX_VARIANTS) {
    return `The number of variants must be from 1 to ${MAX_VARIANTS}.`;
  }
  if (state.seed.trim() !== "") {
    const seed = wholeNumber(state.seed);
    if (seed === null || seed > SEED_MAX) {
      return `The seed must be a whole number from 0 to ${SEED_MAX}.`;
    }
  }
  return null;
}

/** The form as the request the server takes. */
export function toRequest(state: MusicLabFormState, catalog: MusicCatalog): LabMusicRunCreate {
  const models = selectedModels(state, catalog).map((info) => ({
    model: info.id,
    fields: fieldsRequest(info, valuesOf(state, info)),
    prompt_job_id: state.usedPromptJobIds[info.id] ?? null,
  }));
  return {
    kind: state.kind,
    brief: briefRequest(state.kind, state.brief),
    models,
    variants: wholeNumber(state.variants) ?? 1,
    seed: state.seed.trim() === "" ? null : wholeNumber(state.seed),
  };
}

function briefStateFromRun(brief: Record<string, unknown>): MusicBriefState {
  const list = (value: unknown): string => (Array.isArray(value) ? value.map(textOf).join(", ") : "");
  return {
    description: textOf(brief.description),
    genre: list(brief.genre),
    tone: list(brief.tone),
    era: textOf(brief.era),
    moodStart: textOf(brief.mood_start),
    moodMiddle: textOf(brief.mood_middle),
    moodEnd: textOf(brief.mood_end),
    dramaticGoal: textOf(brief.dramatic_goal),
    place: textOf(brief.place),
    durationS: textOf(brief.duration_s),
    underNarration: brief.under_narration === true,
    soundEvent: textOf(brief.sound_event),
    lyrics: textOf(brief.lyrics),
    lyricsTheme: textOf(brief.lyrics_theme),
    language: textOf(brief.language),
    voiceNote: textOf(brief.voice_note),
  };
}

/** The seed a run was made with, or null. */
export function seedOf(run: LabMusicRun): number | null {
  const seed = run.params.seed;
  return typeof seed === "number" ? seed : null;
}

/**
 * The form that would make this run again, with the seed kept so the same inputs give the same
 * sound. It runs the one model of the run; the fields are the ones that were sent.
 */
export function stateFromRun(run: LabMusicRun, catalog: MusicCatalog): MusicLabFormState {
  const info = catalog.models.find((entry) => entry.id === run.model);
  const seed = seedOf(run);
  return {
    kind: run.kind,
    brief: briefStateFromRun(run.brief),
    selected: [run.model],
    values: info === undefined ? {} : { [run.model]: valuesFromFields(info, run.fields) },
    promptJobIds: {},
    usedPromptJobIds: run.prompt_job_id === null ? {} : { [run.model]: run.prompt_job_id },
    variants: "1",
    seed: seed === null ? "" : String(seed),
  };
}

/** The settings a run was made with, as a short line: "seed 12 · 30.0 s · 44100 Hz stereo". */
export function paramsLine(run: LabMusicRun): string {
  const parts: string[] = [];
  const seed = seedOf(run);
  if (seed !== null) {
    parts.push(`seed ${seed}`);
  }
  if (run.duration_s !== null) {
    parts.push(`${run.duration_s.toFixed(1)} s`);
  }
  if (run.sample_rate !== null) {
    const channels = run.channels === 1 ? "mono" : run.channels === 2 ? "stereo" : null;
    parts.push(channels === null ? `${run.sample_rate} Hz` : `${run.sample_rate} Hz ${channels}`);
  }
  return parts.join(" · ");
}

/** The colour of a licence badge for each level of warning. */
export const LICENSE_COLORS: Record<MusicModelInfo["license_level"], string> = {
  open: "green",
  community: "yellow",
  non_commercial: "red",
  unknown: "gray",
};

export const LICENSE_LABELS: Record<MusicModelInfo["license_level"], string> = {
  open: "Open licence",
  community: "Community licence",
  non_commercial: "Non-commercial only",
  unknown: "Licence unverified",
};

/** A run's values as lines of "Label: value" for the "what was sent" box. */
export function sentLines(run: LabMusicRun, catalog: MusicCatalog | undefined): string[] {
  const info = catalog?.models.find((entry) => entry.id === run.model);
  const specs: MusicFieldSpec[] = info?.fields ?? [];
  const labelOf = (name: string) => specs.find((spec) => spec.name === name)?.label ?? name;
  return Object.entries(run.fields)
    .filter(([, value]) => value !== null && value !== "")
    .map(([name, value]) => `${labelOf(name)}: ${typeof value === "string" ? value : JSON.stringify(value)}`);
}

export type RunGroup = { key: string; runs: LabMusicRun[] };

/** The runs of one click together (newest group first), each group in model order, then seed. */
export function groupRuns(runs: LabMusicRun[], catalog: MusicCatalog | undefined): RunGroup[] {
  const order = new Map<string, number>(catalog?.models.map((info, index) => [info.id, index]) ?? []);
  const groups: RunGroup[] = [];
  for (const run of runs) {
    const last = groups[groups.length - 1];
    if (last !== undefined && last.key === run.group_key) {
      last.runs.push(run);
    } else {
      groups.push({ key: run.group_key, runs: [run] });
    }
  }
  for (const group of groups) {
    group.runs.sort(
      (a, b) =>
        (order.get(a.model) ?? 0) - (order.get(b.model) ?? 0) || (seedOf(a) ?? 0) - (seedOf(b) ?? 0),
    );
  }
  return groups;
}
