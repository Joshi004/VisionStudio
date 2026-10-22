import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId, refreshProject } from "./projects";
import type { components } from "./schema";

export type SceneDefinitions = components["schemas"]["SceneDefinitionsOut"];
export type SceneDefinitionEntry =
  components["schemas"]["SceneDefinitionEntryOut"];
export type SceneDefinition = components["schemas"]["SceneDefinitionOut"];
export type SceneDefinitionInput = components["schemas"]["SceneDefinitionIn"];
export type SceneDefineAll = components["schemas"]["SceneDefinitionRunAllOut"];

/**
 * Every scene-definition query of a project starts with this key. It also starts with the
 * project's own key, so saving the story (which refreshes the project) refreshes the "out of
 * date" state too.
 */
export function sceneDefinitionsKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "scene-definitions"] as const;
}

async function fetchDefinitions(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/scene-definitions",
    { params: { path: { project_id: projectId } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(
        error,
        `Could not load the scene definitions (HTTP ${response.status}).`,
      ),
      response.status,
    );
  }
  return data;
}

/**
 * The newest list of scenes with where each definition stands. It is loaded again every few
 * seconds while any definition job is waiting or running.
 */
export function useSceneDefinitions(projectId: number) {
  return useQuery({
    queryKey: sceneDefinitionsKey(projectId),
    queryFn: () => fetchDefinitions(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (current) =>
      current.state.data?.entries.some((entry) => isJobActive(entry.job))
        ? ACTIVE_POLL_MS
        : false,
  });
}

/** A refusal can mean the Story Bible changed, so the jobs are loaded again as well. */
function refreshAfterRun(queryClient: QueryClient, projectId: number) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: sceneDefinitionsKey(projectId) }),
    invalidateAfterJobAction(queryClient),
  ]);
}

/** "Define all": starts a job for every scene that is not defined and up to date. */
export function useDefineAllScenes(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/scene-definitions/run",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not start the scene definitions (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}

/**
 * Starts the job that defines one scene. `confirmReplaceManual` is true only after the user
 * agreed to add a version from the model on top of one they wrote.
 */
export function useDefineOneScene(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { sceneId: string; confirmReplaceManual: boolean }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/scene-definitions/{scene_id}/run",
        {
          params: { path: { project_id: projectId, scene_id: input.sceneId } },
          body: { confirm_replace_manual: input.confirmReplaceManual },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not start the scene definition (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}

/** Saves one scene's edited definition as its next version, written by the user. */
export function useSaveSceneDefinition(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { sceneId: string; definition: SceneDefinitionInput }) => {
      const { data, error, response } = await api.PUT(
        "/api/projects/{project_id}/scene-definitions/{scene_id}",
        {
          params: { path: { project_id: projectId, scene_id: input.sceneId } },
          body: input.definition,
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not save the scene definition (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => refreshProject(queryClient, projectId),
  });
}
