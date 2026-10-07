import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { isValidProjectId, PROJECTS_KEY } from "./projects";
import { scenesKey } from "./scenes";
import type { components } from "./schema";

/** The newest render job of a project and every finished render. */
export type RendersState = components["schemas"]["RendersOut"];
/** One finished render: a final video. */
export type Render = components["schemas"]["RenderOut"];

/** The renders query lives under the project's key, so a job action refreshes it too. */
export function rendersKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "renders"] as const;
}

async function fetchRenders(projectId: number) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}/renders", {
    params: { path: { project_id: projectId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the renders (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/** The newest render job and the finished renders of a project. Reads the database only. */
export function useRenders(projectId: number) {
  return useQuery({
    queryKey: rendersKey(projectId),
    queryFn: () => fetchRenders(projectId),
    enabled: isValidProjectId(projectId),
  });
}

/**
 * Starts a render and returns at once. Progress shows after a Refresh. After a refused start
 * the page may be showing old data (a clip was changed, the scenes went out of date), so the
 * scenes and the renders are loaded again.
 */
export function useStartRender(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST("/api/projects/{project_id}/render", {
        params: { path: { project_id: projectId } },
      });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the render (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    // A start creates a job: the job lists, this project's queries (the renders and the
    // scenes) and the banner's waiting count are all refreshed.
    onSuccess: () => invalidateAfterJobAction(queryClient),
    onError: (error) => {
      if (error instanceof ApiError && (error.status === 404 || error.status === 422)) {
        void queryClient.invalidateQueries({ queryKey: scenesKey(projectId) });
        void queryClient.invalidateQueries({ queryKey: rendersKey(projectId) });
      }
    },
  });
}
