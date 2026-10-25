import { isJobActive } from "../../api/polling";
import type { MusicTrialCase, TrialAnswer } from "../../api/musicLab";

/** The groups of round 2 and what each is about, in the order they are shown. */
export const TRIAL_GROUPS: { id: string; label: string; about: string }[] = [
  { id: "I", label: "I. Music character", about: "Can a theme keep its tune while its feeling changes?" },
  { id: "J", label: "J. Starts and endings", about: "Can a cue start at full presence, or end properly?" },
  { id: "K", label: "K. Joins", about: "Can a join between two cues be rewritten, or a cue carried on?" },
  { id: "L", label: "L. Repairs", about: "Can part of a cue be repaired without touching the rest?" },
  { id: "M", label: "M. Ambience and effects", about: "Do long beds and effects behave as the placement needs?" },
];

export const ANSWER_LABELS: Record<TrialAnswer, string> = { yes: "Yes", partly: "Partly", no: "No" };

export type CaseStatus = "not_started" | "running" | "ready" | "reviewed";

export const STATUS_LABELS: Record<CaseStatus, string> = {
  not_started: "Not started",
  running: "Running",
  ready: "Ready to review",
  reviewed: "Reviewed",
};

export const STATUS_COLORS: Record<CaseStatus, string> = {
  not_started: "gray",
  running: "blue",
  ready: "orange",
  reviewed: "green",
};

/** Where a case stands: not started, running, ready to listen to, or answered. */
export function caseStatus(trial: MusicTrialCase): CaseStatus {
  if (trial.answer !== null) {
    return "reviewed";
  }
  if (trial.runs.length === 0 && trial.local_outputs.length === 0) {
    return "not_started";
  }
  return trial.runs.some((run) => isJobActive(run.job)) ? "running" : "ready";
}

/** The label of a run on the screen: the one the guide gives it, or "Run 12". */
export function runLabel(trial: MusicTrialCase, runId: number): string {
  return (trial.guide.run_labels ?? {})[String(runId)] ?? `Run ${runId}`;
}

/** "3 of 38 cases answered", for the top of the screen. */
export function progressLine(trials: MusicTrialCase[]): string {
  const answered = trials.filter((trial) => trial.answer !== null).length;
  const waiting = trials.filter((trial) => caseStatus(trial) === "ready").length;
  return `${answered} of ${trials.length} cases answered, ${waiting} ready for you to listen to.`;
}
