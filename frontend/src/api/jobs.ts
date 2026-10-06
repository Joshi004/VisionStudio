import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { GPU_KEY } from "./gpu";
import { PROJECTS_KEY } from "./projects";
import type { components } from "./schema";

export type JobSummary = components["schemas"]["JobSummary"];
export type JobDetail = components["schemas"]["JobDetail"];

/** Every job query starts with this key, so one call refreshes them all. */
export const JOBS_KEY = ["jobs"] as const;

/** A job action changes jobs, a project's transcription and the banner's waiting count. */
export function invalidateAfterJobAction(queryClient: QueryClient) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: JOBS_KEY }),
    queryClient.invalidateQueries({ queryKey: PROJECTS_KEY }),
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

/** The newest jobs, all of them or those of one project. */
export function useJobs(projectId?: number) {
  return useQuery({
    queryKey: [...JOBS_KEY, "list", projectId ?? "all"],
    queryFn: () => fetchJobs(projectId),
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

/** One job with its input and output. Nothing is loaded while `jobId` is null. */
export function useJob(jobId: number | null) {
  return useQuery({
    queryKey: [...JOBS_KEY, "detail", jobId],
    queryFn: () => fetchJob(jobId as number),
    enabled: jobId !== null,
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
