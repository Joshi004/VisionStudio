import { api } from "./client";
import { useStartMutation } from "./clips";
import { ApiError, detailMessage } from "./errors";
import { useSceneInputsMutation } from "./sceneInputs";
import type { components } from "./schema";

/** What "Write last frame prompts" started: one job for each scene that needed a prompt. */
export type WriteLastFramePromptsResult = components["schemas"]["WriteLastFramePromptsOut"];
/** What "Generate last frames" started: one job for each scene that needed a frame. */
export type GenerateLastFramesResult = components["schemas"]["GenerateLastFramesOut"];

/**
 * Starts a last frame prompt job (a paid call to the language model) for every scene that needs
 * one, and returns at once. The page follows its progress by itself. After a refusal the page may
 * be showing old data, so the scenes are loaded again.
 */
export function useWriteLastFramePrompts(projectId: number) {
  return useStartMutation(projectId, async () => {
    const { data, error, response } = await api.POST(
      "/api/projects/{project_id}/write-last-frame-prompts",
      { params: { path: { project_id: projectId } } },
    );
    if (!data) {
      throw new ApiError(
        detailMessage(error, `Could not start the last frame prompts (HTTP ${response.status}).`),
        response.status,
      );
    }
    return data;
  });
}

/**
 * Starts the last frame prompt of one scene (a paid call to the language model), and returns at
 * once. `runAgain` asks the model again even if the same request was answered before.
 */
export function useWriteLastFramePrompt(projectId: number) {
  return useStartMutation(
    projectId,
    async ({ sceneId, runAgain }: { sceneId: number; runAgain: boolean }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/scenes/{scene_id}/write-last-frame-prompt",
        {
          params: { path: { project_id: projectId, scene_id: sceneId } },
          body: { run_again: runAgain },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the last frame prompt (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
  );
}

/**
 * Starts a last frame job (an image made on the GPU server by editing the first frame) for every
 * scene that needs one, and returns at once. The page follows its progress by itself.
 */
export function useGenerateLastFrames(projectId: number) {
  return useStartMutation(projectId, async () => {
    const { data, error, response } = await api.POST(
      "/api/projects/{project_id}/generate-last-frames",
      { params: { path: { project_id: projectId } } },
    );
    if (!data) {
      throw new ApiError(
        detailMessage(error, `Could not start the last frames (HTTP ${response.status}).`),
        response.status,
      );
    }
    return data;
  });
}

/**
 * Starts the last frame of one scene (an image made on the GPU server by editing its first
 * frame), and returns at once. `replaceUpload` confirms replacing a frame the user uploaded: it
 * stays among the scene's earlier last frames.
 */
export function useGenerateLastFrame(projectId: number) {
  return useStartMutation(
    projectId,
    async ({ sceneId, replaceUpload }: { sceneId: number; replaceUpload: boolean }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/scenes/{scene_id}/generate-last-frame",
        {
          params: { path: { project_id: projectId, scene_id: sceneId } },
          body: { replace_upload: replaceUpload },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the last frame (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
  );
}

/** Goes back to one of the scene's earlier last frames. The answer holds the scenes afterwards. */
export function useSelectLastFrame(projectId: number) {
  return useSceneInputsMutation(
    projectId,
    async ({ sceneId, assetId }: { sceneId: number; assetId: number }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/scenes/{scene_id}/select-last-frame",
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
