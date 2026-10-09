import type { AutoProblem, AutoStep } from "../../api/autoPipeline";

/**
 * The step the run is at: the first one that is not complete. Every step before it is shown
 * as completed. Once every step is complete this is the number of steps.
 */
export function activeStepIndex(steps: AutoStep[]): number {
  const index = steps.findIndex((step) => step.status !== "done" && step.status !== "skipped");
  return index === -1 ? steps.length : index;
}

/** What is shown under a step's name. Empty for a step the run has not reached. */
export function stepDescription(step: AutoStep): string {
  const perScene = step.total > 1;
  switch (step.status) {
    case "pending":
      return "";
    case "running":
      return perScene ? `${step.done} of ${step.total} scenes done` : "In progress";
    case "done":
      return perScene ? `All ${step.total} scenes done` : "Done";
    case "skipped":
      return "Already done";
    case "failed":
      return perScene ? `Stopped: ${step.done} of ${step.total} scenes done` : "Stopped";
    case "stopped":
      return perScene ? `Cancelled: ${step.done} of ${step.total} scenes done` : "Cancelled";
  }
}

/** "Scene 4: Tried 3 times without success. The last try: ...". The project's own has no prefix. */
export function problemText(problem: AutoProblem): string {
  return problem.scene_number === null
    ? problem.message
    : `Scene ${problem.scene_number}: ${problem.message}`;
}
