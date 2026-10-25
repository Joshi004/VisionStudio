import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type MusicPlacementState = components["schemas"]["MusicPlacementState"];
export type MusicPlacementOut = components["schemas"]["MusicPlacementOut"];
export type MusicPlacementVersion =
  components["schemas"]["MusicPlacementVersionOut"];
export type MusicPlacementContent =
  components["schemas"]["MusicPlacementContent"];
export type PlacedSound = components["schemas"]["PlacedSoundOut"];
export type PlacementEdge = components["schemas"]["PlacementEdgeOut"];
export type PlacementJoin = components["schemas"]["PlacementJoinOut"];
export type PlacementTimeline = components["schemas"]["PlacementTimelineOut"];

/**
 * Every music placement query of a project starts with this key. It also starts with the
 * project's own key, so saving the project's settings (which refreshes the project) refreshes
 * the panel.
 */
export function musicPlacementKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "music-placement"] as const;
}

async function fetchMusicPlacement(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/music-placement",
    {
      params: { path: { project_id: projectId } },
    },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(
        error,
        `Could not load the music placement (HTTP ${response.status}).`,
      ),
      response.status,
    );
  }
  return data;
}

/**
 * The newest version, the list of versions, the newest job and why it is out of date. It is
 * loaded again every few seconds while the job is waiting or running.
 */
export function useMusicPlacement(projectId: number) {
  return useQuery({
    queryKey: musicPlacementKey(projectId),
    queryFn: () => fetchMusicPlacement(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (query) =>
      isJobActive(query.state.data?.job) ? ACTIVE_POLL_MS : false,
  });
}

async function fetchMusicPlacementVersion(projectId: number, version: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/music-placement/versions/{version}",
    { params: { path: { project_id: projectId, version } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(
        error,
        `Could not load the version (HTTP ${response.status}).`,
      ),
      response.status,
    );
  }
  return data;
}

/** One stored version. Nothing is loaded while `version` is null. */
export function useMusicPlacementVersion(
  projectId: number,
  version: number | null,
) {
  return useQuery({
    queryKey: [...musicPlacementKey(projectId), "version", version],
    queryFn: () => fetchMusicPlacementVersion(projectId, version as number),
    enabled: isValidProjectId(projectId) && version !== null,
  });
}

/** Starts the job that places the music. */
export function useRunMusicPlacement(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/music-placement/run",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(
            error,
            `Could not start the music placement (HTTP ${response.status}).`,
          ),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({
          queryKey: musicPlacementKey(projectId),
        }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}
