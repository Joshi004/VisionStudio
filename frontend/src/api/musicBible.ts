import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId, refreshProject } from "./projects";
import type { components } from "./schema";

export type MusicBibleState = components["schemas"]["MusicBibleState"];
export type MusicBibleOut = components["schemas"]["MusicBibleOut"];
export type MusicBibleInput = components["schemas"]["MusicBibleSaveIn"];
export type MusicBibleVersion = components["schemas"]["MusicBibleVersionOut"];
export type MusicDirection = components["schemas"]["DirectionOut"];
export type MusicTheme = components["schemas"]["ThemeOut"];

/**
 * Every Music Bible query of a project starts with this key. It also starts with the project's
 * own key, so saving the project's settings (which refreshes the project) refreshes the panel.
 */
export function musicBibleKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "music-bible"] as const;
}

async function fetchMusicBible(projectId: number) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}/music-bible", {
    params: { path: { project_id: projectId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the Music Bible (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/**
 * The newest version, the list of versions, the newest job, why it is out of date and what the
 * editor offers. It is loaded again every few seconds while the job is waiting or running.
 */
export function useMusicBible(projectId: number) {
  return useQuery({
    queryKey: musicBibleKey(projectId),
    queryFn: () => fetchMusicBible(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (query) => (isJobActive(query.state.data?.job) ? ACTIVE_POLL_MS : false),
  });
}

async function fetchMusicBibleVersion(projectId: number, version: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/music-bible/versions/{version}",
    { params: { path: { project_id: projectId, version } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the version (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/** One stored version. Nothing is loaded while `version` is null. */
export function useMusicBibleVersion(projectId: number, version: number | null) {
  return useQuery({
    queryKey: [...musicBibleKey(projectId), "version", version],
    queryFn: () => fetchMusicBibleVersion(projectId, version as number),
    enabled: isValidProjectId(projectId) && version !== null,
  });
}

/**
 * Starts the job that writes the four directions, the choice and the Bible.
 * `confirmReplaceManual` is true only after the owner agreed to add a version from the model on
 * top of one they wrote or chose.
 */
export function useRunMusicBible(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { confirmReplaceManual: boolean }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/music-bible/run",
        {
          params: { path: { project_id: projectId } },
          body: { confirm_replace_manual: input.confirmReplaceManual },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the Music Bible (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: musicBibleKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/**
 * Starts the job that writes the Bible again from the direction the owner chose among the four
 * of an earlier version. The directions are not written again.
 */
export function useChooseMusicDirection(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { version: number; directionId: string }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/music-bible/choose",
        {
          params: { path: { project_id: projectId } },
          body: { version: input.version, direction_id: input.directionId },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not choose the direction (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: musicBibleKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}

/** Saves the edited Music Bible as the next version, written by the owner. */
export function useSaveMusicBible(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (content: MusicBibleInput) => {
      const { data, error, response } = await api.PUT("/api/projects/{project_id}/music-bible", {
        params: { path: { project_id: projectId } },
        body: content,
      });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not save the Music Bible (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => refreshProject(queryClient, projectId),
  });
}
