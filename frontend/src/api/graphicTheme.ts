import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";

export type GraphicThemeState = components["schemas"]["GraphicThemeState"];
export type GraphicThemeOut = components["schemas"]["GraphicThemeOut"];
export type GraphicThemeVersion = components["schemas"]["GraphicThemeVersionOut"];
export type GraphicThemeColours = components["schemas"]["GraphicThemeColoursOut"];

/**
 * Every graphics theme query of a project starts with this key. It also starts with the project's
 * own key, so saving the project's settings (which refreshes the project) refreshes the panel.
 */
export function graphicThemeKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "graphic-theme"] as const;
}

async function fetchGraphicTheme(projectId: number) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}/graphic-theme", {
    params: { path: { project_id: projectId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the graphics look (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/**
 * The newest version, the list of versions, the newest job and why it is out of date. It is
 * loaded again every few seconds while the job is waiting or running.
 */
export function useGraphicTheme(projectId: number) {
  return useQuery({
    queryKey: graphicThemeKey(projectId),
    queryFn: () => fetchGraphicTheme(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (query) => (isJobActive(query.state.data?.job) ? ACTIVE_POLL_MS : false),
  });
}

async function fetchGraphicThemeVersion(projectId: number, version: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/graphic-theme/versions/{version}",
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
export function useGraphicThemeVersion(projectId: number, version: number | null) {
  return useQuery({
    queryKey: [...graphicThemeKey(projectId), "version", version],
    queryFn: () => fetchGraphicThemeVersion(projectId, version as number),
    enabled: isValidProjectId(projectId) && version !== null,
  });
}

/**
 * Starts the job that writes the theme. `feedback` is the owner's note on the newest version;
 * leave it out for a plain run.
 */
export function useRunGraphicTheme(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { feedback?: string }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/graphic-theme/run",
        {
          params: { path: { project_id: projectId } },
          body: { feedback: input.feedback ?? null },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the graphics look (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: graphicThemeKey(projectId) }),
        invalidateAfterJobAction(queryClient),
      ]),
  });
}
