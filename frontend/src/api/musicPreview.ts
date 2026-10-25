import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type MusicPreview = components["schemas"]["MusicPreviewOut"];

/** What a preview is of: a scene or a cue, and for a cue a take to hear instead of the selected one. */
export type MusicPreviewTarget =
  | { sceneId: string; cueId?: undefined; takeId?: undefined }
  | { sceneId?: undefined; cueId: string; takeId?: number };

/** The project's newest music preview. It starts with the project's own key. */
export function musicPreviewKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "music-preview"] as const;
}

async function fetchMusicPreview(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/music-preview",
    { params: { path: { project_id: projectId } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(
        error,
        `Could not load the music preview (HTTP ${response.status}).`,
      ),
      response.status,
    );
  }
  return data.preview;
}

/**
 * The newest preview of the project, whatever it is of (null when there is none). It is loaded
 * again every few seconds while the job is waiting or running.
 */
export function useMusicPreview(projectId: number) {
  return useQuery({
    queryKey: musicPreviewKey(projectId),
    queryFn: () => fetchMusicPreview(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (query) =>
      isJobActive(query.state.data ?? null) ? ACTIVE_POLL_MS : false,
  });
}

/** Whether a preview is of this target. A preview of another target is not shown for it. */
export function isPreviewOf(
  preview: MusicPreview | null | undefined,
  target: MusicPreviewTarget,
): boolean {
  if (!preview) {
    return false;
  }
  return (
    (preview.scene_id ?? null) === (target.sceneId ?? null) &&
    (preview.cue_id ?? null) === (target.cueId ?? null) &&
    (preview.take_id ?? null) === (target.takeId ?? null)
  );
}

/** Starts the job that makes a preview of the target. */
export function useStartMusicPreview(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (target: MusicPreviewTarget) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/music-preview",
        {
          params: { path: { project_id: projectId } },
          body: {
            scene_id: target.sceneId ?? null,
            cue_id: target.cueId ?? null,
            take_id: target.takeId ?? null,
          },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not start the preview (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    // A refusal can mean something changed, so the preview and the jobs are loaded again.
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: musicPreviewKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}
