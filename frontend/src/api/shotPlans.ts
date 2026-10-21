import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type ShotPlans = components["schemas"]["ShotPlansOut"];
export type ShotPlanEntry = components["schemas"]["ShotPlanEntryOut"];
export type ShotPlanContent = components["schemas"]["ShotPlanContentOut"];
export type Shot = components["schemas"]["ShotOut"];
export type ShotPlanAll = components["schemas"]["ShotPlansRunAllOut"];

/**
 * Every shot-plan query of a project starts with this key. It also starts with the project's
 * own key, so saving the story (which refreshes the project) refreshes the "out of date" state
 * too.
 */
export function shotPlansKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "shot-plans"] as const;
}

async function fetchShotPlans(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/shot-plans",
    { params: { path: { project_id: projectId } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(
        error,
        `Could not load the shot plans (HTTP ${response.status}).`,
      ),
      response.status,
    );
  }
  return data;
}

/**
 * The newest list of scenes with where each scene's shot plan stands. It is loaded again every
 * few seconds while any planning job is waiting or running.
 */
export function useShotPlans(projectId: number) {
  return useQuery({
    queryKey: shotPlansKey(projectId),
    queryFn: () => fetchShotPlans(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (current) =>
      current.state.data?.entries.some((entry) => isJobActive(entry.job))
        ? ACTIVE_POLL_MS
        : false,
  });
}

/** A refusal can mean something changed, so the jobs are loaded again as well. */
function refreshAfterRun(queryClient: QueryClient, projectId: number) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: shotPlansKey(projectId) }),
    invalidateAfterJobAction(queryClient),
  ]);
}

/** "Plan all": starts a job for every scene whose speech is made and whose plan is missing or out of date. */
export function usePlanAllShots(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/shot-plans/run",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not start the shot planning (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}

/** Starts the job that plans the shots of one scene. */
export function usePlanOneSceneShots(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (sceneId: string) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/shot-plans/{scene_id}/run",
        { params: { path: { project_id: projectId, scene_id: sceneId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not start the shot planning (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}
