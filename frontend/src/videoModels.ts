/**
 * The video models the app can make clips with. The ids are what the API stores
 * (`app/services/video_models.py` on the backend lists the same three). MiniMax H3 is the
 * default in the Video lab and the Character lab.
 */
export type VideoModel = "ltx-2.3" | "ltx-2.5" | "minimax-h3";

export const H3_MODEL: VideoModel = "minimax-h3";

export const VIDEO_MODELS: { value: VideoModel; label: string }[] = [
  { value: "ltx-2.3", label: "LTX-2.3" },
  { value: "ltx-2.5", label: "LTX-2.5" },
  { value: H3_MODEL, label: "MiniMax H3" },
];

/** The models the Video lab can make a clip with: the same list as `VIDEO_MODELS`. */
export type LabVideoModel = VideoModel;

export const LAB_VIDEO_MODELS = VIDEO_MODELS;

/** The name to show for a model id. An id this version does not know is shown as it is. */
export function videoModelLabel(model: string | null | undefined): string {
  if (model === null || model === undefined) {
    return "unknown model";
  }
  return VIDEO_MODELS.find((entry) => entry.value === model)?.label ?? model;
}
