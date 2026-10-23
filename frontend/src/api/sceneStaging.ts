import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId, refreshProject } from "./projects";
import type { components } from "./schema";

export type SceneStaging = components["schemas"]["SceneStagingOut"];
export type SceneStagingEntry = components["schemas"]["StagingEntryOut"];
export type SceneStagingContent = components["schemas"]["StagingContentOut"];
export type StagingPlacement = components["schemas"]["PlacementOut"];
export type StagingMove = components["schemas"]["MoveOut"];
export type StagingEnvironment = components["schemas"]["StagingEnvironmentOut"];
export type StagingSaveInput = components["schemas"]["StagingSaveIn"];

/**
 * Every scene-staging query of a project starts with this key. It also starts with the project's
 * own key, so saving the story (which refreshes the project) refreshes the "out of date" state
 * too.
 */
export function sceneStagingKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "scene-staging"] as const;
}

async function fetchStaging(projectId: number) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}/scene-staging", {
    params: { path: { project_id: projectId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the scene staging (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/**
 * The newest list of scenes with where each scene's staging stands. It is loaded again every few
 * seconds while any staging job is waiting or running.
 */
export function useSceneStaging(projectId: number) {
  return useQuery({
    queryKey: sceneStagingKey(projectId),
    queryFn: () => fetchStaging(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (current) =>
      current.state.data?.entries.some((entry) => isJobActive(entry.job)) ? ACTIVE_POLL_MS : false,
  });
}

/** A refusal can mean something changed, so the jobs are loaded again as well. */
function refreshAfterRun(queryClient: QueryClient, projectId: number) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: sceneStagingKey(projectId) }),
    invalidateAfterJobAction(queryClient),
  ]);
}

/** "Stage all": starts a job for every scene whose staging is missing or out of date. */
export function useStageAllScenes(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/scene-staging/run",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the scene staging (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}

/**
 * Starts the job that stages one scene. `confirmReplaceManual` is true only after the user agreed
 * to add a version from the model on top of one they wrote.
 */
export function useStageOneScene(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { sceneId: string; confirmReplaceManual: boolean }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/scene-staging/{scene_id}/run",
        {
          params: { path: { project_id: projectId, scene_id: input.sceneId } },
          body: { confirm_replace_manual: input.confirmReplaceManual },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the scene staging (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}

/** Saves one scene's edited staging as its next version, written by the user. */
export function useSaveSceneStaging(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { sceneId: string; staging: StagingSaveInput }) => {
      const { data, error, response } = await api.PUT(
        "/api/projects/{project_id}/scene-staging/{scene_id}",
        {
          params: { path: { project_id: projectId, scene_id: input.sceneId } },
          body: input.staging,
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not save the scene staging (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => refreshProject(queryClient, projectId),
  });
}
