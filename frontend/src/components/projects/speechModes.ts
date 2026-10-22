import type { ProjectDetail } from "../../api/projects";

/** How a project's story is spoken. Chosen when the project is created and never changed. */
export type SpeechMode = ProjectDetail["speech_mode"];

export const SPEECH_MODES: {
  value: SpeechMode;
  label: string;
  description: string;
}[] = [
  {
    value: "both",
    label: "Narration and dialogue",
    description: "A narrator tells the story and the characters speak.",
  },
  {
    value: "no_dialogue",
    label: "No dialogue",
    description:
      "Only a narrator speaks. The characters' lines are read by the narrator.",
  },
  {
    value: "no_narration",
    label: "No narration",
    description:
      "No narrator. The story is told by what the characters do and say.",
  },
];

export function isSpeechMode(value: string): value is SpeechMode {
  return SPEECH_MODES.some((option) => option.value === value);
}

export function speechModeLabel(mode: SpeechMode): string {
  return SPEECH_MODES.find((option) => option.value === mode)?.label ?? mode;
}
