import type { ProjectDetail } from "../../api/projects";

/** What a project makes. Chosen when the project is created and never changed. */
export type ProjectKind = ProjectDetail["kind"];

export const PROJECT_KINDS: {
  value: ProjectKind;
  label: string;
  description: string;
}[] = [
  {
    value: "story",
    label: "Story",
    description: "A written story turned into a film, with its own characters and places.",
  },
  {
    value: "explainer",
    label: "Explainer",
    description:
      "A script explained by one presenter from the Character Lab: on camera in some passages, and as a voice-over over B-roll in the others.",
  },
];

export function isProjectKind(value: string): value is ProjectKind {
  return PROJECT_KINDS.some((option) => option.value === value);
}

export function projectKindLabel(kind: ProjectKind): string {
  return PROJECT_KINDS.find((option) => option.value === kind)?.label ?? kind;
}
