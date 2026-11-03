import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type GraphicBriefsState = components["schemas"]["GraphicBriefsState"];
export type GraphicBriefScene = components["schemas"]["GraphicBriefSceneOut"];
export type GraphicShot = components["schemas"]["GraphicShotOut"];
export type GraphicShotBrief = components["schemas"]["BriefOut"];

/**
 * Every graphic brief query of a project starts with this key. It also starts with the project's
 * own key, so saving the project's settings (which refreshes the project) refreshes the panel.
 */
export function graphicBriefsKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "graphic-briefs"] as const;
}

async function fetchGraphicBriefs(projectId: number) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}/graphic-briefs", {
    params: { path: { project_id: projectId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the graphic briefs (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/**
 * The graphic shots of every scene with their briefs. It is loaded again every few seconds while
 * the job of any shot is waiting or running.
 */
export function useGraphicBriefs(projectId: number) {
  return useQuery({
    queryKey: graphicBriefsKey(projectId),
    queryFn: () => fetchGraphicBriefs(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (query) =>
      query.state.data?.scenes.some((scene) => scene.shots.some((shot) => isJobActive(shot.job)))
        ? ACTIVE_POLL_MS
        : false,
  });
}

/**
 * Starts the job that writes the brief of one graphic shot. `feedback` is the owner's note on the
 * newest brief of the shot; leave it out for a plain run.
 */
export function useRunGraphicBrief(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { sceneId: string; shotId: string; feedback?: string }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/graphic-briefs/{scene_id}/{shot_id}/run",
        {
          params: {
            path: { project_id: projectId, scene_id: input.sceneId, shot_id: input.shotId },
          },
          body: { feedback: input.feedback ?? null },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the graphic brief (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: graphicBriefsKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}
