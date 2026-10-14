import type { AutoProblem, AutoStep } from "../../api/autoPipeline";

/**
 * What is shown under a step's name. Empty for a step the run has not reached. Steps go on at
 * the same time, and a step's targets are scenes, or characters and places, so the count says
 * "done" and not "scenes done".
 */
export function stepDescription(step: AutoStep): string {
  const counted = step.total > 1;
  switch (step.status) {
    case "pending":
      return "";
    case "running":
      return counted ? `${step.done} of ${step.total} done` : "In progress";
    case "done":
      return counted ? `All ${step.total} done` : "Done";
    case "skipped":
      return "Already done";
    case "failed":
      return counted ? `Stopped: ${step.done} of ${step.total} done` : "Stopped";
    case "stopped":
      return counted ? `Cancelled: ${step.done} of ${step.total} done` : "Cancelled";
  }
}

/**
 * The round marker in front of a step's name: its text and colour. A running step shows a
 * spinner instead of text, so any number of steps can show as running at once.
 */
export function stepMarker(step: AutoStep, number: number): { text: string; color: string } {
  switch (step.status) {
    case "pending":
      return { text: String(number), color: "gray" };
    case "running":
      return { text: "", color: "blue" };
    case "done":
      return { text: "✓", color: "green" };
    case "skipped":
      return { text: "✓", color: "teal" };
    case "failed":
      return { text: "!", color: "red" };
    case "stopped":
      return { text: "–", color: "gray" };
  }
}

/**
 * "Make last frames: Scene 4: Tried 3 times without success. The last try: ...". The step comes
 * first because several steps go on at the same time. The project's own problem has no scene.
 */
export function problemText(problem: AutoProblem): string {
  const text =
    problem.scene_number === null
      ? problem.message
      : `Scene ${problem.scene_number}: ${problem.message}`;
  return problem.step ? `${problem.step}: ${text}` : text;
}
