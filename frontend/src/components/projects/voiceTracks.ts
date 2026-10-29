import type { ProjectDetail } from "../../api/projects";

/**
 * How an explainer's speech is made (FLOW-002). Chosen when the project is created and never
 * changed. A story is always "lines".
 */
export type VoiceTrack = ProjectDetail["voice_track"];

/** The most characters the speech model accepts as a delivery instruction. */
export const DELIVERY_MAX_CHARS = 500;

export const VOICE_TRACKS: {
  value: VoiceTrack;
  label: string;
  description: string;
}[] = [
  {
    value: "continuous",
    label: "Continuous voice",
    description:
      "One voice take per scene, spoken at one pace. The picture is cut on top of it, so a cut can fall on any word.",
  },
  {
    value: "lines",
    label: "Line by line",
    description: "Each line is spoken and shown on its own.",
  },
];

export function isVoiceTrack(value: string): value is VoiceTrack {
  return VOICE_TRACKS.some((option) => option.value === value);
}

export function voiceTrackLabel(track: VoiceTrack): string {
  return VOICE_TRACKS.find((option) => option.value === track)?.label ?? track;
}
