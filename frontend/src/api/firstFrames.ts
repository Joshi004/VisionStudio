import { api } from "./client";
import { useStartMutation } from "./clips";
import { ApiError, detailMessage } from "./errors";
import { useSceneInputsMutation } from "./sceneInputs";
import type { components } from "./schema";

/** What "Generate first frames" started: one job for each scene that needed a frame. */
export type GenerateFirstFramesResult = components["schemas"]["GenerateFirstFramesOut"];

/**
 * Starts a first frame job (a paid image from the image model) for every scene that needs
 * one, and returns at once. Progress shows after a Refresh. After a refusal the page may be
 * showing old data, so the scenes are loaded again.
 */
export function useGenerateFirstFrames(projectId: number) {
  return useStartMutation(projectId, async () => {
    const { data, error, response } = await api.POST(
      "/api/projects/{project_id}/generate-first-frames",
      { params: { path: { project_id: projectId } } },
    );
    if (!data) {
      throw new ApiError(
        detailMessage(error, `Could not start the first frames (HTTP ${response.status}).`),
        response.status,
      );
    }
    return data;
  });
}

/**
 * Starts the first frame of one scene (a paid image), and returns at once. `replaceUpload`
 * confirms replacing a frame the user uploaded: it stays among the scene's earlier frames.
 */
export function useGenerateFirstFrame(projectId: number) {
  return useStartMutation(
    projectId,
    async ({ sceneId, replaceUpload }: { sceneId: number; replaceUpload: boolean }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/scenes/{scene_id}/generate-first-frame",
        {
          params: { path: { project_id: projectId, scene_id: sceneId } },
          body: { replace_upload: replaceUpload },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the first frame (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
  );
}

/** Goes back to one of the scene's earlier frames. The answer holds the scenes afterwards. */
export function useSelectFirstFrame(projectId: number) {
  return useSceneInputsMutation(
    projectId,
    async ({ sceneId, assetId }: { sceneId: number; assetId: number }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/scenes/{scene_id}/select-first-frame",
        {
          params: { path: { project_id: projectId, scene_id: sceneId } },
          body: { asset_id: assetId },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not use that frame (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
  );
}
