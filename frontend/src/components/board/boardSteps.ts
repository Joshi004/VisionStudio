import type { BoardStepStatus } from "../../api/pipelineBoard";

/** How a step status is shown. The order of the keys is the order of the priority list. */
export const STATUS_DISPLAY: Record<BoardStepStatus, { label: string; color: string }> = {
  attention: { label: "Needs attention", color: "red" },
  running: { label: "Running", color: "blue" },
  out_of_date: { label: "Out of date", color: "yellow" },
  done: { label: "Done", color: "green" },
  ready: { label: "Ready", color: "violet" },
  waiting: { label: "Waiting", color: "gray" },
  off: { label: "Off", color: "gray" },
};

/** The groups of steps in the order they are listed. A group not named here comes last. */
export const GROUP_ORDER: readonly string[] = [
  "story",
  "characters",
  "environments",
  "scenes",
  "speech",
  "music",
  "shots",
  "render",
];

export const GROUP_LABELS: Record<string, string> = {
  story: "Story",
  characters: "Characters",
  environments: "Environments",
  scenes: "Scenes",
  speech: "Speech",
  music: "Music",
  shots: "Shots",
  render: "Render",
};

/** Things of the project that are not pipeline steps, listed above the steps. */
export const WORKSPACE_ITEMS: readonly { key: string; label: string }[] = [
  { key: "story_text", label: "Story text" },
  { key: "cast", label: "Cast" },
  { key: "run", label: "Run the whole story" },
  { key: "out_of_date", label: "What is out of date" },
];

export const WORKSPACE_KEYS: ReadonlySet<string> = new Set(WORKSPACE_ITEMS.map((item) => item.key));

export function stepPath(projectId: number, key: string): string {
  return `/projects/${projectId}/pipeline/${key}`;
}
