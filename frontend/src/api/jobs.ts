import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { GPU_KEY } from "./gpu";
import { ACTIVE_POLL_MS, STATUS_POLL_MS, isJobActive } from "./polling";
import type { components } from "./schema";

export type JobSummary = components["schemas"]["JobSummary"];
export type JobDetail = components["schemas"]["JobDetail"];
export type JobCapacity = components["schemas"]["JobCapacity"];
export type PoolCapacity = components["schemas"]["PoolCapacity"];
export type ModelCapacity = components["schemas"]["ModelCapacity"];
export type JobDiagnostics = components["schemas"]["JobDiagnostics"];
export type SeriesStats = components["schemas"]["SeriesStats"];

const DIAGNOSTICS_POLL_MS = 15_000;

/** Every job query starts with this key, so one call refreshes them all. */
export const JOBS_KEY = ["jobs"] as const;

/** A job action changes jobs and the banner's waiting count. */
export function invalidateAfterJobAction(queryClient: QueryClient) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: JOBS_KEY }),
    queryClient.invalidateQueries({ queryKey: GPU_KEY }),
  ]);
}

async function fetchJobs(projectId: number | undefined) {
  const { data, response } = await api.GET("/api/jobs", {
    params: { query: { project_id: projectId, limit: 200 } },
  });
  if (!data) {
    throw new ApiError(`Could not load the jobs (HTTP ${response.status}).`, response.status);
  }
  return data;
}

/**
 * The newest jobs, all of them or those of one project. They are loaded again every few
 * seconds while any of them is waiting or running.
 */
export function useJobs(projectId?: number) {
  return useQuery({
    queryKey: [...JOBS_KEY, "list", projectId ?? "all"],
    queryFn: () => fetchJobs(projectId),
    refetchInterval: (query) => (query.state.data?.some(isJobActive) ? ACTIVE_POLL_MS : false),
  });
}

/** One page of the jobs, and how many jobs there are in all (of the project, when one is given). */
export type JobsPage = { jobs: JobSummary[]; total: number };

async function fetchJobsPage(
  projectId: number | undefined,
  page: number,
  pageSize: number,
): Promise<JobsPage> {
  const { data, response } = await api.GET("/api/jobs", {
    params: { query: { project_id: projectId, limit: pageSize, offset: (page - 1) * pageSize } },
  });
  if (!data) {
    throw new ApiError(`Could not load the jobs (HTTP ${response.status}).`, response.status);
  }
  const total = Number(response.headers.get("X-Total-Count"));
  return { jobs: data, total: Number.isFinite(total) ? total : data.length };
}

/**
 * The newest jobs, `pageSize` at a time (pages start at 1), all of them or those of one
 * project. The page is loaded again every few seconds while any job on it is waiting or running.
 */
export function useJobsPage(projectId: number | undefined, page: number, pageSize: number) {
  return useQuery({
    queryKey: [...JOBS_KEY, "page", projectId ?? "all", pageSize, page],
    queryFn: () => fetchJobsPage(projectId, page, pageSize),
    placeholderData: keepPreviousData,
    refetchInterval: (query) =>
      query.state.data?.jobs.some(isJobActive) ? ACTIVE_POLL_MS : false,
  });
}

async function fetchCapacity() {
  const { data, response } = await api.GET("/api/jobs/capacity");
  if (!data) {
    throw new ApiError(
      `Could not load the job limits (HTTP ${response.status}).`,
      response.status,
    );
  }
  return data;
}

/**
 * The two shared pools of running jobs, the remote server's and the paid inference API's: the
 * limit, what is running and waiting, and which kinds of job. It is loaded again every few
 * seconds while anything is running or waiting in a pool, and now and then otherwise.
 */
export function useJobCapacity() {
  return useQuery({
    queryKey: [...JOBS_KEY, "capacity"],
    queryFn: fetchCapacity,
    refetchInterval: (query) =>
      query.state.data?.pools.some((pool) => pool.running + pool.queued > 0)
        ? ACTIVE_POLL_MS
        : STATUS_POLL_MS,
  });
}

async function fetchDiagnostics() {
  const { data, response } = await api.GET("/api/jobs/diagnostics");
  if (!data) {
    throw new ApiError(
      `Could not load the scheduler health (HTTP ${response.status}).`,
      response.status,
    );
  }
  return data;
}

/** How long the scheduler's steps take and how long jobs wait, over the last few minutes. */
export function useJobDiagnostics() {
  return useQuery({
    queryKey: [...JOBS_KEY, "diagnostics"],
    queryFn: fetchDiagnostics,
    refetchInterval: DIAGNOSTICS_POLL_MS,
  });
}

async function fetchJob(jobId: number) {
  const { data, error, response } = await api.GET("/api/jobs/{job_id}", {
    params: { path: { job_id: jobId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the job (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/**
 * One job with its input and output. Nothing is loaded while `jobId` is null. It is loaded
 * again every few seconds while the job is waiting or running.
 */
export function useJob(jobId: number | null) {
  return useQuery({
    queryKey: [...JOBS_KEY, "detail", jobId],
    queryFn: () => fetchJob(jobId as number),
    enabled: jobId !== null,
    refetchInterval: (query) => (isJobActive(query.state.data) ? ACTIVE_POLL_MS : false),
  });
}

export function useCancelJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (jobId: number) => {
      const { data, error, response } = await api.POST("/api/jobs/{job_id}/cancel", {
        params: { path: { job_id: jobId } },
      });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not cancel the job (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => invalidateAfterJobAction(queryClient),
  });
}

export function useResubmitJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (jobId: number) => {
      const { data, error, response } = await api.POST("/api/jobs/{job_id}/resubmit", {
        params: { path: { job_id: jobId } },
      });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not submit the job again (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => invalidateAfterJobAction(queryClient),
  });
}
