/**
 * The video models the app can make clips with. The ids are what the API stores
 * (`app/services/video_models.py` on the backend lists the same three). MiniMax H3 is the
 * default of a fresh install, in Project settings, on a scene, in the Regenerate picker and in
 * both labs.
 */
export type VideoModel = "ltx-2.3" | "ltx-2.5" | "minimax-h3";

export const H3_MODEL: VideoModel = "minimax-h3";

/** The size MiniMax H3 makes a clip at, by orientation (the same as `H3_SIZES` on the backend). */
export const H3_SIZES: Record<"landscape" | "portrait", { width: number; height: number }> = {
  landscape: { width: 1344, height: 768 },
  portrait: { width: 768, height: 1344 },
};

export const VIDEO_MODELS: { value: VideoModel; label: string }[] = [
  { value: "ltx-2.3", label: "LTX-2.3" },
  { value: "ltx-2.5", label: "LTX-2.5" },
  { value: H3_MODEL, label: "MiniMax H3" },
];

/**
 * The models the Video lab can make a clip with. It is the same list as `VIDEO_MODELS` since
 * MiniMax H3 became a project and scene model; the lab keeps its own names for it.
 */
export type LabVideoModel = VideoModel;

export const LAB_VIDEO_MODELS = VIDEO_MODELS;

export function isVideoModel(value: string | null | undefined): value is VideoModel {
  return VIDEO_MODELS.some((entry) => entry.value === value);
}

export const isLabVideoModel = isVideoModel;

/** The name to show for a model id. An id this version does not know is shown as it is. */
export function videoModelLabel(model: string | null | undefined): string {
  if (model === null || model === undefined) {
    return "unknown model";
  }
  return VIDEO_MODELS.find((entry) => entry.value === model)?.label ?? model;
}

/** The value a choice list uses for "no choice of its own: use the level above". */
export const INHERIT = "inherit";

/** A choice list's data: the "use the level above" entry first, then every model. */
export function modelChoices(inheritLabel: string): { value: string; label: string }[] {
  return [{ value: INHERIT, label: inheritLabel }, ...VIDEO_MODELS];
}
