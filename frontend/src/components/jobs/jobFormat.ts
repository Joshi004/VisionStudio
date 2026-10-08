import type { JobSummary } from "../../api/jobs";

const TYPE_LABELS: Record<JobSummary["type"], string> = {
  transcribe: "Transcription",
  plan_scenes: "Scene proposal",
  draft_descriptions: "Scene descriptions",
  write_image_prompt: "Image prompt",
  generate_clip: "Clip generation",
  render_final: "Final render",
};

export function jobTypeLabel(type: JobSummary["type"]): string {
  return TYPE_LABELS[type];
}

const STATUS_COLORS: Record<JobSummary["status"], string> = {
  queued: "gray",
  running: "blue",
  succeeded: "green",
  failed: "red",
  cancelled: "gray",
};

export function statusColor(status: JobSummary["status"]): string {
  return STATUS_COLORS[status];
}

/** "40 s", "1 min 20 s", "1 h 5 min". */
export function formatElapsed(totalSeconds: number): string {
  const seconds = Math.max(0, Math.round(totalSeconds));
  if (seconds < 60) {
    return `${seconds} s`;
  }
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    const rest = seconds % 60;
    return rest === 0 ? `${minutes} min` : `${minutes} min ${rest} s`;
  }
  const hours = Math.floor(minutes / 60);
  const minutesRest = minutes % 60;
  return minutesRest === 0 ? `${hours} h` : `${hours} h ${minutesRest} min`;
}

/** "typically about 12 min", from the server's usual run time. Empty when it is not known. */
export function typicalText(typicalSeconds: number | null): string {
  if (typicalSeconds === null || typicalSeconds <= 0) {
    return "";
  }
  // A few minutes is a rough figure: round it to the minute so it does not look exact.
  const rounded = typicalSeconds < 120 ? typicalSeconds : Math.round(typicalSeconds / 60) * 60;
  return `typically about ${formatElapsed(rounded)}`;
}

type Timed = Pick<JobSummary, "status" | "created_at" | "started_at" | "finished_at">;

/**
 * How long a job has waited, run or taken, worked out from the stored times and `now`
 * (milliseconds since 1970). It is computed when the page renders, so it is right
 * whenever you look, with no timer (ANALYSIS.md Section 3.4).
 */
export function elapsedText(job: Timed, now: number): string {
  const created = Date.parse(job.created_at);
  const started = job.started_at ? Date.parse(job.started_at) : created;
  const finished = job.finished_at ? Date.parse(job.finished_at) : null;

  if (job.status === "queued") {
    return `waiting ${formatElapsed((now - created) / 1000)}`;
  }
  if (job.status === "running") {
    return `running ${formatElapsed((now - started) / 1000)}`;
  }
  if (finished === null) {
    return "";
  }
  const verb = job.status === "cancelled" ? "cancelled after" : "took";
  return `${verb} ${formatElapsed((finished - created) / 1000)}`;
}

/** Only a job that has not finished shows its phase: for the others it repeats the status. */
export function showsPhase(status: JobSummary["status"]): boolean {
  return status === "queued" || status === "running";
}
