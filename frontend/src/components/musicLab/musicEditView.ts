import type {
  AudioMeasurement,
  MusicCatalog,
  MusicEditCreate,
  MusicEditModel,
  MusicEditOperation,
  MusicKind,
  MusicSource,
  RunSource,
} from "../../api/musicLab";
import {
  decimalOf,
  emptyValues,
  fieldsRequest,
  MAX_VARIANTS,
  SEED_MAX,
  wholeNumber,
  type ModelValues,
} from "./musicLabView";

/** Where the sound to edit comes from: an earlier run (by its number), or a saved recording or join. */
export type SourceMode = "run" | "saved";

/** The edit form as it is held: every box is text, and an empty box means "not given". */
export type MusicEditFormState = {
  sourceMode: SourceMode;
  /** The number of the run to edit, as typed. */
  runNumber: string;
  /** The saved recording or join to edit, as the id of the source, or null. */
  sourceId: number | null;
  operation: MusicEditOperation["id"];
  /** The model of a transform (the other operations have one). Null: the first that does it. */
  model: MusicEditModel["model"] | null;
  kind: MusicKind;
  /** What you want from the edit. It is kept on the runs it makes. */
  description: string;
  /** The fields of the operation, by name. A name the chosen model does not have is not sent. */
  values: ModelValues;
  variants: string;
  /** Empty: random seeds. */
  seed: string;
};

export const DEFAULT_EDIT_FORM: MusicEditFormState = {
  sourceMode: "run",
  runNumber: "",
  sourceId: null,
  operation: "repaint",
  model: null,
  kind: "score",
  description: "",
  values: {},
  variants: "1",
  seed: "",
};

/** One operation of the catalog, or null. */
export function operationOf(catalog: MusicCatalog, id: MusicEditOperation["id"]): MusicEditOperation | null {
  return catalog.operations.find((entry) => entry.id === id) ?? null;
}

/** The model the form will use: the chosen one if this operation has it, else the first. */
export function editModelOf(catalog: MusicCatalog, state: MusicEditFormState): MusicEditModel | null {
  const models = operationOf(catalog, state.operation)?.models ?? [];
  return models.find((entry) => entry.model === state.model) ?? models[0] ?? null;
}

/** The number typed for a run, or null when it is empty or not a whole number. */
export function runNumberOf(state: MusicEditFormState): number | null {
  return wholeNumber(state.runNumber);
}

/** What the form knows about its source: its length and its seam, when they can be known. */
export type SourceInfo = {
  label: string;
  url: string | null;
  durationS: number | null;
  /** Where two joined runs meet, or null. */
  seamS: number | null;
};

/** The seconds as a short text, such as "12.5 s". */
export function secondsText(seconds: number): string {
  return `${seconds.toFixed(1)} s`;
}

/** Why the form cannot be run, or null when it can. The server checks everything again. */
export function editProblem(
  state: MusicEditFormState,
  catalog: MusicCatalog,
  source: SourceInfo | null,
): string | null {
  const model = editModelOf(catalog, state);
  if (model === null) {
    return "Choose what to do with the sound.";
  }
  if (state.sourceMode === "run" && runNumberOf(state) === null) {
    return "Type the number of the run to edit.";
  }
  if (state.sourceMode === "saved" && state.sourceId === null) {
    return "Choose a recording or a join to edit, or upload one.";
  }
  if (state.description.trim() === "") {
    return "Describe what you want first.";
  }
  if (source !== null && source.durationS !== null && source.durationS > model.max_source_s) {
    return `${model.label} edits at most ${model.max_source_s} s of sound, and this source is ${secondsText(source.durationS)}.`;
  }
  const values = { ...emptyValues(model), ...state.values };
  for (const spec of model.fields) {
    const value = values[spec.name];
    if (spec.type === "text" && spec.required && (typeof value !== "string" || value.trim() === "")) {
      return `${model.label}: ${spec.label} is empty.`;
    }
    if (spec.type === "int" || spec.type === "number") {
      const number = typeof value === "string" ? decimalOf(value) : null;
      if (number !== null && Number.isNaN(number)) {
        return `${model.label}: ${spec.label} must be a number.`;
      }
      if (number === null && spec.required) {
        return `${model.label}: ${spec.label} is empty.`;
      }
    }
  }
  // Only the window fields of this model count: others may still hold what was typed before.
  const windowValue = (names: string[]): number | null => {
    const name = names.find((candidate) => model.fields.some((spec) => spec.name === candidate));
    const value = name === undefined ? "" : values[name];
    return typeof value === "string" ? decimalOf(value) : null;
  };
  const start = windowValue(["repaint_start", "mask_start"]);
  const end = windowValue(["repaint_end", "mask_end"]);
  if (start !== null && end !== null && end <= start) {
    return "The window must end after it starts.";
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

/** The form as the request the server takes. Call it only when `editProblem` is null. */
export function toEditRequest(state: MusicEditFormState, catalog: MusicCatalog): MusicEditCreate {
  const model = editModelOf(catalog, state);
  if (model === null) {
    throw new Error("The operation has no model.");
  }
  const values = { ...emptyValues(model), ...state.values };
  return {
    operation: state.operation,
    model: model.model,
    kind: state.kind,
    description: state.description.trim(),
    source_run_id: state.sourceMode === "run" ? runNumberOf(state) : null,
    source_id: state.sourceMode === "saved" ? state.sourceId : null,
    fields: fieldsRequest(model, values),
    variants: wholeNumber(state.variants) ?? 1,
    seed: state.seed.trim() === "" ? null : wholeNumber(state.seed),
  };
}

/** A saved recording or join as what the form needs to know of its source. */
export function sourceInfoOf(source: MusicSource): SourceInfo {
  return { label: source.label, url: source.url, durationS: source.duration_s, seamS: source.seam_s };
}

/** The saved source's line in the picker: "Run 1 + run 2 · join · 19.5 s". */
export function savedSourceLabel(source: MusicSource): string {
  return `${source.label} · ${source.kind} · ${secondsText(source.duration_s)}`;
}

/** Where an edit's sound came from, for its card: "Edit of run 3", "Edit of the recording x". */
export function sourceLine(source: RunSource): string {
  if (source.type === "run") {
    return `Edit of run ${source.run_id}`;
  }
  const length = source.duration_s === null ? "" : ` (${secondsText(source.duration_s)})`;
  const seam = source.seam_s === null ? "" : `, joined at ${secondsText(source.seam_s)}`;
  return `Edit of the ${source.type === "join" ? "join" : "recording"} "${source.label}"${length}${seam}`;
}

/** What was measured in a run, as a short line for its card. */
export function measurementLine(measurement: AudioMeasurement): string {
  const parts = [`${secondsText(measurement.duration_s)} long`];
  if (measurement.leading_silence_s >= 0.1) {
    parts.push(`${secondsText(measurement.leading_silence_s)} of silence first`);
  }
  if (measurement.loudest_moment !== null) {
    parts.push(`loudest at ${secondsText(measurement.loudest_moment.time_s)}`);
  }
  if (measurement.ending !== null) {
    parts.push(measurement.ending.kind === "decay" ? "ends by fading" : "ends cut off");
  }
  return parts.join(" · ");
}
