import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { isValidProjectId, PROJECTS_KEY } from "./projects";
import type { components } from "./schema";

export type ScenesState = components["schemas"]["ScenesOut"];
export type Scene = components["schemas"]["SceneOut"];
export type Proposal = components["schemas"]["ProposalOut"];
/** What the user has confirmed when proposing scenes. Every flag is false unless set. */
export type ProposeFlags = components["schemas"]["ProposeScenesRequest"];
/** One word of the script, as the scenes were cut from it. */
export type SceneWord = components["schemas"]["SceneWordOut"];
/** One edit of one cut: add, remove or move. */
export type CutEditBody = components["schemas"]["CutEditRequest"];
/** What the user has confirmed when drafting the descriptions. */
export type DraftFlags = components["schemas"]["DraftDescriptionsRequest"];

/** The scenes query lives under the project's key, so saving the script refreshes it. */
export function scenesKey(projectId: number) {
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
 * True while any job the scenes carry is waiting or running: the proposal, the description
 * draft, or a scene's clip, first frame or image prompt.
 */
export function scenesHaveActiveJob(data: ScenesState | undefined): boolean {
  if (data === undefined) {
    return false;
  }
  return (
    isJobActive(data.job) ||
    isJobActive(data.description_job) ||
    data.scenes.some(
      (scene) =>
        isJobActive(scene.clip_job) ||
        isJobActive(scene.frame_job) ||
        isJobActive(scene.image_prompt_job),
    )
  );
}

/**
 * A project's scenes, the proposal they came from and whether they are out of date. It
 * lives under the project's key, so saving the script or the voiceover refreshes it. It is
 * loaded again every few seconds while any of its jobs is waiting or running.
 */
export function useScenes(projectId: number) {
  return useQuery({
    queryKey: scenesKey(projectId),
    queryFn: () => fetchScenes(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (query) => (scenesHaveActiveJob(query.state.data) ? ACTIVE_POLL_MS : false),
  });
}

/**
 * Starts the proposal (a paid call to the language model) and returns at once. The page
 * follows its progress by itself.
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

/**
 * Starts drafting the scene descriptions (a paid call to the language model) and returns at
 * once. The page follows its progress by itself. A 422 means the scenes changed since the
 * page was loaded, so they are loaded again.
 */
export function useDraftDescriptions(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (flags: DraftFlags) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/draft-descriptions",
        { params: { path: { project_id: projectId } }, body: flags },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start drafting (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => invalidateAfterJobAction(queryClient),
    onError: (error) => {
      if (error instanceof ApiError && (error.status === 404 || error.status === 422)) {
        void queryClient.invalidateQueries({ queryKey: scenesKey(projectId) });
      }
    },
  });
}

/**
 * Adds, moves or removes one cut. The answer holds the scenes as they are afterwards, so
 * the page shows the change at once, with no Refresh. A 409 (a scene beside the cut has
 * inputs) is left to the caller, which asks the user and sends the edit again. After a 422
 * the page may be showing old scenes, so they are loaded again.
 */
export function useEditCut(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (edit: CutEditBody) => {
      const { data, error, response } = await api.POST("/api/projects/{project_id}/edit-cut", {
        params: { path: { project_id: projectId } },
        body: edit,
      });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not change the cut (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: async (data) => {
      // A check that is still on its way would arrive after this answer and show the old
      // scenes again, so it is cancelled first.
      await queryClient.cancelQueries({ queryKey: scenesKey(projectId), exact: true });
      queryClient.setQueryData(scenesKey(projectId), data);
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 422) {
        void queryClient.invalidateQueries({ queryKey: scenesKey(projectId) });
      }
    },
  });
}
