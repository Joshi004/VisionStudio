import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";
import { storyBibleKey } from "./storyBible";

export type SceneDiscoveryState = components["schemas"]["SceneDiscoveryState"];
export type SceneDiscoveryOut = components["schemas"]["SceneDiscoveryOut"];
export type SceneDiscoveryVersion = components["schemas"]["DiscoveryVersionOut"];
export type SceneItem = components["schemas"]["SceneItem"];

/**
 * Every scene discovery query of a project starts with this key. It also starts with the
 * project's own key, so saving the story (which refreshes the project) refreshes the "out of
 * date" flag.
 */
function scenesKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "scenes"] as const;
}

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
 * The newest version, the list of versions, the newest job and the "out of date" flag. It is
 * loaded again every few seconds while the job is waiting or running.
 */
export function useScenes(projectId: number) {
  return useQuery({
    queryKey: scenesKey(projectId),
    queryFn: () => fetchScenes(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (query) => (isJobActive(query.state.data?.job) ? ACTIVE_POLL_MS : false),
  });
}

async function fetchSceneVersion(projectId: number, version: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/scenes/versions/{version}",
    { params: { path: { project_id: projectId, version } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the version (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/** One stored version. Nothing is loaded while `version` is null. */
export function useSceneVersion(projectId: number, version: number | null) {
  return useQuery({
    queryKey: [...scenesKey(projectId), "version", version],
    queryFn: () => fetchSceneVersion(projectId, version as number),
    enabled: isValidProjectId(projectId) && version !== null,
  });
}

/** Starts the job that finds the next version from the saved story. */
export function useRunScenes(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST("/api/projects/{project_id}/scenes/run", {
        params: { path: { project_id: projectId } },
      });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the scene search (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    // A refusal can mean the Story Bible is missing or out of date, so its state is loaded
    // again too, whether the run started or not.
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: scenesKey(projectId) }),
        queryClient.invalidateQueries({ queryKey: storyBibleKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}
