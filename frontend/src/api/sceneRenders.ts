import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { isValidProjectId } from "./projects";
import type { components } from "./schema";
import { shotTakesKey } from "./shotTakes";

export type SceneRenders = components["schemas"]["SceneRendersOut"];
export type SceneRenderState = components["schemas"]["SceneRenderStateOut"];
export type SceneRender = components["schemas"]["SceneRenderOut"];

/**
 * The scene-render query of a project. It starts with the shot takes' key, so whatever refreshes
 * those (generating a clip, selecting a take) refreshes this too: a scene's video is made from
 * the selected takes.
 */
export function sceneRendersKey(projectId: number) {
  return [...shotTakesKey(projectId), "scene-renders"] as const;
}

async function fetchSceneRenders(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/scene-renders",
    { params: { path: { project_id: projectId } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(
        error,
        `Could not load the scene videos (HTTP ${response.status}).`,
      ),
      response.status,
    );
  }
  return data;
}

/**
 * Every scene with its renders and whether it can be rendered now. Nothing is rendered by
 * itself, so the page asks again only while a scene render job is waiting or running.
 */
export function useSceneRenders(projectId: number) {
  return useQuery({
    queryKey: sceneRendersKey(projectId),
    queryFn: () => fetchSceneRenders(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (current) =>
      current.state.data?.scenes.some((scene) => isJobActive(scene.job))
        ? ACTIVE_POLL_MS
        : false,
  });
}

/** Starts the job that renders one scene, with a placeholder for every shot without a clip. */
export function useRenderScene(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (sceneId: string) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/scene-renders/{scene_id}/run",
        { params: { path: { project_id: projectId, scene_id: sceneId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not start the scene render (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    // A refusal can mean something changed, so the state and the jobs are loaded again.
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: sceneRendersKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}
