import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type MusicThemesState = components["schemas"]["MusicThemesState"];
export type MusicThemeEntry = components["schemas"]["MusicThemeOut"];
export type ThemeCandidate = components["schemas"]["ThemeCandidateOut"];
export type ThemeVersion = components["schemas"]["ThemeVersionOut"];
export type ThemeCheck = components["schemas"]["ThemeCheckOut"];

/**
 * Every music theme query of a project starts with this key. It also starts with the project's
 * own key, so a change to the project (or to its Music Bible) refreshes the panel.
 */
export function musicThemesKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "music-themes"] as const;
}

async function fetchMusicThemes(projectId: number) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}/music-themes", {
    params: { path: { project_id: projectId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the music themes (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/**
 * The themes of the newest Music Bible with their candidates and emotional versions. It is loaded
 * again every few seconds while anything is being written or recorded.
 */
export function useMusicThemes(projectId: number) {
  return useQuery({
    queryKey: musicThemesKey(projectId),
    queryFn: () => fetchMusicThemes(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (query) =>
      query.state.data?.themes.some((theme) => theme.active) ? ACTIVE_POLL_MS : false,
  });
}

function useRefreshAfter(projectId: number) {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: musicThemesKey(projectId) }),
      invalidateAfterJobAction(queryClient),
    ]);
}

/**
 * Starts what is missing or out of date for every theme, or for the one `themeId`.
 * `confirmReplaceOwner` is true only after the owner agreed to replace a recording they chose.
 */
export function useRunMusicThemes(projectId: number) {
  const refresh = useRefreshAfter(projectId);
  return useMutation({
    mutationFn: async (input: { themeId?: string; confirmReplaceOwner: boolean }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/music-themes/run",
        {
          params: {
            path: { project_id: projectId },
            query: input.themeId === undefined ? {} : { theme_id: input.themeId },
          },
          body: { confirm_replace_owner: input.confirmReplaceOwner },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the themes (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: refresh,
  });
}

/** Makes a candidate the theme's canonical recording. Its emotional versions are made again. */
export function useChooseThemeCandidate(projectId: number) {
  const refresh = useRefreshAfter(projectId);
  return useMutation({
    mutationFn: async (input: { themeId: string; candidateId: number }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/music-themes/{theme_id}/choose",
        {
          params: { path: { project_id: projectId, theme_id: input.themeId } },
          body: { candidate_id: input.candidateId },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not choose the recording (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: refresh,
  });
}

/** Makes one emotional version again, with a new seed. */
export function useRegenerateThemeVersion(projectId: number) {
  const refresh = useRefreshAfter(projectId);
  return useMutation({
    mutationFn: async (input: { themeId: string; emotion: string }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/music-themes/{theme_id}/versions/{emotion}/regenerate",
        {
          params: {
            path: { project_id: projectId, theme_id: input.themeId, emotion: input.emotion },
          },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not make the version again (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: refresh,
  });
}
