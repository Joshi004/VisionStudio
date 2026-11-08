import type { components } from "./schema";

/** How often a page asks again while a job it shows is waiting or running. */
export const ACTIVE_POLL_MS = 3_000;

/** How often the Text lab asks again while a reply is being written, so the answer appears as it grows. */
export const CHAT_POLL_MS = 1_000;

/** How often an endpoint that is expensive to compute asks again while a job is active. */
export const SLOW_POLL_MS = 30_000;

/** How often the backend status and the remote server banner ask again, whatever is happening. */
export const STATUS_POLL_MS = 30_000;

/** A job that has not finished: it is waiting to start, or it is running. */
export function isJobActive(
  job: Pick<components["schemas"]["JobSummary"], "status"> | null | undefined,
): boolean {
  return job != null && (job.status === "queued" || job.status === "running");
}
