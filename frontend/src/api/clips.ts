import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { useSceneInputsMutation } from "./sceneInputs";
import { scenesKey } from "./scenes";
import type { components } from "./schema";
import type { VideoModel } from "../videoModels";

/** One finished clip of a scene. */
export type Take = components["schemas"]["TakeOut"];
/** What "Generate all ready scenes" started. */
export type GenerateReadyResult = components["schemas"]["GenerateReadyOut"];

/**
 * After a refused or failed start the page may be showing old data (a scene was merged, the
 * scenes went out of date, a proposal began), so the scenes are loaded again.
 */
export function useStartMutation<TVariables, TResult>(
  projectId: number,
  mutationFn: (variables: TVariables) => Promise<TResult>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    // A start creates jobs: the job lists, the scenes (which carry each scene's latest job)
    // and the banner's waiting count all change.
    onSuccess: () => invalidateAfterJobAction(queryClient),
    onError: (error) => {
      if (error instanceof ApiError && (error.status === 404 || error.status === 422)) {
        void queryClient.invalidateQueries({ queryKey: scenesKey(projectId) });
      }
    },
  });
}

/**
 * Starts a clip for one scene (Generate, and Regenerate when it has one) and returns at once.
 * The clip takes minutes: the page follows its progress by itself. `videoModel` makes this one
 * take with that model; left out, the scene's own choice, the project's or the app's is used.
 */
export function useGenerateClip(projectId: number) {
  return useStartMutation(
    projectId,
    async ({ sceneId, videoModel }: { sceneId: number; videoModel?: VideoModel }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/scenes/{scene_id}/generate",
        {
          params: { path: { project_id: projectId, scene_id: sceneId } },
          body: videoModel === undefined ? undefined : { video_model: videoModel },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the clip (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
  );
}

/** Starts a clip for every scene that is ready and has no clip yet. */
export function useGenerateReadyScenes(projectId: number) {
  return useStartMutation(projectId, async () => {
    const { data, error, response } = await api.POST(
      "/api/projects/{project_id}/generate-ready-scenes",
      { params: { path: { project_id: projectId } } },
    );
    if (!data) {
      throw new ApiError(
        detailMessage(error, `Could not start the clips (HTTP ${response.status}).`),
        response.status,
      );
    }
    return data;
  });
}

/** Makes one of the scene's finished clips the one the final video uses. */
export function useSelectTake(projectId: number) {
  return useSceneInputsMutation(
    projectId,
    async ({ sceneId, assetId }: { sceneId: number; assetId: number }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/scenes/{scene_id}/select-take",
        {
          params: { path: { project_id: projectId, scene_id: sceneId } },
          body: { asset_id: assetId },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not select the take (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
  );
}

/**
 * Sets the scene's own video model, or clears it (null) to use the project's. It changes the
 * clips generated from now on, not the ones already made.
 */
export function useSetSceneVideoModel(projectId: number) {
  return useSceneInputsMutation(
    projectId,
    async ({ sceneId, videoModel }: { sceneId: number; videoModel: VideoModel | null }) => {
      const { data, error, response } = await api.PUT(
        "/api/projects/{project_id}/scenes/{scene_id}/video-model",
        {
          params: { path: { project_id: projectId, scene_id: sceneId } },
          body: { video_model: videoModel },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not change the video model (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
  );
}

/** Switches the scene's own clip sound on or off for the final video. */
export function useSetClipSound(projectId: number) {
  return useSceneInputsMutation(
    projectId,
    async ({ sceneId, useClipSound }: { sceneId: number; useClipSound: boolean }) => {
      const { data, error, response } = await api.PUT(
        "/api/projects/{project_id}/scenes/{scene_id}/clip-sound",
        {
          params: { path: { project_id: projectId, scene_id: sceneId } },
          body: { use_clip_sound: useClipSound },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not change the clip sound (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
  );
}
