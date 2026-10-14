/**
 * The video models the app can make clips with. The ids are what the API stores
 * (`app/services/video_models.py` on the backend lists the same two).
 */
export type VideoModel = "ltx-2.3" | "ltx-2.5";

export const VIDEO_MODELS: { value: VideoModel; label: string }[] = [
  { value: "ltx-2.3", label: "LTX-2.3" },
  { value: "ltx-2.5", label: "LTX-2.5" },
];

/**
 * The models the Video lab can make a clip with: the two above and MiniMax H3. MiniMax H3 can only
 * be chosen in the lab: projects, scenes and the Regenerate picker use `VIDEO_MODELS`.
 */
export type LabVideoModel = VideoModel | "minimax-h3";

export const H3_MODEL: LabVideoModel = "minimax-h3";

export const LAB_VIDEO_MODELS: { value: LabVideoModel; label: string }[] = [
  ...VIDEO_MODELS,
  { value: H3_MODEL, label: "MiniMax H3" },
];

export function isVideoModel(value: string | null | undefined): value is VideoModel {
  return VIDEO_MODELS.some((entry) => entry.value === value);
}

export function isLabVideoModel(value: string | null | undefined): value is LabVideoModel {
  return LAB_VIDEO_MODELS.some((entry) => entry.value === value);
}

/** The name to show for a model id. An id this version does not know is shown as it is. */
export function videoModelLabel(model: string | null | undefined): string {
  if (model === null || model === undefined) {
    return "unknown model";
  }
  return LAB_VIDEO_MODELS.find((entry) => entry.value === model)?.label ?? model;
}

/** The value a choice list uses for "no choice of its own: use the level above". */
export const INHERIT = "inherit";

/** A choice list's data: the "use the level above" entry first, then every model. */
export function modelChoices(inheritLabel: string): { value: string; label: string }[] {
  return [{ value: INHERIT, label: inheritLabel }, ...VIDEO_MODELS];
}
