import type { components } from "./schema";

/** How often a page asks again while a job it shows is waiting or running. */
export const ACTIVE_POLL_MS = 3_000;

/** How often the backend status and the GPU banner ask again, whatever is happening. */
export const STATUS_POLL_MS = 30_000;

/** A job that has not finished: it is waiting to start, or it is running. */
export function isJobActive(
  job: Pick<components["schemas"]["JobSummary"], "status"> | null | undefined,
): boolean {
  return job != null && (job.status === "queued" || job.status === "running");
}
