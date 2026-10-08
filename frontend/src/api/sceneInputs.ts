import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { uploadError } from "./projects";
import { scenesKey, type Scene, type ScenesState } from "./scenes";
import type { components } from "./schema";

/** A scene's first or last frame: the original and how it will be framed. */
export type Frame = components["schemas"]["FrameOut"];
export type FrameSlotName = "first" | "last";
/** What a scene still needs before a clip can be generated. */
export type MissingInput = Scene["missing"][number];

/** The backend's own limits. The server stays the judge; these only avoid a pointless upload. */
export const FRAME_MAX_MB = 40;
export const DESCRIPTION_MAX_CHARS = 4000;

/**
 * Every change to a scene's inputs answers with the scenes as they are afterwards, so the
 * page shows it at once with no Refresh. After a 404 (the scene was merged away by a cut
 * edit, or the generation size changed) the page may be showing old data, so it is loaded
 * again.
 */
export function useSceneInputsMutation<TVariables>(
  projectId: number,
  mutationFn: (variables: TVariables) => Promise<ScenesState>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: (data) => queryClient.setQueryData(scenesKey(projectId), data),
    onError: (error) => {
      if (error instanceof ApiError && error.status === 404) {
        void queryClient.invalidateQueries({ queryKey: scenesKey(projectId) });
      }
    },
  });
}

/** The texts of a scene: the description (the video prompt) and the two frame descriptions. */
export type SceneTexts = {
  scene_description?: string;
  first_frame_description?: string;
  last_frame_description?: string;
};

/**
 * Saves the texts that are sent, and only those. Blank clears one. A text that is saved
 * becomes the user's own: a later AI draft never overwrites it.
 */
export function useSaveSceneTexts(projectId: number) {
  return useSceneInputsMutation(
    projectId,
    async ({ sceneId, texts }: { sceneId: number; texts: SceneTexts }) => {
      const { data, error, response } = await api.PATCH(
        "/api/projects/{project_id}/scenes/{scene_id}",
        {
          params: { path: { project_id: projectId, scene_id: sceneId } },
          body: texts,
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not save the text (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
  );
}

/**
 * Sends the image itself as the request body, as the voiceover is sent. The server decides
 * what the file is from its content, so the content type is always application/octet-stream.
 */
export function useUploadFrame(projectId: number) {
  return useSceneInputsMutation(
    projectId,
    async ({ sceneId, slot, file }: { sceneId: number; slot: FrameSlotName; file: File }) => {
      if (file.size > FRAME_MAX_MB * 1024 * 1024) {
        throw new ApiError(`The file is larger than ${FRAME_MAX_MB} MB.`, 413);
      }
      const response = await fetch(
        `/api/projects/${projectId}/scenes/${sceneId}/frames/${slot}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/octet-stream" },
          body: file,
        },
      );
      if (!response.ok) {
        throw await uploadError(response);
      }
      return (await response.json()) as ScenesState;
    },
  );
}

/** Clears a frame from the scene. The file stays on the server. */
export function useRemoveFrame(projectId: number) {
  return useSceneInputsMutation(
    projectId,
    async ({ sceneId, slot }: { sceneId: number; slot: FrameSlotName }) => {
      const { data, error, response } = await api.DELETE(
        "/api/projects/{project_id}/scenes/{scene_id}/frames/{slot}",
        { params: { path: { project_id: projectId, scene_id: sceneId, slot } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not remove the frame (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
  );
}
