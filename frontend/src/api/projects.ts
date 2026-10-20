import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import type { components } from "./schema";

export type ProjectSummary = components["schemas"]["ProjectSummary"];
export type ProjectDetail = components["schemas"]["ProjectDetail"];
export type ProjectCreate = components["schemas"]["ProjectCreate"];
export type ProjectUpdate = components["schemas"]["ProjectUpdate"];

/** What nginx accepts on /api/, before the backend sees the request. */
const NGINX_MAX_MB = 512;

/** Every project query starts with this key. */
export const PROJECTS_KEY = ["projects"] as const;

async function fetchProjects() {
  const { data, response } = await api.GET("/api/projects");
  if (!data) {
    throw new ApiError(`Could not load the projects (HTTP ${response.status}).`, response.status);
  }
  return data;
}

export function useProjects() {
  return useQuery({ queryKey: PROJECTS_KEY, queryFn: fetchProjects });
}

async function fetchProject(projectId: number) {
  const { data, error, response } = await api.GET("/api/projects/{project_id}", {
    params: { path: { project_id: projectId } },
  });
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the project (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

export function isValidProjectId(projectId: number): boolean {
  return Number.isSafeInteger(projectId) && projectId > 0;
}

export function useProject(projectId: number) {
  return useQuery({
    queryKey: [...PROJECTS_KEY, projectId],
    queryFn: () => fetchProject(projectId),
    enabled: isValidProjectId(projectId),
    // A project that does not exist will not appear on a retry.
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status === 404) && failureCount < 1,
  });
}

export function useCreateProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: ProjectCreate) => {
      const { data, error, response } = await api.POST("/api/projects", { body });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not create the project (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PROJECTS_KEY }),
  });
}

/** The settings are saved this way: only changed fields are sent. */
export function useUpdateProject(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: ProjectUpdate) => {
      const { data, error, response } = await api.PATCH("/api/projects/{project_id}", {
        params: { path: { project_id: projectId } },
        body,
      });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not save the project (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PROJECTS_KEY }),
  });
}

/** The error for a failed upload, from the backend's `detail` or nginx's own answer. */
export async function uploadError(response: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // Not JSON, for example nginx's own error page.
  }
  if (response.status === 413 && body === null) {
    return new ApiError(
      `The file is larger than ${NGINX_MAX_MB} MB, the most the server accepts.`,
      413,
    );
  }
  return new ApiError(
    detailMessage(body, `The upload failed (HTTP ${response.status}).`),
    response.status,
  );
}
