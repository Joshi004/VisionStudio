import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { isValidProjectId, PROJECTS_KEY } from "./projects";
import type { components } from "./schema";

export type TranscriptionState = components["schemas"]["TranscriptionOut"];
export type Transcript = components["schemas"]["TranscriptOut"];
export type ScriptWord = components["schemas"]["ScriptWordOut"];

async function fetchTranscription(projectId: number) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}/transcription", {
    params: { path: { project_id: projectId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the transcript (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/**
 * The newest transcribe job and transcript of a project. It lives under the project's
 * key, so saving the script or the voiceover refreshes whether it is out of date. It is
 * loaded again every few seconds while the job is waiting or running.
 */
export function useTranscription(projectId: number) {
  return useQuery({
    queryKey: [...PROJECTS_KEY, projectId, "transcription"],
    queryFn: () => fetchTranscription(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (query) => (isJobActive(query.state.data?.job) ? ACTIVE_POLL_MS : false),
  });
}

/** Starts the job and returns at once. The page follows its progress by itself. */
export function useStartTranscription(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST("/api/projects/{project_id}/transcribe", {
        params: { path: { project_id: projectId } },
      });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the transcription (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => invalidateAfterJobAction(queryClient),
  });
}
