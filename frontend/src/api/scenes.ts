import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { isValidProjectId, PROJECTS_KEY } from "./projects";
import type { components } from "./schema";

export type ScenesState = components["schemas"]["ScenesOut"];
export type Scene = components["schemas"]["SceneOut"];
export type Proposal = components["schemas"]["ProposalOut"];
/** What the user has confirmed when proposing scenes. Every flag is false unless set. */
export type ProposeFlags = components["schemas"]["ProposeScenesRequest"];

async function fetchScenes(projectId: number) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}/scenes", {
    params: { path: { project_id: projectId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the scenes (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/**
 * A project's scenes, the proposal they came from and whether they are out of date. It
 * lives under the project's key, so saving the script or the voiceover refreshes it.
 */
export function useScenes(projectId: number) {
  return useQuery({
    queryKey: [...PROJECTS_KEY, projectId, "scenes"],
    queryFn: () => fetchScenes(projectId),
    enabled: isValidProjectId(projectId),
  });
}

/**
 * Starts the proposal (a paid call to the language model) and returns at once. Progress
 * shows after a Refresh.
 */
export function useProposeScenes(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (flags: ProposeFlags) => {
      const { data, error, response } = await api.POST("/api/projects/{project_id}/propose-scenes", {
        params: { path: { project_id: projectId } },
        body: flags,
      });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the proposal (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => invalidateAfterJobAction(queryClient),
  });
}
