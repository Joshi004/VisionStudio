import type { ProjectDetail } from "../../api/projects";

/**
 * Where a continuous explainer's voice takes come from (REC-002). "generated": the presenter's
 * voice made by the speech model. "recorded": a person records the script. Can be changed at any
 * time; switching deletes nothing.
 */
export type TakeSource = ProjectDetail["take_source"];

export const TAKE_SOURCES: {
  value: TakeSource;
  label: string;
  description: string;
}[] = [
  {
    value: "generated",
    label: "Generated voice",
    description: "Each scene is spoken by the presenter's voice (TTS).",
  },
  {
    value: "recorded",
    label: "Recorded voice",
    description:
      "You record the script yourself, in one go or scene by scene. The pipeline waits for your recording.",
  },
];

export function isTakeSource(value: string): value is TakeSource {
  return TAKE_SOURCES.some((option) => option.value === value);
}
