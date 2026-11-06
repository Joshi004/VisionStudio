import type { ProjectDetail } from "../../api/projects";

/**
 * How an explainer's callouts are drawn (CMO-002). "boxes": short text boxes, drawn quickly and
 * for free. "motion": a small animated graphic in the video's graphics look, only for a
 * continuous explainer with graphics and callouts on. Can be changed at any time.
 */
export type CalloutStyle = ProjectDetail["callout_style"];

export const CALLOUT_STYLES: {
  value: CalloutStyle;
  label: string;
  description: string;
}[] = [
  {
    value: "boxes",
    label: "Simple boxes",
    description: "Callouts are short text boxes, drawn quickly and for free.",
  },
  {
    value: "motion",
    label: "Motion graphics",
    description:
      "Each callout is a small animated graphic in the video's graphics look, made in two versions you can choose between. Every callout costs two model calls.",
  },
];

export function isCalloutStyle(value: string): value is CalloutStyle {
  return CALLOUT_STYLES.some((option) => option.value === value);
}
