import type { ProjectDetail } from "../../api/projects";

/**
 * How an explainer's captions are delivered (CAP-001). "burned": drawn on the picture.
 * "ytt": nothing is drawn; the captions come as a file. Can be changed at any time.
 */
export type CaptionMode = ProjectDetail["caption_mode"];

export const CAPTION_MODES: {
  value: CaptionMode;
  label: string;
  description: string;
}[] = [
  {
    value: "burned",
    label: "Burned into the video",
    description: "Captions are drawn on the picture. Best for Shorts, Reels and TikTok.",
  },
  {
    value: "ytt",
    label: "YouTube caption file",
    description:
      "The video has no captions. Download a YTT or SRT file from the render and upload it with the video.",
  },
];

export function isCaptionMode(value: string): value is CaptionMode {
  return CAPTION_MODES.some((option) => option.value === value);
}
