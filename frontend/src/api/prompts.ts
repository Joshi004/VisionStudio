import { useQuery } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import type { components } from "./schema";

export type JobPrompt = components["schemas"]["JobPromptOut"];
export type LabImagePrompt = components["schemas"]["LabImagePromptOut"];

/**
 * A job's input and answer never change once it has finished, and a finished job is the only
 * kind that is asked about here (an artifact is saved when its job finishes). So a prompt is
 * kept for the whole visit and never loaded again.
 */
const FOREVER = Infinity;

async function fetchJobPrompt(jobId: number): Promise<JobPrompt> {
  const { data, error, response } = await api.GET("/api/jobs/{job_id}/prompt", {
    params: { path: { job_id: jobId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the prompt (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/** The prompt a job sent to a model. Nothing is loaded while `jobId` is null. */
export function useJobPrompt(jobId: number | null) {
  return useQuery({
    queryKey: ["prompts", "job", jobId],
    queryFn: () => fetchJobPrompt(jobId as number),
    enabled: jobId !== null,
    staleTime: FOREVER,
  });
}

async function fetchImagePrompt(imageId: number): Promise<LabImagePrompt> {
  const { data, error, response } = await api.GET("/api/lab/images/{image_id}/prompt", {
    params: { path: { image_id: imageId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the picture's prompt (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/** The prompt a lab picture was made from. Nothing is loaded while `imageId` is null. */
export function useLabImagePrompt(imageId: number | null) {
  return useQuery({
    queryKey: ["prompts", "image", imageId],
    queryFn: () => fetchImagePrompt(imageId as number),
    enabled: imageId !== null,
    staleTime: FOREVER,
  });
}
