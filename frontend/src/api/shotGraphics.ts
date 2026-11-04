import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type ShotGraphicsState = components["schemas"]["ShotGraphicsStateOut"];
export type ShotGraphicScene = components["schemas"]["ShotGraphicSceneOut"];
export type ShotGraphic = components["schemas"]["ShotGraphicShotOut"];
export type ShotGraphicEngine = components["schemas"]["ShotGraphicEngineOut"];
export type ShotGraphicAttempt = components["schemas"]["ShotGraphicAttemptOut"];
export type ShotGraphicEngineKey = ShotGraphicEngine["key"];

/**
 * Every graphics query of a project starts with this key. It also starts with the project's own
 * key, so saving the project's settings (which refreshes the project) refreshes the panel.
 */
export function shotGraphicsKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "graphics"] as const;
}

async function fetchShotGraphics(projectId: number) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}/graphics", {
    params: { path: { project_id: projectId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the graphics (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/** Whether a version of the shot is being written or drawn. */
export function isShotGraphicWorking(shot: ShotGraphic): boolean {
  return shot.status === "working";
}

/**
 * The graphic shots of every scene with both versions of each. It is loaded again every few
 * seconds while any version of any shot is being written or drawn.
 */
export function useShotGraphics(projectId: number) {
  return useQuery({
    queryKey: shotGraphicsKey(projectId),
    queryFn: () => fetchShotGraphics(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (query) =>
      query.state.data?.scenes.some((scene) => scene.shots.some(isShotGraphicWorking))
        ? ACTIVE_POLL_MS
        : false,
  });
}

/** Makes what is missing for one graphic shot (the same start the pipeline's run uses). */
export function useMakeShotGraphics(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { sceneId: string; shotId: string }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/graphics/{scene_id}/{shot_id}/run",
        {
          params: {
            path: { project_id: projectId, scene_id: input.sceneId, shot_id: input.shotId },
          },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not make the graphics (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: shotGraphicsKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/** A paid model call: makes one version of one shot again as a new attempt, from the same brief. */
export function useAskGraphicAgain(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      sceneId: string;
      shotId: string;
      engine: ShotGraphicEngineKey;
    }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/graphics/{scene_id}/{shot_id}/{engine}/ask-again",
        {
          params: {
            path: {
              project_id: projectId,
              scene_id: input.sceneId,
              shot_id: input.shotId,
              engine: input.engine,
            },
          },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not ask again (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: shotGraphicsKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/**
 * Chooses the version the video uses for one shot. `null` is Automatic: the generated component,
 * and the building blocks only when it failed outright. A new brief puts the shot back on it.
 */
export function useSetGraphicChoice(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      sceneId: string;
      shotId: string;
      engine: ShotGraphicEngineKey | null;
    }) => {
      const { data, error, response } = await api.PUT(
        "/api/projects/{project_id}/graphics/{scene_id}/{shot_id}/choice",
        {
          params: {
            path: { project_id: projectId, scene_id: input.sceneId, shot_id: input.shotId },
          },
          body: { engine: input.engine },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not choose the version (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: shotGraphicsKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}
