import { api } from "./client";
import { useStartMutation } from "./clips";
import { ApiError, detailMessage } from "./errors";
import type { components } from "./schema";

/** What "Write image prompts" started: one job for each scene that needed a prompt. */
export type WriteImagePromptsResult = components["schemas"]["WriteImagePromptsOut"];

/**
 * Starts an image prompt job (a paid call to the language model) for every scene that needs
 * one, and returns at once. The page follows its progress by itself. After a refusal the page may be
 * showing old data, so the scenes are loaded again.
 */
export function useWriteImagePrompts(projectId: number) {
  return useStartMutation(projectId, async () => {
    const { data, error, response } = await api.POST(
      "/api/projects/{project_id}/write-image-prompts",
      { params: { path: { project_id: projectId } } },
    );
    if (!data) {
      throw new ApiError(
        detailMessage(error, `Could not start the image prompts (HTTP ${response.status}).`),
        response.status,
      );
    }
    return data;
  });
}

/**
 * Starts the image prompt of one scene (a paid call to the language model), and returns at
 * once. `runAgain` asks the model again even if the same request was answered before.
 */
export function useWriteImagePrompt(projectId: number) {
  return useStartMutation(
    projectId,
    async ({ sceneId, runAgain }: { sceneId: number; runAgain: boolean }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/scenes/{scene_id}/write-image-prompt",
        {
          params: { path: { project_id: projectId, scene_id: sceneId } },
          body: { run_again: runAgain },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the image prompt (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
  );
}
