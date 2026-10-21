import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type LookStateResolution =
  components["schemas"]["LookStateResolutionOut"];
export type LookStateScene = components["schemas"]["LookStateSceneOut"];
export type LookStateItem = components["schemas"]["LookStateItemOut"];

/**
 * Every looks-and-states query of a project starts with this key. It also starts with the
 * project's own key, so saving the story (which refreshes the project) refreshes the "out of
 * date" state too.
 */
export function lookStateKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "looks-and-states"] as const;
}

async function fetchResolution(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/looks-and-states",
    { params: { path: { project_id: projectId } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(
        error,
        `Could not load the looks and states (HTTP ${response.status}).`,
      ),
      response.status,
    );
  }
  return data;
}

/**
 * What every scene's look and environment-state requests resolved to. It is loaded again every
 * few seconds while the resolution job is waiting or running.
 */
export function useLookStateResolution(projectId: number) {
  return useQuery({
    queryKey: lookStateKey(projectId),
    queryFn: () => fetchResolution(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (current) =>
      isJobActive(current.state.data?.job) ? ACTIVE_POLL_MS : false,
  });
}

/**
 * Starts the job that resolves the looks and states. A refusal can mean something changed, so
 * the state and the jobs are loaded again either way. The library is refreshed too, because the
 * job adds named looks and states to it.
 */
export function useResolveLooksAndStates(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/looks-and-states/run",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not start the resolution (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: lookStateKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}
